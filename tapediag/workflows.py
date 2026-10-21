"""Field-tech workflows: exact read-only plans and evidence-driven decision trees.

Saved report data can drive recommendations, never argv. All live argv are
regenerated from explicit validated paths. Dump retrieval is a plan only.
"""
from . import __version__
from .guided import NOT_PERFORMED, interpret, plan
from .observations import library_checks
from .parsers import parse_drive_status
from .safety import Runner, device_path, validate_command
from .scoring import CLEANING_HOURS_NAMES, active_flags, mam_value, parameters
from .validation import validate_report

CATALOG = {
    "identify": ("Identify drive and library", ("inquiry", "library-inquiry", "library")),
    "firmware": ("Review firmware level", ("inquiry", "library-inquiry")),
    "tapealert": ("Check TapeAlert", ("tapealert", "logpages")),
    "cleaning": ("Review cleaning status", ("tapealert", "logpages")),
    "mam": ("Read cartridge MAM", ("mam",)),
    "dump-plan": ("Prepare drive-dump CAPTURE PLAN", ("inquiry", "tapealert", "logpages")),
    "inventory-audit": ("Audit library inventory", ("library",)),
    "wont-load": ("Tape won't load decision tree", ("inquiry", "readiness", "tapealert", "library")),
    "slow-drive": ("Slow drive decision tree", ("inquiry", "tapealert", "logpages", "mam")),
}
VENDOR = "https://www.ibm.com/docs/en/tape-drive?topic=information-tape-diagnostic-tool-itdt"


def workflow_plan(name, drives=(), changers=()):
    if name not in CATALOG:
        raise ValueError("unknown workflow: " + name)
    kinds = CATALOG[name][1]
    steps = [s for s in plan(drives, changers) if s["kind"] == "inventory" or s["kind"] in kinds]
    for dev in changers:
        device_path(dev)
        if "library-inquiry" in kinds:
            template = next(s for s in plan([dev]) if s["kind"] == "inquiry")
            template.update(id="library-inquiry:" + dev, kind="library-inquiry", argv=[["mtx", "-f", dev, "inquiry"]],
                            explanation="Read changer identity and firmware; never initialize element status.")
            steps.append(template)
    for dev in drives:
        if "readiness" in kinds:
            template = next(s for s in plan([dev]) if s["kind"] == "inquiry")
            template.update(id="readiness:" + dev, kind="readiness", argv=[["sg_turs", dev]],
                            explanation="Read readiness; may consume a pending unit attention. Does not load media.")
            steps.append(template)
    return steps


