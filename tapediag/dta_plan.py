"""A declarative, printable plan shared by real and fake transports."""
from dataclasses import dataclass
import json
import shlex
from urllib.parse import urlencode

from .dta_config import checked, TOKEN


WRITE_OPS = frozenset({"zone.remove", "zone.add", "zone.save", "zone.enable",
                       "library.mount", "library.return", "mover.prepare", "mover.test", "mover.dump", "owner.lock", "owner.unlock"})


@dataclass(frozen=True)
class Request:
    op: str
    target: str
    argv: tuple = ()
    query: tuple = ()
    endpoint: str = ""
    timeout: int = 30

    @property
    def write(self):
        return self.op in WRITE_OPS

    def description(self):
        if self.endpoint:
            query = "progress" if self.op == "library.progress" else urlencode(self.query)
            # These are ENVIRONMENT NAMES, never resolved values.
            return "GET " + self.target + "/gf/" + self.endpoint + ("?" + query if query else "")
        if self.op.startswith("zone.") and self.op in ("zone.remove", "zone.add"):
            command, zone, value = self.argv
            cmd = '{} "{}", "{}"'.format(command, zone, value)
        elif self.op == "zone.enable":
            cmd = 'cfgenable "{}" -f'.format(self.argv[1])
        else:
            cmd = shlex.join(self.argv)
        return "SSH " + self.target + " :: " + cmd

    def public(self):
        return {"op": self.op, "target": self.target, "argv": list(self.argv),
                "endpoint": self.endpoint, "query": [list(x) for x in self.query],
                "write": self.write, "timeout": self.timeout}


@dataclass(frozen=True)
class Step:
    key: str
    purpose: str
    requests: tuple
    rollback: tuple = ()
    before: tuple = ()
    after: tuple = ()
    after_each_write: tuple = ()


def switch_requests(switch, restore=False):
    op, command = ("zone.add", "zoneadd") if restore else ("zone.remove", "zoneremove")
    return tuple(Request(op, switch.ssh, (command, zone, value)) for zone, value in switch.removals) + (
        Request("zone.save", switch.ssh, ("cfgsave", "-f")),
        Request("zone.enable", switch.ssh, ("cfgenable", switch.configuration, "-f")),
    )


def switch_reads(switch):
    return (Request("zone.snapshot", switch.ssh, ("cfgshow",)),
            Request("zone.default", switch.ssh, ("defzone", "--show")),
            Request("zone.transactions", switch.ssh, ("cfgtransshow",)),
            Request("zone.fabric_transactions", switch.ssh, ("cfgtransshow", "--opentrans")))


def library_request(config, op, endpoint, **query):
    return Request(op, config.library["url"], endpoint=endpoint, query=tuple(query.items()))


def inventory_request(config):
    return library_request(config, "library.inventory", "inventory.xml", action="list",
                           partition=config.library["partition"])


def identity_request(config):
    return library_request(config, "library.identity", "driveList.xml", action="list")


def move_requests(config, restore=False):
    lib = config.library
    move = library_request(config, "library.return" if restore else "library.mount", "inventory.xml",
                           action="move", partition=lib["partition"],
                           sourceID="DRIVE" if restore else "SLOT",
                           sourceNumber=str(lib["drive_offset"] if restore else lib["home_slot"]),
                           destinationID="SLOT" if restore else "DRIVE",
                           destinationNumber=str(lib["home_slot"] if restore else lib["drive_offset"]))
    return (move, library_request(config, "library.progress", "inventory.xml", progress=""),
            library_request(config, "library.result", "inventory.xml", action="getMoveResult",
                            partition=lib["partition"]), inventory_request(config))


def mover_request(config, op, *args, timeout=30):
    return Request("mover." + op, config.mover["ssh"], (config.mover["itdt"],) + args, timeout=timeout)


