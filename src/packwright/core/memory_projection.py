import re

from .naming import character_slug, reference_prefix, save_context_skill_path


def project_memory_file(mechanism, adapter, rel_path, text):
    """Project portable memory text into adapter-specific runtime wording."""
    if rel_path == "memory/index.md":
        return _project_memory_index(mechanism, adapter, text)
    if rel_path == "memory/pinned.md":
        return _project_pinned_memory(mechanism, adapter, text)
    if rel_path == "memory/source-map.md":
        return _project_source_map(mechanism, adapter, text)
    return text


def adapter_entry_path(mechanism, adapter):
    if adapter == "codex":
        return "AGENTS.md"
    if adapter == "claude-code":
        return "CLAUDE.md"
    if adapter == "cursor":
        return f".cursor/rules/{character_slug(mechanism)}.mdc"
    return "platform entry file"


def _project_memory_index(mechanism, adapter, text):
    entry = adapter_entry_path(mechanism, adapter)
    text = re.sub(
        r"- Stable identity, voice, and default work rules -> `[^`]+`(?: or equivalent platform entry file)?",
        f"- Stable identity, voice, and default work rules -> `{entry}`",
        text,
    )
    emotion_owner = (
        "- Dynamic emotion state and compact emotion history -> `.emotion-engine/codex-state.json` when enabled"
        if adapter == "codex"
        else "- Dynamic emotion state and compact emotion history -> adapter-specific runtime state when installed; "
        "`memory/emotion-state.json.example` is the portable reference shape"
    )
    text = re.sub(
        r"- Dynamic emotion state and compact emotion history -> .+",
        emotion_owner,
        text,
    )
    return text


def _project_pinned_memory(mechanism, adapter, text):
    entry = adapter_entry_path(mechanism, adapter)
    text = re.sub(
        r"Use `memory/index\.md` for routing, `[^`]+` for stable behavior,",
        f"Use `memory/index.md` for routing, `{entry}` for stable behavior,",
        text,
    )
    return re.sub(
        r"Use `memory/index\.md` for routing, the platform entry file for stable behavior,",
        f"Use `memory/index.md` for routing, `{entry}` for stable behavior,",
        text,
    )


def _project_source_map(mechanism, adapter, text):
    label = _adapter_label(adapter)
    entry = adapter_entry_path(mechanism, adapter)
    save_context = save_context_skill_path(mechanism, adapter)
    save_context_name = "save-context rule" if adapter == "cursor" else "save-context skill"
    update_policy = f"{reference_prefix(mechanism, adapter)}/emotion/update-policy.yaml"

    text = re.sub(
        r"- Current (Codex|Claude Code|Cursor) entry -> `[^`]+`",
        f"- Current {label} entry -> `{entry}`",
        text,
    )
    text = re.sub(
        r"- Current save-context (skill|rule) -> `[^`]+`",
        f"- Current {save_context_name} -> `{save_context}`",
        text,
    )
    text = re.sub(
        r"- Emotion update policy reference -> `[^`]+/emotion/update-policy\.yaml`",
        f"- Emotion update policy reference -> `{update_policy}`",
        text,
    )
    if adapter == "codex":
        text = re.sub(
            r"- Codex sidecar skill -> not installed in this [^\n]+ target",
            "- Current Codex sidecar skill -> `.agents/skills/emotion-engine-codex/SKILL.md`",
            text,
        )
        text = re.sub(
            r"- Codex sidecar helper -> not installed in this [^\n]+ target",
            "- Current Codex sidecar helper -> `.agents/skills/emotion-engine-codex/scripts/emotion_engine_utils.py`",
            text,
        )
        text = re.sub(
            r"- Project-local Emotion Engine state snapshot -> `\.emotion-engine/codex-state\.json` "
            r"\(not active without an adapter sidecar\)",
            "- Project-local Emotion Engine runtime state -> `.emotion-engine/codex-state.json`",
            text,
        )
    else:
        text = re.sub(
            r"- Current Codex sidecar skill -> `\.agents/skills/emotion-engine-codex/SKILL\.md`",
            f"- Codex sidecar skill -> not installed in this {label} target",
            text,
        )
        text = re.sub(
            r"- Current Codex sidecar helper -> `\.agents/skills/emotion-engine-codex/scripts/emotion_engine_utils\.py`",
            f"- Codex sidecar helper -> not installed in this {label} target",
            text,
        )
        text = re.sub(
            r"- Project-local Emotion Engine runtime state -> `\.emotion-engine/codex-state\.json`",
            "- Project-local Emotion Engine state snapshot -> `.emotion-engine/codex-state.json` "
            "(not active without an adapter sidecar)",
            text,
        )
    return text


def _adapter_label(adapter):
    return {
        "codex": "Codex",
        "claude-code": "Claude Code",
        "cursor": "Cursor",
    }.get(adapter, adapter)
