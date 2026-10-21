"""Migration, validation, fleet comparisons, and public CLI contract."""
import copy
import csv
import hashlib
import base64
import io
import json
import re
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from tapediag.cli import main
from tapediag.dashboard import render_dashboard
from tapediag.fleet import csv_text, diff_reports
from tapediag.v3 import migrate, refresh, timestamp
from tapediag.validation import report_schema, validate_report
from tapediag.guided import run_guided
from test_v3_scoring import alerts, set_param


@pytest.fixture
def v3(fixtures):
    return json.loads((fixtures/'fleets/synth-alpha-20261018.json').read_text())


@pytest.mark.parametrize('filename',sorted(p.name for p in (Path(__file__).resolve().parents[1]/'fixtures/fleets').glob('*.json')))
def test_every_fleet_structural_and_semantic_validation(filename,fixtures):
    value=json.loads((fixtures/'fleets'/filename).read_text())
    Draft202012Validator(report_schema('3.0'),format_checker=FormatChecker()).validate(value)
    assert validate_report(value) is value
    assert len(value['drives'])==3 and len(value['libraries'])==1
    library=value['libraries'][0]['status']
    assert library['reported_slots']==48 and library['reported_drives']==3


def test_v3_schema_is_valid_and_package_copy_matches(fixtures):
    root=fixtures.parent
    Draft202012Validator.check_schema(report_schema('3.0'))
    assert (root/'schema/tapediag-report.v3.json').read_bytes()==(root/'tapediag/report_schema_v3.json').read_bytes()


@pytest.mark.parametrize('version,fixture',[
    ('1.0','golden/v1-original-report.json'),('2.0','golden/scenario-healthy.json'),
    ('2.0','golden/scenario-cleaning-needed.json'),('2.0','golden/scenario-degraded-media.json'),
])
def test_migration_is_lossless_for_source_observations_and_nonmutating(version,fixture,fixtures):
    old=json.loads((fixtures/fixture).read_text());before=copy.deepcopy(old)
    v=migrate(old,'SYNTH-MIGRATION','2026-10-17T08:00:00-04:00')
    assert old==before and v is not old
    assert v['schema_version']=='3.0' and v['captured_at']=='2026-10-17T12:00:00Z'
    assert v['migration']['from_version']==version
    assert v['migration']['original_tool_version']==old['tool_version']
    for key in ('commands','errors','inventory','ltfs','itdt'):assert v[key]==old[key]
    for i,d in enumerate(old['drives']):
        for key,val in d.items():assert v['drives'][i][key]==val
    for i,d in enumerate(old['libraries']):
        for key,val in d.items():assert v['libraries'][i][key]==val
    assert validate_report(v) is v
    Draft202012Validator(report_schema('3.0')).validate(v)


def test_migration_missing_time_identity_fallback_and_idempotence(fixtures,v3):
    old=json.loads((fixtures/'golden/scenario-healthy.json').read_text())
    old['drives'][0]['inquiry']['serial']='SYNTH-REDACTED-DRIVE-SERIAL'
    v=migrate(old)
    assert v['captured_at'] is None and v['fleet_id']=='SYNTH-UNASSIGNED'
    assert v['drives'][0]['identity_basis']=='device-path'
    assert v['drives'][0]['asset_id']=='drive:/dev/sg9'
    assert migrate(v)==v and migrate(v) is not v
    assert migrate(v3)==v3
    with pytest.raises(ValueError,match='cannot override'):migrate(v3,fleet_id='SYNTH-OTHER')
    with pytest.raises(ValueError,match='guided'):migrate(run_guided())


@pytest.mark.parametrize('value',['2026-10-18','2026-10-18T12:00:00','2026-02-30T12:00:00Z','2026-10-18 12:00:00Z','invalid',123,True])
def test_bad_timestamps(value):
    with pytest.raises(ValueError):timestamp(value)


def test_timestamp_normalization():
    assert timestamp(None) is None
    assert timestamp('2026-10-18T08:00:00-04:00')=='2026-10-18T12:00:00Z'


@pytest.mark.parametrize('change',[
    lambda v:v.update(secret='extra'),lambda v:v.pop('migration'),
    lambda v:v.update(fleet_id=''),lambda v:v.update(fleet_id='S'*101),
    lambda v:v.update(captured_at='2026-10-18'),
    lambda v:v['drives'][0]['health'].update(score=101),
    lambda v:v['drives'][0]['health'].update(grade='G'),
    lambda v:v['drives'][0]['health'].update(model='arbitrary'),
    lambda v:v['libraries'][0].update(identity_basis='guessed'),
])
def test_malformed_v3_rejected_by_independent_and_internal(change,v3):
    change(v3)
    assert list(Draft202012Validator(report_schema('3.0'),format_checker=FormatChecker()).iter_errors(v3))
    with pytest.raises(ValueError):validate_report(v3)


