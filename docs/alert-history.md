# TapeAlert history across saved reports

`alert-history` compares 2–1000 dated v1/v2/v3 diagnostic reports for one fleet.
Legacy reports need explicit migration metadata first. Input order must be
strictly increasing in UTC; missing, duplicate or reversed times are refused.
It never polls, plans collection, opens devices or issues commands.

```sh
python3 -m tapediag alert-history fixtures/v4/alerts-16.json fixtures/v4/alerts-17.json fixtures/v4/alerts-18.json fixtures/v4/alerts-19.json
```

Add `--html OUTPUT.html` for a self-contained escaped evidence view; JSON still
goes to stdout. `--execute` is refused before any capture/output access, whether
placed before or after the command. Exit 0 means analysis completed (including
observed alerts), 2 means invalid/refused input or local I/O failure. This differs
from `watch`'s regression exit 1. All history inputs together are bounded to
16 MiB; each file uses the existing regular-file reader. The product of distinct
drive identities and snapshots is limited to 10,000 pairs, including missing
observations, to bound expansion of the history grid. Use shorter time ranges
for larger fleets. Duplicate JSON keys,
nonfinite values and excessive nesting are refused.

The `tapediag-alert-history-v1` result joins drives by `(fleet_id, asset_id)`.
Each asset has two separate streams: latched page 2Eh (`tapealert`) and page 12h
response (`tapealert_response`). Every snapshot partitions flags 1–64 into
`active`, `inactive`, and `unknown`; source warnings remain visible. A missing
drive/stream makes every flag unknown. A contradictory capture makes that stream
unknown for that snapshot, even though the underlying parser conservatively
retains active observations. Device-path identities produce a mapping warning.
The caller must confirm identity; neither a timestamp nor a matching anonymous
identifier authenticates a capture. No drives yields an empty asset/event list.

Events compare adjacent snapshots only:

| Before → after | Event | Meaning |
| --- | --- | --- |
| inactive → active | `activated` | Newly observed activation within this interval |
| active → inactive | `cleared` | Observed inactive; does not establish repair |
| known → unknown | `coverage-lost` | Missing evidence, never a clearing event |
| unknown → active | `active-observed` | Active now; activation time is unknown |
| unknown → inactive | `inactive-observed` | Inactive now; no clearing time established |
| unchanged | No event | State remains in the snapshot stream |

The fixtures show flag 20 inactive → active → unknown → inactive. There is no
`cleared` event across that gap. No elapsed active duration or repair success is
inferred. Existing health scores and schemas are not changed by this analysis.

Public semantics: [T10 SSC-3 TapeAlert proposal 05-154r2](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf),
including the polling/acknowledgement caveat and drive flag table; the
[sg_logs response decoder](https://github.com/hreinecke/sg3_utils/blob/master/src/sg_logs.c)
distinguishes page 12h from 2Eh. References checked 2026-10-20. This is a historical
public proposal/profile, not a claim of conformance to every current drive.
See [the existing flag catalogue](tapealert.md). History event rules are original
toolkit policy. Synthetic reports are regenerated with
`PYTHONPATH=. python3 scripts/generate-v4-fixtures.py` from the existing invented
ALPHA fleet; they are not hardware captures.
