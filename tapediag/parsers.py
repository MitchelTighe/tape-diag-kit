"""Pure text parsers. No subprocesses or device opens occur in this module."""

import math
import re
from typing import Optional

from .tapealert import parse_tapealert

PAGE_NAMES = {
    "0x00": "Supported log pages", "0x02": "Write error counters",
    "0x03": "Read error counters", "0x06": "Non-medium error counters", "0x0c": "Sequential-access device",
    "0x0d": "Temperature", "0x0e": "Start-stop cycle counter", "0x12": "TapeAlert response", "0x14": "Device statistics",
    "0x17": "Volume statistics", "0x2e": "TapeAlert",
}


def parse_inventory(text: str) -> dict:
    devices, warnings = [], []
    for line in text.splitlines():
        match = re.match(r"\s*\[([0-9]+:[0-9]+:[0-9]+:[0-9]+)\]\s+(tape|mediumx|changer)\s+(.+?)\s+(\S+)\s+(\S+)\s*$", line)
        if not match:
            if re.search(r"\]\s+(?:tape|mediumx|changer)\b", line):
                warnings.append("unrecognized inventory line: " + line.strip())
            continue
        address, pdt, identity, primary, generic = match.groups()
        # lsscsi's vendor/product/revision fields are padded; model can contain spaces.
        parts = identity.split()
        if len(parts) < 3:
            warnings.append("incomplete identity: " + line.strip())
            continue
        if generic != "-" and not re.fullmatch(r"/dev/sg\d+", generic):
            warnings.append("unrecognized generic device: " + generic)
            continue
        if primary != "-" and not re.fullmatch(r"/dev/(?:n?st\d+|sch\d+|sg\d+)", primary):
            warnings.append("unrecognized primary device: " + primary)
            continue
        kind = "drive" if pdt == "tape" else "changer"
        nst = None
        if kind == "drive" and re.fullmatch(r"/dev/n?st\d+", primary):
            nst = primary if "/nst" in primary else primary.replace("/st", "/nst")
        devices.append({"kind": kind, "address": address, "vendor": parts[0],
                        "model": " ".join(parts[1:-1]), "revision": parts[-1],
                        "device": None if primary == "-" else primary,
                        "generic_device": None if generic == "-" else generic,
                        "nonrewinding_device": nst})
    if not devices and text.strip() and not warnings:
        warnings.append("no tape/changer entries recognized (capture may contain other device types)")
    return {"source": "lsscsi", "devices": devices, "warnings": warnings}


def parse_library(text: str) -> dict:
    result = {"device": None, "reported_drives": None, "reported_slots": None,
              "reported_ie_ports": None, "drives": [], "slots": [], "ie_ports": [],
              "warnings": []}
    header = re.search(r"Storage Changer\s+(\S+):\s*(\d+)\s+Drives?,\s*(\d+)\s+Slots?(?:\s*\(\s*(\d+)\s*,?\s*Import/Export\s*\))?", text, re.I)
    if header:
        result.update(device=header[1], reported_drives=int(header[2]),
                      reported_slots=int(header[3]), reported_ie_ports=int(header[4]) if header[4] else None)
    seen = set()
    for line in text.splitlines():
        match = re.match(r"\s*(Data Transfer Element|Storage Element)\s*(\d+)?\s*(IMPORT/EXPORT)?\s*:\s*(Full|Empty)\b(.*)$", line, re.I)
        if not match:
            if re.search(r"(?:Data Transfer|Storage) Element", line, re.I) and not "Loaded)" in line:
                result["warnings"].append("unrecognized element line: " + line.strip())
            continue
        category, number, ie, state, rest = match.groups()
        if number is None:
            if category.lower().startswith("data"):
                number = "0"  # Historical mtx.doc single-drive output.
            else:
                result["warnings"].append("storage element has no number: " + line.strip())
                continue
        key = "drives" if category.lower().startswith("data") else "ie_ports" if ie else "slots"
        loaded = re.search(r"Storage Element\s+(\d+)\s+Loaded", rest, re.I)
        barcode = re.search(r"(?<!Alternate)\bVolumeTag\s*=\s*([^:]*?)(?=\s*:\s*(?:AlternateVolumeTag|VolumeTag)|$)", rest, re.I)
        alt = re.search(r"AlternateVolumeTag\s*=\s*([^:]*)", rest, re.I)
        element = {"element": int(number), "full": state.lower() == "full",
                   "barcode": (barcode[1].strip() or None) if barcode else None,
                   "alternate_barcode": (alt[1].strip() or None) if alt else None,
                   "source_slot": int(loaded[1]) if loaded else None}
        # Do not treat an empty barcode as evidence of an empty element.
        identity = ("drive" if key == "drives" else "storage", int(number))
        if identity in seen:
            result["warnings"].append("duplicate element: %s %s" % identity)
        seen.add(identity)
        result[key].append(element)
    if not header:
        result["warnings"].append("missing storage changer header")
    if result["reported_drives"] is not None and len(result["drives"]) != result["reported_drives"]:
        result["warnings"].append("drive count differs from header; capture may be truncated")
    if result["reported_slots"] is not None and len(result["slots"]) + len(result["ie_ports"]) != result["reported_slots"]:
        result["warnings"].append("storage count differs from header; slots include IE ports")
    if result["reported_ie_ports"] is not None and len(result["ie_ports"]) != result["reported_ie_ports"]:
        result["warnings"].append("IE port count differs from header")
    return result


