from dataclasses import replace
import hashlib
import http.cookiejar
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from tapediag.dta_config import Refusal
from tapediag.dta_plan import Request, build_plan
from tapediag.dta_storage import Store, canonical, extract_collection, read_regular
from tapediag.dta_transport import Authorization, NoRedirect, RemoteTransport, Response, Uncertain, run_bounded


def request(config, op):
    return next(r for s in build_plan(config, "SYNTH-TRANSPORT") for r in s.requests if r.op == op)


def test_ssh_exact_request_allowlist_and_trust_options(dta_config):
    recorded = []
    def runner(argv, timeout):
        recorded.append((argv, timeout))
        return Response(0, b"")
    transport = RemoteTransport(dta_config, "SYNTH-TRANSPORT", Authorization(dta_config, True, dta_config.serial), runner=runner)
    transport.execute(request(dta_config, "zone.remove"))
    argv, timeout = recorded[0]
    assert argv[0] == "/usr/bin/ssh" and "-T" in argv
    assert "-oStrictHostKeyChecking=yes" in argv and "-oUpdateHostKeys=no" in argv
    assert "-oBatchMode=yes" in argv and "-oControlPath=none" in argv
    assert "-oForwardAgent=no" in argv and "-oClearAllForwardings=yes" in argv
    assert "-oForwardX11=no" in argv and "-oPermitLocalCommand=no" in argv
    assert argv[-1] == 'zoneremove "SYNTH_PROD_A", "SYNTH_DRIVE_A"'
    assert argv[-3:-1] == ["--", "SYNTH_SWITCH_A"]
    assert timeout == 30
    transport.execute(request(dta_config, "mover.test"))
    assert recorded[-1][1] == 10800
    assert " standardtest -forcedataoverwrite" in recorded[-1][0][-1]
    for bad in (Request("zone.remove", "SYNTH_SWITCH_A", ("zoneremove", "SYNTH_PROD_A", "SYNTH_OTHER")),
                Request("mover.test", "SYNTH_MOVER", ("/bin/sh", "-c", "SYNTH")),
                replace(request(dta_config, "mover.test"), timeout=999999)):
        with pytest.raises(Refusal, match="outside"):
            transport.execute(bad)
    assert len(recorded) == 2


@pytest.mark.parametrize("op", ["zone.snapshot", "zone.remove", "mover.test", "library.login", "library.mount"])
def test_transport_cannot_bypass_apply_confirmation(dta_config, op):
    def exploding(*args):
        pytest.fail("unauthorized transport reached subprocess")
    transport = RemoteTransport(dta_config, "SYNTH-TRANSPORT", Authorization(dta_config), runner=exploding)
    with pytest.raises(Refusal, match="--apply AND"):
        transport.execute(request(dta_config, op))


def test_changed_config_invalidates_authorization(dta_config):
    authorization = Authorization(dta_config, True, dta_config.serial)
    changed = replace(dta_config, barcode="SYNTH-CHANGED")
    with pytest.raises(Refusal):
        authorization.require(changed)


class HTTPResponse:
    def __init__(self, url, data, code=200):
        self.url, self.data, self.code = url, data, code
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def getcode(self):
        return self.code
    def geturl(self):
        return self.url
    def read(self, size):
        return self.data[:size]


def synthetic_cookie():
    return http.cookiejar.Cookie(0, "SYNTH_SESSION", "SYNTH_NOT_A_REAL_COOKIE", None, False,
                                 "synth-library.invalid", True, False, "/", True, True, None, True, None, None, {})


def test_https_login_cookie_memory_and_exact_progress_url(dta_config):
    calls = []
    class Opener:
        def open(self, req, timeout):
            calls.append((req, timeout))
            if "login.xml" in req.full_url:
                transport.cookies.set_cookie(synthetic_cookie())
                return HTTPResponse(req.full_url, b"<login><status>OK</status></login>")
            if "logout.xml" in req.full_url:
                return HTTPResponse(req.full_url, b"<logout/>")
            return HTTPResponse(req.full_url, b"<progress><status>OK</status></progress>")
    names = []
    def synthetic_credentials(name):
        names.append(name)
        return "SYNTH_NON_SECRET_VALUE"
    transport = RemoteTransport(dta_config, "SYNTH-TRANSPORT", Authorization(dta_config, True, dta_config.serial),
                                opener=Opener(), credentials=synthetic_credentials)
    login = request(dta_config, "library.login")
    assert "SYNTH_NON_SECRET_VALUE" not in login.description()
    transport.execute(login)
    assert names == ["DTA_LIBRARY_USERNAME", "DTA_LIBRARY_PASSWORD"]
    assert transport.logged_in and len(list(transport.cookies)) == 1
    transport.execute(request(dta_config, "library.progress"))
    assert calls[-1][0].full_url.endswith("/gf/inventory.xml?progress")
    transport.execute(request(dta_config, "library.logout"))
    assert not transport.logged_in and not list(transport.cookies)


