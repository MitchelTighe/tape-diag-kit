"""Offline histories preserve unknown states and require declared chronology."""

import json
import math
from datetime import datetime

from .fleet import normalize
from .logsense import parse_log_hex
from .tapealert import catalog
from .v3 import timestamp

MAX_SNAPSHOTS = 1000
MAX_HISTORY_CELLS = 10000


def ordered_times(values):
    times = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("every snapshot requires a capture timestamp with timezone")
        try:
            normalized = timestamp(value)
        except OverflowError as exc:
            raise ValueError("capture timestamp is outside the supported UTC range") from exc
        moment = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        if times and moment <= times[-1][0]:
            raise ValueError("snapshots must have strictly increasing capture times")
        times.append((moment, normalized))
    return [t[1] for t in times]


def _bounded_snapshots(rows):
    if not isinstance(rows, list) or not 2 <= len(rows) <= MAX_SNAPSHOTS:
        raise ValueError("provide 2 to 1000 snapshots")


def _flag_states(observation):
    states = [None] * 64
    if observation:
        # Existing parser records contradictions conservatively as active.
        # They cannot establish a reliable transition for historical analysis.
        if any("conflicting" in w for w in observation["warnings"]):
            return states
        for n in observation["inactive_flags"]:
            states[n - 1] = False
        for row in observation["active_flags"]:
            states[row["flag"] - 1] = True
    return states


def tapealert_history(reports):
    _bounded_snapshots(reports)
    try:
        reports = [normalize(r) for r in reports]
    except OverflowError as exc:
        raise ValueError("capture timestamp is outside the supported UTC range") from exc
    if len({r["fleet_id"] for r in reports}) != 1:
        raise ValueError("history requires matching fleet_id")
    times = ordered_times([r["captured_at"] for r in reports])
    drives = [{a["asset_id"]: a for a in r["drives"]} for r in reports]
    identities = sorted({key for snapshot in drives for key in snapshot})
    if len(identities) * len(reports) > MAX_HISTORY_CELLS:
        raise ValueError("history exceeds 10000 asset-snapshot pairs; use shorter time ranges")
    assets, events, warnings = [], [], []
    for identity in identities:
        observed = [s.get(identity) for s in drives]
        if any(d and d["identity_basis"] == "device-path" for d in observed):
            warnings.append(identity + ": confirm device-path identity across snapshots")
        streams = {}
        for stream in ("tapealert", "tapealert_response"):
            observations = [d.get(stream) if d else None for d in observed]
            states = [_flag_states(o) for o in observations]
            streams[stream] = [
                {"captured_at": t, "active": [i + 1 for i, v in enumerate(s) if v is True],
                 "inactive": [i + 1 for i, v in enumerate(s) if v is False],
                 "unknown": [i + 1 for i, v in enumerate(s) if v is None],
                 "warnings": o["warnings"] if o else ["observation missing"]}
                for t, s, o in zip(times, states, observations)]
            for index in range(1, len(states)):
                for flag, (before, after) in enumerate(zip(states[index - 1], states[index]), 1):
                    if before is after:
                        continue
                    kind = ("coverage-lost" if after is None else
                            "active-observed" if before is None and after else
                            "inactive-observed" if before is None else
                            "activated" if after else "cleared")
                    events.append({"asset_id": identity, "stream": stream, "flag": flag,
                                   "before": times[index - 1], "after": times[index], "kind": kind})
        assets.append({"asset_id": identity, "streams": streams})
    return {"format": "tapediag-alert-history-v1", "fleet_id": reports[0]["fleet_id"],
            "snapshots": len(reports), "assets": assets, "events": events,
            "warnings": warnings,
            "notes": ["Clear means observed inactive, not repaired; reads may acknowledge latched flags.",
                      "2Eh latched flags and 12h response flags are separate streams.",
                      "Unknown intervals do not establish activation time or duration."],
            "sources": catalog()["sources"]}


