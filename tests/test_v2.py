"""Independent v2 expectations: public-format synthetic observations only."""
import copy
import json
from pathlib import Path
import subprocess

import pytest
from jsonschema import Draft202012Validator

from tapediag.cli import main
from tapediag.guided import run_guided, plan, NOT_PERFORMED
from tapediag.health import summarize, RULES
from tapediag.html_report import render_html
from tapediag.observations import (parse_mam, parse_inquiry, parse_topology, library_checks,
                                  tapealert_response, DENSITIES)
from tapediag.parsers import parse_logpages, parse_drive_status, parse_library
from tapediag.report import offline_report
from tapediag.safety import (Runner, CommandResult, SafetyError, validate_command,
                            mam_commands, inquiry_commands)
from tapediag.v2 import enrich
from tapediag.validation import validate_report, report_schema


def scenario(fixtures, name='healthy'):
    path = fixtures / 'scenarios' / name
    return enrich(offline_report(path), directory=path)


def test_v2_schema_copy_and_valid_scenarios(fixtures):
    root = fixtures.parent
    assert (root/'schema/tapediag-report.v2.json').read_bytes() == (root/'tapediag/report_schema_v2.json').read_bytes()
    schema = report_schema('2.0')
    Draft202012Validator.check_schema(schema)
    for name in ('healthy','cleaning-needed','degraded-media'):
        value = scenario(fixtures,name)
        assert validate_report(value) == value
        Draft202012Validator(schema).validate(value)
        assert value == json.loads((fixtures/'golden'/('scenario-'+name+'.json')).read_text())


@pytest.mark.parametrize('version,path', [('1.0','golden/sample-host.report.json'),('2.0','golden/scenario-healthy.json')])
def test_saved_schema_backward_compatibility(version,path,fixtures,tmp_path,capsys):
    value=json.loads((fixtures/path).read_text())
    assert value['schema_version'] == version
    assert validate_report(value) == value
    Draft202012Validator(report_schema(version)).validate(value)
    assert main(['report','--from-file',str(fixtures/path),'--html',str(tmp_path/'report.html')]) == 0
    assert json.loads(capsys.readouterr().out) == value


@pytest.mark.parametrize('code', ['02','03','06','0c','0d','0e','12','14'])
def test_each_added_log_page_has_fixture_and_exact_allowlist(code,fixtures):
    page=parse_logpages((fixtures/'synthetic'/('logpage-'+code+'.txt')).read_text())['pages'][0]
    assert page['known'] is True and page['page'] == '0x'+code
    assert page['parameters']
    assert validate_command(['sg_logs','--readonly','--page=0x'+code,'/dev/sg9'])


def test_mam_attributes_units_and_serial(fixtures):
    data=parse_mam((fixtures/'synthetic/mam.txt').read_text())
    assert not data['warnings']
    rows={r['id']:r for r in data['attributes']}
    assert rows['0x0003']['value'] == 42
    assert rows['0x0220']['value'] == 24000 and rows['0x0220']['unit'] == 'MiB'
    assert rows['0x0221']['value'] == 48000
    assert rows['0x0401']['redacted'] and rows['0x0401']['value'] == 'SYNTH-MEDIUM-0001'
    for cmd in mam_commands('/dev/sg9'):
        assert validate_command(cmd) == cmd


def test_mam_does_not_retain_unknown_attribute_or_raw_identifier():
    data=parse_mam('Medium serial number: fixture-only-id\nUser medium text label: fixture-only-label\nLoad count: unknown\n')
    text=json.dumps(data)
    assert 'fixture-only' not in text and 'SYNTH-REDACTED-MEDIUM-SERIAL' in text
    assert data['attributes'][-1]['value'] is None and len(data['warnings']) == 2
    assert parse_mam('')['warnings']


def test_inquiry_firmware_vpd_redaction(fixtures):
    data=parse_inquiry((fixtures/'synthetic/inquiry-vpd.txt').read_text())
    assert data['revision'] == '0001' and data['serial'] == 'SYNTH-DRIVE-0001'
    assert data['identifiers'][0]['value'] == 'SYNTH-WWN-0001'
    raw='SCSI_SERIAL=fixture-only-id\nSCSI_IDENT_LUN_NAA=fixture-only-wwn\n'
    parsed=json.dumps(parse_inquiry(raw))
    assert 'fixture-only' not in parsed and 'SYNTH-REDACTED-DEVICE-ID' in parsed
    for cmd in inquiry_commands('/dev/sg9'):
        assert validate_command(cmd) == cmd


