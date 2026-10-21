# Original synthetic v3 fleets

All identities, counters, firmware labels, times and conditions are fictional. No serial number, barcode, site, operator or operational capture comes from real hardware. `scripts/generate-fleets.py` regenerates the nine JSONs deterministically using public-format parsers and the v3 model. No network or device access occurs.

| Fleet | Latest situation | Drive generations | Library |
| --- | --- | --- | --- |
| SYNTH-ALPHA | Clear selected drive observations; library limitations visible | LTO-7/8/9 | 3 drives, 44 storage + 4 IE elements |
| SYNTH-BRAVO | LTO-8 cleaning/usage warnings; duplicate library barcode | LTO-7/8/9 | Same 48-slot format |
| SYNTH-CHARLIE | Failing LTO-9 signals; absent MAM on another drive; truncated library capture | LTO-7/8/9 | Deliberately missing one slot row |

Each fleet has snapshots at 2026-10-16, 17 and 18 at 12:00 UTC. These dates describe invented evidence, not actual observations. ALPHA's error counters remain zero, BRAVO develops a cleaning request, and CHARLIE accumulates error counters and critical alerts. Counter totals and usage thresholds are not rates or remaining-life predictions. Firmware labels S007/S008/S009 are invented, not supported firmware recommendations.

Sources and access dates: [SCORING.md](../../docs/SCORING.md), [sources.json](../sources.json), [SOURCES.md](../SOURCES.md). All generated fixtures are MIT-licensed original project data; no upstream code or manual passages are copied.
