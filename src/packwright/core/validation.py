from collections.abc import Mapping, Sequence
from .adapter_layout import supported_adapters
from .errors import PackwrightValidationError
from .handoff import HANDOFF_ARTIFACTS
from .knowledge_contract import knowledge_artifacts
from .naming import character_slug, is_valid_slug, normalize_slug, save_context_skill_path
from .path_safety import resolve_mechanism_file
from .skill_projection import SKILL_CAPABILITIES
from .workspace_contract import (
    WORKSPACE_DOMAIN_TEMPLATE_DIR,
    WORKSPACE_INDEX_OWNER,
    WORKSPACE_LAYOUT,
    WORKSPACE_LIFECYCLE_DIRS,
    WORKSPACE_ROOT,
    WORKSPACE_SHARED_DIR,
    workspace_artifacts,
)


SUPPORTED_KINDS = {"AtlasMechanismSpec", "CharacterMechanismSpec"}
SUPPORTED_VERSIONS = {"0.5", "0.6", "0.7", "0.8"}
MVP_ADAPTER = "codex"
SUPPORTED_ADAPTERS = set(supported_adapters())
RUNTIME_NEUTRAL_VERSION = "0.8"


def validate_mechanism(data):
    """Validate the platform-neutral character mechanism spec."""
    issues = []
    if not isinstance(data, Mapping):
        raise PackwrightValidationError(["mechanism root must be a mapping"])

    _validate_top_level(data, issues)
    _validate_metadata(data.get("metadata"), issues)
    _validate_parameters(data.get("parameters", {}), issues)
    _validate_run(data.get("run"), issues)
    _validate_archetype(data.get("archetype"), issues)
    if "targets" in data:
        _validate_targets(data.get("targets"), issues)
    if "implementation_scope" in data:
        _validate_implementation_scope(data.get("implementation_scope"), issues)
    _validate_identity(data, issues)
    _validate_operating(data, issues)
    _validate_mechanism_refs(data, issues)
    if "projection" in data:
        _validate_projection(data, issues)
    _validate_emotion(data, issues)
    if str(data.get("version")) == RUNTIME_NEUTRAL_VERSION:
        _validate_automations(data, issues)
    else:
        _validate_session_start(data.get("session_start"), issues)
    _validate_memory(data, issues)
    _validate_workspace(data.get("workspace"), issues)
    _validate_skills(data, issues)
    if "outputs" in data:
        _validate_outputs(data, issues)
    _validate_checker(data.get("checker"), issues)
    _validate_coverage(data, issues)
    if "reserved_specs" in data:
        _validate_reserved_specs(data, issues)

    if issues:
        raise PackwrightValidationError(issues)
    return data


def path_exists(data, dotted_path):
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return False
    return True


def file_exists(data, path):
    try:
        resolve_mechanism_file(data, path)
    except PackwrightValidationError:
        return False
    return True


def _validate_top_level(data, issues):
    required = [
        "version",
        "kind",
        "metadata",
        "parameters",
        "run",
        "archetype",
        "identity",
        "operating",
        "mechanism",
        "emotion",
        "memory",
        "workspace",
        "skills",
        "checker",
        "coverage",
    ]
    if str(data.get("version")) == RUNTIME_NEUTRAL_VERSION:
        required.append("automations")
    else:
        required.append("session_start")
    if str(data.get("version")) in {"0.5", "0.6"}:
        required.extend(("targets", "implementation_scope", "projection", "outputs", "reserved_specs"))
    for key in required:
        if key not in data:
            issues.append(f"missing top-level key: {key}")

    if data.get("kind") not in SUPPORTED_KINDS:
        issues.append(f"kind must be one of {sorted(SUPPORTED_KINDS)}")
    if str(data.get("version")) not in SUPPORTED_VERSIONS:
        issues.append(f"version must be one of {sorted(SUPPORTED_VERSIONS)}")


def _validate_metadata(metadata, issues):
    if not _is_mapping(metadata):
        issues.append("metadata must be a mapping")
        return
    for key in ("name", "title", "description"):
        if not _non_empty_string(metadata.get(key)):
            issues.append(f"metadata.{key} must be a non-empty string")
    if "archetype" in metadata and not _non_empty_string(metadata.get("archetype")):
        issues.append("metadata.archetype must be a non-empty string when provided")
    _validate_optional_slug(metadata, "metadata.slug", issues)


