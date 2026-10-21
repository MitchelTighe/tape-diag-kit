import json
from pathlib import Path

import pytest

from tapediag.parsers import (PARSERS, parse_drive_status, parse_inventory,
                             parse_itdt, parse_library, parse_logpages, parse_ltfs)
from tapediag.tapealert import catalog, parse_tapealert

CASES = json.loads((Path(__file__).resolve().parents[1] / "fixtures/cases.json").read_text())


@pytest.mark.parametrize("filename,command", CASES, ids=[c[0] for c in CASES])
def test_golden_capture(fixtures, filename, command):
    actual = PARSERS[command]((fixtures / filename).read_text())
    expected = json.loads((fixtures / "golden" / (filename.replace("/", "__") + ".json")).read_text())
    assert actual == expected


def test_alert_flags_and_severities(sample):
    result = parse_tapealert(sample("tapealert-set.txt"))
    assert [(f["flag"], f["name"], f["severity"]) for f in result["active_flags"]] == [
        (3, "Hard error", "Warning"), (4, "Media", "Critical"),
        (5, "Read failure", "Critical"), (20, "Clean now", "Critical")]
    assert result["observed_flags"] == list(range(1, 65))
    assert result["unobserved_flags"] == []
    assert result["warnings"] == []


def test_clear_vs_missing(sample):
    clear = parse_tapealert(sample("tapealert-clear.txt"))
    missing = parse_tapealert("")
    assert clear["inactive_flags"] == list(range(1, 65))
    assert missing["inactive_flags"] == []
    assert len(missing["unobserved_flags"]) == 64
    assert missing["warnings"] and not clear["warnings"]


def test_named_partial_alerts(sample):
    result = parse_tapealert(sample("tapealert-named.txt"))
    assert [f["flag"] for f in result["active_flags"]] == [3, 4, 5, 20]
    assert result["inactive_flags"] == [9]
    assert len(result["unobserved_flags"]) == 59


def test_alert_unknown_conflict_reserved(sample):
    result = parse_tapealert(sample("tapealert-numeric.txt"))
    assert result["unknown_flags"] == [{"flag": 65, "value": 1}, {"flag": 0, "value": 0}]
    assert [f["flag"] for f in result["active_flags"]] == [3, 4, 5, 20, 61]
    assert any("conflicting" in s for s in result["warnings"])
    assert any("banana" in s for s in result["warnings"])
    assert result["active_flags"][-1]["defined"] is False


def test_all_catalog_entries_are_addressable():
    rows = catalog()["flags"]
    assert [r["flag"] for r in rows] == list(range(1, 65))
    assert {r["severity"] for r in rows} == {"Critical", "Warning", "Info"}
    result = parse_tapealert("\n".join("Flag %d: 1" % i for i in range(1, 65)))
    assert len(result["active_flags"]) == 64
    assert all(row["action"] for row in result["active_flags"])
    assert all(url.startswith("https://") for url in result["sources"])


def test_inventory_filters_disks_and_maps_nonrewinding(sample):
    devices = parse_inventory(sample("inventory.txt"))["devices"]
    assert len(devices) == 2
    assert devices[0]["model"] == "LTO-DEMO DRIVE"
    assert devices[0]["generic_device"] == "/dev/sg9"
    assert devices[0]["nonrewinding_device"] == "/dev/nst0"
    assert devices[1]["kind"] == "changer"


def test_inventory_missing_mapping_and_bad_paths(sample):
    missing = parse_inventory(sample("inventory-missing-generic.txt"))
    assert missing["devices"][0]["generic_device"] is None
    bad = parse_inventory("[9:0:1:0] tape SYNTH MODEL 0001 /dev/st0 /dev/sg9;erase")
    assert not bad["devices"] and bad["warnings"]


def test_library_occupancy_barcode_ie_and_source_slot(sample):
    result = parse_library(sample("library.txt"))
    assert not result["warnings"]
    assert result["drives"][0]["source_slot"] == 2
    assert result["drives"][0]["barcode"] == "SYN001L8"
    assert not result["drives"][1]["full"]
    assert result["slots"][0]["alternate_barcode"] == "SYNALT01"
    assert result["slots"][2]["full"] and result["slots"][2]["barcode"] is None
    assert result["ie_ports"][0]["element"] == 4
    assert result["ie_ports"][0]["full"] and result["ie_ports"][0]["barcode"] is None


def test_library_truncation_and_duplicates(sample):
    result = parse_library(sample("library-truncated.txt") + "Storage Element 1:Empty\n")
    assert any("duplicate" in s for s in result["warnings"])
    assert any("drive count" in s for s in result["warnings"])
    assert any("storage count" in s for s in result["warnings"])


def test_synthetic_legacy_mtx_is_parsed(fixtures):
    result = parse_library((fixtures / "synthetic/library-legacy.txt").read_text())
    assert result["drives"][0]["element"] == 0
    assert not result["drives"][0]["full"]
    assert len(result["slots"]) == 4
    assert all(s["full"] for s in result["slots"])


