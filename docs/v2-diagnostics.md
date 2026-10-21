# v2 diagnostics and interpretation

All fixture observations are invented. Parser support means support for the documented **decoded text** grammars, not binary SCSI responses or vendor certification. Unknown log-page text is retained. No proprietary/site data informed the implementation.

## Public references and exact command allowlist

The generic log parser handles each page below separately; `fixtures/synthetic/logpage-XX.txt` and matching golden JSON cover each. Pages are attempted once; a drive may legitimately reject an unsupported page. No fallback changes configuration. The common log collection also retains supported pages 00h and SSC volume statistics 17h from v1.

| Page | Meaning and interpretation | Public format/semantic source |
| --- | --- | --- |
| 02h | Write counters. Corrected errors are not automatically a fault; positive uncorrected totals warrant review. Lifetime/current cumulative counters are not rates. | [sg_logs decoder](https://github.com/hreinecke/sg3_utils/blob/master/src/sg_logs.c), [public LTO SCSI reference](https://download.lenovo.com/servers/mig/systems/support/system_x_pdf/tape_scsi_reference.pdf) |
| 03h | Read counters, with the same historical-counter limits. | Same sources as 02h |
| 06h | Non-medium error count. May indicate drive/interface issues; does not isolate a cause. | [sg_logs](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8) and decoder above |
| 0Ch | Sequential-access activity: bytes transferred, as labeled by the utility. Never converts host bytes into native medium usage. | Public LTO SCSI reference above; sg_logs decoder |
| 0Dh | Current and reference temperatures. A missing or 255 value is unavailable; compare compatible units, not an invented universal threshold. | sg_logs decoder and public LTO SCSI reference |
| 0Eh | Start-stop and load-unload cycle counters from SPC. Optional on tape; no universal retirement threshold. | [SPC-4 project/drafts](https://www.t10.org/members/w_spc4.htm), sg_logs decoder |
| 12h | TapeAlert response grouped `Flag01h: 0 02h: 1 ...`. Hexadecimal flag positions map to the SSC drive profile only. The flags may differ from latched page 2Eh; results remain separate. Never apply drive meanings to an SMC library. | [sg_logs response decoder](https://github.com/hreinecke/sg3_utils/blob/master/src/sg_logs.c), [SSC drive TapeAlert proposal](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf) |
| 14h | Device statistics such as lifetime loads/power-on hours. Used as observations, not universal wear limits. | Public LTO SCSI reference and sg_logs decoder above |

Exact command for every row: `sg_logs --readonly --page=0xXX /dev/sgN`. The complete allowed set is `0x00 0x02 0x03 0x06 0x0c 0x0d 0x0e 0x12 0x14 0x17 0x2e`. No raw CDBs, wildcard pages, subpage forwarding, reset, save or select flags are accepted.

## MAM / cartridge memory

`tapediag mam /dev/sg9` plans six exact commands:

```text
sg_read_attr --readonly --first=ID --filter=ID /dev/sg9
```

`ID` must be one of the six identifiers below; both options must have the **same** identifier. `--first` requests attributes at/after the ID; `--filter` restricts utility output to that one attribute. The drive may internally return more attributes, but their text is not retained. No arbitrary attributes, write-attribute utility, raw output or flags are accepted. Defaults are partition 0, logical volume 0; this is not a multi-partition census.

| SPC attribute ID | Attribute | Unit / handling |
| --- | --- | --- |
| 0003h | Load count | Count of full loads; not 0002h (TapeAlert flags). |
| 0220h | Total mebibytes written in medium life | MiB, 1,048,576 bytes. |
| 0221h | Total mebibytes read in medium life | MiB. |
| 0222h | Total mebibytes written in current/last load | MiB. |
| 0223h | Total mebibytes read in current/last load | MiB. |
| 0401h | Medium serial number | Always SYNTH form; no original, suffix or hash retained. |

Public references: [SPC-4 project/draft index](https://www.t10.org/members/w_spc4.htm), [sg_read_attr upstream attribute table](https://github.com/hreinecke/sg3_utils/blob/master/src/sg_read_attr.c), [sg_read_attr man page](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_read_attr.8), [public vendor reproduction of the standard attributes](https://docs.oracle.com/cd/E19190-01/CRCM2172/CRCM2172.pdf) (standard device/medium attribute tables). Older manuals use “MBytes” for these units; the parser normalizes the documented labels to MiB. The upstream utility currently cites SPC-5; the IDs in this subset predate SPC-4. No paid standard was acquired or copied.

The parser recognizes upstream named `Load count: 42` output and ID-prefixed forms, omits unknown attribute values, and emits warnings for unavailable/malformed values and duplicates. It does not infer that a MAM read succeeded just because a process exited zero.

## Inquiry, firmware, VPD and topology

`tapediag inquiry /dev/sg9` plans standard `sg_inq /dev/sg9` plus `sg_inq --export --page=0x80 /dev/sg9` and `sg_inq --export --page=0x83 /dev/sg9`. Firmware is the inquiry product revision. [Upstream sg_inq](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_inq.8) documents export keys `SCSI_SERIAL` and `SCSI_IDENT_*`. Serial and **all** device designators (not just NAA WWNs) become SYNTH placeholders. For these new VPD/MAM operations, the subprocess boundary removes raw original identity text and diagnostic stderr before JSON/state persistence. Synthetic `SYNTH-` identifiers are preserved. This is not a general sanitizer for v1 raw ITDT/LTFS or arbitrary capture files; never collect or share private captures here.

`tapediag topology` wraps only `sg_map -x` and parses generic node, H:C:T:L, SCSI peripheral type 1/8 and optional tape/changer node. Missing mappings stay null. It complements `inventory` (`lsscsi -g`); neither matches drives to changer elements by number. References: [sg_map](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_map.8), [lsscsi](https://doug-gilbert.github.io/scsi/lsscsi.html). Device index equality is never assumed.

Density fallback uses factual codes from the public [mt-st table](https://github.com/iustin/mt-st/blob/main/mt.c), supplementing [mt status documentation](https://github.com/iustin/mt-st/blob/main/mt.1). Explicit captured descriptions remain as supplied; missing descriptions use this small table:

| Code | Name | Code | Name |
| --- | --- | --- | --- |
| 00h | Default | 40h | DLT1 40 GB, or Ultrium |
| 42h | LTO-2 | 44h | LTO-3 |
| 46h | LTO-4 | 58h | LTO-5 |
| 5Ah | LTO-6 | 5Ch | LTO-7 |
| 5Dh | LTO-7-M8 | 5Eh | LTO-8 |
| 60h | LTO-9 | Other | Unknown density |

## Changer consistency

The public [mtx status output](https://github.com/mtx-org/mtx/blob/master/mtx/mtx.doc) documents occupancy, source slots and volume tags. `library_checks()` reports duplicate exact primary/alternate barcodes across different elements, empty elements retaining tags, unobserved source slots, occupied source slots and IE occupancy. An occupied source slot may have been reused; it is a warning, not proof of a failed robot. **A full drive with an empty source slot is expected after loading** and yields an informational observation. Missing barcodes do not mean empty elements. IE “Full/Empty” says nothing about door, interlock or application access state. No inventory, load/unload, transfer or movement command is accepted.

## Transparent health policy

`health.summarize()` applies the following original triage policy. References explain the signals; the point weights and score thresholds are **toolkit policy**, not SCSI/vendor recommendations. Start at 100, subtract each matching rule at most once across the report, clamp at 0. A score below 60 displays fail; 60–99 displays warn; 100 displays pass only when required health observations are covered. Missing observations produce warn/incomplete even at 100. This is neither ML nor a failure forecast.

| Rule | Deduction | Evidence / public reference |
| --- | --- | --- |
| alert-critical | 35 | At least one active Critical SSC drive TapeAlert on 2Eh or 12h. [Public SSC flag profile](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf) |
| alert-warning | 15 | At least one active Warning SSC drive TapeAlert on 2Eh or 12h. [Same profile](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf) |
| uncorrected-errors | 25 | Positive uncorrected read/write error counter on 02h/03h. [sg_logs](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8) |
| non-medium-errors | 10 | Positive non-medium error count on 06h. [sg_logs](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8) |
| temperature-limit | 20 | Current temperature exceeds compatible drive-reported reference, excluding 255. [sg_logs decoder](https://github.com/hreinecke/sg3_utils/blob/master/src/sg_logs.c) |
| changer-consistency | 10 | One or more consistency warnings above. [mtx](https://github.com/mtx-org/mtx/blob/master/mtx/mtx.1) |
| collection-errors | 10 | One or more collection errors; missing observations can mask conditions. [sg_logs exit semantics](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8) |

Every matched rule includes evidence, deduction, and public URL in JSON/HTML. Corrected errors, lifetime loads, bytes and cycle counts alone do not subtract points. Cartridge usage does not establish media damage. Supported-page advertisements do not prove every counter was observed.

The direct T10 SPC-4 r36/r37 draft PDF endpoints were unavailable in this environment; the public project index was readable. A public documentation page's linked `T10B-PDocx.zip` also returned HTTP 404. The factual attribute subset was therefore cross-checked against upstream sg3_utils and the linked public vendor tables, rather than represented as a newly verified full SPC-4 reproduction. Direct clause-by-clause SPC-4 confirmation remains documented in REPORT; no access form, identifying details, paid standard or membership was used.
