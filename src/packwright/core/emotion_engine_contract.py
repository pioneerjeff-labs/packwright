from .adapter_layout import adapter_skill_root


EMOTION_ENGINE_USER_VISIBLE_MODES = ("light", "always", "paused")
EMOTION_ENGINE_MODES = set(EMOTION_ENGINE_USER_VISIBLE_MODES)
EMOTION_ENGINE_RUNTIME = "project_mcp_sidecar"
EMOTION_ENGINE_AVAILABLE_RUNTIME = "optional_project_mcp_sidecar"
EMOTION_ENGINE_CLAUDE_RUNTIME = EMOTION_ENGINE_AVAILABLE_RUNTIME
EMOTION_ENGINE_VERSION = "2.0.0-rc.4"
EMOTION_ENGINE_UPSTREAM_COMMIT = "400bd2eb0ebad5edd3000d7d5ff7da383dfa3615"
EMOTION_ENGINE_GENERATION = "2.0.0-rc.4-400bd2e"
EMOTION_ENGINE_STATE_SCHEMA = "emotion-engine-state/v3"
EMOTION_ENGINE_LEGACY_STATE_SCHEMA = "emotion-engine-state/v2"
EMOTION_ENGINE_REQUIRED_CAPABILITIES = (
    "state_identity/v1",
    "structured_record_policy/v1",
    "session_idempotency/v1",
    "trust_evidence/v1",
    "behavior_audit/v1",
    "repair_plan/v1",
    "migration_extensions/v1",
    "bounded_idempotency/v1",
    "bounded_active_session/v1",
)
EMOTION_ENGINE_SIDECAR = "emotion-engine"
EMOTION_ENGINE_MANIFEST_PATH = "manifest.json"

EMOTION_ENGINE_RUNTIME_ROOT = (
    f".packwright/runtime/emotion-engine/generations/{EMOTION_ENGINE_GENERATION}"
)
EMOTION_ENGINE_STATE_PATH = (
    f".emotion-engine/generations/{EMOTION_ENGINE_GENERATION}/state.json"
)
EMOTION_ENGINE_LEGACY_STATE_PATHS = (
    ".emotion-engine/state.json",
    ".emotion-engine/codex-state.json",
    ".emotion-engine/emotion-state.json",
)
EMOTION_ENGINE_WRAPPER_PATH = "scripts/emotion_engine.sh"
EMOTION_ENGINE_MCP_WRAPPER_PATH = "scripts/emotion_engine_mcp.sh"
EMOTION_ENGINE_LIFECYCLE_PATH = "scripts/emotion_engine_lifecycle.py"
EMOTION_ENGINE_MCP_LAUNCHER_PATH = (
    f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/packwright_mcp_launcher.py"
)
EMOTION_ENGINE_PROJECTION_RECEIPT_PATH = (
    f"{EMOTION_ENGINE_RUNTIME_ROOT}/projection.json"
)
EMOTION_ENGINE_PROJECTION_PENDING_PATH = (
    f"{EMOTION_ENGINE_RUNTIME_ROOT}/projection.pending.json"
)
EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH = (
    ".packwright/activation/emotion-engine-lifecycle.json"
)
EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH = (
    ".packwright/activation/emotion-engine-mcp.json"
)
EMOTION_ENGINE_TARGET_LOCK_PATH = ".packwright/emotion-engine.lock"
EMOTION_ENGINE_MIGRATION_JOURNAL_PATH = (
    ".packwright/transactions/emotion-engine-migration.json"
)
EMOTION_ENGINE_CODEX_LIFECYCLE_CONFIG_PATH = ".codex/hooks.json"

EMOTION_ENGINE_SKILL_PATHS = {
    "codex": f"{adapter_skill_root('codex')}/emotion-engine/SKILL.md",
    "claude-code": f"{adapter_skill_root('claude-code')}/emotion-engine/SKILL.md",
    "cursor": f"{adapter_skill_root('cursor')}/emotion-engine.mdc",
}

EMOTION_ENGINE_MCP_CONFIG_PATHS = {
    "codex": ".codex/config.toml",
    "claude-code": ".mcp.json",
    "cursor": ".cursor/mcp.json",
}

EMOTION_ENGINE_COMMON_SOURCE_FILES = {
    f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_utils.py": "scripts/emotion_engine_utils.py",
    f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_mcp.py": "scripts/emotion_engine_mcp.py",
    f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/register_mcp_client.py": "scripts/register_mcp_client.py",
    f"{EMOTION_ENGINE_RUNTIME_ROOT}/emotion-state-template.json": "emotion-state-template.json",
    f"{EMOTION_ENGINE_RUNTIME_ROOT}/spec/emotion-state.schema.json": "spec/emotion-state.schema.json",
    f"{EMOTION_ENGINE_RUNTIME_ROOT}/LICENSE": "LICENSE",
}

