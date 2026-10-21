# Captured-hex log decoding and drive evidence trends

`log-decode` decodes one saved LOG SENSE page. `log-trend` compares many saved
pages using an explicit JSON manifest. Both run offline with standard-library
Python only. No new live page, hex collection command, CDB, reset or LOG SELECT
route is added. The report schemas and `triage-v3.0.0` model remain unchanged.

```sh
python3 -m tapediag log-decode --from-file fixtures/v4/log-2e.txt
python3 -m tapediag log-decode --from-file fixtures/v4/log-0c.txt
python3 -m tapediag log-decode --from-file fixtures/v4/log-17.txt
python3 -m tapediag log-decode --from-file fixtures/v4/log-31.txt --profile lto5-6-capacity
python3 -m tapediag log-trend --from-file fixtures/v4/log-series.json
```

Add `--html OUTPUT.html` for a local evidence view; JSON is always emitted to
stdout. Exit 0 means parsing/analysis completed, not drive PASS. Inspect warnings
and unavailable values. Exit 2 means invalid/refused input or local I/O failure.
`--execute` is refused before input access. No files named in a manifest are
opened: all captured hex is embedded data, and extra manifest keys are refused.

## Capture grammar and public layouts

Supply whitespace-separated two-digit hex bytes, optional `#` comments and
optional exact byte offsets such as `0000: 2e 00`. Tabs/case variations work;
ASCII gutters, inquiry banners, `0x` byte prefixes and concatenated hex strings
are refused. Convert a saved capture deliberately; the parser does not guess
which prose contains bytes. Text is limited to 1 MiB and decoded bytes to 65,539
(four-byte header plus 16-bit payload length). Exactly one complete page is
required. A mismatched length, truncated descriptor or duplicate parameter code
is an error. SPF and subpage fields are checked; only subpage zero is decoded.

The four-byte page header uses low six page-code bits, SPF bit 6, subpage byte,
and big-endian payload length. Supported pages contain descriptors with a
big-endian two-byte parameter code, control byte, one-byte length, then value.
Control bytes/raw payloads remain in JSON; parameters with unsupported low two
format/linking bits stay unavailable. Unknown pages/subpages stay wholly opaque;
unknown parameters retain bytes, with null interpreted values. Raw bytes may
contain identifiers: this command is not a sanitizer for private captures.

| Page/profile | Decoded subset | Unit/availability |
| --- | --- | --- |
| 2Eh, `ssc` | Flags 1–64, one-byte values 0 or 1 | Other lengths/reserved bits → null; missing flags unknown |
| 0Ch, `ssc` | Parameters 0–3 host/medium read/write byte counters; 0100h cleaning state | Counters remain exact integers in bytes; cleaning value is boolean. Accept 1–8 byte integers. |
| 17h, `ssc` | Page-valid bit (0); thread count (1); written sets/retries/unrecovered errors (2/3/4); read sets/retries/unrecovered errors (7/8/9); native/used capacity (16h/17h) | Counts or MB as labeled; 1–8 byte values. Missing/false page-valid makes other interpreted values null. All-ones capacity is unavailable. |
| 31h, `lto5-6-capacity` only | Four-byte parameters 1–4: main/alternate remaining and maximum capacity | MiB; gauges, never monotonically increasing error counters |

The `ssc` default leaves **31h uninterpreted**. Page 31h is vendor-specific;
the opt-in profile names the historical LTO-5/6-style layout in the public
utility, not an autodetected vendor, universal LTO meaning, or firmware support
claim. An operator must check their exact device reference. MB and MiB are kept
distinct. These narrow decoded subsets omit partition descriptors, strings,
other subpages and vendor extensions; raw bytes preserve them for review.

Public references checked 2026-10-20:

- [T10 SSC TapeAlert proposal 05-154r2](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf): page/parameter layout and flag meanings.
- [sg3_utils public decoder](https://github.com/hreinecke/sg3_utils/blob/master/src/sg_logs.c): `show_sequential_access_page` and `show_volume_stats_pages`, including 17h validity and capacity sentinel handling.
- [sg3_utils vendor decoder](https://github.com/hreinecke/sg3_utils/blob/master/src/sg_logs_vendor.c): `show_tape_capacity_page`, four-byte parameters and MiB labels; explicitly historical/vendor scope.
- [Public LTO SCSI reference](https://download.lenovo.com/servers/mig/systems/support/system_x_pdf/tape_scsi_reference.pdf): LOG SENSE framing and sequential-access device observations. Public manuals/implementations describe formats, not the toolkit's comparison policy.

Fixtures `fixtures/v4/log-*.txt` are original, small synthetic examples built
from those public layouts; no manual page, upstream code, dump or customer
capture is redistributed. Values, identities and timestamps are invented.
The generator is `PYTHONPATH=. python3 scripts/generate-v4-fixtures.py`.

## Many-snapshot manifest

The complete runnable example is `fixtures/v4/log-series.json`. A minimal
manifest looks like this (empty page lists intentionally represent gaps):

```json
{
  "format": "tapediag-log-series-v1",
  "asset_id": "SYNTH-DRIVE-V4",
  "page_control": "current-cumulative",
  "snapshots": [
    {"captured_at": "2026-10-16T00:00:00Z", "medium_id": null, "pages": []},
    {"captured_at": "2026-10-17T00:00:00Z", "medium_id": null, "pages": []}
  ]
}
```

Each page is `{"profile":"ssc","hex":"2e 00 00 05 00 14 00 01 01"}`.
The caller asserts stable drive identity and current-cumulative page control:
the response bytes cannot prove either. Other page controls are refused rather
than compared as cumulative counts. Up to 1,000 snapshots, 32 distinct
page/subpages per snapshot and a 16 MiB input file are supported. Capture times
must be RFC3339 with timezone and strictly increase in UTC. Labels are nonempty
and at most 128 characters. `medium_id` may be null when not known. JSON duplicate
keys, nonfinite numbers and nesting beyond 64 levels are rejected.

`tapediag-log-trend-v1` retains decoded snapshots and adjacent changes. Each
change has page/subpage/code/name/unit, before/after times, previous/current
values, kind and nullable delta. Only comparable counters get nonnegative
deltas. Unknown/missing values, changed encoding/profile/control, unconfirmed
medium identity or decreases suppress deltas. A decrease is `reset-or-wrap`;
it might also mean replacement, not improved health. Volume-scoped fields need
the same non-null `medium_id` at both times. Capacity is a gauge and gets no
counter delta. Flags/cleaning state produce state changes. Gaps break continuity.
Rates, saturation detection, failure forecasts and automatic service decisions
are intentionally absent. Counter increments warrant contextual review, not a
universal failure threshold. JSON integers remain exact in Python; consumers
using IEEE-754 numbers must preserve integers above 2^53−1 themselves.

The four synthetic snapshots show byte/error growth, a cleaning alert, then a
counter decrease and declared medium change. They are evidence examples, not a
real drive-health assessment. The bounded stdlib fuzz harness is
`PYTHONPATH=. python3 scripts/fuzz-v4.py --seconds 30`.
