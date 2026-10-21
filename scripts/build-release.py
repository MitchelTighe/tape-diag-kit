"""Build canonical wheel/sdist in a container, with an offline two-build check."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

from release_source import EPOCH, EXECUTABLES, canonical_tar, export, fingerprint, manifest


def normalize_sdist(path):
    rows = []
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError('non-regular sdist member')
            relative = member.name.split('/', 1)[-1]
            rows.append((member.name, archive.extractfile(member).read(), relative in EXECUTABLES))
    canonical_tar(rows, path)


def normalize_wheel(path):
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('duplicate wheel members')
        rows = [(name, archive.read(name)) for name in sorted(archive.namelist())]
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in rows:
            if name.startswith('/') or '..' in Path(name).parts or '\\' in name or any(ord(c) < 32 for c in name):
                raise ValueError('unsafe wheel name')
            item = zipfile.ZipInfo(name, time.gmtime(EPOCH)[:6])
            item.create_system = 3
            item.external_attr = 0o100644 << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build(root, destination, iteration):
    destination.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='tapediag-build-%d-' % iteration) as temporary:
        source = Path(temporary) / ('first' if iteration == 1 else 'different-path')
        source.mkdir()
        for row in manifest(root):
            target = source / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / row['path'], target)
            # Prove archive output ignores input filesystem metadata.
            target.chmod(0o755 if iteration == 1 else 0o644)
            os.utime(target, (EPOCH + iteration * 12345,) * 2)
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(EPOCH), PYTHONHASHSEED=str(iteration),
                   TZ='UTC' if iteration == 1 else 'Pacific/Honolulu', LC_ALL='C',
                   PYTHONDONTWRITEBYTECODE='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
        subprocess.run([sys.executable, '-m', 'build', '--no-isolation', '--outdir', str(destination)],
                       cwd=source, env=env, check=True)
    for path in destination.iterdir():
        if path.name.endswith('.tar.gz'):
            normalize_sdist(path)
        elif path.suffix == '.whl':
            normalize_wheel(path)
        else:
            raise ValueError('unexpected build artifact')
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.iterdir())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    before = fingerprint(root)
    with tempfile.TemporaryDirectory(prefix='tapediag-reproduction-') as temporary:
        temp = Path(temporary)
        first = build(root, temp / 'one', 1)
        second = build(root, temp / 'two', 2)
        if first != second or before != fingerprint(root):
            raise ValueError('reproducibility failed or source changed')
        for path in (temp / 'one').iterdir():
            shutil.copyfile(path, output / path.name)
    export(root, output / 'public-source.tar.gz')
    (output / 'source-manifest.json').write_text(json.dumps(manifest(root), indent=2) + '\n')
    (output / 'SHA256SUMS').write_text(''.join(digest + '  ' + name + '\n' for name, digest in sorted(first.items())))
    result = {'status': 'PASS', 'source_fingerprint': before, 'source_date_epoch': EPOCH,
              'builds_compared': 2, 'perturbations': ['path', 'mtime', 'mode', 'hash seed', 'timezone'],
              'normalization': 'sorted archive members; fixed timestamps, modes, ownership and gzip header',
              'sha256': first}
    (output / 'reproducibility.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
