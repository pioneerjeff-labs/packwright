import json


AUTOMATION_FEATURE_SCHEMA = "packwright-runtime-automations/v1"
MANAGED_RUNNER_NAME = "packwright_automation.py"

_ADAPTERS = {
    "claude-code": {
        "config_path": ".claude/settings.json",
        "runner_path": f".claude/hooks/{MANAGED_RUNNER_NAME}",
        "events": {"session_start": "SessionStart", "user_prompt": "UserPromptSubmit"},
        "pending_review": False,
    },
    "codex": {
        "config_path": ".codex/hooks.json",
        "runner_path": f".codex/hooks/{MANAGED_RUNNER_NAME}",
        "events": {"session_start": "SessionStart", "user_prompt": "UserPromptSubmit"},
        "pending_review": True,
    },
    "cursor": {
        "config_path": ".cursor/hooks.json",
        "runner_path": f".cursor/hooks/{MANAGED_RUNNER_NAME}",
        "events": {"session_start": "sessionStart"},
        "pending_review": False,
    },
}


def project_runtime_automations(mechanism, adapter):
    """Project canonical local add-context automations into one runtime."""
    config = _ADAPTERS[adapter]
    records = []
    projected = []
    for automation in mechanism.get("automations", []):
        event = automation.get("event")
        if event not in config["events"]:
            reason = "destination event cannot add model context"
            status = "unavailable_missing_effect" if adapter == "cursor" and event == "user_prompt" else "unavailable_missing_event"
            records.append(_record(automation, adapter, status, reason=reason))
            continue
        status = "projected_pending_user_review" if config["pending_review"] else "projected"
        records.append(
            _record(
                automation,
                adapter,
                status,
                native_event=config["events"][event],
            )
        )
        projected.append(automation)

    files = {}
    if projected:
        files[config["runner_path"]] = _render_runner(projected, adapter)
        files[config["config_path"]] = _render_config(projected, adapter, config)

    feature = {
        "schema": AUTOMATION_FEATURE_SCHEMA,
        "scope": "local",
        "canonical_source": "automations",
        "config": {
            "path": config["config_path"],
            "ownership": "managed_hook_entries",
            "managed_command_marker": MANAGED_RUNNER_NAME,
        },
        "runner": {
            "path": config["runner_path"],
            "runtime": "python3",
            "ownership": "managed_file",
        },
        "records": records,
        "summary": _summary(records),
        "cloud": "out_of_scope",
    }
    return files, feature


def automation_config_paths(manifest):
    feature = manifest.get("features", {}).get("automations", {}) if isinstance(manifest, dict) else {}
    config = feature.get("config", {}) if isinstance(feature, dict) else {}
    path = config.get("path") if isinstance(config, dict) else None
    return {path} if isinstance(path, str) and path else set()


def is_managed_automation_config(manifest, rel_path):
    return rel_path in automation_config_paths(manifest)


def merge_managed_hook_config(existing_text, desired_text, marker=MANAGED_RUNNER_NAME):
    """Preserve user JSON and replace only Packwright-owned hook entries."""
    existing = json.loads(existing_text) if existing_text.strip() else {}
    desired = json.loads(desired_text)
    if not isinstance(existing, dict) or not isinstance(desired, dict):
        raise ValueError("hook configuration root must be a JSON object")
    merged = dict(existing)
    desired_hooks = desired.get("hooks", {})
    existing_hooks = existing.get("hooks", {})
    if not isinstance(desired_hooks, dict) or not isinstance(existing_hooks, dict):
        raise ValueError("hooks must be a JSON object")
    hooks = {}
    for event in sorted(set(existing_hooks) | set(desired_hooks)):
        old_entries = existing_hooks.get(event, [])
        new_entries = desired_hooks.get(event, [])
        if not isinstance(old_entries, list) or not isinstance(new_entries, list):
            raise ValueError(f"hooks.{event} must be a list")
        preserved = [entry for entry in old_entries if not _entry_has_marker(entry, marker)]
        hooks[event] = preserved + new_entries
    merged.update({key: value for key, value in desired.items() if key != "hooks" and key not in merged})
    merged["hooks"] = hooks
    return json.dumps(merged, indent=2, sort_keys=True) + "\n"


