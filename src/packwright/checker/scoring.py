import json

from packwright.core.adapter_layout import (
    adapter_entry,
    adapter_pack_kind,
    supported_adapters,
)
from packwright.core.emotion_engine_contract import (
    EMOTION_ENGINE_AVAILABLE_RUNTIME,
    EMOTION_ENGINE_CLAUDE_RUNTIME,
    EMOTION_ENGINE_MCP_WRAPPER_PATH,
    EMOTION_ENGINE_MODES,
    EMOTION_ENGINE_RUNTIME,
    EMOTION_ENGINE_RUNTIME_ROOT,
    EMOTION_ENGINE_STATE_PATH,
    EMOTION_ENGINE_WRAPPER_PATH,
    emotion_engine_artifacts,
    emotion_engine_expected,
    emotion_engine_manifest_diagnostics,
    emotion_engine_skill_path,
)
from packwright.core.errors import PackwrightValidationError
from packwright.core.mechanism_contract import normalize_mechanism
from packwright.core.locale import (
    identity_line,
    locale_feature,
    mechanism_locale,
    section_heading,
)
from packwright.core.skill_projection import (
    projected_skill_path,
    skill_projection_body,
    skill_projection_records,
)
from packwright.core.handoff import (
    DEFAULT_HANDOFF_DIR,
    DEFAULT_SESSION_BRIEF_DIR,
    HANDOFF_HELPER_PATH,
    HANDOFF_SCHEMA,
    HANDOFF_WRAPPER_PATH,
)
from packwright.core.knowledge_contract import (
    KNOWLEDGE_INDEX,
    KNOWLEDGE_MANIFEST,
    SOURCE_MANIFESTS,
    knowledge_artifacts,
)
from packwright.core.naming import (
    character_name,
    character_slug,
    durable_memory_source,
    reference_prefix,
    save_context_skill_path,
)
from packwright.core.readiness import score_readiness
from packwright.core.validation import file_exists, path_exists, validate_mechanism
from packwright.core.workspace_contract import (
    WORKSPACE_INDEX_OWNER,
    WORKSPACE_LAYOUT,
    WORKSPACE_ROOT,
    workspace_artifacts,
    workspace_readme_required_markers,
)


