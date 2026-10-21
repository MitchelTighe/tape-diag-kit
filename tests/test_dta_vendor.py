import copy
import json

import pytest

from tapediag.dta_config import Refusal
from tapediag.dta_vendor import (expand, find_drive, isolated_snapshot, isolation, library_identity,
                                 no_access, no_fabric_transactions, no_transactions, parse_cfgshow,
                                 parse_inquiry, parse_inventory, parse_move_result, parse_progress, parse_scan,
                                 parse_test, parse_version, validate_zoning, xml_root)


def test_scan_documented_default(dta_fixtures, dta_config):
    text = (dta_fixtures / "itdt-scan.txt").read_text()
    rows = parse_scan(text)
    assert len(rows) == 2
    found = find_drive(text, dta_config.serial, "/dev/sg9")
    assert found["changer"] == "SYNTH-CHANGER"
    assert found["host"] == "9" and found["target"] == "1"
    wrapped = text.replace("Generic-Device)", "Generic-\n    Device)")
    assert parse_scan(wrapped) == rows


@pytest.mark.parametrize("change", [
    lambda t: t.replace("Exit with code: 0", ""),
    lambda t: t.replace("Exit with code: 0", "Exit with code: 1"),
    lambda t: t + "unrecognized custom format\n",
    lambda t: t + "Exit with code: 0\n",
    lambda t: t.replace("#1", "#0"),
    lambda t: t.replace("/dev/sg10", "/dev/sg9"),
    lambda t: t.replace("S/N:", "Serial="),
    lambda t: t.replace("(Generic-Device)", ""),
    lambda t: t.replace("Scanning SCSI Bus ...", "WARNING: partial scan"),
    lambda t: "",
])
def test_scan_unknown_or_partial_refuses(dta_fixtures, change):
    with pytest.raises(Refusal):
        parse_scan(change((dta_fixtures / "itdt-scan.txt").read_text()))


@pytest.mark.parametrize("serial,device", [("SYNTH-WRONG", "/dev/sg9"), ("SYNTH-DRIVE-DTA", "/dev/sg8"),
                                           ("SYNTH-CHANGER", "/dev/sg10"), ("SYNTH-DRIVE-DTA", "/dev/st0")])
def test_find_exact_drive_refuses(dta_fixtures, serial, device):
    with pytest.raises(Refusal):
        find_drive((dta_fixtures / "itdt-scan.txt").read_text(), serial, device)


def test_multipath_duplicate_serial_refuses(dta_fixtures, dta_config):
    text = (dta_fixtures / "itdt-scan.txt").read_text().replace("SYNTH-CHANGER H", "SYNTH-DRIVE-DTA H")
    with pytest.raises(Refusal, match="exactly one"):
        find_drive(text, dta_config.serial, "/dev/sg9")


@pytest.mark.parametrize("text,code,success,reported", [
    ("Exit with code: 0\n", 0, True, 0),
    ("Exit with code: 6\n", 6, False, 6),
    ("Test Result: PASS\n", 0, False, None),
    ("Exit with code: 1\n", 0, False, 1),
    ("Exit with code: 0\nExit with code: 0\n", 0, False, None),
    ("", 0, False, None),
    ("Test Result: PASS\nExit with code: 6\n", 6, False, 6),
])
def test_test_parser_never_invents_hardware_pass(text, code, success, reported):
    result = parse_test(text, code)
    assert result["command_success"] is success
    assert result["reported_exit_code"] == reported
    assert result["hardware_verdict"] == "unknown"
    assert result["native_report_review_required"] is True


@pytest.mark.parametrize("version", ["9.6.1", "9.6.2.1", "10.0.0", "", "Graphical Edition Version: 9.6.2"])
def test_itdt_version_mismatch(version):
    with pytest.raises(Refusal):
        parse_version("ITDT-SE " + version, "9.6.2")


def test_version_and_identity_valid(dta_fixtures, dta_config):
    assert parse_version("IBM Tape Diagnostic Tool Standard Edition - Version: 9.6.2\n", "9.6.2") == "9.6.2"
    result = parse_inquiry((dta_fixtures / "itdt-inquiry.json").read_text(), dta_config.serial, dta_config.wwpns)
    assert result == {"serial": "SYNTH-DRIVE-DTA", "wwpn": "00:00:00:00:00:00:00:01"}


@pytest.mark.parametrize("text", ["Version: 9.6.2", "ITDT-GE Version: 9.6.2", "graphical edition Version: 9.6.2"])
def test_se_identity_cannot_be_inferred_from_version_number(text):
    with pytest.raises(Refusal):
        parse_version(text, "9.6.2")


def test_duplicate_inquiry_identity_field_refused(dta_fixtures, dta_config):
    text = (dta_fixtures / "itdt-inquiry.json").read_text().replace('"serialNumberDrive":', '"serialNumberDrive":"SYNTH-OTHER", "serialNumberDrive":')
    with pytest.raises(Refusal):
        parse_inquiry(text, dta_config.serial, dta_config.wwpns)


