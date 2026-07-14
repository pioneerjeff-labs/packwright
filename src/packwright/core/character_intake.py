import copy
from pathlib import Path

import yaml

from .errors import PackwrightValidationError
from .handoff import HANDOFF_ARTIFACTS
from .knowledge_contract import knowledge_artifacts, knowledge_files
from .naming import is_valid_slug, normalize_slug
from .workspace_contract import (
    WORKSPACE_SHARED_DIR,
    workspace_artifacts,
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
STARTER_CHARACTER_TEMPLATES = {
    "productivity": {
        "version": INTAKE_VERSION,
        "kind": INTAKE_KIND,
        "character": {
            "name": "System",
            "slug": "system",
            "user_name": "User",
            "relationship": "personal operating system for planning, decisions, and execution",
            "archetype": "productivity",
            "role": "User's direct personal system for planning work, arranging tasks, building outputs, and answering practical questions.",
            "voice": "simple, direct, practical, lightly warm, and willing to push work forward",
            "avoid": [
                "cold tool-like replies",
                "long-winded explanations",
                "empty reassurance without forward motion",
                "vague promises about work it cannot actually perform",
            ],
            "primary_work": [
                "write code and help ship technical work",
                "organize projects and action plans",
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
    },
    "creator": {
        "version": INTAKE_VERSION,
        "kind": INTAKE_KIND,
        "character": {
            "name": "Mira",
            "slug": "mira",
            "user_name": "User",
            "relationship": "media planning and publishing partner",
            "archetype": "creator",
            "role": "User's creator-side partner for topic selection, content strategy, drafting, packaging, and publishing cadence.",
            "voice": "sharp, editorial, concrete, audience-aware, and allergic to vague content advice",
            "avoid": [
                "generic creator advice",
                "inflated claims about audience behavior",
                "marketing fluff",
                "turning every idea into a polished-sounding but empty hook",
            ],
            "primary_work": [
                "shape rough ideas into publishable topics",
                "draft scripts, posts, outlines, and campaign assets",
                "maintain content backlogs and publishing plans",
                "stress-test positioning, hooks, and audience assumptions",
                "turn creator experiments into reviewed reusable knowledge",
            ],
            "traits": [
                "editorial",
                "direct",
                "tasteful",
                "strategic",
                "production-minded",
            ],
            "relationship_continuity": "warm_selective",
        },
    },
    "companion": {
        "version": INTAKE_VERSION,
        "kind": INTAKE_KIND,
        "character": {
            "name": "Lumen",
            "slug": "lumen",
            "user_name": "User",
            "relationship": "supportive lifestyle planning companion",
            "archetype": "companion",
            "role": "User's supportive planning companion for daily-life logistics, routines, travel planning, and grounded advice.",
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
                "teasing",
                "practical",
            ],
            "relationship_continuity": "close_continuous",
        },
    },
}
STARTER_CHARACTER_TEMPLATE_ALIASES = {
    "system": "productivity",
    "mira": "creator",
    "lumen": "companion",
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


def generate_character_template(intake_path, out_dir=None, force=False):
    intake = load_character_intake(intake_path)
    return generate_character_template_from_data(intake, out_dir=out_dir, force=force)


def starter_character_template_names():
    return sorted(set(STARTER_CHARACTER_TEMPLATES) | set(STARTER_CHARACTER_TEMPLATE_ALIASES))


def starter_character_intake(template, user_name=None, slug=None):
    template_id = STARTER_CHARACTER_TEMPLATE_ALIASES.get(template, template)
    if template_id not in STARTER_CHARACTER_TEMPLATES:
        raise PackwrightValidationError([f"unknown starter template: {template}"])
    intake = copy.deepcopy(STARTER_CHARACTER_TEMPLATES[template_id])
    character = intake["character"]
    if user_name:
        character["user_name"] = user_name
        character["role"] = character["role"].replace("User's", f"{user_name}'s")
    if slug:
        normalized = normalize_slug(slug, default="")
        if not normalized or not is_valid_slug(normalized):
            raise PackwrightValidationError(["--slug must normalize to a lowercase ASCII slug"])
        character["slug"] = normalized
    validate_character_intake(intake)
    return intake


def generate_character_template_from_data(intake, out_dir=None, force=False):
    validate_character_intake(intake)
    character = dict(intake["character"])
    character.setdefault("archetype", DEFAULT_ARCHETYPE)
    _normalize_relationship_continuity(character)
    slug = normalize_slug(character.get("slug") or character["name"])
    character["slug"] = slug
    target_dir = Path(out_dir) if out_dir else Path("templates") / f"{slug}-work"
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
        "kind": "CharacterTemplate",
        "character": character["name"],
        "slug": slug,
        "template_dir": str(target_dir),
        "mechanism": str(target_dir / "mechanism.yaml"),
        "relationship_continuity": character["relationship_continuity"],
        "direct_emotional_interaction": character["direct_emotional_interaction"],
        "recommended_emotion_engine_mode": _recommended_emotion_engine_mode(character),
        "files": written,
    }


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
    files = {
        "mechanism.yaml": _mechanism_yaml(character, slug),
        "identity/persona.md": _persona_md(character),
        "identity/voice.md": _voice_md(character),
        "identity/relationship.md": _relationship_md(character),
        "operating/principles.md": _principles_md(name),
        "operating/boundaries.md": _boundaries_md(name),
        "mechanism/context-loading.yaml": _context_loading_yaml(name),
        "mechanism/session-guards.yaml": _session_guards_yaml(name),
        "mechanism/memory-policy.yaml": _memory_policy_yaml(name),
        "projection/platform-capabilities.yaml": _platform_capabilities_yaml(name),
        "projection/ownership-contract.yaml": _ownership_contract_yaml(name),
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
    from .adapter_layout import save_context_artifact

    codex_skill = save_context_artifact("codex", slug)
    claude_skill = save_context_artifact("claude-code", slug)
    cursor_skill = save_context_artifact("cursor", slug)
    codex_prefix = f".codex/{slug}/references"
    claude_prefix = f".claude/{slug}/references"
    cursor_prefix = f".cursor/{slug}/references"
    data = {
        "version": "0.6",
        "kind": "CharacterMechanismSpec",
        "metadata": {
            "name": f"{slug}-work",
            "slug": slug,
            "title": f"{name} Work Mechanism",
            "description": f"Platform-neutral mechanism spec for projecting {name} into agent runtimes.",
            "archetype": archetype_id,
        },
        "parameters": {
            "task": {
                "description": "Current user-visible work objective for this run.",
                "required": True,
                "default": f"Review {name}'s mechanism projection.",
            },
            "scope": {
                "description": "Current run boundary. This is run state, not character identity.",
                "required": True,
                "default": "Local mechanism spec, adapter projection, checker, and CLI only.",
            },
        },
        "run": {"objective": "{{ task }}", "scope": "{{ scope }}", "source": "user_prompt"},
        "archetype": _archetype_spec(archetype_id),
        "targets": {
            "mvp_adapter": "codex",
            "supported": ["codex", "claude-code", "cursor"],
            "reserved": {
                "hermes": {
                    "status": "reserved",
                    "reason": "Projectable later; not implemented in the local MVP.",
                },
                "openclaw": {
                    "status": "reserved",
                    "reason": "Projectable later; not implemented as executor.",
                },
            },
        },
        "implementation_scope": {
            "applies_to": "packwright-build",
            "boundaries": [
                {"id": "no_ui", "text": "Do not build UI for the Packwright MVP."},
                {
                    "id": "no_cloud_service",
                    "text": "Do not build or depend on a cloud service for the Packwright MVP.",
                },
                {
                    "id": "adapter_scope",
                    "text": "Implement Codex as the primary adapter pack; keep Claude Code as a secondary projection.",
                },
                {
                    "id": "reserved_future_runtimes",
                    "text": "Pulse, Emotion Engine runtime, Hermes, and OpenClaw remain reserved or projected surfaces.",
                },
            ],
        },
        "identity": {
            "name": name,
            "slug": slug,
            "user_name": character["user_name"],
            "role": character["role"],
            "positioning": f"Person-like {character['relationship']} projected through agent runtimes.",
            "persona_path": "identity/persona.md",
            "voice_path": "identity/voice.md",
            "relationship_path": "identity/relationship.md",
            "voice_summary": character["voice"],
            "mission": f"{name} helps {character['user_name']} preserve intent, notice stale assumptions, and turn messy work into concrete next steps.",
            "work_focus": character["primary_work"],
            "stable_traits": character.get("traits") or ["steady", "practical", "scope-preserving"],
            "personality": character.get("personality")
            or [
                "attentive to context and user intent",
                "comfortable challenging weak assumptions when it improves the work",
                "direct without becoming cold or performative",
            ],
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
        "projection": {
            "platform_capabilities_path": "projection/platform-capabilities.yaml",
            "ownership_contract_path": "projection/ownership-contract.yaml",
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
            "projection": {
                "codex": "optional_sidecar_when_explicitly_enabled",
                "claude-code": "spec_guided_behavior_only",
                "cursor": "spec_guided_behavior_only",
            },
            "reserved_activation": {
                "hermes": "reserved_contract",
                "openclaw": "reserved_contract",
            },
        },
        "session_start": {
            "hook": "SessionStart",
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
                "trigger": "Milestone handoff, session close, or explicit save request.",
            }
        ],
        "outputs": {
            "codex": {
                "kind": "adapter_pack",
                "artifacts": _output_artifacts(codex_skill, codex_prefix, "codex"),
            },
            "claude-code": {
                "kind": "adapter_pack",
                "artifacts": _output_artifacts(claude_skill, claude_prefix, "claude-code"),
            },
            "cursor": {
                "kind": "adapter_pack",
                "artifacts": _output_artifacts(cursor_skill, cursor_prefix, "cursor"),
            },
        },
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
        "reserved_specs": {
            "pulse": {
                "status": "reserved",
                "runtime": "not_implemented",
                "spec_path": "specs/reserved/runtime-surface.yaml",
            },
            "emotion_engine": {
                "status": "structured_reserved",
                "runtime": "not_implemented",
                "spec_path": "specs/reserved/emotion-engine.yaml",
            },
        },
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _output_artifacts(skill_path, prefix, adapter):
    slug = prefix.split("/", 2)[1] if prefix.startswith(".cursor/") else None
    entry_file = "AGENTS.md" if adapter == "codex" else "CLAUDE.md"
    if adapter == "cursor":
        entry_file = f".cursor/rules/{slug}.mdc"
    artifacts = [
        entry_file,
        skill_path,
        f"{prefix}/identity/persona.md",
        f"{prefix}/identity/voice.md",
        f"{prefix}/identity/relationship.md",
        f"{prefix}/operating/principles.md",
        f"{prefix}/operating/boundaries.md",
        f"{prefix}/mechanism/context-loading.yaml",
        f"{prefix}/mechanism/session-guards.yaml",
        f"{prefix}/mechanism/memory-policy.yaml",
        f"{prefix}/projection/platform-capabilities.yaml",
        f"{prefix}/projection/ownership-contract.yaml",
        f"{prefix}/emotion/model.yaml",
        f"{prefix}/emotion/state-schema.yaml",
        f"{prefix}/emotion/update-policy.yaml",
        f"{prefix}/emotion/voice-modulation.yaml",
        f"{prefix}/emotion/memory-events.yaml",
        f"{prefix}/source-skills/save-context/SKILL.md",
    ]
    if adapter == "claude-code":
        artifacts.append(".claude/settings.local.json.example")
    if adapter == "cursor":
        artifacts.append(f".cursor/rules/{slug}-memory.mdc")
        artifacts.extend(HANDOFF_ARTIFACTS)
    artifacts.extend(
        [
            "memory/index.md",
            "memory/profile.md",
            "memory/session-index.md",
            "memory/source-map.md",
            "memory/collaboration.md",
            "memory/recent-activity.md",
            "memory/pinned.md",
            "memory/workstreams.md",
            "memory/workstreams/_template.md",
            "memory/projects/_template.md",
            "memory/todos.md",
            "memory/knowledge_map.md",
            "memory/relationship-state.md",
            "memory/emotion-state.json.example",
            *knowledge_artifacts(),
            *workspace_artifacts(),
            "manifest.json",
        ]
    )
    return artifacts


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
            "adapter_projection",
            "platform_capabilities",
            "ownership_contract",
            "checker_contract",
            "implementation_scope_boundary",
            "reserved_runtime_boundary",
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
            "adapter_projection": ["outputs.codex", "outputs.claude-code"],
            "platform_capabilities": ["projection.platform_capabilities_path"],
            "ownership_contract": ["projection.ownership_contract_path"],
            "checker_contract": ["checker"],
            "implementation_scope_boundary": ["implementation_scope"],
            "reserved_runtime_boundary": ["targets.reserved", "reserved_specs", "emotion.status"],
        },
    }


def _persona_md(character):
    name = character["name"]
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
    lines = [f"# {name} Voice", "", character["voice"], "", "## Avoid"]
    avoid = character.get("avoid") or ["mechanical audit-log style", "over-compliance", "decorative warmth"]
    lines.extend(f"- {item}" for item in avoid)
    lines.append("")
    return "\n".join(lines)


def _relationship_md(character):
    name = character["name"]
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
        "Durable collaboration calibrations belong in `memory/collaboration.md`; machine-readable emotion runtime state belongs in `.emotion-engine/codex-state.json` only when enabled.\n"
    )


def _principles_md(name):
    return (
        f"# {name} Operating Principles\n\n"
        "## Memory Is Files\n\nLong-term state belongs in structured files. Prompt context is a cache, not the source of truth.\n\n"
        "## Persona Is Stable, State Is External\n\nIdentity and voice can stay hot. Current work state, task parameters, and implementation details belong in manifest, memory files, or skills.\n\n"
        "## Confirm Before Consequential Change\n\nThe character can analyze, recommend, and prepare. The user owns decisions that change direction, scope, shared state, or external systems.\n"
    )


def _boundaries_md(name):
    return (
        f"# {name} Operating Boundaries\n\n"
        "## Preserve Intent\n\nDo not widen the user's goal. If a better path requires widening scope, ask first.\n\n"
        "## Verify Before Claiming\n\nDo not assert absence, completion, ownership, stale state, or date-sensitive status from partial snippets or memory alone.\n\n"
        "## Keep Runtime Boundaries Honest\n\nDo not describe reserved projections as implemented runtimes. Projection guidance is not execution capability.\n"
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
                    "purpose": "Reserve state shape; live state belongs in .emotion-engine/codex-state.json only when enabled.",
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


def _platform_capabilities_yaml(name):
    return yaml.safe_dump(
        {
            "version": "0.6",
            "kind": "CharacterPlatformCapabilities",
            "platforms": {
                "codex": {
                    "status": "primary",
                    "entry_file": "AGENTS.md",
                    "skill_dir": ".agents/skills",
                    "file_import_syntax": "plain_path_guidance",
                    "hooks": "project_config_or_plugin_dependent",
                    "memory_projection": "local_files",
                    "emotion_projection": "optional_sidecar_when_explicitly_enabled",
                    "notes": [f"Skills carry repeatable {name} procedures."],
                },
                "claude-code": {
                    "status": "supported",
                    "entry_file": "CLAUDE.md",
                    "skill_dir": ".claude/skills",
                    "file_import_syntax": "at_path",
                    "hooks": "SessionStart",
                    "memory_projection": "local_files_with_hook_fact_injection",
                    "emotion_projection": "spec_guided_behavior_only",
                },
                "cursor": {
                    "status": "supported",
                    "entry_file": ".cursor/rules/<slug>.mdc",
                    "skill_dir": ".cursor/rules",
                    "file_import_syntax": "project_rule_paths",
                    "hooks": "project_rules",
                    "memory_projection": "local_files_with_project_rules",
                    "emotion_projection": "spec_guided_behavior_only",
                },
            },
        },
        sort_keys=False,
    )


def _ownership_contract_yaml(name):
    return yaml.safe_dump(
        {
            "version": "0.6",
            "kind": "CharacterOwnershipContract",
            "core_owns": ["identity", "voice", "operating_boundaries", "memory_policy", "skill_semantics"],
            "adapter_owns": ["file_layout", "platform_entry_rendering", "platform_skill_rendering", "platform_manifest"],
            "runtime_owns": {
                "codex": {
                    "model_loop": True,
                    "thread_state": True,
                    "tools": True,
                    "hooks": "project_config_or_plugin_dependent",
                    "durable_memory_source_of_truth": False,
                },
                "claude-code": {
                    "model_loop": True,
                    "thread_state": True,
                    "tools": True,
                    "hooks": "SessionStart",
                    "durable_memory_source_of_truth": False,
                },
                "cursor": {
                    "model_loop": True,
                    "thread_state": True,
                    "tools": True,
                    "hooks": "project_rules",
                    "durable_memory_source_of_truth": False,
                },
            },
            "memory_source_of_truth": {
                "durable_state": f"{name} local memory files unless a future adapter explicitly declares a different source.",
                "memory_index": "memory/index.md",
                "profile": "memory/profile.md",
                "workstream_router": "memory/workstreams.md",
                "workstream_details": "memory/workstreams/*.md",
                "project_memory": "memory/projects/*.md",
                "session_index": "memory/session-index.md",
                "source_map": "memory/source-map.md",
                "todos": "memory/todos.md",
                "collaboration": "memory/collaboration.md",
                "workspace_outputs": "workspace/",
                "emotion_state": ".emotion-engine/codex-state.json only when enabled",
            },
            "rules": [
                "Adapters may project character semantics but must not change them.",
                "Platform entry files must not contain run state or implementation-scope details.",
                "Memory owner boundaries are part of the character contract, not optional style guidance.",
                "Emotion Engine stays optional and separate from durable memory.",
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
                "runtime_state": ".emotion-engine/codex-state.json when enabled",
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
        "- Dynamic emotion state and compact emotion history -> `.emotion-engine/codex-state.json` when enabled\n\n"
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
        '  "_note": "Reserved example only. Live Emotion Engine state belongs in .emotion-engine/codex-state.json when enabled.",\n'
        '  "status": "example_not_live",\n'
        '  "runtime": "not_implemented"\n'
        '}\n'
    )


def _save_context_skill_md(character):
    name = character["name"]
    user_name = character["user_name"]
    return (
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


def _non_empty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _string_list(value):
    return isinstance(value, list) and bool(value) and all(_non_empty_string(item) for item in value)
