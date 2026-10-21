from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
import zipfile

import pytest

from tapediag.dta_config import Refusal
from tapediag.dta_engine import Engine
from tapediag.dta_fake import FakeTransport
from tapediag.dta_plan import build_plan
from tapediag.dta_storage import Store
from tapediag.dta_transport import Authorization, Response, Uncertain


@contextmanager
def session(config, fixtures, path, fake=None, resume=False, after_step=None, auth=None):
    with Store(path, resume=resume) as store:
        fake = fake or FakeTransport(config, fixtures)
        lines = []
        engine = Engine(config, "SYNTH-TEST-RUN", fake, auth or Authorization(config, True, config.serial),
                        store, emit=lines.append, sleep=lambda _: None, after_step=after_step)
        yield engine, fake, store, lines


def test_fake_end_to_end_restores_and_bundles(tmp_path, dta_config, dta_fixtures):
    with session(dta_config, dta_fixtures, tmp_path / "run") as (engine, fake, store, lines):
        manifest = engine.apply()
        assert fake.snapshots == fake.original
        assert not fake.loaded and fake.collected and not fake.authenticated
        assert engine.state["restoration_verified"] and engine.state["failures"] == []
        assert len(engine.state["completed"]) == 15
        writes = [r.op for r in fake.calls if r.write]
        assert writes.count("mover.test") == 1
        assert writes.count("library.mount") == writes.count("library.return") == 1
        assert writes.index("library.return") < writes.index("zone.add")
        assert writes.index("zone.remove") < writes.index("library.mount") < writes.index("mover.test")
        assert sum("GUARD PASS" in line for line in lines) == 3
        with zipfile.ZipFile(store.path / "attachments.zip") as archive:
            embedded = json.loads(archive.read("manifest.json"))
            assert embedded == manifest
            for row in embedded["files"]:
                data = archive.read(row["path"])
                assert len(data) == row["size"]
                assert hashlib.sha256(data).hexdigest() == row["sha256"]
            assert archive.read("audit.jsonl") == (store.path / "audit.jsonl").read_bytes()
            assert "state.json" in archive.namelist()
        ticket = (store.path / "support-ticket.txt").read_text()
        assert "Hardware verdict: UNKNOWN" in ticket and "acceptance: operator verification pending" in ticket
        assert "verified: true" in ticket
        assert all(not (p.stat().st_mode & 0o077) for p in store.path.iterdir())


@pytest.mark.parametrize("apply,serial", [(False, "SYNTH-DRIVE-DTA"), (True, None), (True, "SYNTH-WRONG"), (False, None)])
def test_apply_and_serial_both_required(tmp_path, dta_config, dta_fixtures, apply, serial):
    with session(dta_config, dta_fixtures, tmp_path / "run", auth=Authorization(dta_config, apply, serial)) as (engine, fake, store, _):
        with pytest.raises(Refusal, match="--apply AND"):
            engine.apply()
        assert fake.calls == []
        assert not (store.path / "audit.jsonl").exists()


@pytest.mark.parametrize("bad_op", ["zone.default", "zone.transactions", "zone.fabric_transactions", "mover.version", "library.identity", "mover.identity"])
def test_preflight_failures_never_mutate(tmp_path, dta_config, dta_fixtures, bad_op):
    fake = FakeTransport(dta_config, dta_fixtures,
                         fault=lambda f, r: Response(0, b"unsupported synthetic evidence\n") if r.op == bad_op else None)
    with session(dta_config, dta_fixtures, tmp_path / "run", fake=fake) as (engine, fake, store, _):
        with pytest.raises(Refusal):
            engine.apply()
        assert not any(r.write for r in fake.calls)
        assert not engine.state["restoration_verified"]
        assert (store.path / "attachments.zip").exists()
        assert "verified: false" in (store.path / "support-ticket.txt").read_text()


