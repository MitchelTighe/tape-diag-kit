# TapeAlert sequential-access profile

The decoder addresses all 64 numbered positions in the drive TapeAlert page `0x2e`. A flag missing from a capture is **unknown**, never silently clear. The CLI returns active flag details, observed/inactive/unobserved numbers, unknown out-of-range parameters, and parse warnings.

Names and severities follow the factual drive profile in public [T10/05-154r2, table x+2 (PDF pages 6–7)](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf). This is a historical SSC-3 working proposal, not the current published standard. Compare the device vendor's supported flag list: [IBM LTO TapeAlert](https://www.ibm.com/docs/en/ts4500-tape-library?topic=flags-tapealert-supported-by-lto-tape-drives) and [HPE LTO-7 TapeAlert](https://support.hpe.com/hpesc/public/docDisplay?docId=sd00006909en_us&docLocale=en_US&page=GUID-D7147C7F-2016-0901-0922-0000000005A5.html). A vendor can support a subset or give different service guidance. These are **drive** meanings; a medium changer uses a different SMC TapeAlert table.

Critical denotes failure or imminent failure; Warning denotes a condition that can lead to failure; Info denotes status information. In this selected profile, hard error (3) is Warning, and clean now (20) is Critical. Positions 40–46 are obsolete; 47–49 and 61–64 are reserved. Their `Info` severity is only a display convention: they have `defined: false`, and an active value generates a warning. It is not a standard-assigned severity or reassurance that an unknown flag is harmless.

The action text below is original advisory wording. It is never executed, and does not authorize writing, movement, cleaning, repair or recovery. Follow the device vendor and the application's retention/recovery procedure. Reading this page may acknowledge latched flags on some devices; this toolkit does not change that behavior.