def decide(name, asset, inventory=None):
    """One deterministic terminal path per asset; unknown evidence stays unknown."""
    path = []
    def ask(node, answer):
        path.append(node + ":" + answer)
    def done(outcome, reason, *actions):
        return {"device": asset["device"], "outcome": outcome, "path": path, "reason": reason, "next_steps": list(actions)}
    flags = active_flags(asset)
    critical = any(f["severity"] == "Critical" for f in flags.values())
    cleaning = bool({20, 21} & set(flags))
    health = asset.get("health") or {}
    inventory_identity = next((dict(product=d.get("model"), revision=d.get("revision"))
                               for d in (inventory or {}).get("devices", [])
                               if d.get("generic_device") == asset["device"]), {})
    if name == "identify":
        identity = asset.get("inquiry") or asset.get("drive_status") or inventory_identity
        ask("identity", "observed" if identity.get("product") else "missing")
        if not identity.get("product"):
            return done("identity-missing", "Product identity unavailable", "Review saved inquiry or a planned inquiry collection.")
        mapped = any(d.get("generic_device") == asset["device"] for d in (inventory or {}).get("devices", []))
        ask("mapping", "observed" if mapped else "missing")
        return done("identified" if mapped else "mapping-missing", "Product: %s; firmware: %s" % (identity["product"], identity.get("revision") or "unknown"), "Verify device mapping with the owning application before any external maintenance.")
    if name == "firmware":
        revision = (asset.get("inquiry") or asset.get("drive_status") or inventory_identity).get("revision")
        ask("revision", "observed" if revision else "missing")
        return done("revision-observed" if revision else "revision-missing", "Observed firmware: " + (revision or "unknown"), "Compare the exact model/revision with its public vendor compatibility documentation; no latest-version assertion is made.")
    if name == "tapealert":
        obs = asset.get("tapealert")
        covered = bool(obs) and len(obs["observed_flags"]) == 64 and not obs.get("warnings")
        ask("alerts", "active" if flags else "clear" if covered else "unknown")
        return done("alerts-active" if flags else "alerts-clear" if covered else "alerts-unknown", "%d active flags; full 2Eh coverage %s" % (len(flags), covered), "Review decoded flag actions and retain the saved observations; no flags are reset.")
    if name == "cleaning":
        request = parameters(asset, "0x0c", ("cleaning required", "cleaning action required"))
        lines = [line.lower() for p in (asset.get("logpages") or {}).get("pages", []) if p["page"] == "0x0c" for line in p["raw_lines"]]
        if any(line in ("cleaning action required", "cleaning action required (or in progress)") for line in lines):
            request = 1
        elif "cleaning action not required (or completed)" in lines:
            request = 0
        ask("request", "yes" if cleaning or request == 1 else "no" if request == 0 else "unknown")
        if cleaning or request == 1:
            return done("cleaning-requested", "A drive cleaning request is active", "Arrange vendor-approved cleaning through a separate authorized procedure; this workflow never cleans or moves media.")
        age = parameters(asset, "0x14", CLEANING_HOURS_NAMES, (None, "hours"))
        ask("age", "unknown" if age is None else "review" if age >= 100 else "below-threshold")
        outcome = "cleaning-unknown" if age is None or request != 0 else "cleaning-age-review" if age >= 100 else "cleaning-clear"
        return done(outcome, "Motion hours since cleaning: %s; age threshold is heuristic" % age, "Use drive cleaning requests and vendor instructions; elapsed age alone does not mandate cleaning.")
    if name == "mam":
        attrs = (asset.get("mam") or {}).get("attributes", [])
        ask("attributes", "absent" if not attrs else "complete" if all(mam_value(asset, c) is not None for c in ("0x0003", "0x0220", "0x0221")) else "partial")
        return done("mam-absent" if not attrs else "mam-read" if path[-1].endswith("complete") else "mam-partial", "%d selected attributes observed; absent media is not a drive failure" % len(attrs), "Keep cartridge load/lifetime observations with their units; this tool never loads a cartridge.")
    if name == "dump-plan":
        ask("capture", "plan-only")
        return done("capture-plan", "No dump generated, retrieved, or uploaded", "Retain this read-only report, capture timestamp, model and firmware, TapeAlert and counter evidence.", "Coordinate with the application owner and vendor support for a separately authorized dump procedure: " + VENDOR,
                    "Check vendor dump side effects, privacy, storage destination and free space locally before capture; do not send private data to third parties.")
    if name == "inventory-audit":
        status = asset.get("status")
        ask("status", "observed" if status else "missing")
        if not status:
            return done("inventory-missing", "No element status available", "Review saved mtx status; no inventory command is run.")
        checks = library_checks(status)
        warns = [c for c in checks if c["severity"] == "warn"]
        ask("consistency", "warnings" if warns else "consistent")
        return done("inventory-review" if warns else "inventory-consistent", "%d consistency warnings; full/empty is not a robotics health certification" % len(warns), "Compare logical inventory with the owning application; never infer sg-to-element associations.")
    ask("critical", "yes" if critical else "no")
    if critical:
        return done("critical-alert", "Critical TapeAlert requires attention", "Preserve evidence and review vendor flag guidance; use dump-plan before any external recovery.")
    ask("cleaning", "yes" if cleaning else "no")
    if cleaning:
        return done("cleaning-requested", "Cleaning request may affect operation", "Review the cleaning workflow; no cleaning is executed.")
    obs = asset.get("tapealert")
    covered = bool(obs) and len(obs["observed_flags"]) == 64 and not obs.get("warnings")
    ask("alert-coverage", "complete" if covered else "incomplete")
    if not covered:
        return done("alerts-unknown", "Incomplete TapeAlert evidence; a drive fault cannot be excluded", "Review the TapeAlert workflow or a complete saved capture before interpreting the symptom.")
    if name == "wont-load":
        ready = (asset.get("drive_status") or {}).get("ready")
        ask("ready", "unknown" if ready is None else "yes" if ready else "no")
        if ready is None:
            return done("readiness-unknown", "Readiness has not been established", "Review the read-only readiness plan and application ownership.")
        if ready:
            return done("ready-review", "Drive reports ready; loading symptoms may be intermittent or historical", "Compare saved application events and cartridge compatibility; no retry or move is issued.")
        return done("not-ready-review", "Not ready alone cannot distinguish absent media, initialization, or a load fault", "Inspect public generation compatibility and application/library inventory evidence.", "Review visible cartridge/door indicators through an authorized local procedure; never force a load/unload here.")
    if name == "slow-drive":
        error_values = [parameters(asset, p, ("total uncorrected errors", "total uncorrected read errors", "total uncorrected write errors")) for p in ("0x02", "0x03")]
        ask("errors", "positive" if any(v is not None and v > 0 for v in error_values) else "unknown" if None in error_values else "zero")
        if any(v is not None and v > 0 for v in error_values):
            return done("error-review", "Historical uncorrected errors can accompany retries; no rate inferred", "Compare two time-separated reports using watch; counter resets invalidate rates.")
        if None in error_values:
            return done("performance-unknown", "Read/write counters incomplete", "Collect a second read-only snapshot with application timing context.")
        age = any(r["id"] in ("mam-loads", "mam-lifetime", "head-hours") for r in health.get("reasons", []))
        ask("lifetime", "review" if age else "no-threshold")
        if age:
            return done("lifetime-review", "Heuristic usage threshold reached; this is not a wear diagnosis", "Review cartridge/drive history against vendor guidance.")
        return done("streaming-review", "No decisive drive fault observed; no benchmark was performed", "Review host streaming, block size, compression and application concurrency from saved evidence.", "Capture another timestamped report; lifetime totals alone cannot measure throughput.")
    raise ValueError("unknown workflow: " + name)


