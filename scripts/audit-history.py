"""Read-only, redacted privacy triage of local Git history and the checkout.

No matching value, commit message or identity is emitted. This is a heuristic
audit, not a privacy certificate. Exit 1 requires review; exit 2 is an audit error.
Only the requested JSON report is written. No Git metadata is changed.
"""
import argparse
from collections import Counter
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import zlib


RULES = (
    ("local-path", re.compile(r"/(?:home|Users|mnt/storage)/[^\s`\"<>]+")),
    ("email", re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    ("internal-domain", re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.(?:internal|local|lan|corp)\b", re.I)),
    ("login-host", re.compile(r"\b(?:root|admin)@[^\s`\"<>]+")),
    ("ssh-host", re.compile(r"\bssh\s+(?!-)([\w.-]+)\b")),
    ("private-key-marker", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----")),
    ("credential-assignment", re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*[\"']?([A-Za-z0-9_+/-]{16,})")),
    ("wwn", re.compile(r"\b(?:naa\.[0-9a-f]{16}|[0-9a-f]{2}(?::[0-9a-f]{2}){7})\b", re.I)),
    ("public-reference", re.compile(r"https?://[^\s<>\"`]+", re.I)),
)
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6 = re.compile(r"(?<![\w:])(?:[0-9a-f]{0,4}:){2,}[0-9a-f:.]{0,15}(?:%[\w]+)?", re.I)
SERIAL = (
    re.compile(r'(?i)"(?:serial|(?:alternate_)?barcode)"\s*:\s*"([^"\n]+)"'),
    re.compile(r'''(?i)(?:Serial Number\s*[=:]|SCSI_SERIAL=|SCSI_IDENT_[A-Z0-9_]+=|S/N\s*:|(?:Alternate)?VolumeTag\s*=|Medium serial number\s*:)\s*["']?([^\s,"'<>:}]+)'''),
)
SYNTHETIC = re.compile(r"^(?:SYNTH(?:-|$)|SYN[A-Z0-9-]*$|<[^>]+>$)")


def scan_text(text):
    """Return only (line, category, disposition), never captured values."""
    findings = set()
    for number, line in enumerate(text.splitlines(), 1):
        for category, pattern in RULES:
            if pattern.search(line):
                disposition = "reference-review" if category == "public-reference" else "review"
                findings.add((number, category, disposition))
        for pattern in (IPV4, IPV6):
            for match in pattern.finditer(line):
                try:
                    address = ipaddress.ip_address(match[0].split("%")[0])
                except ValueError:
                    continue
                # Loopback, documentation and synthetic addresses still get a
                # location for review. Do not silently allow private ranges.
                category = "ipv4" if address.version == 4 else "ipv6"
                findings.add((number, category, "review"))
        for pattern in SERIAL:
            for match in pattern.finditer(line):
                value = match[1].rstrip("\\")
                if value.lower() in ("null", "none", "unknown", "redacted", "false", "true"):
                    continue
                if SYNTHETIC.match(value):
                    continue
                findings.add((number, "device-identifier-candidate", "review"))
    return sorted(findings)


def safe_path(path):
    # Paths themselves may carry a private value. Preserve ordinary project
    # locations, but avoid emitting an email, absolute path or control sequence.
    if path.startswith("/") or "@" in path or any(ord(c) < 32 for c in path):
        return "<redacted-path-" + hashlib.sha256(path.encode()).hexdigest()[:12] + ">"
    return path


def git(root, *args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1")
    result = subprocess.run(
        ["git", "--no-pager", "-C", str(root), *args],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
    )
    if result.returncode:
        # Git's stderr can contain URLs, identity-bearing paths or config.
        raise RuntimeError("read-only Git command failed: " + args[0])
    return result.stdout


def binary_text(data, ocr=False):
    """Extract PNG text or PDF text/metadata without printing or writing values."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        parts = []
        offset = 8
        while offset + 12 <= len(data):
            length = int.from_bytes(data[offset:offset + 4], "big")
            kind = data[offset + 4:offset + 8]
            if offset + length + 12 > len(data):
                return "\n".join(parts), "png-metadata-incomplete"
            chunk = data[offset + 8:offset + 8 + length]
            try:
                if kind == b"tEXt":
                    parts.append(chunk.replace(b"\0", b": ").decode("latin1"))
                elif kind in (b"zTXt", b"iTXt"):
                    # Compressed/unicode text may hide identifying metadata.
                    # Extract with a bounded output; malformed fields remain a gap.
                    key, rest = chunk.split(b"\0", 1)
                    if kind == b"zTXt":
                        compressed, payload = True, rest[1:]
                    else:
                        compressed = bool(rest[0])
                        payload = rest[2:].split(b"\0", 2)[2]
                    if compressed:
                        decoder = zlib.decompressobj()
                        payload = decoder.decompress(payload, 2 * 1024 * 1024)
                        if not decoder.eof:
                            return "\n".join(parts), "png-metadata-incomplete"
                    parts.append((key + b": " + payload).decode("utf-8", "replace"))
            except (ValueError, IndexError, zlib.error):
                return "\n".join(parts), "png-metadata-incomplete"
            offset += length + 12
        if ocr:
            try:
                result = subprocess.run(
                    ["tesseract", "stdin", "stdout", "--psm", "11"], input=data,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                    env=dict(os.environ, OMP_THREAD_LIMIT="2"),
                )
                if result.returncode:
                    return "\n".join(parts), "png-ocr-incomplete"
                parts.append(result.stdout.decode("utf-8", "replace"))
                return "\n".join(parts), "png-text-metadata-and-ocr"
            except (OSError, subprocess.TimeoutExpired):
                return "\n".join(parts), "png-ocr-unavailable"
        return "\n".join(parts), "png-text-metadata"
    if data.startswith(b"%PDF-"):
        parts = []
        try:
            for command in (["pdftotext", "-", "-"], ["pdfinfo", "-"]):
                result = subprocess.run(command, input=data, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, timeout=30)
                if result.returncode:
                    return "\n".join(parts), "pdf-extraction-incomplete"
                parts.append(result.stdout.decode("utf-8", "replace"))
            return "\n".join(parts), "pdf-text-and-metadata"
        except (OSError, subprocess.TimeoutExpired):
            return "\n".join(parts), "pdf-extraction-unavailable"
    return "\n".join(m.decode("ascii") for m in re.findall(rb"[\x20-\x7e]{6,}", data)), "printable-strings-only"


def audit(root, ocr=False):
    root = root.resolve()
    shallow = git(root, "rev-parse", "--is-shallow-repository").strip() == b"true"
    commits = git(root, "rev-list", "--all", "--reflog", "HEAD").decode().splitlines()
    refs = git(root, "for-each-ref", "--format=%(objectname) %(objecttype)").decode().splitlines()
    blobs = {}
    findings = []
    binaries = []
    raw_commits = {oid: git(root, "cat-file", "commit", oid).decode("utf-8", "replace") for oid in commits}
    # Reuse only identities already present in this repository. Never consult
    # private contacts, system account databases or an organization/name dictionary.
    identity_patterns = set()
    for raw in raw_commits.values():
        for match in re.finditer(r"^(?:author|committer) (.+?) <[^>]+>", raw, re.M):
            name = match[1].strip()
            if len(name) >= 2:
                identity_patterns.add(r"(?<!\w)" + re.escape(name) + r"(?!\w)")
    identities = [re.compile(pattern, re.I) for pattern in sorted(identity_patterns)]
    gaps = [{"category": "natural-language-identity-review", "location": "<all-text>:1",
             "reason": "Arbitrary person/organization names and bare hostnames need human review; no private name dictionary was accessed."}]
    if shallow:
        gaps.append({"category": "shallow-history", "location": "<history>:1",
                     "reason": "Repository is shallow; unavailable ancestors were not scanned."})
    if git(root, "replace", "-l").strip():
        gaps.append({"category": "replace-refs", "location": "<history>:1",
                     "reason": "Replace refs exist; original objects scanned with replacements disabled."})

    def record(text, path, oid, revisions):
        for line, category, disposition in scan_text(text):
            findings.append({"path": safe_path(path), "line": line, "category": category,
                             "disposition": disposition, "object": oid, "commits": sorted(revisions)})
        for number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in identities):
                findings.append({"path": safe_path(path), "line": number,
                                 "category": "metadata-identity-string", "disposition": "review",
                                 "object": oid, "commits": sorted(revisions)})

    for commit in commits:
        raw = raw_commits[commit]
        for number, line in enumerate(raw.splitlines(), 1):
            if line.startswith(("author ", "committer ")):
                findings.append({"path": "<commit-metadata>", "line": number,
                                 "category": "git-identity", "disposition": "review",
                                 "object": commit, "commits": [commit]})
        record(raw, "<commit-metadata>", commit, [commit])
        for entry in git(root, "ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
            if not entry:
                continue
            meta, rawpath = entry.split(b"\t", 1)
            mode, kind, oid = meta.decode().split()
            path = rawpath.decode("utf-8", "replace")
            record(path, "<tree-path>", oid, [commit])
            if kind != "blob":
                gaps.append({"category": "gitlink", "location": safe_path(path) + ":1",
                             "reason": "Referenced submodule contents are outside this repository."})
                continue
            item = blobs.setdefault(oid, {})
            item.setdefault(path, set()).add(commit)
            if mode == "120000":
                gaps.append({"category": "historical-symlink", "location": safe_path(path) + ":1",
                             "reason": "Link text scanned; target not followed."})

    tag_count = 0
    seen_tags = set()
    for row in refs:
        oid, kind = row.split()
        while kind == "tag" and oid not in seen_tags:
            seen_tags.add(oid)
            raw = git(root, "cat-file", "tag", oid).decode("utf-8", "replace")
            record(raw, "<tag-metadata>", oid, [])
            for number, line in enumerate(raw.splitlines(), 1):
                if line.startswith("tagger "):
                    findings.append({"path": "<tag-metadata>", "line": number,
                                     "category": "git-identity", "disposition": "review",
                                     "object": oid, "commits": []})
            tag_count += 1
            header = dict(line.split(" ", 1) for line in raw.split("\n\n", 1)[0].splitlines() if " " in line)
            oid, kind = header.get("object", ""), header.get("type", "")

    text_blobs = 0
    for oid, locations in sorted(blobs.items()):
        data = git(root, "cat-file", "blob", oid)
        try:
            decoded = data.decode("utf-8")
            binary = "\0" in decoded
        except UnicodeDecodeError:
            binary = True
        if binary:
            decoded, extraction = binary_text(data, ocr=ocr)
            for path, revisions in locations.items():
                binaries.append({"path": safe_path(path), "object": oid,
                                 "commits": sorted(revisions), "bytes": len(data),
                                 "extraction": extraction,
                                 "status": "manual-pixels-and-metadata-review-required"})
        else:
            text_blobs += 1
        for path, revisions in locations.items():
            record(decoded, path, oid, revisions)

    # Include uncommitted tracked files and nonignored untracked files. Never
    # walk the filesystem or follow a worktree symlink into private material.
    checkout_count = 0
    checkout_hashes = {}
    names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")
    for name in sorted(set(names)):
        if not name:
            continue
        relative = name.decode("utf-8", "replace")
        path = root / relative
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and root in p.parents):
            gaps.append({"category": "checkout-symlink", "location": safe_path(relative) + ":1",
                         "reason": "Symlink not followed."})
            continue
        if not path.is_file():
            continue
        # Reports are derived evidence, not release input; avoid a self-scan
        # feedback loop. Historical versions, if committed, are still scanned.
        if relative.startswith("artifacts/release/privacy-"):
            continue
        data = path.read_bytes()
        checkout_count += 1
        checkout_hashes[safe_path(relative)] = hashlib.sha256(data).hexdigest()
        blob_oid = git_blob_id(data)
        if relative in blobs.get(blob_oid, {}):
            for row in findings:
                if row["object"] == blob_oid and row["path"] == safe_path(relative):
                    row["present_in_checkout"] = True
            continue
        try:
            decoded = data.decode("utf-8")
            if "\0" in decoded:
                raise UnicodeError()
        except UnicodeError:
            # Historical binaries are inventoried above; new ones need review.
            decoded, extraction = binary_text(data, ocr=ocr)
            if git_blob_id(data) not in blobs:
                binaries.append({"path": safe_path(relative), "object": "WORKTREE",
                                 "commits": [], "bytes": len(data),
                                 "extraction": extraction,
                                 "status": "manual-pixels-and-metadata-review-required"})
        record(decoded, relative, "WORKTREE", [])

    for row in findings:
        row.setdefault("present_in_checkout", row["object"] == "WORKTREE")

    counts = dict(sorted(Counter(row["category"] for row in findings).items()))
    return {
        "schema": "tapediag-privacy-audit/v1", "status": "REVIEW_REQUIRED",
        "scope": "All local refs, HEAD and reflog-reachable commits; every tree/blob version; annotated tags; nonignored checkout files.",
        "limits": ["No network fetch; remote-only or pruned/unreachable objects are outside this scan.",
                   "No secret/name values emitted; detection is heuristic and may have false positives/negatives.",
                   "Binary extracted text/metadata are scanned; their line numbers refer to extraction output, not source lines. Pixels require human review.",
                   "No automatic clearance, history rewrite, signing or publication."],
        "coverage": {"commits": len(commits), "unique_blobs": len(blobs), "text_blobs": text_blobs,
                     "binary_locations": len(binaries), "annotated_tags": tag_count,
                     "local_refs": len(refs), "checkout_files": checkout_count, "shallow": shallow,
                     "ocr_requested": ocr},
        "commits": commits, "counts": counts, "checkout_sha256": checkout_hashes,
        "findings": sorted(findings, key=lambda r: (r["path"], r["object"], r["line"], r["category"])),
        "binary_review": binaries, "coverage_gaps": gaps,
    }


def git_blob_id(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ocr", action="store_true", help="also inspect PNG pixels with an existing local Tesseract; no install or network")
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, ocr=args.ocr)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        print("Privacy audit ERROR: input/Git operation failed; no raw diagnostic values emitted.")
        return 2
    print(json.dumps({"status": result["status"], "coverage": result["coverage"], "counts": result["counts"]}, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
