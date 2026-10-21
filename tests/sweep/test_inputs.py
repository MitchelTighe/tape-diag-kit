"""Adversarial regressions using only generated synthetic input."""
import json
from pathlib import Path

import pytest

from tapediag.cli import main
from tapediag.dta import main as dta_main
from tapediag.parsers import parse_drive_status, parse_logpages
from tapediag.report import read_capture


def test_failed_tur_is_not_ready():
    assert parse_drive_status("sg_turs: unsuccessful")['ready'] is not True


def test_successful_tur_wording_still_ready():
    assert parse_drive_status("test unit ready completed successfully")['ready'] is True


def test_overflowing_log_decimal_remains_raw():
    raw = "9" * 400 + ".0"
    result = parse_logpages("Temperature [0x0d]:\nTemperature: " + raw)
    parameter = result['pages'][0]['parameters'][0]
    assert parameter['value'] == raw
    json.dumps(result, allow_nan=False)


def test_capture_size_is_checked_on_read(tmp_path, monkeypatch):
    path = tmp_path / "growing.txt"
    limit = 16 * 1024 * 1024
    path.write_bytes(b"x" * (limit + 1))
    original = Path.stat

    def stale_size(self, *args, **kwargs):
        info = original(self, *args, **kwargs)
        if self == path:
            # Model a capture growing after the metadata check.
            import os
            values = list(info)
            values[6] = 0
            return os.stat_result(values)
        return info

    monkeypatch.setattr(Path, 'stat', stale_size)
    with pytest.raises(ValueError, match="16 MiB"):
        read_capture(path)


def test_capture_error_withholds_local_path(tmp_path, capsys):
    path = tmp_path / "SYNTH-private-directory" / "missing.txt"
    assert main(['logpages', '--from-file', str(path)]) == 2
    error = capsys.readouterr().err
    assert str(path) not in error


def test_deep_saved_json_is_controlled_error(tmp_path, capsys):
    path = tmp_path / 'deep.json'
    path.write_text('[' * 2000 + '0' + ']' * 2000)
    assert main(['validate', '--from-file', str(path)]) == 2
    assert 'Traceback' not in capsys.readouterr().err


@pytest.mark.parametrize('state', [[], None, 1, 'SYNTH'])
def test_resume_nonobject_is_controlled_error(tmp_path, dta_fixtures, capsys, state):
    (tmp_path / 'state.json').write_text(json.dumps(state))
    assert dta_main(['--config', str(dta_fixtures / 'config.synthetic.toml'),
                     '--resume', '--output', str(tmp_path)]) == 2
    assert 'REFUSED:' in capsys.readouterr().out


@pytest.mark.parametrize('case', ['missing-directory', 'missing-capture', 'output'])
def test_report_errors_withhold_local_paths(tmp_path, capsys, case):
    path = tmp_path / 'SYNTH-private-directory'
    if case == 'output':
        args = ['dashboard', '--output', str(path / 'report.html')]
        expected = 2
    else:
        if case == 'missing-capture':
            path.mkdir()
        args = ['report', '--schema-version', '1.0', '--from-dir', str(path)]
        expected = 1 if case == 'missing-capture' else 2
    assert main(args) == expected
    captured = capsys.readouterr()
    assert str(path) not in captured.out + captured.err


def test_deep_resume_json_is_controlled_error(tmp_path, dta_fixtures, capsys):
    (tmp_path / 'state.json').write_text('[' * 2000 + '0' + ']' * 2000)
    assert dta_main(['--config', str(dta_fixtures / 'config.synthetic.toml'),
                     '--resume', '--output', str(tmp_path)]) == 2
    assert 'REFUSED:' in capsys.readouterr().out
