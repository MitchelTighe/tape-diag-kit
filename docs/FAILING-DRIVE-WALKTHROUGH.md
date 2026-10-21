# Rehearse a suspected failing-drive diagnosis using fixtures

This is an invented operator exercise. Nothing here collects live evidence,
loads media, cleans a drive, invokes ITDT or certifies a real fault. The question
is whether saved observations justify further drive/media investigation, and
which gaps prevent a conclusion. All identities, dates and values are synthetic.

From the checkout, run this complete reproduction into a chosen local scratch
directory. It executes the five offline commands below, writes JSON and static
HTML for each, and independently asserts the expected results:

```sh
python3 scripts/verify-v4.py --output artifacts/v4-walkthrough
```

1. Review alert history. Flag 20 changes from inactive to active, then is
   unobserved, then observed inactive. The gap means the final observation
   cannot establish when it cleared or whether cleaning/repair happened.

   ```sh
   python3 -m tapediag alert-history fixtures/v4/alerts-16.json fixtures/v4/alerts-17.json fixtures/v4/alerts-18.json fixtures/v4/alerts-19.json
   ```

2. Compare captured log pages for the declared drive and cartridge. Host-write
   increments are 3,072 then 4,096 bytes. Unrecovered-read-error increments are
   2 then 3. On the fourth snapshot the byte count decreases and the declared
   cartridge changes: there is no valid continuous delta across either boundary.
   Review growing error evidence, but do not equate it with proof of drive
   failure or calculate throughput from these samples.

   ```sh
   python3 -m tapediag log-trend --from-file fixtures/v4/log-series.json
   ```

3. Compare the two library inventories. SYNTH-V4-A is observed at slot 1 before
   and at drive element 0 afterward, with slot 1 empty. That is one relocation
   candidate. The tool cannot prove a robot move or associate this logical drive
   element with a Linux tape node. Confirm identity through approved mapping.

   ```sh
   python3 -m tapediag inventory-diff fixtures/v4/inventory-before.txt fixtures/v4/inventory-after.txt --library-id SYNTH-LIB
   ```

4. Look up a hypothetical sense tuple. The key names a medium error and ASC/ASCQ
   11/00 describes exhausted read recovery. This lookup is an additional invented
   example, not a sense response extracted from the log fixtures. Compare saved
   evidence for the same medium and across other drives; this code alone cannot
   isolate media damage from a drive/path problem.

   ```sh
   python3 -m tapediag explain sense:3/11/00
   ```

5. Decode the synthetic vendor capacity example only with its explicit profile.
   Its first field is 1,998,976 MiB remaining in the main partition. Capacity is
   a gauge, not an error count, health score or universal LTO-generation label.

   ```sh
   python3 -m tapediag log-decode --from-file fixtures/v4/log-31.txt --profile lto5-6-capacity
   ```

The evidence supports further review of cleaning/error history and stable drive,
media and library mapping. It does not establish a failed drive. Preserve the
original capture times, note acknowledgement/reset possibilities, and follow
separately authorized vendor procedures if further collection or maintenance is
needed. This walkthrough issues none of those operations.

Public-format citations and exact limitations are in [alert history](alert-history.md),
[log trends](log-trends.md), [inventory diff](inventory-diff.md), and
[code explanations](explain.md). The fixtures can be reproduced using
`PYTHONPATH=. python3 scripts/generate-v4-fixtures.py`.

For release verification after installing the wheel in an isolated environment,
`python3 scripts/verify-v4.py --installed --output OUTPUT` runs Python with `-I`
and a working directory away from source. It reads only the synthetic fixture
paths from this checkout and imports the installed package.

## Generated command manuals

The roff manuals are [tapediag](man/tapediag.1.txt) and [dta](man/dta.1.txt).
The `.txt` suffix keeps them in the repository's existing text-only source
selector. View with `man -l docs/man/tapediag.1.txt` or render with
`groff -Tutf8 -man docs/man/tapediag.1.txt`. The tapediag manual includes every
subcommand; DTA retains its separate guarded maintenance semantics.
Regenerate after any CLI help change:

```sh
PYTHONPATH=. python3 scripts/generate-manpage.py --output docs/man/tapediag.1.txt
PYTHONPATH=. python3 scripts/generate-manpage.py --program dta --output docs/man/dta.1.txt
```

Tests check byte equality with actual argparse help, fixed formatting independent
of terminal width, and roff escaping of request/escape characters. The manuals
are included in source distributions; no system manual directory is modified.