@pytest.mark.parametrize("op", ["library.login", "library.mount"])
def test_http_failures_never_echo_authentication_or_url(dta_config, op):
    class BrokenOpener:
        def open(self, req, timeout):
            raise OSError("SYNTH_PRIVATE_MARKER " + req.full_url)
    transport = RemoteTransport(dta_config, "SYNTH-TRANSPORT", Authorization(dta_config, True, dta_config.serial),
                                opener=BrokenOpener(), credentials=lambda name: "SYNTH_NON_SECRET_VALUE")
    transport.logged_in = True
    with pytest.raises(Refusal) as failure:
        transport.execute(request(dta_config, op))
    assert "SYNTH_PRIVATE_MARKER" not in str(failure.value)
    assert "SYNTH_NON_SECRET_VALUE" not in str(failure.value)
    assert "https://" not in str(failure.value)
    if op == "library.mount":
        assert isinstance(failure.value, Uncertain)


def test_login_requires_cookie_and_no_redirect(dta_config):
    class NoCookie:
        def open(self, req, timeout):
            return HTTPResponse(req.full_url, b"<login><status>OK</status></login>")
    transport = RemoteTransport(dta_config, "SYNTH-TRANSPORT", Authorization(dta_config, True, dta_config.serial),
                                opener=NoCookie(), credentials=lambda name: "SYNTH_NON_SECRET_VALUE")
    with pytest.raises(Refusal, match="session cookie"):
        transport.execute(request(dta_config, "library.login"))
    with pytest.raises(Refusal, match="redirect"):
        NoRedirect().redirect_request(None, None, 302, None, None, "https://SYNTH-OTHER.invalid")


def test_bounded_subprocess_runner_on_synthetic_local_processes():
    result = run_bounded([sys.executable, "-c", "import sys; print('SYNTH OUT'); sys.stderr.write('SYNTH ERR'); sys.exit(3)"], 5)
    assert result.returncode == 3 and result.stdout == b"SYNTH OUT\n" and result.stderr == b"SYNTH ERR"
    assert result.summary()["stdout_sha256"] == hashlib.sha256(b"SYNTH OUT\n").hexdigest()
    with pytest.raises(Uncertain, match="output limit"):
        run_bounded([sys.executable, "-c", "print('SYNTH'*1000)"], 5, limit=20)
    with pytest.raises(Uncertain, match="timeout"):
        run_bounded([sys.executable, "-c", "import time; time.sleep(10)"], 0.05)
    with pytest.raises(Uncertain, match="SSH connection"):
        run_bounded([sys.executable, "-c", "raise SystemExit(255)"], 5)


def test_durable_intent_precedes_each_mutation(tmp_path, dta_config, dta_fixtures):
    from tapediag.dta_engine import Engine
    from tapediag.dta_fake import FakeTransport
    checked = []
    with Store(tmp_path / "run") as store:
        def inspect(fake, req):
            if req.write:
                state = json.loads((store.path / "state.json").read_text())
                audit = [json.loads(line) for line in (store.path / "audit.jsonl").read_text().splitlines()]
                assert state["pending"]["request"] == req.public()
                assert state["pending"]["acknowledged"] is False
                assert audit[-1]["event"] == "request.intent"
                assert audit[-1]["request"] == req.public()
                checked.append(req.op)
        fake = FakeTransport(dta_config, dta_fixtures, fault=inspect)
        engine = Engine(dta_config, "SYNTH-TRANSPORT", fake, Authorization(dta_config, True, dta_config.serial),
                        store, emit=lambda _: None, sleep=lambda _: None)
        engine.apply()
        assert len(checked) == 17
        assert "ENV:DTA_LIBRARY_PASSWORD" in (store.path / "audit.jsonl").read_text()
        assert "SYNTH_NON_SECRET_VALUE" not in (store.path / "audit.jsonl").read_text()