@pytest.mark.parametrize('change',[
    lambda v:v['drives'][0]['health'].update(score=75,grade='B'),
    lambda v:v['drives'][0]['health'].update(assessment='attention'),
    lambda v:v['health'].update(score=50),
    lambda v:v['drives'].append(copy.deepcopy(v['drives'][0])),
    lambda v:v['drives'][1].update(asset_id=v['drives'][0]['asset_id']),
    lambda v:v['drives'][1].update(device=v['drives'][0]['device']),
    lambda v:v['drives'][0].update(device='/dev/st0'),
    lambda v:v['drives'][0]['tapealert']['inactive_flags'].pop(),
])
def test_semantic_inconsistency_rejected(change,v3):
    change(v3)
    with pytest.raises(ValueError):validate_report(v3)


def test_flag_severity_cannot_forge_health(v3):
    d=v3['drives'][0];alerts(d,3)
    d['tapealert']['active_flags'][0]['severity']='Info'
    with pytest.raises(ValueError,match='catalog'):refresh(v3)


def test_empty_report_has_no_numeric_fleet_score(v3):
    v3['drives']=[];v3['libraries']=[]
    refresh(v3)
    assert v3['health']['score'] is None and v3['health']['assets']==0


def test_watch_regressions_and_no_input_mutation(v3):
    before=copy.deepcopy(v3);v3['captured_at']='2026-10-19T12:00:00Z'
    d=v3['drives'][0];alerts(d,3);set_param(d,'0x03','Total uncorrected errors',1);d['mam']=None
    refresh(v3);original=copy.deepcopy(v3)
    diff=diff_reports(before,v3)
    assert diff['regressions']==4
    assert {e['kind'] for e in diff['events']}=={'score','coverage','new-alert','counter-increase'}
    assert v3==original


def test_watch_counter_reset_improvement_new_and_missing_assets(v3):
    before=copy.deepcopy(v3);set_param(before['drives'][0],'0x02','Total uncorrected errors',4);refresh(before)
    v3['captured_at']='2026-10-19T12:00:00Z'
    v3['drives'].pop()
    new=copy.deepcopy(v3['drives'][0]);new.update(device='/dev/sg99',asset_id='SYNTH-NEW');v3['drives'].append(new);refresh(v3)
    diff=diff_reports(before,v3)
    assert {'score','counter-reset','missing-asset','new-asset'}=={e['kind'] for e in diff['events']}
    assert diff['regressions']==1
    assert any('device-path identity' in n for n in diff['notes'])


def test_watch_missing_time_order_and_fleet_mismatch(v3):
    other=copy.deepcopy(v3)
    with pytest.raises(ValueError,match='later'):diff_reports(v3,other)
    other['fleet_id']='SYNTH-OTHER'
    with pytest.raises(ValueError,match='matching'):diff_reports(v3,other)
    other['fleet_id']=v3['fleet_id'];other['captured_at']=None
    assert diff_reports(v3,other)['regressions']==0
    assert 'caller order' in diff_reports(v3,other)['notes'][0]


def test_csv_export_fields_and_formula_injection(v3):
    v3['fleet_id']='=SYNTH-TEST'
    v3['drives'][0]['inquiry']['product']='@SYNTH-model, with comma\nand newline'
    rows=list(csv.DictReader(io.StringIO(csv_text([v3]))))
    assert len(rows)==4 and rows[0]['score']=='100' and rows[0]['model']=='triage-v3.0.0'
    assert rows[0]['fleet_id']=="'=SYNTH-TEST" and rows[0]['product'].startswith("'@SYNTH")
    assert 'comma\nand newline' in rows[0]['product']


@pytest.mark.parametrize('prefix',['=','+','-','@','\t','\r','\n','  ='])
def test_csv_formula_prefixes(prefix,v3):
    v3['fleet_id']=prefix+'SYNTH-TEST'
    row=next(csv.DictReader(io.StringIO(csv_text([v3]))))
    assert row['fleet_id'].startswith("'")


def test_dashboard_escaping_csp_hash_and_placeholders(v3):
    v3['drives'][0]['inquiry']['product']='</script><img src=x onerror=alert(1)>__SCHEMA____SCRIPT_HASH__'
    html=render_dashboard([v3])
    assert '<img src=x' not in html and '\\u003c/script\\u003e' in html
    seed=html.split('<script id="seed" type="application/json">')[1].split('</script>')[0]
    assert json.loads(seed)[0]==v3
    script=html.split('<script id="application">')[1].split('</script>')[0]
    digest=base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert "script-src 'sha256-"+digest+"'" in html
    assert "connect-src 'none'" in html and '@media print' in html
    assert 'fetch(' not in html and 'innerHTML' not in script


