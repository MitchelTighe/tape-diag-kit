"""Run from outside the source checkout, with only the installed wheel available."""
import json
import subprocess
import tempfile
from pathlib import Path
from tapediag.validation import validate_report

def cli(*args, expected=0):
    proc = subprocess.run(['tapediag'] + list(args), capture_output=True, text=True, timeout=10)
    assert proc.returncode == expected, (args, proc.stdout, proc.stderr)
    return json.loads(proc.stdout)

assert cli('tapealert', '/dev/sg9') == [['sg_logs','--readonly','--page=0x2e','/dev/sg9']]
value = cli('guided','--drive','/dev/sg9','--changer','/dev/sg10')
assert validate_report(value)['mode'] == 'dry-run'
assert len(value['not_performed']) == 4
with tempfile.TemporaryDirectory() as directory:
    p = Path(directory)
    (p/'inventory.txt').write_text('')
    report = cli('report','--from-dir',str(p),'--html',str(p/'report.html'))
    assert validate_report(report)['schema_version'] == '3.0'
    assert 'Evidence before action.' in (p/'report.html').read_text()
    saved=p/'v3.json';saved.write_text(json.dumps(report))
    assert cli('validate','--from-file',str(saved))['valid']
    assert cli('watch',str(saved),str(saved))['regressions']==0
    csv_path=p/'fleet.csv'
    assert cli('dashboard',str(saved),'--output',str(p/'dashboard.html'))['reports']==1
    proc=subprocess.run(['tapediag','export-csv',str(saved),'--output',str(csv_path)],capture_output=True,text=True,timeout=10)
    assert proc.returncode==0 and csv_path.read_text().startswith('fleet_id,captured_at,kind')
    legacy=cli('report','--schema-version','2.0','--from-dir',str(p))
    legacy_path=p/'v2.json';legacy_path.write_text(json.dumps(legacy))
    migrated=cli('migrate','--from-file',str(legacy_path))
    assert validate_report(migrated)['migration']['from_version']=='2.0'
proc = subprocess.run(['tapediag','guided','--execute','--drive','/dev/sg9'],capture_output=True,text=True,timeout=10)
assert proc.returncode == 2 and 'i-understand-read-only' in proc.stderr
workflow = cli('guided','--workflow','dump-plan','--drive','/dev/sg9')
assert validate_report(workflow)['document_type'] == 'workflow'
assert not workflow['complete']
print('Installed-wheel CLI smoke: PASS (plan, legacy guided, v3 workflow/schema/report/HTML, migration/validation/watch/CSV/dashboard, confirmation refusal)')
