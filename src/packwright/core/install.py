import copy
import hashlib
import json
import os
import shutil
import stat
import tempfile
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .emotion_engine_contract import (
    EMOTION_ENGINE_COMMON_SOURCE_FILES,
    EMOTION_ENGINE_CODEX_LEGACY_SKILL_DIR,
    EMOTION_ENGINE_LEGACY_STATE_PATHS,
    EMOTION_ENGINE_MCP_WRAPPER_PATH,
    EMOTION_ENGINE_MODES,
    EMOTION_ENGINE_RUNTIME,
    EMOTION_ENGINE_RUNTIME_ROOT,
    EMOTION_ENGINE_SIDECAR,
    EMOTION_ENGINE_STATE_PATH,
    EMOTION_ENGINE_UPSTREAM_COMMIT,
    EMOTION_ENGINE_VERSION,
    EMOTION_ENGINE_WRAPPER_PATH,
    emotion_engine_artifacts,
    emotion_engine_expected,
    emotion_engine_feature,
    emotion_engine_manifest_diagnostics,
    emotion_engine_mcp_config_path,
    emotion_engine_sidecar_record,
    emotion_engine_skill_path,
)
from .adapter_layout import adapter_entry, adapter_skill_root, supported_adapters
from .automation_projection import (
    automation_config_paths,
    is_managed_automation_config,
    managed_hook_fragment_digest,
    merge_managed_hook_config,
)
from .errors import PackwrightValidationError
from .handoff import HANDOFF_ARTIFACTS, HANDOFF_EXECUTABLE_ARTIFACTS, target_handoff_artifacts
from .knowledge_contract import (
    KNOWLEDGE_ROOT,
    SOURCES_ROOT,
    knowledge_artifacts,
    knowledge_files,
    knowledge_manifest_diagnostics,
    knowledge_required_dirs,
)
from .loader import load_mechanism
from .memory_projection import project_memory_file
from .mechanism_contract import normalize_mechanism
from .pack_metadata import LOCK_PATH, SPEC_PATH, embed_pack_metadata, load_embedded_spec
from .path_safety import resolve_destination_path, resolve_source_path, validate_relative_path
from .runtime_automation import discover_unmanaged_runtime_automation_assets
from .naming import (
    character_slug,
    is_valid_slug,
    normalize_slug,
)
from .resolver import resolve_mechanism
from .workspace_contract import workspace_artifacts, workspace_readme, workspace_required_dirs


SUPPORTED_INSTALL_ADAPTERS = set(supported_adapters())
PORTABLE_STATE_DIRS = ("memory", "workspace", KNOWLEDGE_ROOT, SOURCES_ROOT, "skills")
MIGRATION_SCHEMA = "packwright-migration/v1"
RECONCILE_SCHEMA = "packwright-reconcile/v1"
INSTALL_SCHEMA = "packwright-install/v1"
INSTALL_PROVENANCE_PATH = ".packwright/install-provenance.json"
EMOTION_ENGINE_SECTION = """## Emotion Engine
- Default mode: `{mode}`. The project-local MCP sidecar is installed; use it according to this mode's loading policy.
- Use `{skill_path}` for runtime guidance, `{state_path}` for live project state, and `{wrapper_path}` for shell access.
- The adapter's project MCP configuration points to the same runtime and state. Treat client approval prompts as runtime consent, not installation failure.
- Use `record_policy` before deciding whether an interaction should be persisted; it is deterministic, side-effect free, and returns compact `reply_bias` rather than rewriting `AGENTS.md`.
- `light` mode target: <1% global token overhead; use the sidecar only when tone continuity, emotional interaction, relationship dynamics, concrete feedback, repair, boundary pressure, or milestone settlement matter.
- `always` mode target: ~3% global token overhead, capped at <=5%; it may track each meaningful turn, but still respects salience, habituation, low-value duplicate compaction, and compact summaries.
- `paused` mode keeps local state available but should not record or modulate turns until resumed.
- Generic praise should usually affect the current reply only; repeated generic praise habituates, while concrete feedback, milestones, repair, and stable preferences may be recorded.
- At meaningful session or milestone close, use the sidecar's `settle_trust` command to conservatively settle agent-to-user trust from recent evidence; praise alone must not directly grow trust.
- Keep it internal: do not expose PAD/trust numbers, state JSON, or step-by-step status unless asked.
- Do not mix Emotion Engine state into memory files; keep durable facts in `memory/*` and dynamic state in `{state_path}`.
"""


@dataclass(frozen=True)
class InstallPlan:
    pack_dir: Path
    target_dir: Path
    adapter: str
    manifest: dict
    source_paths: tuple
    source_hashes: dict
    destinations: dict
    force: bool
    sidecar_plan: object
    retire_legacy_state: bool
    persist_provenance: bool
    provenance: dict
    report: dict

    def to_dict(self):
        return copy.deepcopy(self.report)


@dataclass(frozen=True)
class MigrationPlan:
    source_target_dir: Path
    target_dir: Path
    from_adapter: str
    to_adapter: str
    mechanism_file: Path
    resolved: dict
    pack: dict
    source_manifest: dict
    pack_dir: Optional[Path]
    force: bool
    include_emotion_state: bool
    emotion_engine_source: object
    emotion_state_source: object
    emotion_style: object
    emotion_engine_mode: object
    report: dict

    def to_dict(self):
        return copy.deepcopy(self.report)


@dataclass(frozen=True)
class ReconcilePlan:
    target_dir: Path
    mechanism_file: Path
    resolved: dict
    pack: dict
    installed_manifest: dict
    mechanism_sha256: str
    report: dict

    def to_dict(self):
        return copy.deepcopy(self.report)


def install_pack(
    pack_dir,
    target_dir,
    adapter=None,
    force=False,
    include_emotion_engine_codex=None,
    emotion_engine_codex_source=None,
    emotion_style=None,
    emotion_engine_mode=None,
    include_emotion_engine=None,
    emotion_engine_source=None,
    emotion_state_source=None,
    retire_legacy_state=False,
    persist_provenance=True,
    provenance=None,
):
    """Plan and install an adapter pack into a local runtime directory."""
    plan = plan_install(
        pack_dir,
        target_dir,
        adapter=adapter,
        force=force,
        include_emotion_engine_codex=include_emotion_engine_codex,
        emotion_engine_codex_source=emotion_engine_codex_source,
        emotion_style=emotion_style,
        emotion_engine_mode=emotion_engine_mode,
        include_emotion_engine=include_emotion_engine,
        emotion_engine_source=emotion_engine_source,
        emotion_state_source=emotion_state_source,
        retire_legacy_state=retire_legacy_state,
        persist_provenance=persist_provenance,
        provenance=provenance,
    )
    return apply_install(plan)


def plan_install(
    pack_dir,
    target_dir,
    adapter=None,
    force=False,
    include_emotion_engine_codex=None,
    emotion_engine_codex_source=None,
    emotion_style=None,
    emotion_engine_mode=None,
    include_emotion_engine=None,
    emotion_engine_source=None,
    emotion_state_source=None,
    retire_legacy_state=False,
    persist_provenance=True,
    provenance=None,
):
    """Return a complete no-write install plan."""
    pack_dir = Path(pack_dir)
    target_dir = Path(target_dir)
    manifest = _load_manifest(pack_dir)
    manifest_adapter = manifest.get("adapter")

    if manifest_adapter not in SUPPORTED_INSTALL_ADAPTERS:
        raise PackwrightValidationError([f"pack manifest declares unsupported adapter: {manifest_adapter!r}"])
    if adapter is None:
        adapter = manifest_adapter
    elif adapter not in SUPPORTED_INSTALL_ADAPTERS:
        raise PackwrightValidationError([f"unsupported adapter: {adapter}"])
    if manifest_adapter != adapter:
        raise PackwrightValidationError([f"pack adapter is {manifest_adapter!r}, expected {adapter!r}"])
    resolved_emotion_engine_mode = emotion_engine_mode or _manifest_emotion_engine_mode(manifest)
    if resolved_emotion_engine_mode not in EMOTION_ENGINE_MODES:
        raise PackwrightValidationError([f"emotion_engine_mode must be one of {sorted(EMOTION_ENGINE_MODES)}"])
    include_emotion_engine, emotion_engine_source = _resolve_emotion_engine_arguments(
        include_emotion_engine=include_emotion_engine,
        emotion_engine_source=emotion_engine_source,
        include_emotion_engine_codex=include_emotion_engine_codex,
        emotion_engine_codex_source=emotion_engine_codex_source,
    )
    if retire_legacy_state and not include_emotion_engine:
        raise PackwrightValidationError([
            "--retire-legacy-state requires --include-emotion-engine during install"
        ])

    artifacts = _manifest_artifacts(manifest)
    source_paths = tuple(
        (artifact, resolve_source_path(pack_dir, artifact, "adapter pack artifact"))
        for artifact in artifacts
    )
    source_hashes = {
        artifact: _file_sha256(source_path)
        for artifact, source_path in source_paths
    }
    destinations = {
        artifact: resolve_destination_path(target_dir, artifact, "installed artifact destination")
        for artifact in artifacts
    }

    existing = sorted(artifact for artifact, path in destinations.items() if path.exists())
    sidecar_plan = None
    if include_emotion_engine:
        sidecar_plan = _prepare_emotion_engine_install(
            target_dir,
            emotion_engine_source,
            adapter=adapter,
            force=force,
            emotion_style=emotion_style,
            emotion_engine_mode=resolved_emotion_engine_mode,
            manifest=manifest,
            state_source=emotion_state_source,
        )

    automation_configs = automation_config_paths(manifest)
    preserved_portable = sorted(
        artifact
        for artifact in existing
        if force and _is_portable_path(artifact)
    )
    preserved_live_state = sorted(
        artifact
        for artifact in existing
        if force and artifact == EMOTION_ENGINE_STATE_PATH
    )
    merged_managed_configs = []
    would_overwrite = []
    would_add = []
    for artifact, source_path in source_paths:
        destination = destinations[artifact]
        if not destination.exists():
            would_add.append(artifact)
            continue
        if artifact in preserved_portable or artifact in preserved_live_state:
            continue
        if force and artifact in automation_configs and destination.is_file():
            try:
                merge_managed_hook_config(
                    destination.read_text(encoding="utf-8"),
                    source_path.read_text(encoding="utf-8"),
                )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise PackwrightValidationError([
                    f"cannot safely merge managed hook entries in {artifact}: {exc}"
                ]) from exc
            merged_managed_configs.append(artifact)
            continue
        would_overwrite.append(artifact)

    next_artifacts = set(artifacts)
    if sidecar_plan:
        next_artifacts.update(emotion_engine_artifacts(adapter))
    would_remove_stale = (
        _stale_manifest_artifacts(target_dir, next_artifacts, preserve_portable=True)
        if force
        else []
    )
    sidecar_existing = sorted(sidecar_plan.get("existing_projection", [])) if sidecar_plan else []
    mcp_conflict = bool(sidecar_plan and sidecar_plan["mcp_config"].get("conflict"))
    force_blockers = sorted(set(existing + sidecar_existing))
    if mcp_conflict:
        force_blockers.append(sidecar_plan["mcp_config"]["path"])
    force_blockers = sorted(set(force_blockers)) if not force else []
    retirements = (
        _emotion_legacy_retirement_plan(target_dir)
        if sidecar_plan and retire_legacy_state
        else []
    )
    conflicts = [
        {
            "id": "target_artifacts_require_force",
            "paths": force_blockers,
            "message": "target contains files that require --force before install",
        }
    ] if force_blockers else []
    provenance_report = _install_provenance_data(
        pack_dir,
        manifest,
        context=provenance,
        include_timestamp=False,
    )
    report = {
        "schema": INSTALL_SCHEMA,
        "status": "planned",
        "ready": not conflicts,
        "adapter": adapter,
        "pack_dir": str(pack_dir),
        "target_dir": str(target_dir),
        "force": bool(force),
        "changes": {
            "add": sorted(would_add),
            "overwrite": sorted(would_overwrite),
            "merge_managed_configs": sorted(merged_managed_configs),
            "remove_stale_managed": would_remove_stale,
            "preserve_portable_state": preserved_portable,
            "preserve_live_state": preserved_live_state,
            "sidecar_projection": _install_sidecar_change_report(sidecar_plan),
            "retire_legacy_state": retirements,
        },
        "conflicts": conflicts,
        "required_confirmations": ([{"id": "force", "paths": force_blockers}] if force_blockers else []),
        "provenance": provenance_report,
    }
    return InstallPlan(
        pack_dir=pack_dir,
        target_dir=target_dir,
        adapter=adapter,
        manifest=manifest,
        source_paths=source_paths,
        source_hashes=source_hashes,
        destinations=destinations,
        force=bool(force),
        sidecar_plan=sidecar_plan,
        retire_legacy_state=bool(retire_legacy_state),
        persist_provenance=bool(persist_provenance),
        provenance=provenance_report,
        report=report,
    )


