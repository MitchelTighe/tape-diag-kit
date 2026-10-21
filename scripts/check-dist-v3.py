"""Check every distribution member, exact source bytes and wheel RECORD."""
import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile

from release_source import manifest
from release_metadata import optional_runtime


VERSION = '0.3.0'
DIST_INFO = 'tapediag-' + VERSION + '.dist-info/'
SDIST_PREFIX = 'tapediag-' + VERSION + '/'


def wheel_record(archive):
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError('duplicate wheel member')
    rows = list(csv.reader(io.StringIO(archive.read(DIST_INFO + 'RECORD').decode())))
    if len(rows) != len(names) or {r[0] for r in rows} != set(names):
        raise ValueError('RECORD member coverage')
    for name, digest, size in rows:
        if name == DIST_INFO + 'RECORD':
            if digest or size:
                raise ValueError('RECORD must not hash itself')
            continue
        data = archive.read(name)
        expected = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        if digest != expected or size != str(len(data)):
            raise ValueError('RECORD hash/size mismatch: ' + name)


def inspect(root, dist):
    selected = {row['path']: row for row in manifest(root)}
    wheel = dist / ('tapediag-' + VERSION + '-py3-none-any.whl')
    sdist = dist / ('tapediag-' + VERSION + '.tar.gz')
    with zipfile.ZipFile(wheel) as archive:
        wheel_record(archive)
        expected = {name for name in selected if name.startswith('tapediag/')}
        expected |= {DIST_INFO + 'licenses/' + name for name in ('LICENSE', 'fixtures/NOTICES.md')}
        generated = {DIST_INFO + name for name in ('METADATA', 'WHEEL', 'entry_points.txt', 'top_level.txt', 'RECORD')}
        if set(archive.namelist()) != expected | generated:
            raise ValueError('unexpected or missing wheel members')
        for name in expected:
            relative = name.removeprefix(DIST_INFO + 'licenses/') if name.startswith(DIST_INFO) else name
            if archive.read(name) != (root / relative).read_bytes():
                raise ValueError('wheel source mismatch: ' + relative)
        metadata = BytesParser().parsebytes(archive.read(DIST_INFO + 'METADATA'))
        optional = optional_runtime(metadata)
        if metadata['Requires-Python'] != '>=3.9' or len(optional) != 1:
            raise ValueError('runtime dependency/python metadata')
        entrypoints = archive.read(DIST_INFO + 'entry_points.txt').decode()
        if 'dta = tapediag.dta:main' not in entrypoints or 'tapediag = tapediag.cli:main' not in entrypoints:
            raise ValueError('console entry point metadata')
        if metadata['License-Expression'] != 'MIT':
            raise ValueError('licence metadata')
        if set(metadata.get_all('License-File')) != {'LICENSE', 'fixtures/NOTICES.md'}:
            raise ValueError('licence notice metadata')
        wheel_count = len(archive.namelist())
    generated_sdist = {'PKG-INFO', 'setup.cfg'} | {'tapediag.egg-info/' + name for name in
                       ('PKG-INFO', 'SOURCES.txt', 'dependency_links.txt', 'entry_points.txt', 'top_level.txt', 'requires.txt')}
    with tarfile.open(sdist, 'r:gz') as archive:
        members = [m for m in archive.getmembers() if not m.isdir()]
        if len(members) != len({m.name for m in members}):
            raise ValueError('duplicate sdist member')
        if any(not m.isfile() for m in members):
            raise ValueError('non-regular sdist member')
        names = {m.name for m in members}
        if not names <= {SDIST_PREFIX + name for name in set(selected) | generated_sdist}:
            raise ValueError('unexpected sdist member')
        sources = archive.extractfile(SDIST_PREFIX + 'tapediag.egg-info/SOURCES.txt').read().decode().splitlines()
        if not set(sources) <= set(selected) | generated_sdist:
            raise ValueError('unexpected or absolute SOURCES.txt entry')
        for relative in selected:
            name = SDIST_PREFIX + relative
            if name not in names or archive.extractfile(name).read() != (root / relative).read_bytes():
                raise ValueError('sdist missing/source mismatch: ' + relative)
        sdist_count = len(members)
    return {'status': 'PASS', 'wheel_files': wheel_count, 'sdist_files': sdist_count,
            'source_files_compared': len(selected), 'runtime_dependencies': 0,
            'optional_dta_dependencies': len(optional),
            'wheel_record': 'all member hashes/sizes verified',
            'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wheel, sdist)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(Path(__file__).resolve().parents[1], args.dist), indent=2))


if __name__ == '__main__':
    main()
