"""Explicit, non-mutating report migration and per-asset v3 enrichment."""
import copy
import re
from datetime import datetime, timezone

from . import __version__
from .observations import library_checks
from .scoring import score_drive, score_library, score_report
from .validation import validate_report


def timestamp(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value) is None:
            raise ValueError("invalid RFC3339 format")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("captured_at must be an ISO-8601 timestamp with timezone") from exc
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def migrate(report, fleet_id=None, captured_at=None):
    """Retain source observations/errors, recompute scores, never invent capture time.

    Migration accepts v1 as well as v2. Guided transcripts are not reports.
    v3 input is validated and copied; callers cannot silently overwrite identity/time.
    """
    validate_report(report)
    if report.get("document_type") == "guided":
        raise ValueError("migration requires a report, not a guided transcript")
    result = copy.deepcopy(report)
    version = result["schema_version"]
    if version == "3.0":
        if fleet_id is not None or captured_at is not None:
            raise ValueError("cannot override identity or capture time on a v3 report")
        return result
    if version == "1.0":
        result.update(document_type="report", topology=None,
                      provenance={"source": "saved v1 report", "references": [], "identifier_policy": "legacy observations retained; synthetic inputs only"})
        for drive in result["drives"]:
            drive.update(mam=None, inquiry=None, tapealert_response=None)
        for library in result["libraries"]:
            library["checks"] = library_checks(library["status"]) if library["status"] else []
    result.update(schema_version="3.0", tool_version=__version__, fleet_id="SYNTH-UNASSIGNED" if fleet_id is None else fleet_id,
                  captured_at=timestamp(captured_at), migration={"from_version": version, "original_tool_version": report["tool_version"],
                  "notes": ["Scores recomputed with triage-v3.0.0; source observations retained.",
                            "Capture time unknown unless explicitly supplied; never inferred from file mtime."]})
    for kind, assets in (("drive", result["drives"]), ("library", result["libraries"])):
        for asset in assets:
            serial = (asset.get("inquiry") or {}).get("serial") if kind == "drive" else None
            if serial and serial.startswith("SYNTH-") and "REDACTED" not in serial:
                asset.update(asset_id=serial, identity_basis="synthetic-serial")
            else:
                asset.update(asset_id=kind + ":" + asset["device"], identity_basis="device-path")
            asset["health"] = (score_drive if kind == "drive" else score_library)(asset, result["errors"])
    result["health"] = score_report(result)
    return validate_report(result)


def refresh(report):
    """Recompute health after an authorized synthetic-fixture edit, without migration."""
    for asset in report["drives"]:
        asset["health"] = score_drive(asset, report["errors"])
    for asset in report["libraries"]:
        asset["health"] = score_library(asset, report["errors"])
    report["health"] = score_report(report)
    return validate_report(report)
