"""Resumable read-only workflow. Saved state is data, never a command source."""
import json
import os
from pathlib import Path

from . import __version__
from .health import summarize
from .observations import parse_inquiry, parse_mam, library_checks
from .parsers import parse_inventory, parse_logpages, parse_library
from .report import COMMON_PAGES, read_capture
from .safety import Runner, device_path, inquiry_commands, log_command, mam_commands, validate_command
from .tapealert import parse_tapealert
from .validation import validate_report

VENDOR_GUIDE = "https://www.ibm.com/support/pages/ibm-tape-device-drivers-and-diagnostic-tool-users-guide"
NOT_PERFORMED = [{"name": n, "status": "NOT PERFORMED BY THIS TOOL - see vendor tool", "url": VENDOR_GUIDE}
                 for n in ("write/read test", "erase", "firmware update", "load/unload")]


def plan(drives=(), changers=()):
    steps = []
    def add(kind, device, commands, explanation, prerequisite, seconds):
        steps.append({"id": kind + ":" + (device or "host"), "kind": kind, "device": device,
                      "argv": [validate_command(a) for a in commands], "explanation": explanation,
                      "prerequisite": prerequisite, "expected_seconds": seconds,
                      "interpretation": "pass: decoded observations without flagged conditions; warn: incomplete/attention; fail: command failure or critical alert. Unsupported pages remain explicit.",
                      "source": "https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8" if kind in ("tapealert", "logpages") else
                                "https://github.com/mtx-org/mtx/blob/master/mtx/mtx.1" if kind == "library" else
                                "https://doug-gilbert.github.io/scsi/lsscsi.html" if kind == "inventory" else
                                "https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_%s.8" % ("read_attr" if kind == "mam" else "inq"),
                      "status": "planned", "results": [], "data": None, "notes": []})
    add("inventory", None, [["lsscsi", "-g"], ["sg_map", "-x"]], "Review cached topology; verify explicit generic-device selections. No numeric sg/st equivalence is assumed.", "no medium needed", 2)
    for dev in dict.fromkeys(drives):
        device_path(dev)
        add("inquiry", dev, inquiry_commands(dev), "Read firmware revision and VPD identity; redact serial and device identifiers.", "no medium needed", 3)
        add("tapealert", dev, [log_command(dev, "0x2e")], "Read SSC drive TapeAlert. Reading can acknowledge latched flags on some firmware.", "no medium needed", 2)
        add("logpages", dev, [log_command(dev, p) for p in COMMON_PAGES], "Read documented counters; unsupported pages and unknown fields are retained, never reset.", "no medium needed", 10)
        add("mam", dev, mam_commands(dev), "Read selected cartridge attributes in partition 0 / logical volume 0. Does not load media.", "medium loaded", 6)
    for dev in dict.fromkeys(changers):
        add("library", device_path(dev), [["mtx", "-f", dev, "status"]], "Read element status and check barcodes/source-slot consistency. Does not inventory or move the robot.", "changer present", 5)
    return steps