def archive_bytes(name="results/SYNTH-DRIVE-DTA.a.gz", kind=None, content=b"SYNTHETIC", size=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as tar:
        info = tarfile.TarInfo(name)
        if kind:
            info.type = kind
            info.linkname = "../SYNTH-NOT-A-FILE"
        info.size = len(content) if size is None else size
        tar.addfile(info, io.BytesIO(content))
    return output.getvalue()


@pytest.mark.parametrize("name,kind", [
    ("../SYNTH-DRIVE-DTA.a", None), ("/results/SYNTH-DRIVE-DTA.a", None),
    ("results/../SYNTH-DRIVE-DTA.a", None), ("results/nested/SYNTH-DRIVE-DTA.a", None),
    ("results/SYNTH-OTHER.a", None), ("logs/not-allowed.log", None),
    ("results/SYNTH-DRIVE-DTA.bad name", None), ("results/SYNTH-DRIVE-DTA.a", tarfile.SYMTYPE),
    ("results/SYNTH-DRIVE-DTA.a", tarfile.LNKTYPE), ("results/SYNTH-DRIVE-DTA.a", tarfile.FIFOTYPE),
    ("results/SYNTH-DRIVE-DTA.a", tarfile.CHRTYPE),
])
def test_collection_rejects_untrusted_tar_members(name, kind):
    with pytest.raises(Refusal):
        extract_collection(archive_bytes(name, kind), "SYNTH-DRIVE-DTA")


def test_collection_validates_and_never_extracts_paths():
    assert extract_collection(archive_bytes(), "SYNTH-DRIVE-DTA") == {"vendor-results-SYNTH-DRIVE-DTA.a.gz": b"SYNTHETIC"}
    with pytest.raises(Refusal):
        extract_collection(b"not an archive", "SYNTH-DRIVE-DTA")
    with pytest.raises(Refusal, match="no native"):
        extract_collection(archive_bytes("logs/metro.log"), "SYNTH-DRIVE-DTA")
    with pytest.raises(Refusal, match="64 MiB"):
        extract_collection(b"x" * (64 * 1024 * 1024 + 1), "SYNTH-DRIVE-DTA")


def test_store_lock_permissions_and_symlink_boundary(tmp_path):
    directory = tmp_path / "run"
    with Store(directory) as store:
        store.event("synthetic")
        store.state = {"synthetic": True}
        store.save()
        assert directory.stat().st_mode & 0o777 == 0o700
        assert (directory / "state.json").stat().st_mode & 0o777 == 0o600
        with pytest.raises(Refusal, match="locked"):
            Store(directory, resume=True)
        with pytest.raises(Refusal, match="must not exist"):
            Store(directory)
        (directory / "bad.txt").symlink_to(directory / "state.json")
        with pytest.raises(Refusal):
            store.write("bad.txt", "SYNTH")
        for name in ("../bad", "lock", "audit.jsonl"):
            with pytest.raises(Refusal):
                store.write(name, "SYNTH")
    with Store(directory, resume=True) as store:
        assert store.state["synthetic"] is True
    alias = tmp_path / "alias"
    alias.symlink_to(directory)
    with pytest.raises(Refusal, match="symlinks"):
        Store(alias, resume=True)


@pytest.mark.parametrize("mutation", ["truncate", "event", "anchor", "sequence"])
def test_checkpoint_audit_corruption_refuses(tmp_path, mutation):
    path = tmp_path / "run"
    with Store(path) as store:
        store.event("synthetic")
        store.state = {"synthetic": True}
        store.save()
    audit = path / "audit.jsonl"
    if mutation == "truncate":
        audit.write_bytes(audit.read_bytes()[:-1])
    elif mutation == "event":
        audit.write_text(audit.read_text().replace('"synthetic"', '"tampered"'))
    elif mutation == "sequence":
        audit.write_text(audit.read_text().replace('"sequence":1', '"sequence":2'))
    else:
        state = json.loads((path / "state.json").read_text())
        state["audit_hash"] = "f" * 64
        (path / "state.json").write_text(json.dumps(state))
    with pytest.raises(Refusal):
        Store(path, resume=True)


def test_local_evidence_reader_refuses_symlinks_and_oversize(tmp_path):
    target = tmp_path / "synthetic.txt"
    target.write_text("SYNTHETIC")
    alias = tmp_path / "alias.txt"
    alias.symlink_to(target)
    with pytest.raises(Refusal):
        read_regular(alias)
    with pytest.raises(Refusal):
        read_regular(target, limit=1)
    with pytest.raises(Refusal):
        read_regular(tmp_path)


def test_bounded_runner_times_out_even_after_remote_pipes_close(monkeypatch):
    original_popen = subprocess.Popen

    def launch_with_pipes_already_closed(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        # Synchronize actual pipe EOF before run_bounded starts its deadline;
        # interpreter startup speed must not choose which timeout path we test.
        assert child.stdout.read() == child.stderr.read() == b""
        assert child.poll() is None
        return child

    monkeypatch.setattr(subprocess, "Popen", launch_with_pipes_already_closed)
    with pytest.raises(Uncertain, match="pipe close"):
        run_bounded([sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(10)"], 0.5)


def test_runner_preserves_agent_socket_reference_but_not_unrelated_environment(monkeypatch):
    monkeypatch.setenv("SSH_AUTH_SOCK", "/SYNTH/agent.sock")
    monkeypatch.setenv("SYNTH_UNRELATED_ENV", "SYNTH_VALUE")
    result = run_bounded([sys.executable, "-c", "import os; print(os.environ.get('SSH_AUTH_SOCK')); print(os.environ.get('SYNTH_UNRELATED_ENV'))"], 5)
    assert result.stdout == b"/SYNTH/agent.sock\nNone\n"