@pytest.mark.parametrize('command,raw', [
    (['sg_inq','--export','--page=0x80','/dev/sg9'],'SCSI_SERIAL=fixture-only-id'),
    (['sg_inq','--export','--page=0x83','/dev/sg9'],'SCSI_IDENT_LUN_NAA=fixture-only-wwn'),
    (mam_commands('/dev/sg9')[-1],'Medium serial number: fixture-only-id'),
])
def test_runner_redacts_before_transcript(command,raw,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('tapediag.safety.shutil.which',lambda *a,**k:'/usr/bin/'+command[0])
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=raw,stderr='fixture-only-diagnostic'))
    result=Runner(True).run(command)
    assert result.ok
    assert 'fixture-only' not in json.dumps(result.to_dict())
    assert 'SYNTH-' in result.stdout


@pytest.mark.parametrize('code,label',list(DENSITIES.items()))
def test_density_fallback(code,label):
    result=parse_drive_status('Density code 0x%x'%code)
    assert result['density_description'] == label


def test_unknown_density_and_explicit_description_preserved():
    assert parse_drive_status('Density code 0xff')['density_description'] == 'Unknown density'
    assert parse_drive_status('Density code 0x5e (captured description)')['density_description'] == 'captured description'


def test_topology_maps_hctl_not_sg_index(fixtures):
    data=parse_topology((fixtures/'synthetic/topology.txt').read_text())
    assert data['mappings'][0] == {'generic_device':'/dev/sg9','address':'9:0:1:0','kind':'drive','device':'/dev/st0'}
    assert data['mappings'][1]['kind'] == 'changer'
    assert parse_topology('/dev/sg1 0 0 0 0 0 /dev/sda')['mappings'] == []
    assert parse_topology('/dev/sg1 0 0 0 0 1 /dev/st0;erase')['warnings']


def test_changer_empty_source_is_expected_and_ie_not_door_state(fixtures):
    checks=library_checks(parse_library((fixtures/'synthetic/library.txt').read_text()))
    assert any(c['rule'] == 'source-empty' and c['severity'] == 'info' for c in checks)
    assert not any(c['severity'] == 'warn' for c in checks)
    assert any('door/access state is not reported' in c['message'] for c in checks)


def test_changer_duplicate_barcode_occupied_source_and_empty_tag(fixtures):
    checks=library_checks(parse_library((fixtures/'synthetic/library-inconsistent.txt').read_text()))
    assert {c['rule'] for c in checks} == {'duplicate-barcode','source-occupied','empty-with-barcode','ie-state'}
    status=parse_library('Data Transfer Element 0:Full (Storage Element 99 Loaded)')
    assert library_checks(status)[0]['rule'] == 'source-unobserved'


def test_tapealert_response_hex_flag_positions(fixtures):
    text=(fixtures/'synthetic/logpage-12.txt').read_text().replace('14h: 0','14h: 1')
    data=tapealert_response(text)
    assert data['page'] == '0x12'
    assert data['observed_flags'] == list(range(1,65))
    assert [r['flag'] for r in data['active_flags']] == [20]
    assert data['active_flags'][0]['name'] == 'Clean now'


@pytest.mark.parametrize('name,score,status', [('healthy',100,'pass'),('cleaning-needed',65,'warn'),('degraded-media',0,'fail')])
def test_health_scenario_scores(name,score,status,fixtures):
    health=summarize(scenario(fixtures,name))
    assert (health['score'],health['status'],health['coverage']) == (score,status,'complete')
    assert all(r['source'].startswith('https://') for r in health['rules'])


def test_health_deductions_once_and_missing_data_not_healthy(fixtures):
    value=scenario(fixtures,'cleaning-needed')
    value['drives'].append(copy.deepcopy(value['drives'][0]))
    assert summarize(value)['score'] == 65
    value['drives']=[]
    assert summarize(value)['status'] == 'warn'
    assert summarize(value)['coverage'] == 'incomplete'


def test_health_temperature_255_and_corrected_errors_not_fault(fixtures):
    value=scenario(fixtures)
    for p in value['drives'][0]['logpages']['pages']:
        if p['page'] == '0x0d': p['parameters'][0]['value']=255
    assert summarize(value)['matches'] == []


