# Drive-test assistant operator runbook

`dta` is a separate maintenance CLI. It can change FC zoning, move a designated disposable TEST cartridge, run a destructive ITDT standard test, and force drive dumps. The existing `tapediag` CLI retains its read-only command grammar.

Default invocation prints the complete plan and rollback before any remote connection. Remote execution requires **both `--apply` and interactive terminal entry of the exact configured drive serial**. Confirmation is not accepted by a flag, pipe, environment variable or checkpoint. It is required again for resume.

## Start offline

From this source checkout, Python 3.11+ needs no runtime dependencies:

```sh
bin/dta --config config.example.toml --run-id SYNTH-PLAN
bin/dta --config fixtures/dta/config.synthetic.toml --run-id SYNTH-DEMO --simulate fixtures/dta
bin/dta --config fixtures/dta/config.synthetic.toml --run-id SYNTH-DEMO --json
```

Every invocation above produces **zero connections and zero remote requests**, including fake requests. `--simulate` selects the fake only when applying. For an interactive in-memory rehearsal with synthetic fixtures:

```sh
mkdir -p .dta-runs
bin/dta --config fixtures/dta/config.synthetic.toml --run-id SYNTH-REHEARSAL \
  --simulate fixtures/dta --apply --output .dta-runs/synthetic-rehearsal
```

Type `SYNTH-DRIVE-DTA` when prompted. This fake has no network/subprocess implementation. Its dump bytes and responses are labeled synthetic. Use a new output directory and run ID for a new run. The default run ID is random. Python 3.9/3.10 additionally needs optional **tomli==2.3.0**; the project extra is `tapediag[dta]`. Any installation/build for this work must run in a rootless container, not on the host.

## Prepare a local config

Copy `config.example.toml` to an ignored `*.dta.local.toml` or inside `.dta-local/`. Replace every placeholder from an independently verified mapping. Never put credential values in TOML, argv, tickets or chat. Configure only the environment **names** `DTA_LIBRARY_USERNAME` and `DTA_LIBRARY_PASSWORD` (or locally chosen names). Provision their values through the operator's existing secure process; DTA reads them only in memory after live authorization. Cookies remain in memory and are never checkpointed. The CLI never prints the resolved login query, HTTP exceptions or raw remote stderr.

Configure all WWPNs on the physical drive, every relevant domain/port **index** member, and one authorized representative switch for **each distinct fabric**. Zoning is fabric-wide; do not repeat switches in the same fabric. Existing SSH aliases must select the intended logical switch/FID and primary FCS where required. They must already have strict known-host trust and appropriate noninteractive credentials. DTA neither discovers missing fabrics nor changes SSH trust. Confirm that no alias includes another asset. Non-diagnostic zones must retain at least one member after removal. Peer zones, target-driven zoning, nested aliases, and unsupported zone output require a separate reviewed implementation.

The diagnostic zones must grant the mover access while production members are removed. Every defined/effective zone outside that allowlist is treated as production. Exact configured removals must cover **all** drive references. Default-zone policy must already be committed **No Access**. Both the local transaction query and capable, empty fabric-wide transaction table must be recognized. DTA never aborts someone else's zoning transaction or changes default-zone policy.

Configure the BlueScale partition, physical drive component ID, both **host-visible `drive.serial`** and **physical `drive.manufacturer_serial`**, partition drive offset and reserved TEST home offset from reviewed library mappings. SCSI element IDs differ from BlueScale offsets; they must not be substituted. Spectra documents `serialNumber` as a location-based serial reported to the host; it can stay unchanged after a physical drive replacement. DTA verifies this serial in ITDT and the library, plus the separate manufacturer serial, so replacement cannot silently inherit test authorization. The typed confirmation uses `drive.serial`. The library port-A WWPN must belong to the configured drive ports. These identities and partition drive number must all agree. The drive must start empty and the exact TEST barcode must be at the configured home. Duplicate barcodes, queued media and unknown occupancy refuse the workflow. Media move requires BlueScale **12.8.04+**; verify firmware support before use. DTA does not perform a robotic audit or automatically change firmware.

