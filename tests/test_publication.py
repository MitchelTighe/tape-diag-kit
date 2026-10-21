"""Release invariants tested with invented inputs; no Git mutation or hardware."""
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import sys
import tarfile
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import release_source as source


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load('build-release')
privacy = load('audit-public-source')
sbom = load('sbom')


def minimal_tree(root, monkeypatch):
    monkeypatch.setattr(source, 'ROOT_FILES', ('README.md',))
    monkeypatch.setattr(source, 'SOURCE_DIRS', ('tapediag',))
    (root / 'README.md').write_text('synthetic release\n')
    (root / 'tapediag').mkdir()
    (root / 'tapediag/test.py').write_text('print("synthetic")\n')


def test_export_is_deterministic_and_does_not_copy_history_or_artifacts(tmp_path, monkeypatch):
    minimal_tree(tmp_path, monkeypatch)
    for name in ('.git', 'artifacts', '.cache'):
        (tmp_path / name).mkdir()
        (tmp_path / name / 'private.txt').write_text('SYNTH-EXCLUDED')
    first, second = tmp_path / 'first.tgz', tmp_path / 'second.tgz'
    source.export(tmp_path, first)
    for path in source.source_files(tmp_path):
        os.utime(path, (1234567890, 1234567890))
        path.chmod(0o777)
    source.export(tmp_path, second)
    assert first.read_bytes() == second.read_bytes()
    assert gzip.decompress(first.read_bytes())
    with tarfile.open(first) as archive:
        assert archive.getnames() == ['README.md', 'tapediag/test.py']
        assert all(m.uid == m.gid == 0 and m.uname == m.gname == '' for m in archive.getmembers())
        assert {m.mtime for m in archive.getmembers()} == {source.EPOCH}


@pytest.mark.parametrize('location', ['root-file', 'nested-file', 'directory'])
def test_export_refuses_symlinks(tmp_path, monkeypatch, location):
    minimal_tree(tmp_path, monkeypatch)
    target = tmp_path / 'outside.txt'
    target.write_text('SYNTH-NOT-SELECTED')
    path = {'root-file': tmp_path / 'README.md', 'nested-file': tmp_path / 'tapediag/test.py',
            'directory': tmp_path / 'tapediag/link'}[location]
    if path.exists():
        path.unlink()
    path.symlink_to(target if location != 'directory' else tmp_path)
    with pytest.raises(ValueError, match='symlink'):
        source.export(tmp_path, tmp_path / 'source.tgz')


def test_export_refuses_unexpected_binary(tmp_path, monkeypatch):
    minimal_tree(tmp_path, monkeypatch)
    (tmp_path / 'tapediag/capture.png').write_bytes(b'SYNTH')
    with pytest.raises(ValueError, match='unexpected'):
        source.source_files(tmp_path)


@pytest.mark.parametrize('payload', [b'SYNTH\x00hidden', b'\xff\xfeSYNTH'])
def test_export_refuses_binary_disguised_as_text(tmp_path, monkeypatch, payload):
    minimal_tree(tmp_path, monkeypatch)
    (tmp_path / 'tapediag/test.py').write_bytes(payload)
    with pytest.raises(ValueError, match='binary source'):
        source.export(tmp_path, tmp_path / 'source.tgz')


@pytest.mark.parametrize('name', ['.hidden.md', 'synthetic@example.invalid.md'])
def test_export_refuses_hidden_or_sensitive_filenames_without_echoing(tmp_path, monkeypatch, name):
    minimal_tree(tmp_path, monkeypatch)
    (tmp_path / 'tapediag' / name).write_text('SYNTH')
    with pytest.raises(ValueError, match='redacted') as error:
        source.export(tmp_path, tmp_path / 'source.tgz')
    assert name not in str(error.value)


@pytest.mark.parametrize('unsafe', ['/absolute', '../escape', 'source/../escape', 'source\\escape'])
def test_canonical_archive_refuses_unsafe_names(tmp_path, unsafe):
    with pytest.raises(ValueError, match='unsafe'):
        source.canonical_tar([(unsafe, b'SYNTH', False)], tmp_path / 'bad.tgz')


