"""Small cited offline knowledge base; identifiers are explicit, never guessed."""

import re

from .observations import DENSITIES
from .parsers import PAGE_NAMES
from .tapealert import catalog
from .logsense import LOG_SOURCE, CAPACITY_SOURCE

ASC_SOURCE = "https://www.t10.org/lists/asc-num.txt"
KEY_SOURCE = "https://www.t10.org/lists/2sensekey.htm"
DENSITY_SOURCE = "https://github.com/iustin/mt-st/blob/main/mt.c"
KEYS = (
    "No sense", "Recovered error", "Not ready", "Medium error", "Hardware error",
    "Illegal request", "Unit attention", "Data protect", "Blank check",
    "Vendor specific", "Copy aborted", "Aborted command", "Reserved",
    "Volume overflow", "Miscompare", "Completed",
)
# Deliberately small factual code subset; original paraphrases, not manual text.
ASC = {
    (0x00, 0x00): ("No additional detail", "Use the sense key and saved command context."),
    (0x00, 0x01): ("Filemark encountered", "A tape boundary observation; interpret with the requested read."),
    (0x00, 0x02): ("Partition or medium end", "Review media position and the application's end-of-medium handling."),
    (0x00, 0x05): ("End of recorded data", "Compare the requested operation with the expected recorded extent."),
    (0x00, 0x17): ("Cleaning request", "Review TapeAlert and the exact model's approved cleaning procedure."),
    (0x04, 0x00): ("Readiness cause unspecified", "Retain additional saved status; this code alone cannot isolate a cause."),
    (0x04, 0x01): ("Readiness transition underway", "Correlate with saved application events and capture time."),
    (0x04, 0x18): ("Open door reported", "Changer-specific evidence; verify model and physical state through approved procedures."),
    (0x11, 0x00): ("Read recovery exhausted", "Compare media identity, repeat history and other drives' saved evidence."),
    (0x27, 0x00): ("Write protection reported", "Check cartridge policy and saved status; do not assume a drive fault."),
    (0x28, 0x00): ("Readiness transition or media change", "Treat cross-snapshot media identity as unconfirmed until verified."),
    (0x29, 0x00): ("Power-on or reset event", "Counter decreases across this event cannot establish improvement."),
    (0x3a, 0x00): ("No medium reported", "An empty drive is not itself evidence of hardware failure."),
}


def _number(value):
    if not re.fullmatch(r"(?:0x[0-9a-f]{1,2}|[0-9]{1,3})", value):
        raise ValueError("use decimal or 0x-prefixed one-byte code")
    result = int(value, 16 if value.startswith("0x") else 10)
    if result > 255:
        raise ValueError("code exceeds one byte")
    return result


def explain(code):
    if not isinstance(code, str) or len(code) > 64:
        raise ValueError("code must be text of at most 64 characters")
    code = code.strip().lower()
    if ":" not in code:
        raise ValueError("use tapealert:N, page:N, density:N, asc:HH/HH or sense:H/HH/HH")
    namespace, value = code.split(":", 1)
    result = {"format": "tapediag-explanation-v1", "code": code, "known": False,
              "name": "Unknown in the offline catalogue", "guidance": "Retain the original code and consult the exact device's public reference.",
              "sources": [], "catalogue_date": "2026-10-20"}
    if namespace == "tapealert":
        number = _number(value)
        data = catalog()
        flag = next((r for r in data["flags"] if r["flag"] == number), None)
        result["sources"] = data["sources"]
        if flag:
            result.update(known=flag["defined"], name=flag["name"],
                          guidance=flag["action"], severity=flag["severity"])
        result["scope"] = "SSC drive flags only; SMC library flags have different meanings."
    elif namespace in ("asc", "sense"):
        pattern = r"[0-9a-f]/[0-9a-f]{2}/[0-9a-f]{2}" if namespace == "sense" else r"[0-9a-f]{2}/[0-9a-f]{2}"
        # Also accept a zero-padded sense-key nibble.
        if namespace == "sense":
            pattern = r"0?[0-9a-f]/[0-9a-f]{2}/[0-9a-f]{2}"
        if not re.fullmatch(pattern, value):
            raise ValueError("sense codes require hex key/ASC/ASCQ; ASC requires hex ASC/ASCQ")
        numbers = [int(v, 16) for v in value.split("/")]
        if namespace == "sense":
            result["sense_key"] = {"code": numbers[0], "name": KEYS[numbers[0]]}
        entry = ASC.get(tuple(numbers[-2:]))
        result["sources"] = [ASC_SOURCE] + ([KEY_SOURCE] if namespace == "sense" else [])
        if entry:
            result.update(known=True, name=entry[0], guidance=entry[1])
        result["scope"] = "Code lookup only; applicability and key/ASC pairing require the device reference."
    elif namespace in ("page", "density"):
        number = _number(value)
        if namespace == "page":
            name = PAGE_NAMES.get("0x%02x" % number)
            if number == 0x31:
                name = "Vendor tape capacity (explicit LTO-5/6-style profile only)"
            result["sources"] = [CAPACITY_SOURCE if number == 0x31 else LOG_SOURCE]
            result["scope"] = "Sequential-access device profile; other peripheral types may reuse page numbers."
        else:
            name = DENSITIES.get(number)
            result["sources"] = [DENSITY_SOURCE]
            result["scope"] = "Density label only; not proof of cartridge capacity or drive/media compatibility."
        if name:
            result.update(known=True, name=name,
                          guidance="Compare the captured value with the exact model and format reference.")
    else:
        raise ValueError("unknown code namespace")
    return result
