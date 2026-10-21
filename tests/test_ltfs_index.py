"""Original synthetic LTFS fixtures; no media or site records."""
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tapediag.cli import main
from tapediag.ltfs_index import IndexRefusal, Limits, validate_index


spec = importlib.util.spec_from_file_location('generate_ltfs', Path(__file__).resolve().parents[1] / 'scripts/generate-ltfs-index.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


@pytest.fixture
def index(tmp_path):
    path = tmp_path / 'synthetic.xml'
    generator.generate(path)
    return path


def edit(path, before, after):
    text = path.read_text()
    assert before in text
    path.write_text(text.replace(before, after), encoding='utf-8')


def check(path, **kwargs):
    return validate_index(path, scratch_dir=path.parent, **kwargs)


@pytest.mark.parametrize('case,valid,code', [
    ('minimal', True, None), ('overlap', False, 'LTFS_EXTENT_OVERLAP'),
    ('shared', True, 'LTFS_SHARED_EXTENT'), ('sparse', True, 'LTFS_SPARSE'),
    ('bad-extents', False, 'LTFS_EXTENT_VALUE'), ('duplicate-names', False, 'LTFS_NAME_DUPLICATE'),
])
def test_generated(index, case, valid, code):
    generator.generate(index, case)
    result = check(index, block_size=1024)
    assert result['valid'] is valid
    if code:
        assert code in result['finding_counts']
    assert list(index.parent.iterdir()) == [index]


@pytest.mark.parametrize('before,after,code', [
    ('<fileuid>2', '<fileuid>1', 'LTFS_UID'),
    ('<fileuid>1', '<fileuid>2', 'LTFS_UID_DUPLICATE'),
    ('<highestfileuid>2', '<highestfileuid>99', 'LTFS_HIGHEST_UID'),
    ('<generationnumber>1', '<generationnumber>0', 'LTFS_GENERATION'),
    (generator.UUID, 'not-a-uuid', 'LTFS_UUID'),
    (generator.STAMP, '2026-02-30T03:04:05.000000000Z', 'LTFS_TIMESTAMP'),
    (generator.STAMP, '2026-01-02T03:04:05Z', 'LTFS_TIMESTAMP'),
    ('<length>0</length>', '<length>0</length><extentinfo/><symlink>target</symlink>', 'LTFS_SYMLINK_EXTENTS'),
    ('<length>0</length>', '<length>-1</length>', 'LTFS_FILE_LENGTH'),
    ('<length>0</length>', '<length>18446744073709551616</length>', 'LTFS_FILE_LENGTH'),
    ('<length>0</length>', '<length>0</length><length>1</length>', 'LTFS_ELEMENT_DUPLICATE'),
    ('<name>empty</name>', '<name>bad/name</name>', 'LTFS_NAME'),
    ('<name>empty</name>', '<name percentencoded="true">bad%zz</name>', 'LTFS_NAME'),
    ('<name>empty</name>', '<name>e\u0301</name>', 'LTFS_NAME'),
    ('<readonly>false</readonly>', '', 'LTFS_REQUIRED'),
    ('<readonly>false</readonly>', '<readonly>1</readonly>', 'LTFS_BOOLEAN'),
])
def test_findings(index, before, after, code):
    edit(index, before, after)
    result = check(index)
    assert not result['valid']
    assert code in result['finding_counts']


@pytest.mark.parametrize('value', ['-1', '0', '1.5', '18446744073709551616', '9' * 5000])
def test_bad_bytecount(index, value):
    generator.generate(index, 'shared')
    edit(index, '<bytecount>8', '<bytecount>' + value)
    assert 'LTFS_EXTENT_VALUE' in check(index)['finding_counts']


@pytest.mark.parametrize('field,value', [('startblock', '-1'), ('fileoffset', '-1'),
                                         ('byteoffset', '-1'), ('byteoffset', '1024'), ('partition', 'A')])
def test_extent_sanity(index, field, value):
    generator.generate(index, 'shared')
    import re
    index.write_text(re.sub('<' + field + '>[^<]+', '<' + field + '>' + value, index.read_text()))
    assert not check(index, block_size=1024)['valid']


def test_sparse_empty_and_unsorted_adjacency(index):
    edit(index, '<length>0</length>', '<length>99</length>')
    assert check(index)['finding_counts']['LTFS_SPARSE'] == 1
    generator.generate(index, 'overlap')
    edit(index, generator.extent() + generator.extent(offset=4, block=20),
         generator.extent(offset=8) + generator.extent(offset=0, block=20))
    result = check(index)
    assert result['valid']
    assert 'LTFS_SPARSE' not in result['finding_counts']


def test_past_eof(index):
    generator.generate(index, 'shared')
    edit(index, '<length>8', '<length>7')
    assert check(index)['finding_counts']['LTFS_EXTENT_PAST_EOF'] == 2


def test_physical_partitions_and_adjacent_bytes(index):
    generator.generate(index, 'shared')
    text = index.read_text()
    first, second = text.split('<fileuid>3')
    index.write_text(first + '<fileuid>3' + second.replace('<partition>b', '<partition>a'))
    assert 'LTFS_SHARED_EXTENT' not in check(index, block_size=1024)['finding_counts']
    index.write_text(first + '<fileuid>3' + second.replace('<byteoffset>0', '<byteoffset>8'))
    assert 'LTFS_SHARED_EXTENT' not in check(index, block_size=1024)['finding_counts']


@pytest.mark.parametrize('block,valid', [(99, True), (100, False), (101, False)])
def test_previous_location(index, block, valid):
    pointer = '<previousgenerationlocation><partition>b</partition><startblock>%d</startblock></previousgenerationlocation>' % block
    edit(index, '<allowpolicyupdate>', pointer + '<allowpolicyupdate>')
    assert check(index)['valid'] is valid


def test_first_generation_cross_partition_backpointer_valid(index):
    # A generation-1 index-partition copy may point to generation 1 on data.
    pointer = '<previousgenerationlocation><partition>a</partition><startblock>100</startblock></previousgenerationlocation>'
    edit(index, '<allowpolicyupdate>', pointer + '<allowpolicyupdate>')
    assert check(index)['valid']


def test_case_and_decoded_names(index):
    generator.generate(index, 'duplicate-names')
    text = index.read_text().replace('<name>duplicate</name>', '<name>Duplicate</name>', 1)
    index.write_text(text)
    assert check(index)['valid']
    index.write_text(text.replace('<name>Duplicate</name>', '<name percentencoded="true">%64uplicate</name>'))
    assert 'LTFS_NAME_DUPLICATE' in check(index)['finding_counts']


@pytest.mark.parametrize('prefix', [
    '<!DOCTYPE ltfsindex>', '<!DOCTYPE ltfsindex [<!ENTITY x "expanded">]>',
    '<!DOCTYPE ltfsindex SYSTEM "urn:synthetic:unresolved">',
    '\ufeff<!DOCTYPE ltfsindex>', ' ' * 16380 + '<!DOCTYPE ltfsindex>',
])
def test_declarations_refused(index, prefix):
    edit(index, '<?xml version="1.0" encoding="UTF-8"?>', prefix)
    with pytest.raises(IndexRefusal, match='LTFS_XML_DECLARATION'):
        check(index)


@pytest.mark.parametrize('payload', [b'<ltfsindex', b'\xff', '<ltfsindex/>'.encode('utf-16'),
                                    b'<ltfsindex>&unknown;</ltfsindex>'])
def test_malformed(index, payload):
    index.write_bytes(payload)
    with pytest.raises(IndexRefusal, match='LTFS_XML'):
        check(index)


@pytest.mark.parametrize('limit,value,code', [
    ('max_bytes', 100, 'BYTES'), ('max_elements', 4, 'ELEMENTS'),
    ('max_depth', 2, 'DEPTH'), ('max_text_chars', 4, 'TEXT'),
    ('max_disk_bytes', 4096, 'SCRATCH'),
])
def test_limits(index, limit, value, code):
    with pytest.raises(IndexRefusal, match=code):
        check(index, limits=replace(Limits(), **{limit: value}))


def test_attribute_limit(index):
    edit(index, '<file>', '<file ' + ' '.join('a%d="x"' % i for i in range(17)) + '>')
    with pytest.raises(IndexRefusal, match='ATTRIBUTES'):
        check(index)


@pytest.mark.parametrize('token', ['<!--' + 'x' * 100000, '<file attribute="' + 'x' * 100000])
def test_unfinished_tokens(index, token):
    index.write_text(token)
    with pytest.raises(IndexRefusal, match='TOKEN'):
        check(index, limits=replace(Limits(), max_token_bytes=32768))


def test_depth(index):
    generator.generate(index, 'deep')
    with pytest.raises(IndexRefusal, match='DEPTH'):
        check(index)
    generator.generate(index, 'deep', depth=10)
    assert check(index)['directories'] == 11


def test_findings_cap(index):
    generator.generate(index, 'bad-extents')
    result = check(index, limits=replace(Limits(), max_findings=1))
    assert len(result['findings']) == 1 and result['findings_truncated']
    assert result['errors'] >= 3


def test_uint64(index):
    edit(index, '<fileuid>2', '<fileuid>18446744073709551615')
    edit(index, '<highestfileuid>2', '<highestfileuid>18446744073709551615')
    assert check(index)['valid']


def test_cli(index, capsys):
    assert main(['ltfs-index', '--from-file', str(index), '--scratch-dir', str(index.parent)]) == 0
    assert json.loads(capsys.readouterr().out)['document_type'] == 'ltfs-index'
    generator.generate(index, 'overlap')
    assert main(['ltfs-index', '--from-file', str(index)]) == 1
    assert not json.loads(capsys.readouterr().out)['valid']
    assert main(['ltfs-index', '--from-file', str(index), '--execute']) == 2
    assert 'offline' in capsys.readouterr().err
    index.write_text('<bad')
    assert main(['ltfs-index', '--from-file', str(index)]) == 2
    assert str(index) not in capsys.readouterr().err


def test_nonregular_and_missing(index):
    for path in (index.parent, index.parent / 'missing'):
        with pytest.raises(IndexRefusal):
            check(path)
    fifo = index.parent / 'fifo'
    os.mkfifo(fifo)
    with pytest.raises(IndexRefusal, match='regular'):
        check(fifo)


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get('LTFS_RUN_SLOW') != '1', reason='set LTFS_RUN_SLOW=1 for the 2M-file resource test')
def test_huge_index_bounded_resources(tmp_path):
    # A child process gives independent peak RSS. Both 100k and 2M have extents;
    # the second index exceeds 2 GiB and is generated on disk, not held in RAM.
    runner = Path(__file__).resolve().parents[1] / 'scripts/measure-ltfs-index.py'
    measurements = []
    for files in (100_000, 2_000_000):
        output = subprocess.run([sys.executable, str(runner), '--files', str(files), '--scratch-dir', str(tmp_path)],
                                capture_output=True, text=True, timeout=1800, check=True)
        row = json.loads(output.stdout)
        print(json.dumps(row, sort_keys=True), flush=True)
        assert row['valid'] and row['files'] == files
        assert row['peak_rss_kib'] < 256 * 1024
        assert row['validation_seconds'] < 1200
        measurements.append(row)
    assert measurements[1]['input_bytes'] > 2 * 1024 ** 3
    assert measurements[1]['peak_rss_kib'] <= measurements[0]['peak_rss_kib'] + 64 * 1024