def _number(text: str):
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"0x[\da-fA-F]+", text):
        return int(text, 16)
    if re.fullmatch(r"-?\d+\.\d+", text):
        value = float(text)
        return value if math.isfinite(value) else text
    return text


def parse_logpages(text: str, page_hint: Optional[str] = None) -> dict:
    pages, current, preamble = [], None, []
    # A page header must end after its page identifier (optional sg_logs acronym).
    header_re = re.compile(r"^\s*(.*?)\s*\[(0x[\da-fA-F]+)(?:\s*,\s*(0x[\da-fA-F]+))?\](?:\s*\[[^]]*\])?\s*:?\s*$")

    def new_page(code, title, subpage=None):
        return {"page": code, "subpage": subpage, "name": title,
                "known": code in PAGE_NAMES, "parameters": [],
                "supported_pages": [], "raw_lines": []}

    # A hint is a fallback for headerless captures, not an extra empty page
    # before sg_logs' inquiry banner.
    has_header = any(header_re.match(line) for line in text.splitlines())
    for line in text.splitlines():
        match = header_re.match(line)
        if match and not (current and current["page"] == "0x00" and line[:1].isspace() and not line.rstrip().endswith(":")):
            code = "0x%02x" % int(match[2], 16)
            current = new_page(code, match[1].strip(), "0x%02x" % int(match[3], 16) if match[3] else None)
            pages.append(current)
            continue
        if current is None and page_hint and not has_header:
            current = new_page(page_hint, PAGE_NAMES.get(page_hint, "Unknown"))
            pages.append(current)
        if current is None:
            if line.strip():
                preamble.append(line.strip())
            continue
        if not line.strip():
            continue
        if current["page"] == "0x00":
            supported = re.match(r"\s*(0x[\da-f]+)(?:\s*,\s*(0x[\da-f]+))?\s*(.*?)\s*$", line, re.I)
            reverse = header_re.match(line)
            if supported or reverse:
                code = supported[1] if supported else reverse[2]
                sub = supported[2] if supported else reverse[3]
                title = supported[3] if supported else reverse[1]
                current["supported_pages"].append({"page": "0x%02x" % int(code, 16),
                    "subpage": "0x%02x" % int(sub, 16) if sub else None, "name": title.strip()})
                continue
        parameter = re.match(r"\s*([^:=]+?)\s*[:=]\s*(.+?)\s*$", line)
        if parameter:
            name, raw = parameter.groups()
            measured = re.fullmatch(r"(-?\d+(?:\.\d+)?|0x[\da-fA-F]+)(?:\s+([A-Za-z][A-Za-z0-9 /%()^-]*))?", raw)
            value, unit = (_number(measured[1]), measured[2]) if measured else (raw, None)
            if raw.lower() in ("<not available>", "not available", "unknown"):
                value = None
            current["parameters"].append({"name": name.strip(), "value": value, "unit": unit, "raw": raw})
        else:
            current["raw_lines"].append(line.strip())
    warnings = []
    if not pages:
        warnings.append("no log page header recognized")
    if any(not p["known"] for p in pages):
        warnings.append("unknown pages retained without interpreting vendor-specific bytes")
    return {"pages": pages, "preamble": preamble, "warnings": warnings}


