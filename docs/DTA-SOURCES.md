# Public command provenance for dta

Access date: **2026-10-18 (America/New_York)**. Only public vendor documentation was researched. No private capture, site configuration, vendor executable, login account, or paid resource was used. Downloaded manuals are research scratch outside the repository; fixtures are newly authored synthetic data, MIT licensed. Vendor manuals retain their own copyright; this project does not redistribute them.

| Vendor reference | Implementation use | Limits |
| --- | --- | --- |
| [IBM Tape Device Drivers Installation and User's Guide, 2025-10-28 PDF](https://www.ibm.com/support/pages/sites/default/files/inline-files/IBM%20Tape%20Device%20Drivers%20and%20Diagnostic%20Tool%20User%27s%20Guide%2020251028.pdf), printed pp. 116–117, 123–125, 143, 146; SE test discussion pp. 89–92 | `-version`, `-LP`, `-R`; scripting `scan`, `-f DEVICE inqj 0x83`, `standardtest -forcedataoverwrite`, `dump`. Default scan row fields, optional changer, JSON page-83 identity, scripting exit marker. | Destructive test and forced dump are explicitly mutating. No curses/menu keystrokes are automated. Text exit status is command evidence; native reports need review. |
| [IBM ITDT v9.6 overview](https://www.ibm.com/support/pages/ibm-tape-diagnostic-tool-itdt-v96) | Confirms Standard Edition and scripting support. | Overview alone is insufficient command syntax. DTA pins an operator-supplied exact SE 9.x version. |
| [Brocade Fabric OS 8.2.x Command Reference, FOS-82x-Command-RM110](https://docs.broadcom.com/doc/FOS-82x-Command-RM), pp. 120–128, 134–135, 217–218, 1493–1494, 1510–1511 | Zoning queries, member removal/addition, saved/effective configuration, noninteractive `-f`, transaction and default-zone checks. | DTA supports ordinary zones with WWPN/alias/domain,index members. Peer/target-driven zoning is refused. Last-member deletion is refused because `zoneadd` would not recreate a deleted zone. |
| [Spectra Tape Libraries XML Command Reference, June 2021, revision S](https://support.spectralogic.com/documentation/default-source/user-guides/xml-commandreference-v12.8.07.pdf?sfvrsn=42f961ba_14), pp. 16–22, 33–38 (especially p. 36 for host-visible versus manufacturer serial), 61–67, 98–100 | `/gf/` query API, cookie login/logout, drive/manufacturer identity, partition inventory, offset-based moves, asynchronous progress and singular `getMoveResult`. | Media move action requires BlueScale 12.8.04+. Revision-history wording uses a plural, but command syntax specifies singular `getMoveResult`; implementation follows command syntax. DTA requires trusted HTTPS, even though the manual describes port 80 as the default. |
| [Spectra TFinity User Guide, June 2025](https://support.spectralogic.com/documentation/default-source/user-guides/tfinity-user-guide.pdf?sfvrsn=6123bdd1_22), library overview / XML command interface | Establishes the BlueScale XML interface for TFinity. | LumOS TFinity Plus is a different interface and is not claimed compatible. |

SSH transport options follow the public [OpenSSH ssh_config manual](https://man.openbsd.org/ssh_config), accessed 2026-10-18: strict pre-existing host trust, agent/X11/port forwarding disabled, local-command hooks disabled, and no shared control socket. The local `SSH_AUTH_SOCK` reference may be passed for authentication; it is neither logged nor forwarded.

The tables above identify factual command grammar, not vendor certification of this assistant. Host-visible location identity and physical manufacturer identity are checked separately; the public reference explicitly distinguishes them. Move results must match the exact TEST route and successful status; final inventory is still required.

The workflow, state machine, safety rules, audit format and support message are original project design.

## Parser boundaries

`parse_scan` accepts the documented default text form, including an optional changer field and a wrapped device-driver label. It requires a successful terminal scripting marker and a unique matching serial/device. Multiple paths to the same serial are refused. Custom scan format strings, curses screens, unspecified JSON dialects and non-IBM LTO records are outside the supported selection grammar.

`parse_test` intentionally parses only the publicly evidenced scripting exit marker. It does not invent a `Test Result: PASS` dialect. A successful process/marker pair sets `command_success`; `hardware_verdict` remains `unknown`. Collected native files are opaque evidence for the operator/vendor. The `.a.gz` file produced by the fake is an explicitly labeled text placeholder, not a functional vendor dump.

`cfgshow` is parsed as complete defined/effective sections. Aliases are expanded; unknown syntax, unresolved aliases, incomplete output and effective/defined disagreement refuse the run. Every zone outside the explicit diagnostic allowlist is treated as production, including inactive defined zones. The entire baseline is compared during restoration, rather than checking only the removed member.

The empty `cfgtransshow --opentrans` fixture is a **synthetic derivation** from the documented transaction capability/domain table and the documented no-outstanding response. The manual's populated example is not an example of an empty fabric. Real firmware may use another empty-table spelling; until it is added with tests, DTA stops before zoning writes. DTA never treats an absent or unrecognized table as empty.

## Hook for locally reviewed real samples

Keep future authorized local samples in the ignored `.dta-local/samples/` directory, outside shipped fixtures and bundles. Follow local access policy; the shipped fixtures use synthetic/public data only.

Use the tests in `tests/test_dta_vendor.py` as the adapter seam: call `parse_scan`, `parse_inquiry`, `parse_test`, `parse_cfgshow`, `parse_inventory`, and `library_identity` on a locally reviewed sample. Create a separately authored synthetic equivalent before proposing a grammar change. Register the synthetic file in `fixtures/sources.json` and `fixtures/SOURCES.md`, with the exact public format reference/access date and what is still inferred. Never loosen the isolation or barcode checks merely to accept unfamiliar text. Do not commit raw site samples or credential-bearing login responses.

Native health-report JSON semantics, broader ITDT release variations, real empty transaction tables, BlueScale TLS deployment, and physical library/drive behavior remain integration follow-ups. No online firmware update, library audit/robot inventory, reset, full-write, erase command, reservation breaking, or vendor-download path is implemented.
