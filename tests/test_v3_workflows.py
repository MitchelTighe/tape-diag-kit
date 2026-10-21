"""Exercise every terminal workflow branch without devices or external commands."""
import copy
import io
import json
import subprocess

import pytest
from jsonschema import Draft202012Validator

from tapediag.cli import main
from tapediag.safety import Runner, CommandResult, validate_command
from tapediag.workflows import CATALOG, choose_workflow, decide, run_workflow, workflow_plan
from tapediag.validation import report_schema, validate_report
from tapediag.tapealert import parse_tapealert
from tapediag.parsers import parse_library
from test_v3_scoring import alerts, set_param


@pytest.fixture
def evidence(fixtures):
    return json.loads((fixtures/'fleets/synth-alpha-20261018.json').read_text())


@pytest.mark.parametrize('name',list(CATALOG))
def test_all_workflow_plans_are_valid_dry_runs(name,monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('dry run executed'))
    v=run_workflow(name,[] if name=='inventory-audit' else ['/dev/sg9'],['/dev/sg20'])
    Draft202012Validator(report_schema('3.0')).validate(v)
    assert validate_report(v) is v
    assert v['mode']=='dry-run' and not v['complete'] and not v['decisions']
    assert all(s['status']=='planned' and not s['results'] for s in v['steps'])
    for step in v['steps']:
        for argv in step['argv']:assert validate_command(argv)==argv
    assert not any(a[0] in ('itdt','sg_read_buffer','sg_raw') for s in v['steps'] for a in s['argv'])


@pytest.mark.parametrize('name',list(CATALOG))
def test_all_workflows_with_saved_evidence(name,evidence,monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('offline workflow executed'))
    v=run_workflow(name,report=evidence)
    assert v['complete'] and v['mode']=='offline' and v['decisions']
    assert all(d['path'] and d['next_steps'] for d in v['decisions'])


@pytest.mark.parametrize('name,change,outcome',[
    ('identify',lambda d:d.update(inquiry=None,drive_status=None),'identity-missing'),
    ('identify',lambda d:None,'mapping-missing'),
    ('firmware',lambda d:d['inquiry'].update(revision=None),'revision-missing'),
    ('firmware',lambda d:None,'revision-observed'),
    ('tapealert',lambda d:alerts(d,3),'alerts-active'),
    ('tapealert',lambda d:alerts(d),'alerts-clear'),
    ('tapealert',lambda d:d.update(tapealert=None),'alerts-unknown'),
    ('cleaning',lambda d:alerts(d,20),'cleaning-requested'),
    ('cleaning',lambda d:set_param(d,'0x0c','Cleaning required',1),'cleaning-requested'),
    ('cleaning',lambda d:set_param(d,'0x14','Hours since last cleaning',100),'cleaning-age-review'),
    ('cleaning',lambda d:None,'cleaning-clear'),
    ('cleaning',lambda d:set_param(d,'0x14','Hours since last cleaning',None),'cleaning-unknown'),
    ('cleaning',lambda d:set_param(d,'0x0c','Cleaning required',None),'cleaning-unknown'),
    ('mam',lambda d:d.update(mam=None),'mam-absent'),
    ('mam',lambda d:d['mam']['attributes'][0].update(value=None),'mam-partial'),
    ('mam',lambda d:None,'mam-read'),
    ('dump-plan',lambda d:None,'capture-plan'),
    ('wont-load',lambda d:alerts(d,4),'critical-alert'),
    ('wont-load',lambda d:alerts(d,21),'cleaning-requested'),
    ('wont-load',lambda d:d['drive_status'].update(ready=None),'readiness-unknown'),
    ('wont-load',lambda d:d['drive_status'].update(ready=True),'ready-review'),
    ('wont-load',lambda d:d['drive_status'].update(ready=False),'not-ready-review'),
    ('slow-drive',lambda d:alerts(d,4),'critical-alert'),
    ('slow-drive',lambda d:alerts(d,21),'cleaning-requested'),
    ('slow-drive',lambda d:set_param(d,'0x03','Total uncorrected errors',1),'error-review'),
    ('slow-drive',lambda d:set_param(d,'0x02','Total uncorrected errors',None),'performance-unknown'),
    ('slow-drive',lambda d:d['health'].update(reasons=[{'id':'mam-loads'}]),'lifetime-review'),
    ('slow-drive',lambda d:None,'streaming-review'),
    ('slow-drive',lambda d:d.update(tapealert=None),'alerts-unknown'),
    ('wont-load',lambda d:d.update(tapealert=None),'alerts-unknown'),
])
def test_every_drive_terminal_branch(name,change,outcome,evidence):
    d=evidence['drives'][0];change(d)
    assert decide(name,d)['outcome']==outcome


