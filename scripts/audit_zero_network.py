#!/usr/bin/env python3
"""Fail when Packwright code or its landing page can initiate network traffic."""

import argparse
import ast
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

NETWORK_MODULES = {"aiohttp", "ftplib", "http", "httpx", "requests", "smtplib", "socket", "telnetlib", "urllib", "websockets"}
NETWORK_CALLS = {"fetch", "WebSocket", "EventSource", "XMLHttpRequest", "sendBeacon"}
EXTERNAL = re.compile(r"^(?:https?:)?//", re.I)
CSS_AUTO = re.compile(r"(?:@import\s+|url\s*\(\s*)['\"]?(?:https?:)?//", re.I)
JS_AUTO = re.compile(r"\b(?:fetch|WebSocket|EventSource|XMLHttpRequest)\s*\(|\.sendBeacon\s*\(", re.I)


class LandingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.issues = []
        self.csp = []
        self.in_style = False
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta" and values.get("http-equiv", "").lower() == "content-security-policy":
            self.csp.append(values.get("content", ""))
        if tag in {"script", "img", "iframe", "audio", "video", "source", "track", "embed", "object", "input"}:
            for name in ("src", "srcset", "data", "poster"):
                if EXTERNAL.match(values.get(name, "").strip()):
                    self.issues.append(f"external auto-loaded <{tag}> {name}")
        if tag == "link" and "stylesheet" in values.get("rel", "").lower() and EXTERNAL.match(values.get("href", "").strip()):
            self.issues.append("external stylesheet")
        if CSS_AUTO.search(values.get("style", "")):
            self.issues.append(f"external CSS in <{tag}> style")
        self.in_style = tag == "style"
        self.in_script = tag == "script"

    def handle_endtag(self, tag):
        if tag == "style": self.in_style = False
        if tag == "script": self.in_script = False

    def handle_data(self, data):
        if self.in_style and CSS_AUTO.search(data): self.issues.append("external CSS auto-load")
        if self.in_script and JS_AUTO.search(data): self.issues.append("network JavaScript call")


def audit_python(path):
    issues = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        return [f"{path}: cannot parse: {exc}"]
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                root = item.name.split(".")[0]
                aliases[item.asname or root] = root
                if root in NETWORK_MODULES: issues.append(f"{path}:{node.lineno}: imports {item.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in NETWORK_MODULES: issues.append(f"{path}:{node.lineno}: imports from {node.module}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in NETWORK_CALLS:
                issues.append(f"{path}:{node.lineno}: calls {func.id}")
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if aliases.get(func.value.id) in NETWORK_MODULES:
                    issues.append(f"{path}:{node.lineno}: calls {func.value.id}.{func.attr}")
    return issues


def audit_landing(path):
    parser = LandingParser()
    parser.feed(path.read_text(encoding="utf-8"))
    required = {"default-src 'none'", "style-src 'unsafe-inline'", "script-src 'none'", "img-src 'self' data:"}
    csp = parser.csp[0] if parser.csp else ""
    if not parser.csp: parser.issues.append("missing CSP meta tag")
    for directive in required:
        if directive not in csp: parser.issues.append(f"CSP missing {directive}")
    return [f"{path}: {item}" for item in parser.issues]


def run(root):
    issues = []
    for path in sorted((root / "src").rglob("*.py")):
        issues.extend(audit_python(path))
    for path in sorted((root / "site").rglob("*.html")):
        issues.extend(audit_landing(path))
    for path in sorted((root / "site").rglob("*.css")):
        if CSS_AUTO.search(path.read_text(encoding="utf-8")):
            issues.append(f"{path}: external CSS auto-load")
    return issues


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    issues = run(args.root.resolve())
    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1
    print("zero-network audit passed")
    return 0


if __name__ == "__main__": raise SystemExit(main())
