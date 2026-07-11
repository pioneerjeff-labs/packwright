#!/usr/bin/env python3
"""Scan tracked release content for private data, credentials, and old names."""

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "private email": re.compile(r"[A-Z0-9._%+-]+@gmail\.com", re.I),
    "private path": re.compile(r"/(?:Users|home)/[^/\s]+/"),
    "old product name": re.compile(r"\bagent harness\b", re.I),
    "private fixture": re.compile(r"\b(?:Rebecca|Norah|Nora)\b", re.I),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential assignment": re.compile(r"\b(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*['\"][^'\"]+", re.I),
}


def main():
    root = Path(__file__).resolve().parents[1]
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    ).split(b"\0")
    issues = []
    for raw in files:
        if not raw: continue
        rel = raw.decode()
        if rel == "scripts/audit_public_tree.py":
            continue
        path = root / rel
        try: text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError): continue
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                issues.append(f"{rel}:{line}: {label}")
    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1
    print(f"public-tree audit passed ({len(files) - 1} tracked files)")
    return 0


if __name__ == "__main__": raise SystemExit(main())
