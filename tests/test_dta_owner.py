from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from tapediag.dta_config import Refusal, parse_config
from tapediag.dta_engine import Engine
from tapediag.dta_fake import FakeTransport
from tapediag.dta_owner import owner_request, parse_owner
from tapediag.dta_plan import build_plan, render_plan
from tapediag.dta_storage import Store
from tapediag.dta_transport import Authorization, Response, Uncertain


def sample(config, locked=True):
    return {"schema": 1, "serial": config.serial, "manufacturer_serial": config.manufacturer_serial,
            "drive": config.owner["drive"], "device": config.owner["device"], "locked": locked,
            "lock_owner": "SYNTH-OWNER-RUN" if locked else None, "idle": True,
            "mounts": 0, "usable": True, "observed_at": datetime.now(timezone.utc).isoformat()}


def test_owner_command_templates_and_safe_reverse_rollback(dta_owner_config):
    request = owner_request(dta_owner_config, "SYNTH-OWNER-RUN", "lock")
    assert request.write and request.target == "SYNTH_OWNER"
    assert request.argv == ("/opt/SYNTH/owner-adapter", "lock", "SYNTH_OWNER_DRIVE", "SYNTH_OWNER_DEVICE",
                            "SYNTH-DRIVE-DTA", "SYNTH-PHYSICAL-DTA", "SYNTH-OWNER-RUN")
    text = render_plan(dta_owner_config, "SYNTH-OWNER-RUN")
    assert "00 [owner.lock]" in text
    assert text.index("Rollback for mount") < text.index("Rollback for isolate.SYNTH_B") < text.index("Rollback for isolate.SYNTH_A") < text.index("Rollback for owner.lock")
    keys = [s.key for s in build_plan(dta_owner_config, "SYNTH-OWNER-RUN")]
    assert keys[0] == "owner.lock" and keys[-3:] == ["owner.unlock", "logout", "bundle"]


@pytest.mark.parametrize("bad", ["missing_token", "unknown_placeholder", "shell", "relative", "unknown_key", "nonstring", "bad_resource"])
def test_owner_config_templates_reject_ambiguous_or_unsafe_inputs(dta_fixtures, dta_owner_config, bad):
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    data = tomllib.loads((dta_fixtures / "config.synthetic.toml").read_text())
    data["owner"] = json.loads(json.dumps(dta_owner_config.owner))
    assert parse_config(data).owner is not None
    if bad == "missing_token":
        data["owner"]["lock_argv"] = ["/opt/SYNTH/adapter", "{serial}"]
    elif bad == "unknown_placeholder":
        data["owner"]["lock_argv"].append("{unknown}")
    elif bad == "shell":
        data["owner"]["lock_argv"].append("SYNTH;bad")
    elif bad == "relative":
        data["owner"]["lock_argv"][0] = "adapter"
    elif bad == "unknown_key":
        data["owner"]["shell_command"] = "SYNTH"
    elif bad == "nonstring":
        data["owner"]["lock_argv"].append(42)
    else:
        data["owner"]["drive"] = "SYNTH&bad"
    with pytest.raises(Refusal):
        parse_config(data)


@pytest.mark.parametrize("key,value", [
    ("schema", True), ("serial", "SYNTH-OTHER"), ("manufacturer_serial", "SYNTH-REPLACEMENT"),
    ("drive", "SYNTH-OTHER"), ("device", "SYNTH-OTHER"), ("locked", False), ("locked", "yes"),
    ("lock_owner", "SYNTH-OTHER-RUN"), ("idle", False), ("idle", "true"), ("mounts", 1), ("mounts", True),
    ("mounts", -1), ("usable", "true"), ("observed_at", "not-a-time"), ("observed_at", "2020-01-01T00:00:00+00:00"),
    ("observed_at", "2026-01-01T00:00:00"),
])
def test_owner_lock_proof_rejects_unknown_stale_busy_or_other_owner(dta_owner_config, key, value):
    data = sample(dta_owner_config)
    assert parse_owner(json.dumps(data), dta_owner_config, "SYNTH-OWNER-RUN", True)["mounts"] == 0
    data[key] = value
    with pytest.raises(Refusal):
        parse_owner(json.dumps(data), dta_owner_config, "SYNTH-OWNER-RUN", True)


def test_owner_unlock_proves_usable_and_does_not_require_no_production_job(dta_owner_config):
    data = sample(dta_owner_config, False)
    data["idle"], data["mounts"] = False, 1  # Actual production work may have resumed.
    assert parse_owner(json.dumps(data), dta_owner_config, "SYNTH-OWNER-RUN", False)["usable"]
    data["usable"] = False
    with pytest.raises(Refusal):
        parse_owner(json.dumps(data), dta_owner_config, "SYNTH-OWNER-RUN", False)


def test_duplicate_owner_lock_field_refused(dta_owner_config):
    text = json.dumps(sample(dta_owner_config)).replace('"locked": true', '"locked": false, "locked": true')
    with pytest.raises(Refusal):
        parse_owner(text, dta_owner_config, "SYNTH-OWNER-RUN", True)