def _validate_parameters(parameters, issues):
    if not _is_mapping(parameters):
        issues.append("parameters must be a mapping")
        return
    for name, spec in parameters.items():
        if not _non_empty_string(name):
            issues.append("parameter keys must be non-empty strings")
            continue
        if not _is_mapping(spec):
            issues.append(f"parameters.{name} must be a mapping")
            continue
        if "required" in spec and not isinstance(spec["required"], bool):
            issues.append(f"parameters.{name}.required must be a boolean")
        if "description" in spec and not _non_empty_string(spec["description"]):
            issues.append(f"parameters.{name}.description must be a non-empty string")


def _validate_run(run, issues):
    if not _is_mapping(run):
        issues.append("run must be a mapping")
        return
    for key in ("objective", "scope", "source"):
        if not _non_empty_string(run.get(key)):
            issues.append(f"run.{key} must be a non-empty string")


def _validate_archetype(archetype, issues):
    if not _is_mapping(archetype):
        issues.append("archetype must be a mapping")
        return
    for key in ("id", "label", "description", "profile_scope", "workstream_scope"):
        if not _non_empty_string(archetype.get(key)):
            issues.append(f"archetype.{key} must be a non-empty string")
    promotion = archetype.get("promotion")
    if not _is_mapping(promotion):
        issues.append("archetype.promotion must be a mapping")
        return
    for key in ("from", "to", "rule"):
        if not _non_empty_string(promotion.get(key)):
            issues.append(f"archetype.promotion.{key} must be a non-empty string")
    if not _is_non_empty_list(promotion.get("signals")):
        issues.append("archetype.promotion.signals must be a non-empty list")


def _validate_targets(targets, issues):
    if not _is_mapping(targets):
        issues.append("targets must be a mapping")
        return
    if targets.get("mvp_adapter") != MVP_ADAPTER:
        issues.append(f"targets.mvp_adapter must be {MVP_ADAPTER}")
    supported = targets.get("supported")
    if not _is_non_empty_list(supported):
        issues.append("targets.supported must be a non-empty legacy adapter list")
    elif any(not _non_empty_string(adapter) for adapter in supported):
        issues.append("targets.supported entries must be non-empty strings")
    reserved = targets.get("reserved", {})
    if not _is_mapping(reserved):
        issues.append("targets.reserved must be a mapping")
        return
    for name, spec in reserved.items():
        if not _is_mapping(spec):
            issues.append(f"targets.reserved.{name} must be a mapping")
            continue
        if spec.get("status") != "reserved":
            issues.append(f"targets.reserved.{name}.status must be reserved")
        if not _non_empty_string(spec.get("reason")):
            issues.append(f"targets.reserved.{name}.reason must be a non-empty string")


def _validate_implementation_scope(implementation_scope, issues):
    if not _is_mapping(implementation_scope):
        issues.append("implementation_scope must be a mapping")
        return
    if not _non_empty_string(implementation_scope.get("applies_to")):
        issues.append("implementation_scope.applies_to must be a non-empty string")
    boundaries = implementation_scope.get("boundaries")
    if not _is_non_empty_list(boundaries):
        issues.append("implementation_scope.boundaries must be a non-empty list")
        return
    _validate_id_list(boundaries, "implementation_scope.boundaries", issues)
    for index, boundary in enumerate(_as_list(boundaries)):
        if _is_mapping(boundary) and not _non_empty_string(boundary.get("text")):
            issues.append(f"implementation_scope.boundaries[{index}].text must be a non-empty string")


