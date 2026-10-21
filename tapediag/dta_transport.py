"""Injectable SSH/HTTPS transports. No transport is invoked during planning.

SSH host trust uses existing strict known-host configuration. HTTPS requires a
trusted TLS endpoint; redirects, proxy environment and persistent cookies are
disabled. Neither login URLs, HTTP exceptions nor remote stderr are printed.
"""
from dataclasses import dataclass
import hashlib
import http.cookiejar
import os
import selectors
import shlex
import signal
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

from .dta_config import Refusal
from .dta_plan import build_plan
from .dta_storage import MAX_ARCHIVE
from .dta_vendor import xml_status, xml_root


class Uncertain(Refusal):
    """The remote operation may still be running; do not replay or auto-restore."""


@dataclass(frozen=True)
class Response:
    returncode: int
    stdout: bytes
    stderr: bytes = b""

    @property
    def text(self):
        try:
            return self.stdout.decode("utf-8")
        except UnicodeError:
            raise Refusal("vendor response is not UTF-8 text") from None

    def summary(self):
        return {"returncode": self.returncode, "stdout_bytes": len(self.stdout),
                "stderr_bytes": len(self.stderr), "stdout_sha256": hashlib.sha256(self.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(self.stderr).hexdigest()}


class Authorization:
    def __init__(self, config, apply=False, typed_serial=None):
        self.fingerprint = config.fingerprint
        self.armed = bool(apply and typed_serial == config.serial)

    def require(self, config):
        if not self.armed or self.fingerprint != config.fingerprint:
            raise Refusal("remote action requires --apply AND exact typed drive serial")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refusal("HTTP redirect refused; login/session data withheld")


def run_bounded(argv, timeout, limit=MAX_ARCHIVE):
    """Read both pipes incrementally; bound time and aggregate output without a shell."""
    environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": os.path.expanduser("~")}
    if os.environ.get("SSH_AUTH_SOCK"):
        environment["SSH_AUTH_SOCK"] = os.environ["SSH_AUTH_SOCK"]
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=environment,
                                   start_new_session=True, close_fds=True)
    except OSError:
        raise Refusal("SSH executable could not be started") from None
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    total, deadline = 0, time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Uncertain("transport timeout; remote process may still run; reconciliation required")
            for key, _ in selector.select(min(remaining, 0.25)):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                total += len(data)
                if total > limit:
                    raise Uncertain("transport output limit exceeded; remote outcome uncertain")
                chunks[key.data].extend(data)
        try:
            code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise Uncertain("transport timeout after pipe close; remote outcome uncertain") from None
        if code == 255 or code < 0:
            raise Uncertain("SSH connection or signal failure; remote outcome uncertain")
        return Response(code, bytes(chunks["stdout"]), bytes(chunks["stderr"]))
    except BaseException:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()


class RemoteTransport:
    """Request grammar is exactly the generated plan, including repeated guard reads."""
    def __init__(self, config, run_id, authorization, runner=run_bounded, credentials=None, opener=None):
        self.config, self.authorization, self.runner = config, authorization, runner
        self.allowed = {self._key(r) for step in build_plan(config, run_id)
                        for r in step.requests + step.rollback + step.before + step.after + step.after_each_write}
        self.credentials = credentials or os.environ.__getitem__
        self.cookies = http.cookiejar.CookieJar()
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(), urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self.logged_in = False

    @staticmethod
    def _key(request):
        return (request.op, request.target, request.argv, request.endpoint, request.query, request.timeout)

    def execute(self, request):
        # Even reads require explicit live authorization; default never contacts endpoints.
        self.authorization.require(self.config)
        if self._key(request) not in self.allowed:
            raise Refusal("transport request is outside the generated plan")
        if request.endpoint:
            return self._http(request)
        command = shlex.join(request.argv)
        if request.op in ("zone.remove", "zone.add"):
            command = '{} "{}", "{}"'.format(*request.argv)
        elif request.op == "zone.enable":
            command = 'cfgenable "{}" -f'.format(request.argv[1])
        argv = ["/usr/bin/ssh", "-T", "-oBatchMode=yes", "-oStrictHostKeyChecking=yes",
                "-oUpdateHostKeys=no", "-oConnectTimeout=10", "-oConnectionAttempts=1",
                "-oForwardAgent=no", "-oForwardX11=no", "-oClearAllForwardings=yes", "-oPermitLocalCommand=no",
                "-oControlMaster=no", "-oControlPath=none", "-oServerAliveInterval=15",
                "-oServerAliveCountMax=2", "--", request.target, command]
        return self.runner(argv, request.timeout)

    def _http(self, request):
        params = dict(request.query)
        if request.op == "library.login":
            try:
                params = {"username": self.credentials(self.config.library["username_env"]),
                          "password": self.credentials(self.config.library["password_env"])}
                if not all(isinstance(v, str) and v for v in params.values()):
                    raise ValueError()
            except (KeyError, ValueError):
                raise Refusal("required library credential environment NAME is unset/empty; values withheld") from None
        elif not self.logged_in:
            raise Refusal("library session is not authenticated")
        query = "progress" if request.op == "library.progress" else urlencode(params)
        url = request.target + "/gf/" + request.endpoint + ("?" + query if query else "")
        try:
            req = urllib.request.Request(url, method="GET", headers={"Accept": "application/xml"})
            with self.opener.open(req, timeout=request.timeout) as response:
                if response.getcode() != 200 or response.geturl() != url:
                    raise Refusal("unexpected HTTP status or URL; details withheld")
                data = response.read(4 * 1024 * 1024 + 1)
                if len(data) > 4 * 1024 * 1024:
                    raise Refusal("library response exceeds size limit")
        except (OSError, urllib.error.URLError, ValueError):
            if request.write:
                raise Uncertain("library transport failed; move outcome uncertain; details withheld") from None
            raise Refusal("library transport failed; authentication/URL details withheld") from None
        result = Response(0, data)
        if request.op == "library.login":
            xml_status(result.text, "login")
            # Real BlueScale requires a session cookie. An injected opener used in
            # tests must populate the same in-memory cookie jar.
            if not list(self.cookies):
                raise Refusal("library login did not supply a session cookie")
            self.logged_in = True
        elif request.op == "library.logout":
            xml_root(result.text, "logout")
            self.cookies.clear()
            self.logged_in = False
        return result