def test_guided_dry_run_no_subprocess_and_valid_schema(monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('dry-run ran subprocess'))
    value=run_guided(['/dev/sg9'],['/dev/sg10'])
    Draft202012Validator(report_schema('2.0')).validate(value)
    assert [s['kind'] for s in value['steps']] == ['inventory','inquiry','tapealert','logpages','mam','library']
    assert all(s['status']=='planned' and not s['results'] for s in value['steps'])
    assert not value['complete'] and len(value['not_performed']) == 4
    for step in value['steps']:
        assert step['expected_seconds'] > 0 and step['source'].startswith('https://')
        for argv in step['argv']: assert validate_command(argv) == argv


@pytest.mark.parametrize('kwargs', [dict(execute=True),dict(execute=True,drives=['/dev/sg9']),dict(execute=True,confirmed=True),dict(resume=True)])
def test_guided_execute_confirmation_and_device_requirements(kwargs,monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('invalid request ran subprocess'))
    with pytest.raises(ValueError): run_guided(**kwargs)


class GuidedFixtureRunner(Runner):
    def __init__(self,fixtures,fail=None):
        super().__init__(True)
        self.fixtures=fixtures
        self.fail=fail
    def run(self,argv):
        validate_command(argv)
        self.results.append(CommandResult(argv,returncode=0))
        r=self.results[-1]
        mapping={'lsscsi':'inventory.txt','sg_map':'topology.txt','sg_inq':'inquiry-vpd.txt','sg_read_attr':'mam.txt','mtx':'library.txt'}
        if argv[0]=='sg_logs':
            name='tapealert-clear.txt' if argv[2]=='--page=0x2e' else 'logpage-'+argv[2][-2:]+'.txt'
            path=self.fixtures/'synthetic'/name
            r.stdout=path.read_text() if path.exists() else 'Supported log pages [0x00]:\n  0x0d Temperature\n'
        else:
            r.stdout=(self.fixtures/'synthetic'/mapping[argv[0]]).read_text()
            if argv[0]=='sg_read_attr':
                # sg_read_attr --filter prints only the selected attribute.
                parsed=parse_mam(r.stdout)
                code=argv[2].split('=')[1]
                r.stdout='\n'.join(a['name']+': '+str(a['value']) for a in parsed['attributes'] if a['id']==code)
        if self.fail and self.fail(argv):
            r.returncode=2;r.error='synthetic command failure'
        return r


def test_guided_execute_and_resume_skips_successful_steps(fixtures,tmp_path):
    path=tmp_path/'state.json'
    runner=GuidedFixtureRunner(fixtures)
    value=run_guided(['/dev/sg9'],['/dev/sg10'],True,True,True,path,runner=runner)
    assert value['complete'] and all(s['status']=='pass' for s in value['steps'])
    assert value['steps'][4]['data']['attributes'][0]['value'] == 42
    Draft202012Validator(report_schema('2.0')).validate(value)
    assert json.loads(path.read_text()) == value
    resumed=GuidedFixtureRunner(fixtures)
    assert run_guided(['/dev/sg9'],['/dev/sg10'],True,True,True,path,True,runner=resumed) == value
    assert resumed.results == []


def test_guided_resume_retries_failed_steps_and_skips_mam_without_media(fixtures,tmp_path):
    path=tmp_path/'state.json'
    runner=GuidedFixtureRunner(fixtures,fail=lambda a:a[0]=='sg_inq')
    value=run_guided(['/dev/sg9'],execute=True,confirmed=True,state_file=path,runner=runner)
    assert value['steps'][1]['status'] == 'fail' and value['steps'][-1]['status'] == 'skipped'
    assert not any(r.argv[0]=='sg_read_attr' for r in runner.results)
    retry=GuidedFixtureRunner(fixtures)
    value=run_guided(['/dev/sg9'],execute=True,confirmed=True,state_file=path,resume=True,runner=retry)
    assert [r.argv[0] for r in retry.results] == ['sg_inq']*3
    assert value['steps'][1]['status'] == 'pass'


def test_guided_resume_rejects_tampered_argv_and_device_change(fixtures,tmp_path):
    path=tmp_path/'state.json'
    run_guided(['/dev/sg9'],state_file=path)
    with pytest.raises(ValueError,match='plan differs'): run_guided(['/dev/sg99'],state_file=path,resume=True)
    value=json.loads(path.read_text());value['steps'][1]['argv']=[['mt','-f','/dev/nst0','erase']]
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='plan differs'): run_guided(['/dev/sg9'],state_file=path,resume=True)