def _validate_identity(data, issues):
    identity = data.get("identity")
    if not _is_mapping(identity):
        issues.append("identity must be a mapping")
        return
    for key in ("name", "role", "positioning", "persona_path", "voice_path", "relationship_path"):
        if not _non_empty_string(identity.get(key)):
            issues.append(f"identity.{key} must be a non-empty string")
    for key in ("user_name", "voice_summary", "mission"):
        if key in identity and not _non_empty_string(identity.get(key)):
            issues.append(f"identity.{key} must be a non-empty string when provided")
    _validate_optional_slug(identity, "identity.slug", issues)
    if not _is_non_empty_list(identity.get("stable_traits")):
        issues.append("identity.stable_traits must be a non-empty list")
    if not _is_non_empty_list(identity.get("work_focus")):
        issues.append("identity.work_focus must be a non-empty list")
    if not _is_non_empty_list(identity.get("personality")):
        issues.append("identity.personality must be a non-empty list")
    for key in ("persona_path", "voice_path", "relationship_path"):
        _validate_file_ref(data, identity.get(key), f"identity.{key}", issues)


def _validate_operating(data, issues):
    operating = data.get("operating")
    if not _is_mapping(operating):
        issues.append("operating must be a mapping")
        return
    for key in ("principles_path", "boundaries_path"):
        if not _non_empty_string(operating.get(key)):
            issues.append(f"operating.{key} must be a non-empty string")
        else:
            _validate_file_ref(data, operating.get(key), f"operating.{key}", issues)
    if not _is_non_empty_list(operating.get("hot_rules")):
        issues.append("operating.hot_rules must be a non-empty list")


def _validate_mechanism_refs(data, issues):
    mechanism = data.get("mechanism")
    if not _is_mapping(mechanism):
        issues.append("mechanism must be a mapping")
        return
    for key in ("context_loading_path", "session_guards_path", "memory_policy_path"):
        if not _non_empty_string(mechanism.get(key)):
            issues.append(f"mechanism.{key} must be a non-empty string")
        else:
            _validate_file_ref(data, mechanism.get(key), f"mechanism.{key}", issues)


def _validate_projection(data, issues):
    projection = data.get("projection")
    if not _is_mapping(projection):
        issues.append("projection must be a mapping")
        return
    for key in ("platform_capabilities_path", "ownership_contract_path"):
        if not _non_empty_string(projection.get(key)):
            issues.append(f"projection.{key} must be a non-empty string")
        else:
            _validate_file_ref(data, projection.get(key), f"projection.{key}", issues)


def _validate_emotion(data, issues):
    emotion = data.get("emotion")
    if not _is_mapping(emotion):
        issues.append("emotion must be a mapping")
        return
    if emotion.get("status") != "structured_reserved":
        issues.append("emotion.status must be structured_reserved")
    if emotion.get("runtime") != "not_implemented":
        issues.append("emotion.runtime must be not_implemented")
    if emotion.get("default_mode") != "light":
        issues.append("emotion.default_mode must be light")
    recommended = emotion.get("recommended_mode")
    if recommended is not None and recommended not in {"light", "always", "paused"}:
        issues.append("emotion.recommended_mode must be light, always, or paused when provided")
    modes = emotion.get("user_visible_modes")
    if modes is not None and modes != ["light", "always", "paused"]:
        issues.append("emotion.user_visible_modes must be [light, always, paused]")
    overhead = emotion.get("estimated_overhead", {})
    if overhead is not None:
        if not _is_mapping(overhead):
            issues.append("emotion.estimated_overhead must be a mapping when provided")
        else:
            for mode in ("light", "always", "paused"):
                if mode not in overhead or not _non_empty_string(overhead.get(mode)):
                    issues.append(f"emotion.estimated_overhead.{mode} must be a non-empty string")
    if not _non_empty_string(emotion.get("role")):
        issues.append("emotion.role must be a non-empty string")
    if "direct_interaction" in emotion and emotion.get("direct_interaction") not in {
        "work_only",
        "some_direct_emotional_interaction",
        "decide_later",
    }:
        issues.append("emotion.direct_interaction must be work_only, some_direct_emotional_interaction, or decide_later")
    if "relationship_continuity" in emotion and emotion.get("relationship_continuity") not in {
        "task_only",
        "warm_selective",
        "close_continuous",
    }:
        issues.append("emotion.relationship_continuity must be task_only, warm_selective, or close_continuous")
    for key in (
        "model_path",
        "state_schema_path",
        "update_policy_path",
        "voice_modulation_path",
        "memory_events_path",
    ):
        if not _non_empty_string(emotion.get(key)):
            issues.append(f"emotion.{key} must be a non-empty string")
        else:
            _validate_file_ref(data, emotion.get(key), f"emotion.{key}", issues)
    projection = emotion.get("projection")
    if projection is not None:
        if not _is_mapping(projection):
            issues.append("emotion.projection must be a mapping")
            return
        allowed = {
            "codex": {"optional_sidecar_when_explicitly_enabled", "spec_guided_behavior_only"},
            "claude-code": {"spec_guided_behavior_only"},
            "cursor": {"spec_guided_behavior_only"},
        }
        for adapter, value in projection.items():
            if adapter in allowed and value not in allowed[adapter]:
                issues.append(f"emotion.projection.{adapter} must be one of {sorted(allowed[adapter])}")