def test_normalization_preserves_bytes_and_record(tmp_path):
    wheel = tmp_path / 'synthetic.whl'
    rows = {'synthetic/module.py': b'pass\n', 'synthetic.dist-info/RECORD': b'synthetic/module.py,sha256=synthetic,5\n'}
    with zipfile.ZipFile(wheel, 'w') as archive:
        for name, data in reversed(list(rows.items())):
            archive.writestr(name, data)
    build.normalize_wheel(wheel)
    first = wheel.read_bytes()
    build.normalize_wheel(wheel)
    assert first == wheel.read_bytes()
    with zipfile.ZipFile(wheel) as archive:
        assert archive.namelist() == sorted(rows)
        assert {n: archive.read(n) for n in archive.namelist()} == rows


def test_sdist_normalization_removes_host_metadata(tmp_path):
    sdist = tmp_path / 'synthetic.tgz'
    with tarfile.open(sdist, 'w:gz') as archive:
        info = tarfile.TarInfo('synthetic/README.md')
        info.size, info.uid, info.gid, info.uname, info.mtime = 5, 1001, 1002, 'SYNTH-USER', 12345
        archive.addfile(info, io.BytesIO(b'SYNTH'))
    build.normalize_sdist(sdist)
    before = sdist.read_bytes()
    build.normalize_sdist(sdist)
    assert sdist.read_bytes() == before
    with tarfile.open(sdist) as archive:
        assert archive.extractfile('synthetic/README.md').read() == b'SYNTH'
        assert archive.getmembers()[0].uname == ''


def test_sdist_normalization_refuses_links(tmp_path):
    sdist = tmp_path / 'synthetic.tgz'
    with tarfile.open(sdist, 'w:gz') as archive:
        info = tarfile.TarInfo('synthetic/link')
        info.type, info.linkname = tarfile.SYMTYPE, '../synthetic'
        archive.addfile(info)
    with pytest.raises(ValueError, match='non-regular'):
        build.normalize_sdist(sdist)


def test_canonical_archive_refuses_duplicate_names(tmp_path):
    with pytest.raises(ValueError, match='duplicate'):
        source.canonical_tar([('same', b'one', False), ('same', b'two', False)], tmp_path / 'bad.tgz')


def test_wheel_record_detects_content_corruption(tmp_path):
    audit_dist = load('check-dist-v3')
    wheel = tmp_path / 'test.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('tapediag/test.py', 'SYNTH-CORRUPTED')
        archive.writestr(audit_dist.DIST_INFO + 'RECORD', 'tapediag/test.py,sha256=synthetic,5\n' + audit_dist.DIST_INFO + 'RECORD,,\n')
    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(ValueError, match='hash/size'):
            audit_dist.wheel_record(archive)


def test_sbom_separates_build_inventory_and_hashes_wheel(tmp_path, monkeypatch):
    from types import SimpleNamespace
    wheel = tmp_path / 'tapediag.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('tapediag.dist-info/METADATA', 'Name: tapediag\nVersion: 0.3.0\nLicense-Expression: MIT\n')
    monkeypatch.setattr(sbom.importlib.metadata, 'distributions', lambda: [SimpleNamespace(metadata={'Name': 'SYNTH-Build-Tool'}, version='1.2.3')])
    monkeypatch.setattr(sbom.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='synthetic-os-package\t1.2.3\tx86_64\n'))
    image = 'sha256:' + 'a' * 64
    result = sbom.inventory(tmp_path, image)
    assert result == sbom.inventory(tmp_path, image)
    assert result == sbom.inventory(tmp_path, 'a' * 64)
    assert result['metadata']['component']['hashes'][0]['content'] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert result['dependencies'] == [{'ref': 'pkg:pypi/tapediag@0.3.0', 'dependsOn': []}]
    assert {c['scope'] for c in result['components']} == {'excluded'}
    assert any(c['version'] == image for c in result['components'])