def score_mechanism(mechanism, adapter_pack, adapter="codex", threshold=None):
    """Score a resolved mechanism and adapter pack."""
    checks = []
    try:
        validate_mechanism(mechanism)
        mechanism = normalize_mechanism(mechanism)
        validate_mechanism(mechanism)
        _add(checks, "mechanism_valid", True, 15, "mechanism spec passes validation")
    except PackwrightValidationError as exc:
        _add(checks, "mechanism_valid", False, 15, "; ".join(exc.issues))
        return _result(checks, 85 if threshold is None else threshold)

    configured_threshold = mechanism.get("checker", {}).get("threshold", 85)
    threshold = configured_threshold if threshold is None else threshold
    adapter_pack = adapter_pack or {}
    adapter = _adapter_from_manifest(adapter_pack, adapter)
    entry_path = _entry_path(mechanism, adapter)
    skill_path = save_context_skill_path(mechanism, adapter)
    save_context_source_path = next(
        item["path"] for item in mechanism["skills"] if item.get("id") == "save-context"
    )
    entry = adapter_pack.get(entry_path, "")
    skill = adapter_pack.get(skill_path, "")
    settings = adapter_pack.get(".claude/settings.json", "")
    automation_runner = adapter_pack.get(".claude/hooks/packwright_automation.py", "")
    manifest = _parse_json(adapter_pack.get("manifest.json", "{}"))
    locale = mechanism_locale(mechanism)
    save_context_neutrality_violation = _save_context_skill_projection_neutrality_violation(
        skill
    )

    implemented_by = mechanism["coverage"]["implemented_by"]
    identity = mechanism["identity"]
    name = character_name(mechanism)

    _add(
        checks,
        "source_files_exist",
        _source_files_exist(mechanism),
        10,
        "all referenced identity, operating, mechanism, emotion, memory, and skill source files exist",
    )
    _add(
        checks,
        "coverage_paths",
        all(path_exists(mechanism, path) for paths in implemented_by.values() for path in paths),
        10,
        "mechanism coverage paths all resolve",
    )
    _add(
        checks,
        "adapter_pack_manifest",
        _manifest_matches_pack(manifest, adapter_pack, adapter),
        10,
        "adapter pack manifest describes emitted artifacts",
    )
    _add(
        checks,
        "locale_projection_contract",
        manifest.get("features", {}).get("locale") == locale_feature(mechanism, adapter),
        10,
        "adapter manifest records the resolved compiler locale and semantic entry sections",
    )
    _add(
        checks,
        "projection_contracts_present",
        _projection_contracts_present(mechanism, adapter_pack, adapter),
        10,
        "adapter pack includes platform capabilities and ownership contract",
    )
    _add(
        checks,
        "ownership_contract_valid",
        _ownership_contract_valid(mechanism, manifest, adapter),
        10,
        "adapter manifest declares runtime ownership without taking durable memory ownership",
    )
    _add(
        checks,
        "entry_has_identity",
        identity["name"] in entry and identity["role"] in entry and identity_line(locale, name) in entry,
        10,
        "entry file keeps character person-like stable identity hot",
    )
    _add(
        checks,
        "entry_has_voice",
        _entry_has_voice(entry, locale),
        10,
        "entry file carries stable voice guidance",
    )
    _add(
        checks,
        "entry_excludes_implementation_scope",
        _entry_excludes_implementation_scope(mechanism, entry),
        10,
        "entry file does not embed Packwright implementation-scope details or run state",
    )
    _add(
        checks,
        "entry_points_to_save_context_skill",
        skill_path in entry,
        10,
        "entry file points to the character save-context skill without turning foundation mechanisms into skills",
    )
    _add(
        checks,
        "entry_uses_runtime_appropriate_links",
        _entry_uses_runtime_appropriate_links(entry, adapter, skill_path, locale),
        10,
        "entry file uses Codex/Pi plain paths or Claude Code @path syntax as appropriate",
    )
    _add(
        checks,
        "on_demand_references_have_purpose",
        _on_demand_references_have_purpose(entry, adapter, locale),
        10,
        "on-demand entry references describe when or why to read each file",
    )
    _add(
        checks,
        "foundation_mechanisms_not_projected_as_skills",
        _foundation_mechanisms_not_projected_as_skills(adapter_pack),
        10,
        "recent activity and fact check remain foundation mechanisms, not projected skills",
    )
    _add(
        checks,
        "semantic_skills_projected",
        _semantic_skills_projected(mechanism, adapter_pack, manifest, entry, adapter),
        10,
        "every supported semantic skill has one native projection and unsupported capabilities are explicit",
    )
    _add(
        checks,
        "semantic_skill_projection_neutral",
        _semantic_skill_projection_neutral(mechanism, adapter_pack, adapter),
        10,
        "semantic skill bodies do not acquire runtime-specific meaning",
    )
    _add(
        checks,
        "save_context_skill_valid",
        section_heading(locale, "procedure") in skill
        and "memory/session-index.md" in skill
        and ("canonical owner file" in skill if locale == "en" else "规范文件" in skill),
        10,
        "save-context skill carries the heavy memory handoff procedure",
    )
    _add(
        checks,
        "save_context_skill_projection_neutral",
        save_context_neutrality_violation is None,
        10,
        (
            "save-context skill avoids runtime-specific projection wording"
            if save_context_neutrality_violation is None
            else f"{save_context_source_path} contains runtime-specific token "
            f"{save_context_neutrality_violation!r}; keep the canonical source body "
            "runtime-neutral and let adapters own runtime names, paths, and front matter"
        ),
    )
    if adapter == "claude-code":
        _add(
            checks,
            "hook_injects_facts_only",
            _hook_injects_facts_only(settings, automation_runner),
            10,
            "managed local hooks inject bounded canonical facts rather than long instructions",
        )
    else:
        _add(
            checks,
            "no_fake_claude_hook",
            not any(path.startswith(".claude/") for path in adapter_pack) and "SessionStart" not in entry,
            10,
            "non-Claude Code projection does not fake Claude Code SessionStart hook semantics",
        )
    _add(
        checks,
        "memory_skeleton_present",
        all(item["path"] in adapter_pack for item in mechanism["memory"]["local_files"]),
        10,
        "adapter pack includes local memory skeleton files",
    )
    _add(
        checks,
        "memory_capacity_policy_present",
        _memory_capacity_policy_present(mechanism, adapter_pack),
        10,
        "memory skeleton carries owner-based routing, profile, workstream router, project, and compatibility limits",
    )
    _add(
        checks,
        "workspace_structure_present",
        _workspace_structure_present(mechanism, adapter_pack),
        10,
        "adapter pack includes workspace directories and keeps output indexing in source-map",
    )
    _add(
        checks,
        "knowledge_skeleton_present",
        _knowledge_skeleton_present(adapter_pack, manifest, entry, adapter),
        10,
        "adapter pack includes a reviewed-knowledge scaffold, source manifests, and explicit loading guidance",
    )
    if adapter == "cursor":
        _add(
            checks,
            "cursor_handoff_tool_present",
            _cursor_handoff_tool_present(adapter_pack, manifest, entry),
            10,
            "Cursor pack includes target-local handoff export helper and handoff/session-brief path guidance",
        )
    _add(
        checks,
        "empty_memory_skeleton_is_user_ready",
        _empty_memory_skeleton_is_user_ready(adapter_pack),
        10,
        "empty memory skeleton files avoid template placeholders and read as usable empty state",
    )
    if adapter == "codex":
        _add(
            checks,
            "reserved_emotion_not_in_daily_codex_entry",
            "live Emotion Engine state" not in entry,
            10,
            "Codex daily entry keeps live Emotion Engine state out of normal operating prompts",
        )
    if adapter == "pi":
        _add(
            checks,
            "pi_project_trust_declared",
            _pi_project_trust_declared(manifest),
            10,
            "Pi pack declares project trust as an explicit runtime activation step",
        )
        _add(
            checks,
            "reserved_emotion_not_in_daily_pi_entry",
            "live Emotion Engine state" not in entry,
            10,
            "Pi daily entry keeps unavailable Emotion Engine runtime state out of normal operating prompts",
        )
    _add(
        checks,
        "emotion_specs_present",
        _emotion_specs_present(mechanism, adapter_pack, adapter),
        10,
        "adapter pack includes structured Emotion Engine spec references",
    )
    _add(
        checks,
        "emotion_engine_default_light",
        _emotion_engine_default_light(mechanism, manifest, adapter),
        10,
        "Emotion Engine defaults to light mode with user-visible token overhead estimates",
    )
    _add(
        checks,
        "emotion_reserved_not_runtime",
        _emotion_reserved_not_runtime(mechanism, manifest),
        10,
        "Emotion Engine is placed as structured reserved state modulation, not runtime execution",
    )
    _add(
        checks,
        "reserved_runtimes_not_implemented",
        _reserved_runtimes_not_implemented(mechanism, manifest),
        10,
        "reserved runtimes and specs remain explicitly non-implemented",
    )
    if _emotion_engine_enabled(adapter_pack, entry, manifest):
        _add(
            checks,
            "emotion_engine_skill_present",
            emotion_engine_skill_path(adapter) in adapter_pack,
            10,
            "adapter-native Emotion Engine guidance is installed when enabled",
        )
        _add(
            checks,
            "emotion_engine_state_present",
            _emotion_engine_state_valid(adapter_pack.get(EMOTION_ENGINE_STATE_PATH, "")),
            10,
            "Emotion Engine state exists at the adapter-neutral project path when enabled",
        )
        _add(
            checks,
            "emotion_engine_settle_trust_present",
            _emotion_engine_settle_trust_present(adapter_pack, entry, adapter),
            10,
            "Emotion Engine supports conservative trust settlement",
        )
        _add(
            checks,
            "emotion_engine_record_policy_present",
            _emotion_engine_record_policy_present(adapter_pack, entry, adapter),
            10,
            "Emotion Engine supports deterministic light/always record policy",
        )
        _add(
            checks,
            "emotion_engine_mcp_present",
            _emotion_engine_mcp_present(adapter_pack, manifest),
            10,
            "Emotion Engine exposes MCP state tools without owning Packwright repair",
        )
        _add(
            checks,
            "emotion_engine_project_wrappers_present",
            _emotion_engine_project_wrappers_present(adapter_pack, manifest),
            10,
            "project-root shell and MCP wrappers forward to the shared runtime",
        )
        _add(
            checks,
            "emotion_engine_entry_internal",
            _emotion_engine_entry_internal(adapter_pack, entry, adapter),
            10,
            "adapter guidance keeps Emotion Engine internals hidden from normal replies",
        )
        _add(
            checks,
            "relationship_state_not_runtime_state",
            _relationship_state_not_runtime_state(
                adapter_pack.get("memory/relationship-state.md", "")
                + "\n"
                + adapter_pack.get("memory/collaboration.md", "")
            ),
            10,
            "collaboration memory stays human-readable and does not store PAD/trust runtime JSON",
        )
        manifest_diagnostics = emotion_engine_manifest_diagnostics(manifest)
        _add(
            checks,
            "emotion_engine_manifest_consistent",
            not manifest_diagnostics,
            10,
            _emotion_engine_diagnostic_message(
                manifest_diagnostics,
                "installed Emotion Engine runtime is reflected in manifest features and sidecars",
            ),
        )

    return _result(checks, threshold)
