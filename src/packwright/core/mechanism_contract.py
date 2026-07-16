import copy


CURRENT_MECHANISM_VERSION = "0.7"
LEGACY_MECHANISM_VERSIONS = {"0.5", "0.6"}

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

    Legacy 0.5/0.6 specs remain valid source documents. Their adapter-owned
    declarations are normalized away in memory so builds and embedded specs use
    the same semantic 0.7 contract as newly generated characters.
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

    session_start = normalized.get("session_start", {})
    if isinstance(session_start, dict):
        session_start.pop("hook", None)
        session_start.setdefault("event", "session_start")

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

    return normalized
