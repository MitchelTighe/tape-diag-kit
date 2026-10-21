#!/usr/bin/env python3
"""Read-only source-checkout CLI done-check; write artifacts in this repository."""
import ast
import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "v3" / "v2-compat"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
lines = []


def run(args, expected=0):
    command = [str(ROOT / "bin/tapediag")] + args
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                          timeout=15, check=False)
    lines.extend(["$ tapediag " + " ".join(args), proc.stdout.rstrip(), proc.stderr.rstrip(), "exit: %d" % proc.returncode, ""])
    assert proc.returncode == expected, proc.stderr
    return proc


plan = run(["tapealert", "/dev/sg9"])
assert json.loads(plan.stdout) == [["sg_logs", "--readonly", "--page=0x2e", "/dev/sg9"]]
(ARTIFACTS / "dry-run.json").write_text(plan.stdout)
report = run(["report", "--schema-version", "2.0", "--from-dir", "fixtures/sample-host"])
data = json.loads(report.stdout)
schema = json.loads((ROOT / "schema/tapediag-report.v2.json").read_text())
Draft202012Validator(schema).validate(data)
assert data["errors"] == []
assert [f["flag"] for f in data["drives"][0]["tapealert"]["active_flags"]] == [3, 4, 5, 20]
assert len(data["drives"][0]["logpages"]["pages"]) == 10
(ARTIFACTS / "sample-report.json").write_text(report.stdout)
run(["library", "/dev/sg10", "--execute", "load", "1"], expected=2)
guided = run(["guided", "--drive", "/dev/sg9", "--changer", "/dev/sg10"])
transcript = json.loads(guided.stdout)
Draft202012Validator(schema).validate(transcript)
assert transcript["mode"] == "dry-run" and len(transcript["not_performed"]) == 4
(ARTIFACTS / "guided-dry-run.json").write_text(guided.stdout)
run(["guided", "--execute", "--drive", "/dev/sg9"], expected=2)
run(["guided", "--execute", "--i-understand-read-only", "--drive", "/dev/sg9", "erase"], expected=2)
for path in (ROOT / "tapediag").glob("*.py"):
    ast.parse(path.read_text(), filename=path.name, feature_version=(3, 9))
(ARTIFACTS / "cli-session.txt").write_text("\n".join(lines) + "\n")
print("Source CLI checks: PASS (exact dry-run plan; v2 report; destructive request refused)")
print("Report: 1 drive, 1 changer, 10 log pages, active TapeAlert flags [3, 4, 5, 20], 0 collection errors")
print("Python 3.9 syntax check: PASS (syntax only; runtime was Python %s)" % sys.version.split()[0])
print("Artifacts: artifacts/v3/v2-compat/dry-run.json, artifacts/v3/v2-compat/sample-report.json, artifacts/v3/v2-compat/cli-session.txt")
