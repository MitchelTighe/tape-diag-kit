"""Synthetic privacy regression tests; never create commits or use real keys."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import zlib

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load_script("audit-history")
release = load_script("check-release")


@pytest.mark.parametrize("sample,category", [
    ("/home/SYNTH-USER/captures", "local-path"),
    ("/Users/SYNTH-USER/captures", "local-path"),
    ("/mnt/storage/SYNTH-SITE", "local-path"),
    ("synthetic@example.invalid", "email"),
    ("tape01.example.internal", "internal-domain"),
    ("admin@SYNTH-HOST", "login-host"),
    ("ssh SYNTH-HOST command", "ssh-host"),
    ("192.0.2.123", "ipv4"),
    ("2001:db8::123", "ipv6"),
    ('"serial": "EXAMPLE-ONLY-123"', "device-identifier-candidate"),
    ('Serial Number = EXAMPLE-ONLY-123', "device-identifier-candidate"),
    ('SCSI_IDENT_LUN_NAA=EXAMPLE-ONLY-123', "device-identifier-candidate"),
    ('VolumeTag=EXAMPLEONLY', "device-identifier-candidate"),
    ("https://example.invalid/reference", "public-reference"),
    ("-----BEGIN " + "OPENSSH PRIVATE KEY-----", "private-key-marker"),
    ("api_key=" + "EXAMPLEONLY" * 3, "credential-assignment"),
])
def test_privacy_detector_reports_location_without_value(sample, category):
    findings = audit.scan_text("ordinary text\n" + sample)
    assert any(row[:2] == (2, category) for row in findings)
    assert sample not in json.dumps(findings)


@pytest.mark.parametrize("sample", [
    '"serial": "SYNTH-DRIVE-001"', '"barcode": "SYN0001L8"',
    '"serial": null', '"serial": {"type": "string"}',
    '"serial": 14', "python:3.13.9-slim-bookworm", "Serial Number = <SERIAL>",
])
def test_synthetic_identifiers_schema_and_version_are_not_private_serials(sample):
    assert not audit.scan_text(sample)


def png_chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def test_png_metadata_extraction_includes_compressed_text_not_pixel_bytes():
    text = b"host=SYNTH-HOST.example.internal"
    png = b"\x89PNG\r\n\x1a\n"
    png += png_chunk(b"zTXt", b"Description\0\0" + zlib.compress(text))
    png += png_chunk(b"IDAT", b"admin@SYNTH-PIXEL-NOISE")
    decoded, method = audit.binary_text(png)
    assert text.decode() in decoded and "PIXEL-NOISE" not in decoded
    assert method == "png-text-metadata"
    assert any(row[1] == "internal-domain" for row in audit.scan_text(decoded))


def test_png_corrupt_or_oversized_metadata_is_not_cleared():
    bad = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 1000) + b"tEXtshort"
    assert audit.binary_text(bad)[1] == "png-metadata-incomplete"
    huge = b"\x89PNG\r\n\x1a\n" + png_chunk(b"zTXt", b"Comment\0\0" + zlib.compress(b"a" * (2 * 1024 * 1024 + 1)))
    assert audit.binary_text(huge)[1] == "png-metadata-incomplete"


def test_ocr_text_is_scanned_without_storing_raw_pixels_or_diagnostics(monkeypatch):
    def fake_ocr(command, **kwargs):
        assert command == ["tesseract", "stdin", "stdout", "--psm", "11"]
        assert kwargs["env"]["OMP_THREAD_LIMIT"] == "2"
        assert kwargs["input"].startswith(b"\x89PNG")
        return subprocess.CompletedProcess(command, 0, b"host.example.internal", b"SYNTH-PRIVATE-DIAGNOSTIC")
    monkeypatch.setattr(audit.subprocess, "run", fake_ocr)
    decoded, method = audit.binary_text(b"\x89PNG\r\n\x1a\n", ocr=True)
    assert method == "png-text-metadata-and-ocr"
    assert audit.scan_text(decoded) == [(1, "internal-domain", "review")]
    assert "DIAGNOSTIC" not in decoded


def test_missing_ocr_is_explicit_coverage_gap(monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr(audit.subprocess, "run", unavailable)
    assert audit.binary_text(b"\x89PNG\r\n\x1a\n", ocr=True) == ("", "png-ocr-unavailable")


def test_pdf_tool_failure_does_not_emit_diagnostics(monkeypatch):
    def fail(*args, **kwargs):
        raise FileNotFoundError("SYNTH-PRIVATE-DIAGNOSTIC")
    monkeypatch.setattr(audit.subprocess, "run", fail)
    assert audit.binary_text(b"%PDF-1.7\nSYNTH") == ("", "pdf-extraction-unavailable")


def test_git_failure_redacts_stderr_and_disables_optional_writes(monkeypatch, tmp_path):
    def fail(command, **kwargs):
        assert kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0"
        assert kwargs["env"]["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert command[:2] == ["git", "--no-pager"]
        return subprocess.CompletedProcess(command, 1, b"", b"SYNTH-PRIVATE-DIAGNOSTIC")
    monkeypatch.setattr(audit.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="read-only Git command failed: rev-list") as error:
        audit.git(tmp_path, "rev-list", "--all")
    assert "SYNTH-PRIVATE" not in str(error.value)


def test_history_scan_keeps_deleted_blob_and_identity_locations(tmp_path, monkeypatch):
    # Mock read-only Git responses instead of creating any .git metadata.
    old, new, blob = "a" * 40, "b" * 40, "c" * 40
    private = b"ordinary\nSerial Number = EXAMPLE-ONLY-123\n"
    rawcommit = b"tree " + b"d" * 40 + b"\nauthor SYNTH-OWNER <synthetic@example.invalid> 1 +0000\ncommitter SYNTH-OWNER <synthetic@example.invalid> 1 +0000\n\nSynthetic commit\n"

    def fake_git(root, *args):
        if args[0] == "rev-parse": return b"false\n"
        if args[0] == "rev-list": return (new + "\n" + old + "\n").encode()
        if args[0] == "for-each-ref": return (new + " commit\n").encode()
        if args[0] == "replace": return b""
        if args[:2] == ("cat-file", "commit"): return rawcommit
        if args[0] == "ls-tree":
            return ("100644 blob " + blob + "\tdeleted-capture.txt\0").encode() if args[-1] == old else b""
        if args[:2] == ("cat-file", "blob"): return private
        if args[0] == "ls-files": return b""
        raise AssertionError("unexpected read-only Git command")

    monkeypatch.setattr(audit, "git", fake_git)
    result = audit.audit(tmp_path)
    assert result["coverage"]["commits"] == 2
    assert result["coverage"]["unique_blobs"] == 1
    found = [r for r in result["findings"] if r["category"] == "device-identifier-candidate"]
    assert len(found) == 1
    assert found[0]["path"] == "deleted-capture.txt" and found[0]["line"] == 2
    assert found[0]["commits"] == [old]
    assert result["counts"]["git-identity"] == 4
    serialized = json.dumps(result)
    assert "EXAMPLE-ONLY-123" not in serialized and "synthetic@example.invalid" not in serialized
    assert result["status"] == "REVIEW_REQUIRED"


def test_checkout_symlink_never_follows_target(tmp_path, monkeypatch):
    outside = tmp_path / "synthetic-outside.txt"
    outside.write_text("EXAMPLE-ONLY-NOT-TO-BE-READ")
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "capture.txt").symlink_to(outside)

    def fake_git(root, *args):
        if args[0] == "rev-parse": return b"true\n"
        if args[0] == "ls-files": return b"capture.txt\0"
        return b""
    monkeypatch.setattr(audit, "git", fake_git)
    result = audit.audit(root)
    assert result["coverage"]["checkout_files"] == 0
    assert {r["category"] for r in result["coverage_gaps"]} >= {"checkout-symlink", "shallow-history"}
    assert "EXAMPLE-ONLY" not in json.dumps(result)


def test_annotated_tag_identity_and_message_are_scanned(tmp_path, monkeypatch):
    tag = "a" * 40
    def fake_git(root, *args):
        if args[0] == "rev-parse": return b"false\n"
        if args[0] == "for-each-ref": return (tag + " tag\n").encode()
        if args[:2] == ("cat-file", "tag"):
            return b"object " + b"b" * 40 + b"\ntype commit\ntag SYNTH-RELEASE\ntagger SYNTH-OWNER <synthetic@example.invalid> 1 +0000\n\nSee 192.0.2.123\n"
        return b""
    monkeypatch.setattr(audit, "git", fake_git)
    result = audit.audit(tmp_path)
    assert result["coverage"]["annotated_tags"] == 1
    assert result["counts"]["git-identity"] == 1
    assert result["counts"]["ipv4"] == 1
    assert all(row["path"] == "<tag-metadata>" for row in result["findings"])
    assert "synthetic@example.invalid" not in json.dumps(result)


def test_audit_error_fails_closed_without_raw_exception(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise RuntimeError("EXAMPLE-ONLY-PRIVATE-DIAGNOSTIC")
    monkeypatch.setattr(audit, "audit", fail)
    output = tmp_path / "result.json"
    assert audit.main(["--output", str(output)]) == 2
    assert "PRIVATE-DIAGNOSTIC" not in capsys.readouterr().out
    assert not output.exists()


def test_sensitive_filename_is_redacted():
    assert audit.safe_path("ordinary/path.txt") == "ordinary/path.txt"
    for path in ("synthetic@example.invalid.txt", "/home/SYNTH-USER/file", "line\nbreak"):
        assert path not in audit.safe_path(path)
        assert audit.safe_path(path).startswith("<redacted-path-")


def test_release_material_consistent_and_ready(draft_release):
    count, errors = release.check(ROOT)
    assert count >= 30 and errors == []
    _, errors = release.check(ROOT, ready=True)
    assert errors == []
    _, errors = release.check(draft_release, ready=True)
    assert "unresolved release placeholder: LICENSE" in errors