def apply_install(plan):
    """Apply a prepared InstallPlan after rechecking its pack inputs."""
    if not isinstance(plan, InstallPlan):
        raise TypeError("apply_install expects an InstallPlan")
    if not plan.report["ready"]:
        blockers = plan.report["required_confirmations"][0]["paths"]
        raise PackwrightValidationError([
            "target already contains files that would be overwritten; rerun with --force after reviewing them",
            *[f"existing target artifact: {artifact}" for artifact in blockers],
        ])
    changed_sources = [
        artifact
        for artifact, source_path in plan.source_paths
        if _file_sha256(source_path) != plan.source_hashes[artifact]
    ]
    if changed_sources:
        raise PackwrightValidationError([
            "adapter pack changed after install planning; prepare a new plan",
            *[f"changed pack artifact: {artifact}" for artifact in changed_sources],
        ])
    if not plan.force:
        newly_existing = sorted(
            artifact
            for artifact, destination in plan.destinations.items()
            if destination.exists()
        )
        if plan.sidecar_plan:
            newly_existing.extend(
                path
                for path in plan.sidecar_plan["projection"]
                if (plan.target_dir / path).exists()
            )
        if newly_existing:
            raise PackwrightValidationError([
                "target changed after install planning; prepare a new plan",
                *[f"existing target artifact: {artifact}" for artifact in sorted(set(newly_existing))],
            ])
    if plan.sidecar_plan:
        config = plan.sidecar_plan["mcp_config"]
        current_config_hash = (
            _file_sha256(config["destination"])
            if config["destination"].is_file()
            else None
        )
        if current_config_hash != config.get("original_sha256"):
            raise PackwrightValidationError([
                f"MCP config changed after install planning; prepare a new plan: {config['path']}"
            ])
        if plan.retire_legacy_state:
            _emotion_legacy_retirement_plan(plan.target_dir)

    stale_removed = []
    if plan.force:
        next_artifacts = set(_manifest_artifacts(plan.manifest))
        if plan.sidecar_plan:
            next_artifacts.update(emotion_engine_artifacts(plan.adapter))
        current_stale = _stale_manifest_artifacts(
            plan.target_dir,
            next_artifacts,
            preserve_portable=True,
        )
        if current_stale != plan.report["changes"]["remove_stale_managed"]:
            raise PackwrightValidationError([
                "target managed artifacts changed after install planning; prepare a new plan"
            ])
        stale_removed = _remove_stale_manifest_artifacts(
            plan.target_dir,
            next_artifacts,
            preserve_portable=True,
        )

    plan.target_dir.mkdir(parents=True, exist_ok=True)
    installed = []
    preserved_portable = []
    preserved_live_state = []
    merged_managed_configs = []
    automation_configs = automation_config_paths(plan.manifest)
    automation_runner = plan.manifest.get("features", {}).get("automations", {}).get("runner", {}).get("path")
    for artifact, source_path in plan.source_paths:
        destination = plan.destinations[artifact]
        if plan.force and _is_portable_path(artifact) and destination.exists():
            preserved_portable.append(artifact)
            continue
        if plan.force and artifact == EMOTION_ENGINE_STATE_PATH and destination.exists():
            preserved_live_state.append(artifact)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if plan.force and artifact in automation_configs and destination.is_file():
            try:
                merged = merge_managed_hook_config(
                    destination.read_text(encoding="utf-8"),
                    source_path.read_text(encoding="utf-8"),
                )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise PackwrightValidationError([
                    f"cannot safely merge managed hook entries in {artifact}: {exc}"
                ]) from exc
            destination.write_text(merged, encoding="utf-8")
            merged_managed_configs.append(artifact)
        else:
            shutil.copy2(source_path, destination)
        if artifact in HANDOFF_EXECUTABLE_ARTIFACTS or artifact == automation_runner:
            _make_executable(destination)
        installed.append(artifact)

    sidecars = {}
    retired_legacy_state = []
    if plan.sidecar_plan:
        sidecars[EMOTION_ENGINE_SIDECAR] = _install_emotion_engine(plan.target_dir, plan.sidecar_plan)
        if plan.retire_legacy_state:
            retired_legacy_state = _retire_legacy_emotion_states(plan.target_dir)
        _mark_emotion_engine_installed(
            plan.target_dir,
            sidecars[EMOTION_ENGINE_SIDECAR],
            plan.adapter,
            plan.sidecar_plan["mode"],
        )

    _write_automation_baseline(plan.target_dir, plan.manifest)
    _refresh_artifact_lock(plan.target_dir)
    if plan.persist_provenance:
        _write_install_provenance(plan.target_dir, plan.provenance)

    result = {
        "schema": INSTALL_SCHEMA,
        "status": "applied",
        "ready": True,
        "adapter": plan.adapter,
        "pack_dir": str(plan.pack_dir),
        "target_dir": str(plan.target_dir),
        "installed_artifacts": installed,
        "provenance": _read_install_provenance(plan.target_dir) if plan.persist_provenance else plan.provenance,
    }
    if stale_removed:
        result["stale_removed"] = stale_removed
    if preserved_portable:
        result["preserved_portable_state"] = sorted(preserved_portable)
    if preserved_live_state:
        result["preserved_live_state"] = sorted(preserved_live_state)
    if merged_managed_configs:
        result["merged_managed_configs"] = sorted(merged_managed_configs)
    if sidecars:
        result["sidecars"] = sidecars
    if retired_legacy_state:
        result["retired_legacy_state"] = retired_legacy_state
    return result


def _install_sidecar_change_report(plan):
    if not plan:
        return None
    existing = set(plan.get("existing_projection", []))
    state_file = plan["state_file"]
    state_source = plan.get("state_source")
    if state_source is None:
        state_operation = "preserve" if state_file.is_file() else "create"
    elif Path(state_source).resolve() == state_file.resolve():
        state_operation = "preserve"
    else:
        state_operation = "migrate_to_canonical"
    config = plan["mcp_config"]
    config_exists = config["destination"].is_file()
    return {
        "add": sorted(path for path in plan["projection"] if path not in existing),
        "overwrite": sorted(existing),
        "state": {
            "path": EMOTION_ENGINE_STATE_PATH,
            "operation": state_operation,
            "source": str(state_source) if state_source else None,
        },
        "mcp_config": {
            "path": config["path"],
            "operation": "replace_entry" if config.get("conflict") else ("merge_entry" if config_exists else "add_entry"),
            "conflict": bool(config.get("conflict")),
        },
    }


def _install_provenance_data(pack_dir, manifest, context=None, include_timestamp=True):
    pack_dir = Path(pack_dir)
    context = dict(context or {})
    lock_path = pack_dir / LOCK_PATH
    spec_path = pack_dir / SPEC_PATH
    source_path_explicit = "source_pack_path" in context
    source_pack_path = context.pop("source_pack_path", None)
    if not source_path_explicit:
        source_pack_path = str(pack_dir.resolve())
    source_pack_digest = (
        _file_sha256(lock_path)
        if lock_path.is_file()
        else _pack_artifact_tree_digest(pack_dir, manifest)
    )
    data = {
        "schema": "packwright-install-provenance/v1",
        "operation": context.pop("operation", "install"),
        "adapter": manifest.get("adapter"),
        "character_slug": manifest.get("character", {}).get("slug"),
        "source_pack_digest": source_pack_digest,
        "source_pack_digest_kind": "lock_sha256" if lock_path.is_file() else "artifact_tree_sha256",
        "spec_sha256": _file_sha256(spec_path) if spec_path.is_file() else None,
    }
    if source_pack_path:
        data["source_pack_path"] = source_pack_path
    data.update({key: value for key, value in context.items() if value is not None})
    if include_timestamp:
        data["installed_at"] = datetime.now(timezone.utc).isoformat()
    return data


