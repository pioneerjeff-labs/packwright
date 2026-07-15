#!/usr/bin/env python3
"""Fail when Packwright release content can initiate network traffic."""

import argparse
import ast
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


NETWORK_MODULES = {
    "aiohttp",
    "asyncio",
    "ftplib",
    "http",
    "httpx",
    "importlib",
    "requests",
    "smtplib",
    "socket",
    "subprocess",
    "telnetlib",
    "urllib",
    "webbrowser",
    "websockets",
}
NETWORK_CALLS = {"EventSource", "WebSocket", "XMLHttpRequest", "fetch", "sendBeacon"}
OS_EXECUTION_CALLS = {"popen", "system"}
EXTERNAL = re.compile(r"^(?:https?:)?//", re.I)
CSS_AUTO = re.compile(r"(?:@import\s+|url\s*\(\s*)['\"]?(?:https?:)?//", re.I)
JS_NETWORK_CALL = re.compile(
    r"\b(?:fetch|WebSocket|EventSource|XMLHttpRequest)\s*\(|\.sendBeacon\s*\(",
    re.I,
)
JS_DYNAMIC_IMPORT = re.compile(r"\bimport\s*\(", re.I)
JS_NEW_IMAGE_SRC = re.compile(r"new\s+Image\s*\([^)]*\)\s*\.src\s*=", re.I)
JS_EXTERNAL_SRC_ASSIGN = re.compile(r"\.src\s*=\s*['\"](?:https?:)?//", re.I)
AUTO_LOADING_LINK_RELS = {
    "dns-prefetch",
    "modulepreload",
    "preconnect",
    "prefetch",
    "preload",
    "stylesheet",
}
SCAN_ROOTS = ("src", "scripts", "templates", "examples")
SAFE_IMPORTS = {("scripts/audit_public_tree.py", "subprocess")}
SAFE_CALLS = {("scripts/audit_public_tree.py", "subprocess", "check_output")}


def _relative_label(path, root=None):
    path = Path(path)
    if root is not None:
        try:
            return path.resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def _is_exempt(path_label, module, attr=None):
    normalized = path_label.replace("\\", "/")
    collection = SAFE_CALLS if attr else SAFE_IMPORTS
    expected = ("scripts/audit_public_tree.py", module, attr) if attr else (
        "scripts/audit_public_tree.py",
        module,
    )
    return expected in collection and normalized.endswith(expected[0])


