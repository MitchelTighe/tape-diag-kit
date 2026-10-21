# Read-only field workflows

`tapediag guided --workflow NAME` prints a dry-run JSON plan. `--menu` presents the same nine choices in a terminal. Every live step requires `--execute`, explicit `--drive /dev/sgN` / `--changer /dev/sgN` selection and `--i-understand-read-only`. These are review workflows inspired by vendor tools' field sequence; they never invoke ITDT. Vendor tool features are broader and may write data or move media.

Use saved evidence without hardware:

```sh
python3 -m tapediag guided --workflow slow-drive --from-report fixtures/fleets/synth-bravo-20261018.json
python3 -m tapediag guided --workflow inventory-audit --from-report fixtures/fleets/synth-charlie-20261018.json
python3 -m tapediag guided --workflow dump-plan --from-report fixtures/fleets/synth-alpha-20261018.json
```

The result records the decision path, outcome, next evidence to review, complete allowlisted command plan and collection failures. Offline decisions do not execute planned commands. `--drive` / `--changer` can filter saved reports; absent selections are errors. Empty applicable asset sets are explicitly unavailable. Firmware review reports the observed revision; it does not assume a latest version or recommend an update.

Live invocation template (documented only; no hardware was used in development):

```sh
python3 -m tapediag guided --workflow cleaning --drive /dev/sg9 --execute --i-understand-read-only --timeout 10
```

Only `mam` / `slow-drive` plans include MAM. MAM is skipped live unless `--medium-loaded` declares a cartridge already present. This flag never loads one. Repeated selections collect several assets; inventory-audit takes changers only. All named workflows start with `lsscsi -g` and `sg_map -x` to review identity/mapping. Plans are regenerated from validated paths. Saved report content and decision answers cannot supply commands. A live failure is retained as a failing step and causes exit 1; a decision is evidence-based triage, not an execution authorization.

The original `guided` command without `--workflow` retains v2 resumable collection, `--state-file` and `--resume` (see [guided.md](guided.md)). Named v3 workflows use `--from-report` for repeatable analysis and do not resume saved steps. `guided --from-file` validates and replays either transcript format; it never executes them.

## Identify drive / library (`identify`)

```text
inventory + topology -> drive inquiry/VPD + changer inquiry/status
  product observed?
    no  -> identity-missing: review inquiry evidence
    yes -> mapping observed?
             no  -> mapping-missing: verify application mapping
             yes -> identified: model + observed revision
```

Changer identity can come from saved inventory; generic-device numbers are never equated with library drive element numbers.

## Firmware level (`firmware`)

```text
inventory -> drive/changer inquiry
  revision observed?
    no  -> revision-missing
    yes -> revision-observed -> compare exact model with public vendor docs
```

No firmware payload, loader or update route exists.

## TapeAlert (`tapealert`)

```text
2Eh flags + selected logs (including 12h response)
  any active flags? -- yes -> alerts-active -> review decoded flag guidance
           |
           no -> all 64 observed without warnings?
                    yes -> alerts-clear (selected observations only)
                    no  -> alerts-unknown
```

Reading alerts can acknowledge latched flags on some firmware. The tool does not reset them.

## Cleaning status (`cleaning`)

```text
TapeAlert 20/21 + 0Ch request + 14h motion hours
  request active? -- yes -> cleaning-requested -> separate vendor procedure
           |
           no/unknown -> age known and request clear?
                          no  -> cleaning-unknown
                          yes -> age >= 100 hours?
                                   yes -> cleaning-age-review (heuristic)
                                   no  -> cleaning-clear
```

Age alone does not prescribe cleaning. A separate authorized procedure and compatible cleaning media are outside this tool.

## Cartridge MAM (`mam`)

```text
already-loaded declaration? -- no (live) -> skip MAM -> mam-absent
           |
          yes -> selected read-only MAM attributes
                  no attributes -> mam-absent
                  loads + lifetime read/write usable? -- no -> mam-partial
                                                     yes -> mam-read
```

No cartridge positioning occurs. Absent media/MAM is not proof of drive failure; units and partial coverage remain visible.

## Drive dump CAPTURE PLAN (`dump-plan`)

```text
inventory -> inquiry -> TapeAlert + selected log pages
  -> capture-plan: retain report, timestamp, model, firmware and counters
  -> review vendor process / side effects / local privacy / storage destination
  -> STOP: no dump generation, retrieval, upload or vendor tool invocation
```

The [public IBM ITDT overview](https://www.ibm.com/docs/en/tape-drive?topic=information-tape-diagnostic-tool-itdt) (accessed 2026-10-18) lists broader test/dump/firmware capabilities. They are not automatically safe to execute here. This workflow provides no runnable dump command.

## Library inventory audit (`inventory-audit`)

```text
mtx status (never mtx inventory)
  status observed? -- no -> inventory-missing
         |
        yes -> count/barcode/source consistency warnings?
                 yes -> inventory-review -> compare saved application inventory
                 no  -> inventory-consistent
```

Empty source slots after a load are normal. An occupied source may have been reused; the capture cannot prove a robot fault. Door, sensors and complete exception health remain unknown. No move/exchange/initialize command is issued.

## Tape won't load (`wont-load`)

```text
inquiry + readiness + TapeAlert + optional changer status
  Critical flag? -- yes -> critical-alert -> retain evidence / dump-plan
        no
  cleaning requested? -- yes -> cleaning-requested -> cleaning workflow
        no
  full TapeAlert coverage? -- no -> alerts-unknown
        yes
  readiness known? -- no -> readiness-unknown
        yes
  ready? -- yes -> ready-review: historical/intermittent symptom
         -- no  -> not-ready-review: absent media / initialization / fault unknown
  -> review generation compatibility, saved application events and inventory
```

A non-ready result cannot identify its cause alone. No retries, insert/eject operations or forced unload are performed.

## Slow drive (`slow-drive`)

```text
TapeAlert + logs + MAM (only if already loaded)
  Critical flag? -- yes -> critical-alert
        no
  cleaning requested? -- yes -> cleaning-requested
        no
  full TapeAlert coverage? -- no -> alerts-unknown
        yes
  uncorrected read/write count positive? -- yes -> error-review -> compare snapshots
        no
  counters complete? -- no -> performance-unknown
        yes
  heuristic lifetime threshold reached? -- yes -> lifetime-review
        no
  -> streaming-review: host feed, block size, compression, concurrency evidence
```

No throughput benchmark or media read test is run. Historical counters cannot establish streaming rate. Use `tapediag watch BEFORE AFTER` to flag score drops, newly active alerts, increased counters, new gaps and missing assets. Decreased counters are reset/replacement/wrap evidence, not an improvement rate.

## Public command references

Accessed **2026-10-18**: [sg_logs](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8), [sg_inq](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_inq.8), [sg_read_attr](https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_read_attr.8), [mtx manual](https://github.com/mtx-org/mtx/blob/master/mtx/mtx.1), [T10 SMC-3 command draft changes](https://www.t10.org/ftp/t10/document.07/07-060r2.pdf), [T10 opcode list](https://t10.t10.org/lists/op-alph.htm). These describe interfaces; only exact forms in `safety.py` are accepted. Every raw opcode (00h–FFh) is refused through `sg_raw`, including nominal reads, to prove there is no raw-CDB bypass.