def test_sbom_refuses_to_claim_zero_when_wheel_declares_dependency(tmp_path):
    wheel = tmp_path / 'tapediag.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('tapediag.dist-info/METADATA', 'Name: tapediag\nVersion: 0.3.0\nRequires-Dist: synthetic-dependency==1.2.3\nLicense-Expression: MIT\n')
    with pytest.raises(ValueError, match='unexpected runtime dependencies'):
        sbom.inventory(tmp_path, 'sha256:' + 'a' * 64)


def test_docs_mhvtl_block_matches_executable_verbatim():
    text = (ROOT / 'docs/INSTALL.md').read_text()
    block = text.split('<!-- mhvtl-quickstart-start -->')[1].split('<!-- mhvtl-quickstart-end -->')[0]
    block = block.split('```sh\n')[1].split('```')[0]
    script = (ROOT / 'scripts/mhvtl-quickstart.sh').read_text().split('# This exact block appears in docs/INSTALL.md; run from the source root.\n')[1]
    assert block == script


def test_only_licensed_ltfs_excerpt_remains(fixtures):
    entries = json.loads((fixtures / 'sources.json').read_text())['entries']
    assert [r['path'] for r in entries if r['kind'] == 'public-excerpt'] == ['public/ltfs-device-prefix.txt']
    assert all('LicenseRef-' not in r['license'] and not r['license'].startswith('GPL') for r in entries)
    assert sorted(p.name for p in (fixtures / 'public').iterdir()) == ['ltfs-device-prefix.txt']


def test_synthetic_replacements_have_independent_semantics(fixtures):
    from tapediag.parsers import parse_drive_status, parse_library, parse_inventory, parse_itdt
    assert parse_drive_status((fixtures / 'synthetic/inquiry-identity.txt').read_text())['product'] == 'SYNTH-DIAG-DRIVE'
    library = parse_library((fixtures / 'synthetic/library-legacy.txt').read_text())
    assert [s['element'] for s in library['slots']] == [7, 11, 15, 23]
    assert library['reported_slots'] is None and library['warnings']
    assert not parse_inventory((fixtures / 'synthetic/inventory-disk-only.txt').read_text())['devices']
    assert parse_itdt((fixtures / 'synthetic/itdt-no-records.txt').read_text())['warnings']


def test_reference_review_rejects_unknown_hosts_and_url_credentials():
    assert privacy.public_reference('See https://github.com/LinearTapeFileSystem/ltfs')
    assert not privacy.public_reference('See https://example.invalid/private')
    assert not privacy.public_reference('See https://synthetic:synthetic@github.com/project')


def test_line_dispositions_cannot_waive_new_candidates(tmp_path, monkeypatch):
    file = tmp_path / 'test.txt'
    old = 'synthetic@example.invalid'
    file.write_text(old + '\nnew-synthetic@example.invalid\n')
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/privacy-dispositions.json').write_text(json.dumps([
        {'path': 'test.txt', 'category': 'email', 'line_sha256': hashlib.sha256(old.encode()).hexdigest(), 'reason': 'Synthetic test'}]))
    (tmp_path / 'fixtures').mkdir()
    (tmp_path / 'fixtures/sources.json').write_text('{"entries": []}')
    monkeypatch.setattr(privacy, 'source_files', lambda root: [file])
    monkeypatch.setattr(privacy, 'fingerprint', lambda root: 'SYNTH')
    result = privacy.scan(tmp_path)
    assert result['status'] == 'REVIEW_REQUIRED' and result['unresolved'] == 1
    assert old not in json.dumps(result)


@pytest.mark.parametrize('image', ['latest', 'python:3.13.9', 'sha256:short', ''])
def test_sbom_rejects_mutable_or_missing_image_identity(tmp_path, image):
    with pytest.raises(ValueError, match='immutable'):
        sbom.inventory(tmp_path, image)