Provision a trusted **HTTPS** XML endpoint. Plain HTTP, credentials in URLs and redirects are refused. The documented API logs in via query parameters, so the TLS endpoint/proxy must follow local policy for suppressing credential-bearing access logs. Library-side logging cannot be controlled by DTA. No TLS-verification bypass or plaintext fallback is provided. Use an operator account authorized for media movement, without unnecessary administrative privileges.

On the mover, provision the exact configured **ITDT SE 9.x version**, its absolute executable path, the verified `/dev/sgN` or non-rewinding `/dev/IBMtapeNn` path, and an existing private output parent. DTA creates a fresh private child directory for each run. It never downloads a vendor executable, installs a driver, invokes a curses menu, forwards arbitrary ITDT flags, updates firmware, or performs a full-write/erase command. `standardtest -forcedataoverwrite` itself destroys the loaded cartridge data.

For automated owner lock/unlock, configure the optional `[owner]` adapter described in [DTA-OWNER-ADAPTER.md](DTA-OWNER-ADAPTER.md). It adds STEP 0 and a final release/visible-usable verification, checks idle/no mounts and run ownership before every maintenance mutation, and retains the lock on known diagnostic/evidence failure. Native command/state mappings for the owning application are site-specific and are not guessed.

Before apply, maintain exclusive ownership of the application/drive and change window. Quiesce the owner, prove it is idle with no pending mounts, prevent other library/zoning writers, and keep ownership until recovery and application acceptance are complete. Cross-device read checks cannot atomically exclude another administrator. A local checkpoint lock protects one run directory, not an entire site. Per-command snapshots detect observed drift but cannot make independent switch commands atomic against a competing administrator.

## Review, then apply

First inspect the ordinary plan with the final local config and a chosen run ID. Review exact commands, every before/after read, the designated disposable TEST barcode, all fabrics, and the rollback order. `--output` on a plan-only invocation creates a local plan/audit directory; that directory is not an apply checkpoint. Use a new directory for apply.

```sh
bin/dta --config .dta-local/drive.dta.local.toml --run-id REVIEWED_RUN
bin/dta --config .dta-local/drive.dta.local.toml --run-id REVIEWED_RUN \
  --apply --output .dta-runs/REVIEWED_RUN
```

The ordered workflow is:

1. Authenticate a fresh XML session, read every fabric, pin the ITDT version, match serial/path/WWPN and library identity, require TEST home and an empty drive, and save a complete zoning baseline.
2. Recheck each fabric baseline and transactions. Issue the configured `zoneremove`, `cfgsave -f`, and `cfgenable CONFIG -f`; verify exact expected isolation. After each individual member change/save/enable, compare the complete defined/effective snapshot against the exact expected intermediate state before issuing the next write. Drift halts before the next save/enable. The underlying vendor `-f` suppresses vendor prompts only after DTA's own serial confirmation.
3. Create private remote run directories. Recheck isolation, identities and inventory. Move TEST from the reserved home slot to the drive with the documented XML move action. Poll progress, read the move result, and confirm final inventory. A successful HTTP reply alone is insufficient.
4. Check the erase guard. Immediately before the actual test, **repeat** all fabric, version, identity and media checks. Refuse unless the loaded barcode is exactly TEST, home is empty, and every configured drive identity is absent from every production zone.
5. Run the documented ITDT scripting `standardtest -forcedataoverwrite`, force dumps with `dump`, and collect only the dedicated run's results/logs. Preserve command output and opaque native files. An exit code is not a hardware-health verdict.
6. Recheck identities, media and isolation. Return TEST to its empty reserved home and verify it arrived. Only then restore each fabric's original members/configuration and compare the complete baseline.
7. Verify configured zoning, TEST home, drive empty/OK and exact serial/path/WWPN visibility. Log out. Write the local support message, SHA256 manifest, and ZIP bundle. No ticket, mail, SMS, board message or upload is sent.

Known diagnostic/dump process failures and refused collection archives are recorded as evidence gaps; when process completion is known and remaining guards pass, the workflow still returns media and restores configuration. It exits **1** with those gaps. A timeout/disconnection or unknown media/zoning outcome halts immediately, preserving isolation and ownership for reconciliation. It does not automatically restore zoning while a remote test may still run or TEST remains loaded.

