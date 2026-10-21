"""Explainable triage policy. Point deductions are toolkit policy, not standards."""
from .observations import library_checks, response_from_page

SSC = "https://www.t10.org/ftp/t10/document.05/05-154r2.pdf"
SG = "https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8"
RULES = [
    {"id": "alert-critical", "deduction": 35, "condition": "At least one active Critical drive TapeAlert", "source": SSC},
    {"id": "alert-warning", "deduction": 15, "condition": "At least one active Warning drive TapeAlert", "source": SSC},
    {"id": "uncorrected-errors", "deduction": 25, "condition": "Positive uncorrected read/write error count", "source": SG},
    {"id": "non-medium-errors", "deduction": 10, "condition": "Positive non-medium error count", "source": SG},
    {"id": "temperature-limit", "deduction": 20, "condition": "Current temperature exceeds drive-reported reference temperature", "source": SG},
    {"id": "changer-consistency", "deduction": 10, "condition": "At least one changer consistency warning", "source": "https://github.com/mtx-org/mtx/blob/master/mtx/mtx.1"},
    {"id": "collection-errors", "deduction": 10, "condition": "At least one collection error", "source": SG},
]


def summarize(report):
    triggered, gaps = {}, []
    for drive in report["drives"]:
        dev = drive["device"]
        alerts = drive.get("tapealert")
        if not alerts or len(alerts["observed_flags"]) < 64:
            gaps.append(dev + ": TapeAlert coverage incomplete")
        pages = (drive.get("logpages") or {}).get("pages", [])
        response = next((response_from_page(p) for p in pages if p["page"] == "0x12"), None)
        for label, observation in (("2Eh", alerts), ("12h response", response)):
            for flag in (observation or {}).get("active_flags", []):
                rule = {"Critical": "alert-critical", "Warning": "alert-warning"}.get(flag["severity"])
                if rule:
                    triggered.setdefault(rule, []).append(dev + " (" + label + "): " + flag["name"])
        if not {"0x02", "0x03", "0x06", "0x0d"}.issubset({p["page"] for p in pages}):
            gaps.append(dev + ": health log pages incomplete")
        seen_signals = set()
        for page in pages:
            values = {}
            for p in page["parameters"]:
                name, value = p["name"].lower(), p["value"]
                if type(value) not in (int, float):
                    continue
                values[name] = (value, p.get("unit"))
                if value >= 0 and page["page"] in ("0x02", "0x03") and "uncorrected" in name:
                    seen_signals.add(page["page"])
                if value >= 0 and page["page"] == "0x06" and "non-medium" in name:
                    seen_signals.add("0x06")
                if page["page"] in ("0x02", "0x03") and "uncorrected" in name and value > 0:
                    triggered.setdefault("uncorrected-errors", []).append(dev + ": " + p["name"] + " = " + str(value))
                if page["page"] == "0x06" and "non-medium" in name and value > 0:
                    triggered.setdefault("non-medium-errors", []).append(dev + ": " + p["name"] + " = " + str(value))
            if page["page"] == "0x0d":
                current = next((v for k, v in values.items() if "current temperature" in k), None)
                reference = next((v for k, v in values.items() if "reference temperature" in k), None)
                compatible = (current is not None and reference is not None and
                              current[1] == reference[1] and current[1] in ("C", "Celsius") and
                              255 not in (current[0], reference[0]))
                if compatible:
                    seen_signals.add("0x0d")
                if compatible and current[0] > reference[0]:
                    triggered.setdefault("temperature-limit", []).append(dev + ": above reported reference")
        for missing in sorted({"0x02", "0x03", "0x06", "0x0d"} - seen_signals):
            gaps.append(dev + ": usable health parameters missing on " + missing)
    for library in report["libraries"]:
        if not library.get("status"):
            gaps.append(library["device"] + ": changer status missing")
        if library.get("status") and any(c["severity"] == "warn" for c in library_checks(library["status"])):
            triggered.setdefault("changer-consistency", []).append(library["device"])
    if report["errors"]:
        triggered["collection-errors"] = ["%d collection errors" % len(report["errors"])]
        gaps.append("Collection failed for one or more observations")
    if not report["drives"]:
        gaps.append("No drive observations")
    matches = [dict(rule, evidence=triggered[rule["id"]]) for rule in RULES if rule["id"] in triggered]
    score = max(0, 100 - sum(r["deduction"] for r in matches))
    return {"score": score, "status": "fail" if score < 60 else "warn" if score < 100 or gaps else "pass",
            "coverage": "incomplete" if gaps else "complete", "gaps": gaps, "matches": matches,
            "rules": RULES, "policy": "triage-v1: each rule deducted once across report; floor 0. No failure prediction or certification. Historical counts are not rates."}
