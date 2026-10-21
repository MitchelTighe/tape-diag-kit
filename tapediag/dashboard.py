"""Produce a single-file, offline fleet dashboard. No server or dependencies."""
import base64
import hashlib
import json
from importlib.resources import files

from .fleet import normalize
from .validation import report_schema


def json_script(value):
    # Prevent an observation containing </script> or HTML entities from escaping.
    return json.dumps(value, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_dashboard(reports=()):
    normalized = [normalize(report) for report in reports]
    template = files("tapediag").joinpath("dashboard.html").read_text(encoding="utf-8")
    # Hash only the executable script, allowing file:// viewing without unsafe-inline.
    script = template.split('<script id="application">', 1)[1].split('</script>', 1)[0]
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    template = template.replace("__SCRIPT_HASH__", digest)
    template = template.replace(">__SCHEMA__</script>", ">" + json_script(report_schema("3.0")) + "</script>")
    return template.replace(">__REPORTS__</script>", ">" + json_script(normalized) + "</script>")
