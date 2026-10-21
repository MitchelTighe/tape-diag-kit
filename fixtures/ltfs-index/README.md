# Synthetic LTFS indexes

These XML files are original output of `scripts/generate-ltfs-index.py`, derived
from the public format rules documented in [LTFS-INDEX](../../docs/LTFS-INDEX.md).
They contain fictional UUID `00000000-0000-4000-8000-000000000132`, synthetic
filenames, a fixed invented timestamp, and no tape serial or site records.
No vendor or SNIA sample XML was copied.

Regenerate each file with:

```sh
python scripts/generate-ltfs-index.py --case minimal --output fixtures/ltfs-index/minimal.xml
```

Substitute `overlap`, `shared`, `sparse`, `bad-extents`, `duplicate-names`, or
`deep` for both the case and basename to regenerate the remaining fixtures.
`deep` intentionally exceeds the default depth limit; all other failing cases
produce semantic findings. `shared` is valid physical cross-file overlap.
`overlap` is invalid logical overlap within one file. `sparse` has valid leading
and interior holes. `bad-extents` includes zero length, negative offset and an
extent beyond file length.

The `huge` case is generated on demand by the opt-in slow test and is excluded
from stored fixtures. Its 2 million files have distinct UIDs and names, one
extent each, and synthetic padding so that the XML exceeds 2 GiB. Fixtures are
covered by the toolkit's MIT license.
