#!/bin/sh
set -eu
cd /tmp
python --version
tapediag --version
python /src/scripts/smoke-installed.py
python /src/scripts/smoke-installed-dta.py
cd /src
pytest -q
python scripts/check-dist-v3.py --dist /dist
mkdir /tmp/tapediag-sdist
tar -xzf /dist/tapediag-0.3.0.tar.gz -C /tmp/tapediag-sdist
cd /tmp/tapediag-sdist/tapediag-0.3.0
pytest -q
cd /src
PYTHONPATH=. python scripts/verify-v3.py
python scripts/audit-identifiers.py
sh scripts/mhvtl-quickstart.sh
python scripts/audit-public-source.py --output /tmp/privacy-source.json
