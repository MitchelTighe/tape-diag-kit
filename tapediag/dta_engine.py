"""Plan-first state machine. Acknowledged failures restore; uncertain writes stop.

Completed checkpoints are resumable. A pending mutating request survives every
exception and process interruption until the entire step has been verified.
"""
import copy
import hashlib
import json
import time

from .dta_config import Refusal
from .dta_owner import owner_request, parse_owner
from .dta_plan import (build_plan, drive_reads, identity_request, inventory_request,
                       library_request, move_requests, plan_json, render_plan, switch_reads)
from .dta_storage import canonical, extract_collection, make_bundle
from .dta_transport import Uncertain
from .dta_vendor import (find_drive, isolated_snapshot, isolation, library_identity,
                         no_access, no_fabric_transactions, no_transactions, one, parse_cfgshow,
                         parse_inquiry, parse_inventory, parse_move_result, parse_progress, parse_test, parse_version,
                         validate_zoning, xml_root, xml_status)


class Engine:
    def __init__(self, config, run_id, transport, authorization, store=None, emit=print,
                 sleep=time.sleep, after_step=None):
        self.config, self.run_id, self.transport = config, run_id, transport
        self.authorization, self.store, self.emit = authorization, store, emit
        self.sleep, self.after_step = sleep, after_step
        self.steps = build_plan(config, run_id)
        self.current = None
        self.state = None

    def dry_run(self):
        transcript = render_plan(self.config, self.run_id, self.steps)
        self.emit(transcript.rstrip())
        # No transport, auth, state or secret access, even with injected transports.
        return transcript

    def _event(self, name, **details):
        self.store.event(name, step=self.current, **details)

    def _save(self):
        self.store.save()

    def planned(self, op):
        return next(r for s in self.steps for r in s.before + s.requests + s.after if r.op == op)

    def owner_probe(self, locked=True):
        if not self.config.owner:
            return None
        request = owner_request(self.config, self.run_id, "probe")
        result = parse_owner(self.call(request).text, self.config, self.run_id, locked)
        self._event("owner.verified", observation=result)
        return result

    def call(self, request, allow_nonzero=False):
        self.authorization.require(self.config)
        self.emit("{} {}".format("WRITE" if request.write else "READ", request.description()))
        self._event("request.intent", request=request.public())
        if request.write:
            self.state["pending"] = {"step": self.current, "request": request.public(), "acknowledged": False}
            self._save()  # audit + write intent durable before dispatch
        response = self.transport.execute(request)
        self._event("request.result", op=request.op, **response.summary())
        if request.write:
            self.state["pending"]["acknowledged"] = True
            self._save()
        if response.returncode and not allow_nonzero:
            raise Refusal("remote command returned nonzero: " + request.op + "; response withheld")
        if response.stderr and request.op.startswith("zone."):
            raise Refusal("unexpected switch stderr; refusing ambiguous switch output")
        if request.op in ("zone.remove", "zone.add", "zone.save", "zone.enable"):
            text = response.text
            # FOS sometimes reports command errors with process returncode zero.
            # Successful blank output is allowed only with post-state verification.
            if any(word in text.lower() for word in (
                    "error", "failed", "not exist", "not found", "invalid", "denied", "abort", "busy",
                    "not allowed", "do you want", "(yes", "[no]", "cannot", "unable")):
                raise Refusal("switch command output indicates failure/prompt; details withheld")
        return response

    def _initialize(self, resume):
        shape = plan_json(self.config, self.run_id)
        plan_hash = hashlib.sha256(canonical(shape)).hexdigest()
        if resume:
            state = self.store.state
            if (not isinstance(state, dict) or state.get("schema") != 1 or state.get("mode") != "apply"
                    or state.get("config_sha256") != self.config.fingerprint
                    or state.get("plan_sha256") != plan_hash or state.get("run_id") != self.run_id):
                raise Refusal("resume requires the original config, plan, run ID and apply checkpoint")
            keys = [step.key for step in self.steps]
            completed = state.get("completed")
            if not isinstance(completed, list) or completed != keys[:len(completed)]:
                raise Refusal("checkpoint steps are not a valid completed prefix")
            if not all(isinstance(state.get(key), dict) for key in ("baseline", "results")):
                raise Refusal("invalid checkpoint baseline/results")
            if not isinstance(state.get("failures"), list) or not isinstance(state.get("evidence"), list):
                raise Refusal("invalid checkpoint evidence/failures")
            for name in state["evidence"]:
                if not isinstance(name, str) or "/" in name or "\\" in name or not name.startswith(("vendor-", "capture-")):
                    raise Refusal("unsafe checkpoint evidence filename")
            if state.get("pending"):
                self._event("resume.refused", reason="uncertain mutating step; manual reconciliation required")
                raise Refusal("pending mutating request: do not replay; verify remote process/robot/transaction state and use saved rollback plan under exclusive maintenance ownership")
            if "preflight" in completed and set(state["baseline"]) != {s.name for s in self.config.switches}:
                raise Refusal("checkpoint is missing a fabric baseline")
            self.state = state
            self._event("resume.begin", completed=completed)
        else:
            self.state = {"schema": 1, "mode": "apply", "run_id": self.run_id,
                          "config_sha256": self.config.fingerprint, "plan_sha256": plan_hash,
                          "completed": [], "baseline": {}, "results": {}, "pending": None,
                          "failures": [], "evidence": [], "restoration_verified": False, "owner_verified": False}
            self.store.state = self.state
            self._event("workflow.begin", config_sha256=self.config.fingerprint, plan_sha256=plan_hash)
            self.store.write("plan.txt", render_plan(self.config, self.run_id))
            self.store.write("plan.json", json.dumps(shape, indent=2) + "\n")
        self._save()

    def _capture(self, name, response):
        filename = "capture-" + name + ".txt"
        self.store.write(filename, response.stdout)
        if filename not in self.state["evidence"]:
            self.state["evidence"].append(filename)

    def switch_snapshot(self, switch):
        snapshot, default, transactions, fabric_transactions = [self.call(r).text for r in switch_reads(switch)]
        no_access(default)
        no_transactions(transactions)
        no_fabric_transactions(fabric_transactions)
        return validate_zoning(parse_cfgshow(snapshot), switch)

    def identity(self):
        library_identity(self.call(identity_request(self.config)).text, self.config)
        scan, inquiry = [self.call(r) for r in drive_reads(self.config)]
        find_drive(scan.text, self.config.serial, self.config.mover["device"])
        parse_inquiry(inquiry.text, self.config.serial, self.config.wwpns)
        return scan, inquiry

    def inventory(self):
        return parse_inventory(self.call(inventory_request(self.config)).text, self.config.library["partition"])

    def media(self, loaded):
        inv = self.inventory()
        lib = self.config.library
        try:
            drive, home = inv["drive"][lib["drive_offset"]], inv["storageSlot"][lib["home_slot"]]
        except KeyError:
            raise Refusal("configured drive/home offset missing from library inventory") from None
        if loaded:
            if not drive["full"] or drive["barcode"] != self.config.barcode or home["full"]:
                raise Refusal("erase/move guard: loaded barcode must equal configured TEST and home must be empty")
            # A source offset, if exposed by firmware, must agree with home.
            if drive["sourceOffset"] not in (None, str(lib["home_slot"])):
                raise Refusal("loaded cartridge source offset differs from configured home")
        elif drive["full"] or not home["full"] or home["barcode"] != self.config.barcode:
            raise Refusal("move guard: drive must be empty and exact TEST barcode at its configured home")
        return inv

    def compare_switch(self, switch, isolated):
        expected = self.state["baseline"][switch.name]
        if isolated:
            expected = isolated_snapshot(expected, self.config, switch)
        observed = self.switch_snapshot(switch)
        if observed != expected:
            raise Refusal("fabric state drift: " + switch.name + "; refusing to modify or test")
        if isolated:
            isolation(observed, self.config, switch)

    def erase_guard(self):
        self.owner_probe()
        for switch in self.config.switches:
            self.compare_switch(switch, True)
        version = self.planned("mover.version")
        parse_version(self.call(version).text, self.config.mover["version"])
        self.identity()
        self.media(True)
        self._event("guard.passed", serial=self.config.serial, barcode=self.config.barcode,
                    check="fresh library media + ITDT page83 identity + all defined/effective production zones absent")
        self.emit("GUARD PASS: exact TEST barcode, serial/path/WWPN and all configured fabric identities isolated")

    def version(self):
        request = self.planned("mover.version")
        return parse_version(self.call(request).text, self.config.mover["version"])

    def _login(self):
        login = self.planned("library.login")
        xml_status(self.call(login).text, "login")

    def _preflight(self):
        self.owner_probe()
        for switch in self.config.switches:
            snapshot = self.switch_snapshot(switch)
            isolated_snapshot(snapshot, self.config, switch)
            self.state["baseline"][switch.name] = snapshot
        version = self.planned("mover.version")
        response = self.call(version)
        parse_version(response.text, self.config.mover["version"])
        self._capture("version", response)
        scan, inquiry = self.identity()
        self._capture("initial-scan", scan)
        self._capture("initial-inquiry", inquiry)
        self.media(False)

    def _zoning(self, step, restore):
        name = step.key.split(".", 1)[1]
        switch = next(s for s in self.config.switches if s.name == name)
        self.owner_probe()
        # Restoration must not expose the diagnostic cartridge to production.
        if restore:
            self.identity()
            self.media(False)
        self.compare_switch(switch, restore)
        original = self.state["baseline"][switch.name]
        isolated = isolated_snapshot(original, self.config, switch)
        expected = copy.deepcopy(isolated if restore else original)
        target = original if restore else isolated
        for request in step.requests:
            self.call(request)
            if request.op in ("zone.remove", "zone.add"):
                _, zone, value = request.argv
                values = expected["defined"]["zone"][zone]
                if restore:
                    values.append(value)
                    values.sort()
                else:
                    values.remove(value)
            elif request.op == "zone.enable":
                expected["effective"] = copy.deepcopy(target["effective"])
            observed = parse_cfgshow(self.call(switch_reads(switch)[0]).text)
            if observed != expected:
                raise Refusal("intermediate zoning drift; refusing the next save/enable or workflow write")
        self.compare_switch(switch, not restore)

    def _move(self, restore):
        self.owner_probe()
        for switch in self.config.switches:
            self.compare_switch(switch, True)
        self.version()
        self.identity()
        self.media(restore)
        requests = move_requests(self.config, restore)
        xml_status(self.call(requests[0]).text, "inventory")
        for attempt in range(300):
            progress = parse_progress(self.call(requests[1]).text, expected_page="inventory.xml")
            if progress == "FAILED":
                raise Refusal("library media move failed; inventory reconciliation required")
            if progress == "OK":
                break
            self.sleep(2)
        else:
            raise Uncertain("library progress timed out; move may still be active")
        result = parse_move_result(self.call(requests[2]).text, self.config, restore)
        self._event("library.move_result", route=result)
        self.media(not restore)

    def _diagnostic(self, step):
        self.erase_guard()  # never trust a saved erase_guard checkpoint
        response = self.call(step.requests[0], allow_nonzero=True)
        self._capture(step.key, response)
        result = parse_test(response.text, response.returncode)
        self.state["results"][step.key] = result
        if not result["command_success"]:
            self.state["failures"].append(step.key + ": command failed or result grammar unknown; review native outputs")

    def _collect(self, step):
        response = self.call(step.requests[0], allow_nonzero=True)
        if response.returncode:
            self.state["failures"].append("collect: remote archive command failed; remote evidence retained")
            return
        try:
            files = extract_collection(response.stdout, self.config.serial)
        except Refusal:
            self.state["failures"].append("collect: unsafe/missing vendor archive evidence refused; remote evidence retained")
            return
        for name, data in files.items():
            self.store.write(name, data)
            if name not in self.state["evidence"]:
                self.state["evidence"].append(name)

    def _verify(self):
        self.owner_probe()
        for switch in self.config.switches:
            self.compare_switch(switch, False)
        self.version()
        scan, inquiry = self.identity()
        self._capture("final-scan", scan)
        self._capture("final-inquiry", inquiry)
        self.media(False)
        self.state["restoration_verified"] = True
        self.emit("RESTORATION VERIFIED: configured zoning baseline, cartridge home, drive empty/OK, exact serial/path/WWPN visible")
        self.emit("OPERATOR FOLLOW-UP: verify application scheduling and production acceptance; hardware verdict remains UNKNOWN")

    def _owner_lock(self, step):
        self.version()
        self.identity()
        initial = self.owner_probe(False)
        if not initial["idle"] or initial["mounts"] != 0:
            raise Refusal("owner must be idle with no active/pending mounts before locking")
        self.call(step.requests[0])
        self.owner_probe(True)

    def _owner_unlock(self, step):
        self._verify()
        if self.state["failures"]:
            self.state["failures"].append("owner: lock retained after diagnostic/evidence failure; operator review and manual release required")
            self._event("owner.held", reason="diagnostic/evidence failure")
            self.emit("OWNER LOCK HELD: review diagnostic/evidence failures before any manual release")
            return
        self.call(step.requests[0])
        self.owner_probe(False)
        self.state["owner_verified"] = True
        self.emit("OWNER VERIFIED: this run released its lock; configured adapter proves exact drive/device visible and usable")

    def apply(self, resume=False):
        self.authorization.require(self.config)
        if self.store is None:
            raise Refusal("apply requires a private audit/checkpoint directory")
        self._initialize(resume)
        self.store.state = self.state
        if len(self.state["completed"]) == len(self.steps):
            self.emit("All steps already completed; no remote writes repeated. Regenerating local bundle only.")
            return make_bundle(self.store, self.config)
        self.current = "session"
        try:
            self._login()  # new cookie on resume; never persist authentication material
            if resume and "preflight" in self.state["completed"]:
                # Determine live expected stage, never use checkpoint alone as proof.
                done = set(self.state["completed"])
                released = self.config.owner and "owner.unlock" in done and self.state["owner_verified"]
                self.owner_probe(not released)
                if not released:
                    for switch in self.config.switches:
                        isolated = "isolate." + switch.name in done and "restore." + switch.name not in done
                        self.compare_switch(switch, isolated)
                    self.version()
                    self.identity()
                    self.media("mount" in done and "return" not in done)
            for step in self.steps:
                if step.key in self.state["completed"]:
                    continue
                self.current = step.key
                self.emit("STEP " + step.key + ": " + step.purpose)
                self._event("step.begin")
                if step.key == "owner.lock":
                    self._owner_lock(step)
                elif step.key == "owner.unlock":
                    self._owner_unlock(step)
                elif step.key == "preflight":
                    self._preflight()
                elif step.key.startswith("isolate."):
                    self._zoning(step, False)
                elif step.key.startswith("restore."):
                    self._zoning(step, True)
                elif step.key == "prepare":
                    self.call(step.requests[0])
                elif step.key in ("mount", "return"):
                    self._move(step.key == "return")
                elif step.key == "erase_guard":
                    self.erase_guard()
                elif step.key in ("diagnostic", "dump"):
                    self._diagnostic(step)
                elif step.key == "collect":
                    self._collect(step)
                elif step.key == "verify":
                    self._verify()
                elif step.key == "logout":
                    xml_root(self.call(step.requests[0]).text, "logout")
                elif step.key != "bundle":
                    raise Refusal("unknown plan step")
                self.state["completed"].append(step.key)
                self.state["pending"] = None
                self._event("step.complete")
                self._save()
                if self.after_step:
                    self.after_step(step.key)
            self._event("workflow.remote_complete", restoration_verified=self.state["restoration_verified"],
                        failures=self.state["failures"], bundle="local archive includes audit through this event")
            self._save()
            return make_bundle(self.store, self.config)
        except BaseException as exc:
            # Do not issue automatic remote cleanup after uncertainty: an SSH
            # timeout does not prove the remote test process has stopped.
            self._event("workflow.halted", exception=type(exc).__name__,
                        pending_write=bool(self.state["pending"]),
                        instruction="keep exclusive ownership; review saved rollback and reconcile remote state")
            self._save()
            self.emit("HALTED: checkpoint/audit retained; do not blindly replay pending writes or expose test media to production")
            try:
                make_bundle(self.store, self.config)
                self.emit("PARTIAL LOCAL BUNDLE: support-ticket.txt and attachments.zip; inspect pending state and restoration status")
            except (OSError, Refusal):
                self.emit("Partial packaging unavailable; preserve the run directory and audit for manual recovery")
            raise