def test_current_source_privacy_has_no_undispositioned_candidates():
    result = privacy.scan(ROOT)
    assert result['unresolved'] == 0
    assert result['status'] == 'PASS'


def test_readiness_rejects_placeholders_until_filled(draft_release):
    release = load('check-release')
    _, errors = release.check(draft_release, ready=True)
    assert 'unresolved release placeholder: CONTRIBUTING.md' in errors
    for name in ('README.md', 'LICENSE', 'pyproject.toml', 'SECURITY.md', 'CONTRIBUTING.md'):
        path = draft_release / name
        path.write_text(re.sub(r'<[A-Z][A-Z0-9_]*>', 'SYNTH-APPROVED', path.read_text()))
    _, approved_errors = release.check(draft_release, ready=True)
    assert approved_errors == []


def test_public_docs_cannot_link_to_excluded_files(tmp_path):
    for path in source.source_files(ROOT):
        target = tmp_path / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    assert not (tmp_path / 'REPORT.md').exists()
    readme = tmp_path / 'README.md'
    readme.write_text(readme.read_text() + '\n[excluded report](REPORT.md)\n')
    release = load('check-release')
    _, errors = release.check(tmp_path)
    assert 'broken local link in README.md' in errors


@pytest.mark.parametrize('relative', [
    'fixtures/dta/config.synthetic.toml', 'fixtures/dta/config.owner.synthetic.toml',
    'fixtures/dta/drive-list.xml', 'fixtures/dta/inventory-home.xml', 'fixtures/dta/inventory-loaded.xml',
    'fixtures/ltfs-index/minimal.xml', 'fixtures/ltfs-index/deep.xml',
])
def test_export_keeps_reviewed_data(relative, tmp_path):
    destination = tmp_path / 'source.tgz'
    source.export(ROOT, destination)
    with tarfile.open(destination) as archive:
        assert archive.extractfile(relative).read() == (ROOT / relative).read_bytes()
        for launcher in ('bin/tapediag', 'bin/dta'):
            assert archive.getmember(launcher).mode == 0o755


@pytest.mark.parametrize('relative', [
    'tapediag/SYNTH.xml', 'tests/SYNTH.toml', 'fixtures/dta/SYNTH.dta.local.toml',
    'fixtures/dta/SYNTH.xml', 'fixtures/dta/SYNTH.toml',
    'fixtures/ltfs-index/SYNTH.xml', 'fixtures/ltfs-index/huge.xml',
])
def test_dta_data_support_does_not_allow_arbitrary_local_inputs(relative, tmp_path, monkeypatch):
    minimal_tree(tmp_path, monkeypatch)
    monkeypatch.setattr(source, 'SOURCE_DIRS', ('tapediag', 'tests', 'fixtures'))
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'fixtures').mkdir()
    file = tmp_path / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text('SYNTH')
    with pytest.raises(ValueError, match='unexpected release source type'):
        source.source_files(tmp_path)


@pytest.mark.parametrize('marker', [
    'python_version < "3.11" and extra == "dta"',
    'extra == "dta" and python_version < "3.11"',
])
def test_optional_dta_metadata_is_pinned_and_conditional(marker):
    from email.message import Message
    from release_metadata import optional_runtime
    metadata = Message()
    metadata['Requires-Dist'] = 'tomli==2.3.0; ' + marker
    metadata['Provides-Extra'] = 'dta'
    assert optional_runtime(metadata)[0]['scope'] == 'optional'


@pytest.mark.parametrize('requirement,extra', [
    ('tomli>=2.3.0; python_version < "3.11" and extra == "dta"', 'dta'),
    ('tomli==2.3.0', 'dta'),
    ('tomli==2.3.0; python_version < "3.11" or extra == "dta"', 'dta'),
    ('tomli==2.3.0; python_version < "3.12" and extra == "dta"', 'dta'),
    ('tomli==2.3.0; python_version < "3.11" and extra == "other"', 'dta'),
    ('tomli==2.3.0; python_version < "3.11" and extra == "dta"', 'other'),
    ('SYNTH-package==2.3.0; python_version < "3.11" and extra == "dta"', 'dta'),
])
def test_optional_metadata_rejects_unreviewed_dependencies(requirement, extra):
    from email.message import Message
    from release_metadata import optional_runtime
    metadata = Message()
    metadata['Requires-Dist'] = requirement
    metadata['Provides-Extra'] = extra
    with pytest.raises(ValueError, match='unexpected runtime dependencies'):
        optional_runtime(metadata)


