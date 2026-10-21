import copy
import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tapediag.report import live_report, offline_report, read_capture, saved_report
from tapediag.safety import CommandResult, Runner, validate_command
from tapediag.validation import report_schema, validate_report


def test_report_golden_and_independent_schema(report, fixtures):
    assert report == json.loads((fixtures / "golden/sample-host.report.json").read_text())
    Draft202012Validator.check_schema(report_schema())
    Draft202012Validator(report_schema()).validate(report)
    assert validate_report(report) == report
    assert report["errors"] == []
    assert len(report["drives"]) == 1 and len(report["libraries"]) == 1
    assert report["mode"] == "offline" and report["commands"] == []


def test_distributable_schema_matches_public_schema():
    root = Path(__file__).resolve().parents[1]
    assert (root / "schema/tapediag-report.v1.json").read_bytes() == (root / "tapediag/report_schema.json").read_bytes()


@pytest.mark.parametrize("change", [
    lambda r: r.update(schema_version="9.0"),
    lambda r: r.update(secret="unexpected"),
    lambda r: r.pop("inventory"),
    lambda r: r["drives"][0]["drive_status"].update(online="yes"),
    lambda r: r["drives"][0]["tapealert"]["active_flags"][0].update(flag=65),
    lambda r: r["drives"][0]["tapealert"]["observed_flags"].append(1),
    lambda r: r["drives"][0]["tapealert"]["active_flags"][0].update(active=1),
    lambda r: r["drives"][0]["tapealert"]["active_flags"][0].update(severity="Unknown"),
])
def test_invalid_reports_are_rejected_by_both_validators(report, change):
    change(report)
    assert list(Draft202012Validator(report_schema()).iter_errors(report))
    with pytest.raises(ValueError, match="invalid v1 report|unsupported schema version"):
        validate_report(report)


def test_report_missing_capture_is_partial_and_still_valid(tmp_path, fixtures):
    dest = tmp_path / "capture"
    shutil.copytree(fixtures / "sample-host", dest)
    (dest / "drives/sg9/tapealert.txt").unlink()
    result = offline_report(dest)
    assert result["drives"][0]["tapealert"] is None
    assert result["errors"][0]["section"] == "tapealert"
    Draft202012Validator(report_schema()).validate(result)


def test_inventory_capture_gap_is_explicit(tmp_path, fixtures):
    (tmp_path / "inventory.txt").write_text((fixtures / "synthetic/inventory.txt").read_text())
    result = offline_report(tmp_path)
    assert len(result["errors"]) == 2
    assert all(e["section"] == "capture" for e in result["errors"])


def test_saved_report_roundtrip(report, tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    assert saved_report(path) == report
    path.write_text('{"schema_version":"1.0"}')
    with pytest.raises(ValueError):
        saved_report(path)


def test_non_files_and_oversized_captures_refused(tmp_path):
    with pytest.raises(ValueError, match="regular file"):
        read_capture(tmp_path)
    path = tmp_path / "large"
    with path.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="16 MiB"):
        read_capture(path)


class FixtureRunner(Runner):
    """Exercise live orchestration using saved outputs, without any subprocess."""
    def __init__(self, fixtures, failures=()):
        super().__init__(True)
        self.fixtures = fixtures
        self.failures = failures

    def run(self, argv):
        validate_command(argv)
        binary = argv[0]
        result = CommandResult(list(argv), returncode=0)
        if binary in self.failures:
            result.returncode = 2
            result.error = "synthetic command failure"
            result.stderr = "not ready" if binary == "sg_turs" else "synthetic unavailable"
        else:
            mapping = {"lsscsi": "inventory.txt", "sg_inq": "itdt-inquiry.txt", "mt": "drive-status.txt", "mtx": "library.txt", "ltfs": "ltfs.txt"}
            if binary == "sg_logs":
                result.stdout = (self.fixtures / "synthetic" / ("tapealert-set.txt" if "0x2e" in argv[2] else "logpages.txt")).read_text()
            elif binary in mapping:
                result.stdout = (self.fixtures / "synthetic" / mapping[binary]).read_text()
            if binary == "ltfs":
                result.stderr, result.stdout = result.stdout, ""  # LTFS can log listing to stderr.
        self.results.append(result)
        return result


def test_live_report_orchestration_discovers_mappings(fixtures):
    runner = FixtureRunner(fixtures)
    result = live_report(runner)
    assert not result["errors"]
    assert result["mode"] == "execute"
    assert result["drives"][0]["drive_status"]["ready"] is True
    assert result["ltfs"]["devices"][0]["device"] == "/dev/sg9"
    assert ["mt", "-f", "/dev/nst0", "status"] in [r.argv for r in runner.results]
    assert len(result["commands"]) == 17
    Draft202012Validator(report_schema()).validate(result)


def test_live_failures_are_retained_and_report_still_valid(fixtures):
    runner = FixtureRunner(fixtures, failures=("sg_turs", "mtx", "ltfs"))
    result = live_report(runner)
    assert len(result["errors"]) == 3
    assert result["drives"][0]["drive_status"]["ready"] is False
    assert result["libraries"][0]["status"] is None
    assert result["ltfs"] is None
    validate_report(result)


def test_explicit_drive_without_mapping_never_guesses_nst(fixtures):
    result = live_report(FixtureRunner(fixtures), drives=["/dev/sg99"])
    assert not any(c["argv"][0] == "mt" for c in result["commands"])
    assert any("skipped" in w for w in result["drives"][0]["drive_status"]["warnings"])


def test_inventory_failure_uses_sysfs_fallback(fixtures, tmp_path):
    result = live_report(FixtureRunner(fixtures, failures=("lsscsi",)), sysfs_root=tmp_path)
    assert result["inventory"]["source"] == "sysfs"
    assert result["errors"][0]["section"] == "inventory"
    validate_report(result)