def _source_files_exist(mechanism):
    refs = [
        mechanism["identity"]["persona_path"],
        mechanism["identity"]["voice_path"],
        mechanism["identity"]["relationship_path"],
        mechanism["operating"]["principles_path"],
        mechanism["operating"]["boundaries_path"],
        mechanism["mechanism"]["context_loading_path"],
        mechanism["mechanism"]["session_guards_path"],
        mechanism["mechanism"]["memory_policy_path"],
        mechanism["emotion"]["model_path"],
        mechanism["emotion"]["state_schema_path"],
        mechanism["emotion"]["update_policy_path"],
        mechanism["emotion"]["voice_modulation_path"],
        mechanism["emotion"]["memory_events_path"],
    ]
    refs.extend(item["path"] for item in mechanism["memory"]["local_files"])
    refs.extend(skill["path"] for skill in mechanism["skills"])
    return _source_files_exist_for_refs(mechanism, refs)


def _source_files_exist_for_refs(mechanism, refs):
    return all(file_exists(mechanism, ref) for ref in refs)


def _adapter_from_manifest(adapter_pack, fallback):
    manifest = _parse_json(adapter_pack.get("manifest.json", "{}"))
    adapter = manifest.get("adapter")
    return adapter if adapter in supported_adapters() else fallback