def _audit_python_source(text, path_label):
    issues = []
    try:
        tree = ast.parse(text, filename=path_label)
    except SyntaxError as exc:
        return [f"{path_label}: cannot parse: {exc}"]

    aliases = {}
    imported_calls = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                root = item.name.split(".")[0]
                aliases[item.asname or root] = root
                if root in NETWORK_MODULES and not _is_exempt(path_label, root):
                    issues.append(f"{path_label}:{node.lineno}: imports {item.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            for item in node.names:
                imported_calls[item.asname or item.name] = (root, item.name)
            if root in NETWORK_MODULES and not _is_exempt(path_label, root):
                issues.append(f"{path_label}:{node.lineno}: imports from {node.module}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id in NETWORK_CALLS:
                    issues.append(f"{path_label}:{node.lineno}: calls {func.id}")
                elif func.id in imported_calls:
                    module, attr = imported_calls[func.id]
                    if module in NETWORK_MODULES and not _is_exempt(path_label, module, attr):
                        issues.append(f"{path_label}:{node.lineno}: calls {module}.{attr}")
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                module = aliases.get(func.value.id, func.value.id)
                if module in NETWORK_MODULES and not _is_exempt(path_label, module, func.attr):
                    issues.append(f"{path_label}:{node.lineno}: calls {func.value.id}.{func.attr}")
                elif module == "os" and func.attr in OS_EXECUTION_CALLS:
                    issues.append(f"{path_label}:{node.lineno}: calls os.{func.attr}")
    return issues


def audit_python(path, root=None):
    path_label = _relative_label(path, root)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path_label}: cannot read: {exc}"]
    return _audit_python_source(text, path_label)


def audit_embedded_python(path, root=None):
    """Audit Python source stored in generated helper strings."""
    path_label = _relative_label(path, root)
    try:
        text = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(text, filename=path_label)
    except (OSError, SyntaxError):
        return []

    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        candidate = node.value.strip()
        if not candidate.startswith(("import ", "from ")) and "\nimport " not in candidate and "\nfrom " not in candidate:
            continue
        embedded_label = f"{path_label}:{node.lineno}:embedded"
        try:
            ast.parse(candidate, filename=embedded_label)
        except SyntaxError:
            continue
        issues.extend(_audit_python_source(candidate, embedded_label))
    return issues


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
        if tag == "link":
            rels = set(values.get("rel", "").lower().split())
            if rels & AUTO_LOADING_LINK_RELS and EXTERNAL.match(values.get("href", "").strip()):
                self.issues.append(f"external auto-loaded <link> {sorted(rels & AUTO_LOADING_LINK_RELS)[0]}")
        if CSS_AUTO.search(values.get("style", "")):
            self.issues.append(f"external CSS in <{tag}> style")
        self.in_style = tag == "style"
        self.in_script = tag == "script"

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_style and CSS_AUTO.search(data):
            self.issues.append("external CSS auto-load")
        if self.in_script:
            self.issues.extend(_javascript_issues(data))


def _parse_csp(value):
    directives = {}
    duplicates = []
    for raw_directive in value.split(";"):
        parts = raw_directive.strip().split()
        if not parts:
            continue
        name = parts[0].lower()
        if name in directives:
            duplicates.append(name)
        directives[name] = parts[1:]
    return directives, duplicates


def _audit_csp(value):
    issues = []
    directives, duplicates = _parse_csp(value)
    for name in duplicates:
        issues.append(f"CSP duplicates {name}")

    required_values = {
        "default-src": {"'none'"},
        "style-src": {"'unsafe-inline'"},
        "img-src": {"'self'", "data:"},
    }
    for name, required in required_values.items():
        values = set(directives.get(name, []))
        if not required.issubset(values):
            issues.append(f"CSP {name} must include {' '.join(sorted(required))}")

    if directives.get("connect-src") != ["'none'"]:
        issues.append("CSP connect-src must be exactly 'none'")
    script_values = set(directives.get("script-src", []))
    if script_values not in ({"'none'"}, {"'self'"}):
        issues.append("CSP script-src must be exactly 'none' or 'self'")

    network_sources = {"*", "http:", "https:", "ws:", "wss:"}
    for name, values in directives.items():
        for value_item in values:
            if value_item.lower() in network_sources or EXTERNAL.match(value_item):
                issues.append(f"CSP {name} permits network source {value_item}")
    return issues


def audit_landing(path):
    parser = LandingParser()
    parser.feed(Path(path).read_text(encoding="utf-8"))
    if not parser.csp:
        parser.issues.append("missing CSP meta tag")
    else:
        parser.issues.extend(_audit_csp(parser.csp[0]))
        if len(parser.csp) > 1:
            parser.issues.append("multiple CSP meta tags")
    return [f"{path}: {item}" for item in parser.issues]


def _javascript_issues(source):
    issues = []
    checks = (
        (JS_NETWORK_CALL, "network JavaScript call"),
        (JS_DYNAMIC_IMPORT, "dynamic JavaScript import"),
        (JS_NEW_IMAGE_SRC, "new Image().src assignment"),
        (JS_EXTERNAL_SRC_ASSIGN, "external JavaScript src assignment"),
    )
    for pattern, label in checks:
        if pattern.search(source):
            issues.append(label)
    return issues


def audit_javascript(path):
    return [f"{path}: {item}" for item in _javascript_issues(Path(path).read_text(encoding="utf-8"))]


def run(root):
    root = Path(root)
    issues = []
    seen_python = set()
    for directory in SCAN_ROOTS:
        scan_root = root / directory
        for path in sorted(scan_root.rglob("*.py")):
            resolved = path.resolve()
            if resolved in seen_python:
                continue
            seen_python.add(resolved)
            issues.extend(audit_python(path, root=root))
            issues.extend(audit_embedded_python(path, root=root))
    for path in sorted((root / "site").rglob("*.html")):
        issues.extend(audit_landing(path))
    for path in sorted((root / "site").rglob("*.css")):
        if CSS_AUTO.search(path.read_text(encoding="utf-8")):
            issues.append(f"{path}: external CSS auto-load")
    for path in sorted((root / "site").rglob("*.js")):
        issues.extend(audit_javascript(path))
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


if __name__ == "__main__":
    raise SystemExit(main())
