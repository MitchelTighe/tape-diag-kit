import copy
import json

import pytest

from tapediag.history import load_series, log_trend, ordered_times
from tapediag.logsense import hex_bytes, parse_log_hex


def test_spec_layout_examples(fixtures):
    expected = {
        "2e": (64, "tapealert_1", False),
        "0c": (3, "host_write_bytes", 1024),
        "17": (5, "page_valid", True),
        "31": (4, "main_remaining_capacity", 1998976),
    }
    for page, (count, name, value) in expected.items():
        result = parse_log_hex((fixtures / ("v4/log-" + page + ".txt")).read_text(),
                               "lto5-6-capacity" if page == "31" else "ssc")
        assert len(result["parameters"]) == count
        assert result["parameters"][0]["name"] == name
        assert result["parameters"][0]["value"] == value
        assert not result["warnings"]
        assert result["sources"]


@pytest.mark.parametrize("text", [
    "", "2e", "2e 00 00", "2e 00 00 01", "2e 00 00 00 00",
    "2e 00 00 03 00 14 00", "2e 00 00 05 00 14 00 02 01",
    "2e 01 00 00", "2e 00 00 0a 00 14 00 01 00 00 14 00 01 01",
    "2e000000", "0x2e 00 00 00", "2e 00 GG 00", "2e 00 0 00",
    "0001: 2e 00 00 00", "0000: 2e 00\n0003: 00 00",
    "2e 00 00 00 |....|", "２ｅ 00 00 00", "2e 00 00 00\ninquiry",
])
def test_malformed_hex_refused(text):
    with pytest.raises(ValueError):
        parse_log_hex(text)


def test_offsets_comments_whitespace_and_case():
    result = parse_log_hex("# synthetic\n0000: 2E 00\n0002: 00 05 # header\n0004: 00 14 00 01 01\n")
    assert result["parameters"][0]["value"] is True
    assert result["parameters"][0]["code"] == 20


@pytest.mark.parametrize("profile", ["ssc", "lto5-6-capacity"])
def test_unknown_page_has_opaque_not_invented_parameter_layout(profile):
    result = parse_log_hex("3f 00 00 03 01 02 03", profile)
    assert result["raw_hex"] == "3f000003010203"
    assert result["parameters"] == []
    assert result["warnings"]


def test_vendor_profile_is_opt_in(fixtures):
    text = (fixtures / "v4/log-31.txt").read_text()
    assert parse_log_hex(text)["parameters"] == []
    rows = parse_log_hex(text, "lto5-6-capacity")["parameters"]
    assert rows[0]["unit"] == "MiB"
    assert rows[0]["kind"] == "gauge"


def test_unknown_parameter_and_subpage_are_preserved():
    unknown = parse_log_hex("0c 00 00 07 ff fe 00 03 41 42 43")
    assert unknown["parameters"][0]["value"] is None
    assert unknown["parameters"][0]["raw_hex"] == "414243"
    subpage = parse_log_hex("6e 01 00 05 00 14 00 01 01")
    assert subpage["parameters"] == []
    assert subpage["subpage"] == 1


@pytest.mark.parametrize("text", [
    "2e 00 00 05 00 14 00 01 02",  # reserved flag bits
    "2e 00 00 06 00 14 00 02 00 01",  # wrong width
    "2e 00 00 04 00 14 00 00",  # zero width
    "2e 00 00 05 00 14 01 01 01",  # unsupported format
    "0c 00 00 0d 00 00 00 09 00 00 00 00 00 00 00 00 01",
    "31 00 00 05 00 01 00 01 01",
])
def test_malformed_known_parameters_remain_unavailable(text):
    result = parse_log_hex(text, "lto5-6-capacity")
    assert result["parameters"][0]["value"] is None
    assert result["warnings"]


def test_large_uint_stays_exact_and_json_serializable():
    result = parse_log_hex("0c 00 00 0c 00 00 00 08 ff ff ff ff ff ff ff fe")
    value = result["parameters"][0]["value"]
    assert value == 2**64 - 2
    assert json.loads(json.dumps(result, allow_nan=False))["parameters"][0]["value"] == value


@pytest.mark.parametrize("valid", ["", "00 00 00 01 00"])
def test_volume_validity_required(valid):
    payload = (valid + " 00 04 00 01 02").strip()
    length = len(bytes.fromhex(payload))
    result = parse_log_hex("17 00 00 %02x " % length + payload)
    assert result["parameters"][-1]["value"] is None
    assert any("validity" in w for w in result["warnings"])


def test_volume_all_ones_capacity_is_unknown():
    result = parse_log_hex("17 00 00 0d 00 00 00 01 01 00 16 00 04 ff ff ff ff")
    assert result["parameters"][1]["value"] is None