def _validate_session_start(session_start, issues):
    if not _is_mapping(session_start):
        issues.append("session_start must be a mapping")
        return
    event = session_start.get("event")
    hook = session_start.get("hook")
    if event is not None:
        if event != "session_start":
            issues.append("session_start.event must be session_start")
    elif hook != "SessionStart":
        issues.append("session_start must declare event: session_start")
    if session_start.get("injects_facts_only") is not True:
        issues.append("session_start.injects_facts_only must be true")
    facts = session_start.get("facts")
    if not _is_non_empty_list(facts):
        issues.append("session_start.facts must be a non-empty list")
        return
    _validate_id_list(facts, "session_start.facts", issues)
    for index, fact in enumerate(_as_list(facts)):
        if _is_mapping(fact) and not _non_empty_string(fact.get("source")):
            issues.append(f"session_start.facts[{index}].source must be a non-empty string")


def _validate_automations(data, issues):
    automations = data.get("automations")
    if not _is_non_empty_list(automations):
        issues.append("automations must be a non-empty list")
        return
    _validate_id_list(automations, "automations", issues)
    for index, automation in enumerate(_as_list(automations)):
        prefix = f"automations[{index}]"
        if not _is_mapping(automation):
            continue
        if automation.get("scope") != "local":
            issues.append(f"{prefix}.scope must be local")
        if automation.get("event") not in {"session_start", "user_prompt"}:
            issues.append(f"{prefix}.event must be session_start or user_prompt")
        if automation.get("effect") != "add_context":
            issues.append(f"{prefix}.effect must be add_context")
        budget = automation.get("budget_bytes")
        if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
            issues.append(f"{prefix}.budget_bytes must be a positive integer")
        producer = automation.get("producer")
        if not _is_mapping(producer):
            issues.append(f"{prefix}.producer must be a mapping")
            continue
        kind = producer.get("kind")
        if kind == "memory_view":
            source = producer.get("source")
            if not _non_empty_string(source):
                issues.append(f"{prefix}.producer.source must be a non-empty string")
            else:
                _validate_file_ref(data, source, f"{prefix}.producer.source", issues)
            select = producer.get("select")
            if not _is_mapping(select):
                issues.append(f"{prefix}.producer.select must be a mapping")
            else:
                max_bytes = select.get("max_bytes")
                if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
                    issues.append(f"{prefix}.producer.select.max_bytes must be a positive integer")
                for key in ("section", "until_section"):
                    if key in select and not _non_empty_string(select.get(key)):
                        issues.append(f"{prefix}.producer.select.{key} must be a non-empty string")
                latest = select.get("bullets_latest")
                if latest is not None and (
                    not isinstance(latest, int) or isinstance(latest, bool) or latest <= 0
                ):
                    issues.append(f"{prefix}.producer.select.bullets_latest must be a positive integer")
        elif kind == "freshness_facts":
            facts = producer.get("facts")
            if not _is_non_empty_list(facts):
                issues.append(f"{prefix}.producer.facts must be a non-empty list")
            else:
                for fact_index, fact in enumerate(_as_list(facts)):
                    fact_prefix = f"{prefix}.producer.facts[{fact_index}]"
                    if not _is_mapping(fact):
                        issues.append(f"{fact_prefix} must be a mapping")
                        continue
                    if not _non_empty_string(fact.get("field")):
                        issues.append(f"{fact_prefix}.field must be a non-empty string")
                    if fact.get("source") not in {"system_date", "system_datetime"}:
                        issues.append(f"{fact_prefix}.source must be system_date or system_datetime")
        elif kind == "relocation_guard":
            baseline = producer.get("baseline_path")
            if baseline != ".packwright/baseline-path":
                issues.append(f"{prefix}.producer.baseline_path must be .packwright/baseline-path")
        else:
            issues.append(
                f"{prefix}.producer.kind must be memory_view, freshness_facts, or relocation_guard"
            )