## Interruption and resume

```sh
bin/dta --config .dta-local/drive.dta.local.toml --apply --resume \
  --output .dta-runs/REVIEWED_RUN
```

Use the original config, output directory and implementation. The run ID is read from the checkpoint. Review the plan again and retype the serial. Config/plan fingerprints, completed-step order, a chained audit anchor and live expected states are revalidated. Completed write steps are not repeated. The destructive guard is always fresh even when its named checkpoint was completed earlier.

A mutating request is journaled and fsynced **before** dispatch. If the process stops after intent but before the entire step is verified, `pending` remains. A pending write is never automatically replayed, even when its response had been acknowledged. SSH timeout does not prove remote process termination; library progress completion can be session-specific and returned only once. This ambiguity is a deliberate stop condition.

For a pending step, retain the directory, private remote outputs, maintenance ownership and the saved rollback plan. Independently determine whether any test/dump process or library move is still active and whether a zoning transaction committed. Reconcile physical inventory and complete fabric states against `state.json`. After remote work is proven stopped, return TEST home before restoring production zones. The displayed rollback order is media return → fabric restoration → final verification, reversing completed maintenance mutations. Do not execute rollback commands against changed or unverified state. Do not delete `pending`, hand-edit `completed`, reuse an old output directory, or run a new destructive test to bypass this stop. There is no force-resume switch. Record manual recovery locally and use a new maintenance run only after a new review.

Read-only failures at a completed boundary can resume after their cause is corrected, without reissuing completed writes. Interrupted local bundle generation can be regenerated with completed `--resume`; this performs no remote writes and does not refresh historical restoration evidence.

## Audit, outputs and acceptance

Run directories are current-user owned, mode **0700**; files are **0600**. A local advisory lock prevents concurrent use of the same directory. `audit.jsonl` records timestamped plan/request intents, response sizes/hashes, gate decisions, transitions and halts with a SHA256 chain. The chain detects accidental corruption relative to its checkpoint anchor; it is not an authenticated log against a malicious current user.

`plan.txt` / `plan.json`, `state.json`, selected `capture-*.txt`, `vendor-*` files, `support-ticket.txt`, `manifest.json` and `attachments.zip` remain local. The archive includes the audit through the last workflow event and hashes each included file. It does not recursively package the worktree, TOML config, environment, SSH directory or cookies. Remote tar entries are read as bytes, never extracted to named paths; symlinks, hardlinks, devices, traversal, duplicates, unrelated serial results, unknown logs and oversized data are refused. Per-file limit is **16 MiB**; aggregate collection limit is **64 MiB**. Larger/vendor variant outputs require manual collection or a separately reviewed change. Native dumps may contain sensitive metadata; review/redact locally before any manual submission.

On a halt, DTA attempts a clearly partial local bundle with completion/pending/restoration status. Disk errors can prevent packaging; the checkpoint and audit remain the primary recovery evidence. DTA retains remote output and never removes vendor files automatically.

Exit statuses: **0** plan or workflow completed without recorded command/evidence gaps; **1** workflow restored with diagnostic/dump/collection gaps; **2** invalid input, refusal or unresolved remote state; **130** interruption. No exit status means hardware PASS. Zoning/library/path restoration is an infrastructure observation. Application scheduling, a successful production job, and native health-report interpretation require operator acceptance before ending the maintenance window, especially after diagnostic failures.

## Verification and integration limits

The synthetic verification harness is `scripts/verify-dta.py`. The task report lists actual executed commands/counts and transcript paths. Unit tests include every completed-step resume boundary, uncertain writes, guard changes immediately before testing, failed returns, failed diagnostics, archive attacks, audit corruption and authorization bypass attempts. No hardware, vendor executable, live switch, live library or production owner was contacted.

See [DTA-SOURCES.md](DTA-SOURCES.md) for public URLs, access dates, inferred empty transaction-table grammar, unsupported outputs and the ignored local-sample adapter seam. Live compatibility is unverified; unknown output stops before the next mutation. Validate with locally approved synthetic equivalents before considering a site rollout.