@pytest.mark.parametrize("failure", ["barcode", "empty", "serial", "physical", "wwpn", "zoning", "version", "default", "home"])
def test_erase_guard_rechecked_after_checkpoint(tmp_path, dta_config, dta_fixtures, failure):
    fake = FakeTransport(dta_config, dta_fixtures)
    def change_after_guard(key):
        if key != "erase_guard":
            return
        if failure == "empty":
            fake.loaded = False
        elif failure == "zoning":
            fake.snapshots[dta_config.switches[0].ssh] = fake.original[dta_config.switches[0].ssh]
        else:
            def fault(f, r):
                if failure == "barcode" and r.op == "library.inventory":
                    return Response(0, f.text("inventory-loaded.xml").replace("SYNTH-TEST-L9", "SYNTH-PRODUCTION-L9").encode())
                if failure == "serial" and r.op == "library.identity":
                    return Response(0, f.text("drive-list.xml").replace("SYNTH-DRIVE-DTA", "SYNTH-OTHER").encode())
                if failure == "physical" and r.op == "library.identity":
                    return Response(0, f.text("drive-list.xml").replace("SYNTH-PHYSICAL-DTA", "SYNTH-REPLACEMENT").encode())
                if failure == "wwpn" and r.op == "mover.identity":
                    return Response(0, f.text("itdt-inquiry.json").replace("0000000000000001", "0000000000000099").encode())
                if failure == "version" and r.op == "mover.version":
                    return Response(0, b"ITDT-SE 9.6.1\n")
                if failure == "default" and r.op == "zone.default":
                    return Response(0, b"Default Zone Access Mode\ncommitted - All Access\ntransaction - No Transaction\n")
                if failure == "home" and r.op == "library.inventory":
                    return Response(0, f.text("inventory-loaded.xml").replace("<offset>7</offset><full>no", "<offset>7</offset><barcode>SYNTH-OTHER-L9</barcode><isQueued>no</isQueued><full>yes").encode())
            fake.fault = fault
    with session(dta_config, dta_fixtures, tmp_path / "run", fake=fake, after_step=change_after_guard) as (engine, fake, _, _):
        with pytest.raises(Refusal):
            engine.apply()
        assert not any(r.op in ("mover.test", "mover.dump", "zone.add") for r in fake.calls)


@pytest.mark.parametrize("step", ["diagnostic", "dump", "collect"])
def test_known_command_failure_still_returns_and_restores(tmp_path, dta_config, dta_fixtures, step):
    fake = FakeTransport(dta_config, dta_fixtures)
    if step == "diagnostic":
        fake.diagnostic_returncode = 6
    elif step == "dump":
        fake.dump_returncode = 6
    else:
        fake.fault = lambda f, r: Response(1, b"") if r.op == "mover.collect" else None
    with session(dta_config, dta_fixtures, tmp_path / "run", fake=fake) as (engine, fake, _, _):
        engine.apply()
        assert fake.snapshots == fake.original and not fake.loaded
        assert engine.state["restoration_verified"] is True
        assert any(item.startswith(step + ":") for item in engine.state["failures"])


@pytest.mark.parametrize("status", ["FAILED", "UNKNOWN"])
def test_failed_or_unknown_move_never_starts_test(tmp_path, dta_config, dta_fixtures, status):
    fake = FakeTransport(dta_config, dta_fixtures)
    fake.progress_states = [status]
    with session(dta_config, dta_fixtures, tmp_path / "run", fake=fake) as (engine, fake, _, _):
        with pytest.raises(Refusal):
            engine.apply()
        assert engine.state["pending"]["request"]["op"] == "library.mount"
        assert not any(r.op in ("mover.test", "zone.add") for r in fake.calls)


def test_lost_library_progress_stops_with_pending_move(tmp_path, dta_config, dta_fixtures):
    fake = FakeTransport(dta_config, dta_fixtures)
    fake.progress_states = ["ACTIVE"] * 301
    with session(dta_config, dta_fixtures, tmp_path / "run", fake=fake) as (engine, fake, _, _):
        with pytest.raises(Uncertain, match="progress timed out"):
            engine.apply()
        assert len([r for r in fake.calls if r.op == "library.progress"]) == 300
        assert not any(r.op == "mover.test" for r in fake.calls)


STEP_NAMES = ["preflight", "isolate.SYNTH_A", "isolate.SYNTH_B", "prepare", "mount", "erase_guard",
              "diagnostic", "dump", "collect", "return", "restore.SYNTH_A", "restore.SYNTH_B", "verify", "logout", "bundle"]


@pytest.mark.parametrize("interrupt_after", STEP_NAMES)
def test_resume_every_completed_step_without_repeating_writes(tmp_path, dta_config, dta_fixtures, interrupt_after):
    def interrupt(step):
        if step == interrupt_after:
            raise KeyboardInterrupt()
    path = tmp_path / "run"
    with session(dta_config, dta_fixtures, path, after_step=interrupt) as (engine, fake, _, _):
        with pytest.raises(KeyboardInterrupt):
            engine.apply()
        assert engine.state["pending"] is None
    previous_writes = [r.op for r in fake.calls if r.write]
    with session(dta_config, dta_fixtures, path, fake=fake, resume=True) as (engine, fake, _, _):
        engine.apply(resume=True)
        writes = [r.op for r in fake.calls if r.write]
        assert writes[:len(previous_writes)] == previous_writes
        assert writes.count("mover.test") == writes.count("mover.dump") == 1
        assert writes.count("library.mount") == writes.count("library.return") == 1
        assert writes.count("mover.prepare") == 1
        assert writes.count("zone.remove") == writes.count("zone.add") == 2
        assert fake.snapshots == fake.original and not fake.loaded
        assert engine.state["completed"] == STEP_NAMES