def test_logpages_supported_parameters_and_units(sample):
    result = parse_logpages(sample("logpages.txt"))
    pages = {p["page"]: p for p in result["pages"]}
    assert list(pages) == ["0x00", "0x02", "0x03", "0x0c", "0x0d", "0x14", "0x17"]
    assert len(pages["0x00"]["supported_pages"]) == 8
    assert pages["0x03"]["parameters"][1]["value"] == 1
    assert pages["0x0d"]["parameters"][0] == {"name": "Current temperature", "value": 29, "unit": "C", "raw": "29 C"}
    assert pages["0x17"]["parameters"][1]["value"] == 12000000


def test_logpages_unknown_and_unavailable(sample):
    unknown = parse_logpages(sample("logpages-unknown.txt"))["pages"][0]
    assert unknown["known"] is False
    assert unknown["parameters"][0]["value"] == 0xf001
    assert unknown["raw_lines"] == ["00 01 02 fe"]
    assert parse_logpages(sample("logpages-unavailable.txt"))["pages"][0]["parameters"][0]["value"] is None


def test_logpage_subpage_and_reverse_supported_format():
    text = "Supported log pages [0x0]:\n  Temperature [0xd]\nVolume statistics [0x17,0x1]:\n"
    result = parse_logpages(text)
    # A header-looking line after page 0 remains a supported entry, not a page body.
    assert result["pages"][0]["supported_pages"][0]["page"] == "0x0d"


def test_no_page_header_is_explicitly_unknown():
    result = parse_logpages("unknown stuff\n")
    assert not result["pages"] and result["warnings"]
    assert result["preamble"] == ["unknown stuff"]


def test_status_density_position_and_protection(sample):
    result = parse_drive_status(sample("drive-status.txt"))
    assert result["density"] == 0x5e and result["density_description"] == "LTO-8"
    assert result["block_size"] == 0
    assert (result["file_number"], result["block_number"]) == (2, 17)
    assert result["online"] is True and result["write_protect"] is True
    assert result["ready"] is True
    assert result["status_flags"] == ["BOT", "ONLINE", "WR_PROT"]


def test_offline_status_and_missing_status_are_distinct(sample):
    offline = parse_drive_status(sample("drive-not-ready.txt"))
    unknown = parse_drive_status("Vendor identification: SYNTH\n")
    assert offline["online"] is False and offline["ready"] is False
    assert offline["write_protect"] is False and offline["file_number"] == -1
    assert unknown["online"] is None and unknown["write_protect"] is None


@pytest.mark.parametrize("code,expected", [(0, True), (2, False), (5, None), (-9, None)])
def test_tur_exit_code_semantics(code, expected):
    assert parse_drive_status("", tur_returncode=code)["ready"] is expected


def test_ltfs_record_with_upstream_vendor_typo(sample):
    result = parse_ltfs(sample("ltfs.txt"))
    assert result["devices"] == [{"device": "/dev/sg9", "vendor": "SYNTH", "product": "LTO-DEMO", "serial": "SYNTH-DRIVE-0001", "product_name": "[LTO-DEMO]"}]
    assert "skipped" in result["ltfsck"]


def test_itdt_scan_inquiry_and_alert_adapters(sample):
    scan = parse_itdt(sample("itdt-scan.txt"))
    assert len(scan["devices"]) == 2
    assert scan["devices"][0]["address"] == "9:0:1:0"
    assert scan["devices"][1]["driver"] == "Generic-Device"
    assert parse_itdt(sample("itdt-inquiry.txt"))["inquiry"] == {"vendor": "SYNTH", "product": "LTO-DEMO", "revision": "0001"}
    assert [f["flag"] for f in parse_itdt(sample("itdt-tapealert.txt"))["tapealert"]["active_flags"]] == [3, 4, 5, 20]


@pytest.mark.parametrize("name", list(PARSERS))
def test_empty_input_does_not_crash(name):
    result = PARSERS[name]("")
    assert isinstance(result, dict)


def test_logpage_hint_does_not_turn_inquiry_banner_into_an_extra_page():
    text = '    SYNTH LTO-DEMO 0001\nTemperature log page [0xd]:\n  Current temperature = 29 C\n'
    result = parse_logpages(text, '0x0d')
    assert len(result['pages']) == 1
    assert result['preamble'] == ['SYNTH LTO-DEMO 0001']
    assert result['pages'][0]['parameters'][0]['value'] == 29


def test_logpage_hint_supports_headerless_decoded_text():
    result = parse_logpages('  Current temperature = 29 C\n', '0x0d')
    assert len(result['pages']) == 1
    assert result['pages'][0]['page'] == '0x0d'
    assert result['pages'][0]['parameters'][0]['value'] == 29
