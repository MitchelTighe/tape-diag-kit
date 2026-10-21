"""Small fail-closed vendor grammars, grounded in docs/DTA-SOURCES.md.

Unknown output is evidence of incompatibility, never evidence of isolation or PASS.
Fixtures contain original synthetic identifiers only.
"""
import copy
import json
import re
import xml.etree.ElementTree as ET

from .dta_config import DEVICE, NAME, TOKEN, WWPN, PORT, Refusal, member, unique_json_object


def bounded(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > 4 * 1024 * 1024 or "\x00" in text:
        raise Refusal("invalid or oversized vendor text")
    return text


def parse_scan(text):
    """Default text scan, including optional Changer field and wrapped driver name.

    A device model, serial, HBTL and terminal exit marker are required. Custom
    -o formats and unsupported records are deliberately refused.
    """
    text = re.sub(r"\((IBM|Generic)-\s*\n\s*Device\)", r"(\1-Device)", bounded(text))
    pattern = re.compile(
        r"#(?P<index>\d+)\s+(?P<device>\S+)\s+-\s+\[(?P<model>[^\]\n]+)\]-"
        r"\[(?P<revision>[^\]\n]+)\]\s+S/N:(?P<serial>\S+)\s+"
        r"H(?P<host>\d+)-B(?P<bus>\d+)-T(?P<target>\d+)-L(?P<lun>\d+)"
        r"(?:\s+Changer:(?P<changer>\S+))?\s+\((?P<driver>IBM-Device|Generic-Device)\)"
    )
    rows = []
    code = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line == "Scanning SCSI Bus ...":
            continue
        end = re.fullmatch(r"Exit with code: (-?\d+)", line)
        if end:
            if code is not None:
                raise Refusal("duplicate scan exit marker")
            code = int(end[1])
            continue
        row = pattern.fullmatch(line)
        if not row or code is not None:
            raise Refusal("unsupported ITDT scan text; add a locally reviewed fixture")
        rows.append(row.groupdict())
    if code != 0 or not rows:
        raise Refusal("ITDT scan missing records or successful exit marker")
    if len({r["index"] for r in rows}) != len(rows) or len({r["device"] for r in rows}) != len(rows):
        raise Refusal("duplicate ITDT scan record")
    return rows


def find_drive(text, serial, device):
    rows = [r for r in parse_scan(text) if r["serial"] == serial]
    if len(rows) != 1 or rows[0]["device"] != device or not re.fullmatch(DEVICE, device):
        raise Refusal("serial must select exactly one configured non-rewinding drive path; multipath is refused")
    if not rows[0]["model"].startswith(("ULT", "LTO")):
        raise Refusal("selected scan record is not a supported IBM LTO tape drive")
    return rows[0]


def parse_version(text, expected):
    bounded(text)
    versions = re.findall(r"(?:Version\s*:?\s*|ITDT-SE\s+)(9\.\d+\.\d+(?:\.\d+)?)\b", text, re.I)
    if (set(versions) != {expected} or re.search(r"Graphical Edition|ITDT-GE", text, re.I)
            or not re.search(r"Standard Edition|ITDT-SE", text, re.I)):
        raise Refusal("ITDT SE version did not match the configured exact 9.x release")
    return expected


def parse_inquiry(text, serial, wwpns):
    text = bounded(text)
    # inqj output may be preceded by human-readable progress, but accepts one JSON object only.
    start = text.find("{")
    if start < 0:
        raise Refusal("inqj page 0x83 JSON missing")
    try:
        doc, end = json.JSONDecoder(object_pairs_hook=unique_json_object).raw_decode(text[start:])
        tail = text[start + end:].strip()
        if tail not in ("", "Exit with code: 0"):
            raise ValueError()
        data = doc["data"]
        port = data["worldWidePortName"]
        if (doc["command"] != "inquiry" or data["pageCode"] != 131
                or doc["parameter"]["pageCode"] != 131 or doc["parameter"]["evpd"] is not True
                or data["vendorIdentification"].strip() != "IBM" or data["serialNumberDrive"].strip() != serial):
            raise ValueError()
        if not re.fullmatch(r"[0-9a-fA-F]{16}", port):
            raise ValueError()
        normalized = ":".join(port[i:i + 2] for i in range(0, 16, 2)).lower()
        if normalized not in wwpns:
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise Refusal("ITDT page 0x83 serial/port identity mismatch or unsupported JSON") from None
    return {"serial": serial, "wwpn": normalized}


def parse_test(text, returncode):
    """Only the public scripting exit marker is a documented text grammar.

    No invented 'Test Result: PASS' line is treated as vendor proof. The health
    verdict stays unknown; support must inspect the collected native reports.
    """
    codes = re.findall(r"^\s*Exit with code: (-?\d+)\s*$", bounded(text), re.M)
    known = len(codes) == 1 and int(codes[0]) == returncode
    return {"process_returncode": returncode,
            "reported_exit_code": int(codes[0]) if len(codes) == 1 else None,
            "command_success": bool(known and returncode == 0),
            "hardware_verdict": "unknown", "native_report_review_required": True,
            "parser_warning": None if known else "missing, duplicate or conflicting scripting exit marker"}


def xml_root(text, root):
    bounded(text)
    declaration = re.match(r"\A<\?xml\s+[^?]*\?>", text)
    rest = text[declaration.end():] if declaration else text
    if "<!" in text or "<?" in rest:
        raise Refusal("XML declarations/entities/processing instructions refused")
    try:
        result = ET.fromstring(text)
    except ET.ParseError:
        raise Refusal("malformed vendor XML") from None
    if result.tag != root:
        raise Refusal("unexpected XML response root (vendor response withheld)")
    return result


def one(node, tag, required=True):
    nodes = node.findall(tag)
    if len(nodes) != 1 or nodes[0].text is None:
        if not nodes and not required:
            return None
        raise Refusal("missing/duplicate XML field " + tag)
    return nodes[0].text.strip()


def xml_status(text, root):
    result = xml_root(text, root)
    status = one(result, "status")
    if status != "OK":
        raise Refusal("library did not report OK (response withheld)")
    return status


def parse_progress(text, expected_page=None):
    root = xml_root(text, "progress")
    if expected_page is not None and one(root, "activePage") != expected_page:
        raise Refusal("library progress is for another or unknown operation")
    status = one(root, "status")
    if status not in ("OK", "ACTIVE", "FAILED", "QUEUE", "SUBMITTED"):
        raise Refusal("unknown library progress state")
    return status


def parse_move_result(text, config, restore):
    root = xml_root(text, "inventory")
    nodes = root.findall("moveResult")
    if len(nodes) != 1:
        raise Refusal("missing/duplicate library moveResult")
    result = nodes[0]
    if list(result):
        if len(list(result)) != 1 or result[0].tag != "message":
            raise Refusal("unknown nested library move result")
        message = one(result, "message")
    else:
        message = (result.text or "").strip()
    match = re.fullmatch(r"Move barcode (\S+) from (Slot|Drive|EE) (\d+) to (Slot|Drive|EE) (\d+) Successful", message)
    lib = config.library
    expected = (config.barcode, "Drive" if restore else "Slot", str(lib["drive_offset"] if restore else lib["home_slot"]),
                "Slot" if restore else "Drive", str(lib["home_slot"] if restore else lib["drive_offset"]))
    if match is None or match.groups() != expected:
        raise Refusal("library move result not proven successful for the exact TEST route")
    return {"barcode": match[1], "source_type": match[2], "source_offset": int(match[3]),
            "destination_type": match[4], "destination_offset": int(match[5])}


def parse_inventory(text, partition):
    root = xml_root(text, "inventory")
    parts = root.findall("partition")
    if len(parts) != 1 or one(parts[0], "name") != partition:
        raise Refusal("library inventory partition mismatch")
    result = {"storageSlot": {}, "entryExitSlot": {}, "drive": {}}
    occupied = []
    for element in parts[0]:
        if element.tag == "name":
            continue
        if element.tag not in result:
            raise Refusal("unsupported inventory element")
        try:
            offset = int(one(element, "offset"))
            scsi_id = int(one(element, "id"))
        except (ValueError, TypeError):
            raise Refusal("invalid library offset/id") from None
        full = one(element, "full")
        barcode = one(element, "barcode", False)
        queued = one(element, "isQueued", False)
        if (full not in ("yes", "no") or offset < 0 or scsi_id < 0
                or (full == "yes" and (not barcode or queued != "no"))
                or (full == "no" and barcode)):
            raise Refusal("ambiguous library occupancy or queued media")
        if barcode:
            if not re.fullmatch(TOKEN, barcode):
                raise Refusal("invalid barcode in inventory")
            occupied.append(barcode)
        if offset in result[element.tag]:
            raise Refusal("duplicate library offset")
        if any(record["id"] == scsi_id for record in result[element.tag].values()):
            raise Refusal("duplicate library SCSI element ID")
        result[element.tag][offset] = {"id": scsi_id, "barcode": barcode, "full": full == "yes",
                                      "sourceOffset": one(element, "sourceOffset", False)}
    if len(set(occupied)) != len(occupied):
        raise Refusal("duplicate barcode in library inventory")
    return result


def library_identity(text, config):
    root = xml_root(text, "driveList")
    rows = [d for d in root.findall("drive") if one(d, "ID") == config.library["drive_id"]]
    if len(rows) != 1:
        raise Refusal("library drive ID missing or ambiguous")
    drive = rows[0]
    # Public Spectra reference p.36: serialNumber is host-visible and location
    # based; manufacturerSerialNumber identifies the replaceable physical drive.
    if (one(drive, "serialNumber") != config.serial
            or one(drive, "manufacturerSerialNumber") != config.manufacturer_serial
            or one(drive, "partition") != config.library["partition"]
            or one(drive, "partitionDriveNumber") != str(config.library["drive_offset"])
            or one(drive, "driveStatus") != "OK"):
        raise Refusal("library manufacturer serial/partition/offset/status mismatch")
    port = one(drive, "wwn").lower().replace(":", "")
    if port.startswith("0x"):
        port = port[2:]
    if not re.fullmatch(r"[0-9a-f]{16}", port) or port not in {w.replace(":", "") for w in config.wwpns}:
        raise Refusal("library port-A WWPN does not match configured drive ports")
    return True


def parse_cfgshow(text):
    sections = {"defined": {"cfg": {}, "zone": {}, "alias": {}},
                "effective": {"cfg": {}, "zone": {}, "alias": {}}}
    section = None
    current = None
    for line in bounded(text).splitlines():
        line = line.strip().rstrip("\\").strip()
        if not line:
            continue
        if line in ("Defined configuration:", "Effective configuration:"):
            key = line.split()[0].lower()
            if section == key or (key == "defined" and section is not None):
                raise Refusal("duplicate/out-of-order cfgshow section")
            section, current = key, None
            continue
        if section is None or re.search(r"peer|principal|target.driven|no effective", line, re.I):
            raise Refusal("unsupported cfgshow output or zoning type")
        match = re.fullmatch(r"(cfg|zone|alias):\s*(" + NAME + r")(?:\s+(.*))?", line)
        if match:
            kind, name, values = match.groups()
            if name in sections[section][kind] or (section == "effective" and kind == "alias"):
                raise Refusal("duplicate or unexpected cfgshow object")
            current = []
            sections[section][kind][name] = current
            line = values or ""
        elif current is None:
            raise Refusal("unrecognized cfgshow continuation")
        if line:
            for value in line.split(";"):
                value = value.strip()
                if value:
                    current.append(member(re.sub(r",\s+", ",", value)))
    if section != "effective" or len(sections["effective"]["cfg"]) != 1:
        raise Refusal("complete defined/effective cfgshow sections required")
    for part in sections.values():
        for kind, objects in part.items():
            for name, values in objects.items():
                if len(set(values)) != len(values) or (not values and kind != "cfg"):
                    raise Refusal("empty/duplicate cfgshow members")
                objects[name] = sorted(values)
    return sections


def expand(values, aliases):
    result = set()
    for value in values:
        if re.fullmatch(WWPN, value) or re.fullmatch(PORT, value):
            result.add(value)
        elif value in aliases:
            # Nested aliases are not supported by FOS; reject rather than recurse.
            if not all(re.fullmatch(WWPN, v) or re.fullmatch(PORT, v) for v in aliases[value]):
                raise Refusal("unsupported nested alias")
            result.update(aliases[value])
        else:
            raise Refusal("unresolved zoning alias")
    return result


def validate_zoning(snapshot, switch):
    defined, effective = snapshot["defined"], snapshot["effective"]
    cfg = switch.configuration
    if set(effective["cfg"]) != {cfg} or cfg not in defined["cfg"]:
        raise Refusal("active configuration mismatch")
    active = set(defined["cfg"][cfg])
    if not active or set(effective["zone"]) != active:
        raise Refusal("defined/effective zone sets differ")
    for names in defined["cfg"].values():
        if any(n not in defined["zone"] for n in names):
            raise Refusal("configuration references unknown zone")
    for name, values in defined["zone"].items():
        expanded = expand(values, defined["alias"])
        if name in active and expanded != expand(effective["zone"][name], {}):
            raise Refusal("defined/effective zoning differs")
    if not set(switch.diagnostic_zones) <= active:
        raise Refusal("diagnostic zone must remain active")
    return snapshot


def no_access(text):
    lines = [l.strip() for l in bounded(text).splitlines() if l.strip()]
    if lines != ["Default Zone Access Mode", "committed - No Access", "transaction - No Transaction"]:
        raise Refusal("default zone is not proven committed No Access / no transaction")


def no_transactions(text):
    # The optional --opentrans domain table varies with FOS. Require the public
    # no-outstanding response with no additional domain rows; unknown is a stop.
    if bounded(text).strip() != "There is no outstanding zone transaction":
        raise Refusal("zoning transactions present or unsupported transaction output")


def no_fabric_transactions(text):
    lines = [line.strip() for line in bounded(text).splitlines() if line.strip()]
    if (len(lines) != 5 or lines[:4] != ["There is no outstanding zone transaction",
            "Transactions Detect: Capable", "Current Open Transactions", "Domain List:"]
            or not re.fullmatch(r"-+", lines[4])):
        raise Refusal("fabric transaction table not proven capable and empty; add locally reviewed output variant")


def isolation(snapshot, config, switch):
    validate_zoning(snapshot, switch)
    identities = set(config.wwpns) | set(switch.ports)
    for section in ("defined", "effective"):
        aliases = snapshot["defined"]["alias"] if section == "defined" else {}
        for zone, values in snapshot[section]["zone"].items():
            if zone not in switch.diagnostic_zones and expand(values, aliases) & identities:
                raise Refusal("drive identity remains in a production zone")
    if not any(expand(snapshot["effective"]["zone"][z], {}) & identities for z in switch.diagnostic_zones):
        raise Refusal("drive is not present in an active diagnostic zone")
    return True


def isolated_snapshot(baseline, config, switch):
    validate_zoning(baseline, switch)
    result = copy.deepcopy(baseline)
    identities = set(config.wwpns) | set(switch.ports)
    for zone, value in switch.removals:
        values = result["defined"]["zone"].get(zone, [])
        if value not in values:
            raise Refusal("configured zone/member removal absent from baseline")
        referenced = expand([value], baseline["defined"]["alias"])
        if not referenced or not referenced <= identities:
            raise Refusal("removal must reference only the configured drive identities")
        values.remove(value)
        if not values:
            raise Refusal("removing last member deletes the zone; automatic rollback would be unsafe")
    result["effective"]["zone"] = {
        name: sorted(expand(result["defined"]["zone"][name], result["defined"]["alias"]))
        for name in result["effective"]["zone"]}
    isolation(result, config, switch)
    return result
