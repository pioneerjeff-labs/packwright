import copy


CURRENT_MECHANISM_VERSION = "0.8"
LEGACY_MECHANISM_VERSIONS = {"0.5", "0.6", "0.7"}

_ADAPTER_OWNED_TOP_LEVEL = {
    "implementation_scope",
    "outputs",
    "projection",
    "reserved_specs",
    "targets",
}

_ADAPTER_OWNED_COVERAGE = {
    "adapter_projection",
    "implementation_scope_boundary",
    "ownership_contract",
    "platform_capabilities",
    "reserved_runtime_boundary",
}


def normalize_mechanism(data):
    """Return the runtime-neutral internal mechanism contract.

    Legacy 0.5/0.6/0.7 specs remain valid source documents. Their adapter-owned
    declarations and session-start shorthand are normalized away in memory so
    builds and embedded specs use the same semantic 0.8 contract as newly
    generated characters.
    """
    normalized = copy.deepcopy(data)
    if str(normalized.get("version")) not in LEGACY_MECHANISM_VERSIONS:
        return normalized

    normalized["version"] = CURRENT_MECHANISM_VERSION
    for key in _ADAPTER_OWNED_TOP_LEVEL:
        normalized.pop(key, None)

    emotion = normalized.get("emotion", {})
    if isinstance(emotion, dict):
        emotion.pop("projection", None)
        emotion.pop("reserved_activation", None)

    session_start = normalized.pop("session_start", {})
    normalized["automations"] = _legacy_session_start_automations(session_start)

    coverage = normalized.get("coverage", {})
    if isinstance(coverage, dict):
        required = coverage.get("required_mechanisms", [])
        if isinstance(required, list):
            coverage["required_mechanisms"] = [
                item for item in required if item not in _ADAPTER_OWNED_COVERAGE
            ]
        implemented_by = coverage.get("implemented_by", {})
        if isinstance(implemented_by, dict):
            for item in _ADAPTER_OWNED_COVERAGE:
                implemented_by.pop(item, None)
            for mechanism_id, paths in implemented_by.items():
                if isinstance(paths, list):
                    implemented_by[mechanism_id] = [
                        "automations" if path == "session_start" else path for path in paths
                    ]

    return normalized


def _legacy_session_start_automations(session_start):
    if not isinstance(session_start, dict):
        return []
    automations = []
    for index, fact in enumerate(session_start.get("facts", [])):
        if not isinstance(fact, dict):
            continue
        fact_id = str(fact.get("id") or f"fact-{index + 1}")
        source = fact.get("source")
        if source == "system_date":
            producer = {
                "kind": "freshness_facts",
                "facts": [{"field": fact_id, "source": "system_datetime"}],
            }
            budget_bytes = 512
        elif isinstance(source, str) and source:
            producer = {
                "kind": "memory_view",
                "source": source,
                "select": {"max_bytes": 4096},
            }
            budget_bytes = 4096
        else:
            continue
        automations.append(
            {
                "id": f"session-start-{fact_id.replace('_', '-')}",
                "scope": "local",
                "event": "session_start",
                "effect": "add_context",
                "producer": producer,
                "budget_bytes": budget_bytes,
            }
        )
    return automations