def parse_drive_status(text: str, tur_returncode: Optional[int] = None) -> dict:
    result = {"vendor": None, "product": None, "revision": None,
              "density": None, "density_description": None, "block_size": None,
              "file_number": None, "block_number": None, "online": None,
              "write_protect": None, "ready": None, "status_flags": [], "warnings": []}
    for name, pattern in {
        "vendor": r"(?:Vendor identification|Vendor ID|Manufacturer)\s*[:=]\s*(.+)",
        "product": r"(?:Product identification|Product ID)\s*[:=]\s*(.+)",
        "revision": r"(?:Product revision level|Revision Level|Revision)\s*[:=]\s*(.+)",
    }.items():
        match = re.search(pattern, text, re.I)
        if match:
            result[name] = match[1].strip().strip("'")
    density = re.search(r"Density code\s+(0x[\da-f]+|\d+)(?:\s*\(([^)]*)\))?", text, re.I)
    if density:
        result["density"] = _number(density[1])
        from .observations import DENSITIES
        result["density_description"] = density[2] or DENSITIES.get(result["density"], "Unknown density")
    for name, pattern in {"block_size": r"(?:Tape )?[Bb]lock size\s+(\d+)",
                          "file_number": r"[Ff]ile number\s*[=:]\s*(-?\d+)",
                          "block_number": r"[Bb]lock number\s*[=:]\s*(-?\d+)"}.items():
        match = re.search(pattern, text)
        if match:
            result[name] = int(match[1])
    # mt-st prints an authoritative GMT bitfield; absence in partial text is unknown.
    status = re.search(r"General status bits on\s*\((?:0x)?([0-9a-fA-F]+)\)", text, re.I)
    if status:
        bits = int(status[1], 16)
        result["online"] = bool(bits & 0x01000000)
        result["write_protect"] = bool(bits & 0x04000000)
        following = text[status.end():].splitlines()
        for line in following:
            if line.strip() and line.strip() != ":":
                if re.fullmatch(r"[A-Z_\s]+", line.strip()):
                    result["status_flags"] = line.split()
                break
    else:
        if re.search(r"\bONLINE\b", text):
            result["online"] = True
        if re.search(r"\bOFFLINE\b", text):
            result["online"] = False
        if re.search(r"\bWR_PROT\b", text):
            result["write_protect"] = True
    if tur_returncode is not None:
        result["ready"] = tur_returncode == 0 if tur_returncode in (0, 2) else None
    elif re.search(r"\bnot ready\b|\bmedium not present\b", text, re.I):
        result["ready"] = False
    elif re.search(r"(?:\btest unit ready|\bsg_turs).*?\b(?:good|ready|success(?:ful|fully)?)\b", text, re.I):
        result["ready"] = True
    if result["file_number"] == -1 or result["block_number"] == -1:
        result["warnings"].append("position -1 means unavailable, not a valid media position")
    if result["block_size"] == 0:
        result["warnings"].append("block size 0 means variable-length blocks")
    if all(result[key] is None for key in ("vendor", "density", "block_size", "online", "ready")):
        result["warnings"].append("no drive status fields recognized")
    return result


def parse_ltfs(text: str) -> dict:
    devices = []
    for line in text.splitlines():
        if "Device Name" not in line:
            continue
        fields = dict((k.strip().lower(), v.strip().rstrip(" ."))
                      for k, v in re.findall(r"([^,=]+)\s*=\s*([^,]*)", line))
        device = fields.get("device name")
        if device:
            devices.append({"device": device, "vendor": fields.get("vendor id", fields.get("vender id")),
                            "product": fields.get("product id"), "serial": fields.get("serial number"),
                            "product_name": fields.get("product name")})
    return {"devices": devices, "ltfsck": "skipped: no checker or repair command is allowlisted",
            "warnings": [] if devices else ["no LTFS device records recognized"]}


def parse_itdt(text: str) -> dict:
    """Parse documented default ITDT scan and inquiry/flag text, never run ITDT."""
    devices = []
    pattern = r"^\s*#(\d+)\s+(\S+)\s+-\s+\[([^]]+)\]-\[([^]]+)\]\s+S/N:(\S+)\s+H(\d+)-B(\d+)-T(\d+)-L(\d+)(?:\s+\(([^)]+)\))?"
    for match in re.finditer(pattern, text, re.M):
        index, device, model, revision, serial, host, bus, target, lun, driver = match.groups()
        devices.append({"index": int(index), "device": device, "model": model,
                        "revision": revision, "serial": serial,
                        "address": ":".join((host, bus, target, lun)), "driver": driver})
    inquiry = parse_drive_status(text)
    alerts = parse_tapealert(text)
    recognized = bool(devices or any(inquiry[k] is not None for k in ("vendor", "product", "revision")) or alerts["observed_flags"])
    return {"adapter": "IBM ITDT saved text only", "devices": devices,
            "inquiry": {k: inquiry[k] for k in ("vendor", "product", "revision")},
            "tapealert": alerts if alerts["observed_flags"] else None,
            "warnings": [] if recognized else ["no supported ITDT records recognized; custom scan formats and binary dumps are unsupported"],
            "raw_lines": text.splitlines()}


PARSERS = {"inventory": parse_inventory, "tapealert": parse_tapealert,
           "logpages": parse_logpages, "drive-status": parse_drive_status,
           "library": parse_library, "ltfs": parse_ltfs, "itdt": parse_itdt}

from .observations import parse_mam, parse_inquiry, parse_topology
PARSERS.update({"mam": parse_mam, "inquiry": parse_inquiry, "topology": parse_topology})
