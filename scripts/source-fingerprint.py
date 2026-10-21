"""Fingerprint every explicitly selected public release input."""
from pathlib import Path
from release_source import fingerprint, manifest
root = Path(__file__).resolve().parents[1]
print('Source fingerprint SHA256: %s (%d files)' % (fingerprint(root), len(manifest(root))))
