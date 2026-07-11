EMOTION_ENGINE_USER_VISIBLE_MODES = ("light", "always", "paused")
EMOTION_ENGINE_MODES = set(EMOTION_ENGINE_USER_VISIBLE_MODES)
EMOTION_ENGINE_RUNTIME = "adapter_sidecar"
EMOTION_ENGINE_AVAILABLE_RUNTIME = "adapter_sidecar_available"
EMOTION_ENGINE_CLAUDE_RUNTIME = "spec_guided_behavior_only"
EMOTION_ENGINE_CODEX_SIDECAR = "emotion-engine-codex"
from .adapter_layout import adapter_skill_root, legacy_skill_roots


EMOTION_ENGINE_CODEX_SKILL_DIR = f"{adapter_skill_root('codex')}/emotion-engine-codex"
EMOTION_ENGINE_CODEX_LEGACY_SKILL_DIR = f"{legacy_skill_roots('codex')[0]}/emotion-engine-codex"
EMOTION_ENGINE_CODEX_STATE_PATH = ".emotion-engine/codex-state.json"
EMOTION_ENGINE_CODEX_WRAPPER_PATH = "scripts/codex_emotion.sh"
EMOTION_ENGINE_CODEX_SKILL_PATH = f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/SKILL.md"
EMOTION_ENGINE_CODEX_SCRIPT_PATH = f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/scripts/codex_emotion.sh"
EMOTION_ENGINE_CODEX_HELPER_PATH = f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/scripts/emotion_engine_utils.py"
EMOTION_ENGINE_CODEX_MCP_PATH = f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/scripts/emotion_engine_mcp.py"
EMOTION_ENGINE_CODEX_MCP_REGISTRATION_PATH = f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/scripts/register_mcp_client.py"
EMOTION_ENGINE_MANIFEST_PATH = "manifest.json"

EMOTION_ENGINE_OVERHEAD = {
    "light": "<1% global token overhead; use only when continuity or milestone settlement matters",
    "always": "~3% target global token overhead, capped at <=5%; optimize state summaries before enabling broadly",
    "paused": "0% runtime overhead while preserving installed state for later resume",
}

EMOTION_ENGINE_CODEX_ARTIFACTS = (
    EMOTION_ENGINE_CODEX_WRAPPER_PATH,
    EMOTION_ENGINE_CODEX_SKILL_PATH,
    f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/README.md",
    f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/install.sh",
    EMOTION_ENGINE_CODEX_SCRIPT_PATH,
    EMOTION_ENGINE_CODEX_HELPER_PATH,
    EMOTION_ENGINE_CODEX_MCP_PATH,
    EMOTION_ENGINE_CODEX_MCP_REGISTRATION_PATH,
    f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/scripts/pulse_demo.py",
    f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/emotion-state-template.json",
    f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/spec/emotion-state.schema.json",
    f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/LICENSE",
    EMOTION_ENGINE_CODEX_STATE_PATH,
)

EMOTION_ENGINE_CODEX_REQUIRED_MANIFEST_ARTIFACTS = {
    EMOTION_ENGINE_CODEX_WRAPPER_PATH,
    EMOTION_ENGINE_CODEX_SKILL_PATH,
    EMOTION_ENGINE_CODEX_SCRIPT_PATH,
    EMOTION_ENGINE_CODEX_HELPER_PATH,
    EMOTION_ENGINE_CODEX_MCP_PATH,
    EMOTION_ENGINE_CODEX_MCP_REGISTRATION_PATH,
    EMOTION_ENGINE_CODEX_STATE_PATH,
}


def emotion_engine_feature(adapter, installed, mode="light"):
    return {
        "default_mode": "light",
        "mode": mode,
        "installed": bool(installed),
        "adapter": adapter,
        "user_visible_modes": list(EMOTION_ENGINE_USER_VISIBLE_MODES),
        "state_path": EMOTION_ENGINE_CODEX_STATE_PATH if adapter == "codex" else None,
        "estimated_overhead": EMOTION_ENGINE_OVERHEAD,
    }


def emotion_engine_codex_sidecar_record(mode):
    return {
        "mode": mode,
        "skill_dir": EMOTION_ENGINE_CODEX_SKILL_DIR,
        "state_file": EMOTION_ENGINE_CODEX_STATE_PATH,
    }


def emotion_engine_codex_expected(manifest, adapter_pack=None):
    if not isinstance(manifest, dict):
        return False
    feature = manifest.get("features", {}).get("emotion_engine", {})
    sidecars = manifest.get("sidecars", {})
    if isinstance(feature, dict) and feature.get("installed") is True:
        return True
    if sidecars.get(EMOTION_ENGINE_CODEX_SIDECAR):
        return True
    if adapter_pack:
        return any(artifact in adapter_pack for artifact in EMOTION_ENGINE_CODEX_ARTIFACTS)
    return False


def emotion_engine_codex_manifest_issues(manifest, expected_mode=None, required_artifacts=None):
    if not isinstance(manifest, dict):
        return ["manifest is not a mapping"]
    issues = []
    feature = manifest.get("features", {}).get("emotion_engine", {})
    sidecar = manifest.get("sidecars", {}).get(EMOTION_ENGINE_CODEX_SIDECAR, {})
    boundaries = manifest.get("boundaries", {})
    artifacts = set(manifest.get("artifacts", []))
    mode = expected_mode or feature.get("mode")
    required = set(required_artifacts or EMOTION_ENGINE_CODEX_REQUIRED_MANIFEST_ARTIFACTS)

    if feature.get("installed") is not True:
        issues.append("manifest does not mark Emotion Engine as installed")
    if feature.get("adapter") != "codex":
        issues.append("manifest feature adapter is not codex")
    if mode not in EMOTION_ENGINE_MODES:
        issues.append("manifest Emotion Engine mode is invalid")
    if feature.get("mode") != mode or sidecar.get("mode") != mode or boundaries.get("emotion_engine_mode") != mode:
        issues.append("manifest Emotion Engine mode is inconsistent")
    if feature.get("default_mode") != "light":
        issues.append("manifest Emotion Engine default_mode is not light")
    if boundaries.get("emotion_engine_runtime") != EMOTION_ENGINE_RUNTIME:
        issues.append("manifest runtime boundary is not adapter_sidecar")
    if sidecar.get("skill_dir") != EMOTION_ENGINE_CODEX_SKILL_DIR:
        issues.append("manifest sidecar skill_dir is inconsistent")
    if sidecar.get("state_file") != EMOTION_ENGINE_CODEX_STATE_PATH:
        issues.append("manifest sidecar state_file is inconsistent")
    for artifact in sorted(required):
        if artifact not in artifacts:
            issues.append(f"manifest artifacts missing {artifact}")
    return issues


def emotion_engine_codex_manifest_diagnostics(manifest, expected_mode=None, required_artifacts=None):
    return [
        {
            "id": _emotion_engine_codex_manifest_issue_id(message),
            "path": EMOTION_ENGINE_MANIFEST_PATH,
            "message": message,
        }
        for message in emotion_engine_codex_manifest_issues(
            manifest,
            expected_mode=expected_mode,
            required_artifacts=required_artifacts,
        )
    ]


def emotion_engine_codex_manifest_consistent(manifest, expected_mode=None, required_artifacts=None):
    return not emotion_engine_codex_manifest_diagnostics(
        manifest,
        expected_mode=expected_mode,
        required_artifacts=required_artifacts,
    )


def _emotion_engine_codex_manifest_issue_id(message):
    if message.startswith("manifest artifacts missing"):
        return "emotion_engine_codex_manifest_missing_artifact"
    return "emotion_engine_codex_manifest_drift"
