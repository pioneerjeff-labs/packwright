#!/usr/bin/env python3
"""Scan release content and reachable history for private data and old names."""

import re
import subprocess
import sys
from pathlib import Path

SELF = "scripts/audit_public_tree.py"
PATTERNS = {
    "private email": re.compile(r"[A-Z0-9._%+-]+@gmail\.com", re.I),
    "private path": re.compile(r"/(?:Users|home)/[^/\s]+/"),
    "old product name": re.compile(r"\bagent(?:[ _-]+)harness\b", re.I),
    "private fixture": re.compile(r"\b(?:Rebecca|Norah|Nora)\b", re.I),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential assignment": re.compile(r"\b(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*['\"][^'\"]+", re.I),
}


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root)


def scan_text(label, text):
    issues = []
    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            issues.append(f"{label}:{line}: {kind}")
    return issues


def candidate_issues(root):
    files = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")
    issues = []
    count = 0
    for raw in files:
        if not raw:
            continue
        rel = raw.decode()
        count += 1
        if rel == SELF:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        issues.extend(scan_text(rel, text))
    return issues, count


def history_issues(root):
    issues = []
    revisions = git(root, "rev-list", "--all").decode().splitlines()
    for rev in revisions:
        metadata = git(root, "show", "-s", "--format=%ae%n%ce", rev).decode(errors="replace")
        for line in metadata.splitlines():
            if PATTERNS["private email"].search(line):
                issues.append(f"{rev}: commit metadata private email")
        paths = git(root, "ls-tree", "-r", "--name-only", "-z", rev).split(b"\0")
        for raw in paths:
            if not raw:
                continue
            rel = raw.decode()
            if rel == SELF:
                continue
            try:
                data = git(root, "show", f"{rev}:{rel}")
                text = data.decode("utf-8")
            except (subprocess.CalledProcessError, UnicodeDecodeError):
                continue
            issues.extend(scan_text(f"{rev}:{rel}", text))
    return issues, len(revisions)


def run(root):
    candidate, files = candidate_issues(root)
    history, commits = history_issues(root)
    return candidate + history, files, commits


def main():
    root = Path(__file__).resolve().parents[1]
    issues, files, commits = run(root)
    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1
    print(f"public-tree audit passed ({files} candidate files, {commits} reachable commits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
