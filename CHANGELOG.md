# Changelog

## 0.3.0 — 2026-10-21

First public release. Earlier versions below were internal development
snapshots and were not published.

- Add offline `ltfs-index` validation of saved LTFS 2.4/2.5 full-index XML:
  guarded streaming parse, DTD/entity refusal, resource limits, stable finding
  codes, logical-overlap vs physical-sharing extent checks, synthetic fixtures.
- Generate tapediag/DTA roff manuals from argparse and add a fixture-only
  suspected-failure walkthrough, including an isolated installed-wheel check.
- Add offline multi-run TapeAlert histories with separate 2Eh/12h streams,
  explicit coverage gaps and observed activation/clearing events.
- Add bounded captured-hex LOG SENSE decoding (2Eh/0Ch/17h and an explicit
  historical vendor 31h profile), plus dated counter/flag trends that preserve
  unknowns, reset boundaries and declared cartridge identity.
- Add saved mtx inventory diffs with duplicate-tag ambiguity and conservative
  relocation candidates; no robot commands or inferred device mappings.
- Add `explain` for cited offline TapeAlert, sense/ASC, log-page and density
  lookups; unknown codes stay unknown. All new analyses optionally export static
  escaped HTML alongside JSON and refuse live execution.
- Add the `dta` drive-test assistant (optional extra) with plan-by-default,
  `--apply` plus serial confirmation, journaled checkpoints and an optional
  drive-owner lock adapter.
- Replace uncertain documentation excerpts/goldens with original synthetic
  parser cases; retain the BSD-licensed LTFS prefix and its notice.
- Add canonical two-build wheel/sdist reproduction, explicit clean-source export,
  complete distribution/RECORD inspection and container-derived CycloneDX SBOM.
- Add pinned Fedora/Rocky installs, README/mhvtl synthetic walkthroughs and an
  upstream naming/licence review.
- Add installation guidance, security policy and contribution guidelines.
- Add pinned Python lint and GitHub Actions workflow validation alongside tests.
- Add nine guided workflows with explicit read-only plans and offline replay.
- Add schema v3, evidence-aware heuristic scoring, fleet dashboards, CSV export,
  explicit v1/v2 migration and saved-report regression comparisons.
- Preserve v1/v2 validation and rendering compatibility.
- Keep CSV artifacts byte-exact so quickstart verification leaves them stable.

## 0.2.0 — development snapshot

- Add MAM, inquiry/VPD and topology parsing, guided collection with resume, and
  schema v2 diagnostic reports.
- Add offline HTML rendering, synthetic scenarios and expanded packaging checks.

## 0.1.0 — development snapshot

- Introduce command planning, explicit read-only collection, offline parsers,
  schema v1 reports and synthetic/publicly attributed fixtures.

Dates for earlier development snapshots are intentionally omitted.
