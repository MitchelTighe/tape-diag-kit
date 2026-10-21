import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tapediag.cli import main
from tapediag.safety import Runner
from tapediag.validation import report_schema
from test_report import FixtureRunner


@pytest.mark.parametrize("command,filename,key", [
    ("inventory", "inventory.txt", "devices"),
    ("tapealert", "tapealert-set.txt", "active_flags"),
    ("logpages", "logpages.txt", "pages"),
    ("drive-status", "drive-status.txt", "density"),
    ("library", "library.txt", "drives"),
    ("ltfs", "ltfs.txt", "devices"),
    ("itdt", "itdt-scan.txt", "devices"),
])
def test_main_fixture_emits_visible_json(command, filename, key, fixtures, capsys, monkeypatch):
    monkeypatch.setattr(Runner, "run", lambda *a: pytest.fail("offline command attempted execution"))
    assert main([command, "--from-file", str(fixtures / "synthetic" / filename)]) == 0
    visible = capsys.readouterr()
    assert visible.err == "" and key in json.loads(visible.out)


def test_tapealert_default_dry_run_exact_plan(capsys, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("dry-run executed a command"))
    assert main(["tapealert", "/dev/sg9"]) == 0
    assert json.loads(capsys.readouterr().out) == [["sg_logs", "--readonly", "--page=0x2e", "/dev/sg9"]]


def test_report_main_emits_valid_v1_json(fixtures, capsys):
    assert main(["report", "--schema-version", "1.0", "--from-dir", str(fixtures / "sample-host")]) == 0
    result = json.loads(capsys.readouterr().out)
    Draft202012Validator(report_schema()).validate(result)
    assert result["errors"] == []


def test_report_from_file_roundtrip(report, tmp_path, capsys):
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(report))
    assert main(["report", "--from-file", str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == report


@pytest.mark.parametrize("argv", [
    ["itdt"], ["itdt", "--execute"], ["tapealert"],
    ["tapealert", "/dev/sg9;erase"], ["library", "/dev/st0"],
    ["report", "--nst", "/dev/nst0"], ["report", "--schema-version", "1.0", "--from-dir", "/missing", "--execute"],
    ["drive-status", "/dev/sg9", "--nst", "/dev/st0"],
])
def test_invalid_request_emits_json_error(argv, capsys):
    assert main(argv) == 2
    assert "error" in json.loads(capsys.readouterr().err)


def test_offline_execute_combination_refused(fixtures, capsys):
    assert main(["inventory", "--execute", "--from-file", str(fixtures / "synthetic/inventory.txt")]) == 2
    assert "cannot be combined" in json.loads(capsys.readouterr().err)["error"]


@pytest.mark.parametrize("value", ["nan", "inf", "0", "301"])
def test_cli_invalid_timeout(value, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["tapealert", "/dev/sg9", "--timeout", value])
    assert exc.value.code == 2
    assert "timeout" in capsys.readouterr().err


def test_execute_option_before_or_after_subcommand(fixtures, capsys, monkeypatch):
    for argv in (["--execute", "tapealert", "/dev/sg9"], ["tapealert", "/dev/sg9", "--execute"]):
        runner = FixtureRunner(fixtures)
        monkeypatch.setattr("tapediag.cli.Runner", lambda *a: runner)
        assert main(argv) == 0
        result = json.loads(capsys.readouterr().out)
        assert len(result["data"]["active_flags"]) == 4
        assert result["commands"][0]["returncode"] == 0


def test_failed_live_cli_returns_nonzero_and_keeps_details(fixtures, capsys, monkeypatch):
    monkeypatch.setattr("tapediag.cli.Runner", lambda *a: FixtureRunner(fixtures, failures=("sg_logs",)))
    assert main(["tapealert", "/dev/sg9", "--execute"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["data"] is None and result["errors"]


def test_report_partial_directory_exits_one(tmp_path, capsys):
    assert main(["report", "--schema-version", "1.0", "--from-dir", str(tmp_path)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["inventory"] is None and result["errors"]
    Draft202012Validator(report_schema()).validate(result)


def test_sysfs_dry_run_does_not_read_sysfs(monkeypatch, capsys):
    monkeypatch.setattr("tapediag.cli.inventory_sysfs", lambda *a: pytest.fail("dry-run read sysfs"))
    assert main(["inventory", "--source", "sysfs"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_destructive_cli_request_refused(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["library", "/dev/sg10", "--execute", "load", "1"])
    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_source_entrypoint_and_python_module(fixtures):
    root = Path(__file__).resolve().parents[1]
    for prefix in ([str(root / "bin/tapediag")], [sys.executable, "-m", "tapediag"]):
        result = subprocess.run(prefix + ["tapealert", "--from-file", str(fixtures / "synthetic/tapealert-set.txt")], cwd=root, capture_output=True, text=True, timeout=10, check=False)
        assert result.returncode == 0 and result.stderr == ""
        assert [f["flag"] for f in json.loads(result.stdout)["active_flags"]] == [3, 4, 5, 20]


def test_ltfs_requested_device_filters_global_listing(fixtures, capsys):
    source = str(fixtures / "synthetic/ltfs.txt")
    assert main(["ltfs", "/dev/sg9", "--from-file", source]) == 0
    assert len(json.loads(capsys.readouterr().out)["devices"]) == 1
    assert main(["ltfs", "/dev/sg99", "--from-file", source]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["devices"] and any("requested device" in w for w in result["warnings"])
