import json

import yaml

from packwright.core.emotion_engine_contract import (
    EMOTION_ENGINE_AVAILABLE_RUNTIME,
    EMOTION_ENGINE_MODES,
    emotion_engine_feature,
)
from packwright.core.errors import PackwrightValidationError
from packwright.core.knowledge_contract import knowledge_feature, knowledge_files
from packwright.core.memory_projection import project_memory_file
from packwright.core.naming import (
    character_mission,
    character_name,
    character_slug,
    character_user_name,
    character_voice_summary,
    durable_memory_source,
    reference_prefix,
    save_context_skill_path,
)
from packwright.core.path_safety import resolve_mechanism_file
from packwright.core.validation import validate_mechanism
from packwright.core.workspace_contract import workspace_feature, workspace_files


ADAPTER_NAME = "codex"


def compile_to_codex_pack(mechanism, references=None):
    """Compile a resolved character mechanism into a Codex adapter pack."""
    validate_mechanism(mechanism)
    if ADAPTER_NAME not in mechanism["targets"].get("supported", []):
        raise PackwrightValidationError(["Codex adapter is not listed in targets.supported"])

    references = references or {}
    skill_path = save_context_skill_path(mechanism, ADAPTER_NAME)
    pack = {
        "AGENTS.md": _render_agents_md(mechanism),
        skill_path: _render_save_context_skill(mechanism, references),
    }
    pack.update(_reference_files(mechanism))
    pack.update(_memory_skeleton_files(mechanism))
    pack.update(_knowledge_files())
    pack.update(_workspace_files(mechanism))
    pack["manifest.json"] = _render_manifest(mechanism, references, sorted(pack.keys()) + ["manifest.json"])
    return pack