def drive_reads(config):
    return (mover_request(config, "scan", "scan"),
            mover_request(config, "identity", "-f", config.mover["device"], "inqj", "0x83"))


def run_directory(config, run_id):
    checked(run_id, TOKEN, "run ID")
    return config.mover["work_dir"] + "/" + run_id


def build_plan(config, run_id):
    from .dta_owner import owner_request
    remote = run_directory(config, run_id)
    login = library_request(config, "library.login", "login.xml",
                            username="ENV:" + config.library["username_env"],
                            password="ENV:" + config.library["password_env"])
    preflight = (login,) + tuple(r for s in config.switches for r in switch_reads(s)) + (
        mover_request(config, "version", "-version"), identity_request(config)) + drive_reads(config) + (inventory_request(config),)
    media_reads = (identity_request(config),) + drive_reads(config) + (inventory_request(config),)
    owner_reads = (owner_request(config, run_id, "probe"),) if config.owner else ()
    guard = owner_reads + tuple(r for s in config.switches for r in switch_reads(s)) + (
        mover_request(config, "version", "-version"),) + media_reads
    steps = []
    if config.owner:
        steps.append(Step("owner.lock", "STEP 0: lock owner drive/device using reviewed config adapter; prove this run owns lock and idle/no mounts",
                          (owner_request(config, run_id, "lock"),),
                          rollback=(owner_request(config, run_id, "unlock"),),
                          before=(login, mover_request(config, "version", "-version"), identity_request(config)) + drive_reads(config) + owner_reads,
                          after=owner_reads))
        preflight = owner_reads + preflight[1:]  # login is printed before the owner-lock prechecks
    steps.append(Step("preflight", "Verify exact version, serial/WWPN, library mapping, home TEST cartridge, empty drive; snapshot every fabric", preflight))
    for switch in config.switches:
        steps.append(Step("isolate." + switch.name,
                          "Recheck baseline and no other zoning transaction; remove all production references and verify isolation",
                          switch_requests(switch), switch_requests(switch, True),
                          before=owner_reads + switch_reads(switch), after=switch_reads(switch),
                          after_each_write=(switch_reads(switch)[0],)))
    steps.append(Step("prepare", "Create a new private remote run directory (refuse reuse)", (
        Request("mover.prepare", config.mover["ssh"],
                ("mkdir", "-m", "700", remote, remote + "/logs", remote + "/results")),)))
    steps.append(Step("mount", "Verify isolation, serial, home barcode and empty drive; move only TEST cartridge and poll to completion",
                      move_requests(config), move_requests(config, True), before=guard))
    steps.append(Step("erase_guard", "Fresh checks: every configured port isolated, no unknown zones; loaded barcode exactly TEST; serial/path/WWPN match", guard))
    common = ("-LP", remote + "/logs", "-R", remote + "/results", "-f", config.mover["device"])
    steps.append(Step("diagnostic", "Repeat erase guard immediately; DESTRUCTIVE IBM ITDT SE standardtest on the configured TEST cartridge only", (
        mover_request(config, "test", *common, "standardtest", "-forcedataoverwrite", timeout=config.mover["timeout_seconds"]),), before=guard))
    steps.append(Step("dump", "Recheck identity/isolation/barcode; force and collect vendor drive dumps; no health verdict inferred", (
        mover_request(config, "dump", *common, "dump", timeout=600),), before=guard))
    steps.append(Step("collect", "Fetch only this run's logs/results; reject links/traversal/devices/oversize tar members", (
        Request("mover.collect", config.mover["ssh"], ("tar", "-cf", "-", "-C", remote, "logs", "results"), timeout=120),)))
    steps.append(Step("return", "Recheck serial, isolation and loaded TEST barcode; return it to the configured, empty home slot", move_requests(config, True), before=guard))
    for switch in config.switches:
        steps.append(Step("restore." + switch.name, "Compare isolated snapshot; restore original members and active configuration; verify exact baseline",
                          switch_requests(switch, True), before=owner_reads + media_reads + switch_reads(switch), after=switch_reads(switch),
                          after_each_write=(switch_reads(switch)[0],)))
    steps.append(Step("verify", "Verify every fabric equals baseline; TEST cartridge home, drive empty/OK and same serial visible; application acceptance remains operator-owned", guard))
    if config.owner:
        steps.append(Step("owner.unlock", "Reverify restored state; unlock only this run's ownership; verify visible/usable through adapter. On diagnostic/evidence failure HOLD lock for operator review",
                          (owner_request(config, run_id, "unlock"),), before=guard, after=owner_reads))
    steps.extend((
                  Step("logout", "Close the XML session (credentials/cookies never persisted)", (
                      library_request(config, "library.logout", "logout.xml"),)),
                  Step("bundle", "Write local support-ticket.txt, manifest with SHA256 and attachment bundle; no upload/send", ())))
    return tuple(steps)


