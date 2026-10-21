"""Version 2 report enrichment; the v1 assembly API remains available."""
from pathlib import Path

from .health import summarize
from .observations import library_checks, parse_inquiry, parse_mam, parse_topology, response_from_page
from .report import read_capture
from .safety import inquiry_commands, mam_commands


def enrich(report, directory=None, runner=None):
    report["schema_version"] = "2.0"
    report["document_type"] = "report"
    report["topology"] = None
    report["provenance"] = {"source": "offline saved captures" if directory else "read-only collection",
                            "references": ["https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8",
                                           "https://www.t10.org/ftp/t10/document.05/05-154r2.pdf"],
                            "identifier_policy": "MAM serial and VPD identifiers replaced with SYNTH placeholders; no raw originals retained"}

    def collect(parser, filename=None, commands=()):
        if directory:
            path = Path(directory) / filename
            return parser(read_capture(path)) if path.is_file() else None
        outputs = []
        for argv in commands:
            result = runner.run(argv)
            if result.ok:
                outputs.append(result.stdout)
            else:
                report["errors"].append({"section": argv[0], "device": argv[-1] if argv[-1].startswith("/dev/") else None,
                                         "message": result.error or "collection failed"})
        return parser("\n".join(outputs)) if outputs else None

    report["topology"] = collect(parse_topology, "topology.txt", [["sg_map", "-x"]])
    for d in report["drives"]:
        prefix = "drives/" + Path(d["device"]).name + "/"
        d["mam"] = collect(parse_mam, prefix + "mam.txt", mam_commands(d["device"]))
        d["inquiry"] = collect(parse_inquiry, prefix + "inquiry.txt", inquiry_commands(d["device"]))
        d["tapealert_response"] = next((response_from_page(p) for p in (d.get("logpages") or {}).get("pages", []) if p["page"] == "0x12"), None)
    for lib in report["libraries"]:
        lib["checks"] = library_checks(lib["status"]) if lib["status"] else []
    if runner:
        report["commands"] = [r.to_dict() for r in runner.results]
    report["health"] = summarize(report)
    return report
