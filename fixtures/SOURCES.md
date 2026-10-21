# Fixture provenance

Every saved sample is original synthetic text, except the explicitly licensed LTFS prefix below. Nothing was recorded from a real site or device. Public sources are references only; no operational data was sent to them. `sources.json` is the machine-readable inventory, including each golden JSON and sample-host copy.

Project-authored synthetic fixtures and expectations are MIT. A publicly readable manual does not automatically grant an open documentation license. Excerpts below retain the stated status; no proprietary document is represented as MIT. These are short factual command-output fragments, not copied implementation code. See [NOTICES.md](NOTICES.md).

## Retained public excerpt and synthetic replacements

Only `public/ltfs-device-prefix.txt` remains an upstream excerpt: an abbreviated,
non-identifying device-list prefix from the [LTFS README](https://github.com/LinearTapeFileSystem/ltfs/blob/main/README.md),
under BSD-3-Clause. Its notice is retained in [NOTICES.md](NOTICES.md).

The four uncertain documentation excerpts and their derived expectations have
been removed from the current source. Independently authored replacements use
invented values; the public URLs in `sources.json` describe grammar only:

| Synthetic fixture | Purpose | License |
| --- | --- | --- |
| `synthetic/inquiry-identity.txt` | Invented vendor, product and revision | MIT |
| `synthetic/library-legacy.txt` | Headerless single-drive grammar, nonconsecutive invented slots | MIT |
| `synthetic/itdt-no-records.txt` | Unrecognized/incomplete input must remain unknown | MIT |
| `synthetic/inventory-disk-only.txt` | Invented disk row is excluded from tape inventory | MIT |

No mhVTL execution or captured device output is claimed. The new
`mhvtl-synthetic/` walkthrough uses original saved text and no emulator process.

## Original synthetic fixtures

| Fixture | Format reference URL | License |
| --- | --- | --- |
| `synthetic/inventory.txt` | [format reference](https://doug-gilbert.github.io/scsi/lsscsi.html) | MIT |
| `synthetic/inventory-missing-generic.txt` | [format reference](https://doug-gilbert.github.io/scsi/lsscsi.html) | MIT |
| `synthetic/library.txt` | [format reference](https://github.com/mtx-org/mtx/blob/master/mtx/mtx.1) | MIT |
| `synthetic/library-empty.txt` | [format reference](https://github.com/mtx-org/mtx/blob/master/mtx/mtx.1) | MIT |
| `synthetic/library-truncated.txt` | [format reference](https://github.com/mtx-org/mtx/blob/master/mtx/mtx.1) | MIT |
| `synthetic/tapealert-named.txt` | [format reference](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf) | MIT |
| `synthetic/tapealert-numeric.txt` | [format reference](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf) | MIT |
| `synthetic/tapealert-clear.txt` | [format reference](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf) | MIT |
| `synthetic/tapealert-set.txt` | [format reference](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf) | MIT |
| `synthetic/logpages.txt` | [format reference](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8) | MIT |
| `synthetic/logpages-unknown.txt` | [format reference](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8) | MIT |
| `synthetic/logpages-unavailable.txt` | [format reference](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8) | MIT |
| `synthetic/drive-status.txt` | [format reference](https://github.com/iustin/mt-st/blob/main/mt.1) | MIT |
| `synthetic/drive-not-ready.txt` | [format reference](https://github.com/iustin/mt-st/blob/main/mt.1) | MIT |
| `synthetic/ltfs.txt` | [format reference](https://github.com/LinearTapeFileSystem/ltfs/blob/main/README.md) | MIT |
| `synthetic/itdt-scan.txt` | [format reference](https://www.ibm.com/support/pages/system/files/inline-files/IBM%20Tape%20Device%20Drivers%20and%20Diagnostic%20Tool%20Users%20Guide.pdf) | MIT |
| `synthetic/itdt-inquiry.txt` | [format reference](https://www.ibm.com/support/pages/system/files/inline-files/IBM%20Tape%20Device%20Drivers%20and%20Diagnostic%20Tool%20Users%20Guide.pdf) | MIT |
| `synthetic/itdt-tapealert.txt` | [format reference](https://www.ibm.com/support/pages/system/files/inline-files/IBM%20Tape%20Device%20Drivers%20and%20Diagnostic%20Tool%20Users%20Guide.pdf) | MIT |
| `synthetic/unrecognized.txt` | [format reference](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf) | MIT |

All synthetic drive/changer identifiers use `SYNTH-`, barcodes use `SYN`, vendor is `SYNTH`, and all layout/position/counter values are invented. The retained LTFS prefix contains public product names, not unique device identities. Test-created sysfs directory trees in `tests/test_sysfs.py` and generated malformed cases are also original synthetic MIT fixtures; their references are the Linux [tape driver documentation](https://www.kernel.org/doc/html/latest/scsi/st.html) and [SG driver mapping documentation](https://doug-gilbert.github.io/sg_v40.html).

## Sample-host copies

| File | Original synthetic source | License |
| --- | --- | --- |
| `sample-host/drives/sg9/drive-status.txt` | `synthetic/drive-status.txt` | MIT |
| `sample-host/drives/sg9/logpages.txt` | `synthetic/logpages.txt` | MIT |
| `sample-host/drives/sg9/tapealert.txt` | `synthetic/tapealert-set.txt` | MIT |
| `sample-host/inventory.txt` | `synthetic/inventory.txt` | MIT |
| `sample-host/itdt.txt` | `synthetic/itdt-scan.txt` | MIT |
| `sample-host/libraries/sg10/status.txt` | `synthetic/library.txt` | MIT |
| `sample-host/ltfs.txt` | `synthetic/ltfs.txt` | MIT |

## Golden JSON

Each of the 36 cases in `cases.json` has `golden/<fixture-path-with-__-instead-of-/>.json`. `sources.json` records the exact original fixture, public URL and source/license status for every golden. `golden/sample-host.report.json` is the MIT expected report from the synthetic capture tree. Tests read these checked-in expectations; they never regenerate them.

## TapeAlert reference data

`../tapediag/tapealert_flags.json` records factual SSC sequential-access identifiers and severities from public [T10/05-154r2, table x+2](https://www.t10.org/ftp/t10/document.05/05-154r2.pdf). It is a historical proposal, not a claim to reproduce the current paid standard. [IBM LTO flags](https://www.ibm.com/docs/en/ts4500-tape-library?topic=flags-tapealert-supported-by-lto-tape-drives) and [HPE LTO TapeAlert page](https://support.hpe.com/hpesc/public/docDisplay?docId=sd00006909en_us&docLocale=en_US&page=GUID-D7147C7F-2016-0901-0922-0000000005A5.html) provide vendor cross-references. Those documents are copyrighted public documentation, with no open document license asserted here. Action text is original paraphrase, distributed under MIT; no vendor action paragraphs are copied. Reserved/obsolete severities are explicitly a toolkit display policy.

## v2 synthetic fixtures and scenarios

All files below are original MIT fixtures, with invented counters/layouts and SYNTH/SYN identifiers. Format references: [sg_logs](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8), [sg_read_attr attribute table](https://github.com/hreinecke/sg3_utils/blob/master/src/sg_read_attr.c), [sg_inq export grammar](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_inq.8), [sg_map](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_map.8), [mtx](https://github.com/mtx-org/mtx/blob/master/mtx/mtx.1). No new public excerpts were copied. MAM units use MiB (1,048,576 bytes); older public manuals label the same counts MBytes. The per-page fixtures and full report expectations have independent tests of key values, rule scores and flag numbers.

- `golden/scenario-cleaning-needed.json`
- `golden/scenario-degraded-media.json`
- `golden/scenario-healthy.json`
- `golden/synthetic__inquiry-vpd.txt.json`
- `golden/synthetic__library-inconsistent.txt.json`
- `golden/synthetic__logpage-02.txt.json`
- `golden/synthetic__logpage-03.txt.json`
- `golden/synthetic__logpage-06.txt.json`
- `golden/synthetic__logpage-0c.txt.json`
- `golden/synthetic__logpage-0d.txt.json`
- `golden/synthetic__logpage-0e.txt.json`
- `golden/synthetic__logpage-12.txt.json`
- `golden/synthetic__logpage-14.txt.json`
- `golden/synthetic__mam.txt.json`
- `golden/synthetic__topology.txt.json`
- `sample-host/drives/sg9/inquiry.txt`
- `sample-host/drives/sg9/mam.txt`
- `sample-host/topology.txt`
- `scenarios/cleaning-needed/drives/sg9/drive-status.txt`
- `scenarios/cleaning-needed/drives/sg9/inquiry.txt`
- `scenarios/cleaning-needed/drives/sg9/logpages.txt`
- `scenarios/cleaning-needed/drives/sg9/mam.txt`
- `scenarios/cleaning-needed/drives/sg9/tapealert.txt`
- `scenarios/cleaning-needed/inventory.txt`
- `scenarios/cleaning-needed/libraries/sg10/status.txt`
- `scenarios/cleaning-needed/topology.txt`
- `scenarios/degraded-media/drives/sg9/drive-status.txt`
- `scenarios/degraded-media/drives/sg9/inquiry.txt`
- `scenarios/degraded-media/drives/sg9/logpages.txt`
- `scenarios/degraded-media/drives/sg9/mam.txt`
- `scenarios/degraded-media/drives/sg9/tapealert.txt`
- `scenarios/degraded-media/inventory.txt`
- `scenarios/degraded-media/libraries/sg10/status.txt`
- `scenarios/degraded-media/topology.txt`
- `scenarios/healthy/drives/sg9/drive-status.txt`
- `scenarios/healthy/drives/sg9/inquiry.txt`
- `scenarios/healthy/drives/sg9/logpages.txt`
- `scenarios/healthy/drives/sg9/mam.txt`
- `scenarios/healthy/drives/sg9/tapealert.txt`
- `scenarios/healthy/inventory.txt`
- `scenarios/healthy/libraries/sg10/status.txt`
- `scenarios/healthy/topology.txt`
- `synthetic/inquiry-vpd.txt`
- `synthetic/library-inconsistent.txt`
- `synthetic/logpage-02.txt`
- `synthetic/logpage-03.txt`
- `synthetic/logpage-06.txt`
- `synthetic/logpage-0c.txt`
- `synthetic/logpage-0d.txt`
- `synthetic/logpage-0e.txt`
- `synthetic/logpage-12.txt`
- `synthetic/logpage-14.txt`
- `synthetic/mam.txt`
- `synthetic/topology.txt`

- `golden/v1-original-report.json`: exact original synthetic v1/tool-0.1.0 report from the baseline artifact, retained unchanged to verify historical compatibility. MIT; same public format references above. Its captured density description predates the v2 fixture correction and is preserved as original data.

## V3 fictional fleets (2026-10-18)

All values are original MIT synthetic data, generated by `scripts/generate-fleets.py`. No operational captures or real identifiers. Public format references: [T10 SSC device statistics](https://www.t10.org/ftp/t10/document.05/05-213r3.pdf) and [T10 SMC element information](https://www.t10.org/ftp/t10/document.08/08-066r0.pdf), accessed 2026-10-18. Full rule references are in `docs/SCORING.md`.

- `fleets/synth-alpha-20261016.json` — fictional dated snapshot; original synthetic data.
- `fleets/synth-alpha-20261017.json` — fictional dated snapshot; original synthetic data.
- `fleets/synth-alpha-20261018.json` — fictional dated snapshot; original synthetic data.
- `fleets/synth-bravo-20261016.json` — fictional dated snapshot; original synthetic data.
- `fleets/synth-bravo-20261017.json` — fictional dated snapshot; original synthetic data.
- `fleets/synth-bravo-20261018.json` — fictional dated snapshot; original synthetic data.
- `fleets/synth-charlie-20261016.json` — fictional dated snapshot; original synthetic data.
- `fleets/synth-charlie-20261017.json` — fictional dated snapshot; original synthetic data.
- `fleets/synth-charlie-20261018.json` — fictional dated snapshot; original synthetic data.

## mhvtl synthetic walkthrough

These original fixture copies exercise saved-text parsing only (MIT):

- `mhvtl-synthetic/drives/sg31/drive-status.txt`
- `mhvtl-synthetic/drives/sg31/inquiry.txt`
- `mhvtl-synthetic/drives/sg31/logpages.txt`
- `mhvtl-synthetic/drives/sg31/mam.txt`
- `mhvtl-synthetic/drives/sg31/tapealert.txt`
- `mhvtl-synthetic/inventory.txt`
- `mhvtl-synthetic/libraries/sg40/status.txt`
- `mhvtl-synthetic/topology.txt`

## Drive-test assistant fixtures

All files below are newly authored synthetic examples, accessed against vendor references on 2026-10-18. The all-zero WWPN namespace is deliberately fictional; no vendor/site serials or cartridge labels are copied. Test transcripts assert command completion only; no undocumented health-result text is invented. See [DTA source notes](../docs/DTA-SOURCES.md).

| Path | Format reference | License/status |
| --- | --- | --- |
| `dta/config.synthetic.toml` | [public grammar reference](https://www.ibm.com/support/pages/sites/default/files/inline-files/IBM%20Tape%20Device%20Drivers%20and%20Diagnostic%20Tool%20User%27s%20Guide%2020251028.pdf) | MIT; original synthetic data |
| `dta/drive-list.xml` | [public grammar reference](https://support.spectralogic.com/documentation/default-source/user-guides/xml-commandreference-v12.8.07.pdf?sfvrsn=42f961ba_14) | MIT; original synthetic data |
| `dta/inventory-home.xml` | [public grammar reference](https://support.spectralogic.com/documentation/default-source/user-guides/xml-commandreference-v12.8.07.pdf?sfvrsn=42f961ba_14) | MIT; original synthetic data |
| `dta/inventory-loaded.xml` | [public grammar reference](https://support.spectralogic.com/documentation/default-source/user-guides/xml-commandreference-v12.8.07.pdf?sfvrsn=42f961ba_14) | MIT; original synthetic data |
| `dta/itdt-inquiry.json` | [public grammar reference](https://www.ibm.com/support/pages/sites/default/files/inline-files/IBM%20Tape%20Device%20Drivers%20and%20Diagnostic%20Tool%20User%27s%20Guide%2020251028.pdf) | MIT; original synthetic data |
| `dta/itdt-scan.txt` | [public grammar reference](https://www.ibm.com/support/pages/sites/default/files/inline-files/IBM%20Tape%20Device%20Drivers%20and%20Diagnostic%20Tool%20User%27s%20Guide%2020251028.pdf) | MIT; original synthetic data |
| `dta/itdt-test-failure.txt` | [public grammar reference](https://www.ibm.com/support/pages/sites/default/files/inline-files/IBM%20Tape%20Device%20Drivers%20and%20Diagnostic%20Tool%20User%27s%20Guide%2020251028.pdf) | MIT; original synthetic data |
| `dta/itdt-test-success.txt` | [public grammar reference](https://www.ibm.com/support/pages/sites/default/files/inline-files/IBM%20Tape%20Device%20Drivers%20and%20Diagnostic%20Tool%20User%27s%20Guide%2020251028.pdf) | MIT; original synthetic data |
| `dta/switch-a.txt` | [public grammar reference](https://docs.broadcom.com/doc/FOS-82x-Command-RM) | MIT; original synthetic data |
| `dta/switch-b.txt` | [public grammar reference](https://docs.broadcom.com/doc/FOS-82x-Command-RM) | MIT; original synthetic data |

`dta/config.owner.synthetic.toml` is an original MIT synthetic owner-adapter profile for the DTA workflow. The [IBM overview](https://www.ibm.com/support/pages/ibm-tape-diagnostic-tool-itdt-v96) anchors the workflow only; the owner commands/verifier contract are original, not vendor-native. Accessed 2026-10-18. See [adapter contract](../docs/DTA-OWNER-ADAPTER.md).

## LTFS index fixtures

The following original MIT-licensed synthetic XML files are generated by
`scripts/generate-ltfs-index.py` from the public SNIA LTFS format rules. No SNIA
sample XML or site capture is included. See [fixture details](ltfs-index/README.md)
and [validator sources and section references](../docs/LTFS-INDEX.md).

- `ltfs-index/minimal.xml`: valid empty regular file.
- `ltfs-index/overlap.xml`: invalid logical overlap within one file.
- `ltfs-index/shared.xml`: valid cross-file physical data sharing.
- `ltfs-index/sparse.xml`: valid leading and interior holes.
- `ltfs-index/bad-extents.xml`: zero length, negative offset and past-EOF extents.
- `ltfs-index/duplicate-names.xml`: duplicate sibling names.
- `ltfs-index/deep.xml`: intentionally exceeds the default nesting limit.

## V4 offline examples

All values, identities and timestamps are original synthetic MIT examples.
Public references describe grammar only; no upstream implementation or manual
text is copied. Reproduce with `PYTHONPATH=. python3 scripts/generate-v4-fixtures.py`.
See [log trends](../docs/log-trends.md), [alert history](../docs/alert-history.md),
[inventory comparison](../docs/inventory-diff.md) and [lookup catalogue](../docs/explain.md).

- `v4/alerts-16.json`
- `v4/alerts-17.json`
- `v4/alerts-18.json`
- `v4/alerts-19.json`
- `v4/explain-codes.txt`
- `v4/inventory-after.txt`
- `v4/inventory-before.txt`
- `v4/log-0c.txt`
- `v4/log-17.txt`
- `v4/log-2e.txt`
- `v4/log-31.txt`
- `v4/log-series.json`
