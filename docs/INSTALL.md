# Installation and offline walkthrough

Python 3.9+ is required. The base `tapediag` CLI has no third-party runtime dependencies. The optional
`dta` extra needs `tomli==2.3.0` on Python 3.9/3.10; Python 3.11+ uses `tomllib`.
See the [DTA runbook](RUNBOOK-drive-test.md) for synthetic plans and its separate
maintenance authorization requirements.
The following installs use a local, reviewed wheel; no package index or tape
utility is contacted. Do not install mhvtl, load its module or mount devices for
this walkthrough. A saved-text fixture models a virtual library's command
formats; it is not a claim of live mhvtl or LTFS interoperability.

## Fedora and Rocky containers

Build dependencies only inside rootless Podman. `Containerfile.distro` accepts
an immutable public base and a complete exact RPM transaction lock. The tested values and
complete offline run commands are in [REPRODUCIBLE-BUILD.md](REPRODUCIBLE-BUILD.md).
Weak dependencies are disabled; every package introduced by the resolved
transaction is pinned (base packages are fixed by the image digest).

| Container | Python | pip RPM | Complete transaction lock |
| --- | --- | --- | --- |
| Fedora 44 | 3.14.8-1.fc44 | 26.0.1-3.fc44 | [Fedora lock](../requirements-fedora-rpm.txt), six RPMs |
| Rocky 9.8 | 3.9.25-7.el9_8 (already in base) | 21.3.1-2.el9_8.rocky.0.1 | [Rocky lock](../requirements-rocky-rpm.txt), one new RPM plus exact Python selection |

Fedora and Rocky use the same installation commands inside a fresh container:

```sh
python3 -m venv /tmp/venv
export PATH="/tmp/venv/bin:$PATH"
python -m pip install --no-index --no-deps /wheels/tapediag-0.3.0-py3-none-any.whl
python -m pip check
tapediag --version
```

Mount only the wheel directory at `/wheels:ro` and public source at `/input:ro`.
Use `--network=none`, `--cap-drop=ALL`, `--security-opt=no-new-privileges` and
no device mounts. The distro check copies fixtures and README to a fresh writable
working directory, executes this installation, the installed-wheel smoke,
the complete README block and the exact walkthrough below.

## mhvtl synthetic quickstart

After installation, run from the source root (or a writable directory containing
its `fixtures/`). These are all saved-text inputs. `/dev/sg31` and `/dev/sg40`
are invented path labels in fixture text; no device is opened. Every serial,
WWN, barcode, topology, counter and time is invented. Missing optional LTFS/ITDT
captures remain unknown. The matching executable block is
`scripts/mhvtl-quickstart.sh`; tests require exact equality of the blocks.

<!-- mhvtl-quickstart-start -->
```sh
mkdir -p artifacts/mhvtl
tapediag inventory --from-file fixtures/mhvtl-synthetic/inventory.txt > artifacts/mhvtl/inventory.json
tapediag report --from-dir fixtures/mhvtl-synthetic --fleet-id SYNTH-MHVTL --captured-at 2026-10-18T00:00:00Z --html artifacts/mhvtl/report.html > artifacts/mhvtl/report.json
tapediag validate --from-file artifacts/mhvtl/report.json
tapediag guided --workflow inventory-audit --from-report artifacts/mhvtl/report.json > artifacts/mhvtl/audit.json
tapediag dashboard artifacts/mhvtl/report.json --output artifacts/mhvtl/dashboard.html
tapediag export-csv artifacts/mhvtl/report.json --output artifacts/mhvtl/fleet.csv
python - <<'PY'
import csv
import json
from pathlib import Path
report = json.loads(Path('artifacts/mhvtl/report.json').read_text())
assert report['schema_version'] == '3.0'
assert report['fleet_id'] == 'SYNTH-MHVTL'
assert len(report['drives']) == len(report['libraries']) == 1
assert not report['errors']
assert report['commands'] == []
rows = list(csv.DictReader(Path('artifacts/mhvtl/fleet.csv').open()))
assert len(rows) == 2 and {row['fleet_id'] for row in rows} == {'SYNTH-MHVTL'}
assert Path('artifacts/mhvtl/dashboard.html').stat().st_size > 1000
print('mhvtl synthetic quickstart: 6 CLI commands + independent assertions PASS; no emulator or hardware')
PY
```
<!-- mhvtl-quickstart-end -->

Open `artifacts/mhvtl/dashboard.html` locally. Expected results are two assets
(one drive, one library), schema 3.0, fleet SYNTH-MHVTL, no collection errors and
an offline dashboard. A score is a heuristic assessment of selected signals,
not a hardware certification. `audit.json` records the inventory decision tree;
`fleet.csv` contains two asset rows. The parser compatibility and safety tests
exercise malformed/incomplete cases separately.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `No module named venv` or missing pip | Rebuild the distro dependency image with the linked exact RPM lock; do not install into the host Python. |
| `externally-managed-environment` | Activate the venv and use its Python; do not pass an override to modify distro Python. |
| Wheel path/version missing | Build with `scripts/build-release.py` inside the pinned container and check `SHA256SUMS`. |
| `tapediag: command not found` | Activate `/tmp/venv/bin` or use `python -m tapediag`; source checkout launchers also require the repository on the import path. |
| Exit 1 from `report` | Inspect `errors` and section warnings. Confirm saved capture tree/file names and UTF-8 text; keep missing evidence explicit. |
| Exit 1 from `watch` | Regressions were found; read the JSON events. Exit 2 indicates invalid input. |
| Unknown TapeAlert/MAM/topology | The fixture or device lacks evidence. A clear flag or healthy score cannot be inferred from absence. |
| GUI file picker rejects v1/v2 | Use CLI `migrate` or `dashboard` to convert saved reports. Import v3 JSON in the file picker. |
| Podman user namespace denied | Use an authorized rootless container host and task scratch. Do not add privilege, change host configuration or mount hardware. |
| Rootless cgroup/SELinux failure | Use the recorded per-container fallback flags; keep source read-only and avoid relabeling any other repository. |
| RPM version no longer available | Stop and record the exact unavailable NEVRA. Select/review a replacement, update the pin and rerun the distro check. Do not silently select latest. |
| `ltfs`/`mtx`/`sg_logs` unavailable | Offline use needs none of them. Live prerequisite utilities are separate optional software, never installed by tapediag. |

No emulator service, kernel module, LTFS mount/format/check/repair or real hardware
validation was performed by this release workflow.