def report_from_steps(steps, drives, changers):
    report = {"inventory": None, "drives": [{"device": d} for d in drives], "libraries": [{"device": d} for d in changers]}
    fields = {"inquiry": "inquiry", "library-inquiry": "inquiry", "tapealert": "tapealert", "logpages": "logpages", "mam": "mam", "library": "status", "readiness": "drive_status"}
    for step in steps:
        if step["kind"] == "inventory":
            report["inventory"] = step["data"]
        else:
            for asset in report["drives"] + report["libraries"]:
                if asset["device"] == step["device"]:
                    asset[fields[step["kind"]]] = step["data"]
    from .scoring import score_drive
    for drive in report["drives"]:
        drive["health"] = score_drive(drive)
    return report


def run_workflow(name, drives=(), changers=(), execute=False, confirmed=False, medium_loaded=False,
                 report=None, timeout=15, runner=None):
    if report is not None and execute:
        raise ValueError("saved report workflow cannot execute")
    if execute and (not confirmed or not (drives or changers)):
        raise ValueError("workflow --execute requires explicit devices and --i-understand-read-only")
    if name == "inventory-audit" and drives:
        raise ValueError("inventory-audit uses --changer, not --drive")
    steps = workflow_plan(name, drives, changers)
    if execute:
        runner = runner or Runner(True, timeout)
        if not runner.execute:
            raise ValueError("runner mode differs from workflow mode")
        for step in steps:
            if step["kind"] == "mam" and not medium_loaded:
                step.update(status="skipped", notes=["MAM requires --medium-loaded; media is never loaded."])
                continue
            step["results"] = [runner.run(validate_command(a)).to_dict() for a in step["argv"]]
            if step["kind"] in ("library-inquiry", "readiness"):
                result = step["results"][0]
                step["data"] = parse_drive_status(result["stdout"] + "\n" + result["stderr"], result["returncode"] if step["kind"] == "readiness" else None)
                step["status"] = "fail" if result["error"] else "warn" if step["kind"] == "library-inquiry" and not step["data"]["product"] else "pass"
            else:
                interpret(step)
        report = report_from_steps(steps, drives, changers)
    elif report is not None:
        validate_report(report)
        if report.get("document_type") == "guided":
            raise ValueError("workflow evidence must be a report")
        if drives or changers:
            selected = set(drives) | set(changers)
            observed = {a["device"] for a in report["drives"] + report["libraries"]}
            if not selected <= observed:
                raise ValueError("selected device absent from saved report")
    assets = []
    if report is not None:
        assets = report["libraries"] if name == "inventory-audit" else report["drives"]
        if name in ("identify", "firmware"):
            assets = report["drives"] + report["libraries"]
        if drives or changers:
            assets = [a for a in assets if a["device"] in set(drives) | set(changers)]
    return validate_report({"schema_version": "3.0", "document_type": "workflow", "tool_version": __version__,
        "workflow": name, "title": CATALOG[name][0], "mode": "execute" if execute else "offline" if report is not None else "dry-run",
        "medium_loaded": medium_loaded, "steps": steps, "decisions": [decide(name, a, report.get("inventory")) for a in assets],
        "limitations": ["Read-only observations can consume unit attention or acknowledge latched alerts.", "No media motion, tests, firmware operations, dump capture or upload."] + ([] if assets or report is None else ["No applicable assets observed; decision unavailable."]),
        "not_performed": NOT_PERFORMED, "complete": report is not None})


def choose_workflow(input_fn=input, stream=None):
    import sys
    stream = stream or sys.stderr
    names = list(CATALOG)
    for index, key in enumerate(names, 1):
        print("%d. %s [%s]" % (index, CATALOG[key][0], key), file=stream)
    print("Select workflow number (q cancels): ", end="", file=stream, flush=True)
    value = input_fn().strip()
    if value.lower() == "q":
        raise ValueError("workflow selection cancelled; nothing executed")
    if not value.isdigit() or not 1 <= int(value) <= len(names):
        raise ValueError("invalid workflow selection; nothing executed")
    return names[int(value) - 1]
