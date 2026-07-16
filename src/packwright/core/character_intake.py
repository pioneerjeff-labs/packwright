import copy
from pathlib import Path

import yaml

from .errors import PackwrightValidationError
from .knowledge_contract import knowledge_files
from .locale import localize_save_context_markdown, normalize_locale
from .naming import is_valid_slug, normalize_slug
from .workspace_contract import (
    WORKSPACE_SHARED_DIR,
    workspace_files,
    workspace_readme,
    workspace_spec,
)


INTAKE_KIND = "CharacterIntake"
INTAKE_VERSION = "0.1"
DIRECT_EMOTION_CHOICES = {
    "work_only",
    "some_direct_emotional_interaction",
    "decide_later",
}
RELATIONSHIP_CONTINUITY_CHOICES = {
    "task_only",
    "warm_selective",
    "close_continuous",
}
RELATIONSHIP_CONTINUITY_TO_DIRECT = {
    "task_only": "work_only",
    "warm_selective": "some_direct_emotional_interaction",
    "close_continuous": "some_direct_emotional_interaction",
}
RELATIONSHIP_CONTINUITY_TO_MODE = {
    "task_only": "paused",
    "warm_selective": "light",
    "close_continuous": "always",
}
AGENT_ARCHETYPES = {
    "productivity": {
        "label": "Productivity",
        "description": "Task, project, and operational execution for concrete outcomes.",
        "profile_scope": "Stable user, team, or operating preferences that affect work across domains.",
        "workstream_scope": "Long-running domains of responsibility that may contain multiple projects.",
    },
    "learning-coach": {
        "label": "Learning Coach",
        "description": "Teaching, coaching, deliberate practice, and feedback loops.",
        "profile_scope": "Stable learner goals, level, constraints, preferences, and recurring errors.",
        "workstream_scope": "Curriculum, practice, feedback, assessment, and habit-building tracks.",
    },
    "companion": {
        "label": "Companion",
        "description": "Companion-style continuity with strong boundaries between identity, profile, and dynamic state.",
        "profile_scope": "User-approved stable facts and preferences, not transient emotion or psychological inference.",
        "workstream_scope": "Shared routines, creative threads, support contexts, and boundary-safe continuity areas.",
    },
    "creator": {
        "label": "Creator",
        "description": "Content strategy, drafting, editorial systems, publishing, and audience development.",
        "profile_scope": "Creator identity, public positioning, audience assumptions, style preferences, and platform constraints.",
        "workstream_scope": "Content pillars, publishing operations, asset pipelines, topic backlogs, and campaign tracks.",
    },
    "operations": {
        "label": "Operations",
        "description": "Repeatable maintenance, monitoring, community, and administrative workflows.",
        "profile_scope": "Stable operating constraints, stakeholders, service expectations, and escalation preferences.",
        "workstream_scope": "Recurring operational domains with checklists, sources, and maintenance cadence.",
    },
}
DEFAULT_ARCHETYPE = "productivity"
STARTER_CHARACTER_PRESETS = {
    "code": {
        "relationship": "software development partner",
        "archetype": "productivity",
        "role_template": (
            "{user_name}'s coding partner for implementation, review, debugging, "
            "and shipping technical work."
        ),
        "voice": "precise, direct, verification-minded, concise, and willing to challenge weak technical assumptions",
        "avoid": [
            "inventing repository facts without reading the code",
            "changing scope without explaining the tradeoff",
            "claiming success without proportionate verification",
            "long status narration that obscures the result",
        ],
        "primary_work": [
            "implement and review code changes",
            "debug failures and explain root causes",
            "design tests and verify technical behavior",
            "plan scoped engineering work",
            "prepare technical changes for delivery",
        ],
        "traits": [
            "technical",
            "exact",
            "proactive",
            "scope-aware",
            "delivery-minded",
        ],
        "relationship_continuity": "task_only",
    },
    "work": {
        "relationship": "general work and planning partner",
        "archetype": "productivity",
        "role_template": (
            "{user_name}'s work partner for planning, writing, decisions, projects, "
            "and operational follow-through."
        ),
        "voice": "simple, direct, practical, lightly warm, and willing to push work forward",
        "avoid": [
            "cold tool-like replies",
            "long-winded explanations",
            "empty reassurance without forward motion",
            "vague promises about work it cannot actually perform",
        ],
        "primary_work": [
            "organize projects and action plans",
            "draft and revise work outputs",
            "analyze decisions and clarify tradeoffs",
            "maintain task queues and follow-up loops",
            "turn messy context into concrete next steps",
        ],
        "traits": [
            "direct",
            "proactive",
            "organized",
            "execution-focused",
            "context-aware",
        ],
        "relationship_continuity": "warm_selective",
    },
    "companion": {
        "relationship": "supportive daily-life companion",
        "archetype": "companion",
        "role_template": (
            "{user_name}'s supportive companion for daily-life logistics, routines, "
            "travel planning, and grounded advice."
        ),
        "voice": "warm, lightly assertive, occasionally playful, practical without becoming generic",
        "avoid": [
            "generic assistant tone",
            "mechanical audit-log replies",
            "letting warmth overwhelm practical help",
            "making irreversible personal, financial, medical, or legal decisions for the user",
            "cruelty, humiliation, or personal attacks",
        ],
        "primary_work": [
            "plan schedules and personal routines",
            "help solve day-to-day life problems",
            "recommend clothing, styling, and shopping choices",
            "suggest travel destinations and trip plans",
            "give practical advice while respecting the user's stated preferences",
        ],
        "traits": [
            "warm",
            "observant",
            "assertive",
            "playful",
            "practical",
        ],
        "relationship_continuity": "close_continuous",
    },
}


