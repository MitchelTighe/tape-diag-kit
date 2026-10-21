"""Generic plan-first drive-test assistant CLI; no implicit remote execution."""
import argparse
import json
from pathlib import Path
import sys
import uuid

from .dta_config import Refusal, checked, load_config, TOKEN
from .dta_engine import Engine
from .dta_fake import FakeTransport
from .dta_plan import plan_json, render_plan
from .dta_storage import Store, read_regular
from .dta_transport import Authorization, RemoteTransport


def parser():
    result = argparse.ArgumentParser(prog="dta", description="Plan-first LTO drive-test assistant. ITDT tests erase TEST media. Default: no connections.")
    result.add_argument("--config", required=True, help="local TOML configuration; secret values are forbidden in config")
    result.add_argument("--apply", action="store_true", help="authorize remote workflow after terminal entry of exact drive serial")
    result.add_argument("--resume", action="store_true", help="resume completed apply checkpoints; never replay a pending write")
    result.add_argument("--output", type=Path, help="new private run directory; required for apply/resume; parent must exist")
    result.add_argument("--run-id", help="safe unique ID for remote output directory (default random; resume reads checkpoint)")
    result.add_argument("--json", action="store_true", help="print declarative plan as JSON; planning only")
    result.add_argument("--simulate", type=Path, metavar="FIXTURE_DIR", help="use ONLY in-memory fake transports with shipped synthetic scenario")
    return result


def main(argv=None, *, input_stream=None, output_stream=None, confirm=None):
    args = parser().parse_args(argv)
    incoming = input_stream or sys.stdin
    outgoing = output_stream or sys.stdout
    emit = lambda value: print(value, file=outgoing, flush=True)
    try:
        config = load_config(args.config)
        if args.apply and args.json:
            raise Refusal("--json is plan-only")
        if args.resume and args.output is None:
            raise Refusal("--resume requires the original --output directory")
        if args.resume:
            state = json.loads(read_regular(args.output / "state.json"))
            if not isinstance(state, dict):
                raise Refusal("checkpoint must be a JSON object")
            run_id = state.get("run_id")
            if args.run_id and args.run_id != run_id:
                raise Refusal("--run-id differs from checkpoint")
        else:
            run_id = args.run_id or "DTA-" + uuid.uuid4().hex
        checked(run_id, TOKEN, "run ID")
        transcript = render_plan(config, run_id)
        emit(json.dumps(plan_json(config, run_id), indent=2) if args.json else transcript.rstrip())
        if not args.apply:
            if args.output and not args.resume:
                with Store(args.output) as store:
                    store.event("plan.only", config_sha256=config.fingerprint, run_id=run_id,
                                remote_requests=0, write_requests=0)
                    store.write("plan.txt", transcript)
                    store.write("plan.json", json.dumps(plan_json(config, run_id), indent=2) + "\n")
            if not args.json:
                emit("PLAN ONLY: 0 connections, 0 remote requests, 0 hardware writes. Use a NEW output directory for apply.")
            return 0
        if args.output is None:
            raise Refusal("--apply requires --output for durable audit/checkpoints")
        if not args.simulate:
            encoded = json.dumps(config.canonical()).upper()
            if any(marker in encoded for marker in ("SYNTH", "REPLACE", ".INVALID", "00:00:00:00:00:00:00:")):
                raise Refusal("placeholder/synthetic configuration cannot be applied to real transports")
        emit("DESTRUCTIVE TEST: designated TEST cartridge data will be overwritten. Review rollback above.")
        emit("Exclusive ownership required: application quiesced, every fabric/drive port enumerated, no concurrent zone/library writer.")
        if confirm is not None:
            typed = confirm(config.serial)
        else:
            if not incoming.isatty():
                raise Refusal("serial confirmation requires an interactive terminal; piping/flags cannot substitute")
            emit("Type the exact drive serial to authorize this run:")
            typed = incoming.readline().rstrip("\n")
        authorization = Authorization(config, apply=True, typed_serial=typed)
        authorization.require(config)
        with Store(args.output, resume=args.resume) as store:
            transport = FakeTransport(config, args.simulate) if args.simulate else RemoteTransport(config, run_id, authorization)
            engine = Engine(config, run_id, transport, authorization, store, emit=emit,
                            sleep=(lambda _: None) if args.simulate else __import__("time").sleep)
            engine.apply(resume=args.resume)
            failures = engine.state["failures"]
        emit("LOCAL BUNDLE: " + str(args.output / "attachments.zip"))
        emit("Restoration verified; native report review and production application acceptance remain operator follow-ups.")
        return 1 if failures else 0
    except KeyboardInterrupt:
        emit("INTERRUPTED: retain audit/checkpoint and exclusive maintenance ownership; reconcile pending remote writes before recovery.")
        return 130
    except (Refusal, OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        # Only our curated Refusal messages are safe to expose. Other exception
        # strings can contain credential URLs, file contents or transport data.
        message = str(exc) if isinstance(exc, Refusal) else "invalid/unavailable local state; details withheld"
        emit("REFUSED: " + message)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
