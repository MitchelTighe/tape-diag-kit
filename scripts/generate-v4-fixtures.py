"""Reproduce original synthetic v4 examples; no hardware or upstream data."""

import copy
import json
from pathlib import Path

from tapediag.tapealert import parse_tapealert
from tapediag.v3 import refresh

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures/v4"


def parameter(code, value, length):
    return code.to_bytes(2, "big") + bytes((0, length)) + value.to_bytes(length, "big")


def page(code, parameters):
    payload = b"".join(parameters)
    return (bytes((code, 0)) + len(payload).to_bytes(2, "big") + payload).hex(" ")


def main():
    OUT.mkdir(exist_ok=True)
    snapshots = []
    for day, total, errors, active in [(16, 1024, 0, False), (17, 4096, 2, True),
                                       (18, 8192, 5, True), (19, 12, 0, False)]:
        captures = {
            "2e": page(0x2e, [parameter(flag, int(active and flag == 20), 1) for flag in range(1, 65)]),
            "0c": page(0x0c, [parameter(0, total, 8), parameter(1, total // 2, 8),
                              parameter(0x100, int(active), 1)]),
            "17": page(0x17, [parameter(0, 1, 1), parameter(4, errors, 8),
                              parameter(9, errors, 8), parameter(0x16, 2400000, 8),
                              parameter(0x17, total, 8)]),
            "31": page(0x31, [parameter(1, 2000000 - total, 4), parameter(2, 0, 4),
                              parameter(3, 2000000, 4), parameter(4, 0, 4)]),
        }
        if day == 16:
            for code, text in captures.items():
                (OUT / ("log-" + code + ".txt")).write_text("# Original synthetic page; see docs/log-trends.md\n" + text + "\n")
        snapshots.append({"captured_at": "2026-10-%dT00:00:00Z" % day,
                          "medium_id": "SYNTH-MEDIUM-A" if day < 19 else "SYNTH-MEDIUM-B",
                          "pages": [{"hex": text, "profile": "lto5-6-capacity" if code == "31" else "ssc"}
                                    for code, text in captures.items()]})
    (OUT / "log-series.json").write_text(json.dumps({
        "format": "tapediag-log-series-v1", "asset_id": "SYNTH-DRIVE-V4",
        "page_control": "current-cumulative", "snapshots": snapshots}, indent=2) + "\n")
    source = json.loads((ROOT / "fixtures/fleets/synth-alpha-20261016.json").read_text())
    for day, flags in [(16, "Flag 20: 0\nFlag 21: 0"), (17, "Flag 20: 1\nFlag 21: 0"),
                       (18, "Flag 21: 0"), (19, "Flag 20: 0\nFlag 21: 0")]:
        report = copy.deepcopy(source)
        report["captured_at"] = "2026-10-%dT00:00:00Z" % day
        report["fleet_id"] = "SYNTH-V4"
        report["drives"] = report["drives"][:1]
        report["libraries"] = []
        report["drives"][0]["tapealert"] = parse_tapealert(flags)
        report["drives"][0]["tapealert_response"] = None
        refresh(report)
        (OUT / ("alerts-%d.json" % day)).write_text(json.dumps(report, indent=2) + "\n")
    before = """Storage Changer /dev/sg40:1 Drives, 3 Slots ( 1 Import/Export )
Data Transfer Element 0:Empty
Storage Element 1:Full :VolumeTag=SYNTH-V4-A
Storage Element 2:Full :VolumeTag=SYNTH-V4-B
Storage Element 3 IMPORT/EXPORT:Empty
"""
    after = """Storage Changer /dev/sg40:1 Drives, 3 Slots ( 1 Import/Export )
Data Transfer Element 0:Full (Storage Element 1 Loaded):VolumeTag=SYNTH-V4-A
Storage Element 1:Empty
Storage Element 2:Full :VolumeTag=SYNTH-V4-B
Storage Element 3 IMPORT/EXPORT:Empty
"""
    (OUT / "inventory-before.txt").write_text(before)
    (OUT / "inventory-after.txt").write_text(after)
    (OUT / "explain-codes.txt").write_text(
        "# Original lookup examples, not a hardware capture\n"
        "tapealert:20\nsense:2/3a/00\nasc:29/00\npage:0x31\ndensity:0x5e\nasc:ff/ff\n")
    print("v4 synthetic examples generated")


if __name__ == "__main__":
    main()
