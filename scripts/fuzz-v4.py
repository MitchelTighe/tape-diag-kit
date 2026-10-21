"""Deterministic stdlib fuzz pass: offline parser mutations, capped wall time.

Unexpected exceptions or non-JSON output fail with a reproducible case. ValueError
is the documented refusal. Seeded edge cases supplement random input; this does
not claim exhaustive fuzz/security coverage. Never opens hardware or a network.
"""

import argparse
import copy
import json
import random
import time
from pathlib import Path

from tapediag.explain import explain
from tapediag.history import load_series, log_trend, tapealert_history
from tapediag.inventory_diff import diff_inventory, inventory_capture
from tapediag.logsense import hex_bytes, parse_log_hex

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=30, choices=range(1, 121))
    parser.add_argument("--iterations", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20261020)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    fixtures = ROOT / "fixtures/v4"
    series = json.loads((fixtures / "log-series.json").read_text())
    reports = [json.loads((fixtures / ("alerts-%d.json" % n)).read_text()) for n in (16, 17)]
    inventory = (fixtures / "inventory-before.txt").read_text()
    tokens = ["", None, False, 0, [], {}, "0001-01-01T00:00:00+01:00",
              "9999-12-31T23:59:59-01:00", "2026-10-16T00:00:00Z", "\0",
              "NaN", "9" * 5000, ["unexpected"]]
    counts, crashes = {}, []
    started = time.monotonic()

    def probe(label, function, value, *extra):
        counts[label] = counts.get(label, 0) + 1
        try:
            result = function(value, *extra)
        except ValueError:
            return
        except Exception as exc:
            crashes.append({"parser": label, "type": type(exc).__name__,
                            "input": value, "message": str(exc)})
            return
        # Serialization failure is a parser-output defect, not input refusal.
        try:
            if not isinstance(result, bytes):
                json.dumps(result, allow_nan=False)
        except Exception as exc:
            crashes.append({"parser": label, "type": type(exc).__name__,
                            "input": value, "message": "output serialization: " + str(exc)})

    # Deterministic edge cases run even under a short budget.
    for token in tokens:
        probe("hex", hex_bytes, token)
        probe("log", parse_log_hex, token)
        probe("json", load_series, json.dumps({"nested": token}))
        probe("explain", explain, token)
        probe("inventory", inventory_capture, token)
        probe("inventory-diff", diff_inventory, token, inventory, "SYNTH-FUZZ")
        candidate = copy.deepcopy(series)
        candidate["snapshots"][0]["captured_at"] = token
        probe("trend", log_trend, candidate)
    for i in range(max(0, args.iterations)):
        if time.monotonic() - started > args.seconds:
            break
        raw = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 200)))
        # Alternate arbitrary bytes with structured, length-correct parameters.
        if i % 2:
            page = rng.choice([0x0c, 0x17, 0x2e, 0x31, 0x6e, 0xff])
            payload = bytes((0, rng.randrange(65), rng.randrange(256), len(raw))) + raw
            raw = bytes((page, 0)) + len(payload).to_bytes(2, "big") + payload
        text = raw.hex(" ")
        probe("hex", hex_bytes, text)
        probe("log", parse_log_hex, text, rng.choice(["ssc", "lto5-6-capacity"]))
        noise = "".join(rng.choice("0123456789abcdef :/\n\t<>\0xyz") for _ in range(rng.randrange(100)))
        probe("explain", explain, rng.choice(["sense:", "asc:", "page:", "tapealert:", ""]) + noise)
        probe("json", load_series, noise)
        lines = inventory.splitlines()
        lines[rng.randrange(len(lines))] = noise
        text = "\n".join(lines)
        probe("inventory", inventory_capture, text)
        probe("inventory-diff", diff_inventory, text, inventory, "SYNTH-FUZZ")
        candidate = copy.deepcopy(series)
        snapshot = candidate["snapshots"][rng.randrange(4)]
        snapshot[rng.choice(["medium_id", "captured_at", "pages"])] = rng.choice(tokens)
        probe("trend", log_trend, candidate)
        changed = copy.deepcopy(reports)
        changed[rng.randrange(2)][rng.choice(["drives", "captured_at", "fleet_id"])] = rng.choice(tokens)
        probe("alert-history", tapealert_history, changed)
        if len(crashes) >= 8:
            break
    print(json.dumps({"seed": args.seed, "seconds": round(time.monotonic() - started, 3),
                      "counts": counts, "crashes": crashes}, indent=2))
    return 1 if crashes else 0


if __name__ == "__main__":
    raise SystemExit(main())
