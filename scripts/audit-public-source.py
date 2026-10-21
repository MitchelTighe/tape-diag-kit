"""Redacted, fail-closed triage of the exact public export selection."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from release_source import fingerprint, source_files


spec = importlib.util.spec_from_file_location('history_audit', Path(__file__).with_name('audit-history.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
REFERENCE_HOSTS = {
    'github.com', 'raw.githubusercontent.com', 'www.t10.org', 'www.ibm.com',
    'support.hpe.com', 'www.kernel.org', 'doug-gilbert.github.io',
    'docs.fedoraproject.org', 'docs.rockylinux.org', 'cyclonedx.org',
    'spdx.org', 'reproducible-builds.org', 'packaging.python.org',
    't10.t10.org', 'man7.org', 'download.lenovo.com', 'docs.oracle.com',
    'json-schema.org', 'www.w3.org', 'example.org', 'www.snia.org',
    'docs.broadcom.com', 'support.spectralogic.com', 'man.openbsd.org',
}


def public_reference(line):
    urls = re.findall(r'https?://[^\s<>"`]+', line)
    return bool(urls) and all(urlsplit(url).hostname in REFERENCE_HOSTS and
                              urlsplit(url).username is None for url in urls)


def scan(root):
    root = Path(root).resolve()
    ledger = json.loads((root / 'docs/privacy-dispositions.json').read_text())
    decisions = {(r['path'], r['category'], r['line_sha256']): r['reason'] for r in ledger}
    findings = []
    paths = source_files(root)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        lines = path.read_text(encoding='utf-8').splitlines()
        for number, category, _ in audit.scan_text('\n'.join(lines)):
            line = lines[number - 1]
            digest = hashlib.sha256(line.encode()).hexdigest()
            reason = decisions.get((relative, category, digest))
            if category == 'public-reference' and public_reference(line):
                reason = 'Public upstream/standards reference on an explicitly reviewed host; no upload.'
            findings.append({'path': relative, 'line': number, 'category': category,
                             'line_sha256': digest, 'disposition': reason or 'UNRESOLVED'})
    unresolved = [row for row in findings if row['disposition'] == 'UNRESOLVED']
    provenance = json.loads((root / 'fixtures/sources.json').read_text())['entries']
    for entry in provenance:
        if entry['kind'] == 'public-excerpt' and (entry['path'] != 'public/ltfs-device-prefix.txt' or entry['license'] != 'BSD-3-Clause'):
            raise ValueError('unexpected public excerpt or licence')
        if 'LicenseRef-' in entry['license'] or entry['license'].startswith('GPL'):
            raise ValueError('unresolved fixture redistribution licence')
    return {'status': 'PASS' if not unresolved else 'REVIEW_REQUIRED',
            'scope': 'Exact public source selection; no Git history, artifacts or binary media.',
            'limits': 'Heuristic detector triage only; owner must accept final content/attribution. Exact line-hash decisions do not waive new lines.',
            'source_fingerprint': fingerprint(root), 'files': len(paths),
            'counts': dict(sorted(Counter(r['category'] for r in findings).items())),
            'unresolved': len(unresolved), 'findings': findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = scan(args.root)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'files', 'counts', 'unresolved')}, indent=2))
    return int(bool(result['unresolved']))


if __name__ == '__main__':
    raise SystemExit(main())
