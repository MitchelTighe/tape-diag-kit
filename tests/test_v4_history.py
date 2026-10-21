import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from tapediag.history import tapealert_history
from tapediag.tapealert import parse_tapealert
from tapediag.v3 import refresh


@pytest.fixture
def reports(fixtures):
    return [json.loads((fixtures / ("v4/alerts-%d.json" % day)).read_text())
            for day in range(16, 20)]


def test_gaps_do_not_clear_alerts(reports):
    original = copy.deepcopy(reports)
    result = tapealert_history(reports)
    events = [e for e in result["events"] if e["flag"] == 20 and e["stream"] == "tapealert"]
    assert [e["kind"] for e in events] == ["activated", "coverage-lost", "inactive-observed"]
    stream = result["assets"][0]["streams"]["tapealert"]
    assert 20 in stream[2]["unknown"]
    assert 20 in stream[3]["inactive"]
    assert result["sources"]
    assert reports == original


def test_observed_clear_and_recurring_activation(reports):
    reports[2]["drives"][0]["tapealert"] = parse_tapealert("Flag 20: 0")
    reports[3]["drives"][0]["tapealert"] = parse_tapealert("Flag 20: 1")
    for report in reports:
        refresh(report)
    events = [e["kind"] for e in tapealert_history(reports)["events"] if e["flag"] == 20]
    assert events == ["activated", "cleared", "activated"]


def test_response_is_separate_from_latched_flags(reports):
    response = parse_tapealert("Flag 20: 0")
    response["page"] = "0x12"
    reports[1]["drives"][0]["tapealert_response"] = response
    refresh(reports[1])
    result = tapealert_history(reports)
    assert any(e["stream"] == "tapealert_response" and e["kind"] == "inactive-observed"
               for e in result["events"])
    assert any(e["stream"] == "tapealert" and e["kind"] == "activated" for e in result["events"])


def test_missing_asset_breaks_history(reports):
    reports[2]["drives"] = []
    refresh(reports[2])
    result = tapealert_history(reports)
    states = result["assets"][0]["streams"]["tapealert"][2]
    assert len(states["unknown"]) == 64
    assert not states["inactive"]


def test_conflicting_capture_cannot_establish_clear(reports):
    reports[2]["drives"][0]["tapealert"] = parse_tapealert("Flag 20: 1\nFlag 20: 0")
    refresh(reports[2])
    result = tapealert_history(reports)
    assert not any(e["kind"] == "cleared" for e in result["events"])
    assert 20 in result["assets"][0]["streams"]["tapealert"][2]["unknown"]


def test_history_requires_matching_fleet(reports):
    reports[-1]["fleet_id"] = "SYNTH-OTHER"
    with pytest.raises(ValueError, match="fleet_id"):
        tapealert_history(reports)


@pytest.mark.parametrize("kind", ["missing", "same", "reverse"])
def test_history_requires_known_increasing_time(reports, kind):
    if kind == "missing":
        reports[0]["captured_at"] = None
    elif kind == "same":
        reports[1]["captured_at"] = reports[0]["captured_at"]
    else:
        reports.reverse()
    with pytest.raises(ValueError):
        tapealert_history(reports)


@pytest.mark.parametrize("reports", [[], [{}], None, [{}] * 1001])
def test_history_count_limits(reports):
    with pytest.raises(ValueError):
        tapealert_history(reports)


def test_device_path_warning(reports):
    for report in reports:
        drive = report["drives"][0]
        drive["identity_basis"] = "device-path"
        drive["asset_id"] = "drive:" + drive["device"]
    assert any("device-path" in w for w in tapealert_history(reports)["warnings"])


@pytest.mark.parametrize("time", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"])
def test_fuzz_regression_report_timestamp_utc_overflow(reports, time):
    reports[0]["captured_at"] = time
    with pytest.raises(ValueError, match="UTC range"):
        tapealert_history(reports)


def test_history_bounds_asset_snapshot_expansion(reports):
    # Small inputs with changing identities must not expand without an output
    # budget into an asset-by-time grid of 64 unknown flags per stream.
    captures = []
    start = datetime(2026, 10, 16, tzinfo=timezone.utc)
    for index in range(101):
        report = copy.deepcopy(reports[0])
        report["captured_at"] = (start + timedelta(minutes=index)).isoformat()
        report["drives"][0]["asset_id"] = "SYNTH-HISTORY-%d" % index
        captures.append(report)
    with pytest.raises(ValueError, match="10000 asset-snapshot"):
        tapealert_history(captures)