def test_owner_full_fake_workflow_orders_lock_and_release(tmp_path, dta_owner_config, dta_fixtures):
    config = dta_owner_config
    fake = FakeTransport(config, dta_fixtures)
    with Store(tmp_path / "run") as store:
        engine = Engine(config, "SYNTH-OWNER-RUN", fake, Authorization(config, True, config.serial), store,
                        emit=lambda _: None, sleep=lambda _: None)
        engine.apply()
        writes = [r.op for r in fake.calls if r.write]
        assert writes[0] == "owner.lock" and writes[-1] == "owner.unlock"
        assert writes.index("owner.lock") < writes.index("zone.remove") < writes.index("library.mount")
        assert writes.index("library.return") < writes.index("zone.add") < writes.index("owner.unlock")
        assert len(writes) == 19 and len(engine.state["completed"]) == 17
        assert engine.state["owner_verified"] and not fake.owner_locked


def test_known_failed_diagnostic_retains_owner_lock_after_restoration(tmp_path, dta_owner_config, dta_fixtures):
    config = dta_owner_config
    fake = FakeTransport(config, dta_fixtures)
    fake.diagnostic_returncode = 6
    with Store(tmp_path / "run") as store:
        engine = Engine(config, "SYNTH-OWNER-RUN", fake, Authorization(config, True, config.serial), store,
                        emit=lambda _: None, sleep=lambda _: None)
        engine.apply()
        assert fake.snapshots == fake.original and not fake.loaded
        assert fake.owner_locked and not engine.state["owner_verified"]
        assert not any(r.op == "owner.unlock" for r in fake.calls)
        assert engine.state["restoration_verified"] and engine.state["failures"]


def test_owner_lock_loss_blocks_test_at_last_guard(tmp_path, dta_owner_config, dta_fixtures):
    config = dta_owner_config
    fake = FakeTransport(config, dta_fixtures)
    def lose_lock(key):
        if key == "erase_guard":
            fake.owner_token = "SYNTH-OTHER-RUN"
    with Store(tmp_path / "run") as store:
        engine = Engine(config, "SYNTH-OWNER-RUN", fake, Authorization(config, True, config.serial), store,
                        emit=lambda _: None, sleep=lambda _: None, after_step=lose_lock)
        with pytest.raises(Refusal, match="owner verifier"):
            engine.apply()
        assert not any(r.op in ("mover.test", "owner.unlock") for r in fake.calls)


@pytest.mark.parametrize("step", ["owner.lock", "preflight", "isolate.SYNTH_A", "isolate.SYNTH_B", "prepare", "mount", "erase_guard",
                                   "diagnostic", "dump", "collect", "return", "restore.SYNTH_A", "restore.SYNTH_B", "verify", "owner.unlock", "logout", "bundle"])
def test_owner_resume_every_checkpoint(tmp_path, dta_owner_config, dta_fixtures, step):
    config = dta_owner_config
    fake = FakeTransport(config, dta_fixtures)
    path = tmp_path / "run"
    def interrupt(key):
        if key == step:
            raise KeyboardInterrupt()
    auth = Authorization(config, True, config.serial)
    with Store(path) as store:
        engine = Engine(config, "SYNTH-OWNER-RUN", fake, auth, store, emit=lambda _: None,
                        sleep=lambda _: None, after_step=interrupt)
        with pytest.raises(KeyboardInterrupt):
            engine.apply()
    with Store(path, resume=True) as store:
        engine = Engine(config, "SYNTH-OWNER-RUN", fake, auth, store, emit=lambda _: None, sleep=lambda _: None)
        engine.apply(resume=True)
        writes = [r.op for r in fake.calls if r.write]
        assert writes.count("owner.lock") == writes.count("owner.unlock") == writes.count("mover.test") == 1
        assert not fake.owner_locked and engine.state["owner_verified"]


@pytest.mark.parametrize("action", ["owner.lock", "owner.unlock"])
def test_uncertain_owner_write_is_not_repeated(tmp_path, dta_owner_config, dta_fixtures, action):
    config = dta_owner_config
    def fault(fake, request):
        if request.op == action:
            raise Uncertain("synthetic unknown owner operation")
    fake = FakeTransport(config, dta_fixtures, fault=fault)
    path = tmp_path / "run"
    auth = Authorization(config, True, config.serial)
    with Store(path) as store:
        engine = Engine(config, "SYNTH-OWNER-RUN", fake, auth, store, emit=lambda _: None, sleep=lambda _: None)
        with pytest.raises(Uncertain):
            engine.apply()
    count = len(fake.calls)
    with Store(path, resume=True) as store:
        engine = Engine(config, "SYNTH-OWNER-RUN", fake, auth, store, emit=lambda _: None, sleep=lambda _: None)
        with pytest.raises(Refusal, match="pending mutating"):
            engine.apply(resume=True)
        assert len(fake.calls) == count
