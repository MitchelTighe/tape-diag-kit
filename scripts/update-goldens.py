#!/usr/bin/env python3
"""Explicit maintainer utility. Review diffs; tests never regenerate expectations."""
import json
from pathlib import Path

from tapediag.parsers import PARSERS
from tapediag.report import offline_report
from tapediag.v2 import enrich

root = Path(__file__).resolve().parents[1]
for filename, command in json.loads((root / "fixtures/cases.json").read_text()):
    output = PARSERS[command]((root / "fixtures" / filename).read_text())
    path = root / "fixtures/golden" / (filename.replace("/", "__") + ".json")
    path.write_text(json.dumps(output, indent=2) + "\n")
(root / "fixtures/golden/sample-host.report.json").write_text(
    json.dumps(offline_report(root / "fixtures/sample-host"), indent=2) + "\n")

for name in ("healthy", "cleaning-needed", "degraded-media"):
    directory = root / "fixtures/scenarios" / name
    (root / "fixtures/golden" / ("scenario-" + name + ".json")).write_text(
        json.dumps(enrich(offline_report(directory), directory=directory), indent=2) + "\n")
# v1-original-report.json is an immutable historical compatibility fixture.
