# Guided read-only workflow

The workflow is an original sequence of documented diagnostic operations, inspired by the structure of public vendor diagnostic guides. It does **not** execute ITDT or reproduce a vendor certification test. References: [public ITDT documentation](https://www.ibm.com/support/pages/ibm-tape-device-drivers-and-diagnostic-tool-users-guide), [sg3_utils](https://github.com/hreinecke/sg3_utils/tree/master/doc), [mtx](https://github.com/mtx-org/mtx/blob/master/mtx/mtx.1).

```sh
# No subprocess or device discovery. Exact argv and explanations are printed as JSON.
python3 -m tapediag guided --drive /dev/sg9 --changer /dev/sg10
python3 -m tapediag guided --dry-run --drive /dev/sg9 --state-file plan.json

# Real collection is an explicit operator action; not needed for fixtures or tests.
python3 -m tapediag guided --execute --drive /dev/sg9 --changer /dev/sg10 \
  --i-understand-read-only --medium-loaded --state-file run.json

# Resume the same explicit selections/mode/prerequisite declaration.
python3 -m tapediag guided --execute --drive /dev/sg9 --changer /dev/sg10 \
  --i-understand-read-only --medium-loaded --state-file run.json --resume

# Validate/replay saved transcript without execution.
python3 -m tapediag guided --from-file run.json
```

No default device is chosen. With no paths, dry-run shows the inventory step only. `--execute` requires one or more explicit `--drive /dev/sgN` or `--changer /dev/sgN` paths and the confirmation flag. `--dry-run` and `--execute` conflict. A dry-run state cannot be resumed into execute mode: choose a fresh state file after reviewing the plan. No CLI argument forwards utility options or adds steps.

| Step | Prerequisite | Expected seconds (planning estimate, not a promise) | Interpretation |
| --- | --- | --- | --- |
| Inventory (`lsscsi -g`, `sg_map -x`) | No medium needed | 2 | Decode topology; no tape/changer mappings or collection errors require review. No automatic selection or association. |
| Inquiry + VPD | No medium needed | 3 | Decode firmware/identity; unknown or incomplete output warns. |
| TapeAlert 2Eh | No medium needed | 2 | Critical active drive flag fails; Warning/Info flags or incomplete observations warn. Reading may acknowledge latched flags. |
| Log pages | No medium needed | 10 | Decoded observations pass unless health rules match (warn); command failures fail. Empty/unknown/truncated observations warn. Media-specific fields can be unavailable. |
| MAM attributes | Medium already loaded | 6 | Selected attributes decoded; malformed/unavailable values warn. Skipped unless `--medium-loaded` is declared; the tool never loads media or probes by moving it. |
| Changer status | Changer explicitly selected/present | 5 | Status parsed with consistency observations; warnings require review, collection errors fail. |

A process failure marks the step fail and retains the error. Unsupported pages do not cause alternative commands. Steps continue so a partial transcript is useful. Each subprocess still has the configured timeout (default 15 seconds; maximum 300), so actual total duration may exceed the estimates. The collection exit status is 1 for any failed step, 0 for plan/completed pass/warn/skipped steps, 2 for invalid/refused requests. Inspect status/notes, not just exit 0. `complete` means the selected sequence finished, not that all diagnostics passed or media was examined.

State is atomically replaced after every step. After interruption, only completed successful steps are skipped; failed/incomplete steps are retried. No automatic retry loop runs. Repeating a failed TapeAlert step can acknowledge flags again. Resume validates the v2 schema and matches immutable metadata/argv to a freshly generated allowlisted plan. Saved argv cannot add commands; saved verdict/data is reinterpreted from successful command results. State is unsigned local data, not an authenticated hardware attestation. Do not edit or reuse it for another collection, and coordinate one writer per state file.

The transcript always lists four operations as **NOT PERFORMED BY THIS TOOL - see vendor tool**: write/read test, erase, firmware update, load/unload. Each links to public vendor documentation. They have no executable argv, no hidden override and no runner route. The exact allowlist excludes both destructive operations and media-positioning/read tests. Use approved vendor tooling and its documented prerequisites outside tapediag for those operations.

Schema [v2](../schema/tapediag-report.v2.json) accepts diagnostic reports and guided transcripts, distinguished by `document_type`. Runtime `validate_report()` dispatches by version; independent jsonschema tests cover both. [v1](../schema/tapediag-report.v1.json) stays unchanged, and saved v1 reports still validate/replay/render. `report --schema-version 1.0` retains the legacy report shape. The Python `offline_report()` / `live_report()` APIs remain v1; `v2.enrich()` adds v2 fields.
