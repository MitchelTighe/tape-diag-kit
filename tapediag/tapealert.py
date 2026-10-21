"""TapeAlert sequential-access profile. Missing observations never mean clear."""

import json
import re
from importlib.resources import files


def catalog() -> dict:
    return json.loads(files("tapediag").joinpath("tapealert_flags.json").read_text(encoding="utf-8"))


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def parse_tapealert(text: str) -> dict:
    data = catalog()
    by_number = {row["flag"]: row for row in data["flags"]}
    names = {_normalize(row["name"]): row["flag"] for row in data["flags"] if row["defined"]}
    for alias, number in {"Cleaning required": 20, "Cleaning requested": 21,
                          "Clean periodic": 21, "Media failure": 4,
                          "Read only format": 17, "Load failure": 55,
                          "Tape directory corrupted on load": 18,
                          "WORM medium integrity check failed": 59,
                          "WORM medium overwrite attempted": 60}.items():
        names[_normalize(alias)] = number
    observed, unknown, warnings = {}, [], []

    def record(number, value):
        if not 1 <= number <= 64:
            unknown.append({"flag": number, "value": value})
            return
        active = bool(value)
        if number in observed and observed[number] != active:
            warnings.append("conflicting observations for flag %d; active wins" % number)
            active = active or observed[number]
        observed[number] = active

    for line in text.splitlines():
        # sg_logs compact form: Flag01h: 0  02h: 1 ... (numbers are hex).
        compact = list(re.finditer(r"\b(?:Flag)?([0-9a-fA-F]{1,2})h\s*:\s*([01])\b", line, re.I))
        if compact:
            for match in compact:
                record(int(match[1], 16), int(match[2]))
            continue
        # Explicit decimal or 0x parameter identifiers in saved diagnostic reports.
        numeric = re.match(r"\s*(?:TapeAlert\s+)?(?:Flag|Parameter(?:\s+code)?)\s*[#=]?\s*(0x[0-9a-f]+|\d+)\s*(?:\([^)]*\))?\s*[:=]\s*(0|1|set|clear|true|false)\s*$", line, re.I)
        if numeric:
            token = numeric[1]
            record(int(token, 16 if token.lower().startswith("0x") else 10), int(numeric[2].lower() in ("1", "set", "true")))
            continue
        named = re.match(r"\s*(?:\[\d+\]\s*)?([^:=]+)\s*[:=]\s*(0|1|set|clear|true|false)\s*$", line, re.I)
        if named:
            number = names.get(_normalize(named[1]))
            if number is not None:
                record(number, int(named[2].lower() in ("1", "set", "true")))
                continue
        if re.search(r"\b(?:flag|parameter)\s*(?:0x[0-9a-f]+|\d+)|\b(?:Flag)?[0-9a-f]{1,2}h\s*:", line, re.I):
            warnings.append("unrecognized flag line: " + line.strip())
    if len(observed) < 64:
        warnings.append("only %d of 64 flags observed; unobserved flags are unknown" % len(observed))
    if any(not by_number[n]["defined"] for n, active in observed.items() if active):
        warnings.append("obsolete/reserved flag active; Info is a display policy, not a standard severity")
    return {"page": "0x2e", "profile": data["profile"], "sources": data["sources"],
            "active_flags": [dict(by_number[n], active=True) for n in sorted(observed) if observed[n]],
            "observed_flags": sorted(observed),
            "inactive_flags": sorted(n for n in observed if not observed[n]),
            "unobserved_flags": sorted(set(by_number) - set(observed)),
            "unknown_flags": unknown, "warnings": warnings}