def _render_agents_md(mechanism):
    identity = mechanism["identity"]
    name = character_name(mechanism)
    user_name = character_user_name(mechanism)
    skill_path = save_context_skill_path(mechanism, ADAPTER_NAME)
    voice_summary = _sentence(character_voice_summary(mechanism))
    lines = [
        f"# {name}",
        "",
        f"You are {name}.",
        "",
        f"{name} is {identity['role']}",
        "",
        character_mission(mechanism),
        "",
        "## Work Focus",
    ]
    lines.extend(f"- {item}" for item in identity.get("work_focus", []))
    lines.extend(["", "## Personality"])
    lines.extend(f"- {trait}" for trait in identity.get("personality", []))
    lines.extend(
        [
            "",
            "## Voice",
            f"- {voice_summary}",
            "- Say what matters first.",
            "- Use warmth through attentiveness, not decoration.",
            "- Treat file reads as internal work unless the user asks for evidence; do not turn normal replies into audit logs.",
            "- When uncertain, name the uncertainty and check the source.",
            "- When corrected, restate the corrected model and adjust without defensiveness.",
            "",
            "## Working Rules",
            "- Preserve the user's stated intent and scope.",
            "- Read relevant files before making factual claims.",
            "- Keep durable memory in files, not in long prompt text.",
            "- Use session index notes to make prior work discoverable.",
            "- Use `workspace/<domain>/` for generated drafts, artifacts, and archives; keep memory files focused on state, decisions, and indexes.",
            "- Use `knowledge/` only for reviewed reusable models and patterns; keep current project state in `memory/`.",
            "- Ask before consequential changes.",
            "- Do not invent emotional or relationship state.",
            f"- When memory is empty, say there is no pickup yet and help {user_name} establish the first useful context; do not quote template placeholders.",
            "",
            "## Use When Needed",
            f"- Read `{skill_path}` for milestone handoff or explicit context-save requests.",
            "- Read `memory/index.md` first when prior context may matter; it is the memory router, not a project state source.",
            "- Read `memory/profile.md` when stable user, subject, learner, creator, or relationship facts could affect the task.",
            "- Read `memory/workstreams.md` when the request belongs to a long-running domain, needs domain routing, or may later be promoted to a separate agent.",
            "- Read `memory/projects/<slug>.md` when a specific project is named or clearly implied; project files are the source of project state and decisions.",
            "- Read `memory/session-index.md` when the user refers to earlier sessions, previous work, or an unnamed prior plan.",
            "- Read `memory/source-map.md` when facts need source lookup, verification paths, or source-of-truth files.",
            "- Read `knowledge/index.md` only when reusable domain knowledge may help; load the smallest useful note set.",
            "- Read `sources/*/manifest.json` only when provenance or original source lookup matters.",
            "- Read `memory/todos.md` for current action queues and commitments.",
            "- Read `memory/collaboration.md` when collaboration calibration, repair history, or user-specific working preferences affect the response.",
            "- Treat `memory/pinned.md`, `memory/recent-activity.md`, `memory/knowledge_map.md`, and `memory/relationship-state.md` only as compatibility files unless the memory index points to them.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_save_context_skill(mechanism, references):
    memory_policy = _load_yaml_ref(mechanism, mechanism["mechanism"]["memory_policy_path"])
    name = character_name(mechanism)
    user_name = character_user_name(mechanism)

    lines = [
        f"# {name} Save Context",
        "",
        f"Use this skill at milestone handoff, session close, or when {user_name} explicitly asks {name} to preserve context.",
        "",
        "## Procedure",
        "1. Identify the current objective, scope, decisions, changed files, verification, and open questions.",
        "2. Update the canonical owner file instead of copying the same fact across layers.",
        "3. Update `memory/profile.md` only for stable cross-workstream profile facts the user intentionally provides or confirms.",
        "4. Update `memory/workstreams.md` for long-running domain routing, and `memory/workstreams/<slug>.md` for dense domain state.",
        "5. Update `memory/projects/<slug>.md` for project state, decisions, open loops, and project-specific sources.",
        "6. Update `memory/session-index.md` for session/thread lookup entries, not project state summaries.",
        "7. Update `memory/source-map.md` for source-of-truth paths, verification routes, workspace artifacts, and lookup pointers.",
        "8. Update `memory/todos.md` for action queues and commitments.",
        "9. Update `memory/collaboration.md` only for stable collaboration calibrations; do not write ordinary praise, transient mood, or live Emotion Engine state.",
        "10. Put generated drafts, artifacts, and archives under `workspace/<domain>/`; do not copy full deliverables into memory files.",
        "11. Update `memory/index.md` only when active projects, memory owners, or routing rules change.",
        "12. Report what was saved, what remains unsaved, and where the next session should resume.",
        "",
        "## Memory Tracks",
    ]
    for track_name, track in memory_policy.get("tracks", {}).items():
        if track.get("id") == "emotion-state":
            continue
        lines.append(f"- {track_name}: {track.get('purpose', '')}")

    lines.extend(
        [
            "",
            "## Boundary Notes",
            f"- {name} local memory files remain the durable memory source of truth.",
            "- `memory/profile.md` stores explicit stable profile facts, not inferred mood or secrets.",
            "- `memory/workstreams.md` is a domain router for long-running areas; project files still own project-specific state.",
            "- `memory/session-index.md` is a lookup index, not a project state source.",
            "- `AGENTS.md` is stable identity/default behavior, not learned collaboration calibration.",
            "- `knowledge/index.md` is a recall router for reviewed reusable knowledge, not current project status.",
            "- `sources/*/manifest.json` stores provenance for knowledge notes and external sources; it is not the knowledge body.",
            "- `workspace/<domain>/` stores drafts, deliverables, and archives; important outputs should be indexed in `memory/source-map.md`.",
            "- `.emotion-engine/codex-state.json` stores dynamic emotion state; do not mirror it into memory files.",
            "- Fact assertion gates are session guards, not a skill.",
            "",
        ]
    )
    return "\n".join(lines)


def _reference_files(mechanism):
    prefix = reference_prefix(mechanism, ADAPTER_NAME)
    refs = {
        f"{prefix}/identity/persona.md": _read_text_ref(mechanism, mechanism["identity"]["persona_path"]),
        f"{prefix}/identity/voice.md": _read_text_ref(mechanism, mechanism["identity"]["voice_path"]),
        f"{prefix}/identity/relationship.md": _read_text_ref(mechanism, mechanism["identity"]["relationship_path"]),
        f"{prefix}/operating/principles.md": _read_text_ref(mechanism, mechanism["operating"]["principles_path"]),
        f"{prefix}/operating/boundaries.md": _read_text_ref(mechanism, mechanism["operating"]["boundaries_path"]),
        f"{prefix}/mechanism/context-loading.yaml": _read_text_ref(mechanism, mechanism["mechanism"]["context_loading_path"]),
        f"{prefix}/mechanism/session-guards.yaml": _read_text_ref(mechanism, mechanism["mechanism"]["session_guards_path"]),
        f"{prefix}/mechanism/memory-policy.yaml": _read_text_ref(mechanism, mechanism["mechanism"]["memory_policy_path"]),
        f"{prefix}/projection/platform-capabilities.yaml": _read_text_ref(
            mechanism, mechanism["projection"]["platform_capabilities_path"]
        ),
        f"{prefix}/projection/ownership-contract.yaml": _read_text_ref(
            mechanism, mechanism["projection"]["ownership_contract_path"]
        ),
        f"{prefix}/emotion/model.yaml": _read_text_ref(mechanism, mechanism["emotion"]["model_path"]),
        f"{prefix}/emotion/state-schema.yaml": _read_text_ref(mechanism, mechanism["emotion"]["state_schema_path"]),
        f"{prefix}/emotion/update-policy.yaml": _read_text_ref(mechanism, mechanism["emotion"]["update_policy_path"]),
        f"{prefix}/emotion/voice-modulation.yaml": _read_text_ref(
            mechanism, mechanism["emotion"]["voice_modulation_path"]
        ),
        f"{prefix}/emotion/memory-events.yaml": _read_text_ref(mechanism, mechanism["emotion"]["memory_events_path"]),
    }
    for skill in mechanism["skills"]:
        refs[f"{prefix}/source-skills/{skill['id']}/SKILL.md"] = _read_text_ref(mechanism, skill["path"])
    return refs


def _memory_skeleton_files(mechanism):
    files = {}
    for item in mechanism["memory"]["local_files"]:
        path = item["path"]
        files[path] = project_memory_file(mechanism, ADAPTER_NAME, path, _read_text_ref(mechanism, path))
    return files


def _workspace_files(mechanism):
    return workspace_files(_read_text_ref(mechanism, "workspace/README.md"))


def _knowledge_files():
    return knowledge_files()


def _render_manifest(mechanism, references, artifacts):
    slug = character_slug(mechanism)
    emotion_mode = _recommended_emotion_mode(mechanism)
    manifest = {
        "kind": "CodexAdapterPack",
        "adapter": ADAPTER_NAME,
        "source_mechanism": references.get("source_mechanism", mechanism.get("source", {}).get("path")),
        "character": {
            "name": character_name(mechanism),
            "slug": slug,
            "user_name": character_user_name(mechanism),
            "direct_emotional_interaction": mechanism.get("emotion", {}).get(
                "direct_interaction", "decide_later"
            ),
            "relationship_continuity": mechanism.get("emotion", {}).get(
                "relationship_continuity", "warm_selective"
            ),
            "emotion_style": character_voice_summary(mechanism),
        },
        "features": {
            "emotion_engine": emotion_engine_feature("codex", installed=False, mode=emotion_mode),
            "memory": _memory_feature(),
            "knowledge": knowledge_feature(),
            "workspace": workspace_feature(),
        },
        "resolved_parameters": mechanism.get("resolved_parameters", {}),
        "run": mechanism.get("run", {}),
        "artifacts": artifacts,
        "implementation_scope": mechanism.get("implementation_scope", {}),
        "ownership": {
            "model_loop": "codex",
            "thread_state": "codex",
            "tools": "codex",
            "durable_memory_source_of_truth": durable_memory_source(mechanism),
            "hooks": "project_config_or_plugin_dependent",
        },
        "boundaries": {
            "is_runtime_executor": False,
            "implements_cloud": False,
            "implemented_runtime": ADAPTER_NAME,
            "emotion_engine_runtime": EMOTION_ENGINE_AVAILABLE_RUNTIME,
            "emotion_engine_mode": emotion_mode,
            "emotion_engine_status": mechanism.get("emotion", {}).get("status"),
            "reserved_runtimes": sorted(mechanism.get("targets", {}).get("reserved", {}).keys()),
            "reserved_specs": sorted(mechanism.get("reserved_specs", {}).keys()),
        },
    }
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def _recommended_emotion_mode(mechanism):
    mode = mechanism.get("emotion", {}).get("recommended_mode", "light")
    return mode if mode in EMOTION_ENGINE_MODES else "light"


def _memory_feature():
    return {
        "core_files": [
            "memory/index.md",
            "memory/profile.md",
            "memory/workstreams.md",
            "memory/workstreams/_template.md",
            "memory/projects/*.md",
            "memory/session-index.md",
            "memory/source-map.md",
            "memory/todos.md",
            "memory/collaboration.md",
        ],
        "pinned_items": 20,
        "recent_activity_hot_entries": 20,
        "session_index_entries": 20,
        "compatibility_files": [
            "memory/pinned.md",
            "memory/recent-activity.md",
            "memory/knowledge_map.md",
            "memory/relationship-state.md",
        ],
        "workstream_load_policy": "load_router_then_relevant_detail",
        "workstream_promotion": "workstream_to_independent_agent_when_persona_toolchain_or_memory_contract_diverges",
        "project_summary_lines": 12,
    }


def _sentence(text):
    text = str(text or "").strip()
    if not text:
        return ""
    if text[-1] in ".!?":
        return text
    return text + "."


def _read_text_ref(mechanism, rel_path):
    path = _resolve_ref(mechanism, rel_path)
    return path.read_text(encoding="utf-8")


def _load_yaml_ref(mechanism, rel_path):
    return yaml.safe_load(_read_text_ref(mechanism, rel_path)) or {}


def _resolve_ref(mechanism, rel_path):
    return resolve_mechanism_file(mechanism, rel_path)
