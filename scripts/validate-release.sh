#!/bin/sh
set -eu
# Mount public source at /input:ro and task output at /out:rw. No devices/network.
python /input/scripts/release_source.py --root /input --output /tmp/public-input
mkdir /tmp/source
tar -xzf /tmp/public-input/public-source.tar.gz -C /tmp/source
if test -d /baseline; then
    cp -R /baseline/. /tmp/pr1-baseline
    cd /tmp/pr1-baseline
    echo 'Standalone PR 1 baseline suite'
    python -m pytest -q -p no:cacheprovider --basetemp=/tmp/pr1-tests
fi
cd /tmp/source
python --version
python -m pip check
python scripts/source-fingerprint.py
ruff check --no-cache .
python scripts/check-release.py
python scripts/audit-public-source.py --output /out/privacy-source.json
python -m pytest -q -p no:cacheprovider --basetemp=/tmp/source-tests
python scripts/build-release.py --output /out
python scripts/check-dist-v3.py --dist /out
python -m pip install --no-index --no-deps /out/*.whl
cd /tmp
python /tmp/source/scripts/smoke-installed.py
python /tmp/source/scripts/smoke-installed-dta.py
mkdir /tmp/sdist
tar -xzf /out/tapediag-0.3.0.tar.gz -C /tmp/sdist
cd /tmp/sdist/tapediag-0.3.0
python -m pytest -q -p no:cacheprovider --basetemp=/tmp/sdist-tests
python scripts/check-release.py
PYTHONPATH=. python scripts/verify-v3.py
python scripts/audit-identifiers.py
mkdir /tmp/dta-scratch
python scripts/verify-dta.py --scratch /tmp/dta-scratch
python scripts/verify-dta.py --owner-adapter --scratch /tmp/dta-scratch --output artifacts/dta/owner
cp -R artifacts/dta /out/dta
sh scripts/mhvtl-quickstart.sh
mkdir -p /out/quickstart
cp -R artifacts/mhvtl /out/quickstart/
cp artifacts/v3/quickstart.html artifacts/v3/quickstart.json /out/quickstart/
python scripts/sbom.py --dist /out --image "${BUILD_IMAGE:?set immutable BUILD_IMAGE}" --output /out/sbom.cdx.json
python scripts/check-sbom.py --schema-dir /schemas /out/sbom.cdx.json
cd /out
sha256sum tapediag-0.3.0-py3-none-any.whl tapediag-0.3.0.tar.gz public-source.tar.gz source-manifest.json reproducibility.json sbom.cdx.json > SHA256SUMS
sha256sum -c SHA256SUMS
echo 'Release validation: PASS'
