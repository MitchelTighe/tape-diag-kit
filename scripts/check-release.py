"""Check release-material consistency (metadata, notices and local links)."""
import argparse
import json
from pathlib import Path
import re

try:
    import tomllib
except ImportError:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md",
    "docs/LICENSE-REVIEW.md",
    "requirements-lint.txt", "Containerfile.lint", "scripts/check-lint.sh",
)


def check(root, ready=False):
    errors = []
    checks = 0

    def require(condition, label):
        nonlocal checks
        checks += 1
        if not condition:
            errors.append(label)

    for name in REQUIRED:
        require((root / name).is_file(), "missing required file: " + name)
    if errors:
        return checks, errors

    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    require(project["license"] == "MIT", "project license metadata")
    require(project["dependencies"] == [], "unexpected runtime dependency")
    require(project.get("optional-dependencies") == {"dta": ["tomli==2.3.0; python_version < '3.11'"]},
            "unexpected optional dependency")
    require(project["scripts"] == {"tapediag": "tapediag.cli:main", "dta": "tapediag.dta:main"},
            "console entry points")
    require(set(project["license-files"]) == {"LICENSE", "fixtures/NOTICES.md"}, "distribution license notices")
    license_text = (root / "LICENSE").read_text()
    for phrase in ("MIT License", "Permission is hereby granted, free of charge", "THE SOFTWARE IS PROVIDED", "tapediag contributors", "not relicensed"):
        require(phrase in license_text, "missing license clause/notice: " + phrase)

    # Check actual local Markdown links, not placeholders, bare URLs or fences.
    markdown = [root / name for name in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md")]
    markdown += sorted((root / "docs").rglob("*.md"))
    for path in markdown:
        content = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
            if target.startswith(("https://", "http://", "#", "<")):
                continue
            local = target.split("#", 1)[0]
            require((path.parent / local).is_file(), "broken local link in " + str(path.relative_to(root)))

    if ready:
        # Readiness additionally rejects unresolved placeholders.
        for name in ("README.md", "LICENSE", "pyproject.toml", "SECURITY.md", "CONTRIBUTING.md"):
            require(not re.search(r"<[A-Z][A-Z0-9_]*>", (root / name).read_text()), "unresolved release placeholder: " + name)
    return checks, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready", action="store_true", help="also reject unresolved placeholders in release-facing files")
    args = parser.parse_args(argv)
    try:
        count, errors = check(ROOT, args.ready)
    except (OSError, ValueError, KeyError, TypeError):
        print("Release material check ERROR: malformed or unreadable input.")
        return 2
    print(json.dumps({"mode": "readiness" if args.ready else "consistency", "checks": count,
                      "status": "FAIL" if errors else "PASS", "errors": errors}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
