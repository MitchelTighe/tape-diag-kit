"""Public-format adapters and conservative consistency checks (no device IO)."""
import re

SG_DOC = "https://github.com/hreinecke/sg3_utils/blob/master/"
MAM_SOURCE = SG_DOC + "src/sg_read_attr.c"
MT_SOURCE = "https://github.com/iustin/mt-st/blob/main/mt.c"
MAM_ATTRIBUTES = {
    "0x0003": ("Load count", "loads"),
    "0x0220": ("Total MiB written in medium life", "MiB"),
    "0x0221": ("Total MiB read in medium life", "MiB"),
    "0x0222": ("Total MiB written in current/last load", "MiB"),
    "0x0223": ("Total MiB read in current/last load", "MiB"),
    "0x0401": ("Medium serial number", None),
}
# Factual code/name subset from mt-st; unknown densities remain explicit.
DENSITIES = {0x00: "Default", 0x40: "DLT1 40 GB, or Ultrium", 0x42: "LTO-2", 0x44: "LTO-3",
             0x46: "LTO-4", 0x58: "LTO-5", 0x5a: "LTO-6", 0x5c: "LTO-7",
             0x5d: "LTO-7-M8", 0x5e: "LTO-8", 0x60: "LTO-9"}


def synthetic_identifier(value, kind="ID"):
    """No hash or suffix of the original identifier is retained."""
    value = value.strip().strip("'\"")
    if not value:
        return None
    if re.fullmatch(r"SYNTH-[A-Za-z0-9_-]+", value):
        return value
    return "SYNTH-REDACTED-" + kind


def parse_mam(text):
    rows, warnings = [], []
    for line in text.splitlines():
        if line.strip() == "Attribute values:":
            continue
        match = re.match(r"\s*(?:\[?(0x[0-9a-fA-F]{1,4})\]?\s*[: ]\s*)?(.+?)\s*[:=]\s*(.*?)\s*$", line)
        if not match:
            continue
        code, name, raw = match.groups()
        if code:
            code = "0x%04x" % int(code, 16)
        else:
            normalized = name.lower().replace("mbytes", "mib").replace("mb ", "mib ")
            code = next((k for k, (n, _) in MAM_ATTRIBUTES.items() if n.lower() == normalized), None)
        if code not in MAM_ATTRIBUTES:
            warnings.append("unrecognized MAM attribute omitted")
            continue
        title, unit = MAM_ATTRIBUTES[code]
        if code == "0x0401":
            value = synthetic_identifier(raw, "MEDIUM-SERIAL")
        elif re.fullmatch(r"\d+", raw):
            value = int(raw)
        else:
            value = None
            warnings.append("unavailable or malformed value for " + code)
        rows.append({"id": code, "name": title, "value": value, "unit": unit,
                     "redacted": code == "0x0401", "source": MAM_SOURCE})
    if not rows:
        warnings.append("no supported MAM attributes observed; medium may be absent or unsupported")
    if len({r["id"] for r in rows}) != len(rows):
        warnings.append("duplicate MAM attributes; values are not merged")
    return {"attributes": rows, "warnings": warnings}


def parse_inquiry(text):
    from .parsers import parse_drive_status
    status = parse_drive_status(text)
    serials = re.findall(r"(?:Unit serial number|SCSI_SERIAL)\s*[:=]\s*(.+)", text, re.I)
    # Export form is used for VPD collection, avoiding ambiguous descriptor text.
    ids = re.findall(r"^\s*(SCSI_IDENT_[A-Z0-9_]+)=(.+)$", text, re.M)
    # Also accept common decoded sg_inq descriptor forms; never retain raw lines.
    ids += [("decoded", m) for m in re.findall(r"(?:NAA|EUI-64|identifier)\s*[:=]\s*(.+)", text, re.I)]
    result = {k: status[k] for k in ("vendor", "product", "revision")}
    result.update(serial=synthetic_identifier(serials[0], "DRIVE-SERIAL") if serials else None,
                  identifiers=[{"type": key, "value": synthetic_identifier(value, "DEVICE-ID")} for key, value in ids],
                  warnings=[])
    if not any(result[k] for k in ("vendor", "serial", "identifiers")):
        result["warnings"].append("no inquiry or VPD fields recognized")
    return result


def parse_topology(text):
    """sg_map -x: sg host channel id lun type primary; unknown mapping is null."""
    mappings, warnings = [], []
    for line in text.splitlines():
        m = re.fullmatch(r"\s*(/dev/sg\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)(?:\s+(/dev/(?:n?st\d+|sch\d+)|-))?\s*", line)
        if not m:
            if line.strip():
                warnings.append("unrecognized sg_map line omitted")
            continue
        sg, host, channel, target, lun, pdt, primary = m.groups()
        if int(pdt) not in (1, 8):
            continue
        mappings.append({"generic_device": sg, "address": ":".join((host, channel, target, lun)),
                         "kind": "drive" if pdt == "1" else "changer",
                         "device": None if primary in (None, "-") else primary})
    if not mappings:
        warnings.append("no tape/changer mappings observed")
    return {"source": "sg_map -x", "mappings": mappings, "warnings": warnings}


def library_checks(status):
    """An empty source slot for a loaded drive is NORMAL, not a fault."""
    checks = []
    def add(rule, severity, message):
        checks.append({"rule": rule, "severity": severity, "message": message,
                       "source": "https://github.com/mtx-org/mtx/blob/master/mtx/mtx.1"})
    elements = [(kind, e) for kind in ("drives", "slots", "ie_ports") for e in status[kind]]
    seen = {}
    for kind, e in elements:
        tag = e["barcode"]
        for candidate in sorted(set(t for t in (tag, e["alternate_barcode"]) if t)):
            if candidate in seen and seen[candidate] != (kind, e["element"]):
                add("duplicate-barcode", "warn", "Barcode %s appears in multiple elements; verify capture consistency." % candidate)
            seen[candidate] = (kind, e["element"])
        if not e["full"] and tag:
            add("empty-with-barcode", "warn", "Empty %s %d retains a barcode; verify status." % (kind, e["element"]))
        if kind == "ie_ports":
            add("ie-state", "info", "IE port %d is %s; door/access state is not reported by mtx status." % (e["element"], "full" if e["full"] else "empty"))
    slots = {e["element"]: e for e in status["slots"] + status["ie_ports"]}
    for d in status["drives"]:
        if d["full"] and d["source_slot"] is not None:
            source = slots.get(d["source_slot"])
            if source is None:
                add("source-unobserved", "warn", "Loaded drive source slot is absent from capture.")
            elif source["full"]:
                add("source-occupied", "warn", "Loaded drive source slot is occupied; it may have been reused. No movement is inferred.")
            else:
                add("source-empty", "info", "Loaded drive has an empty source slot, the expected state after a move.")
    for warning in status["warnings"]:
        add("capture-consistency", "warn", warning)
    return checks


def tapealert_response(text):
    """Decode sg_logs 0x12 FlagXXh groups using the SSC drive flag catalog."""
    from .tapealert import parse_tapealert
    pairs = re.findall(r"(?:Flag)?([0-9a-fA-F]{2})h:\s*([01])\b", text)
    result = parse_tapealert("\n".join("Flag %d: %s" % (int(k, 16), v) for k, v in pairs))
    result["page"] = "0x12"
    return result


def response_from_page(page):
    if page['page'] != '0x12':
        return None
    text = '\n'.join(page['raw_lines'] + [p['name'] + ': ' + p['raw'] for p in page['parameters']])
    return tapealert_response(text) if text else None