def _entry_path(mechanism, adapter):
    return adapter_entry(adapter, character_slug(mechanism))


def _manifest_matches_pack(manifest, adapter_pack, adapter):
    if not isinstance(manifest, dict):
        return False
    all_paths = set(manifest.get("artifacts", [])) | set(adapter_pack.keys())
    external = _manifest_external_artifacts(all_paths)
    artifacts = set(manifest.get("artifacts", [])) - external
    emitted = set(adapter_pack.keys()) - external
    expected_kind = adapter_pack_kind(adapter)
    return manifest.get("kind") == expected_kind and manifest.get("adapter") == adapter and artifacts == emitted


def _manifest_external_artifacts(paths):
    allowed = set()
    for adapter in supported_adapters():
        allowed.update(emotion_engine_artifacts(adapter))
    return set(paths).intersection(allowed)


def _projection_contracts_present(mechanism, adapter_pack, adapter):
    prefix = reference_prefix(mechanism, adapter)
    expected = [
        f"{prefix}/projection/platform-capabilities.yaml",
        f"{prefix}/projection/ownership-contract.yaml",
    ]
    return all(path in adapter_pack for path in expected)


def _ownership_contract_valid(mechanism, manifest, adapter):
    ownership = manifest.get("ownership", {}) if isinstance(manifest, dict) else {}
    return (
        ownership.get("model_loop") == adapter
        and ownership.get("thread_state") == adapter
        and ownership.get("tools") == adapter
        and ownership.get("durable_memory_source_of_truth") == durable_memory_source(mechanism)
    )


def _entry_has_voice(entry, locale):
    if locale == "zh-CN":
        markers = (
            section_heading(locale, "voice"),
            "先说最重要的事。",
            "不确定时，明确指出不确定之处并核对来源。",
            "被纠正时，重述修正后的理解并直接调整",
        )
    else:
        markers = (
            section_heading(locale, "voice"),
            "Say what matters first.",
            "When uncertain, name the uncertainty",
            "When corrected, restate the corrected model",
        )
    return all(marker in entry for marker in markers)


def _entry_excludes_implementation_scope(mechanism, entry):
    forbidden = ["Packwright", "MVP", "adapter pack", "cloud service", "Do not build UI"]
    run = mechanism.get("run", {})
    run_values = [run.get("objective"), run.get("scope")]
    return not any(item and item in entry for item in forbidden + run_values)


def _hook_injects_facts_only(settings_text, runner_text):
    settings = _parse_json(settings_text)
    if not isinstance(settings, dict):
        return False
    hooks = settings.get("hooks", {}).get("SessionStart", [])
    command = json.dumps(hooks) + runner_text
    required = (
        "system_datetime",
        "memory/index.md",
        "memory/profile.md",
        "memory/workstreams.md",
        "memory/session-index.md",
        "memory/source-map.md",
        "memory/todos.md",
        "memory/collaboration.md",
    )
    forbidden = ("You are", "Always", "Never", "Workflow", "implement")
    return all(item in command for item in required) and not any(item in command for item in forbidden)


def _emotion_specs_present(mechanism, adapter_pack, adapter):
    prefix = reference_prefix(mechanism, adapter)
    expected = [
        f"{prefix}/emotion/model.yaml",
        f"{prefix}/emotion/state-schema.yaml",
        f"{prefix}/emotion/update-policy.yaml",
        f"{prefix}/emotion/voice-modulation.yaml",
        f"{prefix}/emotion/memory-events.yaml",
        "memory/collaboration.md",
    ]
    return all(path in adapter_pack for path in expected) and mechanism["emotion"]["status"] == "structured_reserved"