def load_series(text):
    """Read the small original JSON manifest grammar, rejecting duplicate keys."""
    if not isinstance(text, str) or len(text) > 16 * 1024 * 1024:
        raise ValueError("JSON input must be text of at most 16 MiB")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate log-series JSON key")
            result[key] = value
        return result
    def constant(_):
        raise ValueError("non-finite log-series JSON number")
    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("non-finite log-series JSON number")
        return result
    try:
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid log-series JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("expected a JSON object")
    pending = [(result, 0)]
    while pending:
        node, depth = pending.pop()
        if depth > 64:
            raise ValueError("JSON nesting exceeds 64 levels")
        if isinstance(node, dict):
            pending.extend((v, depth + 1) for v in node.values())
        elif isinstance(node, list):
            pending.extend((v, depth + 1) for v in node)
    return result


def log_trend(series):
    if not isinstance(series, dict) or set(series) != {"format", "asset_id", "page_control", "snapshots"}:
        raise ValueError("expected log-series format, asset_id, page_control and snapshots")
    if series["format"] != "tapediag-log-series-v1" or series["page_control"] != "current-cumulative":
        raise ValueError("log series requires format v1 and declared current-cumulative page control")
    identity = series["asset_id"]
    if not isinstance(identity, str) or not identity.strip() or len(identity) > 128:
        raise ValueError("asset_id must be a nonempty label of at most 128 characters")
    snapshots = series["snapshots"]
    _bounded_snapshots(snapshots)
    decoded, maps, media = [], [], []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict) or set(snapshot) != {"captured_at", "medium_id", "pages"}:
            raise ValueError("snapshot requires captured_at, medium_id and pages")
        medium = snapshot["medium_id"]
        if medium is not None and (not isinstance(medium, str) or not medium.strip() or len(medium) > 128):
            raise ValueError("medium_id must be null or a nonempty label of at most 128 characters")
        pages = snapshot["pages"]
        if not isinstance(pages, list) or len(pages) > 32:
            raise ValueError("snapshot pages must be a list of at most 32 captures")
        parsed, mapping, seen = [], {}, set()
        for page in pages:
            if not isinstance(page, dict) or set(page) != {"hex", "profile"}:
                raise ValueError("each page requires hex and profile")
            result = parse_log_hex(page["hex"], page["profile"])
            key = (result["page"], result["subpage"])
            if key in seen:
                raise ValueError("duplicate page/subpage in snapshot")
            seen.add(key)
            parsed.append(result)
            for row in result["parameters"]:
                if row["kind"] != "unknown":
                    mapping[key + (row["code"],)] = dict(row, profile=result["profile"])
        decoded.append({"captured_at": snapshot["captured_at"], "medium_id": medium, "pages": parsed})
        maps.append(mapping)
        media.append(medium)
    times = ordered_times([s["captured_at"] for s in snapshots])
    for snapshot, time in zip(decoded, times):
        snapshot["captured_at"] = time
    changes = []
    for i in range(1, len(maps)):
        for key in sorted(set(maps[i - 1]) | set(maps[i])):
            a, b = maps[i - 1].get(key), maps[i].get(key)
            row = b or a
            previous, current = a["value"] if a else None, b["value"] if b else None
            delta = None
            if previous is None or current is None:
                kind = "unavailable"
            elif a["profile"] != b["profile"] or a["length"] != b["length"] or a["control"] != b["control"]:
                kind = "encoding-changed"
            elif row["scope"] == "medium" and (media[i] is None or media[i - 1] != media[i]):
                kind = "medium-unconfirmed"
            elif row["kind"] == "counter":
                if current < previous:
                    kind = "reset-or-wrap"
                else:
                    kind, delta = "counter-delta", current - previous
            else:
                kind = "unchanged" if previous == current else "state-changed"
            changes.append({"before": times[i - 1], "after": times[i], "page": key[0],
                            "subpage": key[1], "code": key[2], "name": row["name"],
                            "unit": row["unit"], "previous": previous, "current": current,
                            "kind": kind, "delta": delta})
    return {"format": "tapediag-log-trend-v1", "asset_id": identity,
            "snapshots": decoded, "changes": changes,
            "notes": ["Caller declares stable drive identity and current-cumulative page control.",
                      "Medium statistics require matching declared medium_id for comparisons.",
                      "Counter decreases may mean reset, replacement or wrap; no rate is inferred.",
                      "This is evidence history, not a calibrated drive-health score."]}