def managed_hook_fragment_digest(text, marker=MANAGED_RUNNER_NAME):
    import hashlib

    data = json.loads(text)
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    fragment = {
        event: [entry for entry in entries if _entry_has_marker(entry, marker)]
        for event, entries in sorted(hooks.items())
        if isinstance(entries, list) and any(_entry_has_marker(entry, marker) for entry in entries)
    }
    payload = json.dumps(fragment, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _entry_has_marker(value, marker):
    if isinstance(value, dict):
        return any(_entry_has_marker(item, marker) for item in value.values())
    if isinstance(value, list):
        return any(_entry_has_marker(item, marker) for item in value)
    return isinstance(value, str) and marker in value


def _record(automation, adapter, status, native_event=None, reason=None):
    result = {
        "id": automation.get("id"),
        "canonical_event": automation.get("event"),
        "effect": automation.get("effect"),
        "producer": automation.get("producer", {}).get("kind"),
        "adapter": adapter,
        "status": status,
    }
    if native_event:
        result["native_event"] = native_event
    if reason:
        result["reason"] = reason
        result["required_user_decision"] = "accept_degraded_behavior_or_change_canonical_intent"
    return result


def _summary(records):
    summary = {}
    for record in records:
        status = record["status"]
        summary[status] = summary.get(status, 0) + 1
    return summary


def _render_config(projected, adapter, config):
    native_events = sorted({config["events"][item["event"]] for item in projected})
    command = _command(adapter, config["runner_path"])
    hooks = {}
    for native_event in native_events:
        canonical_event = "session_start" if native_event in {"SessionStart", "sessionStart"} else "user_prompt"
        if adapter in {"claude-code", "codex"}:
            group = {"hooks": [{"type": "command", "command": f"{command} {canonical_event}"}]}
            if adapter == "codex" and native_event == "SessionStart":
                group["matcher"] = "startup|resume|clear|compact"
            hooks[native_event] = [group]
        else:
            hooks[native_event] = [{"command": f"{command} {canonical_event}"}]
    root = {"hooks": hooks}
    if adapter == "cursor":
        root["version"] = 1
    if adapter == "codex":
        root["description"] = "Packwright-managed local context automations."
    return json.dumps(root, indent=2, sort_keys=True) + "\n"


def _command(adapter, runner_path):
    if adapter == "claude-code":
        return f'python3 "$CLAUDE_PROJECT_DIR/{runner_path}"'
    if adapter == "codex":
        return f'python3 "$(git rev-parse --show-toplevel 2>/dev/null || pwd -P)/{runner_path}"'
    return f"python3 {runner_path}"


def _render_runner(projected, adapter):
    payload = json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    template = '''#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ADAPTER = __ADAPTER__
AUTOMATIONS = json.loads(__AUTOMATIONS__)


def clamp_utf8(text, limit):
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def project_root():
    for key in ("CLAUDE_PROJECT_DIR", "CURSOR_PROJECT_DIR"):
        value = os.environ.get(key)
        if value:
            return Path(value).resolve()
    return Path(__file__).resolve().parents[2]


def markdown_slice(text, select):
    lines = text.splitlines()
    section = select.get("section")
    until = select.get("until_section")
    if section:
        wanted = str(section).strip().casefold()
        start = None
        level = None
        for index, line in enumerate(lines):
            match = re.match(r"^(#{1,6})\\s+(.+?)\\s*$", line)
            if match and match.group(2).strip().casefold() == wanted:
                start, level = index + 1, len(match.group(1))
                break
        if start is None:
            return ""
        end = len(lines)
        for index in range(start, len(lines)):
            match = re.match(r"^(#{1,6})\\s+(.+?)\\s*$", lines[index])
            if match and (len(match.group(1)) <= level or (until and match.group(2).strip().casefold() == str(until).strip().casefold())):
                end = index
                break
        lines = lines[start:end]
    elif until:
        wanted = str(until).strip().casefold()
        for index, line in enumerate(lines):
            match = re.match(r"^(#{1,6})\\s+(.+?)\\s*$", line)
            if match and match.group(2).strip().casefold() == wanted:
                lines = lines[:index]
                break
    latest = select.get("bullets_latest")
    if latest:
        bullets = [line for line in lines if re.match(r"^\\s*[-*+]\\s+", line)]
        lines = bullets[-int(latest):]
    return "\\n".join(lines).strip()


def produce(automation, root):
    producer = automation["producer"]
    kind = producer["kind"]
    if kind == "memory_view":
        source = root / producer["source"]
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""
        selected = markdown_slice(text, producer.get("select", {}))
        limit = min(int(automation["budget_bytes"]), int(producer.get("select", {}).get("max_bytes", automation["budget_bytes"])))
        return clamp_utf8(selected, limit)
    if kind == "freshness_facts":
        now = datetime.now().astimezone()
        facts = []
        for fact in producer.get("facts", []):
            value = now.date().isoformat() if fact["source"] == "system_date" else now.isoformat(timespec="seconds")
            facts.append(f"{fact['field']}: {value}")
        return clamp_utf8("\\n".join(facts), int(automation["budget_bytes"]))
    if kind == "relocation_guard":
        baseline = root / producer["baseline_path"]
        try:
            expected = Path(baseline.read_text(encoding="utf-8").strip()).resolve()
        except (OSError, ValueError):
            return "Packwright relocation baseline is unavailable; run packwright doctor or reconcile."
        if expected != root.resolve():
            return f"Packwright instance path changed: installed={expected}; current={root.resolve()}. Reconcile path-sensitive local configuration before relying on it."
    return ""


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    root = project_root()
    chunks = []
    for automation in AUTOMATIONS:
        if automation.get("event") != event:
            continue
        value = produce(automation, root)
        if value:
            chunks.append(f"[packwright:{automation['id']}]\\n{value}")
    context = "\\n\\n".join(chunks)
    if ADAPTER == "cursor":
        print(json.dumps({"additional_context": context} if context else {}))
    elif context:
        print(context)


if __name__ == "__main__":
    main()
'''
    return template.replace("__ADAPTER__", repr(adapter)).replace("__AUTOMATIONS__", repr(payload))