def _foundation_mechanisms_not_projected_as_skills(adapter_pack):
    if any("/source-skills/" in path for path in adapter_pack):
        return False
    projected_foundation_suffixes = (
        "recent-activity/SKILL.md",
        "fact-check/SKILL.md",
        "-recent-activity.mdc",
        "-fact-check.mdc",
    )
    return not any(path.endswith(projected_foundation_suffixes) for path in adapter_pack)


def _semantic_skills_projected(mechanism, adapter_pack, manifest, entry, adapter):
    records = skill_projection_records(mechanism, adapter)
    feature = manifest.get("features", {}).get("skills", {}) if isinstance(manifest, dict) else {}
    feature_items = feature.get("items", []) if isinstance(feature, dict) else []
    if feature_items != records or feature.get("count") != len(records):
        return False
    for record in records:
        present = record["path"] in adapter_pack
        if record["status"] == "projected":
            if not present or record["path"] not in entry:
                return False
        elif present:
            return False
    return True


def _semantic_skill_projection_neutral(mechanism, adapter_pack, adapter):
    forbidden = (
        "Codex",
        "Claude Code",
        "Cursor",
        "Pi",
        ".codex/",
        ".claude/",
        ".cursor/",
        ".pi/",
    )
    for skill in mechanism.get("skills", []):
        if skill.get("id") == "save-context":
            continue
        path = projected_skill_path(mechanism, adapter, skill)
        text = adapter_pack.get(path)
        if text is not None and any(
            item in skill_projection_body(text) for item in forbidden
        ):
            return False
    return True


def _entry_uses_runtime_appropriate_links(entry, adapter, skill_path, locale):
    daily_memory_paths = (
        "memory/index.md",
        "memory/profile.md",
        "memory/workstreams.md",
        "memory/session-index.md",
        "memory/source-map.md",
        "memory/todos.md",
        "memory/collaboration.md",
    )
    if adapter in {"codex", "pi"}:
        return (
            section_heading(locale, "use_when_needed") in entry
            and f"`{skill_path}`" in entry
            and "@" not in entry
            and all(f"`{path}`" in entry for path in daily_memory_paths)
        )
    if adapter == "cursor":
        return (
            section_heading(locale, "use_when_needed") in entry
            and f"`{skill_path}`" in entry
            and all(f"`{path}`" in entry for path in daily_memory_paths)
        )
    return (
        section_heading(locale, "load_when_needed") in entry
        and f"@{skill_path}" in entry
        and all(f"@{path}" in entry for path in daily_memory_paths)
    )


def _on_demand_references_have_purpose(entry, adapter, locale):
    section_id = "load_when_needed" if adapter == "claude-code" else "use_when_needed"
    heading = section_heading(locale, section_id)
    lines = _section_bullets(entry, heading)
    minimum = 11 if adapter == "claude-code" else 10
    if len(lines) < minimum:
        return False
    return all(_reference_bullet_has_purpose(line) for line in lines)


def _reference_bullet_has_purpose(line):
    text = line[2:].strip() if line.startswith("- ") else line.strip()
    if text.startswith("@"):
        for separator in (": ", "："):
            if separator in text:
                return bool(text.split(separator, 1)[1].strip())
        return False
    if "`" not in text:
        return False
    parts = text.split("`")
    if len(parts) < 3:
        return False
    purpose = " ".join(parts[::2]).strip(" ，。,:;")
    return len(purpose) >= 3


def _section_bullets(text, heading):
    in_section = False
    bullets = []
    for line in text.splitlines():
        if line.strip() == heading:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.startswith("- "):
            bullets.append(line)
    return bullets


def _save_context_skill_projection_neutrality_violation(skill):
    forbidden = (
        "Codex",
        "Claude",
        "Cursor",
        "Pi",
        "Projection Notes",
        "adapter pack",
        ".codex",
        ".claude",
        ".cursor",
        ".pi",
    )
    body = skill_projection_body(skill)
    return next((item for item in forbidden if item in body), None)


