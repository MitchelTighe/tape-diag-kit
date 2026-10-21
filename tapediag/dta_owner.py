"""Vendor-neutral command-template adapter for exclusive drive ownership.

This is an original DTA JSON contract, NOT claimed native admin-tool output.
Site adapters must be independently reviewed; no proprietary command grammar is
guessed here. Templates are trusted operator configuration, never shell snippets.
"""
from datetime import datetime, timezone
import json

from .dta_config import Refusal, unique_json_object


def owner_request(config, run_id, action):
    from .dta_plan import Request
    owner = config.owner
    key = "verify_argv" if action == "probe" else action + "_argv"
    values = {"serial": config.serial, "manufacturer_serial": config.manufacturer_serial,
              "drive": owner["drive"], "device": owner["device"], "run_id": run_id}
    argv = tuple(value.format(**values) for value in owner[key])
    return Request("owner." + action, owner["ssh"], argv, timeout=30)


def parse_owner(text, config, run_id, locked):
    try:
        if len(text) > 65536:
            raise ValueError()
        data = json.loads(text, object_pairs_hook=unique_json_object)
        required = {"schema", "serial", "manufacturer_serial", "drive", "device", "locked", "lock_owner",
                    "idle", "mounts", "usable", "observed_at"}
        if not isinstance(data, dict) or set(data) != required or type(data["schema"]) is not int or data["schema"] != 1:
            raise ValueError()
        if (data["serial"] != config.serial or data["manufacturer_serial"] != config.manufacturer_serial
                or data["drive"] != config.owner["drive"] or data["device"] != config.owner["device"]
                or any(type(data[key]) is not bool for key in ("locked", "idle", "usable"))
                or type(data["mounts"]) is not int or data["mounts"] < 0):
            raise ValueError()
        observed = datetime.fromisoformat(data["observed_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None or abs((datetime.now(timezone.utc) - observed).total_seconds()) > 60:
            raise ValueError()
        if data["locked"] is not locked:
            raise ValueError()
        if locked and (data["lock_owner"] != run_id or not data["idle"] or data["mounts"] != 0):
            raise ValueError()
        if not locked and (data["lock_owner"] is not None or not data["usable"]):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise Refusal("owner verifier did not prove fresh, exact identity, expected ownership and idle/no-mounts or usable state") from None
    return {key: data[key] for key in ("locked", "idle", "mounts", "usable", "observed_at")}