| Decimal | Hex | Name | Severity | Recommended review/action |
| --- | --- | --- | --- | --- |
| 1 | `01h` | Read warning | Warning | Check read-error trends; isolate media and drive with approved procedures. |
| 2 | `02h` | Write warning | Warning | Review write-error trends and media condition before the next job. |
| 3 | `03h` | Hard error | Warning | Check flags 4, 5 and 6 to narrow the failure. |
| 4 | `04h` | Media | Critical | Preserve readable data under your recovery procedure and retire faulty media. |
| 5 | `05h` | Read failure | Critical | Investigate media and drive; preserve the original cartridge for recovery. |
| 6 | `06h` | Write failure | Critical | Review the failed job and isolate the cartridge from the drive fault. |
| 7 | `07h` | Media life | Warning | Schedule replacement of the cartridge and preserve required data. |
| 8 | `08h` | Not data grade | Warning | Use media approved for the drive and the intended retention policy. |
| 9 | `09h` | Write protect | Critical | Verify that cartridge protection matches the intended job; do not change it automatically. |
| 10 | `0ah` | No removal | Info | Check the application's media-removal reservation before operator intervention. |
| 11 | `0bh` | Cleaning media | Info | Confirm that the loaded cartridge is intended for cleaning. |
| 12 | `0ch` | Unsupported format | Info | Check drive-generation and cartridge-format compatibility. |
| 13 | `0dh` | Recoverable mechanical cartridge failure | Critical | Follow the vendor's safe cartridge recovery procedure. |
| 14 | `0eh` | Unrecoverable mechanical cartridge failure | Critical | Stop using the cartridge and request qualified service. |
| 15 | `0fh` | Memory chip in cartridge failure | Warning | Review cartridge-memory errors and plan media replacement. |
| 16 | `10h` | Forced eject | Critical | Check job completion and cartridge integrity after the forced removal. |
| 17 | `11h` | Read only format | Warning | Use a drive and media combination that supports the intended operation. |
| 18 | `12h` | Tape directory corrupted on load | Warning | Preserve the data and consult the application recovery procedure. |
| 19 | `13h` | Nearing media life | Info | Plan cartridge replacement before its service limit. |
| 20 | `14h` | Clean now | Critical | Arrange an approved cleaning cycle with compatible cleaning media. |
| 21 | `15h` | Clean periodic | Warning | Schedule cleaning according to the drive's maintenance instructions. |
| 22 | `16h` | Expired cleaning media | Critical | Replace the cleaning cartridge with an unused or valid one. |
| 23 | `17h` | Invalid cleaning tape | Critical | Select a cleaning cartridge approved for this drive. |
| 24 | `18h` | Retension requested | Warning | Consult the drive vendor; this toolkit never repositions tape. |
| 25 | `19h` | Dual-port interface error | Warning | Review both interface paths and transport error counters. |
| 26 | `1ah` | Cooling fan failure | Warning | Check cooling and request service for the failed fan. |
| 27 | `1bh` | Power supply failure | Warning | Check power redundancy and arrange service. |
| 28 | `1ch` | Power consumption | Warning | Check the drive's power requirements and supply condition. |
| 29 | `1dh` | Drive maintenance | Warning | Schedule the vendor's prescribed maintenance. |
| 30 | `1eh` | Hardware A | Critical | Preserve diagnostics and request hardware service. |
| 31 | `1fh` | Hardware B | Critical | Preserve diagnostics and consult the vendor's fault-isolation procedure. |
| 32 | `20h` | Interface | Warning | Check interface cabling and transport errors using approved procedures. |
| 33 | `21h` | Eject media | Critical | Consult the vendor's safe removal procedure; no eject command is issued here. |
| 34 | `22h` | Down-load fail | Warning | Review the vendor's update procedure with support; this toolkit never updates firmware. |
| 35 | `23h` | Drive humidity | Warning | Check the environment against the drive's humidity limits. |
| 36 | `24h` | Drive temperature | Warning | Check airflow and ambient temperature against vendor limits. |
| 37 | `25h` | Drive voltage | Warning | Have the power supply and voltage condition checked. |
| 38 | `26h` | Predictive failure | Critical | Plan drive replacement and preserve diagnostics for service. |
| 39 | `27h` | Diagnostics required | Warning | Arrange vendor-approved diagnostics after reviewing active workloads. |
| 40 | `28h` | Obsolete | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 41 | `29h` | Obsolete | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 42 | `2ah` | Obsolete | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 43 | `2bh` | Obsolete | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 44 | `2ch` | Obsolete | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 45 | `2dh` | Obsolete | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 46 | `2eh` | Obsolete | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 47 | `2fh` | Reserved | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 48 | `30h` | Reserved | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 49 | `31h` | Reserved | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 50 | `32h` | Lost statistics | Warning | Treat historical statistics as incomplete and retain the current capture. |
| 51 | `33h` | Tape directory invalid at unload | Warning | Consult the backup application's directory recovery procedure. |
| 52 | `34h` | Tape system area write failure | Critical | Preserve the job logs and investigate the cartridge's system area. |
| 53 | `35h` | Tape system area read failure | Critical | Preserve the cartridge and consult the vendor's recovery procedure. |
| 54 | `36h` | No start of data | Critical | Check format compatibility and seek recovery guidance before reusing media. |
| 55 | `37h` | Loading failure | Critical | Inspect media condition under the vendor's safe handling procedure. |
| 56 | `38h` | Unrecoverable unload failure | Critical | Request service; do not force the cartridge from the drive. |
| 57 | `39h` | Automation interface failure | Critical | Review the drive-to-library interface and request service. |
| 58 | `3ah` | Firmware failure | Warning | Preserve diagnostics and consult support; do not attempt an automatic update. |
| 59 | `3bh` | WORM medium integrity check failed | Warning | Preserve the WORM cartridge and investigate integrity with the application vendor. |
| 60 | `3ch` | WORM medium overwrite attempted | Warning | Review the application's append and retention behavior for WORM media. |
| 61 | `3dh` | Reserved | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 62 | `3eh` | Reserved | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 63 | `3fh` | Reserved | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |
| 64 | `40h` | Reserved | Info | Preserve the raw flag and consult the device vendor; no standard action is assigned. |

Input formats: sg_logs compact `Flag01h: 0  02h: 1` (hexadecimal identifiers), named `Hard error: 1`, and explicit decimal/0x identifiers such as `TapeAlert Flag 20: set` or `Parameter code 0x14 = 1`. `Cleaning required` is an alias for flag 20. Zero/clear/false and one/set/true are recognized. Conflicting observations retain the active state and emit a warning. A partial named report cannot prove that the other flags were clear.

Only positions actually observed are classified as active or inactive. The catalog itself is packaged so offline parsing needs no documentation download, network or paid API. Source and fixture licensing details are in [fixtures/SOURCES.md](../fixtures/SOURCES.md).
