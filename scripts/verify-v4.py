"""Run the fixture-only failing-drive walkthrough, with independent assertions."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def verify(output, installed=False):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = ROOT / "fixtures/v4"
    commands = [
        ("alerts", ["alert-history"] + [str(fixture / ("alerts-%d.json" % day)) for day in range(16, 20)]),
        ("trend", ["log-trend", "--from-file", str(fixture / "log-series.json")]),
        ("inventory", ["inventory-diff", str(fixture / "inventory-before.txt"),
                       str(fixture / "inventory-after.txt"), "--library-id", "SYNTH-LIB"]),
        ("explain", ["explain", "sense:3/11/00"]),
        ("decode", ["log-decode", "--from-file", str(fixture / "log-31.txt"), "--profile", "lto5-6-capacity"]),
    ]
    results = {}
    for name, arguments in commands:
        invocation = [sys.executable] + (["-I"] if installed else []) + ["-m", "tapediag"]
        invocation += arguments + ["--html", str(output / (name + ".html"))]
        completed = subprocess.run(invocation, cwd=output if installed else ROOT,
                                   capture_output=True, text=True, timeout=30, check=True)
        results[name] = json.loads(completed.stdout)
        (output / (name + ".json")).write_text(completed.stdout, encoding="utf-8")
        if completed.stderr:
            raise ValueError("unexpected stderr in offline walkthrough")
        if "<script" in (output / (name + ".html")).read_text().lower():
            raise ValueError("static evidence HTML unexpectedly includes a script")
    events = [e for e in results["alerts"]["events"] if e["flag"] == 20]
    assert [e["kind"] for e in events] == ["activated", "coverage-lost", "inactive-observed"]
    writes = [c for c in results["trend"]["changes"] if c["name"] == "host_write_bytes"]
    assert [c["delta"] for c in writes] == [3072, 4096, None]
    errors = [c for c in results["trend"]["changes"] if c["name"] == "unrecovered_read_errors"]
    assert [c["delta"] for c in errors] == [2, 3, None]
    assert errors[-1]["kind"] == "medium-unconfirmed"
    assert len(results["inventory"]["relocation_candidates"]) == 1
    assert results["inventory"]["relocation_candidates"][0]["after"] == {"kind": "drive", "element": 0}
    assert results["explain"]["known"] and results["explain"]["name"] == "Read recovery exhausted"
    assert results["decode"]["parameters"][0]["unit"] == "MiB"
    print("v4 fixture walkthrough: 5 offline commands + independent assertions PASS" +
          (" (installed package, isolated Python)" if installed else ""))
    return results


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--installed", action="store_true", help="test installed wheel with isolated Python away from source")
    args = cli.parse_args()
    verify(args.output, args.installed)
