"""Bounded, offline SSC LOG SENSE hex decoding; never issue a device command.

Factual layouts: public SSC TapeAlert proposal 05-154r2 and sg3_utils
show_sequential_access_page/show_volume_stats_pages/show_tape_capacity_page.
See docs/log-trends.md for citations, profiles and deliberately narrow scope.
"""

import re

SSC_SOURCE = "https://www.t10.org/ftp/t10/document.05/05-154r2.pdf"
LOG_SOURCE = "https://github.com/hreinecke/sg3_utils/blob/master/src/sg_logs.c"
CAPACITY_SOURCE = "https://github.com/hreinecke/sg3_utils/blob/master/src/sg_logs_vendor.c"
MAX_HEX_TEXT = 1024 * 1024
MAX_PAGE_BYTES = 65539  # Four-byte header plus the unsigned 16-bit page length.
PROFILES = ("ssc", "lto5-6-capacity")

# name, unit, interpretation, scope. No threshold or health score is inferred.
SEQUENTIAL = {
    0: ("host_write_bytes", "bytes", "counter", "drive"),
    1: ("medium_write_bytes", "bytes", "counter", "drive"),
    2: ("medium_read_bytes", "bytes", "counter", "drive"),
    3: ("host_read_bytes", "bytes", "counter", "drive"),
    0x100: ("cleaning_required_or_in_progress", None, "state", "drive"),
}
VOLUME = {
    0: ("page_valid", None, "state", "medium"),
    1: ("thread_count", "count", "counter", "medium"),
    2: ("datasets_written", "count", "counter", "medium"),
    3: ("write_retries", "count", "counter", "medium"),
    4: ("unrecovered_write_errors", "count", "counter", "medium"),
    7: ("datasets_read", "count", "counter", "medium"),
    8: ("read_retries", "count", "counter", "medium"),
    9: ("unrecovered_read_errors", "count", "counter", "medium"),
    0x16: ("native_capacity", "MB", "gauge", "medium"),
    0x17: ("used_native_capacity", "MB", "gauge", "medium"),
}
CAPACITY = {
    1: ("main_remaining_capacity", "MiB", "gauge", "medium"),
    2: ("alternate_remaining_capacity", "MiB", "gauge", "medium"),
    3: ("main_maximum_capacity", "MiB", "gauge", "medium"),
    4: ("alternate_maximum_capacity", "MiB", "gauge", "medium"),
}


def hex_bytes(text):
    """Accept byte pairs, whitespace, # comments and optional exact hex offsets.

    ASCII gutters, prose, 0x prefixes and odd nibbles are refused, not guessed.
    Offsets use ``0000:`` syntax and must match bytes already consumed.
    """
    if not isinstance(text, str) or len(text) > MAX_HEX_TEXT:
        raise ValueError("hex capture must be text of at most 1 MiB")
    result = bytearray()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        offset = re.match(r"^([0-9a-fA-F]{1,8}):\s*", line)
        if offset:
            if int(offset[1], 16) != len(result):
                raise ValueError("hex capture offset does not match byte position")
            line = line[offset.end():]
        if not re.fullmatch(r"(?:[0-9a-fA-F]{2}(?:[ \t]+|$))+", line):
            raise ValueError("expected whitespace-separated hex byte pairs")
        result.extend(bytes.fromhex(line))
        if len(result) > MAX_PAGE_BYTES:
            raise ValueError("hex capture exceeds one LOG SENSE page")
    return bytes(result)


def parse_log_hex(text, profile="ssc"):
    """Decode one complete page. Unknown parameters retain bytes without values."""
    if profile not in PROFILES:
        raise ValueError("unknown offline log profile")
    data = hex_bytes(text)
    if len(data) < 4:
        raise ValueError("truncated LOG SENSE page header")
    page, subpage = data[0] & 0x3f, data[1]
    if len(data) != 4 + int.from_bytes(data[2:4], "big"):
        raise ValueError("LOG SENSE page length does not match capture")
    if not data[0] & 0x40 and subpage:
        raise ValueError("nonzero subpage without SPF")
    warnings, rows, seen = [], [], set()
    supported = subpage == 0 and page in (0x0c, 0x17, 0x2e)
    if page == 0x31 and subpage == 0:
        supported = profile == "lto5-6-capacity"
    if not supported:
        warnings.append("page/subpage has no decoder in selected profile; bytes retained")
        # Unknown pages need not use the parameter-descriptor layout.
        return {"page": "0x%02x" % page, "subpage": subpage, "profile": profile,
                "parameters": [], "raw_hex": data.hex(), "warnings": warnings,
                "sources": [LOG_SOURCE]}
    table = {0x0c: SEQUENTIAL, 0x17: VOLUME, 0x31: CAPACITY}.get(page, {})
    offset = 4
    while offset < len(data):
        if len(data) - offset < 4:
            raise ValueError("truncated LOG SENSE parameter header")
        code = int.from_bytes(data[offset:offset + 2], "big")
        control, length = data[offset + 2:offset + 4]
        end = offset + 4 + length
        if end > len(data):
            raise ValueError("truncated LOG SENSE parameter payload")
        if code in seen:
            raise ValueError("duplicate LOG SENSE parameter code")
        seen.add(code)
        payload = data[offset + 4:end]
        definition = table.get(code)
        if page == 0x2e and 1 <= code <= 64:
            definition = ("tapealert_%d" % code, None, "flag", "drive")
        row = {"code": code, "control": control, "length": length,
               "raw_hex": payload.hex(), "name": None, "unit": None,
               "kind": "unknown", "scope": None, "value": None}
        if definition:
            row.update(zip(("name", "unit", "kind", "scope"), definition))
            expected = (1,) if page == 0x2e else (4,) if page == 0x31 else range(1, 9)
            if length not in expected:
                warnings.append("parameter %04x has unsupported length" % code)
            elif control & 3:
                warnings.append("parameter %04x has unsupported format/linking bits" % code)
            else:
                value = int.from_bytes(payload, "big")
                if page == 0x2e:
                    if value not in (0, 1):
                        warnings.append("TapeAlert %d has reserved bits set" % code)
                    else:
                        row["value"] = bool(value)
                elif page == 0x17 and code == 0:
                    # SSC page-valid is bit zero, not a counter.
                    row["value"] = bool(value & 1)
                elif page == 0x0c and code == 0x100:
                    row["value"] = bool(value)
                elif page == 0x17 and code in (0x16, 0x17) and all(b == 255 for b in payload):
                    warnings.append("parameter %04x capacity is unavailable" % code)
                else:
                    row["value"] = value
        rows.append(row)
        offset = end
    if page == 0x17:
        valid = next((r["value"] for r in rows if r["code"] == 0), None)
        if valid is not True:
            warnings.append("volume statistics page validity is false or unobserved")
            for row in rows:
                if row["code"] != 0:
                    row["value"] = None
    if page == 0x2e and len([r for r in rows if r["kind"] == "flag" and r["value"] is not None]) != 64:
        warnings.append("TapeAlert coverage incomplete; missing flags are unknown")
    return {"page": "0x%02x" % page, "subpage": subpage, "profile": profile,
            "parameters": rows, "raw_hex": data.hex(), "warnings": warnings,
            "sources": [SSC_SOURCE if page == 0x2e else CAPACITY_SOURCE if page == 0x31 else LOG_SOURCE]}
