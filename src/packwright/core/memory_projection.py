import re

from .adapter_layout import adapter_display_name, adapter_entry, adapter_guidance_kind
from .emotion_engine_contract import (
    EMOTION_ENGINE_RUNTIME_ROOT,
    EMOTION_ENGINE_STATE_PATH,
    emotion_engine_skill_path,
)
from .naming import character_slug, reference_prefix, save_context_skill_path


def project_memory_file(mechanism, adapter, rel_path, text, emotion_engine_active=False):
    """Project portable memory text into adapter-specific runtime wording."""
    if rel_path == "memory/index.md":
        return _project_memory_index(mechanism, adapter, text)
    if rel_path == "memory/pinned.md":
        return _project_pinned_memory(mechanism, adapter, text)
    if rel_path == "memory/source-map.md":
        return _project_source_map(
            mechanism,
            adapter,
            text,
            emotion_engine_active=emotion_engine_active,
        )
    return text


def adapter_entry_path(mechanism, adapter):
    return adapter_entry(adapter, character_slug(mechanism))


def _project_memory_index(mechanism, adapter, text):
    entry = adapter_entry_path(mechanism, adapter)
    text = re.sub(
        r"- Stable identity, voice, and default work rules -> `[^`]+`(?: or equivalent platform entry file)?",
        f"- Stable identity, voice, and default work rules -> `{entry}`",
        text,
    )
    return re.sub(
        r"- Dynamic emotion state and compact emotion history -> .+",
        f"- Dynamic emotion state and compact emotion history -> `{EMOTION_ENGINE_STATE_PATH}` when enabled",
        text,
    )


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


def _project_source_map(mechanism, adapter, text, emotion_engine_active=False):
    label = adapter_display_name(adapter)
    entry = adapter_entry_path(mechanism, adapter)
    save_context = save_context_skill_path(mechanism, adapter)
    save_context_name = f"save-context {adapter_guidance_kind(adapter)}"
    update_policy = f"{reference_prefix(mechanism, adapter)}/emotion/update-policy.yaml"

    text = re.sub(
        r"- Current (Codex|Claude Code|Cursor|Pi) entry -> `[^`]+`",
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

    guidance = (
        f"- Current Emotion Engine guidance -> `{emotion_engine_skill_path(adapter)}`"
        if emotion_engine_active
        else f"- Emotion Engine guidance -> not installed in this {label} target"
    )
    helper = (
        f"- Current Emotion Engine helper -> `{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_utils.py`"
        if emotion_engine_active
        else f"- Emotion Engine helper -> not installed in this {label} target"
    )
    state = (
        f"- Project-local Emotion Engine runtime state -> `{EMOTION_ENGINE_STATE_PATH}`"
        if emotion_engine_active
        else f"- Project-local Emotion Engine state snapshot -> `{EMOTION_ENGINE_STATE_PATH}` (not active without the runtime)"
    )
    text = re.sub(
        r"- (?:Current )?(?:Codex sidecar skill|Emotion Engine guidance) -> [^\n]+",
        guidance,
        text,
    )
    text = re.sub(
        r"- (?:Current )?(?:Codex sidecar helper|Emotion Engine helper) -> [^\n]+",
        helper,
        text,
    )
    return re.sub(
        r"- Project-local Emotion Engine (?:runtime state|state snapshot) -> [^\n]+",
        state,
        text,
    )
