"""The only subprocess boundary: exact read-only argv grammars, never a shell."""

import math
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import List, Optional, Sequence

# No caller-supplied flags, binary paths, output files, command strings, or
# environment are accepted. Keep this grammar narrower than upstream utilities.
LOG_PAGES = ("0x00", "0x02", "0x03", "0x06", "0x0c", "0x0d", "0x0e", "0x12", "0x14", "0x17", "0x2e")
TRUSTED_PATH = "/usr/bin:/bin:/usr/local/bin"


class SafetyError(ValueError):
    """The request does not match a complete allowlisted command."""


def device_path(value: str, kind: str = "sg") -> str:
    pattern = r"/dev/sg[0-9]+" if kind == "sg" else r"/dev/nst[0-9]+"
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise SafetyError("expected %s device path, got %r" % (kind, value))
    return value


def validate_command(argv: Sequence[str]) -> List[str]:
    """Reject everything except these exact command forms, including extras."""
    if not isinstance(argv, (list, tuple)) or not argv or not all(isinstance(x, str) for x in argv):
        raise SafetyError("command must be a nonempty argv list")
    args = list(argv)
    if args == ["sg_map", "-x"] or args == ["lsscsi", "-g"] or args == ["ltfs", "-o", "device_list"]:
        return args
    if len(args) == 4 and args[:2] == ["sg_logs", "--readonly"]:
        if args[2] in ["--page=" + p for p in LOG_PAGES]:
            device_path(args[3])
            return args
    if len(args) == 4 and args[:2] == ["sg_inq", "--export"] and args[2] in ("--page=0x80", "--page=0x83"):
        device_path(args[3])
        return args
    if len(args) == 5 and args[:2] == ["sg_read_attr", "--readonly"]:
        from .observations import MAM_ATTRIBUTES
        if args[2] in ["--first=" + k for k in MAM_ATTRIBUTES] and args[3] == "--filter=" + args[2].split("=")[1]:
            device_path(args[4])
            return args
    if len(args) == 2 and args[0] in ("sg_inq", "sg_turs"):
        device_path(args[1])
        return args
    if len(args) == 4 and args[:2] == ["mt", "-f"] and args[3] == "status":
        device_path(args[2], "nst")
        return args
    if len(args) == 4 and args[:2] == ["mtx", "-f"] and args[3] in ("status", "inquiry"):
        device_path(args[2])
        return args
    raise SafetyError("refused: command is outside the read-only allowlist: %r" % args)


@dataclass
class CommandResult:
    argv: List[str]
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.error is None

    def to_dict(self) -> dict:
        return asdict(self)


def _text(value) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


class Runner:
    def __init__(self, execute: bool = False, timeout: float = 15.0):
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 300:
            raise SafetyError("timeout must be finite and in (0, 300] seconds")
        self.execute = execute
        self.timeout = timeout
        self.results: List[CommandResult] = []

    def run(self, argv: Sequence[str]) -> CommandResult:
        args = validate_command(argv)  # Validation also applies to dry-run.
        result = CommandResult(args)
        self.results.append(result)
        if not self.execute:
            return result
        # Never allow an environment setting to turn LOG SENSE into the legacy
        # sg3_utils option parser, or make mt use a different device by default.
        env = {"PATH": TRUSTED_PATH, "LC_ALL": "C", "LANG": "C"}
        executable = shutil.which(args[0], path=TRUSTED_PATH)
        if executable is None:
            result.error = "executable not found: " + args[0]
            return result
        if args[0] == "mt" and os.path.realpath(args[2]) != args[2]:
            result.error = "refused: mt requires a direct non-rewinding /dev/nstN path"
            return result
        try:
            proc = subprocess.run(
                [executable] + args[1:], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout,
                check=False, shell=False, env=env,
            )
            result.returncode = proc.returncode
            result.stdout, result.stderr = proc.stdout, proc.stderr
            if proc.returncode:
                result.error = "command exited with status %d" % proc.returncode
        except subprocess.TimeoutExpired as exc:
            result.stdout, result.stderr = _text(exc.stdout), _text(exc.stderr)
            result.error = "command timed out after %g seconds" % self.timeout
            result.timed_out = True
        except OSError as exc:
            result.error = str(exc)
        if args[0] == "sg_inq" and "--export" not in args:
            from .observations import synthetic_identifier
            result.stdout = re.sub(r"(?im)^(\s*Unit serial number\s*:\s*)(.*)$",
                                   lambda m: m[1] + (synthetic_identifier(m[2], "DRIVE-SERIAL") or ""), result.stdout)
            # An inquiry error can echo identity data; do not persist arbitrary diagnostics.
            if result.stderr:
                result.stderr = "inquiry diagnostic text omitted for identifier privacy; see returncode/error"
        # New identifier-bearing observations never retain unrestricted raw output.
        if args[0] == "sg_read_attr" or (args[0] == "sg_inq" and "--export" in args):
            from .observations import parse_mam, parse_inquiry
            if args[0] == "sg_read_attr":
                parsed = parse_mam(result.stdout)
                result.stdout = "\n".join("%s: %s" % (a["name"], a["value"] if a["value"] is not None else "unknown") for a in parsed["attributes"])
            else:
                parsed = parse_inquiry(result.stdout)
                result.stdout = ("SCSI_SERIAL=" + parsed["serial"] + "\n") if parsed["serial"] else ""
                result.stdout += "\n".join(a["type"] + "=" + a["value"] for a in parsed["identifiers"])
            if result.stderr:
                result.stderr = "diagnostic text omitted for identifier privacy; see returncode/error"
        return result


def mam_commands(dev):
    from .observations import MAM_ATTRIBUTES
    return [validate_command(["sg_read_attr", "--readonly", "--first=" + k, "--filter=" + k, dev]) for k in MAM_ATTRIBUTES]


def inquiry_commands(dev):
    return [["sg_inq", device_path(dev)]] + [validate_command(["sg_inq", "--export", "--page=" + p, dev]) for p in ("0x80", "0x83")]


def log_command(dev: str, page: str) -> List[str]:
    return validate_command(["sg_logs", "--readonly", "--page=" + page, dev])


def drive_commands(dev: str, nst: Optional[str] = None) -> List[List[str]]:
    result = [["sg_inq", device_path(dev)], ["sg_turs", dev]]
    # An sg index has no necessary relationship to the st/nst index.
    if nst is not None:
        result.append(["mt", "-f", device_path(nst, "nst"), "status"])
    return result
