"""Enumerate cached Linux sysfs attributes; never open a /dev node."""

import re
from pathlib import Path


def inventory_sysfs(root=Path("/sys")) -> dict:
    root = Path(root)
    devices, warnings, seen = [], [], set()
    generic_class = root / "class/scsi_generic"
    tape_class = root / "class/scsi_tape"

    def read(path):
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    def add(device, generic=None, tape=None):
        resolved = device.resolve()
        if str(resolved) in seen:
            return
        pdt = read(device / "type")
        if pdt not in ("1", "8"):
            return
        seen.add(str(resolved))
        if generic is None:
            candidates = sorted((device / "scsi_generic").glob("sg*"))
            generic = next((p.name for p in candidates if re.fullmatch(r"sg\d+", p.name)), None)
        if tape is None:
            candidates = sorted((device / "scsi_tape").glob("st*"))
            tape = next((p.name for p in candidates if re.fullmatch(r"st\d+", p.name)), None)
        address = resolved.name if re.fullmatch(r"\d+:\d+:\d+:\d+", resolved.name) else None
        devices.append({"kind": "drive" if pdt == "1" else "changer", "address": address,
                        "vendor": read(device / "vendor"), "model": read(device / "model"),
                        "revision": read(device / "rev"),
                        "device": "/dev/" + tape if tape else None,
                        "generic_device": "/dev/" + generic if generic else None,
                        "nonrewinding_device": "/dev/n" + tape if tape else None})

    try:
        if generic_class.is_dir():
            for entry in sorted(generic_class.iterdir()):
                if re.fullmatch(r"sg\d+", entry.name):
                    add(entry / "device", generic=entry.name)
        if tape_class.is_dir():
            for entry in sorted(tape_class.iterdir()):
                if re.fullmatch(r"st\d+", entry.name):
                    add(entry / "device", tape=entry.name)
    except (OSError, RuntimeError) as exc:
        warnings.append("sysfs enumeration incomplete: " + str(exc))
    if not generic_class.is_dir() and not tape_class.is_dir():
        warnings.append("neither scsi_generic nor scsi_tape class is present")
    return {"source": "sysfs", "devices": devices, "warnings": warnings}