EMOTION_ENGINE_COMMON_ARTIFACTS = tuple(EMOTION_ENGINE_COMMON_SOURCE_FILES)

EMOTION_ENGINE_OVERHEAD = {
    "light": "<1% global token overhead; use only when continuity or milestone settlement matters",
    "always": "~3% target global token overhead, capped at <=5%; optimize state summaries before enabling broadly",
    "paused": "0% runtime overhead while preserving installed state for later resume",
}


def emotion_engine_skill_path(adapter):
    return EMOTION_ENGINE_SKILL_PATHS[adapter]


def emotion_engine_mcp_config_path(adapter):
    return EMOTION_ENGINE_MCP_CONFIG_PATHS[adapter]


def emotion_engine_runtime_supported(adapter):
    return adapter in EMOTION_ENGINE_SKILL_PATHS and adapter in EMOTION_ENGINE_MCP_CONFIG_PATHS


def emotion_engine_artifacts(adapter):
    if not emotion_engine_runtime_supported(adapter):
        return ()
    return (
        *EMOTION_ENGINE_COMMON_ARTIFACTS,
        EMOTION_ENGINE_WRAPPER_PATH,
        EMOTION_ENGINE_MCP_WRAPPER_PATH,
        EMOTION_ENGINE_LIFECYCLE_PATH,
        EMOTION_ENGINE_MCP_LAUNCHER_PATH,
        EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
        emotion_engine_skill_path(adapter),
        EMOTION_ENGINE_STATE_PATH,
    )


def emotion_engine_managed_artifacts(adapter):
    return tuple(path for path in emotion_engine_artifacts(adapter) if path != EMOTION_ENGINE_STATE_PATH)


def emotion_engine_feature(
    adapter,
    installed,
    mode="light",
    source_digest=None,
    mcp_status=None,
    activation=None,
    projection_nonce=None,
):
    if installed and not emotion_engine_runtime_supported(adapter):
        raise ValueError(f"Emotion Engine runtime is unavailable for adapter: {adapter}")
    feature = {
        "default_mode": "light",
        "mode": mode,
        "installed": bool(installed),
        "adapter": adapter,
        "version": EMOTION_ENGINE_VERSION if installed else None,
        "state_schema": EMOTION_ENGINE_STATE_SCHEMA if installed else None,
        "required_capabilities": list(EMOTION_ENGINE_REQUIRED_CAPABILITIES) if installed else [],
        "user_visible_modes": list(EMOTION_ENGINE_USER_VISIBLE_MODES),
        "state_path": EMOTION_ENGINE_STATE_PATH if installed else None,
        "runtime_root": EMOTION_ENGINE_RUNTIME_ROOT if installed else None,
        "writer_generation": EMOTION_ENGINE_GENERATION if installed else None,
        "projection_nonce": projection_nonce if installed else None,
        "skill_path": emotion_engine_skill_path(adapter) if installed else None,
        "mcp_config_path": emotion_engine_mcp_config_path(adapter) if installed else None,
        "mcp_status": mcp_status if installed else None,
        "estimated_overhead": EMOTION_ENGINE_OVERHEAD,
        "activation": dict(activation or {
            "installed": bool(installed),
            "configured": False,
            "active": False,
            "verified": False,
            "status": "not_installed" if not installed else "not_verified",
        }),
    }
    if source_digest:
        feature["source_digest"] = source_digest
    return feature


def emotion_engine_sidecar_record(
    adapter,
    mode,
    source_digest,
    mcp_status,
    activation=None,
    projection_nonce=None,
):
    return {
        "version": EMOTION_ENGINE_VERSION,
        "state_schema": EMOTION_ENGINE_STATE_SCHEMA,
        "required_capabilities": list(EMOTION_ENGINE_REQUIRED_CAPABILITIES),
        "upstream_commit": EMOTION_ENGINE_UPSTREAM_COMMIT,
        "writer_generation": EMOTION_ENGINE_GENERATION,
        "projection_nonce": projection_nonce,
        "mode": mode,
        "runtime_root": EMOTION_ENGINE_RUNTIME_ROOT,
        "skill_path": emotion_engine_skill_path(adapter),
        "state_file": EMOTION_ENGINE_STATE_PATH,
        "mcp_config": emotion_engine_mcp_config_path(adapter),
        "mcp_status": mcp_status,
        "source_digest": source_digest,
        "writer_cohort": [
            f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_utils.py",
            f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_mcp.py",
            EMOTION_ENGINE_WRAPPER_PATH,
            EMOTION_ENGINE_MCP_WRAPPER_PATH,
            EMOTION_ENGINE_LIFECYCLE_PATH,
            EMOTION_ENGINE_MCP_LAUNCHER_PATH,
        ],
        "projection_receipt": EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
        "lifecycle_receipt": EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH,
        "mcp_activation_receipt": EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH,
        "target_lock": EMOTION_ENGINE_TARGET_LOCK_PATH,
        "lifecycle_config": (
            EMOTION_ENGINE_CODEX_LIFECYCLE_CONFIG_PATH
            if adapter == "codex"
            else None
        ),
        "activation": dict(activation or {}),
    }


