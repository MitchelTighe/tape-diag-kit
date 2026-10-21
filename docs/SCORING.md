# Health scoring: triage-v3.0.0

Model ID **`triage-v3.0.0`** is persisted with every asset and fleet summary. This is explainable triage, not a probability of failure, certification, service-life limit, or a vendor-approved health grade. **Every numeric deduction, grade boundary and usage threshold below is an unverified toolkit heuristic.** Public sources define the observations and their interpretation; none prescribes these weights. No model calibration on real devices is claimed.

For each drive/library, start at 100, subtract each matching rule **once per asset**, then floor at 0. Multiple flags/counters in a category retain all evidence but do not repeat the deduction. Active flags in both 2Eh and 12h are deduplicated by flag number. Cleaning flag 20 or 21 suppresses the separate 0Ch cleaning-request deduction. Critical and Warning categories may both contribute; media-life flag 19 contributes its informational usage rule. The fleet score is the **minimum asset score**, or `null` when there are no assets. Scores from v2's report-wide `triage-v1` model are recomputed during migration, not compared as equivalent points.

Grades (heuristic): A 90–100, B 75–89, C 60–74, D 40–59, F 0–39. Grade A with gaps is **unknown**, not a healthy verdict. `assessment` is `attention` if any rule matches, otherwise `unknown` if gaps exist, otherwise `clear`. `coverage` is complete only for this model's selected signals. It does not mean all possible faults were observed. Missingness does not deduct points by itself except the explicitly scored library-capture and collection-error rules.

## Rule ledger

Source keys resolve to public URLs and access dates below. **Heuristic** applies to every row, including the positive-count and temperature deductions.