def test_identified_and_library_identity_from_inventory(evidence):
    assert decide('identify',evidence['drives'][0],evidence['inventory'])['outcome']=='identified'
    assert decide('identify',evidence['libraries'][0],evidence['inventory'])['outcome']=='identified'
    assert decide('firmware',evidence['libraries'][0],evidence['inventory'])['outcome']=='revision-observed'


@pytest.mark.parametrize('status,outcome',[
    (None,'inventory-missing'),
    ('Storage Changer /dev/sg20:0 Drives, 1 Slots\nStorage Element 1:Empty','inventory-consistent'),
    ('Storage Changer /dev/sg20:0 Drives, 2 Slots\nStorage Element 1:Empty','inventory-review'),
])
def test_every_inventory_branch(status,outcome):
    asset={'device':'/dev/sg20','status':parse_library(status) if status else None}
    assert decide('inventory-audit',asset)['outcome']==outcome


@pytest.mark.parametrize('required,outcome',[(True,'cleaning-requested'),(False,'cleaning-clear')])
def test_cleaning_decoded_text_branches(required,outcome,evidence):
    d=evidence['drives'][0]
    p=next(p for p in d['logpages']['pages'] if p['page']=='0x0c')
    p['parameters']=[]
    p['raw_lines']=['Cleaning action required' if required else 'Cleaning action not required (or completed)']
    assert decide('cleaning',d)['outcome']==outcome


@pytest.mark.parametrize('selection',range(1,10))
def test_menu_each_selection(selection):
    stream=io.StringIO()
    assert choose_workflow(lambda:str(selection),stream)==list(CATALOG)[selection-1]
    assert all(name in stream.getvalue() for name in CATALOG)


@pytest.mark.parametrize('selection',['q','Q','0','10','erase','', '-1'])
def test_menu_cancellation_and_bad_selection(selection):
    with pytest.raises(ValueError):choose_workflow(lambda:selection,io.StringIO())


@pytest.mark.parametrize('kwargs',[
    {'execute':True}, {'execute':True,'drives':['/dev/sg9']},
    {'execute':True,'confirmed':True}, {'drives':['/dev/st0']},
])
def test_invalid_live_workflow_never_runs(kwargs,monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('invalid request executed'))
    with pytest.raises(ValueError):run_workflow('identify',**kwargs)


class WorkflowRunner(Runner):
    def __init__(self,fixtures,fail=False):
        super().__init__(True);self.fixtures=fixtures;self.fail=fail
    def run(self,argv):
        validate_command(argv)
        mapping={'lsscsi':'inventory.txt','sg_map':'topology.txt','sg_inq':'inquiry-vpd.txt','mtx':'library.txt','sg_read_attr':'mam.txt'}
        if argv[0]=='sg_turs':text=''
        elif argv[0]=='sg_logs':text=(self.fixtures/'synthetic'/('tapealert-clear.txt' if argv[2].endswith('2e') else 'logpages.txt')).read_text()
        elif argv[0]=='mtx' and argv[-1]=='inquiry':text='Vendor identification: SYNTH\nProduct identification: Mid-size 48-slot library\nRevision: S001\n'
        else:text=(self.fixtures/'synthetic'/mapping[argv[0]]).read_text()
        if argv[0]=='sg_read_attr':
            from tapediag.observations import parse_mam
            code=argv[2].split('=')[1]
            text='\n'.join(a['name']+': '+str(a['value']) for a in parse_mam(text)['attributes'] if a['id']==code)
        r=CommandResult(argv,returncode=2 if self.fail else 0,stdout='' if self.fail else text,error='synthetic failure' if self.fail else None)
        self.results.append(r);return r


@pytest.mark.parametrize('name',list(CATALOG))
def test_each_workflow_live_orchestration_mocked(name,fixtures):
    runner=WorkflowRunner(fixtures)
    v=run_workflow(name,[] if name=='inventory-audit' else ['/dev/sg9'],['/dev/sg10'],True,True,True,runner=runner)
    assert v['complete'] and v['mode']=='execute' and v['decisions']
    assert all(s['status'] in ('pass','warn') for s in v['steps'])
    assert validate_report(v) is v


def test_live_skip_mam_failure_and_runner_mode(fixtures):
    runner=WorkflowRunner(fixtures)
    v=run_workflow('mam',['/dev/sg9'],execute=True,confirmed=True,runner=runner)
    assert v['steps'][-1]['status']=='skipped' and v['decisions'][0]['outcome']=='mam-absent'
    assert not any(r.argv[0]=='sg_read_attr' for r in runner.results)
    v=run_workflow('identify',['/dev/sg9'],execute=True,confirmed=True,runner=WorkflowRunner(fixtures,True))
    assert all(s['status']=='fail' for s in v['steps']) and v['decisions'][0]['outcome']=='identity-missing'
    with pytest.raises(ValueError,match='runner mode'):run_workflow('identify',['/dev/sg9'],execute=True,confirmed=True,runner=Runner())


