import os
import subprocess
from types import SimpleNamespace

import pytest

from tapediag.report import planned_report
from tapediag.safety import Runner, SafetyError, validate_command

DESTRUCTIVE = [
    ["mt", "-f", "/dev/nst0", op] for op in ("rewind", "offline", "unload", "erase", "fsf", "weof", "setblk")
] + [
    ["mtx", "-f", "/dev/sg10", op] for op in ("load", "unload", "inventory", "transfer", "first", "next", "eepos")
] + [
    ["sg_raw", "/dev/sg9", "0a", "00"],
    ["sg_format", "/dev/sg9"], ["sg_write_buffer", "/dev/sg9"],
    ["sg_modes", "--select", "/dev/sg9"], ["itdt", "scan"],
    ["mkltfs", "-d", "/dev/sg9"], ["ltfsck", "--check", "/dev/sg9"],
    ["ltfs", "-o", "devname=/dev/sg9", "/mnt/tape"],
    ["sg_logs", "--readonly", "--reset", "--page=0x2e", "/dev/sg9"],
    ["sg_logs", "--readonly", "--select", "/dev/sg9"],
    ["sg_logs", "--readonly", "--page=0x2e", "/dev/sg9", "--sp"],
    ["sg_logs", "--readonly", "--page=0x3f", "/dev/sg9"],
    ["mt", "-f", "/dev/st0", "status"],
    ["mtx", "-f", "/dev/sg10", "status", "load", "1"],
    ["/tmp/sg_inq", "/dev/sg9"], ["sg_inq", "/dev/sg9;erase"],
    ["sg_turs", "--num=1000000", "/dev/sg9"],
    ["sh", "-c", "sg_inq /dev/sg9"],
    ["sg_logs", "--readonly", "--page=0x2e", "--help"],
    [], "sg_inq /dev/sg9", [None],
]


@pytest.mark.parametrize("argv", DESTRUCTIVE)
def test_allowlist_refuses_destructive_or_unrecognized_argv(argv, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("refused command reached subprocess")
    monkeypatch.setattr(subprocess, "run", unexpected)
    with pytest.raises(SafetyError):
        Runner(execute=True).run(argv)


@pytest.mark.parametrize("argv", planned_report(["/dev/sg9"], ["/dev/sg10"], "/dev/nst0") + [["mtx", "-f", "/dev/sg10", "inquiry"]])
def test_all_planned_commands_are_allowlisted(argv):
    assert validate_command(argv) == argv


def test_dry_run_does_not_resolve_or_execute(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("dry-run attempted external work")
    monkeypatch.setattr("tapediag.safety.shutil.which", unexpected)
    monkeypatch.setattr(subprocess, "run", unexpected)
    result = Runner().run(["sg_inq", "/dev/sg9"])
    assert result.argv == ["sg_inq", "/dev/sg9"]
    assert result.returncode is None


def test_execute_has_timeout_no_shell_and_sanitized_environment(monkeypatch):
    seen = {}
    monkeypatch.setenv("SG3_UTILS_OLD_OPTS", "1")
    monkeypatch.setenv("TAPE", "/dev/st0")
    monkeypatch.setattr("tapediag.safety.shutil.which", lambda name, path: "/usr/bin/" + name)
    def run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    result = Runner(True, 2.5).run(["sg_inq", "/dev/sg9"])
    assert result.ok and result.stdout == "ok"
    assert seen["timeout"] == 2.5 and seen["shell"] is False
    assert seen["stdin"] == subprocess.DEVNULL
    assert seen["argv"] == ["/usr/bin/sg_inq", "/dev/sg9"]
    assert seen["env"] == {"PATH": "/usr/bin:/bin:/usr/local/bin", "LC_ALL": "C", "LANG": "C"}


@pytest.mark.parametrize("failure", ["missing", "timeout", "exit", "oserror"])
def test_execution_failure_is_structured(failure, monkeypatch):
    monkeypatch.setattr("tapediag.safety.shutil.which", lambda name, path: None if failure == "missing" else "/usr/bin/" + name)
    def run(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 1, output=b"partial", stderr=b"waiting")
        if failure == "oserror":
            raise PermissionError("synthetic permission denied")
        return SimpleNamespace(returncode=2, stdout="", stderr="not ready")
    monkeypatch.setattr(subprocess, "run", run)
    result = Runner(True, 1).run(["sg_turs", "/dev/sg9"])
    assert not result.ok and result.error
    if failure == "timeout":
        assert result.timed_out and result.stdout == "partial" and result.stderr == "waiting"
    if failure == "exit":
        assert result.returncode == 2 and result.stderr == "not ready"


def test_mt_refuses_rewinding_symlink(monkeypatch):
    monkeypatch.setattr("tapediag.safety.shutil.which", lambda name, path: "/usr/bin/mt")
    monkeypatch.setattr(os.path, "realpath", lambda p: "/dev/st0")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("rewinding alias executed"))
    result = Runner(True).run(["mt", "-f", "/dev/nst0", "status"])
    assert "non-rewinding" in result.error


@pytest.mark.parametrize("timeout", [0, -1, 301, float("nan"), float("inf")])
def test_invalid_timeouts(timeout):
    with pytest.raises(SafetyError):
        Runner(True, timeout)

# Public opcode names: https://t10.t10.org/lists/op-alph.htm (2026-10-18).
# There is deliberately no raw-CDB escape hatch, including for nominal reads.
@pytest.mark.parametrize('opcode', range(256), ids=lambda n:'cdb-%02x'%n)
def test_every_raw_opcode_refused_before_subprocess(opcode, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('raw opcode executed'))
    with pytest.raises(SafetyError):
        Runner(True).run(['sg_raw', '/dev/sg9', '%02x'%opcode] + ['00']*15)


@pytest.mark.parametrize('argv', [
    ['sg_dd','if=/dev/zero','of=/dev/sg9'],
    ['sg_write_same','/dev/sg9'], ['sg_write_long','/dev/sg9'],
    ['sg_write_attr','/dev/sg9'], ['sg_senddiag','/dev/sg9'],
    ['sg_start','--load','/dev/sg9'], ['sg_prevent','/dev/sg9'],
    ['sg_reset','/dev/sg9'], ['sg_persist','--out','/dev/sg9'],
    ['sg_read_buffer','--mode=err_hist','/dev/sg9'],
    ['sg_logs','--readonly','--page=0x02','--reset','/dev/sg9'],
    ['mt','-f','/dev/nst0','seek','0'],
    ['mtx','-f','/dev/sg20','erase'],
    ['mtx','-f','/dev/sg20','position','1'],
])
def test_v3_no_maintenance_dump_or_state_changing_utility_route(argv,monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('maintenance executed'))
    with pytest.raises(SafetyError):Runner(True).run(argv)