def test_sbom_records_optional_extra_without_turning_build_packages_into_runtime(tmp_path, monkeypatch):
    wheel = tmp_path / 'tapediag.whl'
    metadata = ('Name: tapediag\nVersion: 0.3.0\nLicense-Expression: MIT\n'
                'Provides-Extra: dta\nRequires-Dist: tomli==2.3.0; python_version < "3.11" and extra == "dta"\n')
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('tapediag.dist-info/METADATA', metadata)
    from types import SimpleNamespace
    monkeypatch.setattr(sbom.importlib.metadata, 'distributions', lambda: [])
    monkeypatch.setattr(sbom.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=''))
    result = sbom.inventory(tmp_path, 'sha256:' + 'a' * 64)
    optional = [c for c in result['components'] if c['scope'] == 'optional']
    assert len(optional) == 1 and optional[0]['bom-ref'] == 'pkg:pypi/tomli@2.3.0'
    assert optional[0]['properties'] == [
        {'name': 'tapediag:extra', 'value': 'dta'},
        {'name': 'tapediag:pep508-marker', 'value': 'python_version < "3.11" and extra == "dta"'},
    ]
    assert result['dependencies'][0]['dependsOn'] == ['pkg:pypi/tomli@2.3.0']
    assert all(c['scope'] == 'excluded' for c in result['components'] if c not in optional)


def test_normalized_sdist_keeps_both_source_launchers_executable(tmp_path):
    sdist = tmp_path / 'synthetic.tgz'
    source.canonical_tar([('synthetic/' + name, b'SYNTH\n', False)
                          for name in ('bin/dta', 'bin/tapediag', 'README.md')], sdist)
    build.normalize_sdist(sdist)
    with tarfile.open(sdist) as archive:
        for name in ('bin/dta', 'bin/tapediag'):
            assert archive.getmember('synthetic/' + name).mode == 0o755
        assert archive.getmember('synthetic/README.md').mode == 0o644


@pytest.mark.parametrize('damage', ['required', 'condition', 'graph', 'version'])
def test_sbom_checker_rejects_optional_inventory_or_graph_drift(damage):
    checker = load('check-sbom')
    from release_metadata import DTA_REQUIREMENT
    optional = {'name': 'tomli', 'version': '2.3.0', 'bom-ref': 'pkg:pypi/tomli@2.3.0',
                'purl': 'pkg:pypi/tomli@2.3.0', 'scope': 'optional', 'properties': [
                    {'name': 'tapediag:extra', 'value': 'dta'},
                    {'name': 'tapediag:pep508-marker', 'value': DTA_REQUIREMENT.split('; ', 1)[1]}]}
    value = {'metadata': {'component': {'bom-ref': 'pkg:pypi/tapediag@0.3.0'}},
             'components': [optional], 'dependencies': [
                 {'ref': 'pkg:pypi/tapediag@0.3.0', 'dependsOn': ['pkg:pypi/tomli@2.3.0']},
                 {'ref': 'pkg:pypi/tomli@2.3.0', 'dependsOn': []}]}
    checker.validate_inventory(value)
    if damage == 'required':
        optional['scope'] = 'required'
    elif damage == 'condition':
        optional['properties'][1]['value'] = 'extra == "dta"'
    elif damage == 'graph':
        value['dependencies'][0]['dependsOn'] = []
    else:
        optional['version'] = 'SYNTH'
    with pytest.raises(AssertionError):
        checker.validate_inventory(value)
