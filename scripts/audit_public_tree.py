#!/usr/bin/env python3
"""Scan release content and reachable history for private data and old names."""

import os
import re
import subprocess
import sys
from pathlib import Path

SELF = "scripts/audit_public_tree.py"
REVISION_ENV = "PACKWRIGHT_PUBLIC_AUDIT_REVISION"
FULL_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", re.I)
ALLOWED_PRIVATE_METADATA_COMMITS = frozenset(
    {
        # GitHub's rebase-and-merge UI created this already-published commit with
        # the repository owner's web-account committer email. Keep the exception
        # commit-scoped so every later private metadata occurrence still fails.
        "c2b582ee8dfdb76a0d19c94215b6c0bfd08104d2",
        "cadaf11e7cee7e41389f89bb5f9db48dc0ec978c",
        "4a979c09e24e47f1520987a486599f19918dee88",
    }
)
PATTERNS = {
    "private email": re.compile(r"[A-Z0-9._%+-]+@gmail\.com", re.I),
    "private path": re.compile(r"/(?:Users|home)/[^/\s]+/"),
    "old product name": re.compile(r"\bagent(?:[ _-]+)harness\b", re.I),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential assignment": re.compile(r"\b(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*['\"][^'\"]+", re.I),
}


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root)


def scan_text(label, text):
    issues = []
    patterns = dict(PATTERNS)
    for index, value in enumerate(os.environ.get("PACKWRIGHT_PUBLIC_AUDIT_DENYLIST", "").splitlines(), start=1):
        value = value.strip()
        if value:
            patterns[f"private denylist entry {index}"] = re.compile(re.escape(value), re.I)
    for kind, pattern in patterns.items():
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


def history_revisions(root, revision=None):
    revision = (revision or "").strip()
    if not revision:
        return git(root, "rev-list", "--all").decode().splitlines()
    if not FULL_OBJECT_ID.fullmatch(revision):
        raise ValueError(f"{REVISION_ENV} must be a full Git object ID")
    return git(root, "rev-list", revision).decode().splitlines()


def history_issues(root, revision=None):
    issues = []
    revisions = history_revisions(root, revision)
    for rev in revisions:
        metadata = git(root, "show", "-s", "--format=%ae%n%ce", rev).decode(errors="replace")
        for line in metadata.splitlines():
            if (
                rev not in ALLOWED_PRIVATE_METADATA_COMMITS
                and PATTERNS["private email"].search(line)
            ):
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


def run(root, revision=None):
    candidate, files = candidate_issues(root)
    history, commits = history_issues(root, revision)
    return candidate + history, files, commits


def main():
    root = Path(__file__).resolve().parents[1]
    try:
        issues, files, commits = run(root, revision=os.environ.get(REVISION_ENV))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1
    print(f"public-tree audit passed ({files} candidate files, {commits} reachable commits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
