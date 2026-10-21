#!/bin/sh
set -eu
# This exact block appears in docs/INSTALL.md; run from the source root.
mkdir -p artifacts/mhvtl
tapediag inventory --from-file fixtures/mhvtl-synthetic/inventory.txt > artifacts/mhvtl/inventory.json
tapediag report --from-dir fixtures/mhvtl-synthetic --fleet-id SYNTH-MHVTL --captured-at 2026-10-18T00:00:00Z --html artifacts/mhvtl/report.html > artifacts/mhvtl/report.json
tapediag validate --from-file artifacts/mhvtl/report.json
tapediag guided --workflow inventory-audit --from-report artifacts/mhvtl/report.json > artifacts/mhvtl/audit.json
tapediag dashboard artifacts/mhvtl/report.json --output artifacts/mhvtl/dashboard.html
tapediag export-csv artifacts/mhvtl/report.json --output artifacts/mhvtl/fleet.csv
python - <<'PY'
import csv
import json
from pathlib import Path
report = json.loads(Path('artifacts/mhvtl/report.json').read_text())
assert report['schema_version'] == '3.0'
assert report['fleet_id'] == 'SYNTH-MHVTL'
assert len(report['drives']) == len(report['libraries']) == 1
assert not report['errors']
assert report['commands'] == []
rows = list(csv.DictReader(Path('artifacts/mhvtl/fleet.csv').open()))
assert len(rows) == 2 and {row['fleet_id'] for row in rows} == {'SYNTH-MHVTL'}
assert Path('artifacts/mhvtl/dashboard.html').stat().st_size > 1000
print('mhvtl synthetic quickstart: 6 CLI commands + independent assertions PASS; no emulator or hardware')
PY