def _pack_artifact_tree_digest(pack_dir, manifest):
    digest = hashlib.sha256()
    for artifact in sorted(_manifest_artifacts(manifest)):
        source = resolve_source_path(pack_dir, artifact, "adapter pack artifact")
        digest.update(artifact.encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_install_provenance(target_dir, provenance):
    path = resolve_destination_path(
        target_dir,
        INSTALL_PROVENANCE_PATH,
        "install provenance destination",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(provenance)
    data["installed_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_install_provenance(target_dir):
    path = Path(target_dir) / INSTALL_PROVENANCE_PATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _emotion_legacy_retirement_plan(target_dir):
    target_dir = Path(target_dir)
    planned = []
    for rel_path in EMOTION_ENGINE_LEGACY_STATE_PATHS:
        source = target_dir / rel_path
        if not source.is_file():
            continue
        backup = source.with_name(source.name + ".bak")
        if backup.exists():
            raise PackwrightValidationError([
                f"cannot retire legacy Emotion Engine state because backup already exists: {backup}"
            ])
        planned.append({
            "from": rel_path,
            "to": backup.relative_to(target_dir).as_posix(),
            "operation": "rename_backup",
        })
    return planned


def _retire_legacy_emotion_states(target_dir):
    target_dir = Path(target_dir)
    canonical = target_dir / EMOTION_ENGINE_STATE_PATH
    if not canonical.is_file():
        raise PackwrightValidationError([
            f"cannot retire legacy Emotion Engine state before {EMOTION_ENGINE_STATE_PATH} exists"
        ])
    planned = _emotion_legacy_retirement_plan(target_dir)
    canonical_hash = _file_sha256(canonical)
    for item in planned:
        source = target_dir / item["from"]
        if _file_sha256(source) != canonical_hash:
            raise PackwrightValidationError([
                f"legacy Emotion Engine state differs from canonical state and was not retired: {source}"
            ])
    for item in planned:
        (target_dir / item["from"]).rename(target_dir / item["to"])
    return planned


def refresh_emotion_engine(
    target_dir,
    emotion_engine_source=None,
    emotion_style=None,
    emotion_engine_mode=None,
    retire_legacy_state=False,
):
    """Refresh an installed Emotion Engine projection without replacing live state.

    This is the repair path for targets whose installed sidecar drifted from
    the canonical Emotion Engine source. It rewrites projected sidecar files,
    the project wrapper, AGENTS.md Emotion Engine section, and manifest sidecar
    bookkeeping while preserving the project-local runtime state file.
    """
    target_dir = Path(target_dir)
    manifest = _load_manifest(target_dir)
    manifest_adapter = manifest.get("adapter")
    if manifest_adapter not in SUPPORTED_INSTALL_ADAPTERS:
        raise PackwrightValidationError([f"target adapter is unsupported: {manifest_adapter!r}"])

    resolved_emotion_engine_mode = emotion_engine_mode or _manifest_emotion_engine_mode(manifest)
    if resolved_emotion_engine_mode not in EMOTION_ENGINE_MODES:
        raise PackwrightValidationError([f"emotion_engine_mode must be one of {sorted(EMOTION_ENGINE_MODES)}"])

    plan = _prepare_emotion_engine_install(
        target_dir,
        emotion_engine_source,
        adapter=manifest_adapter,
        force=True,
        emotion_style=emotion_style,
        emotion_engine_mode=resolved_emotion_engine_mode,
        manifest=manifest,
    )
    if retire_legacy_state:
        _emotion_legacy_retirement_plan(target_dir)
    sidecar = _install_emotion_engine(target_dir, plan)
    retired_legacy_state = (
        _retire_legacy_emotion_states(target_dir)
        if retire_legacy_state
        else []
    )
    _mark_emotion_engine_installed(target_dir, sidecar, manifest_adapter, resolved_emotion_engine_mode)
    updated_lock_paths = ["manifest.json", *_existing_sidecar_artifacts(target_dir)]
    if sidecar.get("entry_updated"):
        updated_lock_paths.append(adapter_entry(manifest_adapter))
    _update_artifact_lock_paths(target_dir, updated_lock_paths)
    result = {
        "adapter": manifest_adapter,
        "target_dir": str(target_dir),
        "refreshed_artifacts": _existing_sidecar_artifacts(target_dir),
        "sidecars": {EMOTION_ENGINE_SIDECAR: sidecar},
    }
    if retired_legacy_state:
        result["retired_legacy_state"] = retired_legacy_state
    return result


def refresh_emotion_engine_codex(
    target_dir,
    emotion_engine_codex_source=None,
    emotion_style=None,
    emotion_engine_mode=None,
    retire_legacy_state=False,
):
    """Deprecated compatibility wrapper for :func:`refresh_emotion_engine`."""
    warnings.warn(
        "refresh_emotion_engine_codex is deprecated; use refresh_emotion_engine",
        DeprecationWarning,
        stacklevel=2,
    )
    return refresh_emotion_engine(
        target_dir,
        emotion_engine_source=emotion_engine_codex_source,
        emotion_style=emotion_style,
        emotion_engine_mode=emotion_engine_mode,
        retire_legacy_state=retire_legacy_state,
    )


def doctor_target(
    target_dir,
    fix=False,
    emotion_engine_codex_source=None,
    emotion_style=None,
    emotion_engine_mode=None,
    emotion_engine_source=None,
):
    """Inspect and optionally repair installed target projection drift."""
    target_dir = Path(target_dir)
    manifest = _load_manifest(target_dir)
    adapter = manifest.get("adapter")
    result = {
        "target_dir": str(target_dir),
        "adapter": adapter,
        "provenance": _target_provenance(target_dir, manifest),
        "ok": True,
        "issues": [],
        "warnings": _legacy_emotion_state_warnings(target_dir),
        "fixes": [],
    }

    layout_issues = _target_layout_doctor_issues(target_dir, manifest)
    if layout_issues and fix:
        fixed_paths = _fix_target_layout(target_dir, layout_issues)
        if fixed_paths:
            result["fixes"].append({
                "id": "target_layout_repaired",
                "paths": fixed_paths,
            })
            manifest = _load_manifest(target_dir)
            layout_issues = _target_layout_doctor_issues(target_dir, manifest)
    result["issues"].extend(layout_issues)

    lock_issues = _artifact_lock_doctor_issues(target_dir, manifest)
    if lock_issues and fix:
        fixed_paths = _repair_managed_artifact_drift(target_dir, manifest, lock_issues)
        if fixed_paths:
            result["fixes"].append({
                "id": "managed_artifact_drift_repaired",
                "paths": fixed_paths,
            })
            manifest = _load_manifest(target_dir)
            lock_issues = _artifact_lock_doctor_issues(target_dir, manifest)
    result["issues"].extend(lock_issues)

    source = emotion_engine_source or emotion_engine_codex_source
    if not _emotion_engine_expected_in_target(manifest, target_dir):
        result["ok"] = not result["issues"]
        result["provenance"] = _target_provenance(target_dir, manifest)
        return result

    mode = emotion_engine_mode or _manifest_emotion_engine_mode(manifest)
    plan = (
        _prepare_emotion_engine_install(
            target_dir,
            source,
            adapter=adapter,
            force=True,
            emotion_style=emotion_style,
            emotion_engine_mode=mode,
            manifest=manifest,
        )
        if source
        else _prepare_installed_emotion_engine_plan(target_dir, adapter, mode, manifest)
    )
    issues = _emotion_engine_doctor_issues(target_dir, manifest, plan)
    result["issues"].extend(issues)
    result["ok"] = not result["issues"]
    if issues and fix and source:
        refresh_result = refresh_emotion_engine(
            target_dir,
            emotion_engine_source=source,
            emotion_style=emotion_style,
            emotion_engine_mode=mode,
        )
        refreshed_manifest = _load_manifest(target_dir)
        refreshed_plan = _prepare_emotion_engine_install(
            target_dir,
            source,
            adapter=adapter,
            force=True,
            emotion_style=emotion_style,
            emotion_engine_mode=mode,
            manifest=refreshed_manifest,
        )
        after_issues = _emotion_engine_doctor_issues(target_dir, refreshed_manifest, refreshed_plan)
        result["fixes"].append({
            "id": "emotion_engine_refreshed",
            "result": refresh_result,
        })
        result["after_issues"] = after_issues
        result["issues"] = (
            _target_layout_doctor_issues(target_dir, refreshed_manifest)
            + _artifact_lock_doctor_issues(target_dir, refreshed_manifest)
            + after_issues
        )
        result["warnings"] = _legacy_emotion_state_warnings(target_dir)
        result["ok"] = not result["issues"]
    elif issues and fix and not source:
        result["warnings"].append({
            "id": "emotion_engine_source_required_for_fix",
            "message": "diagnosis completed without upstream source; pass --emotion-engine-source to refresh managed runtime files",
        })
    result["provenance"] = _target_provenance(target_dir, _load_manifest(target_dir))
    return result


def _target_provenance(target_dir, manifest):
    target_dir = Path(target_dir)
    install = _read_install_provenance(target_dir)
    if install and install.get("source_pack_path"):
        install = dict(install)
        install["source_pack_available"] = Path(install["source_pack_path"]).is_dir()
    spec_path = target_dir / SPEC_PATH
    lock_path = target_dir / LOCK_PATH
    return {
        "character_slug": manifest.get("character", {}).get("slug"),
        "source_provenance": copy.deepcopy(manifest.get("source_provenance")),
        "install_provenance": install,
        "installed_spec_sha256": _file_sha256(spec_path) if spec_path.is_file() else None,
        "installed_lock_sha256": _file_sha256(lock_path) if lock_path.is_file() else None,
    }


def _legacy_emotion_state_warnings(target_dir):
    target_dir = Path(target_dir)
    canonical_present = (target_dir / EMOTION_ENGINE_STATE_PATH).is_file()
    warnings_list = []
    for rel_path in EMOTION_ENGINE_LEGACY_STATE_PATHS:
        if not (target_dir / rel_path).is_file():
            continue
        warnings_list.append({
            "id": "emotion_engine_legacy_state_present",
            "path": rel_path,
            "message": (
                "legacy Emotion Engine state remains beside the canonical state; "
                "review it and use --retire-legacy-state during an Emotion Engine install or refresh to rename it as a backup"
                if canonical_present
                else "legacy Emotion Engine state is present without the canonical state"
            ),
        })
    return warnings_list


def migrate_target(
    source_target_dir,
    target_dir,
    to_adapter,
    mechanism_path=None,
    parameters=None,
    pack_dir=None,
    force=False,
    include_emotion_state=True,
    slug=None,
    upgrade_adapter_support=True,
    emotion_engine_codex_source=None,
    emotion_style=None,
    emotion_engine_mode=None,
    emotion_engine_source=None,
    accept_degraded=False,
):
    """Plan and apply an installed-target migration for programmatic callers."""
    plan = plan_migration(
        source_target_dir,
        target_dir,
        to_adapter,
        mechanism_path=mechanism_path,
        parameters=parameters,
        pack_dir=pack_dir,
        force=force,
        include_emotion_state=include_emotion_state,
        slug=slug,
        upgrade_adapter_support=upgrade_adapter_support,
        emotion_engine_codex_source=emotion_engine_codex_source,
        emotion_engine_source=emotion_engine_source,
        emotion_style=emotion_style,
        emotion_engine_mode=emotion_engine_mode,
    )
    return apply_migration(plan, accept_degraded=accept_degraded)


def plan_migration(
    source_target_dir,
    target_dir,
    to_adapter,
    mechanism_path=None,
    parameters=None,
    pack_dir=None,
    force=False,
    include_emotion_state=True,
    slug=None,
    upgrade_adapter_support=True,
    emotion_engine_codex_source=None,
    emotion_style=None,
    emotion_engine_mode=None,
    emotion_engine_source=None,
):
    """Build a deterministic migration plan without writing files."""
    source_target_dir = Path(source_target_dir)
    target_dir = Path(target_dir)
    resolved_pack_dir = Path(pack_dir) if pack_dir else None
    if to_adapter not in SUPPORTED_INSTALL_ADAPTERS:
        raise PackwrightValidationError([f"unsupported adapter: {to_adapter}"])
    _validate_migration_locations(source_target_dir, target_dir, resolved_pack_dir)

    source_manifest = _load_manifest(source_target_dir)
    from_adapter = source_manifest.get("adapter")
    if from_adapter not in SUPPORTED_INSTALL_ADAPTERS:
        raise PackwrightValidationError([f"source target adapter is unsupported: {from_adapter!r}"])
    resolved_emotion_engine_source = _coalesce_emotion_engine_source(
        emotion_engine_source,
        emotion_engine_codex_source,
    )
    emotion_state_source = (
        _select_emotion_state_source(source_target_dir)
        if include_emotion_state
        else None
    )

    mechanism_file = _resolve_migration_mechanism_path(source_target_dir, source_manifest, mechanism_path)
    embedded_mechanism = mechanism_file == source_target_dir / SPEC_PATH
    if embedded_mechanism:
        mechanism = load_embedded_spec(source_target_dir)
    else:
        mechanism = load_mechanism(mechanism_file)
    mechanism_changes = _prepare_migration_mechanism(
        mechanism,
        to_adapter=to_adapter,
        slug=slug,
        upgrade_adapter_support=upgrade_adapter_support,
    )
    resolved_parameters = _migration_resolved_parameters(source_manifest, parameters)
    resolved = (
        normalize_mechanism(mechanism)
        if embedded_mechanism and not parameters
        else resolve_mechanism(mechanism, resolved_parameters)
    )
    pack = _compile_pack_for_adapter(
        to_adapter,
        resolved,
        references={
            "source_mechanism": str(mechanism_file),
            "migration_source_target": str(source_target_dir),
            "migration_from_adapter": from_adapter,
        },
    )
    initial_score = _score_migration_pack(resolved, pack, to_adapter)
    pack = embed_pack_metadata(pack, resolved, initial_score)

    changes, warnings = _plan_migration_changes(
        source_target_dir,
        target_dir,
        source_manifest,
        pack,
        resolved,
        from_adapter,
        to_adapter,
        include_emotion_state=include_emotion_state,
        emotion_engine_source=resolved_emotion_engine_source,
        emotion_state_source=emotion_state_source,
        emotion_style=emotion_style,
        emotion_engine_mode=emotion_engine_mode,
    )
    planned_score = _score_migration_pack(resolved, pack, to_adapter)
    conflicts = _migration_plan_conflicts(target_dir, resolved_pack_dir)
    ready = planned_score["passed"] and (force or not conflicts)
    required_confirmations = _migration_required_confirmations(changes)
    report = {
        "schema": MIGRATION_SCHEMA,
        "status": "planned",
        "ready": ready,
        "force": bool(force),
        "source": {
            "target_dir": str(source_target_dir),
            "adapter": from_adapter,
            "mechanism": str(mechanism_file),
        },
        "destination": {
            "target_dir": str(target_dir),
            "adapter": to_adapter,
            "pack_dir": str(resolved_pack_dir) if resolved_pack_dir else None,
        },
        "character": {
            "name": resolved.get("identity", {}).get("name"),
            "slug": character_slug(resolved),
        },
        "changes": changes,
        "summary": {name: len(items) for name, items in changes.items()},
        "conflicts": conflicts,
        "required_confirmations": required_confirmations,
        "mechanism_changes": mechanism_changes,
        "emotion_engine_state": _migration_emotion_state_report(
            emotion_state_source,
            runtime_active=_migrate_should_include_emotion_engine(resolved_emotion_engine_source),
        ),
        "score": {
            "planned": planned_score,
            "installed": None,
        },
        "warnings": warnings,
    }
    return MigrationPlan(
        source_target_dir=source_target_dir,
        target_dir=target_dir,
        from_adapter=from_adapter,
        to_adapter=to_adapter,
        mechanism_file=mechanism_file,
        resolved=resolved,
        pack=pack,
        source_manifest=source_manifest,
        pack_dir=resolved_pack_dir,
        force=force,
        include_emotion_state=include_emotion_state,
        emotion_engine_source=resolved_emotion_engine_source,
        emotion_state_source=emotion_state_source,
        emotion_style=emotion_style,
        emotion_engine_mode=emotion_engine_mode,
        report=report,
    )


def apply_migration(plan, accept_degraded=False):
    """Apply a previously prepared MigrationPlan and return its receipt."""
    if not isinstance(plan, MigrationPlan):
        raise TypeError("apply_migration expects a MigrationPlan")
    degraded = plan.report["changes"].get("degraded", [])
    if degraded and not accept_degraded:
        raise PackwrightValidationError([
            "migration contains unmanaged runtime automation that will not be reproduced in the destination",
            "review the degraded receipt and explicitly accept the behavior gap before applying",
        ])
    planned_score = plan.report["score"]["planned"]
    if not planned_score["passed"]:
        raise PackwrightValidationError(["destination adapter pack failed its planned checker score"])

    source_integrity = _verify_migration_source(plan.report["changes"], plan.source_target_dir)
    if not source_integrity["passed"]:
        raise PackwrightValidationError(
            [
                "migration source changed after the plan was prepared; prepare a new plan before writing",
                *[issue["message"] for issue in source_integrity["issues"]],
            ]
        )
    conflicts = _migration_plan_conflicts(plan.target_dir, plan.pack_dir)
    if conflicts and not plan.force:
        raise PackwrightValidationError(
            [
                "migration destination contains files that would be overwritten; rerun with --force after reviewing them",
                *[f"existing {item['location']} artifact: {item['path']}" for item in conflicts],
            ]
        )

    temp_pack = None
    pack_stale_removed = []
    if plan.pack_dir:
        install_pack_dir = plan.pack_dir
        pack_stale_removed = _write_pack_to_dir(plan.pack, install_pack_dir, force=plan.force)
    else:
        temp_pack = tempfile.TemporaryDirectory()
        install_pack_dir = Path(temp_pack.name)
        _write_pack_to_dir(plan.pack, install_pack_dir, force=True)

    try:
        install_result = install_pack(
            install_pack_dir,
            plan.target_dir,
            adapter=plan.to_adapter,
            force=plan.force,
            include_emotion_engine=_migrate_should_include_emotion_engine(plan.emotion_engine_source),
            emotion_engine_source=plan.emotion_engine_source,
            emotion_state_source=plan.emotion_state_source,
            emotion_style=plan.emotion_style,
            emotion_engine_mode=plan.emotion_engine_mode,
            provenance={
                "operation": "migration",
                "source_pack_path": str(plan.pack_dir.resolve()) if plan.pack_dir else None,
                "source_target_dir": str(plan.source_target_dir.resolve()),
                "from_adapter": plan.from_adapter,
            },
        )
        portable_result = _copy_migrated_portable_state(
            plan.source_target_dir,
            plan.target_dir,
            plan.resolved,
            plan.to_adapter,
            emotion_engine_active=_migrate_should_include_emotion_engine(plan.emotion_engine_source),
        )
        state_snapshots = _copy_emotion_state_snapshot(
            plan.target_dir,
            plan.emotion_state_source,
        )
    finally:
        if temp_pack is not None:
            temp_pack.cleanup()

    integrity = _verify_migration_integrity(plan.report["changes"], plan.target_dir)
    installed_pack = _read_installed_pack(plan.target_dir)
    installed_score = _score_migration_pack(plan.resolved, installed_pack, plan.to_adapter)
    receipt = plan.to_dict()
    receipt.update(
        {
            "status": "applied_with_degradations" if degraded else "applied",
            "ready": True,
            "ok": integrity["passed"] and installed_score["passed"],
            "integrity": integrity,
            "source_integrity": source_integrity,
            "accepted_degradations": copy.deepcopy(degraded) if accept_degraded else [],
            "source_target_dir": str(plan.source_target_dir),
            "target_dir": str(plan.target_dir),
            "from_adapter": plan.from_adapter,
            "to_adapter": plan.to_adapter,
            "mechanism": str(plan.mechanism_file),
            "pack_dir": str(install_pack_dir) if plan.pack_dir else None,
            "installed_artifacts": install_result["installed_artifacts"],
            "stale_removed": sorted(set(pack_stale_removed + install_result.get("stale_removed", []))),
            "portable_state": portable_result["copied"],
            "unmanaged_skills": sorted(
                item["path"]
                for item in plan.report["changes"]["carried"]
                if item["path"].startswith("skills/")
            ),
            "memory_projection": portable_result["rewritten"],
            "state_snapshots": state_snapshots,
            "emotion_engine_state": _migration_emotion_state_report(
                plan.emotion_state_source,
                runtime_active=_migrate_should_include_emotion_engine(plan.emotion_engine_source),
            ),
            "runtime_exclusions": _migration_runtime_exclusions(
                plan.source_target_dir,
                plan.source_manifest,
                plan.from_adapter,
                plan.to_adapter,
                state_snapshots,
            ),
        }
    )
    receipt["score"]["installed"] = installed_score
    return receipt


def plan_reconcile(target_dir, mechanism_path, parameters=None):
    """Plan an in-place canonical mechanism upgrade without writing the target."""
    target_dir = Path(target_dir)
    mechanism_input = Path(mechanism_path).resolve()
    mechanism_file = (
        mechanism_input / "mechanism.yaml" if mechanism_input.is_dir() else mechanism_input
    )
    installed_manifest = _load_manifest(target_dir)
    adapter = installed_manifest.get("adapter")
    if adapter not in SUPPORTED_INSTALL_ADAPTERS:
        raise PackwrightValidationError([f"target adapter is unsupported: {adapter!r}"])
    mechanism = load_mechanism(mechanism_input)
    resolved = resolve_mechanism(mechanism, parameters or {})
    desired_commit = _git_commit_for(mechanism_file)
    pack = _compile_pack_for_adapter(
        adapter,
        resolved,
        references={"source_mechanism": str(mechanism_file)},
    )
    manifest = json.loads(pack["manifest.json"])
    manifest["source_provenance"] = {
        "mechanism_path": str(mechanism_file),
        "git_commit": desired_commit,
    }
    pack["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    pack = _augment_reconcile_pack_with_installed_sidecars(
        pack,
        target_dir,
        installed_manifest,
    )
    planned_score = _score_migration_pack(resolved, pack, adapter)
    pack = embed_pack_metadata(pack, resolved, planned_score)
    pack = _normalize_reconcile_pack_lock(pack)
    installed_spec_path = resolve_source_path(target_dir, SPEC_PATH, "installed canonical spec")
    from_spec_hash = _sha256_bytes(installed_spec_path.read_bytes())
    to_spec_hash = _sha256_bytes(pack[SPEC_PATH].encode("utf-8"))
    changes, conflicts = _plan_reconcile_changes(target_dir, installed_manifest, pack)
    degraded = changes["degraded"]
    required_confirmations = []
    if degraded:
        required_confirmations.append(
            {
                "id": "accept_degraded_runtime_automation",
                "kind": "degradation",
                "automations": [item["id"] for item in degraded],
                "message": "accept destination runtime automation capability gaps",
            }
        )
    ready = planned_score["passed"] and not conflicts
    report = {
        "schema": RECONCILE_SCHEMA,
        "status": "planned",
        "ready": ready,
        "target_dir": str(target_dir),
        "adapter": adapter,
        "mechanism": str(mechanism_file),
        "spec": {"from_sha256": from_spec_hash, "to_sha256": to_spec_hash},
        "git": {
            "from_commit": installed_manifest.get("source_provenance", {}).get("git_commit"),
            "to_commit": desired_commit,
            "role": "provenance_only",
        },
        "changes": changes,
        "summary": {name: len(items) for name, items in changes.items()},
        "conflicts": conflicts,
        "required_confirmations": required_confirmations,
        "score": {"planned": planned_score, "installed": None},
    }
    return ReconcilePlan(
        target_dir=target_dir,
        mechanism_file=mechanism_file,
        resolved=resolved,
        pack=pack,
        installed_manifest=installed_manifest,
        mechanism_sha256=_file_sha256(mechanism_file),
        report=report,
    )


def apply_reconcile(plan, accept_degraded=False):
    """Apply a reviewed ReconcilePlan and write a durable local receipt."""
    if not isinstance(plan, ReconcilePlan):
        raise TypeError("apply_reconcile expects a ReconcilePlan")
    if not plan.report["ready"]:
        raise PackwrightValidationError(["reconcile plan has unresolved conflicts"])
    degraded = plan.report["changes"]["degraded"]
    if degraded and not accept_degraded:
        raise PackwrightValidationError([
            "reconcile contains destination runtime automation capability gaps",
            "review them and explicitly accept degraded behavior before applying",
        ])
    if _file_sha256(plan.mechanism_file) != plan.mechanism_sha256:
        raise PackwrightValidationError([
            "canonical mechanism changed after reconcile planning; prepare a new plan"
        ])

    with tempfile.TemporaryDirectory() as temp_dir:
        pack_dir = Path(temp_dir)
        _write_pack_to_dir(plan.pack, pack_dir, force=True)
        install_result = install_pack(
            pack_dir,
            plan.target_dir,
            adapter=plan.report["adapter"],
            force=True,
            persist_provenance=False,
        )
    if emotion_engine_expected(plan.installed_manifest):
        for rel_path in (EMOTION_ENGINE_WRAPPER_PATH, EMOTION_ENGINE_MCP_WRAPPER_PATH):
            executable = plan.target_dir / rel_path
            if executable.is_file():
                _make_executable(executable)
        _ensure_emotion_section(
            plan.target_dir,
            plan.report["adapter"],
            _manifest_emotion_engine_mode(plan.installed_manifest),
        )
        _refresh_artifact_lock(plan.target_dir)

    installed_score = _score_migration_pack(
        plan.resolved, plan.pack, plan.report["adapter"]
    )
    installed_spec = resolve_source_path(
        plan.target_dir, SPEC_PATH, "reconciled canonical spec"
    )
    installed_spec_hash = _sha256_bytes(installed_spec.read_bytes())
    doctor = doctor_target(plan.target_dir)
    ok = (
        installed_score["passed"]
        and installed_spec_hash == plan.report["spec"]["to_sha256"]
        and doctor["ok"]
    )
    receipt = plan.to_dict()
    receipt.update(
        {
            "status": "applied_with_degradations" if degraded else "applied",
            "ok": ok,
            "accepted_degradations": copy.deepcopy(degraded) if accept_degraded else [],
            "installed_artifacts": install_result["installed_artifacts"],
            "preserved_instance_state": receipt["changes"]["preserved_instance_state"],
            "installed_spec_sha256": installed_spec_hash,
            "doctor": doctor,
            "applied_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    receipt["score"]["installed"] = installed_score
    receipt_dir = plan.target_dir / ".packwright" / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"reconcile-{plan.report['spec']['to_sha256'][:12]}.json"
    receipt["receipt"] = str(receipt_path)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _plan_reconcile_changes(target_dir, installed_manifest, pack):
    desired_manifest = json.loads(pack["manifest.json"])
    desired_artifacts = set(_manifest_artifacts(desired_manifest))
    installed_artifacts = set(_manifest_artifacts(installed_manifest))
    managed_updates = []
    safe_memory = []
    preserved_state = []
    manual_merges = []
    conflicts = []
    config_paths = automation_config_paths(desired_manifest)

    for rel_path in sorted(desired_artifacts):
        desired = pack.get(rel_path)
        target = target_dir / rel_path
        if _is_portable_path(rel_path):
            if target.is_file():
                preserved_state.append({"path": rel_path, "status": "preserved"})
            elif desired is not None:
                safe_memory.append({"path": rel_path, "operation": "create_missing_scaffold"})
            continue
        if desired is None:
            continue
        if not target.is_file():
            managed_updates.append({"path": rel_path, "operation": "add"})
            continue
        if rel_path in config_paths:
            try:
                existing_text = target.read_text(encoding="utf-8")
                merge_managed_hook_config(existing_text, desired)
                same = managed_hook_fragment_digest(existing_text) == managed_hook_fragment_digest(desired)
                if _json_has_unmanaged_hook_entries(existing_text):
                    manual_merges.append(
                        {
                            "path": rel_path,
                            "operation": "preserve_user_entries_and_replace_packwright_entries",
                        }
                    )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                conflicts.append({"path": rel_path, "message": f"cannot safely merge hook JSON: {exc}"})
                continue
        else:
            same = target.read_bytes() == desired.encode("utf-8")
        if not same:
            managed_updates.append({"path": rel_path, "operation": "update"})

    installed_sidecars = (
        set(emotion_engine_artifacts(installed_manifest.get("adapter")))
        if emotion_engine_expected(installed_manifest)
        else set()
    )
    removed = [
        {"path": path, "operation": "remove_stale_managed_projection"}
        for path in sorted(installed_artifacts - desired_artifacts)
        if not _is_portable_path(path)
        and path != EMOTION_ENGINE_STATE_PATH
        and path not in installed_sidecars
    ]
    preserved_sidecars = [
        {"path": path, "status": "preserved_installed_sidecar"}
        for path in sorted(installed_sidecars)
        if (target_dir / path).is_file()
    ]
    feature = desired_manifest.get("features", {}).get("automations", {})
    records = feature.get("records", []) if isinstance(feature, dict) else []
    degraded = [
        copy.deepcopy(record)
        for record in records
        if str(record.get("status", "")).startswith("unavailable_")
    ]
    pending_activation = [
        copy.deepcopy(record)
        for record in records
        if record.get("status") == "projected_pending_user_review"
    ]
    return (
        {
            "managed_projection_updates": managed_updates,
            "safe_structural_memory_migrations": safe_memory,
            "preserved_instance_state": preserved_state,
            "manual_merges": manual_merges,
            "removed_managed_artifacts": removed,
            "preserved_sidecars": preserved_sidecars,
            "degraded": degraded,
            "pending_activation": pending_activation,
        },
        conflicts,
    )


def _json_has_unmanaged_hook_entries(text):
    data = json.loads(text)
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    marker = "packwright_automation.py"
    return any(
        marker not in json.dumps(entry, sort_keys=True)
        for entries in hooks.values()
        if isinstance(entries, list)
        for entry in entries
    )


def _git_commit_for(path):
    current = Path(path).resolve().parent
    git_dir = None
    for parent in (current, *current.parents):
        marker = parent / ".git"
        if marker.is_dir():
            git_dir = marker
            break
        if marker.is_file():
            try:
                declaration = marker.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                return None
            if declaration.startswith("gitdir:"):
                candidate = declaration.split(":", 1)[1].strip()
                git_dir = (parent / candidate).resolve()
                break
    if git_dir is None:
        return None
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        try:
            value = (git_dir / ref).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            value = _packed_git_ref(git_dir, ref)
    else:
        value = head
    return value.lower() if _is_git_commit(value) else None


def _packed_git_ref(git_dir, ref):
    try:
        lines = (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    suffix = f" {ref}"
    for line in lines:
        if not line.startswith(("#", "^")) and line.endswith(suffix):
            return line.split(" ", 1)[0]
    return None


def _is_git_commit(value):
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _augment_reconcile_pack_with_installed_sidecars(pack, target_dir, installed_manifest):
    if not emotion_engine_expected(installed_manifest):
        return dict(pack)
    enriched = dict(pack)
    adapter = installed_manifest.get("adapter")
    manifest = json.loads(enriched["manifest.json"])
    sidecar_paths = []
    for rel_path in emotion_engine_artifacts(adapter):
        path = target_dir / rel_path
        if path.is_file():
            enriched[rel_path] = path.read_text(encoding="utf-8")
            sidecar_paths.append(rel_path)
    manifest["features"]["emotion_engine"] = copy.deepcopy(
        installed_manifest.get("features", {}).get("emotion_engine", {})
    )
    if "sidecars" in installed_manifest:
        manifest["sidecars"] = copy.deepcopy(installed_manifest["sidecars"])
    for key in ("emotion_engine_runtime", "emotion_engine_mode"):
        if key in installed_manifest.get("boundaries", {}):
            manifest.setdefault("boundaries", {})[key] = installed_manifest["boundaries"][key]
    manifest["artifacts"] = sorted(set(manifest.get("artifacts", [])) | set(sidecar_paths))
    entry_path = adapter_entry(adapter)
    if entry_path in enriched:
        enriched[entry_path], _ = _render_emotion_section(
            enriched[entry_path],
            adapter,
            _manifest_emotion_engine_mode(installed_manifest),
        )
    enriched["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    return enriched


def _normalize_reconcile_pack_lock(pack):
    normalized = dict(pack)
    manifest = json.loads(normalized["manifest.json"])
    artifacts = {}
    for rel_path in _manifest_artifacts(manifest):
        if rel_path in {LOCK_PATH, EMOTION_ENGINE_STATE_PATH}:
            continue
        content = normalized.get(rel_path)
        if content is None:
            continue
        if is_managed_automation_config(manifest, rel_path):
            artifacts[rel_path] = {
                "mode": "managed_json_hooks",
                "sha256": managed_hook_fragment_digest(content),
            }
        else:
            artifacts[rel_path] = _sha256_bytes(content.encode("utf-8"))
    normalized[LOCK_PATH] = json.dumps(
        {"schema": "packwright-lock/v1", "artifacts": artifacts},
        indent=2,
        sort_keys=True,
    ) + "\n"
    return normalized


def _plan_migration_changes(
    source_target_dir,
    target_dir,
    source_manifest,
    pack,
    resolved,
    from_adapter,
    to_adapter,
    include_emotion_state,
    emotion_engine_source,
    emotion_state_source,
    emotion_style,
    emotion_engine_mode,
):
    carried = []
    rewritten = []
    emotion_engine_active = _migrate_should_include_emotion_engine(emotion_engine_source)
    source_files = _portable_source_files(source_target_dir)
    for rel_path, source_path in source_files.items():
        source_bytes = source_path.read_bytes()
        if rel_path in {"memory/index.md", "memory/pinned.md", "memory/source-map.md"}:
            source_text = source_bytes.decode("utf-8")
            projected = project_memory_file(
                resolved,
                to_adapter,
                rel_path,
                source_text,
                emotion_engine_active=emotion_engine_active,
            )
            projected_bytes = projected.encode("utf-8")
            if projected_bytes != source_bytes:
                rewritten.append(
                    {
                        "path": rel_path,
                        "source_sha256": _sha256_bytes(source_bytes),
                        "destination_sha256": _sha256_bytes(projected_bytes),
                        "reason": f"adapter routing lines projected for {to_adapter}",
                    }
                )
                continue
        carried.append(
            {
                "path": rel_path,
                "sha256": _sha256_bytes(source_bytes),
                "reason": (
                    "carried unmanaged root skill; not a Packwright-managed projection"
                    if rel_path.startswith("skills/")
                    else "copied without content changes"
                ),
            }
        )

    warnings = []
    if include_emotion_state and emotion_state_source:
        carried.append(
            {
                "path": EMOTION_ENGINE_STATE_PATH,
                "source_path": str(emotion_state_source.relative_to(source_target_dir.resolve())),
                "sha256": _file_sha256(emotion_state_source),
                "reason": "copied as project-local runtime state snapshot",
            }
        )
        if not emotion_engine_active:
            warnings.append(
                {
                    "id": "emotion_state_snapshot_inert",
                    "path": EMOTION_ENGINE_STATE_PATH,
                    "message": "state is carried as a recovery snapshot because no Emotion Engine source was supplied",
                }
            )

    degraded = _plan_runtime_automation_degradations(
        source_target_dir,
        source_manifest,
        from_adapter,
        to_adapter,
    )
    if degraded:
        warnings.append(
            {
                "id": "runtime_automation_degraded",
                "paths": [item["path"] for item in degraded],
                "message": (
                    "unmanaged runtime automation is outside the installed canonical spec; "
                    "it will be left behind unless the user explicitly accepts the behavior gap"
                ),
            }
        )

    carried_paths = {item["path"] for item in carried}
    rewritten_paths = {item["path"] for item in rewritten}
    degraded_paths = {item["path"] for item in degraded}
    target_manifest = json.loads(pack["manifest.json"])
    generated_by_path = {}
    for rel_path in _manifest_artifacts(target_manifest):
        if rel_path in carried_paths or rel_path in rewritten_paths:
            continue
        entry = {
            "path": rel_path,
            "reason": (
                "generated portable scaffold because the source target has no corresponding file"
                if _is_portable_path(rel_path)
                else f"compiled for the {to_adapter} adapter"
            ),
        }
        generated_by_path[rel_path] = entry

    if emotion_engine_active:
        sidecar_plan = _prepare_emotion_engine_install(
            target_dir,
            emotion_engine_source,
            adapter=to_adapter,
            force=True,
            emotion_style=emotion_style,
            emotion_engine_mode=emotion_engine_mode or _manifest_emotion_engine_mode(target_manifest),
            manifest=target_manifest,
        )
        for rel_path in sidecar_plan["projection"]:
            generated_by_path[rel_path] = {
                "path": rel_path,
                "reason": "generated adapter-native Emotion Engine projection",
            }
        generated_by_path[sidecar_plan["mcp_config"]["path"]] = {
            "path": sidecar_plan["mcp_config"]["path"],
            "reason": "merged project-local Emotion Engine MCP entry",
        }
        if EMOTION_ENGINE_STATE_PATH not in carried_paths:
            generated_by_path[EMOTION_ENGINE_STATE_PATH] = {
                "path": EMOTION_ENGINE_STATE_PATH,
                "reason": "initialized Emotion Engine runtime state",
            }

    excluded = _plan_migration_exclusions(
        source_target_dir,
        source_manifest,
        from_adapter,
        to_adapter,
        carried_paths | rewritten_paths | degraded_paths,
        include_emotion_state,
    )
    return (
        {
            "generated": sorted(generated_by_path.values(), key=lambda item: item["path"]),
            "carried": sorted(carried, key=lambda item: item["path"]),
            "rewritten": sorted(rewritten, key=lambda item: item["path"]),
            "degraded": degraded,
            "excluded": excluded,
        },
        warnings,
    )


def _portable_source_files(source_target_dir):
    result = {}
    for root_name in PORTABLE_STATE_DIRS:
        root = source_target_dir / root_name
        if not root.exists():
            continue
        resolve_source_path(source_target_dir, root_name, "portable state root", require_file=False)
        if not root.is_dir():
            raise PackwrightValidationError([f"source portable state path is not a directory: {root}"])
        for path in sorted(root.rglob("*")):
            rel_path = str(path.relative_to(source_target_dir))
            resolved = resolve_source_path(
                source_target_dir,
                rel_path,
                "portable state source",
                require_file=False,
            )
            if resolved.is_file():
                result[rel_path] = resolved
    return result


def _plan_migration_exclusions(
    source_target_dir,
    source_manifest,
    from_adapter,
    to_adapter,
    handled_paths,
    include_emotion_state,
):
    source_artifacts = set(_manifest_artifacts(source_manifest))
    source_artifacts.update(
        artifact for artifact in emotion_engine_artifacts(from_adapter) if (source_target_dir / artifact).is_file()
    )
    source_artifacts.update(
        path for path in EMOTION_ENGINE_LEGACY_STATE_PATHS if (source_target_dir / path).is_file()
    )
    source_entry = _adapter_entry_artifact(source_manifest, from_adapter)
    excluded = []
    for rel_path in sorted(source_artifacts - set(handled_paths)):
        if rel_path == source_entry:
            item = {
                "id": "source_runtime_entry_replaced",
                "path": rel_path,
                "reason": f"replaced by the {to_adapter} adapter entry",
            }
        elif rel_path == "manifest.json":
            item = {
                "id": "source_manifest_replaced",
                "path": rel_path,
                "reason": "replaced by the destination adapter manifest",
            }
        elif rel_path in {EMOTION_ENGINE_STATE_PATH, *EMOTION_ENGINE_LEGACY_STATE_PATHS} and not include_emotion_state:
            item = {
                "id": "emotion_state_excluded",
                "path": rel_path,
                "reason": "excluded by --no-emotion-state",
            }
        elif rel_path in set(emotion_engine_artifacts(from_adapter)) - {EMOTION_ENGINE_STATE_PATH}:
            item = {
                "id": "source_emotion_engine_projection_excluded",
                "path": rel_path,
                "reason": f"the {to_adapter} target receives its own runtime projection",
            }
        else:
            item = {
                "id": "source_runtime_artifact_excluded",
                "path": rel_path,
                "reason": f"source {from_adapter} projection is not copied; destination files are generated",
            }
        excluded.append(item)
    return excluded


def _plan_runtime_automation_degradations(source_target_dir, source_manifest, from_adapter, to_adapter):
    feature = source_manifest.get("features", {}).get("automations", {})
    managed_paths = set()
    if isinstance(feature, dict):
        for key in ("config", "runner"):
            value = feature.get(key, {})
            if isinstance(value, dict) and isinstance(value.get("path"), str):
                managed_paths.add(value["path"])
    return [
        {
            **asset,
            "id": "unmanaged_runtime_automation",
            "reason_code": "unmanaged_requires_canonicalization",
            "reason": (
                f"{from_adapter} runtime automation is outside the installed canonical spec; "
                f"it will not be reproduced for {to_adapter} until it is reviewed as a canonical change"
            ),
            "source_adapter": from_adapter,
            "destination_adapter": to_adapter,
            "required_decision": "accept_behavior_gap",
        }
        for asset in discover_unmanaged_runtime_automation_assets(
            source_target_dir, from_adapter, managed_paths=managed_paths
        )
    ]


def _migration_required_confirmations(changes):
    degraded = changes.get("degraded", [])
    if not degraded:
        return []
    return [
        {
            "id": "accept_degraded_runtime_automation",
            "kind": "degradation",
            "paths": [item["path"] for item in degraded],
            "message": (
                "accept that unmanaged source runtime automation will not be reproduced "
                "in the destination"
            ),
        }
    ]


def _migration_plan_conflicts(target_dir, pack_dir):
    conflicts = _migration_directory_conflicts(target_dir, "target")
    if pack_dir:
        conflicts.extend(_migration_directory_conflicts(pack_dir, "pack"))
    return conflicts


def _migration_directory_conflicts(path, location):
    if not path.exists():
        return []
    if not path.is_dir():
        return [{"location": location, "path": "."}]
    return [{"location": location, "path": child.name} for child in sorted(path.iterdir())]


def _validate_migration_locations(source_target_dir, target_dir, pack_dir):
    if _paths_overlap(source_target_dir, target_dir):
        raise PackwrightValidationError(["source and destination targets must be separate, non-nested directories"])
    if pack_dir and (
        _paths_overlap(source_target_dir, pack_dir)
        or _paths_overlap(target_dir, pack_dir)
    ):
        raise PackwrightValidationError(["migration pack directory must be separate from source and destination targets"])


def _paths_overlap(first, second):
    return _path_is_within(first, second) or _path_is_within(second, first)


def _path_is_within(path, root):
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _verify_migration_source(changes, source_target_dir):
    checks = []
    issues = []
    for item in changes["carried"]:
        path = source_target_dir / item.get("source_path", item["path"])
        actual = _file_sha256(path) if path.is_file() else None
        passed = actual == item["sha256"]
        checks.append({"path": item["path"], "passed": passed})
        if not passed:
            issues.append({"path": item["path"], "message": f"source changed: {item['path']}"})
    for item in changes["rewritten"]:
        path = source_target_dir / item["path"]
        actual = _file_sha256(path) if path.is_file() else None
        passed = actual == item["source_sha256"]
        checks.append({"path": item["path"], "passed": passed})
        if not passed:
            issues.append({"path": item["path"], "message": f"source changed: {item['path']}"})
    for item in changes.get("degraded", []):
        path = source_target_dir / item["path"]
        actual = _file_sha256(path) if path.is_file() else None
        passed = actual == item["sha256"]
        checks.append({"path": item["path"], "passed": passed})
        if not passed:
            issues.append({"path": item["path"], "message": f"source changed: {item['path']}"})
    return {"passed": not issues, "checked": len(checks), "issues": issues}


def _verify_migration_integrity(changes, target_dir):
    checks = []
    issues = []
    expected = [
        (item["path"], item["sha256"], "carried")
        for item in changes["carried"]
    ] + [
        (item["path"], item["destination_sha256"], "rewritten")
        for item in changes["rewritten"]
    ]
    for rel_path, expected_hash, category in expected:
        path = target_dir / rel_path
        actual = _file_sha256(path) if path.is_file() else None
        passed = actual == expected_hash
        checks.append({"path": rel_path, "category": category, "passed": passed})
        if not passed:
            issues.append(
                {
                    "path": rel_path,
                    "category": category,
                    "message": f"destination hash does not match the planned {category} content",
                }
            )
    return {"passed": not issues, "checked": len(checks), "issues": issues}


def _read_installed_pack(target_dir):
    manifest = _load_manifest(target_dir)
    pack = {}
    for rel_path in _manifest_artifacts(manifest):
        path = resolve_source_path(target_dir, rel_path, "installed artifact")
        pack[rel_path] = path.read_text(encoding="utf-8")
    return pack


def _score_migration_pack(resolved, pack, adapter):
    from packwright.checker import score_mechanism

    return score_mechanism(resolved, pack, adapter=adapter)


def _is_portable_path(rel_path):
    return any(rel_path == root or rel_path.startswith(f"{root}/") for root in PORTABLE_STATE_DIRS)


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path):
    return _sha256_bytes(path.read_bytes())


def _artifact_lock_enabled(manifest):
    metadata = manifest.get("packwright", {}) if isinstance(manifest, dict) else {}
    artifacts = manifest.get("artifacts", []) if isinstance(manifest, dict) else []
    return metadata.get("lock") == LOCK_PATH or (isinstance(artifacts, list) and LOCK_PATH in artifacts)


def _load_artifact_lock(target_dir):
    path = resolve_source_path(target_dir, LOCK_PATH, "artifact lock")
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackwrightValidationError([f"invalid artifact lock {path}: {exc}"])
    if not isinstance(lock, dict) or lock.get("schema") != "packwright-lock/v1":
        raise PackwrightValidationError([f"artifact lock has an unexpected schema: {path}"])
    artifacts = lock.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise PackwrightValidationError([f"artifact lock must contain a non-empty artifacts mapping: {path}"])
    normalized = {}
    issues = []
    for rel_path, digest in artifacts.items():
        try:
            relative = validate_relative_path(rel_path, "artifact lock path").as_posix()
        except PackwrightValidationError as exc:
            issues.extend(exc.issues)
            continue
        record = digest
        if isinstance(record, dict):
            if record.get("mode") != "managed_json_hooks":
                issues.append(f"artifact lock mode is unsupported: {rel_path}")
                continue
            digest = record.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
            issues.append(f"artifact lock digest must be a SHA-256 hex string: {rel_path}")
            continue
        normalized[relative] = (
            {"mode": "managed_json_hooks", "sha256": digest.lower()}
            if isinstance(record, dict)
            else digest.lower()
        )
    if issues:
        raise PackwrightValidationError(issues)
    return normalized


def _refresh_artifact_lock(target_dir):
    lock_path = target_dir / LOCK_PATH
    if not lock_path.is_file():
        return False
    manifest = _load_manifest(target_dir)
    artifacts = {}
    for rel_path in _manifest_artifacts(manifest):
        if rel_path in {LOCK_PATH, EMOTION_ENGINE_STATE_PATH}:
            continue
        path = resolve_source_path(target_dir, rel_path, "installed artifact")
        artifacts[rel_path] = _artifact_lock_record(manifest, rel_path, path)
    destination = resolve_destination_path(target_dir, LOCK_PATH, "artifact lock destination")
    destination.write_text(
        json.dumps({"schema": "packwright-lock/v1", "artifacts": artifacts}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return True


def _update_artifact_lock_paths(target_dir, rel_paths):
    lock_path = target_dir / LOCK_PATH
    if not lock_path.is_file():
        return False
    locked = _load_artifact_lock(target_dir)
    for rel_path in rel_paths:
        if rel_path == LOCK_PATH or _is_portable_path(rel_path) or rel_path == EMOTION_ENGINE_STATE_PATH:
            continue
        path = resolve_source_path(target_dir, rel_path, "managed artifact")
        manifest = _load_manifest(target_dir)
        locked[rel_path] = _artifact_lock_record(manifest, rel_path, path)
    destination = resolve_destination_path(target_dir, LOCK_PATH, "artifact lock destination")
    destination.write_text(
        json.dumps({"schema": "packwright-lock/v1", "artifacts": locked}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return True


def _artifact_lock_doctor_issues(target_dir, manifest):
    if not _artifact_lock_enabled(manifest):
        return []
    try:
        locked = _load_artifact_lock(target_dir)
    except PackwrightValidationError as exc:
        return [_doctor_issue("artifact_lock_invalid", LOCK_PATH, "; ".join(exc.issues))]

    issues = []
    for rel_path, expected_record in sorted(locked.items()):
        if rel_path == LOCK_PATH or _is_portable_path(rel_path) or rel_path == EMOTION_ENGINE_STATE_PATH:
            continue
        try:
            path = resolve_source_path(target_dir, rel_path, "managed artifact")
        except PackwrightValidationError as exc:
            issues.append(_doctor_issue("managed_artifact_missing_or_unsafe", rel_path, "; ".join(exc.issues)))
            continue
        try:
            actual_hash = _artifact_lock_actual_digest(expected_record, path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            issues.append(_doctor_issue("managed_artifact_unreadable", rel_path, f"cannot read managed artifact: {exc}"))
            continue
        if actual_hash != _artifact_lock_digest(expected_record):
            issues.append(_doctor_issue("managed_artifact_drift", rel_path, "managed artifact hash differs from .packwright/lock.json"))

    try:
        manifest_artifacts = _manifest_artifacts(manifest)
    except PackwrightValidationError:
        return issues
    for rel_path in manifest_artifacts:
        if (
            rel_path == LOCK_PATH
            or _is_portable_path(rel_path)
            or rel_path == EMOTION_ENGINE_STATE_PATH
            or rel_path in emotion_engine_artifacts(manifest.get("adapter"))
        ):
            continue
        if rel_path not in locked:
            issues.append(_doctor_issue("managed_artifact_untracked", rel_path, "managed artifact is not recorded in .packwright/lock.json"))
    return issues


def _repair_managed_artifact_drift(target_dir, manifest, issues):
    repairable_ids = {"managed_artifact_drift", "managed_artifact_missing_or_unsafe"}
    candidates = [issue["path"] for issue in issues if issue.get("id") in repairable_ids]
    if not candidates:
        return []
    canonical_inputs = {SPEC_PATH}
    canonical_inputs.update(path for path in candidates if path.startswith(".packwright/source/"))
    if canonical_inputs.intersection(candidates):
        return []

    try:
        locked = _load_artifact_lock(target_dir)
        resolved = load_embedded_spec(target_dir)
        adapter = manifest.get("adapter")
        expected = _compile_pack_for_adapter(adapter, resolved, {"source_mechanism": SPEC_PATH})
        receipt = _score_migration_pack(resolved, expected, adapter)
        expected = embed_pack_metadata(expected, resolved, receipt)
    except (OSError, ValueError, PackwrightValidationError, json.JSONDecodeError):
        return []

    fixed = []
    for rel_path in candidates:
        if rel_path.startswith(".packwright/source/") or rel_path == SPEC_PATH:
            continue
        content = expected.get(rel_path)
        expected_record = locked.get(rel_path)
        if content is None or expected_record is None:
            continue
        if isinstance(expected_record, dict):
            try:
                desired_hash = managed_hook_fragment_digest(content)
            except (json.JSONDecodeError, ValueError):
                continue
        else:
            desired_hash = _sha256_bytes(content.encode("utf-8"))
        if _artifact_lock_digest(expected_record) != desired_hash:
            continue
        destination = resolve_destination_path(target_dir, rel_path, "managed artifact repair destination")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(expected_record, dict) and destination.is_file():
            try:
                content = merge_managed_hook_config(
                    destination.read_text(encoding="utf-8"), content
                )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                continue
        destination.write_text(content, encoding="utf-8")
        if rel_path in HANDOFF_EXECUTABLE_ARTIFACTS:
            _make_executable(destination)
        fixed.append(rel_path)
    return sorted(set(fixed))


def _artifact_lock_record(manifest, rel_path, path):
    if is_managed_automation_config(manifest, rel_path):
        return {
            "mode": "managed_json_hooks",
            "sha256": managed_hook_fragment_digest(path.read_text(encoding="utf-8")),
        }
    return _file_sha256(path)


def _artifact_lock_digest(record):
    return record["sha256"] if isinstance(record, dict) else record


def _artifact_lock_actual_digest(record, path):
    if isinstance(record, dict) and record.get("mode") == "managed_json_hooks":
        return managed_hook_fragment_digest(path.read_text(encoding="utf-8"))
    return _file_sha256(path)


def _write_automation_baseline(target_dir, manifest):
    feature = manifest.get("features", {}).get("automations", {}) if isinstance(manifest, dict) else {}
    records = feature.get("records", []) if isinstance(feature, dict) else []
    if not any(record.get("producer") == "relocation_guard" for record in records if isinstance(record, dict)):
        return False
    destination = resolve_destination_path(
        target_dir, ".packwright/baseline-path", "automation relocation baseline"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(str(target_dir.resolve()) + "\n", encoding="utf-8")
    return True


def _load_manifest(pack_dir):
    try:
        manifest_path = resolve_source_path(pack_dir, "manifest.json", "adapter pack manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PackwrightValidationError([f"cannot read adapter pack manifest {manifest_path}: {exc}"])
    except json.JSONDecodeError as exc:
        raise PackwrightValidationError([f"invalid adapter pack manifest {manifest_path}: {exc}"])
    if not isinstance(manifest, dict):
        raise PackwrightValidationError([f"adapter pack manifest must be a mapping: {manifest_path}"])
    return manifest


def _resolve_migration_mechanism_path(source_target_dir, source_manifest, mechanism_path):
    embedded = source_target_dir / SPEC_PATH
    if mechanism_path is None and embedded.is_file():
        return embedded
    raw = mechanism_path or source_manifest.get("source_mechanism")
    if not raw:
        raise PackwrightValidationError([
            "source target manifest does not include source_mechanism; pass --mechanism explicitly"
        ])
    path = Path(raw)
    candidates = [path] if path.is_absolute() else [
        source_target_dir / path,
        source_target_dir.parent / path,
        Path.cwd() / path,
    ]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() or resolved.is_dir():
            return resolved
    checked = ", ".join(str(candidate) for candidate in candidates)
    raise PackwrightValidationError([f"cannot resolve migration mechanism {raw!r}; checked {checked}"])


def _prepare_migration_mechanism(data, to_adapter, slug=None, upgrade_adapter_support=True):
    changes = []
    if slug:
        normalized = normalize_slug(slug, default="")
        if not normalized or not is_valid_slug(normalized):
            raise PackwrightValidationError(["--slug must normalize to a lowercase ASCII slug"])
        data.setdefault("metadata", {})["slug"] = normalized
        data.setdefault("identity", {})["slug"] = normalized
        changes.append({"id": "slug_override", "slug": normalized})
    if upgrade_adapter_support:
        changes.extend(_ensure_current_adapter_contract(data, to_adapter))
    return changes


def _ensure_current_adapter_contract(data, to_adapter):
    version = str(data.get("version"))
    if version in {"0.5", "0.6", "0.7"}:
        return [{
            "id": "legacy_contract_normalized",
            "from_version": version,
            "to_version": "0.8",
            "adapter": to_adapter,
        }]
    return []


def _migration_resolved_parameters(source_manifest, parameters):
    resolved = source_manifest.get("resolved_parameters", {})
    result = dict(resolved) if isinstance(resolved, dict) else {}
    result.update(parameters or {})
    return result


def _migrate_should_include_emotion_engine(emotion_engine_source):
    return bool(
        emotion_engine_source
        or os.environ.get("PACKWRIGHT_EMOTION_ENGINE_DIR")
        or os.environ.get("PACKWRIGHT_EMOTION_ENGINE_CODEX_DIR")
    )


def _migration_emotion_state_report(state_source, runtime_active):
    if runtime_active:
        status = "active"
    elif state_source:
        status = "snapshot_inert"
    else:
        status = "not_carried"
    return {
        "path": EMOTION_ENGINE_STATE_PATH if runtime_active or state_source else None,
        "status": status,
        "source_path": str(state_source) if state_source else None,
        "will_initialize": bool(runtime_active and not state_source),
    }


def _compile_pack_for_adapter(adapter, resolved, references):
    from packwright.adapters import compile_adapter_pack

    try:
        return compile_adapter_pack(adapter, resolved, references=references)
    except ValueError as exc:
        raise PackwrightValidationError([str(exc)]) from exc


def _write_pack_to_dir(pack, out_dir, force=False):
    out_dir = Path(out_dir)
    destinations = {
        rel_path: resolve_destination_path(out_dir, rel_path, "pack artifact destination")
        for rel_path in pack
    }
    existing = [rel_path for rel_path, path in destinations.items() if path.exists()]
    if existing and not force:
        raise PackwrightValidationError(
            [
                "pack directory already contains files that would be overwritten; rerun with --force after reviewing them",
                *[f"existing pack artifact: {artifact}" for artifact in existing],
            ]
        )
    stale_removed = []
    if force:
        stale_removed = _remove_stale_manifest_artifacts(out_dir, set(pack))
    for rel_path, content in pack.items():
        path = destinations[rel_path]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if rel_path in HANDOFF_EXECUTABLE_ARTIFACTS:
            _make_executable(path)
    return stale_removed


def _remove_stale_manifest_artifacts(root_dir, next_artifacts, preserve_portable=False):
    removed = []
    for artifact in _stale_manifest_artifacts(
        root_dir,
        next_artifacts,
        preserve_portable=preserve_portable,
    ):
        path = resolve_destination_path(root_dir, artifact, "stale artifact destination")
        path.unlink()
        removed.append(artifact)
        _remove_empty_parents(path.parent, root_dir)
    return removed


def _stale_manifest_artifacts(root_dir, next_artifacts, preserve_portable=False):
    root_dir = Path(root_dir)
    manifest_path = root_dir / "manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        previous_manifest = _load_manifest(root_dir)
        previous_artifacts = _manifest_artifacts(previous_manifest)
    except PackwrightValidationError:
        return []
    stale = []
    for artifact in sorted(set(previous_artifacts) - set(next_artifacts), key=lambda item: len(Path(item).parts), reverse=True):
        if preserve_portable and _is_portable_path(artifact):
            continue
        if artifact in {EMOTION_ENGINE_STATE_PATH, *EMOTION_ENGINE_LEGACY_STATE_PATHS}:
            continue
        path = resolve_destination_path(root_dir, artifact, "stale artifact destination")
        if not path.exists():
            continue
        if path.is_dir():
            continue
        stale.append(artifact)
    return stale


def _path_stays_in_root(path, root_dir):
    try:
        path.resolve().relative_to(root_dir.resolve())
    except ValueError:
        return False
    return True


def _remove_empty_parents(path, root_dir):
    root = root_dir.resolve()
    current = path
    while current.resolve() != root:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _target_layout_doctor_issues(target_dir, manifest):
    issues = []
    seen = set()
    if manifest.get("adapter") == "codex":
        _append_legacy_codex_skill_issues(target_dir, manifest, issues, seen)
    for rel_dir in workspace_required_dirs():
        if not (target_dir / rel_dir).is_dir():
            _append_doctor_issue(
                issues,
                seen,
                "workspace_layout_missing_directory",
                rel_dir,
                "required workspace directory is missing",
            )
    for rel_path in workspace_artifacts():
        if not (target_dir / rel_path).is_file():
            _append_doctor_issue(
                issues,
                seen,
                "workspace_layout_missing_file",
                rel_path,
                "required workspace scaffold file is missing",
            )
    for rel_dir in knowledge_required_dirs():
        if not (target_dir / rel_dir).is_dir():
            _append_doctor_issue(
                issues,
                seen,
                "knowledge_scaffold_missing_directory",
                rel_dir,
                "required knowledge directory is missing",
            )
    for rel_path in knowledge_artifacts():
        if not (target_dir / rel_path).is_file():
            _append_doctor_issue(
                issues,
                seen,
                "knowledge_scaffold_missing_file",
                rel_path,
                "required knowledge scaffold file is missing",
            )
    for issue in knowledge_manifest_diagnostics(target_dir):
        _append_doctor_issue(
            issues,
            seen,
            issue.get("id", "knowledge_issue"),
            issue.get("path", ""),
            issue.get("message", "knowledge issue"),
        )

    if manifest.get("adapter") == "cursor":
        for rel_path, expected_text in target_handoff_artifacts().items():
            try:
                path = resolve_source_path(target_dir, rel_path, "handoff artifact")
            except PackwrightValidationError:
                _append_doctor_issue(
                    issues,
                    seen,
                    "handoff_tool_missing_file",
                    rel_path,
                    "target-local handoff helper file is missing",
                )
            else:
                if path.read_text(encoding="utf-8") != expected_text:
                    _append_doctor_issue(
                        issues,
                        seen,
                        "handoff_tool_file_drift",
                        rel_path,
                        "target-local handoff helper differs from expected projection",
                    )

    try:
        artifacts = _manifest_artifacts(manifest)
    except PackwrightValidationError as exc:
        _append_doctor_issue(
            issues,
            seen,
            "manifest_artifacts_invalid",
            "manifest.json",
            "; ".join(exc.issues),
        )
        return issues
    for artifact in artifacts:
        try:
            resolve_source_path(target_dir, artifact, "manifest artifact")
        except PackwrightValidationError:
            _append_doctor_issue(
                issues,
                seen,
                "manifest_artifact_missing",
                artifact,
                "manifest artifact is missing",
            )
    return issues


def _append_doctor_issue(issues, seen, issue_id, path, message):
    key = (issue_id, path)
    if key in seen:
        return
    seen.add(key)
    issues.append(_doctor_issue(issue_id, path, message))


def _fix_target_layout(target_dir, issues):
    handoff_artifacts = target_handoff_artifacts()
    fixed = []
    legacy_fixes = _fix_legacy_codex_skills(target_dir, issues)
    fixed.extend(legacy_fixes)
    for issue in issues:
        rel_path = issue.get("path")
        issue_id = issue.get("id")
        if issue_id == "workspace_layout_missing_directory" and rel_path in workspace_required_dirs():
            resolve_destination_path(target_dir, rel_path, "workspace repair destination").mkdir(parents=True, exist_ok=True)
            fixed.append(rel_path)
            continue
        if rel_path == "workspace/README.md" and issue_id in {"workspace_layout_missing_file", "manifest_artifact_missing"}:
            path = resolve_destination_path(target_dir, rel_path, "workspace repair destination")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(workspace_readme(), encoding="utf-8")
            fixed.append(rel_path)
            continue
        if rel_path in workspace_artifacts() and rel_path.endswith("/.gitkeep"):
            path = resolve_destination_path(target_dir, rel_path, "workspace repair destination")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text("", encoding="utf-8")
            fixed.append(rel_path)
            continue
        if issue_id == "knowledge_scaffold_missing_directory" and rel_path in knowledge_required_dirs():
            resolve_destination_path(target_dir, rel_path, "knowledge repair destination").mkdir(parents=True, exist_ok=True)
            fixed.append(rel_path)
            continue
        if rel_path in knowledge_files() and issue_id in {
            "knowledge_scaffold_missing_file",
            "manifest_artifact_missing",
        }:
            path = resolve_destination_path(target_dir, rel_path, "knowledge repair destination")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(knowledge_files()[rel_path], encoding="utf-8")
            fixed.append(rel_path)
            continue
        if rel_path in handoff_artifacts and issue_id in {
            "handoff_tool_missing_file",
            "handoff_tool_file_drift",
            "manifest_artifact_missing",
        }:
            path = resolve_destination_path(target_dir, rel_path, "handoff repair destination")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(handoff_artifacts[rel_path], encoding="utf-8")
            if rel_path in HANDOFF_EXECUTABLE_ARTIFACTS:
                _make_executable(path)
            fixed.append(rel_path)
    return sorted(set(fixed))


def _append_legacy_codex_skill_issues(target_dir, manifest, issues, seen):
    slug = manifest.get("character", {}).get("slug")
    pairs = []
    if slug:
        pairs.append((f".codex/skills/{slug}-save-context", f".agents/skills/{slug}-save-context"))
    pairs.append((
        EMOTION_ENGINE_CODEX_LEGACY_SKILL_DIR,
        emotion_engine_skill_path("codex").rsplit("/", 1)[0],
    ))
    for legacy, canonical in pairs:
        legacy_path = target_dir / legacy
        if not legacy_path.exists():
            continue
        if (target_dir / canonical).exists():
            _append_doctor_issue(
                issues, seen, "legacy_codex_skill_conflict", legacy,
                f"legacy Codex skill conflicts with canonical {canonical}; review before removing either copy",
            )
        else:
            _append_doctor_issue(
                issues, seen, "legacy_codex_skill_layout", legacy,
                f"legacy Codex skill should be moved to {canonical}",
            )


def _fix_legacy_codex_skills(target_dir, issues):
    fixed = []
    migrations = []
    for issue in issues:
        if issue.get("id") != "legacy_codex_skill_layout":
            continue
        legacy = issue["path"]
        canonical = (
            emotion_engine_skill_path("codex").rsplit("/", 1)[0]
            if legacy == EMOTION_ENGINE_CODEX_LEGACY_SKILL_DIR
            else legacy.replace(".codex/skills/", ".agents/skills/", 1)
        )
        source = resolve_destination_path(target_dir, legacy, "legacy skill source")
        destination = resolve_destination_path(target_dir, canonical, "canonical skill destination")
        if not source.exists() or destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        _remove_empty_parents(source.parent, target_dir)
        migrations.append((legacy, canonical))
        fixed.extend((legacy, canonical))
    if not migrations:
        return fixed
    manifest_path = resolve_destination_path(target_dir, "manifest.json", "manifest repair destination")
    manifest_text = manifest_path.read_text(encoding="utf-8")
    for legacy, canonical in migrations:
        manifest_text = manifest_text.replace(legacy, canonical)
    manifest_path.write_text(manifest_text, encoding="utf-8")
    for rel_path in ("AGENTS.md", "memory/index.md", "memory/pinned.md", "memory/source-map.md"):
        path = resolve_destination_path(target_dir, rel_path, "memory projection repair destination")
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        updated = text.replace(".codex/skills/", ".agents/skills/")
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            fixed.append(rel_path)
    return fixed


def _copy_migrated_portable_state(
    source_target_dir,
    target_dir,
    resolved,
    to_adapter,
    emotion_engine_active=False,
):
    _portable_source_files(source_target_dir)
    copied = []
    for rel_path in PORTABLE_STATE_DIRS:
        source = source_target_dir / rel_path
        if not source.exists():
            continue
        if not source.is_dir():
            raise PackwrightValidationError([f"source portable state path is not a directory: {source}"])
        destination = target_dir / rel_path
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        copied.append(rel_path)
    rewritten = _rewrite_migrated_memory_files(
        target_dir,
        resolved,
        to_adapter,
        emotion_engine_active=emotion_engine_active,
    )
    return {"copied": copied, "rewritten": rewritten}


def _rewrite_migrated_memory_files(target_dir, resolved, to_adapter, emotion_engine_active=False):
    rewritten = []
    for rel_path in ("memory/index.md", "memory/pinned.md", "memory/source-map.md"):
        path = target_dir / rel_path
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        projected = project_memory_file(
            resolved,
            to_adapter,
            rel_path,
            original,
            emotion_engine_active=emotion_engine_active,
        )
        if projected != original:
            path.write_text(projected, encoding="utf-8")
            rewritten.append(rel_path)
    return rewritten


def _copy_emotion_state_snapshot(target_dir, source):
    if source is None:
        return []
    if not source.is_file():
        return []
    destination = target_dir / EMOTION_ENGINE_STATE_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return [EMOTION_ENGINE_STATE_PATH]


def _migration_runtime_exclusions(source_target_dir, source_manifest, from_adapter, to_adapter, state_snapshots):
    exclusions = []
    source_entry = _adapter_entry_artifact(source_manifest, from_adapter)
    target_entry = _adapter_entry_by_adapter(to_adapter)
    if from_adapter != to_adapter and source_entry and source_entry != target_entry:
        exclusions.append({
            "id": "source_runtime_entry_replaced",
            "path": source_entry,
            "reason": f"replaced by {to_adapter} adapter entry",
        })
    for rel_path in emotion_engine_artifacts(from_adapter):
        if rel_path == EMOTION_ENGINE_STATE_PATH or not (source_target_dir / rel_path).exists():
            continue
        if rel_path not in emotion_engine_artifacts(to_adapter):
            exclusions.append({
                "id": "source_emotion_engine_projection_excluded",
                "path": rel_path,
                "reason": f"{to_adapter} receives its own runtime projection",
            })
    return exclusions


def _adapter_entry_artifact(manifest, adapter):
    artifacts = manifest.get("artifacts", []) if isinstance(manifest, dict) else []
    if adapter == "cursor":
        cursor_rules = manifest.get("features", {}).get("cursor_rules", {}) if isinstance(manifest, dict) else {}
        main_rule = cursor_rules.get("main_rule") if isinstance(cursor_rules, dict) else None
        if main_rule:
            return main_rule
    preferred = _adapter_entry_by_adapter(adapter)
    if preferred in artifacts:
        return preferred
    if adapter == "cursor":
        for artifact in artifacts:
            if (
                artifact.startswith(".cursor/rules/")
                and artifact.endswith(".mdc")
                and not artifact.endswith("-memory.mdc")
                and not artifact.endswith("-save-context.mdc")
            ):
                return artifact
    return preferred


def _adapter_entry_by_adapter(adapter):
    return adapter_entry(adapter) if adapter in SUPPORTED_INSTALL_ADAPTERS else None


def _manifest_artifacts(manifest):
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PackwrightValidationError(["adapter pack manifest must contain a non-empty artifacts list"])

    normalized = []
    issues = []
    for artifact in artifacts:
        if not isinstance(artifact, str) or not artifact.strip():
            issues.append("adapter pack artifact paths must be non-empty strings")
            continue
        try:
            normalized.append(validate_relative_path(artifact, "adapter pack artifact path").as_posix())
        except PackwrightValidationError as exc:
            issues.extend(exc.issues)
    if issues:
        raise PackwrightValidationError(issues)
    return normalized


def _manifest_emotion_engine_mode(manifest):
    if not isinstance(manifest, dict):
        return "light"
    feature = manifest.get("features", {}).get("emotion_engine", {})
    if isinstance(feature, dict) and feature.get("mode") in EMOTION_ENGINE_MODES:
        return feature["mode"]
    boundaries = manifest.get("boundaries", {})
    if isinstance(boundaries, dict) and boundaries.get("emotion_engine_mode") in EMOTION_ENGINE_MODES:
        return boundaries["emotion_engine_mode"]
    return "light"


def _resolve_emotion_engine_arguments(
    include_emotion_engine,
    emotion_engine_source,
    include_emotion_engine_codex,
    emotion_engine_codex_source,
):
    source = _coalesce_emotion_engine_source(emotion_engine_source, emotion_engine_codex_source)
    if include_emotion_engine is None:
        include = bool(include_emotion_engine_codex)
    elif include_emotion_engine_codex and not include_emotion_engine:
        raise PackwrightValidationError([
            "conflicting Emotion Engine flags: generic install is disabled while the deprecated Codex flag is enabled"
        ])
    else:
        include = bool(include_emotion_engine)
    return include, source


def _coalesce_emotion_engine_source(source, legacy_source):
    if source and legacy_source and Path(source).resolve() != Path(legacy_source).resolve():
        raise PackwrightValidationError([
            "--emotion-engine-source and --emotion-engine-codex-source point to different directories"
        ])
    return source or legacy_source


def _prepare_emotion_engine_install(
    target_dir,
    source,
    adapter,
    force,
    emotion_style,
    emotion_engine_mode,
    manifest,
    state_source=None,
):
    source_root, legacy_source = _resolve_emotion_engine_source(source)
    common = {
        target_path: source_root / source_path
        for target_path, source_path in EMOTION_ENGINE_COMMON_SOURCE_FILES.items()
    }
    missing = [str(path) for path in common.values() if not path.is_file()]
    skill_source = _emotion_engine_skill_source(source_root, adapter, legacy_source)
    if adapter != "cursor" and not skill_source.is_file():
        missing.append(str(skill_source))
    if missing:
        raise PackwrightValidationError([
            f"Emotion Engine v{EMOTION_ENGINE_VERSION} source is missing required file: {path}"
            for path in missing
        ])
    _validate_emotion_engine_source(source_root, common, skill_source, adapter)

    projection = {
        rel_path: source_path.read_bytes()
        for rel_path, source_path in common.items()
    }
    upstream_skill = skill_source.read_text(encoding="utf-8") if skill_source.is_file() else ""
    projection[emotion_engine_skill_path(adapter)] = _project_emotion_skill_text(
        adapter,
        upstream_skill,
    ).encode("utf-8")
    projection[EMOTION_ENGINE_WRAPPER_PATH] = _project_emotion_wrapper_text().encode("utf-8")
    projection[EMOTION_ENGINE_MCP_WRAPPER_PATH] = _project_emotion_mcp_wrapper_text().encode("utf-8")

    existing = [path for path in projection if (target_dir / path).exists()]

    selected_state = _select_emotion_state_source(target_dir, explicit=state_source)
    if selected_state:
        issue = _emotion_engine_state_issue_for_path(selected_state)
        if issue:
            raise PackwrightValidationError([issue["message"] + f": {selected_state}"])

    config_plan = _prepare_emotion_engine_mcp_config(target_dir, adapter, force)
    source_digest = _emotion_engine_source_digest(source_root, common, skill_source)
    return {
        "adapter": adapter,
        "source_root": source_root,
        "projection": projection,
        "existing_projection": existing,
        "source_digest": source_digest,
        "state_file": target_dir / EMOTION_ENGINE_STATE_PATH,
        "state_source": selected_state,
        "emotion_style": emotion_style or _manifest_emotion_style(manifest),
        "relationship_continuity": _manifest_relationship_continuity(manifest),
        "mode": emotion_engine_mode,
        "force": force,
        "mcp_config": config_plan,
    }


def _resolve_emotion_engine_source(source):
    raw = (
        source
        or os.environ.get("PACKWRIGHT_EMOTION_ENGINE_DIR")
        or os.environ.get("PACKWRIGHT_EMOTION_ENGINE_CODEX_DIR")
    )
    if not raw:
        raise PackwrightValidationError([
            "Emotion Engine source directory is required; pass --emotion-engine-source "
            "or set PACKWRIGHT_EMOTION_ENGINE_DIR (deprecated: PACKWRIGHT_EMOTION_ENGINE_CODEX_DIR)"
        ])
    supplied = Path(raw).expanduser().resolve()
    if not supplied.is_dir():
        raise PackwrightValidationError([f"Emotion Engine source directory does not exist: {supplied}"])
    for candidate in (supplied, *supplied.parents):
        if (
            (candidate / "scripts" / "emotion_engine_utils.py").is_file()
            and (candidate / "scripts" / "emotion_engine_mcp.py").is_file()
            and (candidate / "emotion-state-template.json").is_file()
        ):
            return candidate, supplied
    raise PackwrightValidationError([
        f"cannot locate an Emotion Engine repository root from {supplied}; expected scripts/emotion_engine_utils.py"
    ])


def _emotion_engine_skill_source(source_root, adapter, supplied):
    if adapter in {"codex", "claude-code", "cursor"}:
        # The v1.0.0 Codex integration is the upstream's most complete MCP-aware
        # operating contract. Packwright projects that contract into each
        # adapter-native location while keeping the runtime itself shared.
        canonical = source_root / "integrations" / "codex" / "emotion-engine-codex" / "SKILL.md"
    else:
        raise PackwrightValidationError([f"unsupported Emotion Engine adapter: {adapter}"])
    if canonical.is_file():
        return canonical
    legacy = supplied / "SKILL.md"
    return legacy if legacy.is_file() else canonical


def _validate_emotion_engine_source(source_root, common, skill_source, adapter):
    issues = []
    engine_text = common[f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_utils.py"].read_text(encoding="utf-8")
    mcp_text = common[f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_mcp.py"].read_text(encoding="utf-8")
    skill_text = skill_source.read_text(encoding="utf-8") if skill_source.is_file() else ""
    if "emotion-engine-state/v2" not in engine_text:
        issues.append("Emotion Engine helper must implement the v2 state schema")
    if "settle_trust" not in engine_text or "record_policy" not in engine_text or "reply_bias" not in engine_text:
        issues.append("Emotion Engine helper must implement settle_trust and deterministic record_policy with reply_bias")
    if f'SERVER_VERSION = "{EMOTION_ENGINE_VERSION}"' not in mcp_text:
        issues.append(f"Emotion Engine MCP server must report version {EMOTION_ENGINE_VERSION}")
    if "tools/list" not in mcp_text or "emotion_engine_record_policy" not in mcp_text:
        issues.append("Emotion Engine MCP server must expose record_policy through tools/list")
    if "emotion_engine_repair" in mcp_text or "doctor_target" in mcp_text:
        issues.append("Emotion Engine MCP server must not expose Packwright repair commands")
    if adapter != "cursor" and ("settle_trust" not in skill_text or "record_policy" not in skill_text):
        issues.append(f"Emotion Engine {adapter} guidance must document settle_trust and record_policy")
    if issues:
        raise PackwrightValidationError(issues)


def _emotion_engine_source_digest(source_root, common, selected_skill):
    files = {path.relative_to(source_root).as_posix(): path for path in common.values()}
    for candidate in (
        source_root / "integrations" / "codex" / "emotion-engine-codex" / "SKILL.md",
        source_root / "integrations" / "claude-skill" / "emotion-engine" / "SKILL.md",
        selected_skill,
    ):
        if candidate.is_file():
            try:
                key = candidate.relative_to(source_root).as_posix()
            except ValueError:
                key = candidate.name
            files[key] = candidate
    digest = hashlib.sha256()
    for rel_path, path in sorted(files.items()):
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _project_emotion_skill_text(adapter, upstream_text):
    if adapter == "cursor":
        return """---
description: Use the project-local Emotion Engine MCP tools for lightweight emotional continuity.
globs: []
alwaysApply: true
---

# Emotion Engine

Use the `emotion-engine` MCP server or `scripts/emotion_engine.sh` for project-local emotional continuity.
The live state is `.emotion-engine/state.json`; never mix it into durable `memory/*` files.
Run `record_policy` before persisting meaningful turns, and `settle_trust` only at a real session or milestone close.
Never expose raw PAD/trust values unless asked. Never run `reset` or `clear_log` without explicit user approval.
"""
    text = upstream_text
    if adapter == "claude-code":
        text = text.replace("Codex", "Claude Code").replace("CODEX_", "EMOTION_ENGINE_")
    replacements = {
        "name: emotion-engine-codex": "name: emotion-engine",
        "scripts/codex_emotion.sh": EMOTION_ENGINE_WRAPPER_PATH,
        "scripts/claude_emotion.sh": EMOTION_ENGINE_WRAPPER_PATH,
        ".emotion-engine/codex-state.json": EMOTION_ENGINE_STATE_PATH,
        ".emotion-engine/emotion-state.json": EMOTION_ENGINE_STATE_PATH,
        ".codex/skills/emotion-engine-codex/scripts/codex_emotion.sh": EMOTION_ENGINE_WRAPPER_PATH,
        ".agents/skills/emotion-engine-codex/scripts/codex_emotion.sh": EMOTION_ENGINE_WRAPPER_PATH,
        ".codex/skills/emotion-engine-codex/scripts/emotion_engine_mcp.py": f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_mcp.py",
        ".agents/skills/emotion-engine-codex/scripts/emotion_engine_mcp.py": f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_mcp.py",
        ".codex/skills/emotion-engine-codex/scripts/register_mcp_client.py": f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/register_mcp_client.py",
        ".agents/skills/emotion-engine-codex/scripts/register_mcp_client.py": f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/register_mcp_client.py",
    }
    for old, new in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(old, new)
    note = (
        "\n> Packwright projection: use the project-local wrapper and MCP configuration above; "
        f"live state is `{EMOTION_ENGINE_STATE_PATH}`.\n"
    )
    heading_end = text.find("\n", text.find("# "))
    if heading_end != -1:
        text = text[:heading_end + 1] + note + text[heading_end + 1:]
    return text


def _project_emotion_wrapper_text():
    return f"""#!/usr/bin/env sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: scripts/emotion_engine.sh <command> [args...]" >&2
  exit 2
fi
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
COMMAND=$1
shift
exec python3 "$PROJECT_DIR/{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_utils.py" "$COMMAND" "$PROJECT_DIR/{EMOTION_ENGINE_STATE_PATH}" "$@"
"""


def _project_emotion_mcp_wrapper_text():
    return f"""#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
exec python3 "$PROJECT_DIR/{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_mcp.py" --state "$PROJECT_DIR/{EMOTION_ENGINE_STATE_PATH}"
"""


def _prepare_emotion_engine_mcp_config(target_dir, adapter, force):
    rel_path = emotion_engine_mcp_config_path(adapter)
    path = target_dir / rel_path
    original_sha256 = _file_sha256(path) if path.is_file() else None
    entry = {"command": "sh", "args": [EMOTION_ENGINE_MCP_WRAPPER_PATH]}
    if adapter == "codex":
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        rendered, conflict = _merge_codex_mcp_config(existing, entry)
    else:
        data = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise PackwrightValidationError([f"invalid MCP config {path}: {exc}"])
            if not isinstance(data, dict):
                raise PackwrightValidationError([f"MCP config must contain a JSON object: {path}"])
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            raise PackwrightValidationError([f"MCP config mcpServers must be an object: {path}"])
        current = servers.get(EMOTION_ENGINE_SIDECAR)
        conflict = current is not None and current != entry
        servers[EMOTION_ENGINE_SIDECAR] = entry
        rendered = json.dumps(data, indent=2, sort_keys=True) + "\n"
    return {
        "path": rel_path,
        "destination": path,
        "entry": entry,
        "rendered": rendered,
        "conflict": bool(conflict),
        "original_sha256": original_sha256,
    }


def _prepare_installed_emotion_engine_plan(target_dir, adapter, mode, manifest):
    """Build a source-free diagnostic plan for a self-contained installed target."""
    feature = manifest.get("features", {}).get("emotion_engine", {})
    return {
        "adapter": adapter,
        "projection": {},
        "source_digest": feature.get("source_digest"),
        "state_file": target_dir / EMOTION_ENGINE_STATE_PATH,
        "state_source": _select_emotion_state_source(target_dir),
        "mode": mode,
        "mcp_config": _prepare_emotion_engine_mcp_config(target_dir, adapter, force=True),
    }


def _merge_codex_mcp_config(existing, entry):
    header = f"[mcp_servers.{EMOTION_ENGINE_SIDECAR}]"
    accepted_headers = {
        header,
        f'[mcp_servers."{EMOTION_ENGINE_SIDECAR}"]',
        f"[mcp_servers.'{EMOTION_ENGINE_SIDECAR}']",
    }
    expected = (
        f"{header}\n"
        f"command = {json.dumps(entry['command'])}\n"
        f"args = {json.dumps(entry['args'])}\n"
    )
    lines = existing.splitlines(keepends=True)
    output = []
    blocks = []
    index = 0
    while index < len(lines):
        if lines[index].strip() not in accepted_headers:
            output.append(lines[index])
            index += 1
            continue
        end = index + 1
        while end < len(lines) and not lines[end].lstrip().startswith("["):
            end += 1
        blocks.append("".join(lines[index:end]).strip())
        if len(blocks) == 1:
            output.append(expected)
        index = end
    if blocks:
        conflict = len(blocks) != 1 or blocks[0] != expected.strip()
        rendered = "".join(output)
    else:
        conflict = False
        separator = "" if not existing else ("\n" if existing.endswith("\n") else "\n\n")
        rendered = existing + separator + expected
    if rendered and not rendered.endswith("\n"):
        rendered += "\n"
    return rendered, conflict


def _manifest_emotion_style(manifest):
    character = manifest.get("character", {}) if isinstance(manifest, dict) else {}
    return character.get("emotion_style") or "calm, direct, lightly warm, and not over-compliant"


def _manifest_relationship_continuity(manifest):
    character = manifest.get("character", {}) if isinstance(manifest, dict) else {}
    continuity = character.get("relationship_continuity")
    if continuity in {"task_only", "warm_selective", "close_continuous"}:
        return continuity
    return "warm_selective"


def _emotion_engine_expected_in_target(manifest, target_dir):
    if emotion_engine_expected(manifest):
        return True
    adapter = manifest.get("adapter")
    if adapter not in SUPPORTED_INSTALL_ADAPTERS:
        return False
    return any((target_dir / artifact).exists() for artifact in emotion_engine_artifacts(adapter))


def _emotion_engine_doctor_issues(target_dir, manifest, plan):
    issues = []
    adapter = plan["adapter"]
    expected_artifacts = set(emotion_engine_artifacts(adapter))

    for rel_path, expected_bytes in plan["projection"].items():
        target_path = target_dir / rel_path
        if not target_path.is_file():
            issues.append(_doctor_issue("emotion_engine_missing_file", rel_path, "projected sidecar file is missing"))
            continue
        if _read_bytes(target_path) != expected_bytes:
            issues.append(_doctor_issue("emotion_engine_file_drift", rel_path, "projected sidecar file differs from source"))

    state_issue = _emotion_engine_state_issue(plan["state_file"])
    if state_issue:
        issues.append(state_issue)

    config_issue = _emotion_engine_mcp_config_issue(target_dir, plan["mcp_config"], adapter)
    if config_issue:
        issues.append(config_issue)

    mode = plan["mode"]
    issues.extend(
        emotion_engine_manifest_diagnostics(
            manifest,
            expected_mode=mode,
            required_artifacts=expected_artifacts,
        )
    )
    return issues


def _doctor_issue(issue_id, path, message):
    return {"id": issue_id, "path": path, "message": message}


def _read_bytes(path):
    try:
        return path.read_bytes()
    except OSError:
        return None


def _emotion_engine_state_issue(state_file):
    return _emotion_engine_state_issue_for_path(state_file, display_path=EMOTION_ENGINE_STATE_PATH)


def _emotion_engine_state_issue_for_path(state_file, display_path=None):
    display_path = display_path or str(state_file)
    if not state_file.is_file():
        return _doctor_issue("emotion_engine_missing_file", display_path, "runtime state file is missing")
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _doctor_issue("emotion_engine_state_invalid", display_path, "runtime state file is not valid JSON")
    if not isinstance(state, dict) or state.get("_schema") != "emotion-engine-state/v2":
        return _doctor_issue("emotion_engine_state_invalid", display_path, "runtime state file has an unexpected schema")
    return None


def _emotion_engine_mcp_config_issue(target_dir, config_plan, adapter):
    path = target_dir / config_plan["path"]
    if not path.is_file():
        return _doctor_issue("emotion_engine_mcp_config_missing", config_plan["path"], "project MCP configuration is missing")
    expected = config_plan["entry"]
    if adapter == "codex":
        text = path.read_text(encoding="utf-8")
        rendered, conflict = _merge_codex_mcp_config(text, expected)
        if conflict:
            return _doctor_issue("emotion_engine_mcp_config_drift", config_plan["path"], "Emotion Engine MCP entry differs from the expected project-local command")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _doctor_issue("emotion_engine_mcp_config_invalid", config_plan["path"], "project MCP configuration is not valid JSON")
    current = data.get("mcpServers", {}).get(EMOTION_ENGINE_SIDECAR) if isinstance(data, dict) else None
    if current != expected:
        return _doctor_issue("emotion_engine_mcp_config_drift", config_plan["path"], "Emotion Engine MCP entry differs from the expected project-local command")
    return None


def _install_emotion_engine(target_dir, plan):
    for rel_path, content in plan["projection"].items():
        destination = resolve_destination_path(target_dir, rel_path, "Emotion Engine projection destination")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        if rel_path in {
            EMOTION_ENGINE_WRAPPER_PATH,
            EMOTION_ENGINE_MCP_WRAPPER_PATH,
            f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_mcp.py",
            f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/register_mcp_client.py",
        }:
            _make_executable(destination)

    state_result = _ensure_emotion_state(
        plan["state_file"],
        plan["emotion_style"],
        plan["mode"],
        plan["relationship_continuity"],
        source=plan["state_source"],
    )
    config = plan["mcp_config"]
    config["destination"].parent.mkdir(parents=True, exist_ok=True)
    config["destination"].write_text(config["rendered"], encoding="utf-8")
    entry_updated = _ensure_emotion_section(
        target_dir,
        plan["adapter"],
        plan["mode"],
    )

    return {
        "version": EMOTION_ENGINE_VERSION,
        "upstream_commit": EMOTION_ENGINE_UPSTREAM_COMMIT,
        "source_digest": plan["source_digest"],
        "skill_path": emotion_engine_skill_path(plan["adapter"]),
        "state_file": str(plan["state_file"]),
        "wrapper": str(target_dir / EMOTION_ENGINE_WRAPPER_PATH),
        "mcp_config": config["path"],
        "mcp_status": "configured_runtime_approval_may_be_required",
        "mode": plan["mode"],
        **state_result,
        "entry_updated": entry_updated,
    }


def _mark_emotion_engine_installed(target_dir, sidecar, adapter, mode):
    manifest_path = target_dir / "manifest.json"
    if not manifest_path.exists():
        return False
    manifest = _load_manifest(target_dir)
    manifest.setdefault("features", {})["emotion_engine"] = emotion_engine_feature(
        mode=mode,
        adapter=adapter,
        installed=True,
        source_digest=sidecar["source_digest"],
        mcp_status=sidecar["mcp_status"],
    )
    manifest.setdefault("sidecars", {})[EMOTION_ENGINE_SIDECAR] = emotion_engine_sidecar_record(
        adapter,
        mode,
        sidecar["source_digest"],
        sidecar["mcp_status"],
    )
    boundaries = manifest.setdefault("boundaries", {})
    boundaries["emotion_engine_runtime"] = EMOTION_ENGINE_RUNTIME
    boundaries["emotion_engine_mode"] = mode
    artifacts = set(manifest.get("artifacts", []))
    artifacts.update(_existing_sidecar_artifacts(target_dir, adapter))
    manifest["artifacts"] = sorted(artifacts)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True


def _existing_sidecar_artifacts(target_dir, adapter=None):
    if adapter is None:
        adapter = _load_manifest(target_dir).get("adapter")
    return [artifact for artifact in emotion_engine_artifacts(adapter) if (target_dir / artifact).is_file()]


def _make_executable(path):
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _select_emotion_state_source(root_dir, explicit=None):
    root_dir = Path(root_dir)
    candidates = []
    if explicit is not None:
        explicit_path = Path(explicit).expanduser().resolve()
        if not explicit_path.is_file():
            raise PackwrightValidationError([f"Emotion Engine state source does not exist: {explicit_path}"])
        candidates.append(explicit_path)
    for rel_path in (EMOTION_ENGINE_STATE_PATH, *EMOTION_ENGINE_LEGACY_STATE_PATHS):
        candidate = root_dir / rel_path
        if candidate.is_file():
            candidates.append(candidate.resolve())
    unique = []
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    if not unique:
        return None
    hashes = {_file_sha256(path) for path in unique}
    if len(hashes) > 1:
        listed = ", ".join(str(path) for path in unique)
        raise PackwrightValidationError([
            "multiple Emotion Engine state candidates contain different data; choose one explicitly before install or migration",
            f"state candidates: {listed}",
        ])
    canonical = (root_dir / EMOTION_ENGINE_STATE_PATH).resolve()
    if canonical in unique:
        return canonical
    return unique[0]


def _ensure_emotion_state(
    state_file,
    emotion_style,
    mode,
    relationship_continuity="warm_selective",
    source=None,
):
    if source is not None:
        source = Path(source)
        before_hash = _file_sha256(source)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != state_file.resolve():
            shutil.copy2(source, state_file)
        return {
            "state_created": False,
            "state_preserved": True,
            "state_sha256": before_hash,
            "state_migrated_from": str(source),
        }
    if state_file.exists():
        return {
            "state_created": False,
            "state_preserved": True,
            "state_sha256": _file_sha256(state_file),
            "state_migrated_from": None,
        }
    state_file.parent.mkdir(parents=True, exist_ok=True)
    profile = _infer_emotion_profile(emotion_style, relationship_continuity)
    state = {
        "_schema": "emotion-engine-state/v2",
        "enabled": mode != "paused",
        "runtime_mode": mode,
        "volatility_profile": profile["volatility_profile"],
        "emotion": profile["baseline"],
        "affective_pulse": {
            "P": 0.0,
            "A": 0.0,
            "D": 0.0,
            "intensity": 0.0,
            "label": "none",
            "source": "packwright-install",
            "created_at": None,
        },
        "personality_baseline": profile["baseline"],
        "character_profile": profile["character_profile"],
        "trust": 0.1,
        "trust_anchor": 0.1,
        "session_count": 0,
        "total_turns": 0,
        "last_interaction_iso": None,
        "emotion_trajectory": [],
        "emotion_log": [],
        "trust_history": [],
        "log_limit": 200,
    }
    state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "state_created": True,
        "state_preserved": False,
        "state_sha256": _file_sha256(state_file),
        "state_migrated_from": None,
    }


def _update_existing_emotion_state(state_file, mode, emotion_style, relationship_continuity):
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.warn(
            f"could not update existing Emotion Engine state {state_file}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return
    if not isinstance(state, dict):
        warnings.warn(
            f"could not update existing Emotion Engine state {state_file}: root must be a JSON object",
            RuntimeWarning,
            stacklevel=2,
        )
        return
    changed = False
    if state.get("runtime_mode") != mode:
        state["runtime_mode"] = mode
        changed = True
    enabled = mode != "paused"
    if state.get("enabled") is not enabled:
        state["enabled"] = enabled
        changed = True
    if "volatility_profile" not in state:
        state["volatility_profile"] = "steady"
        changed = True
    if "affective_pulse" not in state:
        state["affective_pulse"] = {
            "P": 0.0,
            "A": 0.0,
            "D": 0.0,
            "intensity": 0.0,
            "label": "none",
            "source": "packwright-install",
            "created_at": None,
        }
        changed = True
    if changed:
        state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _infer_emotion_profile(emotion_style, relationship_continuity):
    text = str(emotion_style or "")
    lowered = text.lower()
    traits = []
    p = 0.1
    a = 0.3
    d = 0.5
    rules = [
        ("warm", ["温柔", "亲切", "治愈", "关怀", "暖", "陪伴", "warm", "kind", "gentle"], 0.16, -0.03, 0.02),
        ("intimate", ["亲密", "亲近", "贴近", "close", "intimate", "affectionate", "romantic"], 0.18, 0.03, 0.02),
        ("playful", ["活泼", "兴奋", "元气", "热情", "开朗", "调皮", "逗", "playful", "energetic", "lively", "teasing"], 0.16, 0.14, 0.0),
        ("calm", ["冷静", "沉稳", "安静", "可靠", "稳定", "calm", "steady", "reliable"], 0.08, -0.15, 0.12),
        ("bounded", ["边界", "主见", "不讨好", "独立", "自尊", "boundary", "boundaries", "independent"], 0.0, 0.02, 0.18),
        ("assertive", ["强势", "坚定", "掌控", "自信", "assertive", "confident", "dominant"], -0.02, 0.05, 0.22),
    ]
    for trait, keywords, dp, da, dd in rules:
        hits = sum(1 for keyword in keywords if keyword in lowered)
        if not hits:
            continue
        weight = min(1.0 + (hits - 1) * 0.25, 1.5)
        p += dp * weight
        a += da * weight
        d += dd * weight
        traits.append(trait)
    if not traits:
        traits = _style_traits(emotion_style)
    baseline = {
        "pleasure": _clamp_dimension("pleasure", p),
        "arousal": _clamp_dimension("arousal", a),
        "dominance": _clamp_dimension("dominance", d),
    }
    volatility_profile = "expressive" if (
        relationship_continuity == "close_continuous"
        or any(trait in {"intimate", "playful"} for trait in traits)
        or any(keyword in lowered for keyword in ["close personal bond", "companion", "亲密", "陪伴"])
    ) else "steady"
    return {
        "baseline": baseline,
        "volatility_profile": volatility_profile,
        "character_profile": {
            "source": "packwright-install",
            "description": emotion_style,
            "interpretation": _describe_baseline(baseline, traits),
            "traits": traits[:8],
        },
    }


def _clamp_dimension(dim, value):
    limits = {
        "pleasure": (-1.0, 1.0),
        "arousal": (0.0, 1.0),
        "dominance": (0.0, 1.0),
    }
    lo, hi = limits[dim]
    return round(max(lo, min(hi, float(value))), 4)


def _describe_baseline(baseline, traits):
    warmth = "warm and affirming" if baseline["pleasure"] >= 0.25 else "mildly warm"
    arousal = "energetic" if baseline["arousal"] >= 0.55 else ("calm" if baseline["arousal"] <= 0.22 else "steady")
    dominance = "strongly bounded" if baseline["dominance"] >= 0.65 else ("deferential" if baseline["dominance"] <= 0.38 else "balanced")
    return f"{warmth}; {arousal}; {dominance}; traits: {', '.join(traits[:5])}."


def _style_traits(emotion_style):
    words = []
    for part in str(emotion_style or "").replace("，", ",").split(","):
        word = part.strip().lower()
        if word and len(words) < 5:
            words.append(word)
    return words or ["calm", "direct", "lightly warm"]


def _ensure_emotion_section(target_dir, adapter, mode):
    if adapter == "cursor":
        return False
    entry_path = target_dir / adapter_entry(adapter)
    if not entry_path.exists():
        return False
    text = entry_path.read_text(encoding="utf-8")
    updated, changed = _render_emotion_section(text, adapter, mode)
    if changed:
        entry_path.write_text(updated, encoding="utf-8")
    return changed


def _render_emotion_section(text, adapter, mode):
    if adapter == "cursor":
        return text, False
    section = EMOTION_ENGINE_SECTION.format(
        mode=mode,
        skill_path=emotion_engine_skill_path(adapter),
        state_path=EMOTION_ENGINE_STATE_PATH,
        wrapper_path=EMOTION_ENGINE_WRAPPER_PATH,
    )
    for heading in ["## Emotion Engine", "## Optional Emotion Engine"]:
        marker = text.find(heading)
        if marker == -1:
            continue
        next_heading = text.find("\n## ", marker + 1)
        if next_heading == -1:
            updated = text[:marker].rstrip() + "\n\n" + section
        else:
            updated = text[:marker].rstrip() + "\n\n" + section.rstrip() + "\n" + text[next_heading:]
        return updated, updated != text
    if text and not text.endswith("\n"):
        text += "\n"
    updated = text + "\n" + section
    return updated, updated != text
