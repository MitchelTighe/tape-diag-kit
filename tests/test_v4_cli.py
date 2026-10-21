import json

import pytest

from tapediag.cli import main
from tapediag.explain import explain
from tapediag.offline_cli import evidence_html


@pytest.mark.parametrize("code,name", [
    ("tapealert:20", "Clean now"), ("tapealert:0x14", "Clean now"),
    ("sense:2/3a/00", "No medium reported"), ("sense:02/3A/00", "No medium reported"),
    ("asc:29/00", "Power-on or reset event"), ("page:0x2e", "TapeAlert"),
    ("density:0x5e", "LTO-8"),
])
def test_offline_explanation(code, name):
    result = explain(code)
    assert result["known"]
    assert result["name"] == name
    assert result["sources"]
    assert result["guidance"]
    assert result["scope"]


@pytest.mark.parametrize("code", ["tapealert:64", "tapealert:255", "asc:ff/ff", "density:0xff", "page:0x3f", "sense:3/ff/ff"])
def test_unknown_is_not_guessed(code):
    result = explain(code)
    assert not result["known"]
    assert result["sources"]


@pytest.mark.parametrize("code", [
    "", "20", "sense:2/3a", "sense:12/3a/00", "asc:3a", "asc:3a/00/00",
    "page:-1", "page:256", "page:2e", "page:0x100", "tapealert:9999",
    "run:erase", "tapealert:20;ls", None, [], "x" * 65,
])
def test_bad_code_grammar(code):
    with pytest.raises(ValueError):
        explain(code)


def test_lookup_fixtures(fixtures):
    for line in (fixtures / "v4/explain-codes.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            assert explain(line)["sources"]


def arguments(fixtures):
    base = fixtures / "v4"
    return [
        ["explain", "tapealert:20"],
        ["log-decode", "--from-file", str(base / "log-0c.txt")],
        ["log-trend", "--from-file", str(base / "log-series.json")],
        ["inventory-diff", str(base / "inventory-before.txt"), str(base / "inventory-after.txt"), "--library-id", "SYNTH-LIB"],
        ["alert-history", str(base / "alerts-16.json"), str(base / "alerts-17.json")],
    ]


def test_all_commands_offline_and_html(fixtures, tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("offline command attempted process or network")
    monkeypatch.setattr("tapediag.safety.Runner.__init__", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    for argv in arguments(fixtures):
        output = tmp_path / (argv[0] + ".html")
        assert main(argv + ["--html", str(output)]) == 0
        result = json.loads(capsys.readouterr().out)
        assert isinstance(result, dict)
        assert "<!doctype html>" in output.read_text()


def test_execute_refused_before_input_or_output(fixtures, tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("refusal must precede input and Runner")
    monkeypatch.setattr("tapediag.offline_cli.read_capture", forbidden)
    monkeypatch.setattr("tapediag.safety.Runner.__init__", forbidden)
    for argv in arguments(fixtures):
        for candidate in (["--execute"] + argv, argv + ["--execute"]):
            output = tmp_path / "refused.html"
            assert main(candidate + ["--html", str(output)]) == 2
            assert "offline only" in json.loads(capsys.readouterr().err)["error"]
            assert not output.exists()


def test_html_cannot_run_capture_markup():
    content = evidence_html({"barcode": "SYNTH-</pre><script>alert(1)</script>&\""})
    assert "<script>" not in content
    assert "&lt;script&gt;" in content
    assert "default-src 'none'" in content
    assert "https://" not in content


@pytest.mark.parametrize("command", ["log-decode", "log-trend"])
def test_cli_bad_input_is_json_error(command, tmp_path, capsys):
    path = tmp_path / "bad.txt"
    path.write_text("not a capture")
    assert main([command, "--from-file", str(path)]) == 2
    assert "error" in json.loads(capsys.readouterr().err)


def test_input_error_does_not_expose_path(tmp_path, capsys):
    path = tmp_path / "missing"
    assert main(["log-decode", "--from-file", str(path)]) == 2
    assert str(path) not in capsys.readouterr().err


def test_history_rejects_duplicate_json_keys(tmp_path, capsys):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":"3.0","schema_version":"1.0"}')
    assert main(["alert-history", str(path), str(path)]) == 2
    assert "duplicate" in capsys.readouterr().err


def test_history_aggregate_input_limit(fixtures, monkeypatch, capsys):
    text = (fixtures / "v4/alerts-16.json").read_text()
    monkeypatch.setattr("tapediag.offline_cli.read_capture", lambda p: text + " " * (8 * 1024 * 1024))
    assert main(["alert-history", "one.json", "two.json"]) == 2
    assert "aggregate" in capsys.readouterr().err


def test_fuzz_regression_history_timestamp_cli(fixtures, tmp_path, capsys):
    report = json.loads((fixtures / "v4/alerts-16.json").read_text())
    report["captured_at"] = "0001-01-01T00:00:00+01:00"
    path = tmp_path / "overflow.json"
    path.write_text(json.dumps(report))
    assert main(["alert-history", str(path), str(path)]) == 2
    assert "UTC range" in capsys.readouterr().err