def _empty_memory_skeleton_is_user_ready(adapter_pack):
    index = adapter_pack.get("memory/index.md", "")
    profile = adapter_pack.get("memory/profile.md", "")
    session_index = adapter_pack.get("memory/session-index.md", "")
    source_map = adapter_pack.get("memory/source-map.md", "")
    collaboration = adapter_pack.get("memory/collaboration.md", "")
    pinned = adapter_pack.get("memory/pinned.md", "")
    workstreams = adapter_pack.get("memory/workstreams.md", "")
    workstream_template = adapter_pack.get("memory/workstreams/_template.md", "")
    recent = adapter_pack.get("memory/recent-activity.md", "")
    todos = adapter_pack.get("memory/todos.md", "")
    knowledge_map = adapter_pack.get("memory/knowledge_map.md", "")
    project_template = adapter_pack.get("memory/projects/_template.md", "")
    relationship_state = adapter_pack.get("memory/relationship-state.md", "")
    workspace_readme = adapter_pack.get("workspace/README.md", "")
    memory_text = "\n".join(
        (
            index,
            profile,
            session_index,
            source_map,
            collaboration,
            pinned,
            workstreams,
            workstream_template,
            recent,
            todos,
            knowledge_map,
            project_template,
            relationship_state,
            workspace_readme,
        )
    )
    forbidden = ("template skeleton", "Add newest pickup entries below this line")
    required = (
        "This is the default memory router.",
        "This file stores stable profile facts",
        "No pinned memory has been recorded yet.",
        "domain router",
        "Agent Promotion",
        "No pickup entries have been recorded yet.",
        "newest 20",
        "No current todos have been recorded yet.",
        "not a knowledge base by itself",
        "No project state has been recorded yet.",
        "No relationship continuity notes have been recorded yet.",
        "Use this directory for generated work products",
    )
    usable_state = (
        ("No active projects have been recorded yet." in index or "## Active Projects" in index)
        and ("No session index entries have been recorded yet." in session_index or "<!-- entries -->" in session_index)
        and (
            "No source mappings have been recorded yet." in source_map
            or "## Sources" in source_map
            or "## Packwright Sources" in source_map
            or "## Project Memory" in source_map
        )
        and ("No collaboration calibrations have been recorded yet." in collaboration or "## Current Calibrations" in collaboration)
    )
    return (
        all(item in memory_text for item in required)
        and usable_state
        and not any(item in memory_text for item in forbidden)
    )


def _memory_capacity_policy_present(mechanism, adapter_pack):
    limits = mechanism.get("memory", {}).get("limits", {})
    expected = {
        "pinned_items": 20,
        "recent_activity_hot_entries": 20,
        "session_index_entries": 20,
        "workstream_summary_bullets": 7,
        "project_summary_lines": 12,
        "workspace_artifact_index_entries": 50,
    }
    if any(limits.get(key) != value for key, value in expected.items()):
        return False
    combined = "\n".join(
        adapter_pack.get(path, "")
        for path in (
            "memory/index.md",
            "memory/profile.md",
            "memory/session-index.md",
            "memory/source-map.md",
            "memory/collaboration.md",
            "memory/pinned.md",
            "memory/workstreams.md",
            "memory/workstreams/_template.md",
            "memory/recent-activity.md",
            "memory/projects/_template.md",
            "workspace/README.md",
        )
    )
    required = (
        "default memory router",
        "stable profile facts",
        "domain router",
        "newest 20",
        "source registry",
        "stable collaboration calibrations",
        "compatibility",
        "12 lines or fewer",
        "generated work products",
    )
    return all(item in combined for item in required)


def _workspace_structure_present(mechanism, adapter_pack):
    workspace = mechanism.get("workspace", {})
    required = set(workspace_artifacts())
    readme = adapter_pack.get("workspace/README.md", "")
    return (
        workspace.get("root") == WORKSPACE_ROOT
        and workspace.get("layout") == WORKSPACE_LAYOUT
        and workspace.get("index_owner") == WORKSPACE_INDEX_OWNER
        and required.issubset(adapter_pack.keys())
        and all(marker in readme for marker in workspace_readme_required_markers())
    )


def _knowledge_skeleton_present(adapter_pack, manifest, entry, adapter):
    artifacts = set(manifest.get("artifacts", [])) if isinstance(manifest, dict) else set()
    feature = manifest.get("features", {}).get("knowledge", {}) if isinstance(manifest, dict) else {}
    required = set(knowledge_artifacts())
    source_json_ok = all(isinstance(_parse_json(adapter_pack.get(path, "")), dict) for path in SOURCE_MANIFESTS)
    manifest_json = _parse_json(adapter_pack.get(KNOWLEDGE_MANIFEST, ""))
    if adapter == "claude-code":
        entry_mentions = f"@{KNOWLEDGE_INDEX}" in entry and "@sources/local/manifest.json" in entry
    else:
        entry_mentions = f"`{KNOWLEDGE_INDEX}`" in entry and "`sources/*/manifest.json`" in entry
    return (
        required.issubset(adapter_pack.keys())
        and required.issubset(artifacts)
        and feature.get("root") == "knowledge"
        and feature.get("recall_index") == KNOWLEDGE_INDEX
        and feature.get("manifest") == KNOWLEDGE_MANIFEST
        and feature.get("sources_root") == "sources"
        and adapter_pack.get(KNOWLEDGE_INDEX, "").startswith("# Knowledge Recall Index")
        and isinstance(manifest_json, dict)
        and manifest_json.get("schema") == "packwright-knowledge-manifest/v1"
        and source_json_ok
        and entry_mentions
    )


