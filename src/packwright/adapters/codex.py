import json

from packwright.core.adapter_layout import (
    adapter_emotion_engine_runtime,
    adapter_lifecycle,
    adapter_pack_kind,
    render_adapter_capabilities,
    render_ownership_contract,
)
from packwright.core.automation_projection import project_runtime_automations
from packwright.core.emotion_engine_contract import EMOTION_ENGINE_MODES, emotion_engine_feature
from packwright.core.knowledge_contract import knowledge_feature, knowledge_files
from packwright.core.locale import (
    locale_feature,
    localize_entry_markdown,
)
from packwright.core.memory_projection import project_memory_file
from packwright.core.mechanism_contract import normalize_mechanism
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
from packwright.core.skill_projection import (
    projected_generic_skill_files,
    render_skill_projection,
    skill_projection_feature,
    skill_projection_records,
    skill_spec,
)
from packwright.core.validation import validate_mechanism
from packwright.core.workspace_contract import workspace_feature, workspace_files


ADAPTER_NAME = "codex"


def compile_to_codex_pack(mechanism, references=None):
    """Compile a resolved character mechanism into a Codex adapter pack."""
    validate_mechanism(mechanism)
    mechanism = normalize_mechanism(mechanism)
    validate_mechanism(mechanism)

    references = references or {}
    skill_path = save_context_skill_path(mechanism, ADAPTER_NAME)
    save_context = skill_spec(mechanism, "save-context")
    pack = {
        "AGENTS.md": _render_agents_md(mechanism),
        # save-context is mandatory and intentionally bypasses optional
        # capability gating.
        skill_path: render_skill_projection(
            mechanism,
            ADAPTER_NAME,
            save_context,
        ),
    }
    automation_files, automation_feature = project_runtime_automations(mechanism, ADAPTER_NAME)
    pack.update(automation_files)
    pack.update(projected_generic_skill_files(mechanism, ADAPTER_NAME))
    pack.update(_reference_files(mechanism))
    pack.update(_memory_skeleton_files(mechanism))
    pack.update(_knowledge_files())
    pack.update(_workspace_files(mechanism))
    pack["manifest.json"] = _render_manifest(
        mechanism, references, sorted(pack.keys()) + ["manifest.json"], automation_feature
    )
    return pack


def _render_agents_md(mechanism):
    identity = mechanism["identity"]
    name = character_name(mechanism)
    user_name = character_user_name(mechanism)
    skill_path = save_context_skill_path(mechanism, ADAPTER_NAME)
    voice_summary = _sentence(character_voice_summary(mechanism))
    extra_skill_lines = [
        f"- Read `{record['path']}` when {skill_spec(mechanism, record['id'])['trigger']}"
        for record in skill_projection_records(mechanism, ADAPTER_NAME)
        if record["id"] != "save-context" and record["status"] == "projected"
    ]
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
    use_when_index = lines.index("- Read `memory/index.md` first when prior context may matter; it is the memory router, not a project state source.")
    lines[use_when_index:use_when_index] = extra_skill_lines
    return localize_entry_markdown("\n".join(lines), mechanism, ADAPTER_NAME)


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
        f"{prefix}/projection/platform-capabilities.yaml": render_adapter_capabilities(
            ADAPTER_NAME, character_slug(mechanism)
        ),
        f"{prefix}/projection/ownership-contract.yaml": render_ownership_contract(
            ADAPTER_NAME, durable_memory_source(mechanism)
        ),
        f"{prefix}/emotion/model.yaml": _read_text_ref(mechanism, mechanism["emotion"]["model_path"]),
        f"{prefix}/emotion/state-schema.yaml": _read_text_ref(mechanism, mechanism["emotion"]["state_schema_path"]),
        f"{prefix}/emotion/update-policy.yaml": _read_text_ref(mechanism, mechanism["emotion"]["update_policy_path"]),
        f"{prefix}/emotion/voice-modulation.yaml": _read_text_ref(
            mechanism, mechanism["emotion"]["voice_modulation_path"]
        ),
        f"{prefix}/emotion/memory-events.yaml": _read_text_ref(mechanism, mechanism["emotion"]["memory_events_path"]),
    }
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


def _render_manifest(mechanism, references, artifacts, automation_feature):
    slug = character_slug(mechanism)
    emotion_mode = _recommended_emotion_mode(mechanism)
    manifest = {
        "kind": adapter_pack_kind(ADAPTER_NAME),
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
            "automations": automation_feature,
            "locale": locale_feature(mechanism, ADAPTER_NAME),
            "emotion_engine": emotion_engine_feature("codex", installed=False, mode=emotion_mode),
            "skills": skill_projection_feature(mechanism, ADAPTER_NAME),
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
            "hooks": adapter_lifecycle(ADAPTER_NAME),
        },
        "boundaries": {
            "is_runtime_executor": False,
            "implements_cloud": False,
            "implemented_runtime": ADAPTER_NAME,
            "emotion_engine_runtime": adapter_emotion_engine_runtime(ADAPTER_NAME),
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


def _resolve_ref(mechanism, rel_path):
    return resolve_mechanism_file(mechanism, rel_path)