@pytest.mark.parametrize("field,value", [("serialNumberDrive", "SYNTH-OTHER"), ("worldWidePortName", "0000000000000099"),
                                         ("worldWidePortName", "bad"), ("pageCode", 128),
                                         ("vendorIdentification", "OTHER")])
def test_inquiry_identity_refuses(dta_fixtures, dta_config, field, value):
    doc = json.loads((dta_fixtures / "itdt-inquiry.json").read_text())
    doc["data"][field] = value
    with pytest.raises(Refusal):
        parse_inquiry(json.dumps(doc), dta_config.serial, dta_config.wwpns)


@pytest.mark.parametrize("status", ["OK", "ACTIVE", "SUBMITTED", "QUEUE", "FAILED"])
def test_documented_library_progress_states(status):
    assert parse_progress("<progress><status>" + status + "</status></progress>") == status


@pytest.mark.parametrize("text", ["<error><status>OK</status></error>", "<progress><status>UNKNOWN</status></progress>",
                                  "<progress/>", "<progress><status>OK</status><status>OK</status></progress>",
                                  '<!DOCTYPE x [<!ENTITY y "OK">]><progress><status>&y;</status></progress>',
                                  "<progress><status>OK</progress>"])
def test_unknown_xml_or_progress_refused(text):
    with pytest.raises(Refusal):
        parse_progress(text)


def test_inventory_offsets_and_home(dta_fixtures):
    home = parse_inventory((dta_fixtures / "inventory-home.xml").read_text(), "SYNTH TEST")
    loaded = parse_inventory((dta_fixtures / "inventory-loaded.xml").read_text(), "SYNTH TEST")
    assert home["storageSlot"][7]["id"] == 4102
    assert loaded["drive"][1]["id"] == 256
    assert loaded["drive"][1]["barcode"] == "SYNTH-TEST-L9"
    assert loaded["storageSlot"][7]["full"] is False


@pytest.mark.parametrize("before,after", [("SYNTH TEST", "SYNTH OTHER"), ("<full>yes", "<full>unknown"),
                                         ("<isQueued>no", "<isQueued>yes"), ("<offset>7", "<offset>-1"),
                                         ("<offset>7</offset>", ""), ("<barcode>SYNTH-TEST-L9</barcode>", ""),
                                         ("<full>yes</full>", "<full>yes</full><full>yes</full>")])
def test_ambiguous_inventory_refuses(dta_fixtures, before, after):
    text = (dta_fixtures / "inventory-home.xml").read_text().replace(before, after)
    with pytest.raises(Refusal):
        parse_inventory(text, "SYNTH TEST")


@pytest.mark.parametrize("before,after", [("SYNTH-DRIVE-DTA", "SYNTH-WRONG"), ("<driveStatus>OK", "<driveStatus>unknown"),
                                         ("<partitionDriveNumber>1", "<partitionDriveNumber>2"),
                                         ("SYNTH TEST", "SYNTH OTHER"), ("FR1/DBA1/fLTO-DRV1", "FR1/DBA1/fLTO-DRV2")])
def test_library_drive_mapping_refuses(dta_fixtures, dta_config, before, after):
    text = (dta_fixtures / "drive-list.xml").read_text()
    assert library_identity(text, dta_config)
    with pytest.raises(Refusal):
        library_identity(text.replace(before, after), dta_config)


def test_zoning_alias_expansion_and_exact_rollback(dta_fixtures, dta_config):
    sw = dta_config.switches[0]
    initial = parse_cfgshow((dta_fixtures / "switch-a.txt").read_text())
    expected = copy.deepcopy(initial)
    isolated = isolated_snapshot(initial, dta_config, sw)
    assert initial == expected  # Planning must never mutate baseline.
    assert isolated["defined"]["zone"]["SYNTH_PROD_A"] == ["00:00:00:00:00:00:00:11"]
    assert isolation(isolated, dta_config, sw)
    with pytest.raises(Refusal, match="production zone"):
        isolation(initial, dta_config, sw)


def test_library_replacement_cannot_hide_behind_location_serial(dta_fixtures, dta_config):
    text = (dta_fixtures / "drive-list.xml").read_text()
    assert "<serialNumber>SYNTH-DRIVE-DTA</serialNumber>" in text
    with pytest.raises(Refusal, match="manufacturer serial"):
        library_identity(text.replace("SYNTH-PHYSICAL-DTA", "SYNTH-PHYSICAL-REPLACEMENT"), dta_config)
    with pytest.raises(Refusal, match="port-A"):
        library_identity(text.replace("0000000000000001", "0000000000000099"), dta_config)


def test_move_result_requires_exact_successful_route(dta_config):
    message = "Move barcode SYNTH-TEST-L9 from Slot 7 to Drive 1 Successful"
    body = "<inventory><moveResult>" + message + "</moveResult></inventory>"
    result = parse_move_result(body, dta_config, False)
    assert result["source_offset"] == 7 and result["destination_offset"] == 1
    nested = "<inventory><moveResult><message>" + message + "</message></moveResult></inventory>"
    assert parse_move_result(nested, dta_config, False) == result
    for wrong in (body.replace("Successful", "Failed"), body.replace("Slot 7", "Slot 8"),
                  body.replace("Drive 1", "Drive 2"), body.replace("SYNTH-TEST-L9", "SYNTH-OTHER-L9"),
                  "<inventory><moveResult/></inventory>", "<inventory/>"):
        with pytest.raises(Refusal):
            parse_move_result(wrong, dta_config, False)


