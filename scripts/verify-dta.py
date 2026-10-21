#!/usr/bin/env python3
"""Reproduce full DTA plans, fake execution, audit and bundle without a network.

No vendor binary is executed. All transports and archive bytes are synthetic.
Use an existing task scratch parent; no installs/builds occur in this script.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tapediag.dta_config import load_config
from tapediag.dta_engine import Engine
from tapediag.dta_fake import FakeTransport
from tapediag.dta_storage import Store
from tapediag.dta_transport import Authorization


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, required=True, help="existing authorized scratch parent")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "dta")
    parser.add_argument("--owner-adapter", action="store_true", help="also exercise the optional synthetic owner lock/verifier profile")
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    config = load_config(ROOT / "fixtures/dta" / ("config.owner.synthetic.toml" if args.owner_adapter else "config.synthetic.toml"))
    lines = ["SYNTHETIC REHEARSAL: in-memory fake transports only; no network, vendor executable or hardware."]
    fake = FakeTransport(config, ROOT / "fixtures/dta")
    run_id = "SYNTH-DEMO"
    engine = Engine(config, run_id, fake, Authorization(config), emit=lines.append)
    plan = engine.dry_run()
    assert not fake.calls, "default plan invoked transport"
    (args.output / "dry-run-plan.txt").write_text(plan + "PLAN ONLY: 0 connections, 0 remote requests, 0 hardware writes.\n")
    with tempfile.TemporaryDirectory(prefix="dta-verify-", dir=args.scratch) as temporary:
        run = Path(temporary) / "run"
        with Store(run) as store:
            engine = Engine(config, run_id, fake, Authorization(config, True, config.serial), store,
                            emit=lines.append, sleep=lambda _: None)
            manifest = engine.apply()
            state = engine.state
            assert state["restoration_verified"] and not state["failures"]
            assert fake.snapshots == fake.original and not fake.loaded and not fake.authenticated
            writes = [r.op for r in fake.calls if r.write]
            assert writes.count("mover.test") == writes.count("mover.dump") == 1
            assert writes.index("library.return") < writes.index("zone.add")
            assert writes.count("library.mount") == writes.count("library.return") == 1
            with zipfile.ZipFile(run / "attachments.zip") as archive:
                assert archive.read("audit.jsonl") == (run / "audit.jsonl").read_bytes()
                for row in manifest["files"]:
                    data = archive.read(row["path"])
                    assert len(data) == row["size"]
                    assert hashlib.sha256(data).hexdigest() == row["sha256"]
            for source, destination in (("audit.jsonl", "fake-audit.jsonl"), ("state.json", "fake-state.json"),
                                        ("support-ticket.txt", "support-ticket.txt"), ("manifest.json", "bundle-manifest.json"),
                                        ("attachments.zip", "attachments.synthetic.zip"), ("plan.json", "plan.json")):
                shutil.copyfile(run / source, args.output / destination)
        with Store(run, resume=True) as reopened:
            assert reopened.state["completed"] == state["completed"]  # validates full audit chain/anchor
    summary = {"synthetic_only": True, "plan_remote_requests": 0, "plan_hardware_writes": 0,
               "completed_steps": len(state["completed"]), "fake_requests": len(fake.calls), "fake_writes": len(writes),
               "failures": state["failures"], "restoration_verified_in_fake": True,
               "hardware_verdict": "unknown", "manifest_files_verified": len(manifest["files"])}
    lines.append("SYNTHETIC RESULT: " + json.dumps(summary, sort_keys=True))
    (args.output / "fake-e2e-transcript.txt").write_text("\n".join(lines) + "\n")
    (args.output / "verification.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("DTA synthetic verification passed: {} steps, {} fake requests, {} fake writes, {} hashed files; plan made 0 requests.".format(
        summary["completed_steps"], summary["fake_requests"], summary["fake_writes"], summary["manifest_files_verified"]))
    print("Full plan and fake execution transcript: " + str(args.output / "fake-e2e-transcript.txt"))


if __name__ == "__main__":
    main()
