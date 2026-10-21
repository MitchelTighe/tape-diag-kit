# V3 report interchange

The public structural schema is `schema/tapediag-report.v3.json`, byte-identical to the package resource. It uses Draft 2020-12 and accepts two document types: `report` and `workflow`. Older v1 reports and v2 reports/guided transcripts remain accepted by their frozen schemas.

New `report --from-dir` / `report --execute` outputs default to v3. The Python `offline_report()` / `live_report()` APIs retain their v1 assembly contract, and `v2.enrich()` retains its v2 contract. `v3.migrate()` is a non-mutating adapter that validates input and creates the scored v3 representation; `migrate(v3)` validates/copies without changing its observations or metadata.

## Report additions

- `fleet_id`: anonymous scope shared only by reports from the same fleet. Default `SYNTH-UNASSIGNED` is a placeholder, not a discovered host/site name. Set stable distinct scopes before combining reports from different hosts.
- `captured_at`: RFC3339 timestamp with timezone, normalized to UTC by the writer, or `null` when unknown. Live collection records completion time; offline files never inherit current time or file mtime. Supply `--captured-at` only when the capture time is known. Timestamp precision is retained up to Python datetime's microseconds.
- `migration`: source schema and producer version, plus explanation of recomputation/time handling. New reports use the v2 observation assembly internally, so their `from_version` is also `2.0`. Original v2 aggregate health is replaced by the versioned v3 policy; source diagnostic observations/commands/errors are retained.
- Each drive/library has `asset_id`, `identity_basis`, and `health`. Known synthetic serials can identify drives; redaction placeholders use a device-path identity. Paths must be confirmed across reconnects. Identical paths in different fleets remain distinct.
- `health` at report level contains model ID, minimum asset score (null for no assets), asset count and attention count. Per-asset health includes score, grade, assessment, coverage, gaps and cited heuristic reasons.

Report IDs must be unique within a fleet snapshot; devices must also be unique. Do not reuse an anonymous asset identity for different hardware. Redacted production identifiers cannot provide stable cross-host identity and are deliberately not hashed. No real site/serial should be inserted into this repository's fixtures.

Migration preserves all fields in the source drive/library observation records. V1 lacks inquiry/MAM/response/topology, so migration fills those with null and computes new coverage gaps. Migration never executes or trusts saved argv as a command source. Saved-report replay remains byte-value compatible with its original version; explicit migration is a separate step.

## Validation and dashboard

`tapediag validate --from-file REPORT` performs structural validation plus v3 integrity checks: permitted device paths, unique identities, catalog-consistent TapeAlert fields/partitions, recomputed per-asset health, and aggregate consistency. Structural JSON Schema validation alone cannot enforce all these cross-field relationships. Validation does not authenticate observations or certify hardware.

The dashboard CLI accepts v1/v2/v3 reports and embeds migrated copies. The browser file picker accepts structurally valid v3 reports and verifies score arithmetic, grades, coverage and identity uniqueness. It cannot run the Python model; validate externally edited JSON with the CLI before import. Its UI makes no network calls and uses text nodes for user-provided strings. Only local File API reads and an inline, hash-authorized application script are used. No persistent browser storage is written.

History joins on `(fleet_id, asset_id)`. Each card uses its latest dated observation, or last input when all are undated; undated observations never contribute to chronological trends. Snapshots with identical timestamps use input order as a tie-breaker. Exact duplicate JSON reports are ignored. Combining conflicting observations at one timestamp does not produce an authenticated history. A tooltip/diagnosis is not inferred from points on a trend. JavaScript numbers cannot exactly represent every integer above 2^53−1; the source observation's `raw` text and Python-validated JSON remain authoritative for large counter values. Scores and thresholds shown in the UI are small integers; no rates are calculated in the browser.

`watch BEFORE AFTER` requires the same fleet and, when both timestamps are known, strictly increasing time. It reports regressions and counter resets without computing rates. It warns on device-path identity reuse. CSV has one row per asset/snapshot, retains units in evidence/gaps, quotes embedded delimiters/newlines and escapes spreadsheet formula prefixes.

## Workflow documents

V3 `document_type: workflow` records the named workflow, mode, explicit read-only steps, result evidence, decisions and limitations. Each decision includes the terminal outcome and branch path. `complete` means analysis/collection finished, not that all steps passed. Collection failures remain failing steps and return exit 1. Dry-run documents have planned steps and no decisions. Offline analysis can contain a full hypothetical plan with no executed results.

V2 `guided` remains the resumable format. Named v3 workflows cannot consume a saved argv plan for resume. `guided --from-file` is replay only. V3 workflow validation rejects argv outside the exact safety grammar, even during replay. Dump capture is always a plan, never a binary dump or executable vendor command.

See [WORKFLOWS.md](WORKFLOWS.md) and [SCORING.md](SCORING.md) for behavior and public evidence definitions.