def _validate_memory(data, issues):
    memory = data.get("memory")
    if not _is_mapping(memory):
        issues.append("memory must be a mapping")
        return
    local_files = memory.get("local_files")
    if not _is_non_empty_list(local_files):
        issues.append("memory.local_files must be a non-empty list")
    else:
        _validate_id_list(local_files, "memory.local_files", issues)
        ids = set()
        for index, item in enumerate(_as_list(local_files)):
            if not _is_mapping(item):
                continue
            ids.add(item.get("id"))
            for key in ("path", "track"):
                if not _non_empty_string(item.get(key)):
                    issues.append(f"memory.local_files[{index}].{key} must be a non-empty string")
            _validate_file_ref(data, item.get("path"), f"memory.local_files[{index}].path", issues)
        for required in (
            "memory_index",
            "profile",
            "session_index",
            "source_map",
            "collaboration",
            "pinned_memory",
            "workstreams",
            "workstream_template",
            "todos",
            "project_template",
            "relationship_state",
        ):
            if required not in ids:
                issues.append(f"memory.local_files must include {required}")
    if not _is_non_empty_list(memory.get("durable_dirs")):
        issues.append("memory.durable_dirs must be a non-empty list")
    _validate_memory_limits(memory.get("limits"), issues)
    if not _non_empty_string(memory.get("scratch_dir")):
        issues.append("memory.scratch_dir must be a non-empty string")


def _validate_memory_limits(limits, issues):
    if not _is_mapping(limits):
        issues.append("memory.limits must be a mapping")
        return
    expected = {
        "pinned_items": 20,
        "recent_activity_hot_entries": 20,
        "session_index_entries": 20,
        "workstream_summary_bullets": 7,
        "project_summary_lines": 12,
        "workspace_artifact_index_entries": 50,
    }
    for key, value in expected.items():
        if limits.get(key) != value:
            issues.append(f"memory.limits.{key} must be {value}")


def _validate_workspace(workspace, issues):
    if not _is_mapping(workspace):
        issues.append("workspace must be a mapping")
        return
    for key in ("root", "layout", "domain_template_dir", "shared_dir", "index_owner"):
        if not _non_empty_string(workspace.get(key)):
            issues.append(f"workspace.{key} must be a non-empty string")
    if workspace.get("root") != WORKSPACE_ROOT:
        issues.append(f"workspace.root must be {WORKSPACE_ROOT}")
    if workspace.get("layout") != WORKSPACE_LAYOUT:
        issues.append(f"workspace.layout must be {WORKSPACE_LAYOUT}")
    if workspace.get("domain_template_dir") != WORKSPACE_DOMAIN_TEMPLATE_DIR:
        issues.append(f"workspace.domain_template_dir must be {WORKSPACE_DOMAIN_TEMPLATE_DIR}")
    if workspace.get("shared_dir") != WORKSPACE_SHARED_DIR:
        issues.append(f"workspace.shared_dir must be {WORKSPACE_SHARED_DIR}")
    if workspace.get("index_owner") != WORKSPACE_INDEX_OWNER:
        issues.append(f"workspace.index_owner must be {WORKSPACE_INDEX_OWNER}")
    if workspace.get("lifecycle_dirs") != list(WORKSPACE_LIFECYCLE_DIRS):
        expected = ", ".join(WORKSPACE_LIFECYCLE_DIRS)
        issues.append(f"workspace.lifecycle_dirs must be [{expected}]")
    if not _is_non_empty_list(workspace.get("rules")):
        issues.append("workspace.rules must be a non-empty list")


