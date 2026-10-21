"""Isolated registration/dispatch for the v4 offline analysis commands."""

import argparse
import html
import json
from pathlib import Path

from .explain import explain
from .history import load_series, log_trend, tapealert_history
from .inventory_diff import diff_inventory
from .logsense import PROFILES, parse_log_hex
from .report import read_capture

COMMANDS = ("alert-history", "log-decode", "log-trend", "inventory-diff", "explain")


def register(subs):
    for name in COMMANDS:
        p = subs.add_parser(name, help="offline " + name)
        # Refuse explicitly in dispatch on either side of the subcommand.
        p.add_argument("--execute", action="store_true", default=argparse.SUPPRESS,
                       help="refused: this command is offline only")
        p.add_argument("--html", type=Path, help="also write an escaped self-contained HTML evidence report")
        if name == "alert-history":
            p.add_argument("reports", nargs="+", type=Path, help="2–1000 dated reports in capture order")
        elif name == "inventory-diff":
            p.add_argument("before", type=Path)
            p.add_argument("after", type=Path)
            p.add_argument("--library-id", required=True, help="caller-confirmed stable anonymous library label")
        elif name == "explain":
            p.add_argument("code", help="tapealert:20, sense:2/3a/00, asc:3a/00, page:0x2e, density:0x5e")
        else:
            p.add_argument("--from-file", required=True, type=Path)
            if name == "log-decode":
                p.add_argument("--profile", choices=PROFILES, default="ssc")


def evidence_html(value):
    """No scripts, URLs, external assets or active content from capture text."""
    body = html.escape(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False))
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            'style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            '<title>tapediag offline evidence</title>'
            '<style>body{font:1rem system-ui;max-width:80rem;margin:2rem auto;padding:1rem}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
            '<h1>Offline diagnostic evidence</h1>'
            '<p>Observations and caller-declared identities are not a hardware-health certification.</p>'
            '<pre>' + body + '</pre></html>\n')


def run(args):
    if args.execute:
        raise ValueError("this command is offline only; --execute is refused")
    if args.command == "explain":
        value = explain(args.code)
    elif args.command == "alert-history":
        if not 2 <= len(args.reports) <= 1000:
            raise ValueError("provide 2 to 1000 snapshots")
        reports, total = [], 0
        for path in args.reports:
            text = read_capture(path)
            total += len(text.encode("utf-8"))
            if total > 16 * 1024 * 1024:
                raise ValueError("history inputs exceed aggregate 16 MiB limit")
            # Reuse bounded reader and strict duplicate/nonfinite JSON decoder.
            report = load_series(text)
            reports.append(report)
        value = tapealert_history(reports)
    elif args.command == "inventory-diff":
        value = diff_inventory(read_capture(args.before), read_capture(args.after), args.library_id)
    elif args.command == "log-decode":
        value = parse_log_hex(read_capture(args.from_file), args.profile)
    else:
        value = log_trend(load_series(read_capture(args.from_file)))
    if args.html:
        args.html.write_text(evidence_html(value), encoding="utf-8")
    return value