def _cursor_handoff_tool_present(adapter_pack, manifest, entry):
    helper = adapter_pack.get(HANDOFF_HELPER_PATH, "")
    wrapper = adapter_pack.get(HANDOFF_WRAPPER_PATH, "")
    artifacts = set(manifest.get("artifacts", [])) if isinstance(manifest, dict) else set()
    feature = manifest.get("features", {}).get("handoff", {}) if isinstance(manifest, dict) else {}
    local_tool = manifest.get("local_tools", {}).get("handoff_export", {}) if isinstance(manifest, dict) else {}
    return (
        HANDOFF_HELPER_PATH in adapter_pack
        and HANDOFF_WRAPPER_PATH in adapter_pack
        and HANDOFF_HELPER_PATH in artifacts
        and HANDOFF_WRAPPER_PATH in artifacts
        and HANDOFF_SCHEMA in helper
        and DEFAULT_HANDOFF_DIR in helper
        and DEFAULT_SESSION_BRIEF_DIR in helper
        and HANDOFF_HELPER_PATH.rsplit("/", 1)[-1] in wrapper
        and feature.get("schema") == HANDOFF_SCHEMA
        and feature.get("command") == HANDOFF_WRAPPER_PATH
        and feature.get("default_handoff_dir") == DEFAULT_HANDOFF_DIR
        and feature.get("session_brief_dir") == DEFAULT_SESSION_BRIEF_DIR
        and local_tool.get("schema") == HANDOFF_SCHEMA
        and local_tool.get("command") == HANDOFF_WRAPPER_PATH
        and DEFAULT_HANDOFF_DIR in entry
        and DEFAULT_SESSION_BRIEF_DIR in entry
    )


def _emotion_reserved_not_runtime(mechanism, manifest):
    boundaries = manifest.get("boundaries", {}) if isinstance(manifest, dict) else {}
    runtime = boundaries.get("emotion_engine_runtime")
    return (
        mechanism["emotion"].get("status") == "structured_reserved"
        and mechanism["emotion"].get("runtime") == "not_implemented"
        and runtime in {
            False,
            "optional_project_mcp_sidecar",
            "spec_guided_behavior_only",
            "unavailable_no_builtin_mcp",
            EMOTION_ENGINE_AVAILABLE_RUNTIME,
            EMOTION_ENGINE_RUNTIME,
            EMOTION_ENGINE_CLAUDE_RUNTIME,
        }
    )


def _pi_project_trust_declared(manifest):
    feature = (
        manifest.get("features", {}).get("project_trust", {})
        if isinstance(manifest, dict)
        else {}
    )
    boundaries = manifest.get("boundaries", {}) if isinstance(manifest, dict) else {}
    return (
        feature.get("required_for_project_resources") is True
        and feature.get("status") == "requires_runtime_confirmation"
        and feature.get("interactive_activation") == "/trust"
        and feature.get("non_interactive_activation") == "pi --approve"
        and boundaries.get("pi_extensions") == "not_projected"
        and boundaries.get("mcp") == "unavailable_no_builtin_mcp"
    )


def _emotion_engine_default_light(mechanism, manifest, adapter):
    emotion = mechanism.get("emotion", {})
    feature = manifest.get("features", {}).get("emotion_engine", {}) if isinstance(manifest, dict) else {}
    overhead = feature.get("estimated_overhead", {})
    return (
        emotion.get("default_mode") == "light"
        and feature.get("default_mode") == "light"
        and feature.get("mode") in EMOTION_ENGINE_MODES
        and feature.get("adapter") == adapter
        and "light" in overhead
        and "always" in overhead
        and "<1%" in overhead.get("light", "")
        and "<=5%" in overhead.get("always", "")
    )


def _reserved_runtimes_not_implemented(mechanism, manifest):
    reserved_targets = mechanism.get("targets", {}).get("reserved", {})
    reserved_specs = mechanism.get("reserved_specs", {})
    manifest_boundaries = manifest.get("boundaries", {}) if isinstance(manifest, dict) else {}
    specs_ok = all(
        spec.get("status") in {"reserved", "structured_reserved"} and spec.get("runtime") == "not_implemented"
        for spec in reserved_specs.values()
    )
    targets_ok = all(spec.get("status") == "reserved" for spec in reserved_targets.values())
    manifest_ok = manifest_boundaries.get("is_runtime_executor") is False and manifest_boundaries.get("implements_cloud") is False
    return specs_ok and targets_ok and manifest_ok


def _emotion_engine_enabled(adapter_pack, entry, manifest):
    return (
        emotion_engine_expected(manifest, adapter_pack)
        or "## Emotion Engine" in entry
        or "## Optional Emotion Engine" in entry
    )


