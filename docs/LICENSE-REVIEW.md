# Licence and attribution review

Original project code, documentation and synthetic fixtures are MIT-licensed.
The original contributor credit and MIT notice are retained. The retained
`fixtures/public/ltfs-device-prefix.txt` fragment is BSD-3-Clause; its full
notice remains in `fixtures/NOTICES.md`, included in both wheel and sdist.

The four uncertain sg-inquiry, lsscsi, mtx and ITDT documentation excerpts and
all their derived golden files were removed from the current tree. New fixtures
are independently authored synthetic examples with invented values; source
URLs document grammar only. `fixtures/sources.json` records each replacement
and its new golden as MIT. This removes the need for upstream permission for
those removed excerpts; it makes no retroactive claim about historical blobs.

No mhvtl, LTFS, mtx, sg3_utils or ITDT implementation is copied or linked into
the package. Optional utility execution uses a separate process. The base `tapediag` CLI has zero third-party Python dependencies. The optional
`dta` extra uses the MIT-licensed `tomli==2.3.0` on Python 3.9/3.10; its code is
not embedded in the project wheel, and its optional dependency is inventoried. See [UPSTREAM-REVIEW.md](UPSTREAM-REVIEW.md)
for the pinned upstream naming/licence cross-check and its limits.

This is a source/notice assessment, not a legal opinion or upstream endorsement.