@pytest.mark.parametrize("uncertain_op", ["zone.remove", "zone.save", "zone.enable", "mover.prepare", "library.mount", "mover.test", "mover.dump", "library.return", "zone.add"])
def test_uncertain_write_never_replayed_or_auto_restored(tmp_path, dta_config, dta_fixtures, uncertain_op):
    def fault(fake, request):
        if request.op == uncertain_op:
            raise Uncertain("synthetic interrupted transport")
    fake = FakeTransport(dta_config, dta_fixtures, fault=fault)
    path = tmp_path / "run"
    with session(dta_config, dta_fixtures, path, fake=fake) as (engine, fake, _, _):
        with pytest.raises(Uncertain):
            engine.apply()
        assert engine.state["pending"]["request"]["op"] == uncertain_op
        assert engine.state["pending"]["acknowledged"] is False
    count = len(fake.calls)
    fake.fault = None
    with session(dta_config, dta_fixtures, path, fake=fake, resume=True) as (engine, fake, _, _):
        with pytest.raises(Refusal, match="pending mutating"):
            engine.apply(resume=True)
        assert len(fake.calls) == count


def test_return_not_confirmed_never_exposes_test_media(tmp_path, dta_config, dta_fixtures):
    def fault(fake, request):
        if request.op == "library.return":
            return Response(0, b"<inventory><status>FAILED</status></inventory>")
    fake = FakeTransport(dta_config, dta_fixtures, fault=fault)
    with session(dta_config, dta_fixtures, tmp_path / "run", fake=fake) as (engine, fake, _, _):
        with pytest.raises(Refusal):
            engine.apply()
        assert not any(r.op == "zone.add" for r in fake.calls)


def test_resume_configuration_change_refused_before_transport(tmp_path, dta_config, dta_fixtures):
    path = tmp_path / "run"
    with session(dta_config, dta_fixtures, path, after_step=lambda _: (_ for _ in ()).throw(KeyboardInterrupt())) as (engine, fake, _, _):
        with pytest.raises(KeyboardInterrupt):
            engine.apply()
    count = len(fake.calls)
    changed = replace(dta_config, barcode="SYNTH-OTHER")
    with session(changed, dta_fixtures, path, fake=fake, resume=True) as (engine, _, _, _):
        with pytest.raises(Refusal, match="original config"):
            engine.apply(resume=True)
        assert len(fake.calls) == count


def test_resume_revalidates_live_state(tmp_path, dta_config, dta_fixtures):
    path = tmp_path / "run"
    def interrupt(key):
        if key == "mount":
            raise KeyboardInterrupt()
    with session(dta_config, dta_fixtures, path, after_step=interrupt) as (engine, fake, _, _):
        with pytest.raises(KeyboardInterrupt):
            engine.apply()
    fake.loaded = False
    count = len([r for r in fake.calls if r.write])
    with session(dta_config, dta_fixtures, path, fake=fake, resume=True) as (engine, _, _, _):
        with pytest.raises(Refusal, match="loaded barcode"):
            engine.apply(resume=True)
        assert len([r for r in fake.calls if r.write]) == count


@pytest.mark.parametrize("after_op", ["zone.remove", "zone.save"])
def test_intermediate_zoning_drift_stops_before_next_commit(tmp_path, dta_config, dta_fixtures, after_op):
    def fault(fake, request):
        if request.op == "zone.snapshot" and len(fake.calls) > 1 and fake.calls[-2].op == after_op:
            fake.snapshots[request.target]["defined"]["alias"]["SYNTH_UNRELATED_CHANGE"] = ["00:00:00:00:00:00:00:99"]
    fake = FakeTransport(dta_config, dta_fixtures, fault=fault)
    with session(dta_config, dta_fixtures, tmp_path / "run", fake=fake) as (engine, fake, _, _):
        with pytest.raises(Refusal, match="intermediate zoning drift"):
            engine.apply()
        writes = [r.op for r in fake.calls if r.write]
        assert writes == (["zone.remove"] if after_op == "zone.remove" else ["zone.remove", "zone.save"])
        assert engine.state["pending"]["request"]["op"] == after_op