def test_guided_state_not_overwritten_or_symlinked(tmp_path):
    path=tmp_path/'state.json';path.write_text('existing')
    with pytest.raises(ValueError,match='already exists'): run_guided(state_file=path)
    other=tmp_path/'alias';other.symlink_to(path)
    with pytest.raises(ValueError): run_guided(state_file=other)
    assert path.read_text() == 'existing'


@pytest.mark.parametrize('op',['write','read-test','erase','firmware','load','unload'])
def test_guided_destructive_steps_have_no_cli_execution_route(op,capsys,monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('destructive command ran'))
    with pytest.raises(SystemExit) as exc: main(['guided','--execute','--i-understand-read-only','--drive','/dev/sg9',op])
    assert exc.value.code == 2
    capsys.readouterr()


@pytest.mark.parametrize('argv',[
    ['sg_read_attr','/dev/sg9'],['sg_write_attr','/dev/sg9'],
    ['sg_read_attr','--readonly','--first=0x0800','--filter=0x0800','/dev/sg9'],
    mam_commands('/dev/sg9')[0]+['--raw'],
    ['sg_inq','--export','--page=0x89','/dev/sg9'],['sg_map','-i'],
])
def test_new_allowlist_cannot_expand(argv,monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('refused command ran'))
    with pytest.raises(SafetyError): Runner(True).run(argv)


@pytest.mark.parametrize('change',[
    lambda v:v.update(secret='extra'),lambda v:v['health'].update(score=101),
    lambda v:v['drives'][0]['mam']['attributes'][0].update(value=[]),
    lambda v:v['libraries'][0]['checks'][0].update(severity='critical'),
    lambda v:v['drives'][0]['tapealert_response'].update(page='0x2e'),
])
def test_v2_malformed_reports_rejected_by_both(change,fixtures):
    value=scenario(fixtures);change(value)
    assert list(Draft202012Validator(report_schema('2.0')).iter_errors(value))
    with pytest.raises(ValueError):validate_report(value)


def test_html_escapes_untrusted_observations_and_has_no_external_assets(fixtures):
    value=scenario(fixtures)
    value['drives'][0]['drive_status']['product']='<script>alert("fixture")</script>'
    value['errors'].append({'section':'<img src=https://example.org/>','device':None,'message':'synthetic <&> failure'})
    html=render_html(value)
    assert '<script>' not in html and '<img ' not in html and 'fetch(' not in html
    assert '&lt;script&gt;' in html and '&lt;img src=' in html
    assert 'default-src' in html and '@media print' in html and 'prefers-color-scheme' in html
    assert 'Collection errors' in html and 'synthetic &lt;&amp;&gt; failure' in html


def test_report_cli_v2_html_and_guided_replay(fixtures,tmp_path,capsys):
    assert main(['report','--schema-version','2.0','--from-dir',str(fixtures/'scenarios/healthy'),'--html',str(tmp_path/'r.html')]) == 0
    value=json.loads(capsys.readouterr().out);assert value['schema_version']=='2.0'
    assert (tmp_path/'r.html').read_text().startswith('<!doctype html>')
    path=tmp_path/'guided.json';path.write_text(json.dumps(run_guided(['/dev/sg9'])))
    assert main(['guided','--from-file',str(path)]) == 0
    assert json.loads(capsys.readouterr().out)['document_type']=='guided'
    assert main(['report','--from-file',str(path)]) == 2
    assert 'not a guided transcript' in capsys.readouterr().err

@pytest.mark.parametrize('value,unit', [(255,'C'),(None,'C'),(29,'F')])
def test_unavailable_or_incompatible_temperature_leaves_coverage_gap(value,unit,fixtures):
    report=scenario(fixtures)
    page=next(p for p in report['drives'][0]['logpages']['pages'] if p['page']=='0x0d')
    page['parameters'][0].update(value=value,unit=unit)
    health=summarize(report)
    assert health['score']==100 and health['status']=='warn' and health['coverage']=='incomplete'
    assert any('usable health parameters missing on 0x0d' in g for g in health['gaps'])


def test_empty_advertised_error_page_cannot_prove_health(fixtures):
    report=scenario(fixtures)
    page=next(p for p in report['drives'][0]['logpages']['pages'] if p['page']=='0x02')
    page['parameters']=[]
    assert summarize(report)['coverage']=='incomplete'