def render_plan(config, run_id, steps=None):
    steps = build_plan(config, run_id) if steps is None else steps
    lines = ["DTA PLAN v1 — no remote action without --apply and a typed serial",
             "Run: " + run_id, "Drive: " + config.serial + "; designated TEST barcode: " + config.barcode,
             "Physical manufacturer serial: " + config.manufacturer_serial,
             "Config SHA256: " + config.fingerprint,
             "Prerequisite: exclusive maintenance ownership, every fabric/drive port configured, no other zone/library writers.",
             "ROLLBACK COMMANDS — review BEFORE any apply; never execute blindly against changed state:",
             "  Recovery order: prove remote tests stopped -> return TEST media home -> restore fabrics in reverse order -> verify -> unlock owner if configured."]
    rollback_steps = ([s for s in steps if s.key == "mount"] +
                      list(reversed([s for s in steps if s.key.startswith("isolate.")])) +
                      [s for s in steps if s.key == "owner.lock"])
    for step in rollback_steps:
        if step.rollback:
            lines.append("  Rollback for " + step.key + ":")
            for request in step.rollback:
                lines.append("    " + request.description())
    lines.append("FORWARD PLAN:")
    for i, step in enumerate(steps, 0 if config.owner else 1):
        lines.append("{:02d} [{}] {}".format(i, step.key, step.purpose))
        for request in step.before:
            lines.append("  BEFORE READ " + request.description())
        for request in step.requests:
            lines.append("  WOULD {} {}".format("WRITE" if request.write else "READ", request.description()))
            if request.write:
                for observation in step.after_each_write:
                    lines.append("  THEN READ " + observation.description() + " (must equal exact intermediate expected state)")
        for request in step.after:
            lines.append("  AFTER READ " + request.description())
        if step.key.startswith(("isolate.", "restore.")) or step.key in ("mount", "return", "dump", "diagnostic"):
            lines.append("  Re-read required evidence before mutation; audit durable intent before dispatch; stop on drift/ambiguity.")
    lines.extend(("Polling: inventory.xml?progress (empty parameter); QUEUE/SUBMITTED/ACTIVE repeat at 2s, at most 300 responses.",
                  "Resume: --resume revalidates completed checkpoints; an uncertain write is NEVER replayed automatically.",
                  "Restoration proves configured zoning/library/path state; it does not establish application scheduling or hardware PASS."))
    return "\n".join(lines) + "\n"


def plan_json(config, run_id):
    return {"schema": 1, "mode": "plan", "remote_requests": 0, "hardware_writes": 0,
            "run_id": run_id, "config_sha256": config.fingerprint,
            "steps": [{"key": s.key, "purpose": s.purpose,
                       "requests": [r.public() for r in s.requests],
                       "rollback": [r.public() for r in s.rollback],
                       "before": [r.public() for r in s.before],
                       "after": [r.public() for r in s.after],
                       "after_each_write": [r.public() for r in s.after_each_write]} for s in build_plan(config, run_id)]}
