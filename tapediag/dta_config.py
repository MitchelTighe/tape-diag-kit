"""Strict, declarative DTA configuration. Credentials are referenced by name only."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import urlsplit


class Refusal(ValueError):
    """Missing, ambiguous or unsafe evidence; no speculative fallback is allowed."""


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refusal("duplicate JSON field refused")
        result[key] = value
    return result


NAME = r"[A-Za-z][A-Za-z0-9_]{0,63}"
TOKEN = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}"
WWPN = r"(?:[0-9a-fA-F]{2}:){7}[0-9a-fA-F]{2}"
PORT = r"[1-9][0-9]{0,2},[0-9]{1,3}"
DEVICE = r"/dev/(?:sg[0-9]+|IBMtape[0-9]+n)"


def checked(value, pattern, label):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise Refusal("invalid " + label)
    return value


def fields(obj, required, optional=()):
    if not isinstance(obj, dict) or set(obj) - set(required) - set(optional) or set(required) - set(obj):
        raise Refusal("configuration keys do not match schema: " + ", ".join(required))


def absolute_path(value, label):
    checked(value, r"/[A-Za-z0-9_./-]+", label)
    p = PurePosixPath(value)
    if ".." in p.parts or str(p) != value or value in ("/", "/tmp", "/var/tmp"):
        raise Refusal("unsafe " + label)
    return value


def member(value):
    checked(value, "(?:" + NAME + "|" + WWPN + "|" + PORT + ")", "zone member")
    return value.lower() if re.fullmatch(WWPN, value) else value


@dataclass(frozen=True)
class Switch:
    name: str
    ssh: str
    fabric: str
    configuration: str
    removals: tuple
    diagnostic_zones: tuple
    ports: tuple


@dataclass(frozen=True)
class Config:
    serial: str
    manufacturer_serial: str
    barcode: str
    wwpns: tuple
    switches: tuple
    library: dict
    mover: dict
    owner: object = None

    def canonical(self):
        return {"serial": self.serial, "manufacturer_serial": self.manufacturer_serial,
                "barcode": self.barcode, "wwpns": self.wwpns,
                "switches": [vars(s) for s in self.switches],
                "library": self.library, "mover": self.mover, "owner": self.owner}

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.canonical(), sort_keys=True).encode()).hexdigest()


def parse_config(data):
    fields(data, ("schema", "drive", "switches", "library", "mover"), ("owner",))
    if type(data["schema"]) is not int or data["schema"] != 1:
        raise Refusal("unsupported configuration schema")
    drive = data["drive"]
    fields(drive, ("serial", "manufacturer_serial", "test_barcode", "wwpns"))
    serial = checked(drive["serial"], TOKEN, "drive serial")
    physical = checked(drive["manufacturer_serial"], TOKEN, "physical manufacturer serial")
    barcode = checked(drive["test_barcode"], TOKEN, "test barcode")
    if any(value.upper() in ("UNKNOWN", "UNAVAILABLE", "NONE", "NULL", "NA", "NO_BARCODE", "NOBARCODE")
           for value in (serial, physical, barcode)):
        raise Refusal("unknown/unavailable identity cannot authorize a test")
    if not isinstance(drive["wwpns"], list) or not drive["wwpns"]:
        raise Refusal("configure every drive port WWPN")
    wwpns = tuple(checked(w, WWPN, "WWPN").lower() for w in drive["wwpns"])
    if len(set(wwpns)) != len(wwpns):
        raise Refusal("duplicate drive WWPN")
    switches = []
    if not isinstance(data["switches"], list) or not data["switches"]:
        raise Refusal("at least one switch/fabric is required")
    for s in data["switches"]:
        fields(s, ("name", "ssh", "fabric", "configuration", "removals", "diagnostic_zones", "ports"))
        for k in ("name", "ssh", "fabric", "configuration"):
            checked(s[k], NAME, "switch " + k)
        removals = []
        if not isinstance(s["removals"], list) or not s["removals"]:
            raise Refusal("explicit zone/member removals are required on every fabric")
        for removal in s["removals"]:
            fields(removal, ("zone", "member"))
            removals.append((checked(removal["zone"], NAME, "zone"), member(removal["member"])))
        if len(set(removals)) != len(removals):
            raise Refusal("duplicate zone/member removal")
        if not isinstance(s["diagnostic_zones"], list) or not isinstance(s["ports"], list):
            raise Refusal("diagnostic_zones and ports must be lists")
        zones = tuple(checked(z, NAME, "diagnostic zone") for z in s["diagnostic_zones"])
        ports = tuple(checked(p, PORT, "domain,port index") for p in s["ports"])
        if not zones or len(set(zones)) != len(zones) or len(set(ports)) != len(ports):
            raise Refusal("unique diagnostic zones and ports required")
        if set(zones) & {z for z, _ in removals}:
            raise Refusal("a diagnostic zone cannot be removed")
        switches.append(Switch(s["name"], s["ssh"], s["fabric"], s["configuration"],
                               tuple(removals), zones, ports))
    for k in ("name", "ssh", "fabric"):
        if len({getattr(s, k) for s in switches}) != len(switches):
            raise Refusal("configure one unique representative switch per fabric; duplicate " + k)
    fields(data["library"], ("url", "partition", "drive_id", "drive_offset", "home_slot", "username_env", "password_env"))
    lib = dict(data["library"])
    if not isinstance(lib["url"], str) or any(ord(c) < 33 or ord(c) > 126 for c in lib["url"]):
        raise Refusal("library URL must be a printable ASCII HTTPS origin")
    try:
        parsed = urlsplit(lib["url"])
        port = parsed.port
    except ValueError:
        raise Refusal("invalid library HTTPS origin") from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or port == 0 or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise Refusal("library URL must be an HTTPS origin without credentials")
    lib["url"] = lib["url"].rstrip("/")
    checked(lib["partition"], r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}", "partition")
    checked(lib["drive_id"], r"(?:FR[0-9]+/)?(?:DBA[0-9]+/)?[A-Za-z0-9_-]+", "library drive ID")
    for k in ("drive_offset", "home_slot"):
        if type(lib[k]) is not int or not 0 <= lib[k] <= 1000000:
            raise Refusal("invalid library " + k)
    for k in ("username_env", "password_env"):
        checked(lib[k], r"[A-Z][A-Z0-9_]{0,63}", "credential environment NAME")
    fields(data["mover"], ("ssh", "itdt", "version", "device", "work_dir", "timeout_seconds"))
    mover = dict(data["mover"])
    checked(mover["ssh"], NAME, "mover SSH alias")
    absolute_path(mover["itdt"], "ITDT executable")
    absolute_path(mover["work_dir"], "remote work directory")
    checked(mover["device"], DEVICE, "non-rewinding tape/generic device")
    checked(mover["version"], r"9\.[0-9]+\.[0-9]+(?:\.[0-9]+)?", "pinned ITDT SE 9.x version")
    if type(mover["timeout_seconds"]) is not int or not 60 <= mover["timeout_seconds"] <= 14400:
        raise Refusal("ITDT timeout must be 60..14400 seconds")
    owner = None
    if "owner" in data:
        fields(data["owner"], ("ssh", "drive", "device", "lock_argv", "unlock_argv", "verify_argv"))
        owner = dict(data["owner"])
        checked(owner["ssh"], NAME, "owner SSH alias")
        for key in ("drive", "device"):
            checked(owner[key], TOKEN, "owner resource " + key)
        for key in ("lock_argv", "unlock_argv", "verify_argv"):
            argv = owner[key]
            if not isinstance(argv, list) or not 2 <= len(argv) <= 32 or not all(isinstance(v, str) for v in argv):
                raise Refusal("owner command template must be an argv list")
            absolute_path(argv[0], "owner adapter executable")
            joined = " ".join(argv)
            if "{run_id}" not in joined or "{serial}" not in joined:
                raise Refusal("owner templates must bind exact serial and run ownership token")
            for value in argv:
                checked(value, r"[A-Za-z0-9_./,:={}+-]{1,256}", "owner argv template token")
                for placeholder in re.findall(r"\{[^}]*\}", value):
                    if placeholder not in ("{serial}", "{manufacturer_serial}", "{drive}", "{device}", "{run_id}"):
                        raise Refusal("unsupported owner template placeholder")
                if re.search(r"[{}]", re.sub(r"\{(?:serial|manufacturer_serial|drive|device|run_id)\}", "", value)):
                    raise Refusal("unbalanced owner template placeholder")
    return Config(serial, physical, barcode, wwpns, tuple(switches), lib, mover, owner)


def load_config(path):
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError as exc:
            raise Refusal("TOML needs Python 3.11+ or optional pinned dta dependency tomli==2.3.0") from exc
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise Refusal("configuration must be a regular file")
            raw = handle.read(65537)
        if len(raw) > 65536:
            raise Refusal("configuration exceeds 64 KiB")
        return parse_config(tomllib.loads(raw.decode("utf-8")))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, Refusal):
            raise
        raise Refusal("cannot load valid DTA TOML configuration (contents withheld)") from None
