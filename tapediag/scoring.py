"""Pure, versioned triage model. Numeric weights/thresholds are heuristics.

Public sources define observations, never these deductions. See docs/SCORING.md.
V2 health.summarize intentionally retains its original policy for replay.
"""
import math

from .observations import library_checks, response_from_page

MODEL = "triage-v3.0.0"
ACCESSED = "2026-10-18"
CLEANING_HOURS_NAMES = ("hours since last cleaning", "hours since last clean", "media motion (head) hours since last successful cleaning operation")
HEAD_HOURS_NAMES = ("lifetime medium motion hours", "lifetime medium motion (head) hours", "lifetime media motion (head) hours")
SSC_ALERT = "https://www.t10.org/ftp/t10/document.05/05-154r2.pdf"
SSC_CLEAN = "https://www.t10.org/ftp/t10/document.06/06-235r0.pdf"
SSC_STATS = "https://www.t10.org/ftp/t10/document.05/05-213r3.pdf"
LTO = "https://www.ibm.com/support/pages/system/files/inline-files/LTO%20SCSI%20Reference_GA32-0928-05%20%28EXTERNAL%29_0.pdf"
SMC = "https://www.t10.org/ftp/t10/document.08/08-066r0.pdf"
SG = "https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8"


def rule(key, points, condition, source):
    return {"id": key, "deduction": points, "condition": condition, "source": source,
            "accessed": ACCESSED, "basis": "heuristic"}


RULES = [
    rule("alert-critical", 35, "Any active Critical TapeAlert (2Eh or 12h)", SSC_ALERT),
    rule("alert-warning", 15, "Any active Warning TapeAlert (2Eh or 12h)", SSC_ALERT),
    rule("media-life-alert", 10, "Active nearing-media-life flag 19 (13h)", SSC_CLEAN),
    rule("uncorrected-errors", 25, "Positive uncorrected read/write error counter (02h/03h)", LTO),
    rule("non-medium-errors", 10, "Positive non-medium error counter (06h)", LTO),
    rule("temperature-limit", 20, "Temperature above reported reference (0Dh); 255 means unavailable", LTO),
    rule("cleaning-request", 15, "Cleaning required from 0Ch, unless cleaning alert 20/21 already contributes", SSC_CLEAN),
    rule("cleaning-age", 5, "At least 100 medium-motion hours since last cleaning (14h)", SSC_STATS),
    rule("mam-loads", 10, "At least 10000 cartridge loads (MAM 0003h)", LTO),
    rule("mam-lifetime", 5, "At least 1000000000 MiB read plus written (MAM 0220h/0221h)", LTO),
    rule("head-hours", 5, "At least 20000 lifetime medium-motion hours (14h)", SSC_STATS),
    rule("library-consistency", 20, "Conflicting barcode or source-slot observations", SMC),
    rule("library-coverage", 15, "Missing/truncated/inconsistent element capture", SMC),
    rule("collection-errors", 10, "One or more collection errors relevant to this asset", SG),
]


def number(value):
    return (type(value) is int and value >= 0) or (type(value) is float and math.isfinite(value) and value >= 0)


def parameters(drive, page, names, units=(None,)):
    """Only exact normalized public decoded labels; ambiguous duplicates are gaps."""
    found = [p for log in (drive.get("logpages") or {}).get("pages", [])
             if log["page"] == page and log.get("subpage") in (None, "0x00")
             for p in log["parameters"] if p["name"].lower().strip() in names]
    if len(found) != 1 or not number(found[0]["value"]) or found[0]["unit"] not in units:
        return None
    return found[0]["value"]


def mam_value(drive, code):
    found = [a for a in (drive.get("mam") or {}).get("attributes", []) if a["id"] == code]
    unit = "loads" if code == "0x0003" else "MiB"
    return found[0]["value"] if len(found) == 1 and number(found[0]["value"]) and found[0]["unit"] == unit else None


def active_flags(drive):
    observations = [drive.get("tapealert"), drive.get("tapealert_response")]
    observations.extend(response_from_page(p) for p in (drive.get("logpages") or {}).get("pages", []) if p["page"] == "0x12")
    from .tapealert import catalog
    known = {f["flag"]: dict(f, active=True) for f in catalog()["flags"]}
    return {f["flag"]: known[f["flag"]] for obs in observations if obs for f in obs["active_flags"] if f["flag"] in known}


def finish(triggered, gaps):
    reasons = [dict(r, evidence=sorted(set(triggered[r["id"]]))) for r in RULES if r["id"] in triggered]
    score = max(0, 100 - sum(r["deduction"] for r in reasons))
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"
    return {"model": MODEL, "score": score, "grade": grade,
            "assessment": "attention" if reasons else "unknown" if gaps else "clear",
            "coverage": "incomplete" if gaps else "complete", "gaps": sorted(set(gaps)), "reasons": reasons}