def emotion_engine_expected(manifest, adapter_pack=None):
    if not isinstance(manifest, dict):
        return False
    feature = manifest.get("features", {}).get("emotion_engine", {})
    sidecars = manifest.get("sidecars", {})
    if isinstance(feature, dict) and feature.get("installed") is True:
        return True
    if sidecars.get(EMOTION_ENGINE_SIDECAR):
        return True
    adapter = manifest.get("adapter")
    if adapter_pack and adapter in EMOTION_ENGINE_SKILL_PATHS:
        return any(path in adapter_pack for path in emotion_engine_artifacts(adapter))
    return False


def emotion_engine_manifest_issues(manifest, expected_mode=None, required_artifacts=None):
    if not isinstance(manifest, dict):
        return ["manifest is not a mapping"]
    issues = []
    adapter = manifest.get("adapter")
    feature = manifest.get("features", {}).get("emotion_engine", {})
    sidecar = manifest.get("sidecars", {}).get(EMOTION_ENGINE_SIDECAR, {})
    boundaries = manifest.get("boundaries", {})
    artifacts = set(manifest.get("artifacts", []))
    mode = expected_mode or feature.get("mode")
    required = set(required_artifacts or emotion_engine_artifacts(adapter))

    if feature.get("installed") is not True:
        issues.append("manifest does not mark Emotion Engine as installed")
    if feature.get("adapter") != adapter:
        issues.append("manifest Emotion Engine adapter is inconsistent")
    if feature.get("version") != EMOTION_ENGINE_VERSION:
        issues.append("manifest Emotion Engine version is inconsistent")
    if (
        feature.get("writer_generation") != EMOTION_ENGINE_GENERATION
        or sidecar.get("writer_generation") != EMOTION_ENGINE_GENERATION
    ):
        issues.append("manifest Emotion Engine writer generation is inconsistent")
    if (
        not isinstance(feature.get("projection_nonce"), str)
        or not feature.get("projection_nonce")
        or feature.get("projection_nonce") != sidecar.get("projection_nonce")
    ):
        issues.append("manifest Emotion Engine projection nonce is inconsistent")
    if feature.get("state_schema") != EMOTION_ENGINE_STATE_SCHEMA or sidecar.get("state_schema") != EMOTION_ENGINE_STATE_SCHEMA:
        issues.append("manifest Emotion Engine state schema is inconsistent")
    required_capabilities = list(EMOTION_ENGINE_REQUIRED_CAPABILITIES)
    if feature.get("required_capabilities") != required_capabilities or sidecar.get("required_capabilities") != required_capabilities:
        issues.append("manifest Emotion Engine required capabilities are inconsistent")
    if mode not in EMOTION_ENGINE_MODES:
        issues.append("manifest Emotion Engine mode is invalid")
    if feature.get("mode") != mode or sidecar.get("mode") != mode or boundaries.get("emotion_engine_mode") != mode:
        issues.append("manifest Emotion Engine mode is inconsistent")
    if feature.get("default_mode") != "light":
        issues.append("manifest Emotion Engine default_mode is not light")
    if boundaries.get("emotion_engine_runtime") != EMOTION_ENGINE_RUNTIME:
        issues.append("manifest runtime boundary is not project_mcp_sidecar")
    if sidecar.get("state_file") != EMOTION_ENGINE_STATE_PATH:
        issues.append("manifest sidecar state_file is inconsistent")
    if sidecar.get("skill_path") != emotion_engine_skill_path(adapter):
        issues.append("manifest sidecar skill_path is inconsistent")
    if feature.get("mcp_config_path") != emotion_engine_mcp_config_path(adapter):
        issues.append("manifest MCP config path is inconsistent")
    if not feature.get("source_digest") or feature.get("source_digest") != sidecar.get("source_digest"):
        issues.append("manifest Emotion Engine source digest is inconsistent")
    expected_writer_cohort = [
        f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_utils.py",
        f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_mcp.py",
        EMOTION_ENGINE_WRAPPER_PATH,
        EMOTION_ENGINE_MCP_WRAPPER_PATH,
        EMOTION_ENGINE_LIFECYCLE_PATH,
        EMOTION_ENGINE_MCP_LAUNCHER_PATH,
    ]
    if sidecar.get("writer_cohort") != expected_writer_cohort:
        issues.append("manifest Emotion Engine writer cohort is inconsistent")
    if sidecar.get("projection_receipt") != EMOTION_ENGINE_PROJECTION_RECEIPT_PATH:
        issues.append("manifest Emotion Engine projection receipt path is inconsistent")
    if sidecar.get("mcp_activation_receipt") != EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH:
        issues.append("manifest Emotion Engine MCP activation receipt path is inconsistent")
    if sidecar.get("target_lock") != EMOTION_ENGINE_TARGET_LOCK_PATH:
        issues.append("manifest Emotion Engine target lock path is inconsistent")
    expected_lifecycle_config = (
        EMOTION_ENGINE_CODEX_LIFECYCLE_CONFIG_PATH if adapter == "codex" else None
    )
    if sidecar.get("lifecycle_config") != expected_lifecycle_config:
        issues.append("manifest Emotion Engine lifecycle configuration path is inconsistent")
    activation = feature.get("activation")
    if not isinstance(activation, dict) or any(
        not isinstance(activation.get(key), bool)
        for key in ("installed", "configured", "active", "verified")
    ):
        issues.append("manifest Emotion Engine activation layers are missing")
    elif activation != sidecar.get("activation"):
        issues.append("manifest Emotion Engine activation layers are inconsistent")
    for artifact in sorted(required):
        if artifact not in artifacts:
            issues.append(f"manifest artifacts missing {artifact}")
    return issues