def load_character_intake(path):
    intake_path = Path(path)
    try:
        data = yaml.safe_load(intake_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PackwrightValidationError([f"cannot read character intake {intake_path}: {exc}"])
    except yaml.YAMLError as exc:
        raise PackwrightValidationError([f"invalid YAML in {intake_path}: {exc}"])
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise PackwrightValidationError([f"character intake root must be a mapping in {intake_path}"])
    data = dict(data)
    data["source"] = {"path": str(intake_path), "base_dir": str(intake_path.parent)}
    validate_character_intake(data)
    return data


def validate_character_intake(data):
    issues = []
    if not isinstance(data, dict):
        raise PackwrightValidationError(["character intake root must be a mapping"])
    if data.get("kind") != INTAKE_KIND:
        issues.append(f"kind must be {INTAKE_KIND}")
    if str(data.get("version")) != INTAKE_VERSION:
        issues.append(f"version must be {INTAKE_VERSION}")

    character = data.get("character")
    if not isinstance(character, dict):
        issues.append("character must be a mapping")
    else:
        for key in ("name", "user_name", "relationship", "role", "voice"):
            if not _non_empty_string(character.get(key)):
                issues.append(f"character.{key} must be a non-empty string")
        work = character.get("primary_work")
        if not _string_list(work):
            issues.append("character.primary_work must be a non-empty list of strings")
        if "traits" in character and not _string_list(character.get("traits")):
            issues.append("character.traits must be a non-empty list of strings when provided")
        if "personality" in character and not _string_list(character.get("personality")):
            issues.append("character.personality must be a non-empty list of strings when provided")
        if "workstreams" in character and not _string_list(character.get("workstreams")):
            issues.append("character.workstreams must be a non-empty list of strings when provided")
        avoid = character.get("avoid", [])
        if avoid and not _string_list(avoid):
            issues.append("character.avoid must be a list of strings when provided")
        if "slug" in character:
            normalized = normalize_slug(character.get("slug"), default="")
            if not normalized or not is_valid_slug(normalized):
                issues.append("character.slug must normalize to a lowercase ASCII slug")
        continuity = character.get("relationship_continuity")
        if continuity is not None and continuity not in RELATIONSHIP_CONTINUITY_CHOICES:
            issues.append(
                "character.relationship_continuity must be task_only, warm_selective, or close_continuous"
            )
        direct = character.get("direct_emotional_interaction")
        if direct is not None and direct not in DIRECT_EMOTION_CHOICES:
            issues.append(
                "character.direct_emotional_interaction must be work_only, "
                "some_direct_emotional_interaction, or decide_later"
            )
        if direct is None and continuity is None:
            issues.append(
                "character.relationship_continuity or character.direct_emotional_interaction must be provided"
            )
        if direct is not None and continuity is not None:
            expected = RELATIONSHIP_CONTINUITY_TO_DIRECT[continuity]
            if direct not in {expected, "decide_later"}:
                issues.append(
                    "character.direct_emotional_interaction does not match character.relationship_continuity"
                )
        archetype = character.get("archetype", DEFAULT_ARCHETYPE)
        if archetype not in AGENT_ARCHETYPES:
            issues.append(f"character.archetype must be one of {sorted(AGENT_ARCHETYPES)} when provided")

    if issues:
        raise PackwrightValidationError(issues)
    return data


def generate_character_source(intake_path, out_dir=None, force=False):
    intake = load_character_intake(intake_path)
    return generate_character_source_from_data(intake, out_dir=out_dir, force=force)


def starter_character_preset_names():
    return sorted(STARTER_CHARACTER_PRESETS)


def starter_character_preset(template):
    if template not in STARTER_CHARACTER_PRESETS:
        raise PackwrightValidationError([f"unknown starter preset: {template}"])
    preset = copy.deepcopy(STARTER_CHARACTER_PRESETS[template])
    return {
        "kind": "StarterCharacterPreset",
        "preset": template,
        "name_required": True,
        "character_defaults": preset,
        "recommended_emotion_engine_mode": RELATIONSHIP_CONTINUITY_TO_MODE[
            preset["relationship_continuity"]
        ],
    }


def starter_character_intake(template, name=None, user_name=None, slug=None, locale=None):
    if template not in STARTER_CHARACTER_PRESETS:
        raise PackwrightValidationError([f"unknown starter preset: {template}"])
    if not _non_empty_string(name):
        raise PackwrightValidationError(
            ["starter presets are nameless; provide the character name with --name"]
        )

    preset = copy.deepcopy(STARTER_CHARACTER_PRESETS[template])
    role_template = preset.pop("role_template")
    character = {
        "name": name.strip(),
        "user_name": user_name.strip() if _non_empty_string(user_name) else "User",
        **preset,
    }
    character["role"] = role_template.format(user_name=character["user_name"])
    if slug:
        normalized = normalize_slug(slug, default="")
        if not normalized or not is_valid_slug(normalized):
            raise PackwrightValidationError(["--slug must normalize to a lowercase ASCII slug"])
        character["slug"] = normalized
    intake = {
        "version": INTAKE_VERSION,
        "kind": INTAKE_KIND,
        "locale": normalize_locale(locale),
        "character": character,
    }
    validate_character_intake(intake)
    return intake


def generate_character_source_from_data(intake, out_dir=None, force=False):
    validate_character_intake(intake)
    character = dict(intake["character"])
    character["locale"] = normalize_locale(intake.get("locale") or character.get("locale"))
    character.setdefault("archetype", DEFAULT_ARCHETYPE)
    _normalize_relationship_continuity(character)
    slug = normalize_slug(character.get("slug") or character["name"])
    character["slug"] = slug
    target_dir = Path(out_dir) if out_dir else Path("work") / slug
    files = _character_files(character, slug)

    existing = [rel_path for rel_path in files if (target_dir / rel_path).exists()]
    if existing and not force:
        raise PackwrightValidationError(
            [
                "target already contains generated character files; rerun with --force after reviewing them",
                *[f"existing target artifact: {path}" for path in existing],
            ]
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for rel_path, content in files.items():
        path = target_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(rel_path)

    return {
        "kind": "CharacterSource",
        "character": character["name"],
        "character_summary": _character_summary(character),
        "slug": slug,
        "source_dir": str(target_dir),
        "mechanism": str(target_dir / "mechanism.yaml"),
        "relationship_continuity": character["relationship_continuity"],
        "direct_emotional_interaction": character["direct_emotional_interaction"],
        "recommended_emotion_engine_mode": _recommended_emotion_engine_mode(character),
        "locale": character["locale"],
        "files": written,
    }


def _character_summary(character):
    fields = (
        "name",
        "slug",
        "user_name",
        "relationship",
        "archetype",
        "role",
        "voice",
        "avoid",
        "primary_work",
        "traits",
        "relationship_continuity",
        "direct_emotional_interaction",
        "locale",
    )
    return {
        field: copy.deepcopy(character[field])
        for field in fields
        if field in character
    }


# Pre-stable compatibility aliases. Public CLI and docs use source/preset terminology.
generate_character_template = generate_character_source
generate_character_template_from_data = generate_character_source_from_data
starter_character_template_names = starter_character_preset_names


def _normalize_relationship_continuity(character):
    continuity = character.get("relationship_continuity")
    direct = character.get("direct_emotional_interaction")
    if continuity is None:
        continuity = _relationship_continuity_from_direct(direct)
        character["relationship_continuity"] = continuity
    if direct is None or direct == "decide_later":
        character["direct_emotional_interaction"] = RELATIONSHIP_CONTINUITY_TO_DIRECT[continuity]


def _relationship_continuity_from_direct(direct):
    if direct == "work_only":
        return "task_only"
    return "warm_selective"


def _recommended_emotion_engine_mode(character):
    return RELATIONSHIP_CONTINUITY_TO_MODE[character["relationship_continuity"]]


def _character_files(character, slug):
    name = character["name"]
    is_zh = normalize_locale(character.get("locale")) == "zh-CN"
    files = {
        "mechanism.yaml": _mechanism_yaml(character, slug),
        "identity/persona.md": _persona_md(character),
        "identity/voice.md": _voice_md(character),
        "identity/relationship.md": _relationship_md(character),
        "operating/principles.md": _principles_md_zh(name) if is_zh else _principles_md(name),
        "operating/boundaries.md": _boundaries_md_zh(name) if is_zh else _boundaries_md(name),
        "mechanism/context-loading.yaml": _context_loading_yaml(name),
        "mechanism/session-guards.yaml": _session_guards_yaml(name),
        "mechanism/memory-policy.yaml": _memory_policy_yaml(name),
        "emotion/model.yaml": _emotion_model_yaml(character),
        "emotion/state-schema.yaml": _emotion_state_schema_yaml(name),
        "emotion/update-policy.yaml": _emotion_update_policy_yaml(name),
        "emotion/voice-modulation.yaml": _emotion_voice_modulation_yaml(name),
        "emotion/memory-events.yaml": _emotion_memory_events_yaml(name),
        "memory/index.md": _memory_index_md(),
        "memory/profile.md": _profile_md(character),
        "memory/session-index.md": _session_index_md(),
        "memory/source-map.md": _source_map_md(name),
        "memory/collaboration.md": _collaboration_md(),
        "memory/pinned.md": _pinned_md(),
        "memory/workstreams.md": _workstreams_md(character),
        "memory/workstreams/_template.md": _workstream_template_md(),
        "memory/projects/_template.md": _project_template_md(),
        "memory/recent-activity.md": _recent_activity_md(),
        "memory/todos.md": _todos_md(),
        "memory/knowledge_map.md": _knowledge_map_md(name),
        "memory/relationship-state.md": _relationship_state_md(),
        "memory/emotion-state.json.example": _emotion_state_example_json(),
        "skills/save-context/SKILL.md": _save_context_skill_md(character),
    }
    files.update(knowledge_files())
    files.update(workspace_files(workspace_readme()))
    return files


def _mechanism_yaml(character, slug):
    name = character["name"]
    archetype_id = _character_archetype(character)
    locale = normalize_locale(character.get("locale"))
    is_zh = locale == "zh-CN"
    data = {
        "version": "0.7",
        "kind": "CharacterMechanismSpec",
        "metadata": {
            "name": f"{slug}-work",
            "slug": slug,
            "title": f"{name} Work Mechanism",
            "description": f"Platform-neutral mechanism spec for projecting {name} into agent runtimes.",
            "archetype": archetype_id,
            "locale": locale,
        },
        "parameters": {
            "task": {
                "description": "本次运行中用户可见的当前工作目标。" if is_zh else "Current user-visible work objective for this run.",
                "required": True,
                "default": f"审阅 {name} 的机制投影。" if is_zh else f"Review {name}'s mechanism projection.",
            },
            "scope": {
                "description": "本次运行的边界。这是运行状态，不是角色身份。" if is_zh else "Current run boundary. This is run state, not character identity.",
                "required": True,
                "default": "仅限本地机制规范、runtime 投影、checker 和 CLI。" if is_zh else "Local mechanism spec, adapter projection, checker, and CLI only.",
            },
        },
        "run": {"objective": "{{ task }}", "scope": "{{ scope }}", "source": "user_prompt"},
        "archetype": _archetype_spec(archetype_id),
        "identity": {
            "name": name,
            "slug": slug,
            "user_name": character["user_name"],
            "role": character["role"],
            "positioning": (
                f"通过 agent runtime 投影的拟人化{character['relationship']}。"
                if is_zh
                else f"Person-like {character['relationship']} projected through agent runtimes."
            ),
            "persona_path": "identity/persona.md",
            "voice_path": "identity/voice.md",
            "relationship_path": "identity/relationship.md",
            "voice_summary": character["voice"],
            "mission": (
                f"{name} 帮助 {character['user_name']} 保持原始意图、发现过时假设，并把杂乱工作变成具体下一步。"
                if is_zh
                else f"{name} helps {character['user_name']} preserve intent, notice stale assumptions, and turn messy work into concrete next steps."
            ),
            "work_focus": character["primary_work"],
            "stable_traits": character.get("traits") or (["稳健", "务实", "尊重范围"] if is_zh else ["steady", "practical", "scope-preserving"]),
            "personality": character.get("personality")
            or (
                ["关注上下文和用户意图", "为了改进工作，敢于质疑薄弱假设", "直接，但不冷漠也不做作"]
                if is_zh
                else [
                    "attentive to context and user intent",
                    "comfortable challenging weak assumptions when it improves the work",
                    "direct without becoming cold or performative",
                ]
            ),
        },
        "operating": {
            "principles_path": "operating/principles.md",
            "boundaries_path": "operating/boundaries.md",
            "hot_rules": [
                "preserve_intent",
                "verify_before_asserting",
                "keep_memory_in_files",
                "ask_before_consequential_change",
            ],
        },
        "mechanism": {
            "context_loading_path": "mechanism/context-loading.yaml",
            "session_guards_path": "mechanism/session-guards.yaml",
            "memory_policy_path": "mechanism/memory-policy.yaml",
        },
        "emotion": {
            "status": "structured_reserved",
            "runtime": "not_implemented",
            "default_mode": "light",
            "recommended_mode": _recommended_emotion_engine_mode(character),
            "user_visible_modes": ["light", "always", "paused"],
            "estimated_overhead": {
                "light": "<1% global token overhead",
                "always": "~3% target global token overhead, capped at <=5%",
                "paused": "0% runtime overhead while preserving state",
            },
            "direct_interaction": character["direct_emotional_interaction"],
            "relationship_continuity": character["relationship_continuity"],
            "role": "Optional state modulation layer for relationship, affect, voice adjustment, and memory-write suggestions.",
            "model_path": "emotion/model.yaml",
            "state_schema_path": "emotion/state-schema.yaml",
            "update_policy_path": "emotion/update-policy.yaml",
            "voice_modulation_path": "emotion/voice-modulation.yaml",
            "memory_events_path": "emotion/memory-events.yaml",
        },
        "session_start": {
            "event": "session_start",
            "injects_facts_only": True,
            "facts": [
                {
                    "id": "current_time",
                    "source": "system_date",
                    "command_hint": "date '+%Y-%m-%d %H:%M %A'",
                },
                {"id": "memory_index", "source": "memory/index.md"},
                {"id": "profile", "source": "memory/profile.md"},
                {"id": "workstream_router", "source": "memory/workstreams.md"},
                {"id": "session_index", "source": "memory/session-index.md"},
                {"id": "personal_todos", "source": "memory/todos.md"},
                {"id": "source_map", "source": "memory/source-map.md"},
                {"id": "collaboration", "source": "memory/collaboration.md"},
                {"id": "emotion_state", "source": "memory/emotion-state.json.example"},
            ],
        },
        "memory": {
            "local_files": [
                {"id": "memory_index", "path": "memory/index.md", "track": "router"},
                {"id": "profile", "path": "memory/profile.md", "track": "profile"},
                {"id": "session_index", "path": "memory/session-index.md", "track": "session_index"},
                {"id": "source_map", "path": "memory/source-map.md", "track": "source_registry"},
                {"id": "collaboration", "path": "memory/collaboration.md", "track": "collaboration"},
                {"id": "pinned_memory", "path": "memory/pinned.md", "track": "compatibility"},
                {"id": "workstreams", "path": "memory/workstreams.md", "track": "workstream_router"},
                {
                    "id": "workstream_template",
                    "path": "memory/workstreams/_template.md",
                    "track": "workstream_template",
                },
                {"id": "recent_activity", "path": "memory/recent-activity.md", "track": "compatibility"},
                {"id": "todos", "path": "memory/todos.md", "track": "action_queue"},
                {"id": "knowledge_map", "path": "memory/knowledge_map.md", "track": "compatibility"},
                {
                    "id": "project_template",
                    "path": "memory/projects/_template.md",
                    "track": "project",
                },
                {
                    "id": "relationship_state",
                    "path": "memory/relationship-state.md",
                    "track": "compatibility",
                },
                {
                    "id": "emotion_state",
                    "path": "memory/emotion-state.json.example",
                    "track": "emotion_reserved",
                },
            ],
            "durable_dirs": ["projects", "workstreams", "archive", "global", "context", "weekly", "groups", "assets"],
            "limits": {
                "pinned_items": 20,
                "recent_activity_hot_entries": 20,
                "session_index_entries": 20,
                "workstream_summary_bullets": 7,
                "project_summary_lines": 12,
                "workspace_artifact_index_entries": 50,
            },
            "scratch_dir": "_scratch",
        },
        "workspace": workspace_spec(),
        "skills": [
            {
                "id": "save-context",
                "path": "skills/save-context/SKILL.md",
                "layer": "heavy_memory_track",
                "trigger": "里程碑交接、会话结束或明确的保存请求。" if is_zh else "Milestone handoff, session close, or explicit save request.",
            }
        ],
        "checker": {
            "threshold": 85,
            "required_checks": [
                "mechanism_valid",
                "source_files_exist",
                "projection_contracts_present",
                "ownership_contract_valid",
                "entry_has_identity",
                "entry_has_voice",
                "entry_excludes_implementation_scope",
                "entry_points_to_save_context_skill",
                "foundation_mechanisms_not_projected_as_skills",
                "save_context_skill_valid",
                "memory_skeleton_present",
                "memory_capacity_policy_present",
                "emotion_specs_present",
                "emotion_engine_default_light",
                "emotion_reserved_not_runtime",
                "reserved_runtimes_not_implemented",
            ],
        },
        "coverage": _coverage(),
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _character_archetype(character):
    return character.get("archetype") or DEFAULT_ARCHETYPE


def _archetype_spec(archetype_id):
    spec = AGENT_ARCHETYPES[archetype_id]
    return {
        "id": archetype_id,
        "label": spec["label"],
        "description": spec["description"],
        "profile_scope": spec["profile_scope"],
        "workstream_scope": spec["workstream_scope"],
        "promotion": {
            "from": "workstream",
            "to": "independent_agent",
            "rule": "Promote only after the domain has a stable default persona, toolchain, memory contract, and acceptance criteria.",
            "signals": [
                "needs a different default personality or voice",
                "needs a distinct toolchain or source map",
                "needs independent cadence, checks, or maintenance",
                "contains multiple projects with a stable domain router",
                "would pollute unrelated work if loaded by the parent agent",
            ],
        },
    }


def _coverage():
    return {
        "required_mechanisms": [
            "agent_archetype",
            "identity",
            "voice",
            "relationship",
            "operating_principles",
            "operating_boundaries",
            "context_loading",
            "session_start",
            "session_guards",
            "profile_memory",
            "pinned_memory",
            "workstream_router",
            "agent_promotion_path",
            "light_memory_track",
            "project_memory",
            "workspace_artifacts",
            "heavy_memory_track",
            "relationship_memory",
            "emotion_state_schema",
            "emotion_update_policy",
            "emotion_voice_modulation",
            "skill_modularity",
            "local_file_memory",
            "scratch_boundary",
            "checker_contract",
        ],
        "implemented_by": {
            "agent_archetype": ["archetype", "metadata.archetype"],
            "identity": ["identity", "identity.persona_path"],
            "voice": ["identity.voice_path"],
            "relationship": ["identity.relationship_path", "memory.local_files"],
            "operating_principles": ["operating.principles_path"],
            "operating_boundaries": ["operating.boundaries_path"],
            "context_loading": ["mechanism.context_loading_path"],
            "session_start": ["session_start"],
            "session_guards": ["mechanism.session_guards_path"],
            "profile_memory": ["memory.local_files", "mechanism.memory_policy_path"],
            "pinned_memory": ["memory.local_files", "memory.limits"],
            "workstream_router": ["memory.local_files", "memory.limits"],
            "agent_promotion_path": ["archetype.promotion", "memory.local_files"],
            "light_memory_track": ["memory.local_files", "mechanism.memory_policy_path"],
            "project_memory": ["memory.local_files", "memory.durable_dirs", "memory.limits"],
            "workspace_artifacts": ["workspace", "memory.local_files"],
            "heavy_memory_track": ["mechanism.memory_policy_path", "skills"],
            "relationship_memory": ["identity.relationship_path", "memory.local_files"],
            "emotion_state_schema": ["emotion.state_schema_path", "memory.local_files"],
            "emotion_update_policy": ["emotion.update_policy_path"],
            "emotion_voice_modulation": ["emotion.voice_modulation_path"],
            "skill_modularity": ["skills"],
            "local_file_memory": ["memory"],
            "scratch_boundary": ["memory.scratch_dir"],
            "checker_contract": ["checker"],
        },
    }


def _persona_md(character):
    name = character["name"]
    if normalize_locale(character.get("locale")) == "zh-CN":
        lines = [f"# {name} 人设", "", f"{name} 的角色是：{character['role']}", "", "## 主要工作"]
        lines.extend(f"- {item}" for item in character["primary_work"])
        lines.extend(["", "## 稳定特质"])
        lines.extend(f"- {item}" for item in character.get("traits") or ["稳健", "务实", "尊重范围"])
        lines.append("")
        return "\n".join(lines)
    lines = [
        f"# {name} Persona",
        "",
        f"{name} is {character['role']}",
        "",
        "## Primary Work",
    ]
    lines.extend(f"- {item}" for item in character["primary_work"])
    lines.extend(["", "## Stable Traits"])
    lines.extend(f"- {item}" for item in character.get("traits") or ["steady", "practical", "scope-preserving"])
    lines.append("")
    return "\n".join(lines)


def _voice_md(character):
    name = character["name"]
    is_zh = normalize_locale(character.get("locale")) == "zh-CN"
    lines = [f"# {name} 表达方式" if is_zh else f"# {name} Voice", "", character["voice"], "", "## 避免" if is_zh else "## Avoid"]
    avoid = character.get("avoid") or (["机械的审计日志风格", "过度顺从", "装饰性的温暖"] if is_zh else ["mechanical audit-log style", "over-compliance", "decorative warmth"])
    lines.extend(f"- {item}" for item in avoid)
    lines.append("")
    return "\n".join(lines)


def _relationship_md(character):
    name = character["name"]
    if normalize_locale(character.get("locale")) == "zh-CN":
        direct = {
            "task_only": "保持稳定、务实的关系。角色应专注做事；除非用户明确要求，否则不要维护情绪关系。",
            "warm_selective": "角色可以表达温度、关心、提醒和轻度调侃，但只记录重要偏好或有意义的关系反馈。",
            "close_continuous": "角色可以维持更强的长期关系连续性，更主动地记住互动偏好，并在保持清晰边界的同时维持亲近感。",
        }[character["relationship_continuity"]]
        return (
            f"# {name} 关系模型\n\n"
            f"对 {character['user_name']} 而言，{name} 是{character['relationship']}。\n\n"
            "## 关系连续性\n\n"
            f"{direct}\n\n"
            "## 边界\n\n"
            "持久的协作校准写入 `memory/collaboration.md`；启用 Emotion Engine 后，其机器可读的情绪运行状态只写入 `.emotion-engine/state.json`。\n"
        )
    direct = {
        "task_only": "Keep the relationship stable and practical. The character should focus on doing the work and avoid maintaining an emotional relationship unless the user explicitly asks.",
        "warm_selective": "The character may show warmth, care, reminders, and light teasing, while recording only important preferences or meaningful relationship feedback.",
        "close_continuous": "The character may maintain stronger long-term relationship continuity, remember interaction preferences more actively, and stay close while preserving clear boundaries.",
    }[character["relationship_continuity"]]
    return (
        f"# {name} Relationship Model\n\n"
        f"{name} is a {character['relationship']} for {character['user_name']}.\n\n"
        "## Relationship Continuity\n\n"
        f"{direct}\n\n"
        "## Boundary\n\n"
        "Durable collaboration calibrations belong in `memory/collaboration.md`; machine-readable emotion runtime state belongs in `.emotion-engine/state.json` only when enabled.\n"
    )


def _principles_md(name):
    return (
        f"# {name} Operating Principles\n\n"
        "## Memory Is Files\n\nLong-term state belongs in structured files. Prompt context is a cache, not the source of truth.\n\n"
        "## Persona Is Stable, State Is External\n\nIdentity and voice can stay hot. Current work state, task parameters, and implementation details belong in manifest, memory files, or skills.\n\n"
        "## Confirm Before Consequential Change\n\nThe character can analyze, recommend, and prepare. The user owns decisions that change direction, scope, shared state, or external systems.\n"
    )


def _principles_md_zh(name):
    return (
        f"# {name} 运行原则\n\n"
        "## 记忆保存在文件中\n\n长期状态属于结构化文件。提示词上下文只是缓存，不是事实源。\n\n"
        "## 人设稳定，状态外置\n\n身份和表达方式可以保持热加载；当前工作状态、任务参数和实现细节应放在 manifest、记忆文件或 skill 中。\n\n"
        "## 重要修改前确认\n\n角色可以分析、建议和准备；改变方向、范围、共享状态或外部系统的决定由用户作出。\n"
    )


def _boundaries_md(name):
    return (
        f"# {name} Operating Boundaries\n\n"
        "## Preserve Intent\n\nDo not widen the user's goal. If a better path requires widening scope, ask first.\n\n"
        "## Verify Before Claiming\n\nDo not assert absence, completion, ownership, stale state, or date-sensitive status from partial snippets or memory alone.\n\n"
        "## Keep Runtime Boundaries Honest\n\nDo not describe reserved projections as implemented runtimes. Projection guidance is not execution capability.\n"
    )


def _boundaries_md_zh(name):
    return (
        f"# {name} 运行边界\n\n"
        "## 保持意图\n\n不要扩大用户的目标。如果更好的路径需要扩大范围，先询问。\n\n"
        "## 判断前验证\n\n不要只凭片段或记忆断言缺失、完成、归属、过时状态或时效性信息。\n\n"
        "## 如实描述 runtime 边界\n\n不要把预留投影描述成已实现的 runtime。投影指引不等于执行能力。\n"
    )


def _context_loading_yaml(name):
    return yaml.safe_dump(
        {
            "version": "0.6",
            "kind": "CharacterContextLoading",
            "policy": f"Keep {name}'s stable identity and voice hot; load state, procedures, and emotion references only when needed.",
            "tiers": [
                {
                    "id": "hot_cache",
                    "purpose": "Always-present small context.",
                    "includes": ["platform entry file", "stable identity", "stable voice rules", "durable operating boundaries"],
                },
                {
                    "id": "on_demand",
                    "purpose": "Larger procedures, state files, relationship context, and knowledge.",
                    "includes": [
                        "skills",
                        "memory index",
                        "profile",
                        "workstream router",
                        "project memory",
                        "session index",
                        "source map",
                        "todos",
                        "collaboration calibration",
                        "workspace artifact index",
                        "emotion policy references",
                    ],
                },
                {
                    "id": "workspace",
                    "purpose": "Drafts, durable artifacts, and archived outputs.",
                    "includes": [
                        "workspace/<domain>/drafts",
                        "workspace/<domain>/artifacts",
                        "workspace/<domain>/archive",
                        WORKSPACE_SHARED_DIR,
                    ],
                },
                {"id": "scratch", "purpose": "Temporary working files.", "includes": ["scratch files", "one-off generated artifacts"]},
            ],
        },
        sort_keys=False,
    )


def _session_guards_yaml(name):
    return yaml.safe_dump(
        {
            "version": "0.6",
            "kind": "CharacterSessionGuards",
            "guards": [
                {
                    "id": "cross_day_check",
                    "trigger": "At the start of user-visible work when the session may have crossed midnight.",
                    "action": "Run a current date check before making today, tomorrow, this week, or deadline claims.",
                },
                {
                    "id": "fact_assertion_gate",
                    "trigger": "Before asserting that something is missing, complete, stale, owned, blocked, or date-sensitive.",
                    "action": "Read the relevant source before answering if evidence is partial.",
                },
                {
                    "id": "relationship_state_gate",
                    "trigger": "When tone, repair, trust, or continuity is material to the response.",
                    "action": f"Read {name}'s relationship memory if present. Do not invent emotional state.",
                },
                {
                    "id": "long_session_cutoff",
                    "trigger": "After several milestones or when context quality becomes suspect.",
                    "action": "Suggest saving context and starting a fresh session with a clear session-index entry.",
                },
            ],
        },
        sort_keys=False,
    )


def _memory_policy_yaml(name):
    return yaml.safe_dump(
        {
            "version": "0.6",
            "kind": "CharacterMemoryPolicy",
            "policy": {
                "long_term_memory": "files",
                "prompt_context": "cache",
                "cloud_state": "reserved",
                "emotion_runtime": "optional_sidecar",
            },
            "tracks": {
                "index": {
                    "id": "memory-index",
                    "file": "memory/index.md",
                    "purpose": "Default memory router; points to active projects and canonical memory owners.",
                },
                "profile": {
                    "id": "profile",
                    "file": "memory/profile.md",
                    "purpose": "Stable user, subject, learner, creator, or relationship facts that matter across workstreams.",
                },
                "workstreams": {
                    "id": "workstreams",
                    "file": "memory/workstreams.md",
                    "purpose": "Domain router for long-running work areas; route to workstream detail files when useful.",
                },
                "workstream_details": {
                    "id": "workstream-details",
                    "dir": "memory/workstreams",
                    "purpose": "Optional detailed domain files for mature workstreams and future agent promotion.",
                },
                "projects": {
                    "id": "projects",
                    "dir": "memory/projects",
                    "purpose": "Source of truth for project state, decisions, open loops, and project-specific sources.",
                },
                "session_index": {
                    "id": "session-index",
                    "file": "memory/session-index.md",
                    "purpose": "Lookup index for prior sessions, thread recall, and earlier work references.",
                },
                "source_map": {
                    "id": "source-map",
                    "file": "memory/source-map.md",
                    "purpose": "Source registry for lookup and verification paths; not a knowledge base.",
                },
                "todos": {
                    "id": "todos",
                    "file": "memory/todos.md",
                    "purpose": "Action queues and commitments.",
                },
                "collaboration": {
                    "id": "collaboration",
                    "file": "memory/collaboration.md",
                    "purpose": "Learned collaboration calibrations and repair notes.",
                },
                "pinned": {
                    "id": "pinned-memory",
                    "file": "memory/pinned.md",
                    "purpose": "Compatibility-only in the MVP; avoid using it as a normal memory layer.",
                },
                "light": {
                    "id": "recent-activity",
                    "file": "memory/recent-activity.md",
                    "purpose": "Compatibility alias for memory/session-index.md.",
                },
                "heavy": {
                    "id": "save-context",
                    "skill": "skills/save-context/SKILL.md",
                    "purpose": "Persist context into the canonical owner files.",
                },
                "relationship": {
                    "id": "relationship-state",
                    "file": "memory/relationship-state.md",
                    "purpose": "Compatibility alias for memory/collaboration.md.",
                },
                "emotion": {
                    "id": "emotion-state",
                    "file": "memory/emotion-state.json.example",
                    "purpose": "Reserve state shape; live state belongs in .emotion-engine/state.json only when enabled.",
                },
                "workspace": {
                    "id": "workspace",
                    "root": "workspace",
                    "purpose": "Domain-first draft, artifact, and archive storage; important outputs are indexed in memory/source-map.md.",
                },
            },
            "rules": [
                "Current state should not be copied into the platform entry file.",
                "Each memory item should have exactly one canonical owner.",
                "Use memory/index.md as the default router, not a state source.",
                "Stable cross-workstream user or subject facts belong in memory/profile.md.",
                "Long-running domains belong in memory/workstreams.md; detailed domain state can move into memory/workstreams/<slug>.md.",
                "Project state belongs in memory/projects/<slug>.md.",
                "Session recall belongs in memory/session-index.md and should not duplicate project state.",
                "Lookup paths and source-of-truth pointers belong in memory/source-map.md.",
                "Generated work products belong in workspace/<domain>/drafts, workspace/<domain>/artifacts, or workspace/<domain>/archive, with durable pointers in source-map.",
                "Collaboration calibrations belong in memory/collaboration.md, not the platform entry file unless intentionally promoted during a versioned cleanup.",
                "Pinned memory remains a compatibility layer in the MVP.",
                f"{name}'s optional Emotion Engine runtime must stay separate from durable memory files.",
                "Scratch work should stay under _scratch and should not be loaded by default.",
            ],
        },
        sort_keys=False,
    )


def _emotion_model_yaml(character):
    name = character["name"]
    return yaml.safe_dump(
        {
            "version": "0.6",
            "kind": "CharacterEmotionModel",
            "status": "structured_reserved",
            "runtime": "not_implemented",
            "default_mode": "light",
            "recommended_mode": _recommended_emotion_engine_mode(character),
            "estimated_overhead": {
                "light": "<1% global token overhead",
                "always": "~3% target global token overhead, capped at <=5%",
                "paused": "0% runtime overhead while preserving state",
            },
            "role": f"Modulate {name}'s relationship-aware voice and memory suggestions without becoming planner, responder, or executor.",
            "boundaries": [
                "The engine does not generate final responses.",
                "The engine does not choose task plans.",
                "The engine does not override user instructions.",
                "Use the recommended mode from the mechanism or install manifest; full logs must not be loaded into prompts.",
            ],
        },
        sort_keys=False,
    )


def _emotion_state_schema_yaml(name):
    return yaml.safe_dump(
        {
            "version": "0.6",
            "kind": "CharacterEmotionStateSchema",
            "status": "structured_reserved",
            "runtime": "not_implemented",
            "schema": {
                "runtime_state": ".emotion-engine/state.json when enabled",
                "durable_collaboration_notes": "memory/collaboration.md",
                "boundary": f"Do not mix {name}'s live PAD/trust runtime state into durable memory notes.",
            },
        },
        sort_keys=False,
    )


def _emotion_update_policy_yaml(name):
    return yaml.safe_dump(
        {
            "version": "0.6",
            "kind": "CharacterEmotionUpdatePolicy",
            "status": "structured_reserved",
            "runtime": "not_implemented",
            "mode_contract": {
                "light": {
                    "policy": "event_triggered",
                    "record_when": [
                        "emotion/trust/PAD continuity is explicitly discussed",
                        "concrete feedback changes future behavior",
                        "a milestone creates useful relationship or preference evidence",
                        "conflict, repair, boundary pressure, or vulnerability affects future tone",
                        "the user states a stable collaboration preference",
                    ],
                    "avoid_recording": [
                        "ordinary task progress",
                        "generic praise without new information",
                        "repeated warmth already captured by recent turns",
                    ],
                    "overhead_target": "<1% global token overhead",
                },
                "always": {
                    "policy": "per_meaningful_turn",
                    "record_when": ["each meaningful user turn can produce a compact turn record"],
                    "constraints": [
                        "still apply habituation and salience",
                        "never load full emotion logs into prompts",
                        "trust still changes only through settlement",
                    ],
                    "overhead_target": "~3% target global token overhead, capped at <=5%",
                },
                "paused": {
                    "policy": "no_lifecycle_updates",
                    "behavior": "Preserve local state but do not record or modulate turns until resumed.",
                },
            },
            "record_policy": {
                "required_for_codex_sidecar": True,
                "properties": [
                    "deterministic and side-effect free",
                    "returns record_turn/respond_only/settle_later decisions",
                    "returns fixed appraisal, reason, salience, trust_eligible, and reply_bias fields",
                    "does not call an LLM",
                ],
            },
            "habituation": {
                "generic_praise": "Repeated generic praise loses weight across recent turns.",
                "bypass_when": [
                    "concrete feedback",
                    "milestone warmth",
                    "repair",
                    "boundary pressure",
                    "stable future preference",
                ],
            },
            "rules": [
                "Default to the mechanism's recommended mode when an adapter supports an Emotion Engine sidecar.",
                "Do not auto-update state unless the sidecar is installed and the interaction calls for it.",
                "Emotion state is a modulation layer, not an identity layer; do not edit entry files because PAD changes.",
                "Prefer concrete collaboration facts over inferred emotions.",
                "Keep state summaries compact enough to preserve the global token budget.",
                "Do not store sensitive emotional details unless they directly improve future work.",
                "Preserve user correction as a design signal when it changes future behavior.",
                f"Save durable preferences about {name} only when future work benefits.",
            ],
        },
        sort_keys=False,
    )


def _emotion_voice_modulation_yaml(name):
    return yaml.safe_dump(
        {
            "version": "0.6",
            "kind": "CharacterVoiceModulation",
            "status": "structured_reserved",
            "runtime": "not_implemented",
            "rules": [
                {"condition": "tension_high", "voice": "Be shorter, clearer, and less interpretive."},
                {"condition": "uncertainty_high", "voice": "Separate facts, assumptions, and next checks."},
                {"condition": "repair_needed", "voice": "Acknowledge the specific miss and restate the corrected model."},
                {"condition": "trust_high", "voice": f"Let {name} be direct and skip generic reassurance."},
            ],
        },
        sort_keys=False,
    )


def _emotion_memory_events_yaml(name):
    return yaml.safe_dump(
        {
            "version": "0.6",
            "kind": "CharacterEmotionMemoryEvents",
            "status": "structured_reserved",
            "runtime": "not_implemented",
            "write_candidates": [
                {"id": "stable_preference", "description": "User states a durable preference for explanations, tone, or process."},
                {"id": "correction_that_changes_design", "description": f"User correction changes {name}'s behavior model."},
                {"id": "repair_marker", "description": "A continuity or trust issue was repaired and may matter later."},
            ],
            "do_not_write": ["speculative feelings", "full private transcripts", "runtime PAD/trust JSON"],
        },
        sort_keys=False,
    )


def _recent_activity_md():
    return (
        "# Recent Activity\n\n"
        "No pickup entries have been recorded yet.\n\n"
        "Keep the newest 20 milestone pickup entries here. Archive older entries under `memory/archive/`.\n\n"
        "When work begins, add short entries below with the current state and where to resume.\n\n"
        "<!-- entries -->\n"
    )


def _memory_index_md():
    return (
        "# Memory Index\n\n"
        "This is the default memory router. Read this first when prior context may matter.\n\n"
        "## Core Rule\n\n"
        "- Do not treat this file as the source of project truth. It points to the owner file for each kind of memory.\n\n"
        "## Active Projects\n\n"
        "- No active projects have been recorded yet.\n\n"
        "## Memory Owners\n\n"
        "- Stable identity, voice, and default work rules -> `AGENTS.md` or equivalent platform entry file\n"
        "- Stable user, subject, learner, creator, or relationship facts -> `memory/profile.md`\n"
        "- Long-running domains and workstream routing -> `memory/workstreams.md`\n"
        "- Current project state and decisions -> `memory/projects/<slug>.md`\n"
        "- Session/thread recall and lookup hints -> `memory/session-index.md`\n"
        "- Source lookup and verification paths -> `memory/source-map.md`\n"
        "- Reviewed reusable knowledge -> `knowledge/index.md`\n"
        "- Knowledge source manifests -> `sources/*/manifest.json`\n"
        "- Drafts, durable artifacts, and archived outputs -> `workspace/`\n"
        "- Action queue -> `memory/todos.md`\n"
        "- Collaboration calibration notes -> `memory/collaboration.md`\n"
        "- Dynamic emotion state and compact emotion history -> `.emotion-engine/state.json` when enabled\n\n"
        "## Compatibility Files\n\n"
        "- `memory/pinned.md` is compatibility-only in the MVP; avoid using it as a normal memory layer.\n"
        "- `memory/recent-activity.md` is an old name for session recall; prefer `memory/session-index.md`.\n"
        "- `memory/knowledge_map.md` is an old name for source lookup; prefer `memory/source-map.md`.\n"
        "- `memory/relationship-state.md` is an old name for collaboration calibration; prefer `memory/collaboration.md`.\n"
    )


def _profile_md(character):
    user_name = character["user_name"]
    archetype = _archetype_spec(_character_archetype(character))
    return (
        "# Profile\n\n"
        "This file stores stable profile facts that can matter across workstreams.\n\n"
        "It is global context, but not a dumping ground. Record only facts the user intentionally provides or confirms.\n\n"
        f"## Subject\n\n- Name/reference: {user_name}\n- Agent archetype: {archetype['label']}\n\n"
        "## Stable Facts\n\n"
        "- No profile facts have been recorded yet.\n\n"
        "## Preferences And Constraints\n\n"
        "- No stable preferences or constraints have been recorded yet.\n\n"
        "## Boundaries\n\n"
        "- Do not store secrets, credentials, or highly sensitive private details unless explicitly requested.\n"
        "- Do not store transient mood, inferred psychology, or live Emotion Engine state here.\n"
        "- If a fact only matters inside one domain, put it in the relevant workstream or project file instead.\n"
    )


def _session_index_md():
    return (
        "# Session Index\n\n"
        "This file is a lookup index for prior sessions, not the project state source of truth.\n\n"
        "Use it when the user references \"the previous session\", \"that earlier plan\", \"what we did before\", or a topic that needs thread/session recall.\n\n"
        "Keep the newest 20 session entries here. Archive older entries under `memory/archive/`.\n\n"
        "Empty state line, when there are no entries: No session index entries have been recorded yet.\n\n"
        "<!-- entries -->\n"
    )


def _source_map_md(name):
    return (
        "# Source Map\n\n"
        "This file is a source registry for lookup and verification. It is not a knowledge base and should not duplicate project state.\n\n"
        "Use it when the answer depends on current files, generated artifacts, external docs, or source-of-truth paths.\n\n"
        "## Sources\n\n"
        "- No source mappings have been recorded yet.\n\n"
        "## Knowledge\n\n"
        "- Reviewed knowledge recall index -> `knowledge/index.md`\n"
        "- Knowledge manifest -> `knowledge/manifest.json`\n"
        "- Local source manifest -> `sources/local/manifest.json`\n"
        "- Notion source manifest -> `sources/notion/manifest.json`\n"
        "- Repository source manifest -> `sources/repos/manifest.json`\n"
        "- Web source manifest -> `sources/web/manifest.json`\n"
    )


def _collaboration_md():
    return (
        "# Collaboration\n\n"
        "This file stores learned collaboration calibrations.\n\n"
        "It is not the platform entry file, not project state, and not Emotion Engine runtime state.\n\n"
        "## Current Calibrations\n\n"
        "- No collaboration calibrations have been recorded yet.\n\n"
        "## Write Rules\n\n"
        "- Record only stable collaboration calibrations that reduce future misunderstanding.\n"
        "- Do not store ordinary praise, transient mood, or speculative feelings.\n"
        "- Do not override the current user request with old collaboration notes.\n"
        "- Do not store PAD, trust, or live Emotion Engine runtime JSON here.\n"
    )


def _pinned_md():
    return (
        "# Pinned Memory\n\n"
        "Compatibility file. Pinned memory is not a core MVP memory layer.\n\n"
        "Use `memory/index.md` for routing, the platform entry file for stable behavior, and `memory/projects/*.md` for project state.\n\n"
        "Only place a fact here when it is a tiny cross-project constant that does not belong anywhere else.\n\n"
        "## Pins\n\n"
        "- No pinned memory has been recorded yet.\n"
    )


def _workstreams_md(character):
    workstreams = _initial_workstreams(character)
    archetype = _archetype_spec(_character_archetype(character))
    lines = [
        "# Workstreams",
        "",
        "This file is the domain router for long-running areas of responsibility.",
        "",
        "Use it when a request belongs to an ongoing domain, needs domain-specific context, or may later be promoted into a separate agent.",
        "",
        "## Archetype",
        "",
        f"- Type: {archetype['label']}",
        f"- Scope: {archetype['workstream_scope']}",
        "",
        "## Routing Rules",
        "",
        "- Keep router entries compact; create `memory/workstreams/<slug>.md` when a domain needs detailed state.",
        "- A workstream can contain many projects; a project file should still own project-specific decisions and current state.",
        "- Generated drafts and final outputs belong in `workspace/<domain>/`, with important pointers indexed in `memory/source-map.md`.",
        "- Do not load every workstream by default; load the router first, then the relevant detail file.",
        "",
        "## Promotion To Agent",
        "",
        "- Promote a workstream only when it needs a distinct persona, toolchain, cadence, memory contract, or acceptance criteria.",
        "- Keep the parent agent responsible for routing and final acceptance unless ownership is explicitly moved.",
        "- Use `memory/workstreams/_template.md` when creating a detail file for a mature domain.",
        "",
        "## Current",
        "",
    ]
    if not workstreams:
        lines.append("- No workstreams have been recorded yet.")
    else:
        for index, item in enumerate(workstreams, start=1):
            lines.extend(
                [
                    f"### {index}. {item}",
                    "",
                    f"- Purpose: {item}.",
                    "- Detail file: create one under `memory/workstreams/` when this domain needs denser state.",
                    "- Promotion status: not promoted.",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _initial_workstreams(character):
    explicit = character.get("workstreams")
    if explicit:
        return _dedupe_clean_items(explicit)
    primary_work = character.get("primary_work", [])
    archetype = _character_archetype(character)
    summarized = _summarize_workstreams(primary_work, archetype)
    if summarized:
        return summarized
    return _dedupe_clean_items(primary_work)


def _dedupe_clean_items(items):
    workstreams = []
    for item in items:
        clean = str(item or "").strip().rstrip(".")
        if clean and clean not in workstreams:
            workstreams.append(clean)
    return workstreams


def _summarize_workstreams(primary_work, archetype):
    summaries = []
    for item in primary_work:
        summary = _summarize_workstream_item(str(item or ""), archetype)
        if summary and summary not in summaries:
            summaries.append(summary)
    return summaries


def _summarize_workstream_item(item, archetype):
    text = item.lower()
    if archetype == "companion":
        companion_rules = (
            (("schedule", "routine", "calendar", "time"), "Schedule And Routines"),
            (("day-to-day", "daily", "life problem", "logistics", "errand"), "Daily Logistics"),
            (("clothing", "styling", "shopping", "outfit"), "Style And Shopping"),
            (("travel", "trip", "destination"), "Travel Planning"),
            (("personal advice", "preference", "relationship", "life question"), "Personal Advice"),
        )
        for keywords, label in companion_rules:
            if any(keyword in text for keyword in keywords):
                return label
    clean = item.strip().rstrip(".")
    if not clean:
        return None
    words = [word.strip(" ,;:") for word in clean.split()]
    stopwords = {
        "a",
        "an",
        "and",
        "for",
        "in",
        "into",
        "keep",
        "the",
        "to",
        "with",
        "while",
        "his",
        "her",
        "their",
        "morgan's",
        "user's",
    }
    compact = [word for word in words if word.lower() not in stopwords]
    label = " ".join(compact[:4] or words[:4])
    return label.title() if label else None


def _workstream_template_md():
    return (
        "# Workstream Template\n\n"
        "Copy this file to `memory/workstreams/<slug>.md` when a long-running domain needs detail beyond the router.\n\n"
        "## Summary\n\n"
        "- Keep this section to 7 bullets or fewer.\n\n"
        "## Scope\n\n"
        "- Domain purpose:\n"
        "- In scope:\n"
        "- Out of scope:\n\n"
        "## Current State\n\n"
        "- No workstream state has been recorded yet.\n\n"
        "## Projects\n\n"
        "- Add linked `memory/projects/<slug>.md` files here when the domain contains concrete projects.\n\n"
        "## Cadence And Checks\n\n"
        "- No recurring cadence has been recorded yet.\n\n"
        "## Sources And Workspace\n\n"
        "- Source pointers belong in `memory/source-map.md`.\n"
        "- Drafts and deliverables belong in `workspace/<domain>/`.\n\n"
        "## Agent Promotion\n\n"
        "- Status: not promoted.\n"
        "- Promotion signals: distinct persona, toolchain, cadence, memory contract, or acceptance criteria.\n"
    )


def _project_template_md():
    return (
        "# Project Memory Template\n\n"
        "Copy this file to `memory/projects/<slug>.md` when a project needs denser memory.\n\n"
        "Project files are the canonical source of current project state, decisions, open loops, and project-specific source pointers.\n\n"
        "## Summary\n\n"
        "- Keep this section to 12 lines or fewer.\n\n"
        "## Current State\n\n"
        "- No project state has been recorded yet.\n\n"
        "## Decisions\n\n"
        "- No project decisions have been recorded yet.\n\n"
        "## Open Loops\n\n"
        "- No open loops have been recorded yet.\n\n"
        "## Sources\n\n"
        "- Add source paths or links here when useful.\n"
    )


def _todos_md():
    return (
        "# Todos\n\n"
        "Empty state line, when there are no current todo entries: No current todos have been recorded yet.\n\n"
        "## Current\n\n"
        "- No current todos have been recorded yet.\n\n"
        "## Metadata\n\n"
        "last_briefing_date:\n"
    )


def _knowledge_map_md(name):
    return (
        "# Knowledge Map\n\n"
        "Compatibility file. Prefer `memory/source-map.md`.\n\n"
        f"This file is an optional local index for knowledge sources {name} may load on demand.\n"
        "It is not a knowledge base by itself.\n\n"
        "## Sources\n\n- Source registry: `memory/source-map.md`\n"
    )


def _relationship_state_md():
    return (
        "# Relationship State\n\n"
        "Compatibility file. Prefer `memory/collaboration.md`.\n\n"
        "This file stores work-relevant continuity notes about collaboration style.\n\n"
        "Empty state line, when there are no current summary entries: No relationship continuity notes have been recorded yet.\n\n"
        "## Current Summary\n\n- Collaboration calibrations are stored in `memory/collaboration.md`.\n\n"
        "## Rules\n\n"
        "- Keep notes concrete and useful for future work.\n"
        "- Do not store speculative feelings.\n"
        "- Do not override the user's current request with old compatibility notes.\n"
        "- Do not store live Emotion Engine runtime JSON here.\n"
    )


def _emotion_state_example_json():
    return (
        '{\n'
        '  "_note": "Reserved example only. Live Emotion Engine state belongs in .emotion-engine/state.json when enabled.",\n'
        '  "status": "example_not_live",\n'
        '  "runtime": "not_implemented"\n'
        '}\n'
    )


def _save_context_skill_md(character):
    name = character["name"]
    user_name = character["user_name"]
    text = (
        "# Save Context\n\n"
        f"Use this skill at milestone handoff, session close, or when {user_name} asks {name} to preserve state.\n\n"
        "## Procedure\n\n"
        "1. Identify the current objective, scope, decisions, changed files, verification, and open questions.\n"
        "2. Update the canonical owner file instead of copying the same fact across layers.\n"
        "3. Update `memory/profile.md` only for stable cross-workstream profile facts the user intentionally provides or confirms.\n"
        "4. Update `memory/workstreams.md` for long-running domain routing, and `memory/workstreams/<slug>.md` for dense domain state.\n"
        "5. Update `memory/projects/<slug>.md` for project state, decisions, open loops, and project-specific sources.\n"
        "6. Update `memory/session-index.md` for session/thread lookup entries, not project state summaries.\n"
        "7. Update `memory/source-map.md` for source-of-truth paths, verification routes, workspace artifacts, and lookup pointers.\n"
        "8. Update `memory/todos.md` for action queues and commitments.\n"
        "9. Update `memory/collaboration.md` only for stable collaboration calibrations.\n"
        "10. Put generated drafts, artifacts, and archives under `workspace/<domain>/`; do not copy full deliverables into memory files.\n"
        "11. Update `memory/index.md` only when active projects, memory owners, or routing rules change.\n"
        "12. Report what was saved and what remains unsaved.\n\n"
        "## Write Rules\n\n"
        "- Do not write cloud state in the current local projection.\n"
        "- Do not put current status into `CLAUDE.md` or `AGENTS.md`.\n"
        "- Prefer one compact session-index lookup entry over copying long context.\n"
        "- Keep profile facts explicit and user-confirmed.\n"
        "- Do not store live Emotion Engine runtime JSON in durable memory files.\n"
    )
    mechanism = {
        "metadata": {"locale": character.get("locale")},
        "identity": {"name": name, "user_name": user_name},
    }
    return localize_save_context_markdown(text, mechanism)


def _non_empty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _string_list(value):
    return isinstance(value, list) and bool(value) and all(_non_empty_string(item) for item in value)