def test_previous_index_pair(index):
    previous = index.parent / 'previous.xml'
    previous.write_bytes(index.read_bytes())
    edit(index, '<generationnumber>1', '<generationnumber>3')
    edit(index, '<startblock>100', '<startblock>200')
    edit(index, '<allowpolicyupdate>',
         '<previousgenerationlocation><partition>b</partition><startblock>100</startblock></previousgenerationlocation><allowpolicyupdate>')
    assert check(index, previous_index=previous)['valid']
    edit(previous, '<generationnumber>1', '<generationnumber>4')
    assert 'LTFS_PREVIOUS_GENERATION' in check(index, previous_index=previous)['finding_counts']
    edit(previous, '<startblock>100', '<startblock>99')
    edit(previous, generator.UUID, '00000000-0000-4000-8000-000000000133')
    result = check(index, previous_index=previous)
    assert {'LTFS_PREVIOUS_TARGET', 'LTFS_PREVIOUS_UUID'} <= result['finding_counts'].keys()


def test_version_24(index):
    edit(index, 'version="2.5.0"', 'version="2.4.0"')
    assert check(index)['valid']


@pytest.mark.parametrize('change', ['<ltfsincrementalindex version="2.5.0"/>',
                                   '<ltfsindex version="9.0.0"/>',
                                   '<ltfsindex version="2.5.0"><file/></ltfsindex>'])
