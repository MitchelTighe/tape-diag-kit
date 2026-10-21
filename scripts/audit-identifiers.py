"""Audit fixture/artifact text only; report counts and locations, never raw values."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
patterns = [
    ('serial', r'"serial"\s*:\s*"([^"\n]+)"', 'SYNTH-'),
    ('serial', r'(?:Serial Number\s*=|S/N:|SCSI_SERIAL=|Medium serial number\s*:)\s*([^,\s<]+)', 'SYNTH-'),
    ('barcode', r'"(?:alternate_)?barcode"\s*:\s*"([^"\n]+)"', 'SYN'),
    ('barcode', r'(?:Alternate)?VolumeTag[ \t]*=[ \t]*([^:\n<]*)', 'SYN'),
    ('designator', r'"value"\s*:\s*"([^"\n]+)"\s*[,}]', None),
    ('WWN', r'SCSI_IDENT_[A-Z0-9_]+=([^\s<]+)', 'SYNTH-'),
    ('serial', r'<(?:serialNumber|manufacturerSerialNumber)>([^<]+)</', 'SYNTH-'),
    ('barcode', r'<barcode>([^<]+)</barcode>', 'SYN'),
    ('serial', r'^\s*(?:serial|manufacturer_serial)\s*=\s*"([^"]+)"', 'SYNTH-'),
    ('barcode', r'^\s*test_barcode\s*=\s*"([^"]+)"', 'SYN'),
]
counts = {'files':0,'serial':0,'barcode':0,'WWN':0}
failures = []
for base in ('fixtures','artifacts'):
    for path in sorted((ROOT/base).rglob('*')):
        if not path.is_file() or path.suffix not in ('.txt','.json','.html','.xml','.toml','.jsonl'):
            continue
        text = path.read_text(encoding='utf-8')
        counts['files'] += 1
        for kind, pattern, prefix in patterns:
            if prefix is None:
                continue
            for match in re.finditer(pattern,text,(re.I if kind=='serial' else 0) | re.M):
                value = match[1].strip().rstrip('"\\')
                if not value or value in ('null','None'):
                    continue
                counts[kind] += 1
                if not value.startswith(prefix):
                    failures.append({'file':str(path.relative_to(ROOT)), 'kind':kind})
        safe_text = text
        if path.is_relative_to(ROOT/'fixtures'/'dta') or path.is_relative_to(ROOT/'artifacts'/'dta'):
            safe_text = re.sub(r'\b00:00:00:00:00:00:00:[0-9a-f]{2}\b', 'SYNTH-WWPN', text, flags=re.I)
        if re.search(r'\b(?:naa\.[0-9a-f]{16}|[0-9a-f]{2}(?::[0-9a-f]{2}){7})\b',safe_text,re.I):
            failures.append({'file':str(path.relative_to(ROOT)),'kind':'unredacted WWN pattern'})
        if path.is_relative_to(ROOT/'fixtures'/'dta') or path.is_relative_to(ROOT/'artifacts'/'dta'):
            for match in re.finditer(r'"(?:worldWidePortName|worldWideNodeName)"\s*:\s*"([^"]+)"|<wwn>([^<]+)</wwn>',text):
                value = next(v.strip() for v in match.groups() if v)
                if not re.fullmatch(r'0{14}[0-9a-fA-F]{2}', value):
                    failures.append({'file':str(path.relative_to(ROOT)), 'kind':'non-synthetic hex WWPN'})
        if re.search(r'(?:root|admin)@[^\s]+|https?://[^\s]+\.(?:internal|local)\b',text):
            failures.append({'file':str(path.relative_to(ROOT)),'kind':'operational hostname pattern'})
print(json.dumps({'status':'FAIL' if failures else 'PASS','counts':counts,'failures':failures},indent=2))
sys.exit(1 if failures else 0)
