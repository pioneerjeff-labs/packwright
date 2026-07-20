import hashlib
import json
import re
from pathlib import Path

from .path_safety import resolve_source_path


LOCAL_AUTOMATION_CONFIGS = {
    "claude-code": (
        (".claude/settings.json", "json_settings"),
        (".claude/settings.local.json", "json_settings"),
    ),
    "codex": (
        (".codex/hooks.json", "json_hooks"),
        (".codex/config.toml", "codex_toml"),
    ),
    "cursor": ((".cursor/hooks.json", "json_hooks"),),
}

LOCAL_AUTOMATION_ASSET_ROOTS = {
    "claude-code": (".claude/hooks",),
    "codex": (".codex/hooks",),
    "cursor": (".cursor/hooks",),
}

_KNOWN_EVENTS = (
    "AfterAgentResponse",
    "AfterFileEdit",
    "BeforeAgentResponse",
    "BeforeFileEdit",
    "BeforeShellExecution",
    "BeforeSubmitPrompt",
    "Notification",
    "PostToolUse",
    "PreCompact",
    "PreToolUse",
    "SessionEnd",
    "SessionStart",
    "Stop",
    "SubagentStart",
    "SubagentStop",
    "UserPromptSubmit",
    "afterAgentResponse",
    "afterFileEdit",
    "beforeAgentResponse",
    "beforeFileEdit",
    "beforeShellExecution",
    "beforeSubmitPrompt",
    "sessionEnd",
    "sessionStart",
)
_KNOWN_EVENT_RE = re.compile(
    r"\b(" + "|".join(re.escape(event) for event in _KNOWN_EVENTS) + r")\b"
)
_TOML_HOOK_MARKER_RE = re.compile(
    r"(?im)^\s*(?:\[\[?\s*hooks(?:\.|\]|\s)|hooks\s*=)"
)


def discover_unmanaged_runtime_automation_assets(target_dir, adapter, managed_paths=None):
    """Return local runtime automation evidence without translating behavior."""
    target_dir = Path(target_dir)
    managed_paths = set(managed_paths or ())
    discovered = []
    for rel_path, config_format in LOCAL_AUTOMATION_CONFIGS.get(adapter, ()):
        path = target_dir / rel_path
        if not path.is_file():
            continue
        source = resolve_source_path(target_dir, rel_path, "runtime automation config")
        if rel_path in managed_paths and not _config_has_unmanaged_hook_entries(source):
            continue
        inspection = _inspect_automation_config(source, config_format)
        if not inspection["declares_automation"]:
            continue
        discovered.append(
            _automation_asset(
                source,
                rel_path,
                role="configuration",
                config_format=config_format,
                events=inspection["events"],
                parse_status=inspection["parse_status"],
            )
        )

    if not discovered:
        return []

    for rel_root in LOCAL_AUTOMATION_ASSET_ROOTS.get(adapter, ()):
        root = target_dir / rel_root
        if not root.is_dir():
            continue
        resolve_source_path(target_dir, rel_root, "runtime automation asset root", require_file=False)
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel_path = path.relative_to(target_dir).as_posix()
            if rel_path in managed_paths:
                continue
            source = resolve_source_path(target_dir, rel_path, "runtime automation asset")
            discovered.append(
                _automation_asset(
                    source,
                    rel_path,
                    role="supporting_asset_candidate",
                )
            )
    return sorted(discovered, key=lambda item: item["path"])


def _inspect_automation_config(path, config_format):
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"declares_automation": True, "events": [], "parse_status": "unreadable"}
    if config_format == "codex_toml":
        return _inspect_codex_toml(text)
    return _inspect_json_config(text, settings=config_format == "json_settings")


def _config_has_unmanaged_hook_entries(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return True
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    if not isinstance(hooks, dict):
        return True
    marker = "packwright_automation.py"
    return any(
        marker not in json.dumps(entry, sort_keys=True)
        for entries in hooks.values()
        if isinstance(entries, list)
        for entry in entries
    )


def _inspect_json_config(text, settings):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        declares = '"hooks"' in text or bool(_KNOWN_EVENT_RE.search(text))
        return {
            "declares_automation": declares,
            "events": sorted(set(_KNOWN_EVENT_RE.findall(text))),
            "parse_status": "invalid",
        }
    if not isinstance(data, dict):
        return {"declares_automation": False, "events": [], "parse_status": "parsed"}

    hooks = data.get("hooks")
    if hooks is None and not settings:
        hooks = {
            key: value
            for key, value in data.items()
            if isinstance(key, str) and _KNOWN_EVENT_RE.fullmatch(key)
        }
    declares = bool(hooks)
    events = sorted(str(event) for event in hooks) if isinstance(hooks, dict) else []
    return {"declares_automation": declares, "events": events, "parse_status": "parsed"}


def _inspect_codex_toml(text):
    searchable = _toml_without_comments(text)
    declares = bool(_TOML_HOOK_MARKER_RE.search(searchable))
    events = sorted(set(_KNOWN_EVENT_RE.findall(searchable))) if declares else []
    return {"declares_automation": declares, "events": events, "parse_status": "marker_scan"}


def _toml_without_comments(text):
    lines = []
    for line in text.splitlines():
        quote = None
        escaped = False
        kept = []
        for char in line:
            if escaped:
                kept.append(char)
                escaped = False
                continue
            if char == "\\" and quote == '"':
                kept.append(char)
                escaped = True
                continue
            if char in {"'", '"'}:
                if quote == char:
                    quote = None
                elif quote is None:
                    quote = char
                kept.append(char)
                continue
            if char == "#" and quote is None:
                break
            kept.append(char)
        lines.append("".join(kept))
    return "\n".join(lines)


def _automation_asset(path, rel_path, role, config_format=None, events=None, parse_status=None):
    item = {
        "path": rel_path,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
        "role": role,
    }
    if config_format:
        item["format"] = config_format
    if events:
        item["events"] = list(events)
    if parse_status:
        item["parse_status"] = parse_status
    return item