def test_saved_selection_filters_and_absent_device_rejected(evidence):
    v=run_workflow('firmware',['/dev/sg9'],report=evidence)
    assert len(v['decisions'])==1
    with pytest.raises(ValueError,match='absent'):run_workflow('identify',['/dev/sg99'],report=evidence)
    with pytest.raises(ValueError,match='cannot execute'):run_workflow('identify',execute=True,report=evidence)
    with pytest.raises(ValueError,match='uses --changer'):run_workflow('inventory-audit',['/dev/sg9'])
    with pytest.raises(ValueError,match='unknown workflow'):workflow_plan('erase')
    with pytest.raises(ValueError,match='unknown workflow'):decide('erase',evidence['drives'][0])


def test_no_assets_is_explicit(evidence):
    evidence['drives']=[];evidence['health']['assets']=1;evidence['health']['score']=100
    v=run_workflow('wont-load',report=evidence)
    assert not v['decisions'] and 'No applicable assets' in v['limitations'][-1]


@pytest.mark.parametrize('args',[
    ['guided','--workflow','identify','--state-file','state.json'],
    ['guided','--workflow','identify','--resume'],
    ['guided','--workflow','identify','--dry-run','--execute'],
    ['guided','--from-report','unused.json'],
    ['guided','--menu','--workflow','identify'],
    ['guided','--menu'],
])
def test_named_cli_invalid_modes(args,capsys):
    assert main(args)==2
    assert json.loads(capsys.readouterr().err)['error']


def test_named_cli_offline_and_replay(fixtures,tmp_path,capsys):
    path=fixtures/'fleets/synth-alpha-20261018.json'
    assert main(['guided','--workflow','slow-drive','--from-report',str(path)])==0
    v=json.loads(capsys.readouterr().out)
    assert v['schema_version']=='3.0' and v['decisions'][0]['outcome']=='streaming-review'
    saved=tmp_path/'workflow.json';saved.write_text(json.dumps(v))
    assert main(['guided','--from-file',str(saved)])==0
    assert json.loads(capsys.readouterr().out)==v


def test_headerless_guided_log_pages_use_explicit_command_hint():
    from tapediag.guided import interpret
    step=next(s for s in workflow_plan('slow-drive',['/dev/sg9']) if s['kind']=='logpages')
    step['results']=[CommandResult(['sg_logs','--readonly','--page=0x14','/dev/sg9'],returncode=0,
        stdout='Device statistics (ssc-3 and adc)\n  Lifetime media motion (head) hours: 22000\n').to_dict()]
    interpret(step)
    assert step['data']['pages'][0]['page']=='0x14'
    assert step['data']['pages'][0]['parameters'][0]['value']==22000


def test_live_readiness_fail_and_changer_identity_gap(fixtures):
    runner=WorkflowRunner(fixtures,True)
    value=run_workflow('wont-load',['/dev/sg9'],execute=True,confirmed=True,runner=runner)
    step=next(s for s in value['steps'] if s['kind']=='readiness')
    assert step['status']=='fail' and step['data']['ready'] is False
    value=run_workflow('firmware',changers=['/dev/sg10'],execute=True,confirmed=True,runner=WorkflowRunner(fixtures,True))
    step=next(s for s in value['steps'] if s['kind']=='library-inquiry')
    assert step['status']=='fail' and value['decisions'][0]['outcome']=='revision-missing'


def test_named_workflow_evidence_cannot_be_guided_transcript():
    from tapediag.guided import run_guided
    with pytest.raises(ValueError,match='must be a report'):run_workflow('identify',report=run_guided())


def test_menu_cli_selects_without_executing(monkeypatch,capsys):
    import sys
    monkeypatch.setattr(sys.stdin,'isatty',lambda:True)
    monkeypatch.setattr('tapediag.workflows.choose_workflow',lambda:'dump-plan')
    assert main(['guided','--menu','--drive','/dev/sg9'])==0
    value=json.loads(capsys.readouterr().out)
    assert value['workflow']=='dump-plan' and value['mode']=='dry-run'


def test_unknown_cleaning_age_with_unknown_request_and_raw_in_progress(evidence):
    d=evidence['drives'][0]
    page=next(p for p in d['logpages']['pages'] if p['page']=='0x0c')
    page['parameters']=[];page['raw_lines']=['Cleaning action required (or in progress)']
    assert decide('cleaning',d)['outcome']=='cleaning-requested'


def test_named_collection_failure_exit_code(monkeypatch,capsys,fixtures):
    import tapediag.workflows
    original=tapediag.workflows.run_workflow
    monkeypatch.setattr(tapediag.workflows,'run_workflow',lambda *a,**k:original(*a,**dict(k,runner=WorkflowRunner(fixtures,True))))
    assert main(['guided','--workflow','identify','--drive','/dev/sg9','--execute','--i-understand-read-only'])==1
    value=json.loads(capsys.readouterr().out)
    assert any(s['status']=='fail' for s in value['steps'])
