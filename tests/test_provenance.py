import ast
import json
import re
from pathlib import Path


def test_every_saved_fixture_and_golden_has_provenance(fixtures):
    entries = json.loads((fixtures / "sources.json").read_text())["entries"]
    by_path = {e["path"]: e for e in entries}
    paths = {str(p.relative_to(fixtures)) for p in fixtures.rglob("*.txt")}
    paths |= {str(p.relative_to(fixtures)) for p in (fixtures / "golden").glob("*.json")}
    paths |= {str(p.relative_to(fixtures)) for p in (fixtures / "fleets").glob("*.json")}
    paths |= {str(p.relative_to(fixtures)) for p in (fixtures / "v4").glob("*.json")}
    paths |= {str(p.relative_to(fixtures)) for p in (fixtures / "dta").glob("*") if p.suffix in (".xml", ".json", ".toml")}
    paths |= {str(p.relative_to(fixtures)) for p in (fixtures / "ltfs-index").glob("*.xml")}
    assert paths == set(by_path)
    for path, row in by_path.items():
        assert row["url"].startswith("https://") and row["license"]
        for original in row.get("derived_from", []):
            assert original in by_path
    docs = (fixtures / "SOURCES.md").read_text()
    for path in paths:
        if not path.startswith("golden/"):
            assert path in docs


def test_only_synthetic_serials_or_barcodes_in_fixtures(fixtures):
    for path in fixtures.rglob("*"):
        if not path.is_file() or path.suffix not in (".txt", ".json", ".xml", ".toml"):
            continue
        text = path.read_text()
        for serial in re.findall(r'"serial"\s*:\s*"([^"\n]+)"|Serial Number\s*=\s*([^,\n]+)|S/N:(\S+)', text):
            value = next(v.strip() for v in serial if v)
            assert value.startswith("SYNTH-"), (path, value)
        for barcode in re.findall(r'"(?:alternate_)?barcode"\s*:\s*"([^"\n]+)"|(?<!Alternate)VolumeTag\s*=\s*([^:\n]*)', text):
            value = next((v.strip() for v in barcode if v.strip()), "")
            assert not value or value.startswith("SYN"), (path, value)
        if path.parent == fixtures / "dta":
            for value in re.findall(r'<(?:serialNumber|manufacturerSerialNumber|barcode)>([^<]+)</', text):
                synthetic = value.strip().startswith("SYNTH-")
                assert synthetic, (path, "non-synthetic XML identity")
            for value in re.findall(r'^\s*(?:serial|manufacturer_serial|test_barcode)\s*=\s*"([^"]+)"', text, re.M):
                synthetic = value.startswith("SYNTH-")
                assert synthetic, (path, "non-synthetic TOML identity")
            for value in re.findall(r'"(?:worldWidePortName|worldWideNodeName)"\s*:\s*"([^"]+)"|<wwn>([^<]+)</wwn>', text):
                actual = next(v.strip() for v in value if v)
                synthetic = bool(re.fullmatch(r"0{14}[0-9a-fA-F]{2}", actual))
                assert synthetic, (path, "non-synthetic hex WWPN")
        # DTA needs syntactically valid WWPNs to exercise the actual FOS grammar.
        # Only the all-zero synthetic namespace in this exact fixture directory
        # is allowed; ordinary hardware WWPN patterns remain forbidden.
        safe_text = text
        if path.parent == fixtures / "dta":
            safe_text = re.sub(r'\b00:00:00:00:00:00:00:[0-9a-f]{2}\b', 'SYNTH-WWPN', text, flags=re.I)
        assert not re.search(r'\b(?:naa\.[0-9a-f]{16}|[0-9a-f]{2}(?::[0-9a-f]{2}){7})\b', safe_text, re.I)
        assert not re.search(r'(?:root|admin)@[^\s]+|https?://[^\s]+\.(?:internal|local)\b', text)


def test_runtime_source_parses_as_python39_syntax():
    root = Path(__file__).resolve().parents[1]
    for path in (root / "tapediag").glob("*.py"):
        ast.parse(path.read_text(), filename=str(path), feature_version=(3, 9))
