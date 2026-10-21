import io
import json
from pathlib import Path

import pytest

from tapediag.dta import main


def arguments(dta_fixtures):
    return ["--config", str(dta_fixtures / "config.synthetic.toml"), "--run-id", "SYNTH-CLI"]


def test_cli_dry_run_complete_transcript_no_transport(dta_fixtures, monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("plan constructed a remote transport")
    monkeypatch.setattr("tapediag.dta.RemoteTransport", fail)
    monkeypatch.setattr("tapediag.dta.FakeTransport", fail)
    stream = io.StringIO()
    assert main(arguments(dta_fixtures) + ["--simulate", str(dta_fixtures)], output_stream=stream) == 0
    text = stream.getvalue()
    assert "[preflight]" in text and "[bundle]" in text
    assert text.endswith("PLAN ONLY: 0 connections, 0 remote requests, 0 hardware writes. Use a NEW output directory for apply.\n")


def test_cli_plan_writes_only_local_audit(tmp_path, dta_fixtures):
    output = tmp_path / "plan"
    assert main(arguments(dta_fixtures) + ["--output", str(output)], output_stream=io.StringIO()) == 0
    assert {p.name for p in output.iterdir()} == {"lock", "audit.jsonl", "plan.txt", "plan.json"}
    audit = json.loads((output / "audit.jsonl").read_text())
    assert audit["remote_requests"] == audit["write_requests"] == 0
    assert len(json.loads((output / "plan.json").read_text())["steps"]) == 15


def test_json_plan_is_one_machine_readable_document(dta_fixtures):
    output = io.StringIO()
    assert main(arguments(dta_fixtures) + ["--json"], output_stream=output) == 0
    document = json.loads(output.getvalue())
    assert document["mode"] == "plan" and document["remote_requests"] == document["hardware_writes"] == 0


@pytest.mark.parametrize("args", [["--apply"], ["--apply", "--json"], ["--resume"]])
def test_cli_missing_requirements_fail_closed(dta_fixtures, args):
    assert main(arguments(dta_fixtures) + args, output_stream=io.StringIO()) == 2


def test_serial_confirmation_cannot_be_piped(tmp_path, dta_fixtures):
    output = tmp_path / "run"
    stream = io.StringIO()
    result = main(arguments(dta_fixtures) + ["--simulate", str(dta_fixtures), "--apply", "--output", str(output)],
                  input_stream=io.StringIO("SYNTH-DRIVE-DTA\n"), output_stream=stream)
    assert result == 2 and "interactive terminal" in stream.getvalue()
    assert not output.exists()


@pytest.mark.parametrize("typed", ["SYNTH-WRONG", "", "SYNTH-DRIVE-DTA "])
def test_wrong_typed_serial_never_creates_run(tmp_path, dta_fixtures, typed):
    output = tmp_path / "run"
    result = main(arguments(dta_fixtures) + ["--simulate", str(dta_fixtures), "--apply", "--output", str(output)],
                  output_stream=io.StringIO(), confirm=lambda _: typed)
    assert result == 2 and not output.exists()


def test_synthetic_values_cannot_reach_real_transport(tmp_path, dta_fixtures, monkeypatch):
    monkeypatch.setattr("tapediag.dta.RemoteTransport", lambda *a, **k: pytest.fail("synthetic real transport"))
    output = tmp_path / "run"
    stream = io.StringIO()
    assert main(arguments(dta_fixtures) + ["--apply", "--output", str(output)], output_stream=stream,
                confirm=lambda serial: serial) == 2
    assert "placeholder/synthetic" in stream.getvalue() and not output.exists()


def test_cli_fake_apply_and_completed_resume(tmp_path, dta_fixtures):
    output = tmp_path / "run"
    args = arguments(dta_fixtures) + ["--apply", "--simulate", str(dta_fixtures), "--output", str(output)]
    stream = io.StringIO()
    assert main(args, output_stream=stream, confirm=lambda serial: serial) == 0
    assert (output / "attachments.zip").is_file()
    assert "Restoration verified" in stream.getvalue()
    before = (output / "audit.jsonl").read_bytes()
    assert main(args + ["--resume"], output_stream=io.StringIO(), confirm=lambda serial: serial) == 0
    assert (output / "audit.jsonl").read_bytes() != before  # local resume event only
    events = [json.loads(line) for line in (output / "audit.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "resume.begin"


def test_config_parse_errors_do_not_echo_file_contents(tmp_path):
    config = tmp_path / "broken.toml"
    marker = "SYNTH_PRIVATE_MARKER"
    config.write_text(marker + ' = "unterminated')
    stream = io.StringIO()
    assert main(["--config", str(config)], output_stream=stream) == 2
    assert marker not in stream.getvalue()