def test_unsupported_structure(index, change):
    index.write_text(change)
    with pytest.raises(IndexRefusal, match='LTFS_INDEX_TYPE|LTFS_STRUCTURE'):
        check(index)


def test_no_directory(index):
    index.write_text('<ltfsindex version="2.5.0"/>')
    assert not check(index)['valid']


def test_complete_comment_limit(index):
    edit(index, '<file>', '<!--' + 'x' * 10000 + '--><file>')
    with pytest.raises(IndexRefusal, match='TOKEN'):
        check(index, limits=replace(Limits(), max_token_bytes=1024))


def test_scratch_cleanup_on_parse_failure(index):
    edit(index, '</ltfsindex>', '')
    with pytest.raises(IndexRefusal):
        check(index)
    assert list(index.parent.iterdir()) == [index]


def test_read_limits_ignore_stale_stat(index, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(Path, 'stat', lambda self: SimpleNamespace(st_mode=0o100644, st_size=1))
    with pytest.raises(IndexRefusal, match='BYTES'):
        check(index, limits=replace(Limits(), max_bytes=100))


@pytest.mark.parametrize('case', [case for case in generator.CASES if case != 'huge'])
def test_saved_fixtures_reproduce(index, case):
    generator.generate(index, case)
    saved = Path(__file__).resolve().parents[1] / 'fixtures/ltfs-index' / (case + '.xml')
    assert index.read_bytes() == saved.read_bytes()