def test_progress_must_be_for_this_move():
    for body in ("<progress><status>OK</status></progress>",
                 "<progress><activePage>package.xml</activePage><status>OK</status></progress>"):
        with pytest.raises(Refusal):
            parse_progress(body, expected_page="inventory.xml")


def test_standard_xml_declaration_allowed_but_entities_and_other_pis_refused():
    assert xml_root('<?xml version="1.0" encoding="UTF-8"?><logout/>', "logout").tag == "logout"
    for body in ('<?xml version="1.0"?><?SYNTH command?><logout/>',
                 '<?xml version="1.0"?><!DOCTYPE x><logout/>'):
        with pytest.raises(Refusal):
            xml_root(body, "logout")


@pytest.mark.parametrize("change", [
    lambda t: t.replace("Effective configuration:", ""),
    lambda t: t.replace("Effective configuration:", "Effective configuration:\nNo Effective configuration"),
    lambda t: t.replace("alias: SYNTH_DRIVE_A", "alias: SYNTH_DRIVE_A --peerzone"),
    lambda t: t + "unexpected warning\n",
    lambda t: t.replace("SYNTH_PROD_A; SYNTH_DIAG_A", "SYNTH_MISSING; SYNTH_DIAG_A"),
    lambda t: t.replace("alias: SYNTH_DRIVE_A 00:00:00:00:00:00:00:01; 1,1", "alias: SYNTH_DRIVE_A SYNTH_NESTED"),
    lambda t: t.replace("cfg: SYNTH_CFG_A\n", "cfg: SYNTH_WRONG\n"),
    lambda t: t.replace("zone: SYNTH_PROD_A\n  00:00:00:00:00:00:00:01", "zone: SYNTH_PROD_A\n  00:00:00:00:00:00:00:99"),
    lambda t: t.replace("cfg: SYNTH_CFG_A\n", "cfg: SYNTH_CFG_A\ncfg: SYNTH_EXTRA\n"),
])
def test_unknown_or_inconsistent_zoning_refuses(dta_fixtures, dta_config, change):
    text = change((dta_fixtures / "switch-a.txt").read_text())
    with pytest.raises(Refusal):
        validate_zoning(parse_cfgshow(text), dta_config.switches[0])


def test_unlisted_inactive_zone_still_prevents_test(dta_fixtures, dta_config):
    initial = parse_cfgshow((dta_fixtures / "switch-a.txt").read_text())
    initial["defined"]["zone"]["SYNTH_FORGOTTEN"] = ["00:00:00:00:00:00:00:01"]
    with pytest.raises(Refusal, match="production zone"):
        isolated_snapshot(initial, dta_config, dta_config.switches[0])


def test_zone_last_member_deletion_and_shared_alias_refuse(dta_fixtures, dta_config):
    initial = parse_cfgshow((dta_fixtures / "switch-a.txt").read_text())
    initial["defined"]["zone"]["SYNTH_PROD_A"] = ["SYNTH_DRIVE_A"]
    initial["effective"]["zone"]["SYNTH_PROD_A"] = ["00:00:00:00:00:00:00:01", "1,1"]
    with pytest.raises(Refusal, match="last member"):
        isolated_snapshot(initial, dta_config, dta_config.switches[0])
    initial = parse_cfgshow((dta_fixtures / "switch-a.txt").read_text())
    initial["defined"]["alias"]["SYNTH_DRIVE_A"].append("00:00:00:00:00:00:00:99")
    for values in initial["effective"]["zone"].values():
        values.append("00:00:00:00:00:00:00:99")
    with pytest.raises(Refusal, match="only the configured"):
        isolated_snapshot(initial, dta_config, dta_config.switches[0])


@pytest.mark.parametrize("text", ["", "Default Zone Access Mode\ncommitted - All Access\ntransaction - No Transaction", "No Access"])
def test_default_zone_unknown_or_allaccess_refuses(text):
    with pytest.raises(Refusal):
        no_access(text)


@pytest.mark.parametrize("text", ["", "Current transaction token is 1\nIt is abortable", "There is no outstanding zone transaction\nWARNING"])
def test_local_transaction_unknown_or_active_refuses(text):
    with pytest.raises(Refusal):
        no_transactions(text)


def test_fabric_transaction_table_strict():
    base = "There is no outstanding zone transaction\nTransactions Detect: Capable\nCurrent Open Transactions\nDomain List:\n-----\n"
    no_fabric_transactions(base)
    for text in (base + "1\n", base.replace("Capable", "Incapable"), "There is no outstanding zone transaction"):
        with pytest.raises(Refusal):
            no_fabric_transactions(text)