def test_dashboard_cli_accepts_legacy_and_empty(fixtures,tmp_path,capsys):
    target=tmp_path/'dashboard.html'
    assert main(['dashboard',str(fixtures/'golden/scenario-healthy.json'),'--output',str(target)])==0
    assert json.loads(capsys.readouterr().out)['reports']==1
    assert '"schema_version": "3.0"' in target.read_text()
    assert main(['dashboard','--output',str(target)])==0
    capsys.readouterr()
    assert '>[]</script>' in target.read_text()


def test_migrate_validate_report_csv_and_watch_cli(fixtures,tmp_path,capsys):
    old=fixtures/'golden/scenario-healthy.json';out=tmp_path/'migrated.json'
    assert main(['migrate','--from-file',str(old),'--fleet-id','SYNTH-CLI'])==0
    v=json.loads(capsys.readouterr().out);out.write_text(json.dumps(v))
    assert main(['validate','--from-file',str(out)])==0
    assert json.loads(capsys.readouterr().out)['valid'] is True
    assert main(['report','--from-file',str(out)])==0
    assert json.loads(capsys.readouterr().out)==v
    assert main(['export-csv',str(out)])==0
    assert 'fleet_id,captured_at,kind' in capsys.readouterr().out
    csvpath=tmp_path/'fleet.csv';assert main(['export-csv',str(out),'--output',str(csvpath)])==0
    assert len(list(csv.DictReader(csvpath.open())))==2
    capsys.readouterr()
    assert main(['watch',str(out),str(out)])==0
    assert json.loads(capsys.readouterr().out)['regressions']==0


def test_watch_cli_regression_exit_code(fixtures,capsys):
    assert main(['watch',str(fixtures/'fleets/synth-bravo-20261016.json'),str(fixtures/'fleets/synth-bravo-20261018.json')])==1
    assert json.loads(capsys.readouterr().out)['regressions']>0


def test_v3_default_writer_and_legacy_v2_option(fixtures,capsys):
    assert main(['report','--from-dir',str(fixtures/'scenarios/healthy'),'--fleet-id','SYNTH-CLI','--captured-at','2026-10-18T12:00:00Z'])==0
    v=json.loads(capsys.readouterr().out)
    assert v['schema_version']=='3.0' and v['captured_at']=='2026-10-18T12:00:00Z'
    assert main(['report','--schema-version','2.0','--from-dir',str(fixtures/'scenarios/healthy')])==0
    assert json.loads(capsys.readouterr().out)['schema_version']=='2.0'


@pytest.mark.parametrize('args',[
    ['--execute','validate','--from-file','unused.json'],
    ['--execute','migrate','--from-file','unused.json'],
    ['--execute','dashboard','--output','unused.html'],
    ['--execute','watch','unused.json','unused.json'],
    ['--execute','export-csv','unused.json'],
])
def test_offline_v3_commands_refuse_execute(args,capsys,monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('offline command executed'))
    assert main(args)==2
    assert 'offline only' in capsys.readouterr().err


def test_watch_fractional_timestamp_order(v3):
    after=copy.deepcopy(v3);after['captured_at']='2026-10-18T12:00:00.100000Z'
    assert diff_reports(v3,after)['regressions']==0
    with pytest.raises(ValueError,match='later'):diff_reports(after,v3)


def test_empty_fleet_identity_refused_on_migration(fixtures):
    old=json.loads((fixtures/'golden/scenario-healthy.json').read_text())
    with pytest.raises(ValueError):migrate(old,fleet_id='')


@pytest.mark.parametrize('args',[
    ['report','--schema-version','2.0','--fleet-id','SYNTH-TEST'],
    ['report','--from-file','unused.json','--captured-at','2026-10-18T12:00:00Z'],
])
def test_metadata_cannot_be_silently_ignored(args,capsys):
    assert main(args)==2
    assert 'identity/time metadata' in capsys.readouterr().err


def test_workflow_saved_argv_is_allowlist_checked():
    from tapediag.workflows import run_workflow
    v=run_workflow('dump-plan',['/dev/sg9'])
    v['steps'][0]['argv']=[['sg_raw','/dev/sg9','0a','00']]
    with pytest.raises(ValueError,match='allowlist'):validate_report(v)


def test_workflow_json_is_not_a_dashboard_input():
    from tapediag.workflows import run_workflow
    with pytest.raises(ValueError):render_dashboard([run_workflow('identify')])
