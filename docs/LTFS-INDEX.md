# Offline LTFS index validation

`tapediag ltfs-index` reads a saved full-index XML file without accessing a tape,
mounting a filesystem, invoking vendor programs, or fetching XML resources. It
supports full indexes with `version="2.4.0"` or `version="2.5.0"`. Incremental
indexes require replay against a full index and are refused explicitly.

```sh
python -m tapediag ltfs-index --from-file fixtures/ltfs-index/minimal.xml
python -m tapediag ltfs-index --from-file fixtures/ltfs-index/shared.xml --block-size 524288
python -m tapediag ltfs-index --from-file current.xml --previous-index previous.xml --scratch-dir scratch
```

Supply `--block-size` from the volume's LTFS **label**, not a guessed drive block
size. The index does not contain this value. With it, the validator checks
`byteoffset < blocksize` and scans physical byte ranges on each partition for
sharing. Without it, those checks are explicitly marked unverified. Different
partition IDs never overlap. The physical scan uses half-open byte ranges;
adjacent bytes within a block are not overlapping bytes.

JSON is emitted to stdout, using the other commands' formatting. Exit 0 means
no errors in the implemented checks, exit 1 means validation findings, and exit
2 means a refused input or resource/IO error (JSON on stderr). No local filename
or XML file/directory name is included in diagnostics. Findings identify an
entry by its one-based XML traversal ordinal; index-level findings use 0. The
`index` summary includes the supplied volume UUID and generation/location data.

## Specification and scope

Public primary sources:

- [SNIA LTFS Format 2.4](https://www.snia.org/sites/default/files/technical-work/ltfs/release/SNIA-LTFS-Format-2.4.0-TechPosition.pdf).
- [SNIA LTFS Format 2.5](https://www.snia.org/sites/default/files/2025-03/SNIA-LTFS-Format-v2.5-Technical-Position.pdf).

The implementation and fixtures are original; no specification sample XML or
external implementation was copied. The following section references use 2.5;
2.4 has the same extent, name, timestamp, and UUID rules.

| Rule | Specification | Result |
| --- | --- | --- |
| Logical extents must not overlap or extend past file length; order is immaterial | §6.1 | Error |
| Gaps, including a wholly sparse file or a trailing hole | §6.3.3 | Information; valid |
| Physical data shared by files or extents | §6.3.4 | Information; valid |
| UTF-8, NFC, case-preserving names; percent-encoded names | §7.4 | Decode before comparing names within a directory; preserve case |
| Nanosecond UTC timestamps and UUID spelling | §§7.7–7.8 | Error for invalid syntax/calendar values |
| Generation and self/back pointers | §§5.4.1–5.4.3, 9.2.3–9.2.4 | Validate integers, partitions, and local ordering; optionally compare a referenced index |
| Required directory/file metadata, unique file UIDs | §§9.2.6, 9.2.8 | Error |
| Extent fields and mutual exclusion of symlink/extentinfo | §9.2.9 | Error |

Case variants are distinct directory entries. The caseless matching rules in
§7.5 concern **placement-policy patterns**, not a command to case-fold all names.
Percent encoding is decoded before duplicate checks, so `example` and encoded
`%65xample` collide. Invalid encodings and non-NFC names are errors.

Physical cross-file overlap must **not** be treated as corruption: §6.3.4 allows
shared data. The scan reports each range that overlaps an earlier range, rather
than enumerating every overlapping pair (which could produce quadratic output).
Negative fields and zero-byte extents are errors. Numeric fields are limited to
unsigned 64-bit values with at most 20 decimal digits; arithmetic uses Python
integers and disk keys that preserve full-width ordering.

A generation need not increase by exactly one. A generation-1 index-partition
copy can have a cross-partition pointer to generation 1 in the data partition.
For the same partition, a back pointer must precede the current index. With
`--previous-index`, the supplied full index must pass these checks, match the
volume UUID and target location, and have a generation no greater than current.
Equal-generation content equivalence is not established. The tool always emits
`LTFS_CHAIN_UNVERIFIED`: it cannot establish the complete chain, which partition
is the data partition, actual media locations, label identity, or consistency
with unprovided indexes. A missing pointer is not universally an error.

This is a bounded semantic validator, not a complete XML Schema or on-tape
conformance implementation. It checks the documented required metadata and
structural relationships, but does not fully validate extension fields, extended
attributes, placement policies, symlink target existence/length, or every XML
attribute. It cannot determine Data Extent boundaries, fractional final block
lengths, filemarks, or whether a referenced block exists without media evidence.

## Resource and parser limits

Only Python standard-library modules are used. `ElementTree.iterparse` consumes
16 KiB chunks. An independent Expat preflight sees each chunk first and refuses
DTD/entity declarations, non-UTF-8 XML, excessive structure, and excessive text.
It never resolves external resources. Declaration rejection works across chunk
boundaries. Completed XML nodes are removed from their parents and cleared;
directory children and file extents are not retained as a growing XML tree.

UIDs, sibling names, and extents live in a temporary SQLite database with a
4 MiB page cache and on-disk indexes. Checks do not accumulate all files in RAM.
Memory is bounded by configured XML depth/metadata/token limits, the parser
chunk, the SQLite cache, and the finding cap. Disk space grows with entries and
extents; temporary state is removed on success and handled failure. Use a
scratch filesystem with sufficient free space. The database limit is applied
before schema creation; exhaustion is a controlled refusal. No database is kept
as a side effect or written beside the input.

Default API limits (`tapediag.ltfs_index.Limits`):

| Limit | Default |
| --- | --- |
| Actual bytes consumed | 64 GiB |
| XML elements | 500 million |
| Element depth | 256 |
| Attributes per element | 16 |
| Token / retained scalar metadata per frame | 1 MiB |
| Contiguous text | 1 million characters (1,048,576) |
| Distinct child fields per frame | 128 |
| Retained findings | 1,000 |
| SQLite database | 8 GiB |

Unfinished-token detection allows at most two additional 16 KiB chunks while
Expat awaits an event. This also bounds unfinished attributes/comments before
an end event exists. Limits are policy, not LTFS format maxima. The Python API
accepts a customized `Limits`; the CLI uses the defaults. Counts remain exact
after the finding list is truncated. Limit failures do not return a misleading
partial valid result. Input must be a regular file, checked before and after
opening; input-size enforcement does not trust `stat` size.

## Finding codes

Codes are stable API identifiers; messages can change. All codes below are
errors except the four explicitly informational codes.

| Codes | Meaning |
| --- | --- |
| `LTFS_EXTENT_OVERLAP`, `LTFS_EXTENT_PAST_EOF` | Logical overlap / past file length |
| `LTFS_EXTENT_VALUE`, `LTFS_EXTENT_PARTITION`, `LTFS_BYTEOFFSET` | Invalid extent field / partition / block offset |
| `LTFS_SPARSE`, `LTFS_SHARED_EXTENT` | Informational sparse layout / physical sharing |
| `LTFS_BLOCK_SIZE_UNVERIFIED`, `LTFS_CHAIN_UNVERIFIED` | Informational check limitations |
| `LTFS_UID`, `LTFS_UID_DUPLICATE`, `LTFS_ROOT_UID`, `LTFS_HIGHEST_UID` | UID range, uniqueness, root identity, or highest UID |
| `LTFS_NAME`, `LTFS_NAME_DUPLICATE` | Name syntax or sibling collision |
| `LTFS_UUID`, `LTFS_TIMESTAMP`, `LTFS_BOOLEAN`, `LTFS_FILE_LENGTH`, `LTFS_INTEGER` | Invalid scalar metadata |
| `LTFS_GENERATION`, `LTFS_LOCATION`, `LTFS_PREVIOUS_LOCATION` | Invalid index generation / location / backward pointer |
| `LTFS_PREVIOUS_INVALID`, `LTFS_PREVIOUS_UUID`, `LTFS_PREVIOUS_TARGET`, `LTFS_PREVIOUS_GENERATION` | Supplied previous full index fails consistency checks |
| `LTFS_REQUIRED`, `LTFS_ELEMENT_DUPLICATE`, `LTFS_SYMLINK_EXTENTS` | Missing field, duplicate scalar/container, conflicting file representation |

Refusals use `LTFS_XML`, `LTFS_XML_DECLARATION`, `LTFS_XML_ENCODING`,
`LTFS_INDEX_TYPE`, `LTFS_STRUCTURE`, `LTFS_LIMIT_BYTES`, `LTFS_LIMIT_ELEMENTS`,
`LTFS_LIMIT_DEPTH`, `LTFS_LIMIT_ATTRIBUTES`, `LTFS_LIMIT_TOKEN`, `LTFS_LIMIT_TEXT`,
`LTFS_LIMIT_METADATA`, `LTFS_LIMIT_CHILDREN`, `LTFS_LIMIT_CONFIG`, `LTFS_INPUT`,
`LTFS_BLOCK_SIZE`, `LTFS_SCRATCH`, and `LTFS_IO`.

## Synthetic fixtures and scale test

[Fixture provenance](../fixtures/ltfs-index/README.md) records the generated cases.
All identifiers are fictional. The huge index is generated only on demand; it is
never committed, packaged, or read into a single Python string.

```sh
python scripts/generate-ltfs-index.py --case sparse --output sparse.xml
python scripts/generate-ltfs-index.py --case huge --files 2000000 --output huge.xml
python -m pytest -q tests/test_ltfs_index.py
LTFS_RUN_SLOW=1 python -m pytest -q -s tests/test_ltfs_index.py -m slow
```

Run the last command in the project's rootless test container with `nice` and a
suitable scratch mount. The slow test runs separate 100,000-file and 2,000,000-file
child processes, records generation/validation time and Linux peak RSS, and
removes generated data. It asserts the large input exceeds 2 GiB, peak RSS stays
below 256 MiB and grows by no more than 64 MiB, and each validation takes less
than 1,200 seconds. The child timeout is 1,800 seconds. These are regression
budgets, not benchmark promises. Normal suites explicitly skip the slow test;
release adoption must run it once and retain its actual measurements.
