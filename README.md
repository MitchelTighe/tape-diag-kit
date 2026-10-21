# tapediag

Read-only diagnostics for Linux LTO tape drives and SCSI medium changers. Plan commands, parse saved outputs without hardware access, or explicitly collect a versioned JSON report. Python 3.9+; `tapediag` uses only the standard library at runtime. The optional `dta` extra requires the pinned TOML reader on Python 3.9/3.10.

**Dry-run is the default.** A live command requires `--execute`. Offline `--from-file` and `report --from-dir` never invoke external tools or open tape devices. No root privileges are required for planning or parsing.

Validate saved LTFS 2.4/2.5 full-index XML with
`tapediag ltfs-index --from-file index.xml`. The
[LTFS index guide](docs/LTFS-INDEX.md) describes streaming limits, sparse and
shared extents, stable finding codes, and synthetic fixtures.

Maintained by Mitchel Tighe. Source: https://github.com/MitchelTighe/tape-diag-kit
(the Python package and commands are named `tapediag`).
[Security policy](SECURITY.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [License](LICENSE)

## Why this exists

Tape troubleshooting often means comparing several command formats while trying
to avoid a maintenance action. tapediag puts those observations into versioned
reports, records missing evidence explicitly, and lets you rehearse the exact
read-only commands before collection. Saved captures and the included synthetic
fleets work without tape hardware. Scores are triage heuristics, not certified
health verdicts or a substitute for vendor support.

## Install and first use

tapediag is not published on PyPI. Install the wheel attached to a
[GitHub release](https://github.com/MitchelTighe/tape-diag-kit/releases), or run
directly from a source checkout. The base CLI has no third-party dependencies:

```sh
python3 -m pip install tapediag-0.3.0-py3-none-any.whl
# optional drive-test assistant extra (adds tomli on Python 3.9/3.10)
python3 -m pip install 'tapediag-0.3.0-py3-none-any.whl[dta]'
```

From a checkout, with Python 3.9 or newer:

```sh
python3 -m tapediag --help
python3 -m tapediag tapealert /dev/sg9
python3 -m tapediag report --from-dir fixtures/scenarios/healthy
```

The second command prints a plan. The third parses synthetic saved text. Neither
accesses hardware. `bin/tapediag` is also a source launcher. For an installed CLI,
use the rootless container build in [Development and verification](#development-and-verification);
it builds and installs the wheel inside the container and tests it away from the
source checkout. A wheel built there can later be installed into an isolated
Python environment with `python -m pip install --no-index --no-deps /path/to/tapediag-0.3.0-py3-none-any.whl`.
No third-party Python dependencies, root access, device mounts or vendor tools are needed for offline `tapediag` use.
Live collection separately needs the appropriate Linux utilities and permissions.

See [Fedora/Rocky installation and synthetic mhvtl walkthrough](docs/INSTALL.md),
[reproducible builds and SBOM](docs/REPRODUCIBLE-BUILD.md),
and [upstream naming/licence review](docs/UPSTREAM-REVIEW.md). The base `tapediag` CLI has no third-party Python packages. For `dta` configuration on Python 3.9/3.10, install the pinned `dta` extra described in the operator runbook; Python 3.11+ uses `tomllib`.

The separate **`dta` drive-test assistant** plans a maintenance workflow across Brocade FC zoning, Spectra BlueScale media moves, and IBM ITDT SE 9.x scripting. Its write-capable workflow requires **`--apply` plus terminal entry of the exact drive serial**, with fresh media/identity/isolation guards. Existing `tapediag` command permissions remain read-only. Start with the [operator runbook](docs/RUNBOOK-drive-test.md) and [public vendor references](docs/DTA-SOURCES.md).

```sh
bin/dta --config config.example.toml --run-id SYNTH-PLAN
bin/dta --config fixtures/dta/config.synthetic.toml --run-id SYNTH-DEMO --simulate fixtures/dta
```

Both commands only print a plan: **zero remote requests**. Site values belong in a local ignored `*.dta.local.toml`, with credentials referenced by environment **name** only. `dta --resume` continues completed apply checkpoints; an uncertain in-flight write requires manual reconciliation. The [operator runbook](docs/RUNBOOK-drive-test.md) describes synthetic rehearsal and limitations. DTA does not download ITDT, submit tickets, or infer a hardware PASS from an exit code.

An optional [owner lock/verifier adapter](docs/DTA-OWNER-ADAPTER.md) adds STEP 0 and final unlock/visible-usable verification. Command templates and resource mappings come from config; no native proprietary admin syntax is guessed. The synthetic enabled profile is `fixtures/dta/config.owner.synthetic.toml`.

## Quickstart — offline v3

Run from the repository root. Every command below uses synthetic data or command planning; no installation or hardware is needed. `scripts/verify-v3.py` executes this exact block and records the results.

<!-- quickstart-v3-start -->
```sh
export PATH="$PWD/bin:$PATH"
mkdir -p artifacts/v3
tapediag --help
tapediag tapealert /dev/sg9
tapediag guided --workflow wont-load --drive /dev/sg9 > artifacts/v3/quickstart-plan.json
tapediag report --from-dir fixtures/scenarios/healthy --fleet-id SYNTH-QUICKSTART --html artifacts/v3/quickstart.html > artifacts/v3/quickstart.json
tapediag validate --from-file artifacts/v3/quickstart.json
tapediag guided --workflow slow-drive --from-report fixtures/fleets/synth-bravo-20261018.json > artifacts/v3/quickstart-workflow.json
tapediag migrate --from-file fixtures/golden/scenario-healthy.json --fleet-id SYNTH-LEGACY > artifacts/v3/migrated-v2.json
tapediag dashboard fixtures/fleets/*.json --output artifacts/v3/fleet-dashboard.html
tapediag export-csv fixtures/fleets/*.json --output artifacts/v3/fleet.csv
tapediag watch fixtures/fleets/synth-alpha-20261016.json fixtures/fleets/synth-alpha-20261018.json > artifacts/v3/watch-clear.json
```
<!-- quickstart-v3-end -->

Open `artifacts/v3/fleet-dashboard.html` in a browser: it embeds three fictional fleets with dated history. It works from disk without a server/network, supports local multi-file v3 JSON import, score trends, worst-first sort, search, fleet/type/evidence filters, dark mode and printing. No CDN, external JavaScript, telemetry, uploads or fetch calls. The file picker accepts v3; the dashboard CLI migrates v1/v2 as it embeds them.

Use `tapediag guided --menu --drive /dev/sg9 --changer /dev/sg20` in a terminal for the nine-choice wizard. [WORKFLOWS.md](docs/WORKFLOWS.md) documents each tree with ASCII diagrams and live prerequisites. Without `--execute`, the wizard only prints a plan. The `dump-plan` workflow prepares a **CAPTURE PLAN**; it never generates, retrieves or uploads a dump. Original v2 resumable collection remains available with `guided` without `--workflow`.

Every v3 asset carries a score (0–100), grade, model ID, reasons, evidence gaps and identity basis. All weights/thresholds are unverified heuristics, with public observation definitions in [SCORING.md](docs/SCORING.md). A 100 score with gaps remains unknown. Fleet scores use the minimum asset score. Library inventory health cannot establish complete robotics/door/sensor health.

`watch BEFORE AFTER` compares two saved reports, returning **1 if regressions exist**, 0 otherwise, and 2 for invalid inputs. It flags score drops, new alerts, increasing error counters, coverage loss and missing assets; counter decreases remain reset/replacement/wrap notes. CSV output protects spreadsheet formula prefixes. No polling, timers, service configuration or live collection is part of watch.

V3 is the default for newly assembled reports; saved-report replay preserves its input version. Use `migrate --from-file` to explicitly convert v1/v2 JSON, `report --schema-version 2.0` for the frozen v2 writer, or `--schema-version 1.0` for the v1 shape. Migration does not invent capture time from mtime. Supply an anonymous stable `--fleet-id` and actual `--captured-at` (RFC3339 with timezone) when the capture time is known. Device-path identities require mapping verification across reconnects; redacted serials are not used to merge unrelated drives.

`python3 -m tapediag` is equivalent to the source-checkout launcher. Runtime uses only Python's standard library.

## Offline v4 analysis additions

Compare captured evidence across runs without a device or vendor utility:

```sh
python3 -m tapediag alert-history fixtures/v4/alerts-16.json fixtures/v4/alerts-17.json fixtures/v4/alerts-18.json fixtures/v4/alerts-19.json
python3 -m tapediag log-decode --from-file fixtures/v4/log-0c.txt
python3 -m tapediag log-trend --from-file fixtures/v4/log-series.json
python3 -m tapediag inventory-diff fixtures/v4/inventory-before.txt fixtures/v4/inventory-after.txt --library-id SYNTH-LIB
python3 -m tapediag explain sense:2/3a/00
```

[TapeAlert history](docs/alert-history.md) separates clears from coverage gaps.
[Captured-hex log trends](docs/log-trends.md) retain reset/media-change boundaries.
[Inventory diffs](docs/inventory-diff.md) report tag relocation candidates and
ambiguity. [Offline explanations](docs/explain.md) cite a finite public catalogue.
Each supports JSON stdout and optional `--html OUTPUT.html`; `--execute` is
refused. Exit 0 means analysis completed, including warnings/unknowns; exit 2
means invalid input. Existing `watch` retains its regression exit 1 behavior.
These standalone analysis formats do not change v3 reports or their scores.
A [fixture-only suspected-failure walkthrough](docs/FAILING-DRIVE-WALKTHROUGH.md)
reproduces all five commands and links the generated argparse manuals.

## Collecting diagnostics

Optional Linux utilities: `lsscsi`, sg3_utils (`sg_logs`, `sg_inq`, `sg_turs`), mt-st (`mt`), `mtx`, and LTFS (`ltfs`). Missing programs, permission errors, unsupported pages, and timeouts are reported in JSON; they do not trigger installation or alternate maintenance commands.

After confirming the device mapping and coordinating with the application that owns the drive:

```sh
tapediag report --execute --drive /dev/sg9 --nst /dev/nst0 --changer /dev/sg10 --timeout 10
```

`report --execute` also supports automatic discovery through `lsscsi -g`, with cached sysfs enumeration as a fallback if that command fails. `--drive` and `--changer` each restrict their respective kind when supplied and can be repeated. For a planned collection over known devices, provide explicit selections. Without selections, dry-run shows the inventory and LTFS discovery commands; execution adds diagnostics for the drives and changers discovered by inventory. No devices are discovered during dry-run. `--nst` requires exactly one explicit `--drive` in a report.

`inventory --source sysfs --execute` reads `/sys/class/scsi_generic` and `/sys/class/scsi_tape`, including cached `type`, `vendor`, `model`, `rev`, and device mapping entries. It opens no `/dev` nodes. `--sysfs-root` accepts a saved sysfs directory tree. The sysfs dry-run command list is `[]` because it has no subprocesses.

## Safety model

The runner accepts complete, hard-coded argument forms, not arbitrary command strings. It uses an absolute executable found on a fixed system search path, a minimal environment with the C locale, no shell, closed stdin, and a timeout for every process (15 seconds by default, configurable up to 300). Flags cannot be forwarded. No `sg_raw`, LOG SELECT/reset/save, mode-select, write-buffer, firmware update, formatting, erasing, media positioning, loading, unloading, or robot inventory command is accepted. `mtx inventory` is **not** `tapediag inventory`: the former can move the robot and is refused.

Only numeric `/dev/sgN` and non-rewinding `/dev/nstN` command arguments are accepted. `mt status` refuses symlink aliases and `/dev/stN` to avoid close-time rewinds. A generic-device number is never assumed to equal a tape-device number. `drive-status` without `--nst` runs inquiry and TEST UNIT READY only and reports that `mt` was skipped; reports use a confirmed inventory mapping when available.

Read-only describes the issued diagnostic operations, not an assurance of zero device side effects. Reading TapeAlert can acknowledge/clear latched flags on some devices; TEST UNIT READY can consume unit attention. Device firmware and the tape driver control these effects. The toolkit changes no configuration, performs no cleaning/recovery actions, and never mounts LTFS. Review the [command reference](docs/commands.md) and [TapeAlert profile](docs/tapealert.md) before collection.

## Offline files and JSON

Observation subcommands accept `--from-file PATH`. Supply a regular UTF-8 text capture (invalid UTF-8 is replaced; limit 16 MiB). For `drive-status`, a file can concatenate standard inquiry, saved TUR diagnostics, and `mt status` output. TUR success often has no text; offline `ready` remains `null` unless the capture explicitly reports readiness. LTFS parses its device-list text, including records logged to stderr during live collection. An optional device argument filters that listing.

`itdt --from-file PATH` is an adapter for saved default ITDT scan lines, labeled inquiry fields, and numeric/named TapeAlert text. It never invokes ITDT, including with `--execute`. Custom ITDT format strings, graphical screenshots, binary dump files, and ITDT JSON dialects are outside this adapter's current scope.

`report --from-file` validates and replays saved **v1, v2 or v3 report JSON**, while `report --from-dir` assembles command captures in this layout:

```text
capture/
  inventory.txt                    # lsscsi -g
  drives/sg9/
    drive-status.txt               # concatenated inquiry / TUR / mt status
    tapealert.txt                  # sg_logs --page=0x2e decoded text
    logpages.txt                   # concatenated decoded log pages
  libraries/sg10/status.txt         # mtx status
  ltfs.txt                         # optional
  itdt.txt                         # optional; offline only
```

Repeat `sgN` directories for additional devices. Missing required captures and inventory devices without a capture directory produce explicit errors and exit status 1. Do not infer drive-to-library associations from the numeric element identifiers: `mtx` drive elements have no guaranteed relationship to `/dev/nstN`.

The [v1](schema/tapediag-report.v1.json), [v2](schema/tapediag-report.v2.json) and [v3](schema/tapediag-report.v3.json) schemas use Draft 2020-12, with byte-identical package copies for dependency-free validation. V3 is the default for new CLI reports. `validate --from-file` also checks v3 score integrity against observations. Development tests independently validate reports with `jsonschema`. Unknown log-page bytes and unrecognized lines are retained. Missing observations are `null` or explicitly listed as unobserved; a successful collection is not a hardware-health verdict. Review section warnings as well as top-level errors. Temperature units and capacity labels remain as reported; live collection and scored reports deliberately exclude vendor capacity pages `0x30`/`0x31`. The separate offline `log-decode` command requires an explicit historical profile to interpret `0x31`. Standard SSC volume statistics `0x17` supplies capacity/usage where supported.

Exit statuses: **0** for planning/successful parsing or collection; **1** for a partial report or subprocess failure; **2** for invalid arguments, refused commands, invalid saved reports, or unreadable input. Argparse usage errors are human-readable on stderr; other errors are JSON. Live subcommands return `{data, commands, errors}`; reports return v3 by default (`--schema-version 1.0` or `2.0` retains the older shape). Explicit sysfs inventory and offline parsers return their data directly.

## Development and verification

The reference workflow builds and tests in rootless containers with no network or device mounts. Dependencies and images are pinned. The matrix uses Python 3.9.25 and 3.13.9, with a wheel and sdist built inside each test image:

```sh
podman build --memory=2g --build-arg PYTHON_IMAGE=docker.io/library/python:3.9.25-slim-bookworm -t localhost/tapediag-test:3.9.25 .
podman run --rm --network=none --cpus=2 --memory=2g localhost/tapediag-test:3.9.25
# Repeat with python:3.13.9-slim-bookworm and tag 3.13.9.
```

The image installs the wheel, smoke-tests its CLI away from source, then runs pytest. The [release validation runbook](docs/REPRODUCIBLE-BUILD.md) covers independent builds, full source/sdist suites and offline installation checks. [.github/workflows/ci.yml](.github/workflows/ci.yml) runs pinned Ruff and actionlint checks plus the two-interpreter build/test sequence. Existing environments can run the test suite directly:

```sh
python3 -m pip install -r requirements-dev.txt   # pytest, jsonschema
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

The full release pipeline (`scripts/validate-release.sh` inside `Containerfile.release`) runs lint, the source and sdist test suites, a two-build reproducibility check, installed-wheel smoke tests and SBOM validation.

[Fixture sources and licenses](fixtures/SOURCES.md) distinguish short public excerpts from original synthetic data. [CONTRIBUTING.md](CONTRIBUTING.md) describes capture hygiene and parser changes. Project code and original fixtures use **MIT**, chosen for simple reuse by administrators and downstream diagnostic tools. The retained LTFS excerpt keeps its BSD-3-Clause status and notice; see [LICENSE](LICENSE) and [fixtures/NOTICES.md](fixtures/NOTICES.md).

## v2-compatible diagnostics and guided collection

V2 added `mam`, `inquiry`, `topology` and `guided`. Every diagnostic adapter accepts saved text and defaults to command planning. [Diagnostic details](docs/v2-diagnostics.md) list every allowed page/attribute, public citation, density code, consistency rule and health deduction.

```sh
python3 -m tapediag mam --from-file fixtures/synthetic/mam.txt
python3 -m tapediag inquiry --from-file fixtures/synthetic/inquiry-vpd.txt
python3 -m tapediag topology --from-file fixtures/synthetic/topology.txt
python3 -m tapediag guided --drive /dev/sg9 --changer /dev/sg10
```

The guided plan walks inventory → inquiry/VPD → TapeAlert → log pages → MAM → changer status. It prints exact argv, explanation, prerequisites, expected duration and interpretation for every step. It lists write/read tests, erase, firmware and load/unload as **NOT PERFORMED BY THIS TOOL - see vendor tool** with a public link. There is no execution route for those operations. See [guided execution and resume](docs/guided.md) for the explicit confirmation flag, already-loaded media prerequisite, per-step state persistence and partial-result semantics.

Explicit `report --schema-version 2.0` uses [schema v2](schema/tapediag-report.v2.json), with inquiry/MAM, topology, changer checks, provenance and the frozen triage policy. V1 saved reports continue to validate and render; `--schema-version 1.0` selects the legacy collection shape. “Read-only” retains the v1 caveats: TapeAlert may acknowledge flags, and devices control firmware side effects. No maintenance command or media read/write test is performed.

## HTML rendering and fixture reproduction

V3 HTML embeds inline CSS/JavaScript, its structural schema and all report data. Its CSP blocks network connections and hashes the application script. User strings use text nodes. File import validates structure, score arithmetic and identity uniqueness; `tapediag validate` additionally recomputes scores from observations. Treat imported reports as local diagnostic records, not authenticated device evidence.

Legacy v1/v2 replay via `report --from-file ... --html ...` retains the original JavaScript-free report renderer. To create that legacy layout from captures, request `--schema-version 2.0`. `scripts/render-scenarios.py` reproduces v2 scenarios independently of the CLI default.

```sh
PYTHONPATH=. python3 scripts/generate-fleets.py
PYTHONPATH=. python3 scripts/verify-v3.py
```

The [v3 browser check](scripts/screenshots-v3.py) uses [Containerfile.browser](Containerfile.browser), pinned Playwright 1.55.0. Run inside the container with the source at `/work`, a writable task-scratch mount at `/out`, and `--network=none`:

```sh
python scripts/screenshots-v3.py --output /out
```

It captures all three synthetic fleets and their combined dashboard at desktop 1440px and phone 390px, exercises sorting/filtering/file import/rejection, checks overflow and network silence, and exports dark/print media. No live tape device, vendor diagnostic executable, firmware operation, media movement or throughput test is exercised.

The capture layout also accepts optional `topology.txt` at the root and `drives/sgN/mam.txt` / `inquiry.txt`. Missing optional captures remain unobserved. No manifest commands are interpreted.

## Status and limitations

tapediag 0.3.0 is tested against synthetic fixtures, saved captures and the mhvtl
virtual tape library walkthrough; it has not been certified against any vendor's
hardware. Scores and findings are triage aids. Confirm conclusions with the drive
or library vendor's own diagnostics before replacing hardware or media.

## License

MIT for original code, documentation and synthetic fixtures; the retained LTFS
excerpt keeps its BSD-3-Clause notice. See [LICENSE](LICENSE),
[fixtures/NOTICES.md](fixtures/NOTICES.md) and the
[license review](docs/LICENSE-REVIEW.md).
