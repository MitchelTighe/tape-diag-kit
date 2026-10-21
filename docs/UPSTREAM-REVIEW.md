# Upstream naming and licence cross-check

Public upstream sources checked on 2026-10-19 at the immutable revisions linked
below. No upstream implementation was added to this tree.

| Upstream snapshot | Commands and naming | Licence/scope | Release assessment |
| --- | --- | --- | --- |
| [mhvtl 263c8a2d1f37654e190d88decb4657ad2639b399](https://github.com/markh794/mhvtl/tree/263c8a2d1f37654e190d88decb4657ad2639b399) | `usr/Makefile` builds `vtlcmd`, `vtltape`, `vtllibrary`, `mktape`, `dump_tape`, `tape_util` and other emulator utilities. | `COPYING` supplies GPL version 2, with an explicit kernel version restriction. Do not assume a permissive licence for emulator code. | The installed `tapediag` and `dta` commands overlap with none of those names. Neither installs emulator daemons, configuration or kernel modules. Synthetic saved-text fixture directory is `mhvtl-synthetic`, explicitly not captured emulator output. |
| [LTFS efc9e3a5c498504c03c2f1d0b931bae058922104](https://github.com/LinearTapeFileSystem/ltfs/tree/efc9e3a5c498504c03c2f1d0b931bae058922104) | `src/Makefile.am` installs `ltfs`; `src/utils/Makefile.am` installs `mkltfs`, `ltfsck`. | Main `LICENSE`/source notices are BSD-3-Clause. Backend/submodule notices are separately scoped; the organization also has an LGPL backend project. Do not infer the main licence covers every external component. | This package installs its own `tapediag` and `dta` entry points. `tapediag ltfs` is a subcommand, not an `ltfs` executable; only the pre-existing separate `ltfs --list-devices` operation is allowlisted. No mount, format or checker is installed/invoked. |

The authoritative licence text and build manifests were checked at those exact
revisions: [mhvtl COPYING](https://github.com/markh794/mhvtl/blob/263c8a2d1f37654e190d88decb4657ad2639b399/COPYING),
[mhvtl build targets](https://github.com/markh794/mhvtl/blob/263c8a2d1f37654e190d88decb4657ad2639b399/usr/Makefile),
[LTFS LICENSE](https://github.com/LinearTapeFileSystem/ltfs/blob/efc9e3a5c498504c03c2f1d0b931bae058922104/LICENSE),
[LTFS main target](https://github.com/LinearTapeFileSystem/ltfs/blob/efc9e3a5c498504c03c2f1d0b931bae058922104/src/Makefile.am),
and [LTFS utilities](https://github.com/LinearTapeFileSystem/ltfs/blob/efc9e3a5c498504c03c2f1d0b931bae058922104/src/utils/Makefile.am).
These are naming/notice checks, not live interoperability or trademark clearance.
The cross-check did not reserve `tapediag` or `dta` on a forge or package index.

The compatibility assessment for this release is narrow: original MIT code,
original synthetic data and a BSD-3-Clause LTFS documentation fragment with its
notice retained. GPL mhvtl is neither bundled nor linked, so no combined mhvtl
binary is being distributed under MIT. Interacting through command output does
not import upstream implementation into this package. Any future copied/linked
GPL component or backend distribution requires a new scope/licence review.

The uncertain mtx/sg-inquiry/lsscsi/ITDT excerpts are removed. Public format
references remain citations, not redistributed manuals. See
[LICENSE-REVIEW.md](LICENSE-REVIEW.md) and `fixtures/sources.json`.

Known semantic collisions are documented: `tapediag inventory` discovers/parses
saved device inventory, while `mtx inventory` can move robotics and is refused;
`tapediag ltfs` lists/parses devices, while the upstream LTFS suite also mounts,
formats and checks media. No top-level utility is shadowed by installation.

DTA vendor manuals are cited in [DTA-SOURCES.md](DTA-SOURCES.md), without copying
manual text or redistributing vendor executables. Its configurations, transcripts
and adapters in the public source are original synthetic examples. The optional
Python 3.9/3.10 TOML reader is `tomli==2.3.0` (MIT); it is separately installed,
not embedded in this wheel. The SBOM records its conditional optional relationship.
