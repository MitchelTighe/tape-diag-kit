"""CLI: command planning by default; explicit execution or pure offline parsing."""

import argparse
import json
import math
import sys
from pathlib import Path

from . import __version__
from .parsers import PARSERS, parse_drive_status, parse_logpages
from .report import (COMMON_PAGES, live_report, offline_report, planned_report,
                     read_capture, saved_report)
from .safety import Runner, SafetyError, device_path, drive_commands, log_command, mam_commands, inquiry_commands
from .sysfs import inventory_sysfs
from .validation import validate_report


def timeout_value(value):
    timeout = float(value)
    if not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise argparse.ArgumentTypeError("timeout must be in (0, 300] seconds")
    return timeout


def parser():
    root = argparse.ArgumentParser(prog="tapediag", description="Read-only tape diagnostics. Dry-run is the default.")
    root.add_argument("--version", action="version", version=__version__)
    # These work before or after the subcommand; SUPPRESS prevents overwriting.
    def common(p, suppress=False):
        default = argparse.SUPPRESS if suppress else False
        p.add_argument("--execute", action="store_true", default=default, help="execute only allowlisted read-only commands")
        p.add_argument("--timeout", type=timeout_value, default=argparse.SUPPRESS if suppress else 15.0, metavar="SECONDS")
    common(root)
    subs = root.add_subparsers(dest="command", required=True)
    p = subs.add_parser("ltfs-index", help="offline streaming LTFS index validation")
    common(p, True)
    p.add_argument("--from-file", type=Path, required=True)
    p.add_argument("--block-size", type=int, help="blocksize from the LTFS label, in bytes")
    p.add_argument("--previous-index", type=Path, help="optional referenced previous full index")
    p.add_argument("--scratch-dir", type=Path, help="directory for temporary disk-backed checks")
    for name in list(PARSERS) + ["report", "guided"]:
        p = subs.add_parser(name)
        common(p, True)
        p.add_argument("--from-file", type=Path, help="parse saved output without subprocesses")
        if name in ("tapealert", "logpages", "drive-status", "library", "ltfs", "mam", "inquiry"):
            p.add_argument("device", nargs="?", help="/dev/sgN (optional in offline mode)")
        if name == "inventory":
            p.add_argument("--source", choices=("auto", "lsscsi", "sysfs"), default="auto")
            p.add_argument("--sysfs-root", type=Path, default=Path("/sys"))
        if name in ("drive-status", "report"):
            p.add_argument("--nst", help="explicit /dev/nstN for mt status (never inferred from sg index)")
        if name == "guided":
            from .workflows import CATALOG
            p.add_argument("--workflow", choices=tuple(CATALOG))
            p.add_argument("--menu", action="store_true", help="choose a named workflow interactively")
            p.add_argument("--from-report", type=Path, help="use a saved report as decision-tree evidence")
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--drive", action="append", default=[])
            p.add_argument("--changer", action="append", default=[])
            p.add_argument("--i-understand-read-only", action="store_true")
            p.add_argument("--medium-loaded", action="store_true", help="declare that media is already loaded; never loads media")
            p.add_argument("--state-file", type=Path)
            p.add_argument("--resume", action="store_true")
        if name == "report":
            p.add_argument("--html", type=Path, help="write a self-contained HTML report from saved or collected data")
            p.add_argument("--schema-version", choices=("1.0", "2.0", "3.0"), default="3.0")
            p.add_argument("--fleet-id", help="anonymous stable fleet scope for v3")
            p.add_argument("--captured-at", help="ISO-8601 capture time with timezone, never inferred for saved captures")
            p.add_argument("--from-dir", type=Path, help="directory of saved command captures")
            p.add_argument("--drive", action="append", default=[], help="/dev/sgN; repeat for several drives")
            p.add_argument("--changer", action="append", default=[], help="/dev/sgN; repeat for several changers")
    for name in ("migrate", "validate", "dashboard", "watch", "export-csv"):
        p = subs.add_parser(name, help="offline " + name)
        if name in ("migrate", "validate"):
            p.add_argument("--from-file", type=Path, required=True)
        elif name == "watch":
            p.add_argument("before", type=Path)
            p.add_argument("after", type=Path)
        else:
            p.add_argument("reports", nargs="*" if name == "dashboard" else "+", type=Path)
            p.add_argument("--output", type=Path, required=name == "dashboard")
        if name == "migrate":
            p.add_argument("--fleet-id")
            p.add_argument("--captured-at")
    from .offline_cli import register
    register(subs)
    return root