def test_standard_inquiry_implicit_serial_is_redacted(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('tapediag.safety.shutil.which',lambda *a,**k:'/usr/bin/sg_inq')
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout='Vendor identification: SYNTH\nUnit serial number: fixture-only-id\n',stderr='fixture-only-diagnostic'))
    result=Runner(True).run(['sg_inq','/dev/sg9'])
    assert 'fixture-only' not in json.dumps(result.to_dict())
    assert 'Vendor identification: SYNTH' in result.stdout


def test_guided_interruption_keeps_last_complete_step(fixtures,tmp_path):
    path=tmp_path/'state.json'
    class Interrupted(GuidedFixtureRunner):
        def run(self,argv):
            if argv[0]=='sg_inq': raise KeyboardInterrupt()
            return super().run(argv)
    with pytest.raises(KeyboardInterrupt):
        run_guided(['/dev/sg9'],execute=True,confirmed=True,state_file=path,runner=Interrupted(fixtures))
    saved=json.loads(path.read_text())
    assert saved['steps'][0]['status']=='pass' and saved['steps'][1]['status']=='planned'
    assert saved['complete'] is False
    resumed=GuidedFixtureRunner(fixtures)
    value=run_guided(['/dev/sg9'],execute=True,confirmed=True,state_file=path,resume=True,runner=resumed)
    assert value['complete'] and not any(r.argv[0] in ('lsscsi','sg_map') for r in resumed.results)


def test_guided_resume_ignores_forged_saved_verdict_and_reinterprets(fixtures,tmp_path):
    path=tmp_path/'state.json'
    run_guided(['/dev/sg9'],execute=True,confirmed=True,state_file=path,runner=GuidedFixtureRunner(fixtures))
    value=json.loads(path.read_text())
    step=next(s for s in value['steps'] if s['kind']=='tapealert')
    step['results'][0]['stdout']='Flag 20: 1\n'
    step['data']=None
    step['status']='pass'
    path.write_text(json.dumps(value))
    # Saved observations are not authenticated, but the saved verdict is never trusted.
    resumed=GuidedFixtureRunner(fixtures)
    result=run_guided(['/dev/sg9'],execute=True,confirmed=True,state_file=path,resume=True,runner=resumed)
    assert result['steps'][2]['status']=='pass'
    assert any(r.argv[0]=='sg_logs' for r in resumed.results)


def test_guided_resume_success_without_command_evidence_refused(fixtures,tmp_path):
    path=tmp_path/'state.json'
    value=run_guided(['/dev/sg9'],state_file=path)
    value['steps'][0]['status']='pass'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='lacks successful command evidence'):
        run_guided(['/dev/sg9'],state_file=path,resume=True)


def test_historical_v1_artifact_validates_without_conversion(fixtures):
    path=fixtures/'golden/v1-original-report.json'
    value=json.loads(path.read_text())
    assert value['schema_version']=='1.0' and value['tool_version']=='0.1.0'
    Draft202012Validator(report_schema('1.0')).validate(value)
    assert validate_report(value) is value
    assert 'schema 1.0' in render_html(value)


def test_ambiguous_density_is_not_reported_as_one_format():
    assert parse_drive_status('Density code 0x40')['density_description']=='DLT1 40 GB, or Ultrium'


def test_alternate_barcodes_cross_elements_and_truncated_capture_warn():
    status=parse_library('Storage Changer /dev/sg10:0 Drives, 2 Slots\nStorage Element 1:Full :VolumeTag=SYN001L8:AlternateVolumeTag=SYNALT01\nStorage Element 2:Full :VolumeTag=SYNALT01\n')
    assert any(c['rule']=='duplicate-barcode' for c in library_checks(status))
    truncated=parse_library('Storage Changer /dev/sg10:1 Drives, 2 Slots\nData Transfer Element 0:Empty\n')
    assert any(c['rule']=='capture-consistency' for c in library_checks(truncated))


def test_response_alerts_contribute_to_triage_and_render_separately(fixtures):
    value=scenario(fixtures)
    page=next(p for p in value['drives'][0]['logpages']['pages'] if p['page']=='0x12')
    for p in page['parameters']:
        p['raw']=p['raw'].replace('14h: 0','14h: 1')
    health=summarize(value)
    assert health['score']==65
    assert '(12h response): Clean now' in health['matches'][0]['evidence'][0]
    html=render_html(value)
    assert 'Drive response observations' in html and '20 · Critical' in html
    assert 'data-label="Recommended action"' in html
