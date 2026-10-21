"""Compare mtx status observations; never turn tag matches into robot commands."""

from .observations import library_checks
from .parsers import parse_library

SOURCE = "https://github.com/mtx-org/mtx/blob/master/mtx/mtx.doc"


def inventory_capture(text):
    """Use the existing mtx grammar, refusing ambiguous element identities."""
    if not isinstance(text, str) or len(text) > 16 * 1024 * 1024:
        raise ValueError("inventory capture must be text of at most 16 MiB")
    result = parse_library(text)
    if result["reported_drives"] is None:
        raise ValueError("inventory comparison requires an mtx storage changer header")
    if any(w.startswith("duplicate element:") for w in result["warnings"]):
        raise ValueError("duplicate element identity prevents inventory comparison")
    return result


def _elements(status):
    return {(("drive" if kind == "drives" else "storage"), e["element"]):
            dict(e, type=kind)
            for kind in ("drives", "slots", "ie_ports") for e in status[kind]}


def _tags(elements):
    tags = {}
    for key, element in elements.items():
        for tag in set(t for t in (element["barcode"], element["alternate_barcode"]) if t):
            tags.setdefault(tag, []).append((key, element["full"]))
    return tags


def diff_inventory(before_text, after_text, library_id):
    if not isinstance(library_id, str) or not library_id.strip() or len(library_id) > 128:
        raise ValueError("library_id must be a nonempty label of at most 128 characters")
    before, after = inventory_capture(before_text), inventory_capture(after_text)
    old, new = _elements(before), _elements(after)
    events, relocations = [], []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a is None or b is None:
            events.append({"element_kind": key[0], "element": key[1],
                           "kind": "newly-observed" if a is None else "unobserved-after",
                           "before": a, "after": b})
        else:
            fields = {name: {"before": a[name], "after": b[name]}
                      for name in ("full", "barcode", "alternate_barcode", "source_slot", "type")
                      if a[name] != b[name]}
            if fields:
                events.append({"element_kind": key[0], "element": key[1],
                               "kind": "changed", "fields": fields})
    old_tags, new_tags = _tags(old), _tags(new)
    ambiguous = sorted(t for t in set(old_tags) | set(new_tags)
                       if len(old_tags.get(t, [])) > 1 or len(new_tags.get(t, [])) > 1
                       or any(not full for _, full in old_tags.get(t, []) + new_tags.get(t, [])))
    for tag in sorted(set(old_tags) & set(new_tags) - set(ambiguous)):
        source, destination = old_tags[tag][0][0], new_tags[tag][0][0]
        if source == destination:
            continue
        # Both endpoints must be observed at both times. An absent slot is not
        # evidence that a tag left it, nor an absent destination that it arrived.
        if source in new and destination in old:
            relocations.append({"barcode": tag,
                                "before": {"kind": source[0], "element": source[1]},
                                "after": {"kind": destination[0], "element": destination[1]}})
    warnings = []
    if before["device"] != after["device"]:
        warnings.append("capture device labels differ; caller must confirm library identity")
    if ambiguous:
        warnings.append("ambiguous or empty-element tags excluded from relocation candidates")
    for phase, status in (("before", before), ("after", after)):
        warnings.extend(phase + ": " + c["message"] for c in library_checks(status)
                        if c["severity"] == "warn")
    return {"format": "tapediag-inventory-diff-v1", "library_id": library_id,
            "events": events, "relocation_candidates": relocations,
            "ambiguous_tags": ambiguous, "warnings": warnings,
            "notes": ["Caller asserts both captures describe the same library.",
                      "Element numbers are mtx logical identifiers, not /dev mappings or sg raw addresses.",
                      "Tag relocation is a candidate association, not proof of a physical move.",
                      "Missing elements mean missing evidence, not removed hardware.",
                      "Occupancy does not establish door, sensor or robotics health."],
            "sources": [SOURCE]}