def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False))


def filter_ltfs(data, device):
    if device:
        device_path(device)
        data["devices"] = [row for row in data["devices"] if row["device"] == device]
        if not data["devices"]:
            data["warnings"].append("requested device not present in LTFS listing: " + device)
    return data


def main(argv=None):
    root = parser()
    args = root.parse_args(argv)
    try:
        if args.command == "ltfs-index":
            if args.execute:
                raise ValueError("ltfs-index is offline only; --execute is refused")
            from .ltfs_index import validate_index
            result = validate_index(args.from_file, block_size=args.block_size, scratch_dir=args.scratch_dir,
                                    previous_index=args.previous_index)
            emit(result)
            return 0 if result["valid"] else 1
        from .offline_cli import COMMANDS, run
        if args.command in COMMANDS:
            emit(run(args))
            return 0
        if args.command in ("migrate", "validate", "dashboard", "watch", "export-csv"):
            if args.execute:
                raise ValueError("this command is offline only; --execute is refused")
            from .v3 import migrate
            from .fleet import csv_text, diff_reports
            if args.command == "validate":
                value = saved_report(args.from_file)
                emit({"valid": True, "schema_version": value["schema_version"], "document_type": value.get("document_type", "report")})
            elif args.command == "migrate":
                emit(migrate(saved_report(args.from_file), args.fleet_id, args.captured_at))
            elif args.command == "watch":
                value = diff_reports(saved_report(args.before), saved_report(args.after))
                emit(value)
                return 1 if value["regressions"] else 0
            elif args.command == "dashboard":
                from .dashboard import render_dashboard
                args.output.write_text(render_dashboard([saved_report(p) for p in args.reports]), encoding="utf-8")
                emit({"dashboard": str(args.output), "reports": len(args.reports)})
            else:
                content = csv_text([saved_report(p) for p in args.reports])
                if args.output:
                    args.output.write_text(content, encoding="utf-8")
                else:
                    print(content, end="")
            return 0
        if args.command == "guided":
            from .workflows import choose_workflow, run_workflow
            if args.menu and args.workflow:
                raise ValueError("choose --menu or --workflow")
            if args.menu:
                if not sys.stdin.isatty():
                    raise ValueError("--menu requires a terminal; use --workflow in scripts")
                args.workflow = choose_workflow()
            if args.workflow:
                if args.from_file or args.resume or args.state_file:
                    raise ValueError("named workflows use --from-report; resumable legacy collection uses guided without --workflow")
                if args.dry_run and args.execute:
                    raise ValueError("--dry-run and --execute are mutually exclusive")
                value = run_workflow(args.workflow, args.drive, args.changer, args.execute, args.i_understand_read_only,
                                     args.medium_loaded, saved_report(args.from_report) if args.from_report else None, args.timeout)
                emit(value)
                return 1 if any(s["status"] == "fail" for s in value["steps"]) else 0
            if args.from_report:
                raise ValueError("--from-report requires --workflow or --menu")
            from .guided import run_guided
            if args.from_file:
                if args.execute or args.resume or args.state_file:
                    raise ValueError("guided replay cannot execute or change state")
                value = saved_report(args.from_file)
                if value.get("document_type") not in ("guided", "workflow"):
                    raise ValueError("expected a guided transcript")
            else:
                if args.dry_run and args.execute:
                    raise ValueError("--dry-run and --execute are mutually exclusive")
                value = run_guided(args.drive, args.changer, args.execute, args.i_understand_read_only,
                                   args.medium_loaded, args.state_file, args.resume, args.timeout)
            emit(value)
            return 1 if any(s["status"] == "fail" for s in value["steps"]) else 0
        def output_report(result, directory=None, runner=None):
            if args.schema_version in ("2.0", "3.0") and result["schema_version"] == "1.0" and (directory or runner):
                from .v2 import enrich
                result = enrich(result, directory, runner)
            if args.schema_version == "3.0" and (directory or runner):
                from .v3 import migrate
                from datetime import datetime, timezone
                result = migrate(result, args.fleet_id, args.captured_at or (datetime.now(timezone.utc).isoformat() if runner else None))
            validate_report(result)
            if result.get("document_type") in ("guided", "workflow"):
                raise ValueError("report expects a report document, not a guided transcript")
            if args.html:
                if result["schema_version"] == "3.0":
                    from .dashboard import render_dashboard
                    html = render_dashboard([result])
                else:
                    from .html_report import render_html
                    html = render_html(result)
                args.html.write_text(html, encoding="utf-8")
            emit(result)
            return 1 if result["errors"] else 0
        if args.command == "report" and (args.fleet_id is not None or args.captured_at is not None):
            if args.from_file or args.schema_version != "3.0":
                raise ValueError("identity/time metadata requires new v3 collection; use migrate for saved legacy reports")
        if args.from_file and (args.execute or getattr(args, "from_dir", None)):
            raise ValueError("--from-file cannot be combined with --execute or --from-dir")
        if getattr(args, "from_dir", None) and args.execute:
            raise ValueError("--from-dir cannot be combined with --execute")
        if getattr(args, "nst", None):
            device_path(args.nst, "nst")
            if args.command == "report" and len(args.drive) != 1:
                raise ValueError("--nst with report requires exactly one explicit --drive")
        if args.from_file:
            result = saved_report(args.from_file) if args.command == "report" else PARSERS[args.command](read_capture(args.from_file))
            if args.command == "ltfs":
                result = filter_ltfs(result, args.device)
            if args.command == "report":
                return output_report(result)
            emit(result)
            return 0
        if args.command == "report" and args.from_dir:
            result = offline_report(args.from_dir)
            return output_report(result, directory=args.from_dir)
        runner = Runner(args.execute, args.timeout)
        if args.command == "itdt":
            raise ValueError("itdt is parse-only: provide --from-file; ITDT is never executed")
        if args.command == "report":
            commands = planned_report(args.drive, args.changer, args.nst)
            if args.schema_version in ("2.0", "3.0"):
                commands.insert(1, ["sg_map", "-x"])
                for dev in args.drive:
                    commands.extend(inquiry_commands(dev) + mam_commands(dev))
            if args.html and not args.execute:
                raise ValueError("--html requires --from-file, --from-dir or --execute")
            if not args.execute:
                emit([runner.run(c).argv for c in commands])
                return 0
            result = live_report(runner, args.drive, args.changer, args.nst)
            return output_report(result, runner=runner)
        if args.command == "inventory":
            if args.source == "sysfs":
                emit(inventory_sysfs(args.sysfs_root) if args.execute else [])
                return 0
            commands = [["lsscsi", "-g"]]
        elif args.command == "topology":
            commands = [["sg_map", "-x"]]
        elif args.command == "ltfs":
            if args.device:
                device_path(args.device)
            commands = [["ltfs", "-o", "device_list"]]
        else:
            if not args.device:
                raise ValueError("provide a /dev/sgN device or --from-file")
            device_path(args.device)
            if args.command == "mam":
                commands = mam_commands(args.device)
            elif args.command == "inquiry":
                commands = inquiry_commands(args.device)
            elif args.command == "tapealert":
                commands = [log_command(args.device, "0x2e")]
            elif args.command == "logpages":
                commands = [log_command(args.device, page) for page in COMMON_PAGES]
            elif args.command == "drive-status":
                commands = drive_commands(args.device, args.nst)
            else:
                commands = [["mtx", "-f", args.device, "status"]]
        results = [runner.run(c) for c in commands]
        if not args.execute:
            emit([r.argv for r in results])
            return 0
        errors = [r.error for r in results if r.error]
        text = "\n".join(r.stdout for r in results if r.ok)
        if args.command == "inventory" and errors and args.source == "auto":
            data = inventory_sysfs(args.sysfs_root)
        elif args.command == "drive-status":
            data = parse_drive_status(text + "\n" + results[1].stderr, results[1].returncode)
            if not args.nst:
                data["warnings"].append("mt status skipped: supply --nst with the confirmed non-rewinding device")
        elif args.command == "logpages":
            data = {"pages": [], "preamble": [], "warnings": []}
            for result, page in zip(results, COMMON_PAGES):
                if result.ok:
                    parsed = parse_logpages(result.stdout, page)
                    for key in data:
                        data[key].extend(parsed[key])
        elif args.command == "ltfs":
            data = PARSERS[args.command](text + "\n" + "\n".join(r.stderr for r in results if r.ok))
        else:
            data = PARSERS[args.command](text) if any(r.ok for r in results) else None
        if args.command == "ltfs":
            data = filter_ltfs(data, args.device)
        emit({"data": data, "commands": [r.to_dict() for r in results], "errors": errors})
        return 1 if errors else 0
    except (SafetyError, ValueError, OSError, EOFError) as exc:
        message = "local input/output unavailable (path withheld)" if isinstance(exc, OSError) else str(exc)
        print(json.dumps({"error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
