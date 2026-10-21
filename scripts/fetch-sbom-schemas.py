"""Fetch only hash-pinned public CycloneDX 1.6 validation data into scratch."""
import argparse
import hashlib
from pathlib import Path
from urllib.request import urlopen


BASE = 'https://raw.githubusercontent.com/CycloneDX/specification/1.6/schema/'
PINS = {
    'bom-1.6.schema.json': '3e92dddbc30cf7f6a02b80f0942b1a4cfd4fb1c26f1dfc4310afa9d613cafb93',
    'spdx.schema.json': 'baa9d3bd1ed57b6751b0887edead6b5063ff53ff7429cf85d476c6c94af0166e',
    'jsf-0.82.schema.json': '8bae002c25e723db7ee1f26afde680ae1a2b1a8f6b4b4b0fd65dc3becb090aae',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    verified = {}
    for name, expected in PINS.items():
        with urlopen(BASE + name, timeout=30) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('public schema hash/size mismatch: ' + name)
        verified[name] = data
    for name, data in verified.items():
        (args.output / name).write_bytes(data)
    print('Pinned CycloneDX 1.6 schema download: 3/3 SHA256 checks PASS')


if __name__ == '__main__':
    main()