| Rule ID | Deduction | Trigger / handling | Public definition source | Weight basis |
| --- | ---: | --- | --- | --- |
| `alert-critical` | 35 | At least one active Critical drive TapeAlert in 2Eh/12h | [SSC alerts](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf) | Heuristic |
| `alert-warning` | 15 | At least one active Warning drive TapeAlert | SSC alerts | Heuristic |
| `media-life-alert` | 10 | Nearing-media-life flag 19 decimal (13h) | [SSC cleaning alignment](https://www.t10.org/ftp/t10/document.06/06-235r0.pdf) | Heuristic |
| `uncorrected-errors` | 25 | Positive total uncorrected count on write/read pages 02h/03h | [LTO reference](https://www.ibm.com/support/pages/system/files/inline-files/LTO%20SCSI%20Reference_GA32-0928-05%20%28EXTERNAL%29_0.pdf) | Heuristic |
| `non-medium-errors` | 10 | Positive non-medium count on 06h | LTO reference | Heuristic |
| `temperature-limit` | 20 | Current temperature exceeds drive's own reference on 0Dh, compatible Celsius units; 255 is unavailable | LTO reference | Heuristic |
| `cleaning-request` | 15 | 0Ch reports required cleaning; suppressed if flags 20/21 already contribute | SSC cleaning alignment | Heuristic |
| `cleaning-age` | 5 | ≥100 motion hours since last cleaning, 14h | [SSC device statistics](https://www.t10.org/ftp/t10/document.05/05-213r3.pdf) | **Unverified threshold and weight**, not a cleaning schedule |
| `mam-loads` | 10 | Cartridge MAM 0003h ≥10000 loads | LTO reference | **Unverified threshold and weight**, not a retirement limit |
| `mam-lifetime` | 5 | MAM 0220h + 0221h ≥1000000000 MiB | LTO reference | **Unverified threshold and weight**, not native capacity or full passes |
| `head-hours` | 5 | Lifetime medium-motion hours ≥20000, 14h | SSC device statistics | **Unverified threshold and weight**, not predicted remaining life |
| `library-consistency` | 20 | Duplicate barcode, empty-with-barcode, or occupied source-slot warning | [SMC element information](https://www.t10.org/ftp/t10/document.08/08-066r0.pdf) | Heuristic; captures may be taken during other applications' changes |
| `library-coverage` | 15 | Absent, truncated/count-inconsistent capture, or unobserved source slot | SMC element information | Heuristic; evidence quality, not proof of a mechanical fault |
| `collection-errors` | 10 | One or more relevant collection errors (asset device or host-wide `null` device) | [sg_logs interface](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8) | Heuristic; collection failure is not a hardware diagnosis |

## Public references and verification

Access date for **every URL in this document: 2026-10-18**. No paid standard, private reference, identifying form, customer capture or site material was used. Sources are factual references; fixtures and rule prose are original synthetic material.

- **SSC alerts:** public T10 SSC-3 proposal 05-154r2, TapeAlert flag definitions and severity. The packaged flag catalog retains source references. [Public proposal](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf).
- **SSC cleaning alignment:** public draft-change proposal 06-235r0, decimal 19/20/21 (13h/14h/15h) meanings and clearing conditions. Drives can use older display names. [Public proposal](https://www.t10.org/ftp/t10/document.06/06-235r0.pdf).
- **SSC device statistics:** public SSC-3 draft-change proposal 05-213r3, page 14h (lifetime counters and cleaning age). [Public proposal](https://www.t10.org/ftp/t10/document.05/05-213r3.pdf).
- **LTO reference:** public IBM LTO SCSI Reference GA32-0928-05, dated 2022-02-28. Sections 6.4.2/3/4, 6.4.6, 6.4.12, 6.4.14 and 6.5.2 define selected counters, temperature, device/volume statistics and MAM. MAM load counts saturate; lifetime MiB read/written are usage totals. Vendor error counters may include recovery outcomes; interpret in model/firmware context. [Public vendor manual](https://www.ibm.com/support/pages/system/files/inline-files/LTO%20SCSI%20Reference_GA32-0928-05%20%28EXTERNAL%29_0.pdf).
- **SMC element information:** public SMC-3 proposal 08-066r0 describes element occupancy/status information. Barcode/source-slot checks are our consistency policy, not a standard fault detector. [Public proposal](https://www.t10.org/ftp/t10/document.08/08-066r0.pdf).
- **sg_logs interface:** upstream utility documentation describes LOG SENSE decoding/options and reset/select behavior. Our fixed grammar omits state-changing options. [Public upstream manual](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8).

Direct full-draft SSC/SMC PDF endpoints were unavailable through the research tool. The accessible T10 draft-change proposals above and public LTO manual were used instead. No claim is made that every later standard revision or vendor implementation matches these decoded labels.

## Observation contract and limits

The model consumes decoded text through existing parsers; no raw CDB, LOG SELECT, counter reset, vendor maintenance mode, or new vendor-only log page is introduced. Read-only 00h, 02h, 03h, 06h, 0Ch, 0Dh, 0Eh, 12h, 14h, 17h and 2Eh remain the exact allowlist. Page 17h observations are retained for capacity/history context; they do not add another usage deduction. Optional MAM uses selected read-only attributes only. TapeAlert reads may acknowledge flags; TEST UNIT READY can consume unit attention. Coordinate collection with the owning application.

Exact decoded labels and aliases accepted for scoring live in `tapediag/scoring.py`. Required numerical fields must be finite, nonnegative, unambiguous and have compatible units. Booleans, strings, negative values, wrong units, duplicate labels and nonzero subpages are unavailable. Corrected-error totals alone are not scored. Temperature comparisons accept C/Celsius; raw numeric counters use no unit unless explicitly documented. Cleaning/head ages accept hours or the public decoded label's implicit hours. Upstream sg_logs labels `Media motion (head) hours since last successful cleaning operation`, `Lifetime media motion (head) hours` and `Cleaning action required (or in progress)` are also recognized ([public decoder source](https://raw.githubusercontent.com/hreinecke/sg3_utils/master/src/sg_logs.c), accessed 2026-10-18). Standard cleaning age is motion time, not calendar age; it must not be substituted with a vendor page's minutes counter.

Drive coverage checks: all 64 TapeAlert flags, usable 02h/03h/06h counters, compatible 0Dh current/reference, 0Ch cleaning state (or active cleaning alert), cleaning/head hours, MAM loads/lifetime read/write, and relevant collection errors. An empty drive can legitimately have no MAM: its score remains qualified by the gap. Unknown fields are retained by the parser but cannot silently become scoring inputs.

Library checks count captured drive/slot/IE elements against the header and review barcode/source-slot consistency. Empty slots, empty drive elements and empty source slots for loaded drives are normal. No drive-to-changer association is inferred from element numbers. `mtx status` cannot establish door, sensor or complete element exception state, so **library coverage always carries that limitation**. Library scoring is an inventory audit, not a robotics health assessment.

`tapediag validate` checks the structural schema and recomputes health to catch altered scores/reasons/grades. Its v3 semantic checks include unique asset/device IDs and TapeAlert catalog/partition consistency. The published JSON Schema is structural; external validators alone cannot perform all model checks. The browser checks structure and displayed score arithmetic; use CLI validation for full observation-to-model integrity before importing externally edited JSON.

## Example and changes

`fixtures/fleets/` contains three invented fleets, each with three dated snapshots and LTO-7/8/9 drives plus a 48-slot library. Latest minimum scores: ALPHA 100, BRAVO 70, CHARLIE 0. BRAVO's cleaning alert, cleaning age and MAM load threshold illustrate additive reasons. CHARLIE illustrates error totals, alerts, temperature and usage thresholds, plus an incomplete inventory capture. These are examples, not calibration data.

Any changed threshold, source interpretation, deduction or coverage requirement must receive a new model ID and matching tests/docs. Schema v3 does not imply future scoring models are comparable. `watch` compares reports under the supported model, reports missing coverage and counter decreases, and never infers a rate from lifetime totals or a reset.
