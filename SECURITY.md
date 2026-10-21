# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub's
[private vulnerability reporting](https://github.com/MitchelTighe/tape-diag-kit/security/advisories/new)
for this repository. This is a small project maintained on a best-effort basis;
no response time is guaranteed.

Include the affected version, a description of the trust boundary crossed,
reproduction steps using **synthetic data**, and the expected behavior. Do not open a public issue containing exploit details or private
captures. Never include secrets, device serials, barcodes, WWNs, hostnames,
customer records, or operational logs. A minimal invented fixture is preferable.
If private reporting is unavailable, open a public issue asking for a contact
without disclosing the vulnerability.

## Supported versions

Fixes target the latest 0.3.x release. There is no backport commitment for older
versions. V1/v2 **report format compatibility** does not imply maintenance of
older software releases.

## Boundaries to preserve

- Planning is the default. `--execute` is an explicit authorization to collect;
  it is not permission to perform maintenance, write media, or move cartridges.
- The runner accepts complete argv forms, uses no shell, and limits execution
  time. Do not bypass it to add a diagnostic command.
- TapeAlert reads and TEST UNIT READY can change device-reported state. Read-only
  commands do not guarantee zero firmware or driver side effects.
- Saved reports and imported dashboard files are untrusted input. Validation,
  literal rendering, CSP, input size limits and CSV formula escaping are security
  boundaries. Report validity does not authenticate its source.
- Collection can contain identifying data even when fixtures are synthetic.
  There is no promise of automatic anonymization. Review every field and raw
  command output before sharing; use synthetic reproductions for contributions.
- Offline dashboards have no upload endpoint or telemetry. Never add external
  scripts, tracking, or automatic network lookups to reports.

The maintainer coordinates fixes and disclosure after reproducing a report.
Any advisory distinguishes tested behavior from hardware assumptions.