def _validate_skills(data, issues):
    skills = data.get("skills")
    if not _is_non_empty_list(skills):
        issues.append("skills must be a non-empty list")
        return
    _validate_id_list(skills, "skills", issues)
    if not any(isinstance(skill, Mapping) and skill.get("id") == "save-context" for skill in skills):
        issues.append("skills must include the required save-context skill")
    for index, skill in enumerate(_as_list(skills)):
        if not _is_mapping(skill):
            continue
        if "adapters" in skill:
            issues.append(
                f"skills[{index}].adapters is not allowed; declare semantic capabilities and let the adapter registry project them"
            )
        for key in ("path", "layer", "trigger"):
            if not _non_empty_string(skill.get(key)):
                issues.append(f"skills[{index}].{key} must be a non-empty string")
        _validate_file_ref(data, skill.get("path"), f"skills[{index}].path", issues)
        skill_id = skill.get("id")
        if _non_empty_string(skill_id) and not is_valid_slug(skill_id):
            issues.append(f"skills[{index}].id must be a lowercase ASCII slug")
        capabilities = skill.get("capabilities", [])
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) and item in SKILL_CAPABILITIES for item in capabilities
        ):
            issues.append(
                f"skills[{index}].capabilities must contain only {sorted(SKILL_CAPABILITIES)}"
            )
        elif len(capabilities) != len(set(capabilities)):
            issues.append(f"skills[{index}].capabilities must not contain duplicates")
        elif skill_id == "save-context" and capabilities:
            issues.append(
                f"skills[{index}].capabilities must be empty because save-context is a mandatory artifact"
            )


def _validate_outputs(data, issues):
    outputs = data.get("outputs")
    if not _is_mapping(outputs):
        issues.append("outputs must be a mapping")
        return
    for adapter, config in outputs.items():
        if adapter not in SUPPORTED_ADAPTERS:
            continue
        if not _is_mapping(config):
            issues.append(f"outputs.{adapter} must be a mapping")
            continue
        if config.get("kind") != "adapter_pack":
            issues.append(f"outputs.{adapter}.kind must be adapter_pack")
        artifacts = config.get("artifacts")
        if not _is_non_empty_list(artifacts):
            issues.append(f"outputs.{adapter}.artifacts must be a non-empty list")
            continue
        skill_path = save_context_skill_path(data, adapter)
        if adapter == "codex":
            required = (
                "AGENTS.md",
                skill_path,
                "manifest.json",
                "memory/index.md",
                "memory/profile.md",
                "memory/session-index.md",
                "memory/source-map.md",
                "memory/collaboration.md",
                "memory/pinned.md",
                "memory/workstreams.md",
                "memory/workstreams/_template.md",
                "memory/projects/_template.md",
                "memory/todos.md",
                "memory/relationship-state.md",
                *knowledge_artifacts(),
                *workspace_artifacts(),
            )
        elif adapter == "claude-code":
            required = (
                "CLAUDE.md",
                skill_path,
                ".claude/settings.local.json.example",
                "manifest.json",
                "memory/index.md",
                "memory/profile.md",
                "memory/session-index.md",
                "memory/source-map.md",
                "memory/collaboration.md",
                "memory/pinned.md",
                "memory/workstreams.md",
                "memory/workstreams/_template.md",
                "memory/projects/_template.md",
                "memory/todos.md",
                "memory/relationship-state.md",
                *knowledge_artifacts(),
                *workspace_artifacts(),
            )
        else:
            slug = character_slug(data)
            required = (
                "manifest.json",
                f".cursor/rules/{slug}.mdc",
                f".cursor/rules/{slug}-memory.mdc",
                skill_path,
                "memory/index.md",
                "memory/profile.md",
                "memory/session-index.md",
                "memory/source-map.md",
                "memory/collaboration.md",
                "memory/pinned.md",
                "memory/workstreams.md",
                "memory/workstreams/_template.md",
                "memory/projects/_template.md",
                "memory/todos.md",
                "memory/relationship-state.md",
                *knowledge_artifacts(),
                *HANDOFF_ARTIFACTS,
                *workspace_artifacts(),
            )
        for artifact in required:
            if artifact not in artifacts:
                issues.append(f"outputs.{adapter}.artifacts must include {artifact}")