def emotion_engine_manifest_diagnostics(manifest, expected_mode=None, required_artifacts=None):
    return [
        {
            "id": _emotion_engine_manifest_issue_id(message),
            "path": EMOTION_ENGINE_MANIFEST_PATH,
            "message": message,
        }
        for message in emotion_engine_manifest_issues(
            manifest,
            expected_mode=expected_mode,
            required_artifacts=required_artifacts,
        )
    ]


def _emotion_engine_manifest_issue_id(message):
    if message.startswith("manifest artifacts missing"):
        return "emotion_engine_manifest_missing_artifact"
    return "emotion_engine_manifest_drift"


# 0.1.0 compatibility aliases. Remove after one published compatibility cycle.
EMOTION_ENGINE_CODEX_SIDECAR = EMOTION_ENGINE_SIDECAR
EMOTION_ENGINE_CODEX_SKILL_PATH = EMOTION_ENGINE_SKILL_PATHS["codex"]
EMOTION_ENGINE_CODEX_SKILL_DIR = EMOTION_ENGINE_CODEX_SKILL_PATH.rsplit("/", 1)[0]
EMOTION_ENGINE_CODEX_LEGACY_SKILL_DIR = ".codex/skills/emotion-engine-codex"
EMOTION_ENGINE_CODEX_STATE_PATH = EMOTION_ENGINE_STATE_PATH
EMOTION_ENGINE_CODEX_WRAPPER_PATH = EMOTION_ENGINE_WRAPPER_PATH
EMOTION_ENGINE_CODEX_MCP_WRAPPER_PATH = EMOTION_ENGINE_MCP_WRAPPER_PATH
EMOTION_ENGINE_CODEX_SCRIPT_PATH = f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_utils.py"
EMOTION_ENGINE_CODEX_HELPER_PATH = EMOTION_ENGINE_CODEX_SCRIPT_PATH
EMOTION_ENGINE_CODEX_MCP_PATH = f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_mcp.py"
EMOTION_ENGINE_CODEX_MCP_REGISTRATION_PATH = f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/register_mcp_client.py"
EMOTION_ENGINE_CODEX_ARTIFACTS = emotion_engine_artifacts("codex")
EMOTION_ENGINE_CODEX_REQUIRED_MANIFEST_ARTIFACTS = set(EMOTION_ENGINE_CODEX_ARTIFACTS)


def emotion_engine_codex_sidecar_record(mode):
    return emotion_engine_sidecar_record("codex", mode, "legacy-unknown", "configured")


def emotion_engine_codex_expected(manifest, adapter_pack=None):
    return emotion_engine_expected(manifest, adapter_pack=adapter_pack)


def emotion_engine_codex_manifest_issues(manifest, expected_mode=None, required_artifacts=None):
    return emotion_engine_manifest_issues(
        manifest,
        expected_mode=expected_mode,
        required_artifacts=required_artifacts,
    )


def emotion_engine_codex_manifest_diagnostics(manifest, expected_mode=None, required_artifacts=None):
    return emotion_engine_manifest_diagnostics(
        manifest,
        expected_mode=expected_mode,
        required_artifacts=required_artifacts,
    )


def emotion_engine_codex_manifest_consistent(manifest, expected_mode=None, required_artifacts=None):
    return not emotion_engine_codex_manifest_diagnostics(
        manifest,
        expected_mode=expected_mode,
        required_artifacts=required_artifacts,
    )