def score_drive(drive, errors=()):
    triggered, gaps = {}, []
    def hit(key, evidence):
        triggered.setdefault(key, []).append(evidence)
    flags = active_flags(drive)
    alerts = drive.get("tapealert")
    if not alerts or set(alerts["observed_flags"]) != set(range(1, 65)) or alerts.get("warnings"):
        gaps.append("Full 2Eh TapeAlert coverage unavailable")
    for flag in flags.values():
        key = {"Critical": "alert-critical", "Warning": "alert-warning"}.get(flag["severity"])
        if key:
            hit(key, "Flag %d: %s" % (flag["flag"], flag["name"]))
    if 19 in flags:
        hit("media-life-alert", "Flag 19: nearing media life")
    for page, names, key in [("0x02", ("total uncorrected errors", "total uncorrected write errors"), "uncorrected-errors"),
                             ("0x03", ("total uncorrected errors", "total uncorrected read errors"), "uncorrected-errors"),
                             ("0x06", ("non-medium error count",), "non-medium-errors")]:
        value = parameters(drive, page, names)
        if value is None:
            gaps.append("Usable counter unavailable on " + page)
        elif value > 0:
            hit(key, "%s counter = %s (historical; not a rate)" % (page, value))
    current = parameters(drive, "0x0d", ("current temperature",), ("C", "Celsius"))
    reference = parameters(drive, "0x0d", ("reference temperature",), ("C", "Celsius"))
    if current is None or reference is None or 255 in (current, reference):
        gaps.append("Comparable current/reference temperature unavailable")
    elif current > reference:
        hit("temperature-limit", "%s C exceeds %s C reference" % (current, reference))
    clean = parameters(drive, "0x0c", ("cleaning required", "cleaning action required"))
    lines = [line.lower() for p in (drive.get("logpages") or {}).get("pages", []) if p["page"] == "0x0c" for line in p["raw_lines"]]
    if any(line in ("cleaning action required", "cleaning action required (or in progress)") for line in lines):
        clean = 1
    elif "cleaning action not required (or completed)" in lines:
        clean = 0
    if clean not in (0, 1) and not ({20, 21} & set(flags)):
        gaps.append("Cleaning request status unavailable")
    if clean == 1 and not ({20, 21} & set(flags)):
        hit("cleaning-request", "0Ch reports cleaning required")
    for names, key, threshold in [(CLEANING_HOURS_NAMES, "cleaning-age", 100),
                                  (HEAD_HOURS_NAMES, "head-hours", 20000)]:
        value = parameters(drive, "0x14", names, (None, "hours"))
        if value is None:
            gaps.append("Unavailable: " + names[0])
        elif value >= threshold:
            hit(key, "%s = %s hours; heuristic threshold %s" % (names[0], value, threshold))
    loads = mam_value(drive, "0x0003")
    written, read = mam_value(drive, "0x0220"), mam_value(drive, "0x0221")
    if loads is None:
        gaps.append("MAM cartridge load count unavailable (media may be absent)")
    elif loads >= 10000:
        hit("mam-loads", "Cartridge load count = %s; heuristic threshold 10000" % loads)
    if written is None or read is None:
        gaps.append("MAM lifetime read/write MiB unavailable")
    elif written + read >= 1000000000:
        hit("mam-lifetime", "Cartridge lifetime read + write = %s MiB; heuristic threshold 1000000000" % (written + read))
    relevant = [e for e in errors if e["device"] in (None, drive["device"])]
    if relevant:
        hit("collection-errors", "%d relevant collection errors" % len(relevant))
        gaps.append("Collection errors present")
    return finish(triggered, gaps)


def score_library(library, errors=()):
    status = library.get("status")
    checks = library_checks(status) if status else []
    triggered, gaps = {}, []
    conflicts = [c["message"] for c in checks if c["severity"] == "warn" and c["rule"] not in ("capture-consistency", "source-unobserved")]
    incomplete = [c["message"] for c in checks if c["rule"] in ("capture-consistency", "source-unobserved")]
    if conflicts:
        triggered["library-consistency"] = conflicts
    if incomplete or not status:
        triggered["library-coverage"] = incomplete or ["Element status unavailable"]
        gaps.extend(incomplete or ["Element status unavailable"])
    # mtx status does not expose all exception/door/sensor states; never certify robotics.
    gaps.append("mtx status cannot establish door, sensor, or complete element exception health")
    relevant = [e for e in errors if e["device"] in (None, library["device"])]
    if relevant:
        triggered["collection-errors"] = ["%d relevant collection errors" % len(relevant)]
        gaps.append("Collection errors present")
    return finish(triggered, gaps)


def score_report(report):
    scores = [a["health"]["score"] for a in report["drives"] + report["libraries"]]
    return {"model": MODEL, "score": min(scores) if scores else None,
            "aggregation": "minimum asset score; no assets means unknown",
            "assets": len(scores), "attention": sum(a["health"]["assessment"] == "attention" for a in report["drives"] + report["libraries"])}
