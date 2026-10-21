"""Rejected candidates: existing guards challenged with synthetic fixtures."""
import io
import tarfile

import pytest

from tapediag.cli import main
from tapediag.dta_config import Refusal, load_config
from tapediag.dta_storage import Store, extract_collection
from tapediag.dta_vendor import xml_root
from tapediag.report import read_capture


@pytest.mark.parametrize('text', [
    '<!DOCTYPE inventory [<!ENTITY x "SYNTH">]><inventory>&x;</inventory>',
    '<!DOCTYPE inventory SYSTEM "https://example.invalid/index"><inventory/>',
    '<inventory>\x00</inventory>',
    '<inventory><drive>',
    '<?instruction SYNTH?><inventory/>',
    '\ufeff<!DOCTYPE inventory><inventory/>',
])
def test_vendor_xml_rejects_unsafe_or_truncated_input(text):
    with pytest.raises(Refusal):
        xml_root(text, 'inventory')


@pytest.mark.parametrize('raw', [b'\xff', b'\xef\xbb\xbfschema = 1', b'schema = 1\x00',
                                 b'schema = 1\nschema = 1', b'x' * 65537])
def test_config_refuses_invalid_encoding_and_size(tmp_path, raw):
    path = tmp_path / 'synthetic.toml'
    path.write_bytes(raw)
    with pytest.raises(Refusal):
        load_config(path)


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'nested/file'])
def test_store_refuses_traversal(tmp_path, name):
    with Store(tmp_path / 'run') as store:
        with pytest.raises(Refusal):
            store.write(name, 'SYNTH')


@pytest.mark.parametrize('name', ['../escape', '/results/SYNTH.log',
                                 'results/../SYNTH.log', 'results/nested/SYNTH.log'])
def test_collection_refuses_traversal(name):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as archive:
        entry = tarfile.TarInfo(name)
        entry.size = 5
        archive.addfile(entry, io.BytesIO(b'SYNTH'))
    with pytest.raises(Refusal):
        extract_collection(data.getvalue(), 'SYNTH')


def test_collection_refuses_truncated_payload():
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as archive:
        entry = tarfile.TarInfo('results/SYNTH.log')
        entry.size = 1024
        archive.addfile(entry, io.BytesIO(b'x' * 1024))
    with pytest.raises(Refusal):
        extract_collection(data.getvalue()[:600], 'SYNTH')


@pytest.mark.parametrize('timeout', ['nan', 'inf', '-inf', '0', '301'])
def test_cli_refuses_invalid_timeout(timeout):
    with pytest.raises(SystemExit) as exc:
        main(['logpages', '/dev/sg9', '--timeout', timeout])
    assert exc.value.code == 2


def test_capture_replaces_latin1_bytes(tmp_path):
    path = tmp_path / 'synthetic.txt'
    path.write_bytes(b'SYNTH caf\xe9')
    assert read_capture(path) == 'SYNTH caf\ufffd'


def test_capture_keeps_universal_newline_behavior(tmp_path):
    path = tmp_path / 'synthetic.txt'
    path.write_bytes(b'SYNTH\r\nline\rend\n')
    assert read_capture(path) == 'SYNTH\nline\nend\n'
