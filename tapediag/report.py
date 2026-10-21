"""Versioned report assembly from saved captures or read-only commands."""

import json
import os
from pathlib import Path
import stat

from . import __version__
from .parsers import PARSERS, parse_drive_status, parse_inventory, parse_logpages
from .safety import LOG_PAGES, Runner, device_path, drive_commands, log_command
from .sysfs import inventory_sysfs
from .validation import validate_report

SCHEMA_VERSION = "1.0"
COMMON_PAGES = tuple(p for p in LOG_PAGES if p != "0x2e")


def empty_report(mode):
    return {"schema_version": SCHEMA_VERSION, "tool_version": __version__, "mode": mode,
            "inventory": None, "drives": [], "libraries": [], "ltfs": None, "itdt": None,
            "commands": [], "errors": []}


def error(report, section, device, message):
    report["errors"].append({"section": section, "device": device, "message": message})


def read_capture(path):
    """Read only a regular saved file, not devices, FIFOs, or sockets."""
    path = Path(path)
    limit = 16 * 1024 * 1024
    try:
        if not path.is_file():
            raise ValueError("saved capture must be a regular file")
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("saved capture must be a regular file")
            raw = handle.read(limit + 1)
    except OSError:
        raise ValueError("cannot read saved capture; expected an accessible regular file") from None
    if len(raw) > limit:
        raise ValueError("saved capture exceeds the 16 MiB limit")
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def offline_report(directory):
    """Fixed capture layout; no manifest commands are ever interpreted."""
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError("capture directory does not exist")
    report = empty_report("offline")

    def parse(section, path, device=None, required=True):
        if not path.is_file():
            if required:
                error(report, section, device, "missing capture: " + str(path.relative_to(directory)))
            return None
        try:
            return PARSERS[section](read_capture(path))
        except (OSError, ValueError) as exc:
            error(report, section, device, str(exc))
            return None

    report["inventory"] = parse("inventory", directory / "inventory.txt")
    for path in sorted((directory / "drives").glob("sg*")):
        if not path.is_dir():
            continue
        dev = device_path("/dev/" + path.name)
        report["drives"].append({"device": dev,
            "tapealert": parse("tapealert", path / "tapealert.txt", dev),
            "logpages": parse("logpages", path / "logpages.txt", dev),
            "drive_status": parse("drive-status", path / "drive-status.txt", dev)})
    for path in sorted((directory / "libraries").glob("sg*")):
        if path.is_dir():
            dev = device_path("/dev/" + path.name)
            report["libraries"].append({"device": dev, "status": parse("library", path / "status.txt", dev)})
    report["ltfs"] = parse("ltfs", directory / "ltfs.txt", required=False)
    report["itdt"] = parse("itdt", directory / "itdt.txt", required=False)
    # An inventory entry with no captured diagnostic section is an explicit gap.
    if report["inventory"]:
        for item in report["inventory"]["devices"]:
            key = "drives" if item["kind"] == "drive" else "libraries"
            if not any(d["device"] == item["generic_device"] for d in report[key]):
                error(report, "capture", item["generic_device"], "inventory device has no diagnostic capture directory")
    return report


def saved_report(filename):
    try:
        report = json.loads(read_capture(filename))
    except RecursionError:
        raise ValueError("saved report nesting exceeds decoder limit") from None
    return validate_report(report)


def planned_report(drives=(), changers=(), nst=None):
    commands = [["lsscsi", "-g"]]
    for index, dev in enumerate(drives):
        commands.extend(drive_commands(dev, nst if index == 0 else None))
        commands.append(log_command(dev, "0x2e"))
        commands.extend(log_command(dev, page) for page in COMMON_PAGES)
    commands.extend(["mtx", "-f", device_path(dev), "status"] for dev in changers)
    commands.append(["ltfs", "-o", "device_list"])
    return commands


def live_report(runner: Runner, drives=(), changers=(), nst=None, sysfs_root=Path("/sys")):
    if not runner.execute:
        raise ValueError("live report requires an executing runner")
    report = empty_report("execute")

    def run(section, dev, argv):
        result = runner.run(argv)
        if not result.ok:
            error(report, section, dev, result.error or "command failed")
        return result

    inv = run("inventory", None, ["lsscsi", "-g"])
    report["inventory"] = parse_inventory(inv.stdout) if inv.ok else inventory_sysfs(sysfs_root)
    drive_list = list(dict.fromkeys(drives))
    changer_list = list(dict.fromkeys(changers))
    mappings = {}
    for item in report["inventory"]["devices"]:
        sg = item["generic_device"]
        if not sg:
            error(report, "inventory", item["device"], "no generic device mapping; skipped")
            continue
        if item["kind"] == "drive":
            mappings[sg] = item["nonrewinding_device"]
            if not drives:
                drive_list.append(sg)
        elif not changers:
            changer_list.append(sg)
    for index, dev in enumerate(dict.fromkeys(drive_list)):
        explicit_nst = nst if index == 0 else None
        commands = drive_commands(dev, explicit_nst or mappings.get(dev))
        results = [run("drive-status", dev, argv) for argv in commands]
        status_text = "\n".join(r.stdout for r in results if r.ok)
        # TUR's diagnostics normally go to stderr and success often has no output.
        tur = results[1]
        status = parse_drive_status(status_text + "\n" + tur.stderr, tur.returncode)
        if len(commands) < 3:
            status["warnings"].append("mt status skipped: no non-rewinding device mapping; supply --nst")
        ta = run("tapealert", dev, log_command(dev, "0x2e"))
        page_data = {"pages": [], "preamble": [], "warnings": []}
        for page in COMMON_PAGES:
            result = run("logpages", dev, log_command(dev, page))
            if result.ok:
                parsed = parse_logpages(result.stdout, page)
                for key in page_data:
                    page_data[key].extend(parsed[key])
        report["drives"].append({"device": dev, "drive_status": status,
                                 "tapealert": PARSERS["tapealert"](ta.stdout) if ta.ok else None,
                                 "logpages": page_data})
    for dev in dict.fromkeys(changer_list):
        result = run("library", dev, ["mtx", "-f", device_path(dev), "status"])
        report["libraries"].append({"device": dev, "status": PARSERS["library"](result.stdout) if result.ok else None})
    result = run("ltfs", None, ["ltfs", "-o", "device_list"])
    if result.ok:
        report["ltfs"] = PARSERS["ltfs"](result.stdout + "\n" + result.stderr)
    report["commands"] = [result.to_dict() for result in runner.results]
    return report
