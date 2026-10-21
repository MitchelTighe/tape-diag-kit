# Contributing

Keep the runtime dependency-free and compatible with Python 3.9+. Parsing functions must remain pure: no subprocesses, device access, network access or environment-dependent behavior. All external commands belong behind `tapediag.safety.Runner` and its complete argv grammar.

Use only public vendor/upstream documentation, public man pages and upstream public test material. New captures must be original synthetic fixtures or short, attributable public excerpts. Do not submit real operational captures, serials, WWNs, hostnames, library layouts, personal information, or customer data. Give synthetic identifiers an obvious `SYNTH-` or `SYN` prefix. Record every fixture in `fixtures/SOURCES.md` and `fixtures/sources.json`, including its URL, license status, and whether it is synthetic. Do not infer a documentation redistribution license from its public availability.

For a parser change, add a small fixture, a reviewed golden JSON result, and independent semantic assertions. Cover incomplete, unknown and malformed input. Tests must not regenerate their own expected outputs. The explicit `PYTHONPATH=. python3 scripts/update-goldens.py` maintainer utility overwrites golden files; review every changed result against the original fixture and keep the semantic assertions independent.

Use the rootless Podman workflow in README to install development dependencies and build/install the package. Never mount devices or add privileges to the test container. `requirements-dev.txt` pins test dependencies; they are not runtime requirements. Run pytest and the pinned Ruff/actionlint checks (`scripts/check-lint.sh`). The container smoke check also exercises the installed package away from the source directory. If containers are unavailable, existing pytest/jsonschema installations can run the pure offline tests without installing or building anything; record the interpreter and that limitation.

A safety change needs refusal tests that prove rejected argv never reaches subprocess execution. Preserve finite timeouts, minimal environment, fixed executable search path, non-rewinding tape paths, and separate stdout/stderr/error reporting. Do not extend the allowlist merely to make a test or a device succeed. No write, movement, firmware, maintenance or repair commands belong in this toolkit.

Schema changes require an explicit compatibility decision. `schema/tapediag-report.v1.json` and the bundled `tapediag/report_schema.json` must match byte-for-byte. Test with the independent Draft 2020-12 validator as well as the internal schema-subset validator. Add a new schema version for incompatible report changes.

Include the commands actually run, their real results and remaining gaps with your change. Do not claim a hardware, container, screenshot or minimum-version check that was not executed.


## Review

Keep contributions small enough to review. Describe the problem, resulting
behavior, synthetic reproduction and commands actually tested. The maintainer
reviews safety-boundary, schema and provenance changes before merging; passing
tests do not replace that review. Contributors must have permission to submit
their work under the project license and must preserve third-party notices.

Lint intentionally checks fatal syntax, control-flow and undefined-name errors
rather than imposing a formatting style. `scripts/check-release.py` checks
package metadata, license notices and local documentation links.
`scripts/audit-public-source.py` scans the selected release source for
identifiers that should not be published.

## Security issues

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md),
with minimal synthetic reproductions. Do not post private captures or
vulnerability details in public issues.
