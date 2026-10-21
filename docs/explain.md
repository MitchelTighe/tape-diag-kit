# Offline code explanations

`explain` looks up a small packaged catalogue. It uses no device, subprocess,
network, runtime download or external account. Public URLs are citations only.

```sh
python3 -m tapediag explain tapealert:20
python3 -m tapediag explain sense:2/3a/00
python3 -m tapediag explain asc:29/00
python3 -m tapediag explain page:0x31
python3 -m tapediag explain density:0x5e
```

Namespaces prevent decimal/hex confusion:

| Namespace | Syntax | Coverage |
| --- | --- | --- |
| `tapealert` | Decimal or `0x` byte, e.g. `20` or `0x14` | Existing SSC drive catalogue, positions 1–64; reserved/obsolete positions remain explicitly undefined |
| `sense` | Hex key/ASC/ASCQ, e.g. `2/3a/00` or `02/3a/00` | Sense key labels plus a small ASC/ASCQ subset; does not decode a sense buffer or validate every key/code pairing |
| `asc` | Two hex bytes separated by `/`, e.g. `3a/00` | 00/00, 00/01, 00/02, 00/05, 00/17, 04/00, 04/01, 04/18, 11/00, 27/00, 28/00, 29/00, 3a/00 |
| `page` | Decimal or `0x` byte | Existing standard log-page names plus explicitly vendor-specific 31h context |
| `density` | Decimal or `0x` byte | Existing mt-st code subset; not a capacity or compatibility verdict |

Names are case-insensitive. A valid unknown code returns `known: false`, public
sources and guidance to consult the exact model reference; no diagnosis is
invented. The combined sense result can name a sense key while its ASC remains
unknown. Malformed/out-of-range codes return exit 2. All successful lookups,
including unknowns, return exit 0. `--execute` is refused. Add `--html OUTPUT.html`
for an escaped static evidence page; JSON remains on stdout.

`tapediag-explanation-v1` JSON includes code, known/name/guidance, sources,
catalogue date and scope. Advice is original triage prose, not a service
procedure, executable command or vendor endorsement. Confirm peripheral type:
SSC drive TapeAlert meanings must not be applied to SMC libraries; page numbers
can also differ across disk/tape profiles. The 04/18 ASC example is changer
door evidence, not generic tape-drive evidence. No supplied sense-key/ASC
combination is represented as a standards conformance check.

Sources checked 2026-10-20:

- [T10 public numeric ASC/ASCQ assignments](https://www.t10.org/lists/asc-num.txt) and [sense key index](https://www.t10.org/lists/2sensekey.htm).
- [SSC TapeAlert proposal 05-154r2](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf); existing [catalogue/profile caveats](tapealert.md).
- [sg3_utils page decoder](https://github.com/hreinecke/sg3_utils/blob/master/src/sg_logs.c) and [vendor page decoder](https://github.com/hreinecke/sg3_utils/blob/master/src/sg_logs_vendor.c).
- [mt-st public density table](https://github.com/iustin/mt-st/blob/main/mt.c).

`fixtures/v4/explain-codes.txt` contains original synthetic lookup examples;
no manual prose, vendor software or real device capture is shipped. The small
catalogue is intentionally finite and can be expanded only with public evidence,
synthetic examples and tests. It is not refreshed during a lookup.
