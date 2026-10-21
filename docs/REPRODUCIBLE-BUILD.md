# Reproducible release build

The public input is selected by `scripts/release_source.py`, not by a broad
archive of the checkout. It includes code, synthetic fixtures, tests, docs and
pinned container/build inputs, and rejects links or unexpected file types.
It excludes `.git`, generated artifacts, caches, local configuration and scratch.
The manifest hashes every selected file. No historical identity is rewritten.

The canonical release pipeline uses `SOURCE_DATE_EPOCH=1792281600` (2026-10-18
00:00:00 UTC). Setuptools 80.9.0 builds the sdist and its wheel with build 1.3.0,
wheel 0.45.1 and pinned supporting packages. The release script then normalizes
archive ordering/timestamps/modes/ownership, ZIP metadata and the gzip header.
This normalization is part of the build; raw setuptools archives are not claimed
to be reproducible. Wheel member bytes and RECORD hashes remain unchanged.

The two builds use clean temporary directories and vary source path, mtime,
mode, Python hash seed and time zone. Both normalized wheel and sdist must match
byte for byte; the script fails if source bytes change during the check.
The wheel is built from its sdist by the standard build frontend. Test both the
selected source and the exact sdist independently on Python 3.9.25 and 3.13.9.
Cross-interpreter equality is measured in the report; only claim it if executed.

## Create the reviewable source candidate

From a checkout, export only the selected release inputs into a scratch directory:

```sh
python3 scripts/release_source.py --output "$TASK_SCRATCH/export"
python3 scripts/audit-public-source.py --output "$TASK_SCRATCH/export/privacy-source.json"
```

`TASK_SCRATCH` denotes an empty scratch directory of your choice. Compare the manifest/fingerprint and scan, then extract
`public-source.tar.gz` into a **new empty source directory** for review. The tar
has repository-relative paths and no Git metadata. To build on another host, send only that archive.

## Offline validation commands

Build dependency images in rootless Podman; network is used only for public
image/package pulls. All runs have network disabled, no hardware and no extra
capabilities. Use a fresh empty output directory per interpreter.
Run the following commands from the new empty directory populated by extracting
the public source export. The wrapper selects public source again before copying it
into its temporary test directory.

```sh
podman build -f Containerfile.release -t localhost/tapediag-publication:3.13.9 .
podman build -f Containerfile.release --build-arg PYTHON_IMAGE=docker.io/library/python:3.9.25-slim-bookworm@sha256:a02e9c5406c416c504d6c9a1a306ff4080c3173f1008d192f953bd20382a2d5c -t localhost/tapediag-publication:3.9.25 .
mkdir -p /tmp/tapediag-release-313
python3 scripts/fetch-sbom-schemas.py --output /tmp/tapediag-release-schemas
BUILD_IMAGE="$(podman image inspect localhost/tapediag-publication:3.13.9 --format '{{.Id}}')"
podman run --rm --network=none --cap-drop=ALL --security-opt=no-new-privileges --tmpfs /tmp:rw,size=2g,mode=1777 -e BUILD_IMAGE="$BUILD_IMAGE" -v "$PWD:/input:ro" -v /tmp/tapediag-release-313:/out:rw -v /tmp/tapediag-release-schemas:/schemas:ro "$BUILD_IMAGE"
# Repeat with the 3.9.25 image and a new /tmp/tapediag-release-39 directory.
```

Any empty scratch directory can replace the `/tmp` output paths. On SELinux
hosts, add `:Z` to the bind mounts (for example `-v "$PWD:/input:ro,Z"`).
Restricted rootless environments may additionally need engine flags
`--cgroup-manager=cgroupfs --events-backend=file` and run flags
`--cgroups=disabled --security-opt=label=disable`.

`validate-release.sh` performs lint/consistency, full source tests, two builds,
distribution member checks, installed-wheel smoke away from source, full sdist
tests, README verification, identifier audit and mhvtl synthetic quickstart.
An optional read-only `/baseline` mount also executes the standalone PR 1 suite.
It then creates `sbom.cdx.json` **inside that container**. The CycloneDX 1.6
inventory identifies the hashed wheel, zero base runtime dependencies, and the
pinned conditional `dta` extra;
Python build tools and dpkg OS packages are separately marked `excluded` from
runtime. It records the immutable image and artifact hashes. It is an inventory,
not a vulnerability assessment. It uses the standard library and pinned build-time `packaging` parser, no paid service,
network or external SBOM API. Container inventory failure fails the run.

Once all artifacts/SBOM are final, create the complete unsigned checksum list:

```sh
cd /tmp/tapediag-release-313
sha256sum tapediag-0.3.0-py3-none-any.whl tapediag-0.3.0.tar.gz public-source.tar.gz source-manifest.json reproducibility.json sbom.cdx.json > SHA256SUMS
sha256sum -c SHA256SUMS
```

Keep per-interpreter outputs separate. The wheel and sdist from both
interpreters should be byte-identical; published release checksums are listed
in the GitHub release notes.

## Fedora/Rocky reproduction

Exact base image digests and complete RPM transaction locks (including Python,
pip and newly introduced dependencies) are pinned in
`requirements-fedora-rpm.txt`, `requirements-rocky-rpm.txt` and the commands
below.
The installation image introduces only the locked RPM versions, with weak
dependencies disabled. Do not silently update pins.
Build each dependency image with its complete RPM lock:

```sh
podman build -f Containerfile.distro --build-arg DISTRO_IMAGE=registry.fedoraproject.org/fedora:44@sha256:cd3513b19e87220eb6fba1aeb041cf88f9c00c3b1de213c36db7532c383f4a1c --build-arg RPM_LOCK=requirements-fedora-rpm.txt -t localhost/tapediag-distro:fedora44 .
podman build -f Containerfile.distro --build-arg DISTRO_IMAGE=docker.io/rockylinux/rockylinux:9@sha256:ed654c694190a670bb5c33f68995b862214fc96ffbdca95e07a8935ba0a3717d --build-arg RPM_LOCK=requirements-rocky-rpm.txt -t localhost/tapediag-distro:rocky9.8 .
```

Run each fresh image with:

```sh
podman run --rm --network=none --cap-drop=ALL --security-opt=no-new-privileges --tmpfs /tmp:rw,size=1g,mode=1777 -v "$PWD:/input:ro" -v /tmp/tapediag-release-313:/wheels:ro localhost/tapediag-distro:fedora44
# Repeat using the separately pinned Rocky image/tag.
```

Both run the installed CLI, source-free smoke, exact README shell block and exact
mhvtl synthetic block. `scripts/check-distro.sh` is the entry point. The source
is never imported by installed-wheel smokes; only fixtures are copied for docs.

## SBOM schema validation

Validate offline using the pinned CycloneDX **1.6** schemas
`bom-1.6.schema.json`, `spdx.schema.json` and `jsf-0.82.schema.json` from the
[official versioned schema directory](https://github.com/CycloneDX/specification/tree/1.6/schema).
The exact SHA-256 pins are built into
[the schema fetcher](../scripts/fetch-sbom-schemas.py). Keep these validation
inputs in a scratch directory and mount at `/schemas:ro` in the test container. The release wrapper requires this
mount and validates its generated SBOM automatically. To repeat just that check:

```sh
python scripts/check-sbom.py --schema-dir /schemas /out/sbom.cdx.json
```

The checker uses the pinned jsonschema/referencing development dependencies and
a local resource registry; it cannot fetch unresolved schema references. The
SBOM is not bundled into the wheel, and build tools are not runtime dependencies.
