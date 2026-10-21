"""Offline fleet normalization, CSV export and two-snapshot regression checks."""
import csv
import io
from datetime import datetime

from .scoring import active_flags, parameters
from .v3 import migrate, timestamp
from .validation import validate_report


def normalize(report):
    value = migrate(report)
    if value["document_type"] != "report":
        raise ValueError("expected a report")
    return value


def assets(report):
    for kind, rows in (("drive", report["drives"]), ("library", report["libraries"])):
        for row in rows:
            yield kind, row


def csv_text(reports):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["fleet_id","captured_at","kind","asset_id","device","product","firmware","score","grade","assessment","coverage","model","reasons","gaps"])
    def safe(value):
        # Spreadsheet formula injection; csv quoting alone is insufficient.
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        if isinstance(value, str) and value[:1] in ("\t", "\r", "\n"):
            return "'" + value
        return value
    for report in reports:
        report = normalize(report)
        for kind, asset in assets(report):
            inquiry = asset.get("inquiry") or asset.get("drive_status") or {}
            h = asset["health"]
            writer.writerow([safe(v) for v in [report["fleet_id"], report["captured_at"] or "unknown", kind,
                asset["asset_id"], asset["device"], inquiry.get("product") or "unknown", inquiry.get("revision") or "unknown",
                h["score"], h["grade"], h["assessment"], h["coverage"], h["model"],
                "; ".join(r["id"] for r in h["reasons"]), "; ".join(h["gaps"])]] )
    return stream.getvalue()


def diff_reports(before, after):
    before, after = normalize(before), normalize(after)
    if before["fleet_id"] != after["fleet_id"]:
        raise ValueError("watch requires matching fleet_id")
    if before["captured_at"] and after["captured_at"] and datetime.fromisoformat(timestamp(after["captured_at"]).replace("Z", "+00:00")) <= datetime.fromisoformat(timestamp(before["captured_at"]).replace("Z", "+00:00")):
        raise ValueError("watch requires after timestamp later than before")
    old = {a["asset_id"]: (kind, a) for kind, a in assets(before)}
    new = {a["asset_id"]: (kind, a) for kind, a in assets(after)}
    events, notes = [], []
    if not before["captured_at"] or not after["captured_at"]:
        notes.append("Capture time missing: caller order used; no elapsed-time/rate inference.")
    for key in sorted(set(old) | set(new)):
        def event(kind, reason, regression=False):
            events.append({"asset_id": key, "kind": kind, "reason": reason, "regression": regression})
        if key not in new:
            event("missing-asset", "Previously observed asset absent from after report", True)
            continue
        if key not in old:
            event("new-asset", "Asset first observed")
            continue
        old_kind, a = old[key]
        new_kind, b = new[key]
        if old_kind != new_kind:
            raise ValueError("watch asset kind changed for matching asset_id")
        if a["identity_basis"] == "device-path" or b["identity_basis"] == "device-path":
            notes.append(key + ": device-path identity may be reused; confirm mapping before interpreting changes.")
        delta = b["health"]["score"] - a["health"]["score"]
        if delta:
            event("score", "%s -> %s (%+d)" % (a["health"]["score"], b["health"]["score"], delta), delta < 0)
        added_gaps = sorted(set(b["health"]["gaps"]) - set(a["health"]["gaps"]))
        if added_gaps:
            event("coverage", "; ".join(added_gaps), True)
        for flag in sorted(set(active_flags(b)) - set(active_flags(a))):
            event("new-alert", "TapeAlert flag %d newly active" % flag, True)
        for page, names in [("0x02", ("total uncorrected errors", "total uncorrected write errors")),
                            ("0x03", ("total uncorrected errors", "total uncorrected read errors")),
                            ("0x06", ("non-medium error count",))]:
            v1, v2 = parameters(a, page, names), parameters(b, page, names)
            if v1 is not None and v2 is not None and v2 != v1:
                if v2 < v1:
                    event("counter-reset", page + " decreased; reset/replacement/wrap possible; no delta/rate used")
                else:
                    event("counter-increase", "%s increased by %s (not a rate)" % (page, v2 - v1), True)
    return {"document_type": "watch", "fleet_id": before["fleet_id"], "before": before["captured_at"],
            "after": after["captured_at"], "regressions": sum(e["regression"] for e in events), "events": events, "notes": notes}
