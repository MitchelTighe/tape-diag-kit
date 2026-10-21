import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("program", ["tapediag", "dta"])
def test_generated_manual_matches_actual_cli(monkeypatch, program):
    monkeypatch.setenv("COLUMNS", "40")
    content = script("generate-manpage").manual(program)
    assert content == (ROOT / ("docs/man/" + program + ".1.txt")).read_text()
    if program == "tapediag":
        assert ".SS log\\-trend" in content
        assert "\\-\\-library\\-id" in content
    else:
        assert "\\-\\-apply" in content


def test_roff_request_and_escape_injection():
    escaped = script("generate-manpage").roff(".so SYNTH\n'break\n\\escape --flag")
    assert escaped.startswith("\\&.so")
    assert "\n\\&'break" in escaped
    assert "\\eescape \\-\\-flag" in escaped


def test_fixture_walkthrough(tmp_path):
    results = script("verify-v4").verify(tmp_path)
    assert set(results) == {"alerts", "trend", "inventory", "explain", "decode"}
