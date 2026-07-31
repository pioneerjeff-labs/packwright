import json
import shlex
from pathlib import Path

from .path_safety import resolve_destination_path


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
    "pi": {
        "config_path": None,
        "runner_path": None,
        "events": {},
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
            if adapter == "pi":
                reason = "Pi Core does not generate executable project extensions"
                status = "unavailable_requires_extension"
            else:
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
            "ownership": "managed_hook_entries" if config["config_path"] else "not_projected",
            "managed_command_marker": MANAGED_RUNNER_NAME,
        },
        "runner": {
            "path": config["runner_path"],
            "runtime": "python3" if config["runner_path"] else None,
            "ownership": "managed_file" if config["runner_path"] else "not_projected",
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


def bind_pack_runtime_paths(pack, target_dir):
    """Bind managed hook commands to one installed target without mutating the source pack."""
    bound = dict(pack)
    try:
        manifest = json.loads(bound["manifest.json"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return bound
    if manifest.get("adapter") != "codex":
        return bound
    feature = manifest.get("features", {}).get("automations", {})
    config = feature.get("config", {}) if isinstance(feature, dict) else {}
    runner = feature.get("runner", {}) if isinstance(feature, dict) else {}
    config_path = config.get("path") if isinstance(config, dict) else None
    runner_path = runner.get("path") if isinstance(runner, dict) else None
    if not isinstance(config_path, str) or not isinstance(runner_path, str):
        return bound
    if config_path not in bound:
        return bound
    absolute_runner = resolve_destination_path(
        target_dir,
        runner_path,
        "installed automation runner",
    )
    data = json.loads(bound[config_path])
    _bind_managed_commands(data, f"python3 {shlex.quote(str(absolute_runner))}")
    bound[config_path] = json.dumps(data, indent=2, sort_keys=True) + "\n"
    return bound


def bind_managed_hook_config(text, target_dir, manifest):
    """Return one managed hook config with Packwright commands bound to target_dir."""
    if manifest.get("adapter") != "codex":
        return text
    feature = manifest.get("features", {}).get("automations", {})
    runner = feature.get("runner", {}) if isinstance(feature, dict) else {}
    runner_path = runner.get("path") if isinstance(runner, dict) else None
    if not isinstance(runner_path, str) or not runner_path:
        return text
    absolute_runner = resolve_destination_path(
        target_dir,
        runner_path,
        "installed automation runner",
    )
    data = json.loads(text)
    _bind_managed_commands(data, f"python3 {shlex.quote(str(absolute_runner))}")
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _bind_managed_commands(value, command_prefix):
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key == "command"
                and isinstance(item, str)
                and MANAGED_RUNNER_NAME in item
            ):
                event = item.rsplit(" ", 1)[-1]
                value[key] = f"{command_prefix} {event}"
            else:
                _bind_managed_commands(item, command_prefix)
    elif isinstance(value, list):
        for item in value:
            _bind_managed_commands(item, command_prefix)


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
            handler = {"type": "command", "command": f"{command} {canonical_event}"}
            if adapter == "codex":
                handler["additionalContextLimit"] = 0
            group = {"hooks": [handler]}
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
        return f"python3 {runner_path}"
    return f"python3 {runner_path}"


def _render_runner(projected, adapter):
    payload = json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    template = '''#!/usr/bin/env python3
import json
import hashlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ADAPTER = __ADAPTER__
AUTOMATIONS = json.loads(__AUTOMATIONS__)
MANAGED_RUNNER_NAME = "packwright_automation.py"
ACTIVATION_SCHEMA = "packwright-runtime-activation-stamp/v1"


def clamp_utf8(text, limit):
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def clamp_memory_view(text, limit, source):
    encoded = text.encode("utf-8")
    total = len(encoded)
    if total <= limit:
        return text
    markers = (
        f"\\n[truncated: budget {limit}/{total} bytes — read {source} for the rest]",
        "\\n[truncated]",
        "[truncated]",
        "~",
    )
    marker = next(
        (candidate for candidate in markers if len(candidate.encode("utf-8")) <= limit),
        "",
    )
    marker_bytes = marker.encode("utf-8")
    content_limit = max(0, limit - len(marker_bytes))
    content = encoded[:content_limit].decode("utf-8", errors="ignore")
    return content + marker


def project_root():
    for key in ("CLAUDE_PROJECT_DIR", "CURSOR_PROJECT_DIR"):
        value = os.environ.get(key)
        if value:
            return Path(value).resolve()
    return Path(__file__).resolve().parents[2]


def managed_fragment_digest(text):
    def has_marker(value):
        if isinstance(value, dict):
            return any(has_marker(item) for item in value.values())
        if isinstance(value, list):
            return any(has_marker(item) for item in value)
        return isinstance(value, str) and MANAGED_RUNNER_NAME in value

    data = json.loads(text)
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    fragment = {
        event: [entry for entry in entries if has_marker(entry)]
        for event, entries in sorted(hooks.items())
        if isinstance(entries, list) and any(has_marker(entry) for entry in entries)
    }
    payload = json.dumps(fragment, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def record_activation(root, event, context):
    if ADAPTER != "codex":
        return
    try:
        config_path = root / ".codex" / "hooks.json"
        hook_digest = managed_fragment_digest(config_path.read_text(encoding="utf-8"))
        stamp_path = root / ".packwright" / "activation" / "codex-hooks.json"
        data = {}
        if stamp_path.is_file():
            data = json.loads(stamp_path.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or data.get("schema") != ACTIVATION_SCHEMA
            or data.get("hook_digest") != hook_digest
            or data.get("target_dir") != str(root.resolve())
        ):
            data = {
                "schema": ACTIVATION_SCHEMA,
                "adapter": "codex",
                "target_dir": str(root.resolve()),
                "hook_digest": hook_digest,
                "events": {},
            }
        automation_ids = sorted(
            automation["id"]
            for automation in AUTOMATIONS
            if automation.get("event") == event
        )
        data["events"][event] = {
            "executed_at": datetime.now().astimezone().isoformat(),
            "context_bytes": len(context.encode("utf-8")),
            "automation_ids": automation_ids,
        }
        stamp_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = stamp_path.with_name(
            stamp_path.name + f".{os.getpid()}.tmp"
        )
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\\n",
            encoding="utf-8",
        )
        temporary.replace(stamp_path)
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        pass


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
        return clamp_memory_view(selected, limit, producer["source"])
    if kind == "freshness_facts":
        now = datetime.now().astimezone()
        facts = []
        for fact in producer.get("facts", []):
            value = now.date().isoformat() if fact["source"] == "system_date" else now.isoformat(timespec="seconds")
            facts.append(f"{fact['field']}: {value}")
        return clamp_utf8("\\n".join(facts), int(automation["budget_bytes"]))
    if kind == "relocation_guard":
        limit = int(automation["budget_bytes"])
        baseline = root / producer["baseline_path"]
        try:
            expected = Path(baseline.read_text(encoding="utf-8").strip()).resolve()
        except (OSError, ValueError):
            return clamp_utf8(
                "Packwright relocation baseline is unavailable; run packwright doctor or reconcile.",
                limit,
            )
        if expected != root.resolve():
            return clamp_utf8(
                f"Packwright instance path changed: installed={expected}; current={root.resolve()}. Reconcile path-sensitive local configuration before relying on it.",
                limit,
            )
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
        print(json.dumps({"additional_context": context} if context else {}), flush=True)
    elif context:
        print(context, flush=True)
    else:
        sys.stdout.flush()
    record_activation(root, event, context)


if __name__ == "__main__":
    main()
'''
    return template.replace("__ADAPTER__", repr(adapter)).replace("__AUTOMATIONS__", repr(payload))
