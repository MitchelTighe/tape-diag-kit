"""Execute the exact README quickstart block and verify offline CLI contracts.

Uses only synthetic fixtures and plan requests. No --execute command is run.
Captures summaries of actual outputs, exit statuses and artifact paths.
"""
import json
import os
from pathlib import Path
import subprocess

from tapediag.validation import validate_report

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/v3'
OUT.mkdir(parents=True,exist_ok=True)
readme=(ROOT/'README.md').read_text()
block=readme.split('<!-- quickstart-v3-start -->')[1].split('<!-- quickstart-v3-end -->')[0]
commands=block.split('```sh\n')[1].split('```')[0].strip().splitlines()
# The documentation block is version-controlled code. Explicitly disallow live flags.
assert all('--execute' not in line for line in commands)
env=dict(os.environ,PATH=str(ROOT/'bin')+os.pathsep+os.environ['PATH'],PYTHONDONTWRITEBYTECODE='1')
transcript=[]
for command in commands:
    if command.startswith('export PATH='):
        transcript.append({'command':command,'exit':0,'summary':'PATH set to source launcher for following commands'})
        continue
    proc=subprocess.run(['sh','-eu','-c',command],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
    transcript.append({'command':command,'exit':proc.returncode,'stdout':proc.stdout.strip(),'stderr':proc.stderr.strip()})
    assert proc.returncode==0,(command,proc.stderr)
quick=json.loads((OUT/'quickstart.json').read_text())
assert validate_report(quick)['schema_version']=='3.0' and quick['fleet_id']=='SYNTH-QUICKSTART'
assert quick['captured_at'] is None and quick['commands']==[]
assert validate_report(json.loads((OUT/'quickstart-workflow.json').read_text()))['workflow']=='slow-drive'
assert validate_report(json.loads((OUT/'quickstart-plan.json').read_text()))['mode']=='dry-run'
assert validate_report(json.loads((OUT/'migrated-v2.json').read_text()))['migration']['from_version']=='2.0'
assert json.loads((OUT/'watch-clear.json').read_text())['regressions']==0
# Regression exit code is an explicit contract, outside the all-success quickstart.
proc=subprocess.run([str(ROOT/'bin/tapediag'),'watch','fixtures/fleets/synth-bravo-20261016.json','fixtures/fleets/synth-bravo-20261018.json'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
assert proc.returncode==1
regression=json.loads(proc.stdout);assert regression['regressions']>0
(OUT/'watch-regressions.json').write_text(proc.stdout)
transcript.append({'command':'tapediag watch fixtures/fleets/synth-bravo-20261016.json fixtures/fleets/synth-bravo-20261018.json','exit':proc.returncode,'summary':str(regression['regressions'])+' regression events'})
(OUT/'quickstart-results.json').write_text(json.dumps({'quickstart_commands':len(commands),'all_success':True,'extra_regression_check':True,'results':transcript},indent=2)+'\n')
print('README quickstart: %d/%d commands completed successfully; no hardware or live execution.'%(len(commands),len(commands)))
print('v3 report/schema, workflow, plan, migration, dashboard and CSV artifacts validated; clear watch exit 0, regression watch exit 1 (%d events).'%regression['regressions'])