@pytest.mark.parametrize("value", [None, 7, b"2e 00", "00 " * 65540, " " * (1024 * 1024 + 1)])
def test_hex_bounds(value):
    with pytest.raises(ValueError):
        hex_bytes(value)


def test_invalid_profile():
    with pytest.raises(ValueError):
        parse_log_hex("2e 00 00 00", "guess")


@pytest.fixture
def series(fixtures):
    return json.loads((fixtures / "v4/log-series.json").read_text())


def test_trend_counters_reset_media_and_states(series):
    original = copy.deepcopy(series)
    result = log_trend(series)
    rows = result["changes"]
    host = [r for r in rows if r["name"] == "host_write_bytes"]
    assert [r["delta"] for r in host] == [3072, 4096, None]
    assert host[-1]["kind"] == "reset-or-wrap"
    errors = [r for r in rows if r["name"] == "unrecovered_read_errors"]
    assert [r["delta"] for r in errors] == [2, 3, None]
    assert errors[-1]["kind"] == "medium-unconfirmed"
    assert any(r["name"] == "tapealert_20" and r["kind"] == "state-changed" for r in rows)
    assert all(r["delta"] is None for r in rows if "capacity" in r["name"])
    assert series == original


def test_missing_snapshot_breaks_counter_delta(series):
    series["snapshots"][1]["pages"] = []
    rows = log_trend(series)["changes"]
    assert all(r["delta"] is None for r in rows if r["name"] == "host_write_bytes")


def test_unknown_medium_disables_volume_deltas(series):
    for s in series["snapshots"]:
        s["medium_id"] = None
    rows = log_trend(series)["changes"]
    assert all(r["kind"] == "medium-unconfirmed" for r in rows if r["page"] == "0x17")
    assert next(r for r in rows if r["name"] == "host_write_bytes")["delta"] == 3072


def test_changed_encoding_breaks_counter_delta(series):
    series["snapshots"][1]["pages"][1]["hex"] = "0c 00 00 05 00 00 00 01 02"
    row = next(r for r in log_trend(series)["changes"] if r["name"] == "host_write_bytes")
    assert row["kind"] == "encoding-changed"
    assert row["delta"] is None


@pytest.mark.parametrize("value", [None, [], 0, {}, {"format": "unknown"}])
def test_invalid_series_root(value):
    with pytest.raises(ValueError):
        log_trend(value)


@pytest.mark.parametrize("field,value", [
    ("format", "v9"), ("page_control", "threshold"), ("asset_id", None),
    ("asset_id", ""), ("asset_id", "x" * 129), ("snapshots", []),
    ("snapshots", [{}] * 1001), ("snapshots", [None, None]),
])
def test_invalid_series_fields(series, field, value):
    series[field] = value
    with pytest.raises(ValueError):
        log_trend(series)


@pytest.mark.parametrize("field,value", [
    ("medium_id", []), ("medium_id", ""), ("pages", None),
    ("pages", [{}]), ("pages", [{"hex": None, "profile": "ssc"}]),
    ("pages", [{"hex": "2e 00 00 00", "profile": "ssc"}] * 33),
    ("captured_at", None), ("captured_at", "2026-10-16"), ("captured_at", "bad"),
])
def test_invalid_snapshot_fields(series, field, value):
    series["snapshots"][0][field] = value
    with pytest.raises(ValueError):
        log_trend(series)


def test_duplicate_page_refused(series):
    series["snapshots"][0]["pages"].append(series["snapshots"][0]["pages"][0])
    with pytest.raises(ValueError, match="duplicate page"):
        log_trend(series)


@pytest.mark.parametrize("times", [
    ["2026-10-16T00:00:00Z"] * 2,
    ["2026-10-17T00:00:00Z", "2026-10-16T00:00:00Z"],
    ["2026-10-16T00:00:00Z", "2026-10-16T01:00:00+01:00"],
])
def test_time_order(times):
    with pytest.raises(ValueError, match="increasing"):
        ordered_times(times)


@pytest.mark.parametrize("text", ['{"a": 1, "a": 2}', '{"v": NaN}', '[', "[" * 2000 + "]" * 2000],
                         ids=["duplicate", "nonfinite", "truncated", "deep"])
def test_manifest_json_errors_are_controlled(text):
    with pytest.raises(ValueError):
        load_series(text)


@pytest.mark.parametrize("time", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"])
def test_fuzz_regression_timestamp_utc_overflow(series, time):
    series["snapshots"][0]["captured_at"] = time
    with pytest.raises(ValueError, match="UTC range"):
        log_trend(series)


@pytest.mark.parametrize("text", ['{"v":1e9999}', '{"v":' + "[" * 65 + "0" + "]" * 65 + "}"])
def test_json_numeric_overflow_and_depth_refused(text):
    with pytest.raises(ValueError):
        load_series(text)
