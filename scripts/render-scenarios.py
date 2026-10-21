"""Create review artifacts using only synthetic saved fixtures (no subprocesses)."""
import json
from pathlib import Path
from tapediag.guided import run_guided
from tapediag.html_report import render_html
from tapediag.report import offline_report
from tapediag.v2 import enrich
from tapediag.validation import validate_report

root = Path(__file__).resolve().parents[1]
out = root / 'artifacts/v2'
out.mkdir(parents=True, exist_ok=True)
for name in ('sample-host', 'healthy', 'cleaning-needed', 'degraded-media'):
    path = root / 'fixtures' / ('sample-host' if name == 'sample-host' else 'scenarios/' + name)
    value = validate_report(enrich(offline_report(path), directory=path))
    (out / (name + '.json')).write_text(json.dumps(value, indent=2) + '\n')
    (out / (name + '.html')).write_text(render_html(value), encoding='utf-8')
    print('%s: score=%d status=%s coverage=%s errors=%d' % (name, value['health']['score'], value['health']['status'], value['health']['coverage'], len(value['errors'])))
(out / 'guided-dry-run.json').write_text(json.dumps(run_guided(['/dev/sg9'], ['/dev/sg10']), indent=2) + '\n')
print('Rendered four self-contained reports and guided dry-run transcript')
