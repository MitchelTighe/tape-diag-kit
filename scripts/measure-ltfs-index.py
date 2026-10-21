#!/usr/bin/env python3
"""Linux resource probe: generate, validate, measure and remove a synthetic index."""
import argparse
import importlib.util
import json
from pathlib import Path
import resource
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tapediag.ltfs_index import validate_index  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--files', type=int, default=2_000_000)
    parser.add_argument('--scratch-dir', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('generate_ltfs', Path(__file__).with_name('generate-ltfs-index.py'))
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    with tempfile.TemporaryDirectory(prefix='ltfs-measure-', dir=args.scratch_dir) as directory:
        path = Path(directory) / 'huge.xml'
        start = time.monotonic()
        generator.generate(path, 'huge', files=args.files)
        generation_seconds = time.monotonic() - start
        start = time.monotonic()
        result = validate_index(path, block_size=1024, scratch_dir=directory)
        print(json.dumps({'files': result['files'], 'valid': result['valid'], 'input_bytes': path.stat().st_size,
                          'generation_seconds': round(generation_seconds, 3),
                          'validation_seconds': round(time.monotonic() - start, 3),
                          'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
        return 0 if result['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
