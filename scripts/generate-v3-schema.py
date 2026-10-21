"""Generate v3's strict structural schema from the frozen v2 vocabulary."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
schema = json.loads((ROOT / 'tapediag/report_schema_v2.json').read_text())
schema.update(title='tapediag v3 report or field workflow', **{'$id': 'https://example.org/tapediag/schema/tapediag-report.v3.json'})
def obj(props):
    return {'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False}
def ref(key):
    return {'$ref': '#/$defs/' + key}
def arr(item):
    return {'type': 'array', 'items': item}
string = {'type': 'string'}
strings = arr(string)
score = {'type': 'integer', 'minimum': 0, 'maximum': 100}
defs = schema['$defs']
defs['score_reason'] = obj({'id': string, 'deduction': score, 'condition': string, 'source': string,
    'accessed': {'const': '2026-10-18'}, 'basis': {'const': 'heuristic'}, 'evidence': strings})
defs['asset_health'] = obj({'model': {'const': 'triage-v3.0.0'}, 'score': score, 'grade': {'enum': ['A','B','C','D','F']},
    'assessment': {'enum': ['clear','attention','unknown']}, 'coverage': {'enum': ['complete','incomplete']},
    'gaps': strings, 'reasons': arr(ref('score_reason'))})
defs['fleet_health'] = obj({'model': {'const': 'triage-v3.0.0'}, 'score': {'anyOf': [score, {'type': 'null'}]},
    'aggregation': {'const': 'minimum asset score; no assets means unknown'}, 'assets': {'type': 'integer', 'minimum': 0},
    'attention': {'type': 'integer', 'minimum': 0}})
report = defs['report']
report['properties']['schema_version'] = {'const': '3.0'}
report['properties']['health'] = ref('fleet_health')
report['properties'].update(fleet_id={'type': 'string', 'minLength': 1, 'maxLength': 100},
    captured_at={'type': ['string', 'null'], 'format': 'date-time', 'pattern': r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$'},
    migration=obj({'from_version': {'enum': ['1.0','2.0']}, 'original_tool_version': string, 'notes': strings}))
report['required'].extend(['fleet_id','captured_at','migration'])
for key in ('drives','libraries'):
    asset = report['properties'][key]['items']
    asset['properties'].update(asset_id={'type': 'string', 'minLength': 1, 'maxLength': 200},
        identity_basis={'enum': ['synthetic-serial','device-path']}, health=ref('asset_health'))
    asset['required'].extend(['asset_id','identity_basis','health'])
step = defs['step']
step['properties']['kind']['enum'].extend(['library-inquiry', 'readiness'])
step['properties']['data']['anyOf'].append(ref('drive_status'))
defs['decision'] = obj({'device': string, 'outcome': string, 'path': strings, 'reason': string, 'next_steps': strings})
defs['workflow'] = obj({'schema_version': {'const': '3.0'}, 'document_type': {'const': 'workflow'},
    'tool_version': string, 'workflow': {'enum': ['identify','firmware','tapealert','cleaning','mam','dump-plan','inventory-audit','wont-load','slow-drive']},
    'title': string, 'mode': {'enum': ['dry-run','offline','execute']}, 'medium_loaded': {'type': 'boolean'},
    'steps': arr(ref('step')), 'decisions': arr(ref('decision')), 'limitations': strings,
    'not_performed': copy.deepcopy(defs['guided']['properties']['not_performed']), 'complete': {'type': 'boolean'}})
schema['anyOf'] = [ref('report'), ref('workflow')]
# Remove unused v2 policy/guided definitions; shared observation shapes remain frozen.
for key in ('health','rule','match','guided'):
    defs.pop(key, None)
encoded = json.dumps(schema, indent=2) + '\n'
for path in (ROOT/'tapediag/report_schema_v3.json', ROOT/'schema/tapediag-report.v3.json'):
    path.write_text(encoded)
