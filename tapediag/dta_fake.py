"""Stateful in-memory fake: intentionally incapable of contacting any endpoint."""
import copy
import io
import json
from pathlib import Path
import tarfile

from .dta_config import Refusal
from .dta_transport import Response
from .dta_storage import utcnow
from .dta_vendor import expand, parse_cfgshow


def cfg_text(snapshot):
    lines = []
    for section in ("defined", "effective"):
        lines.append(section.capitalize() + " configuration:")
        for kind in ("cfg", "zone", "alias"):
            for name, values in snapshot[section][kind].items():
                lines.append(kind + ": " + name + (" " + "; ".join(values) if values else ""))
    return "\n".join(lines) + "\n"


class FakeTransport:
    def __init__(self, config, fixture_dir, fault=None):
        self.config, self.fixtures, self.fault = config, Path(fixture_dir), fault
        if config.serial != "SYNTH-DRIVE-DTA" or len(config.switches) != 2:
            raise Refusal("fake transport accepts the shipped synthetic scenario only")
        self.snapshots = {s.ssh: parse_cfgshow((self.fixtures / ("switch-a.txt" if i == 0 else "switch-b.txt")).read_text())
                          for i, s in enumerate(config.switches)}
        self.original = copy.deepcopy(self.snapshots)
        self.loaded, self.prepared, self.authenticated = False, False, False
        self.calls = []
        self.diagnostic_returncode = 0
        self.dump_returncode = 0
        self.collected = False
        self.progress_states = ["ACTIVE", "OK"]
        self.progress = []
        self.last_restore = False
        self.owner_locked = False
        self.owner_token = None

    def text(self, name):
        return (self.fixtures / name).read_text()

    def execute(self, request):
        self.calls.append(request)
        if self.fault:
            result = self.fault(self, request)
            if result is not None:
                return result
        op = request.op
        if op == "owner.probe":
            return Response(0, json.dumps({"schema": 1, "serial": self.config.serial,
                "manufacturer_serial": self.config.manufacturer_serial,
                "drive": self.config.owner["drive"], "device": self.config.owner["device"],
                "locked": self.owner_locked, "lock_owner": self.owner_token,
                "idle": True, "mounts": 0, "usable": True, "observed_at": utcnow()}).encode())
        if op == "owner.lock":
            if self.owner_locked:
                raise Refusal("fake ownership already locked")
            self.owner_locked, self.owner_token = True, request.argv[-1]
            return Response(0, b"")
        if op == "owner.unlock":
            if not self.owner_locked or self.owner_token != request.argv[-1]:
                raise Refusal("fake ownership is not this run's lock")
            self.owner_locked, self.owner_token = False, None
            return Response(0, b"")
        if op == "library.login":
            self.authenticated = True
            return Response(0, b"<login><status>OK</status></login>")
        if op.startswith("library.") and not self.authenticated:
            raise Refusal("fake library session missing")
        if op == "library.logout":
            self.authenticated = False
            return Response(0, b"<logout/>")
        if op.startswith("zone."):
            snapshot = self.snapshots[request.target]
            if op == "zone.snapshot":
                return Response(0, cfg_text(snapshot).encode())
            if op == "zone.default":
                return Response(0, b"Default Zone Access Mode\ncommitted - No Access\ntransaction - No Transaction\n")
            if op == "zone.transactions":
                return Response(0, b"There is no outstanding zone transaction\n")
            if op == "zone.fabric_transactions":
                return Response(0, b"There is no outstanding zone transaction\nTransactions Detect: Capable\nCurrent Open Transactions\nDomain List:\n-------------------------\n")
            if op in ("zone.remove", "zone.add"):
                _, zone, value = request.argv
                values = snapshot["defined"]["zone"][zone]
                if op == "zone.remove":
                    values.remove(value)
                elif value not in values:
                    values.append(value)
                    values.sort()
                return Response(0, b"")
            if op == "zone.save":
                return Response(0, b"")
            if op == "zone.enable":
                cfg = request.argv[1]
                snapshot["effective"]["cfg"] = {cfg: []}
                snapshot["effective"]["zone"] = {
                    name: sorted(expand(snapshot["defined"]["zone"][name], snapshot["defined"]["alias"]))
                    for name in snapshot["defined"]["cfg"][cfg]}
                return Response(0, b"")
        if op == "library.identity":
            return Response(0, self.text("drive-list.xml").encode())
        if op == "library.inventory":
            return Response(0, self.text("inventory-loaded.xml" if self.loaded else "inventory-home.xml").encode())
        if op in ("library.mount", "library.return"):
            params = dict(request.query)
            restore = op == "library.return"
            expected = {"action": "move", "partition": "SYNTH TEST", "sourceID": "DRIVE" if restore else "SLOT",
                        "sourceNumber": "1" if restore else "7", "destinationID": "SLOT" if restore else "DRIVE",
                        "destinationNumber": "7" if restore else "1"}
            if params != expected or self.loaded != restore:
                raise Refusal("invalid synthetic move")
            self.loaded = not restore
            self.last_restore = restore
            self.progress = list(self.progress_states)
            return Response(0, b"<inventory><status>OK</status><message>Started move</message></inventory>")
        if op == "library.progress":
            status = self.progress.pop(0) if self.progress else "OK"
            return Response(0, ("<progress><activePage>inventory.xml</activePage><status>" + status + "</status></progress>").encode())
        if op == "library.result":
            route = "Drive 1 to Slot 7" if self.last_restore else "Slot 7 to Drive 1"
            return Response(0, ("<inventory><moveResult>Move barcode SYNTH-TEST-L9 from " + route + " Successful</moveResult></inventory>").encode())
        if op == "mover.version":
            return Response(0, b"IBM Tape Diagnostic Tool Standard Edition - Version: 9.6.2\n")
        if op == "mover.scan":
            return Response(0, self.text("itdt-scan.txt").encode())
        if op == "mover.identity":
            return Response(0, self.text("itdt-inquiry.json").encode())
        if op == "mover.prepare":
            if self.prepared:
                return Response(1, b"", b"synthetic directory exists")
            self.prepared = True
            return Response(0, b"")
        if op in ("mover.test", "mover.dump"):
            if not self.prepared or not self.loaded:
                raise Refusal("fake requires a new private run and loaded test cartridge")
            code = self.diagnostic_returncode if op == "mover.test" else self.dump_returncode
            return Response(code, ("SYNTHETIC test process; no hardware used.\nExit with code: " + str(code) + "\n").encode())
        if op == "mover.collect":
            self.collected = True
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode="w") as archive:
                files = {"logs/metro.log": b"SYNTHETIC dedicated run log only\n",
                         "results/SYNTH-DRIVE-DTA.a.gz": b"SYNTHETIC placeholder; NOT a vendor binary dump\n",
                         "results/SYNTH-DRIVE-DTA.standardtest.json": json.dumps({"synthetic": True, "hardware_verdict": "unknown"}).encode()}
                for name, data in files.items():
                    item = tarfile.TarInfo(name)
                    item.size = len(data)
                    archive.addfile(item, io.BytesIO(data))
            return Response(0, output.getvalue())
        raise Refusal("unsupported fake request")
