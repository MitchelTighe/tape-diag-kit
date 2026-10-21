"""Private, locked local checkpoints, chained JSONL audit and curated bundles."""
from contextlib import AbstractContextManager
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import zipfile

from .dta_config import Refusal, unique_json_object


MAX_FILE = 16 * 1024 * 1024
MAX_ARCHIVE = 64 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def read_regular(path, limit=MAX_FILE):
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise Refusal("expected a regular local evidence file")
            data = handle.read(limit + 1)
    except OSError:
        raise Refusal("cannot read regular local evidence file") from None
    if len(data) > limit:
        raise Refusal("local evidence file exceeds size limit")
    return data


class Store(AbstractContextManager):
    def __init__(self, directory, resume=False):
        self.path = Path(directory).absolute()
        if self.path.is_symlink() or any(p.is_symlink() for p in self.path.parents):
            raise Refusal("run directory and parents cannot be symlinks")
        if not resume:
            try:
                self.path.mkdir(mode=0o700, parents=False, exist_ok=False)
            except OSError:
                raise Refusal("new run directory must not exist; parent must already exist") from None
        try:
            info = self.path.stat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise Refusal("run directory must be owned by current user, mode 0700")
            fd = os.open(str(self.path / "lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            self.lock = os.fdopen(fd, "a+b")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if hasattr(self, "lock"):
                self.lock.close()
            raise Refusal("run directory is locked or unavailable") from None
        self.sequence, self.last_hash = 0, "0" * 64
        self.hashes = [self.last_hash]
        self.audit_path = self.path / "audit.jsonl"
        self.state = None
        try:
            if resume:
                self._read_audit()
                self.state = json.loads(read_regular(self.path / "state.json"), object_pairs_hook=unique_json_object)
                count, anchor = self.state["audit_count"], self.state["audit_hash"]
                if type(count) is not int or not 0 <= count <= self.sequence or self.hashes[count] != anchor:
                    raise Refusal("checkpoint audit anchor mismatch")
            elif self.audit_path.exists():
                raise Refusal("unexpected existing audit")
        except (ValueError, KeyError, TypeError):
            self.lock.close()
            raise Refusal("invalid checkpoint/audit") from None
        except BaseException:
            self.lock.close()
            raise

    def __exit__(self, *args):
        self.lock.close()

    def _read_audit(self):
        data = read_regular(self.audit_path, MAX_ARCHIVE)
        if data and not data.endswith(b"\n"):
            raise Refusal("truncated audit; preserve evidence and reconcile manually")
        for line in data.splitlines():
            event = json.loads(line, object_pairs_hook=unique_json_object)
            if not isinstance(event, dict):
                raise Refusal("invalid audit event object")
            digest = event.pop("hash")
            if (event["sequence"] != self.sequence + 1 or event["previous_hash"] != self.last_hash
                    or hashlib.sha256(canonical(event)).hexdigest() != digest):
                raise Refusal("audit chain is inconsistent")
            self.sequence += 1
            self.last_hash = digest
            self.hashes.append(digest)

    def event(self, event, **details):
        item = {"sequence": self.sequence + 1, "timestamp": utcnow(), "previous_hash": self.last_hash,
                "event": event, **details}
        digest = hashlib.sha256(canonical(item)).hexdigest()
        item["hash"] = digest
        fd = os.open(str(self.audit_path), os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "ab") as handle:
            handle.write(canonical(item) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.sequence += 1
        self.last_hash = digest
        self.hashes.append(digest)

    def write(self, name, data):
        if Path(name).name != name or name in ("lock", "audit.jsonl"):
            raise Refusal("unsafe local output filename")
        data = data.encode() if isinstance(data, str) else data
        target = self.path / name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise Refusal("local output is not a regular file")
        temporary = self.path / (name + ".tmp")
        fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temporary), str(target))
            dfd = os.open(str(self.path), os.O_DIRECTORY | os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def save(self):
        self.state["audit_count"] = self.sequence
        self.state["audit_hash"] = self.last_hash
        self.write("state.json", canonical(self.state) + b"\n")


def extract_collection(data, serial):
    """Return curated bytes, never tar.extract/all. No links, nested directories or unrelated captures."""
    if len(data) > MAX_ARCHIVE:
        raise Refusal("collection exceeds 64 MiB")
    output = {}
    total = 0
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
        with archive:
            for entry in archive:
                path = PurePosixPath(entry.name)
                if entry.isdir() and entry.name.rstrip("/") in ("logs", "results"):
                    continue
                if (not entry.isfile() or entry.issym() or entry.islnk() or path.is_absolute()
                        or ".." in path.parts or len(path.parts) != 2 or path.parts[0] not in ("logs", "results")
                        or entry.size < 0 or entry.size > MAX_FILE):
                    raise Refusal("unsafe collection tar member")
                name = path.name
                if not all(c.isascii() and (c.isalnum() or c in "._-") for c in name) or name.startswith("."):
                    raise Refusal("unsafe collection filename")
                # Native vendor file names vary. Only exact configured serial-prefix
                # results or the dedicated run's log file may be collected.
                if path.parts[0] == "results" and not name.startswith(serial + "."):
                    raise Refusal("result does not belong to configured drive")
                if path.parts[0] == "logs" and name != "metro.log":
                    raise Refusal("unexpected ITDT logging file; explicit review required")
                key = "vendor-" + path.parts[0] + "-" + name
                if key in output:
                    raise Refusal("duplicate collection filename")
                total += entry.size
                if total > MAX_ARCHIVE:
                    raise Refusal("collection expanded size exceeds limit")
                output[key] = archive.extractfile(entry).read(MAX_FILE + 1)
    except (tarfile.TarError, OSError, EOFError):
        raise Refusal("invalid uncompressed collection archive") from None
    if not any(k.startswith("vendor-results-") for k in output):
        raise Refusal("no native vendor result/dump files collected")
    return output


def make_bundle(store, config):
    state = store.state
    result = state["results"].get("diagnostic", {})
    status = state.get("restoration_verified", False)
    ticket = ("Subject: LTO drive diagnostic evidence — " + config.serial + "\n\n"
              "Run: " + state["run_id"] + "\n"
              "Physical manufacturer serial: " + config.manufacturer_serial + "\n"
              "Designated TEST cartridge: " + config.barcode + "\n"
              "ITDT SE configured version: " + config.mover["version"] + "\n"
              "Diagnostic command evidence: " + json.dumps(result, sort_keys=True) + "\n"
              "Configured zoning/library/path restoration verified: " + str(status).lower() + "\n"
              "Optional owner adapter visible/usable verification: " + str(state.get("owner_verified", False)).lower() + "\n"
              "Hardware verdict: UNKNOWN; review native vendor reports and dumps.\n"
              "Application/backup scheduler acceptance: operator verification pending.\n"
              "Completed steps: " + json.dumps(state["completed"]) + "\n"
              "Pending mutating step: " + json.dumps(state.get("pending"), sort_keys=True) + "\n"
              "Failures/evidence gaps: " + json.dumps(state["failures"], sort_keys=True) + "\n"
              "Bundle is local only. Review/redact attachments under your support policy before any manual submission.\n")
    store.write("support-ticket.txt", ticket)
    names = ["support-ticket.txt", "plan.txt", "plan.json", "audit.jsonl", "state.json"]
    names.extend(state.get("evidence", []))
    if any(not isinstance(name, str) or Path(name).name != name for name in names):
        raise Refusal("unsafe bundle evidence path")
    files = {name: read_regular(store.path / name, MAX_ARCHIVE) for name in sorted(set(names))}
    manifest = {"schema": 1, "run_id": state["run_id"], "files": [
        {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in files.items()]}
    manifest_bytes = canonical(manifest) + b"\n"
    store.write("manifest.json", manifest_bytes)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("manifest.json", manifest_bytes)
    store.write("attachments.zip", output.getvalue())
    return manifest