def interpret(step):
    kind = step["kind"]
    text = "\n".join(r["stdout"] for r in step["results"] if r["returncode"] == 0 and not r["error"])
    parsers = {"inventory": parse_inventory, "inquiry": parse_inquiry, "tapealert": parse_tapealert,
               "logpages": parse_logpages, "mam": parse_mam, "library": parse_library}
    if kind == "logpages":
        data = {"pages": [], "preamble": [], "warnings": []}
        for result in step["results"]:
            if result["returncode"] == 0 and not result["error"]:
                # Current sg_logs releases can omit the numeric page header.
                hint = result["argv"][2].split("=", 1)[1]
                parsed = parse_logpages(result["stdout"], hint)
                for key in data:
                    data[key].extend(parsed[key])
    else:
        data = parsers[kind](text)
    step["data"] = data
    if kind == "inventory" and not data["devices"]:
        data["warnings"].append("no tape/changer inventory entries observed")
    if kind == "inquiry" and (not data["identifiers"] or any(data[k] is None for k in ("vendor", "product", "revision", "serial"))):
        data["warnings"].append("inquiry/VPD identity coverage incomplete")
    if kind == "mam":
        from .observations import MAM_ATTRIBUTES
        if {a["id"] for a in data["attributes"]} != set(MAM_ATTRIBUTES):
            data["warnings"].append("selected MAM attribute coverage incomplete")
    if kind == "logpages" and (any(not r["stdout"].strip() for r in step["results"] if r["returncode"] == 0) or any(not p["parameters"] and not p["supported_pages"] for p in data["pages"])):
        data["warnings"].append("one or more decoded pages contain no recognized parameters")
    if any(r["error"] or r["returncode"] != 0 for r in step["results"]):
        step["status"] = "fail"
    elif kind == "tapealert" and any(f["severity"] == "Critical" for f in data["active_flags"]):
        step["status"] = "fail"
    elif data.get("warnings") or (kind == "tapealert" and data["active_flags"]):
        step["status"] = "warn"
    elif kind == "library" and any(c["severity"] == "warn" for c in library_checks(data)):
        step["status"] = "warn"
    else:
        step["status"] = "pass"
    if kind == "logpages":
        partial = {"drives": [{"device": step["device"], "logpages": data}], "libraries": [], "errors": []}
        health = summarize(partial)
        if health["matches"] or any("usable health parameters" in g for g in health["gaps"]):
            step["status"] = "fail" if step["status"] == "fail" else "warn"


def save_state(path, transcript):
    """Atomic replacement in the same directory, including on interruption."""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    if path.is_symlink() or temporary.is_symlink():
        raise ValueError("state file and temporary path must not be symlinks")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(transcript, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))


def run_guided(drives=(), changers=(), execute=False, confirmed=False, medium_loaded=False,
               state_file=None, resume=False, timeout=15, runner=None):
    if execute and (not confirmed or not (drives or changers)):
        raise ValueError("guided --execute requires explicit --drive/--changer paths and --i-understand-read-only")
    if resume and not state_file:
        raise ValueError("--resume requires --state-file")
    steps = plan(drives, changers)
    transcript = {"schema_version": "2.0", "document_type": "guided", "tool_version": __version__,
                  "mode": "execute" if execute else "dry-run", "medium_loaded": medium_loaded,
                  "steps": steps, "not_performed": NOT_PERFORMED, "complete": False}
    if resume:
        old = validate_report(json.loads(read_capture(state_file)))
        if old.get("document_type") != "guided" or old["mode"] != transcript["mode"] or old["medium_loaded"] != medium_loaded:
            raise ValueError("resume state belongs to a different workflow or mode")
        if len(old["steps"]) != len(steps):
            raise ValueError("resume plan differs from explicit device selection")
        for expected, saved in zip(steps, old["steps"]):
            if any(saved[k] != expected[k] for k in expected if k not in ("status", "results", "data", "notes")):
                raise ValueError("resume plan differs from current allowlisted plan")
            if saved["status"] in ("pass", "warn"):
                if [r["argv"] for r in saved["results"]] != expected["argv"] or any(r["returncode"] != 0 or r["error"] for r in saved["results"]):
                    raise ValueError("resume success lacks successful command evidence")
                expected.update(results=saved["results"])
                interpret(expected)  # Reinterpret saved results, do not trust saved verdict/data.
    runner = runner or Runner(execute, timeout)
    if runner.execute != execute:
        raise ValueError("runner mode differs from guided mode")
    if state_file and not resume and Path(state_file).exists():
        raise ValueError("state file already exists; use --resume or choose a new file")
    if state_file:
        save_state(state_file, validate_report(transcript))
    if execute:
        for step in steps:
            if step["status"] in ("pass", "warn"):
                continue
            if step["prerequisite"] == "medium loaded" and not medium_loaded:
                step.update(status="skipped", notes=["MAM skipped: --medium-loaded was not declared; tool never loads media."])
            else:
                step["results"] = [runner.run(argv).to_dict() for argv in step["argv"]]
                interpret(step)
            if state_file:
                save_state(state_file, validate_report(transcript))
        transcript["complete"] = True
    if state_file:
        save_state(state_file, validate_report(transcript))
    return validate_report(transcript)