def _emotion_engine_state_valid(text):
    state = _parse_json(text)
    return isinstance(state, dict) and state.get("_schema") == "emotion-engine-state/v2"


def _emotion_engine_entry_internal(adapter_pack, entry, adapter):
    guidance = adapter_pack.get(emotion_engine_skill_path(adapter), "")
    forbidden = (
        '"pleasure"',
        '"arousal"',
        '"dominance"',
        '"trust"',
        "pleasure:",
        "arousal:",
        "dominance:",
        "trust_history",
        "emotion_trajectory",
    )
    routing_ok = (
        EMOTION_ENGINE_STATE_PATH in guidance
        and "settle_trust" in guidance
        and "record_policy" in guidance
    )
    if adapter != "cursor":
        routing_ok = routing_ok and emotion_engine_skill_path(adapter) in entry
    return routing_ok and not any(item in entry for item in forbidden)


def _emotion_engine_settle_trust_present(adapter_pack, entry, adapter):
    skill = adapter_pack.get(emotion_engine_skill_path(adapter), "")
    helper = adapter_pack.get(f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_utils.py", "")
    wrapper = adapter_pack.get(EMOTION_ENGINE_WRAPPER_PATH, "")
    return (
        "settle_trust" in skill
        and "settle_trust" in helper
        and "emotion_engine_utils.py" in wrapper
        and EMOTION_ENGINE_STATE_PATH in wrapper
    )


def _emotion_engine_record_policy_present(adapter_pack, entry, adapter):
    skill = adapter_pack.get(emotion_engine_skill_path(adapter), "")
    helper = adapter_pack.get(f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_utils.py", "")
    return (
        "record_policy" in skill
        and "record_policy" in helper
        and "parse_record_policy_args" in helper
        and "reply_bias" in helper
        and '"decision"' in helper
        and "generic_praise_habituated" in helper
    )


def _emotion_engine_mcp_present(adapter_pack, manifest):
    mcp_path = f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_mcp.py"
    registration_path = f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/register_mcp_client.py"
    mcp = adapter_pack.get(mcp_path, "")
    registration = adapter_pack.get(registration_path, "")
    artifacts = set(manifest.get("artifacts", [])) if isinstance(manifest, dict) else set()
    return (
        mcp_path in adapter_pack
        and registration_path in adapter_pack
        and mcp_path in artifacts
        and registration_path in artifacts
        and "tools/list" in mcp
        and "emotion_engine_record_policy" in mcp
        and "codex" in registration
        and "state" in registration
        and "emotion_engine_repair" not in mcp
        and "doctor_target" not in mcp
    )


def _emotion_engine_project_wrappers_present(adapter_pack, manifest):
    wrapper = adapter_pack.get(EMOTION_ENGINE_WRAPPER_PATH, "")
    mcp_wrapper = adapter_pack.get(EMOTION_ENGINE_MCP_WRAPPER_PATH, "")
    artifacts = set(manifest.get("artifacts", [])) if isinstance(manifest, dict) else set()
    return (
        EMOTION_ENGINE_WRAPPER_PATH in adapter_pack
        and EMOTION_ENGINE_MCP_WRAPPER_PATH in adapter_pack
        and EMOTION_ENGINE_WRAPPER_PATH in artifacts
        and EMOTION_ENGINE_MCP_WRAPPER_PATH in artifacts
        and "emotion_engine_utils.py" in wrapper
        and "emotion_engine_mcp.py" in mcp_wrapper
    )


def _relationship_state_not_runtime_state(text):
    forbidden = (
        '"pleasure"',
        '"arousal"',
        '"dominance"',
        '"trust"',
        "trust_history",
        "emotion_trajectory",
        "emotion-engine-state/v2",
    )
    return not any(item in text for item in forbidden)


def _emotion_engine_diagnostic_message(diagnostics, fallback):
    if not diagnostics:
        return fallback
    return "; ".join(issue["message"] for issue in diagnostics)


def _parse_json(text):
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}


def _add(checks, check_id, passed, weight, message):
    checks.append(
        {
            "id": check_id,
            "passed": bool(passed),
            "weight": weight,
            "message": message,
        }
    )


def _result(checks, threshold):
    total = sum(check["weight"] for check in checks)
    earned = sum(check["weight"] for check in checks if check["passed"])
    score = round((earned / total) * 100, 2) if total else 0.0
    passed = score >= threshold and all(check["passed"] for check in checks)
    return {
        "score": score,
        "threshold": threshold,
        "passed": passed,
        "scope": "managed_structure",
        "readiness": score_readiness(passed),
        "checks": checks,
    }
