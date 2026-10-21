"""Dependency-free validation for the exact schema vocabulary shipped here.

This is an internal validator, not a general JSON Schema implementation. Tests
also check reports against the independent jsonschema Draft202012Validator.
"""

import json
import math
import re
from importlib.resources import files


def report_schema(version="1.0"):
    if version not in ("1.0", "2.0", "3.0"):
        raise ValueError("unsupported schema version: " + str(version))
    name = "report_schema.json" if version == "1.0" else "report_schema_v%s.json" % version[0]
    return json.loads(files("tapediag").joinpath(name).read_text(encoding="utf-8"))


def validate_report(value):
    version = value.get("schema_version", "1.0") if isinstance(value, dict) else "1.0"
    root = report_schema(version)

    def visit(value, schema, path):
        def fail(reason):
            raise ValueError("invalid v%s report at %s: %s" % (version[0], path, reason))
        if "$ref" in schema:
            return visit(value, root["$defs"][schema["$ref"].split("/")[-1]], path)
        if "anyOf" in schema:
            for option in schema["anyOf"]:
                try:
                    visit(value, option, path)
                    return
                except ValueError:
                    pass
            fail("does not match any permitted type")
        if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
            fail("wrong constant")
        if "enum" in schema and value not in schema["enum"]:
            fail("value is outside enum")
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            checks = {"null": value is None, "string": isinstance(value, str),
                      "boolean": isinstance(value, bool), "integer": type(value) is int,
                      "number": type(value) in (int, float) and (type(value) is int or math.isfinite(value)),
                      "array": isinstance(value, list), "object": isinstance(value, dict)}
            if not any(checks[t] for t in types):
                fail("wrong type")
        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", math.inf):
                fail("invalid string length")
            if "pattern" in schema and re.search(schema["pattern"], value) is None:
                fail("string does not match pattern")
            if schema.get("format") == "date-time":
                from .v3 import timestamp
                try:
                    timestamp(value)
                except ValueError:
                    fail("invalid timestamp")
        if isinstance(value, dict) and "properties" in schema:
            if set(schema.get("required", [])) - set(value):
                fail("required property missing")
            if schema.get("additionalProperties") is False and set(value) - set(schema["properties"]):
                fail("unknown property")
            for key, child in value.items():
                if key in schema["properties"]:
                    visit(child, schema["properties"][key], path + "." + key)
        if isinstance(value, list) and "items" in schema:
            if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in value}) != len(value):
                fail("duplicate array item")
            for index, child in enumerate(value):
                visit(child, schema["items"], path + "[%d]" % index)
        if type(value) in (int, float):
            if "minimum" in schema and value < schema["minimum"]:
                fail("below minimum")
            if "maximum" in schema and value > schema["maximum"]:
                fail("above maximum")
    visit(value, root, "$")
    if version == "3.0":
        _validate_v3(value)
    return value


def _validate_v3(value):
    """Cross-field integrity checks beyond the published structural schema."""
    from .safety import device_path, validate_command
    if value["document_type"] == "workflow":
        for step in value["steps"]:
            if step["device"] is not None:
                device_path(step["device"])
            for argv in step["argv"]:
                validate_command(argv)
            for result in step["results"]:
                validate_command(result["argv"])
        return
    from .scoring import score_drive, score_library, score_report
    from .tapealert import catalog
    flags = {f["flag"]: dict(f, active=True) for f in catalog()["flags"]}
    for drive in value["drives"]:
        for obs in (drive.get("tapealert"), drive.get("tapealert_response")):
            if not obs:
                continue
            active = [f["flag"] for f in obs["active_flags"]]
            observed, inactive, unobserved = map(set, (obs["observed_flags"], obs["inactive_flags"], obs["unobserved_flags"]))
            if (len(set(active)) != len(active) or set(active) & inactive or
                    set(active) | inactive != observed or unobserved != set(range(1, 65)) - observed):
                raise ValueError("invalid v3 report: inconsistent TapeAlert partition")
            if any(f != flags[f["flag"]] for f in obs["active_flags"]):
                raise ValueError("invalid v3 report: TapeAlert severity/name differs from public catalog")
    assets = value["drives"] + value["libraries"]
    keys = [a["asset_id"] for a in assets]
    if len(set(keys)) != len(keys):
        raise ValueError("invalid v3 report: duplicate asset_id")
    devices = [a["device"] for a in assets]
    if len(set(devices)) != len(devices):
        raise ValueError("invalid v3 report: duplicate device")
    for kind, rows in (("drive", value["drives"]), ("library", value["libraries"])):
        for asset in rows:
            device_path(asset["device"])
            expected = (score_drive if kind == "drive" else score_library)(asset, value["errors"])
            if expected != asset["health"]:
                raise ValueError("invalid v3 report: health does not match observations/model")
    if value["health"] != score_report(value):
        raise ValueError("invalid v3 report: fleet health does not match assets")
