"""Explicit source selection for public exports; never consult Git metadata."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile


EPOCH = 1792281600  # 2026-10-18 00:00:00 UTC; stable release input.
ROOT_FILES = (
    'README.md', 'LICENSE', 'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md',
    'pyproject.toml', 'MANIFEST.in',
    'requirements-build.txt', 'requirements-dev.txt', 'requirements-lint.txt',
    'requirements-fedora-rpm.txt',
    'requirements-rocky-rpm.txt',
    'Containerfile', 'Containerfile.browser', 'Containerfile.lint',
    'Containerfile.release', 'Containerfile.distro', '.containerignore',
    '.gitignore', '.gitattributes', '.github/workflows/ci.yml', 'bin/tapediag',
    'bin/dta', 'config.example.toml',
)
SOURCE_DIRS = ('tapediag', 'schema', 'fixtures', 'tests', 'scripts', 'docs')
SUFFIXES = {'.py', '.sh', '.json', '.txt', '.md', '.html'}
EXECUTABLES = {'bin/tapediag', 'bin/dta'}
DTA_DATA = {'fixtures/dta/' + name for name in (
    'config.synthetic.toml', 'config.owner.synthetic.toml',
    'drive-list.xml', 'inventory-home.xml', 'inventory-loaded.xml')}
LTFS_DATA = {'fixtures/ltfs-index/' + name + '.xml' for name in (
    'minimal', 'overlap', 'shared', 'sparse', 'bad-extents', 'duplicate-names', 'deep')}


def supported_type(relative):
    path = Path(relative)
    return path.suffix in SUFFIXES or relative in DTA_DATA or relative in LTFS_DATA


def source_files(root):
    """Fail closed on links, special files and unexpected source types."""
    root = Path(root).resolve()
    paths = []
    for name in ROOT_FILES:
        path = root / name
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root and root in parent.parents):
            raise ValueError('symlink in release source: ' + name)
        if not path.is_file():
            raise ValueError('missing release input: ' + name)
        paths.append(path)
    for name in SOURCE_DIRS:
        base = root / name
        if base.is_symlink() or not base.is_dir():
            raise ValueError('missing or linked source directory: ' + name)
        for path in base.rglob('*'):
            if '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
                continue
            if path.is_symlink():
                raise ValueError('symlink in release source: ' + str(path.relative_to(root)))
            if path.is_dir():
                continue
            relative = path.relative_to(root).as_posix()
            if not re.fullmatch(r'[A-Za-z0-9_./-]+', relative) or any(part.startswith('.') for part in path.relative_to(base).parts):
                raise ValueError('unsupported or hidden source filename (redacted)')
            if not path.is_file() or not supported_type(relative):
                raise ValueError('unexpected release source type: ' + str(path.relative_to(root)))
            paths.append(path)
    selected = sorted(set(paths), key=lambda p: p.relative_to(root).as_posix())
    for path in selected:
        data = path.read_bytes()
        try:
            data.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError('binary source input refused') from None
        if b'\0' in data:
            raise ValueError('binary source input refused')
    return selected


def manifest(root):
    root = Path(root).resolve()
    return [{'path': p.relative_to(root).as_posix(), 'size': p.stat().st_size,
             'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in source_files(root)]


def fingerprint(root):
    data = json.dumps(manifest(root), sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(data).hexdigest()


def canonical_tar(rows, destination):
    """Rows are (safe relative name, bytes, executable); no host metadata."""
    rows = list(rows)
    if len(rows) != len({row[0] for row in rows}):
        raise ValueError('duplicate archive name')
    with open(destination, 'wb') as output:
        with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=EPOCH, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
                for name, data, executable in sorted(rows):
                    parts = Path(name).parts
                    if not parts or name.startswith('/') or '..' in parts or '\\' in name or any(ord(c) < 32 for c in name):
                        raise ValueError('unsafe archive name')
                    item = tarfile.TarInfo(name)
                    item.size = len(data)
                    item.mode = 0o755 if executable else 0o644
                    item.mtime = EPOCH
                    item.uid = item.gid = 0
                    item.uname = item.gname = ''
                    archive.addfile(item, io.BytesIO(data))


def export(root, destination):
    root = Path(root).resolve()
    rows = [(p.relative_to(root).as_posix(), p.read_bytes(), p.relative_to(root).as_posix() in EXECUTABLES)
            for p in source_files(root)]
    canonical_tar(rows, destination)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    export(args.root, args.output / 'public-source.tar.gz')
    (args.output / 'source-manifest.json').write_text(json.dumps(manifest(args.root), indent=2) + '\n')
    print('Public source export: %d files; SHA256 %s' % (len(manifest(args.root)), fingerprint(args.root)))