def _validate_checker(checker, issues):
    if not _is_mapping(checker):
        issues.append("checker must be a mapping")
        return
    threshold = checker.get("threshold")
    if not isinstance(threshold, int) or threshold < 0 or threshold > 100:
        issues.append("checker.threshold must be an integer from 0 to 100")
    if not _is_non_empty_list(checker.get("required_checks")):
        issues.append("checker.required_checks must be a non-empty list")


def _validate_coverage(data, issues):
    coverage = data.get("coverage")
    if not _is_mapping(coverage):
        issues.append("coverage must be a mapping")
        return
    required = coverage.get("required_mechanisms")
    implemented_by = coverage.get("implemented_by")
    if not _is_non_empty_list(required):
        issues.append("coverage.required_mechanisms must be a non-empty list")
        required = []
    if not _is_mapping(implemented_by):
        issues.append("coverage.implemented_by must be a mapping")
        implemented_by = {}

    seen = set()
    for mechanism in _as_list(required):
        if not _non_empty_string(mechanism):
            issues.append("coverage mechanisms must be non-empty strings")
            continue
        if mechanism in seen:
            issues.append(f"duplicate character mechanism: {mechanism}")
        seen.add(mechanism)

        paths = implemented_by.get(mechanism)
        if not _is_non_empty_list(paths):
            issues.append(f"coverage.implemented_by.{mechanism} must be a non-empty list")
            continue
        for path in paths:
            if not _non_empty_string(path):
                issues.append(f"coverage path for {mechanism} must be a non-empty string")
            elif not path_exists(data, path):
                issues.append(f"coverage path for {mechanism} does not exist: {path}")


def _validate_reserved_specs(data, issues):
    reserved_specs = data.get("reserved_specs", {})
    if not _is_mapping(reserved_specs):
        issues.append("reserved_specs must be a mapping")
        return
    for name, spec in reserved_specs.items():
        if not _is_mapping(spec):
            issues.append(f"reserved_specs.{name} must be a mapping")
            continue
        if spec.get("status") not in {"reserved", "structured_reserved"}:
            issues.append(f"reserved_specs.{name}.status must be reserved or structured_reserved")
        if spec.get("runtime") != "not_implemented":
            issues.append(f"reserved_specs.{name}.runtime must be not_implemented")
        if not _non_empty_string(spec.get("spec_path")):
            issues.append(f"reserved_specs.{name}.spec_path must be a non-empty string")


def _validate_id_list(items, path, issues):
    seen = set()
    for index, item in enumerate(_as_list(items)):
        item_path = f"{path}[{index}]"
        if not _is_mapping(item):
            issues.append(f"{item_path} must be a mapping")
            continue
        item_id = item.get("id")
        if not _non_empty_string(item_id):
            issues.append(f"{item_path}.id must be a non-empty string")
        elif item_id in seen:
            issues.append(f"duplicate id in {path}: {item_id}")
        else:
            seen.add(item_id)


def _validate_optional_slug(mapping, label, issues):
    if not _is_mapping(mapping) or "slug" not in mapping:
        return
    value = mapping.get("slug")
    if not _non_empty_string(value):
        issues.append(f"{label} must be a non-empty string when provided")
        return
    normalized = normalize_slug(value, default="")
    if not normalized or not is_valid_slug(normalized):
        issues.append(f"{label} must normalize to a lowercase ASCII slug")


def _validate_file_ref(data, rel_path, label, issues):
    if not _non_empty_string(rel_path):
        return
    try:
        resolve_mechanism_file(data, rel_path, label)
    except PackwrightValidationError as exc:
        issues.extend(exc.issues)


def _is_mapping(value):
    return isinstance(value, Mapping)


def _is_list(value):
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _is_non_empty_list(value):
    return _is_list(value) and len(value) > 0


def _as_list(value):
    if _is_list(value):
        return value
    return []


def _non_empty_string(value):
    return isinstance(value, str) and bool(value.strip())
