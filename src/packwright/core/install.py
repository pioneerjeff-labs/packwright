import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import uuid
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - Unix fallback
    msvcrt = None

_EMOTION_TARGET_THREAD_LOCKS = {}
_EMOTION_TARGET_THREAD_LOCKS_GUARD = threading.Lock()
_EMOTION_TARGET_LOCK_LOCAL = threading.local()

from .emotion_engine_contract import (
    EMOTION_ENGINE_COMMON_SOURCE_FILES,
    EMOTION_ENGINE_CODEX_LEGACY_SKILL_DIR,
    EMOTION_ENGINE_GENERATION,
    EMOTION_ENGINE_LEGACY_STATE_PATHS,
    EMOTION_ENGINE_LEGACY_STATE_SCHEMA,
    EMOTION_ENGINE_LIFECYCLE_PATH,
    EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH,
    EMOTION_ENGINE_LEGACY_WRITER_FENCE_PATH,
    EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH,
    EMOTION_ENGINE_MCP_LAUNCHER_PATH,
    EMOTION_ENGINE_MCP_WRAPPER_PATH,
    EMOTION_ENGINE_MIGRATION_JOURNAL_PATH,
    EMOTION_ENGINE_MIGRATION_LINEAGE_PATH,
    EMOTION_ENGINE_MODES,
    EMOTION_ENGINE_PROJECTION_PENDING_PATH,
    EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
    EMOTION_ENGINE_REQUIRED_CAPABILITIES,
    EMOTION_ENGINE_RUNTIME,
    EMOTION_ENGINE_RUNTIME_ROOT,
    EMOTION_ENGINE_SIDECAR,
    EMOTION_ENGINE_STATE_PATH,
    EMOTION_ENGINE_STATE_SCHEMA,
    EMOTION_ENGINE_TARGET_LOCK_PATH,
    EMOTION_ENGINE_UPSTREAM_COMMIT,
    EMOTION_ENGINE_VERSION,
    EMOTION_ENGINE_WRAPPER_PATH,
    EMOTION_ENGINE_WRITER_GATEWAY_PATH,
    emotion_engine_artifacts,
    emotion_engine_expected,
    emotion_engine_feature,
    emotion_engine_managed_artifacts,
    emotion_engine_manifest_diagnostics,
    emotion_engine_mcp_config_path,
    emotion_engine_runtime_supported,
    emotion_engine_sidecar_record,
    emotion_engine_skill_path,
)
from .atomic_io import (
    write_bytes_atomic as _write_bytes_atomic,
    write_json_atomic as _write_json_atomic,
    write_text_atomic as _write_text_atomic,
)
from .emotion_engine_projection import (
    codex_lifecycle_config_issue,
    prepare_codex_lifecycle_config,
    render_emotion_engine_lifecycle,
    render_emotion_engine_mcp_launcher,
    render_emotion_engine_writer_gateway,
)
from .adapter_layout import adapter_entry, adapter_skill_root, supported_adapters
from .automation_projection import (
    automation_config_paths,
    bind_managed_hook_config,
    bind_pack_runtime_paths,
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
from .readiness import target_readiness
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
- Generic praise should usually affect the current reply only; repeated generic praise habituates. Route task facts, work checkpoints, stable preferences, and concrete feedback to host memory rather than emotional state.
- Emotional writes require a structured subject/event type, explicit host approval, the host-native session id, a unique event id, and the bound character/relationship ids. Never invent lifecycle ids or bypass `record_policy`.
- At a real session or relational milestone close, `settle_trust` requires both session and event ids and may settle only eligible evidence; praise alone must not directly grow trust.
- The installed lifecycle bridge forwards native session starts only when `session_idempotency/v1` is present. When the host has no reliable close event, it closes the old session only after a different native session appears.
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
    emotion_state_sha256: object
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
    if include_emotion_engine and not emotion_engine_runtime_supported(adapter):
        raise PackwrightValidationError([
            f"Emotion Engine runtime is unavailable for {adapter}; "
            "install without --include-emotion-engine and retain any state as an inert snapshot"
        ])
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
                desired_text = bind_managed_hook_config(
                    source_path.read_text(encoding="utf-8"),
                    target_dir,
                    manifest,
                )
                merge_managed_hook_config(
                    destination.read_text(encoding="utf-8"),
                    desired_text,
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
    """Apply one install while sharing the Emotion Engine transaction lock."""
    if not isinstance(plan, InstallPlan):
        raise TypeError("apply_install expects an InstallPlan")
    journal_path = _emotion_engine_migration_journal_path(plan.target_dir)
    existing_manifest_path = resolve_destination_path(
        plan.target_dir,
        "manifest.json",
        "installed manifest",
    )
    existing_emotion_engine = (
        existing_manifest_path.is_file()
        and emotion_engine_expected(_load_manifest(plan.target_dir))
    )
    if plan.sidecar_plan or journal_path.is_file() or existing_emotion_engine:
        with _emotion_engine_target_lock(plan.target_dir):
            _assert_no_incomplete_emotion_engine_migration(plan.target_dir)
            _resume_emotion_projection_commit(plan.target_dir)
            _assert_emotion_artifact_lock_current(plan.target_dir)
            return _apply_install_locked(plan)
    return _apply_install_locked(plan)


def _apply_install_locked(plan):
    if plan.force and plan.sidecar_plan:
        snapshot = _snapshot_target_files(_install_sidecar_transaction_paths(plan))
        try:
            return _apply_install_locked_body(plan)
        except Exception:
            _restore_target_files(snapshot)
            raise
    return _apply_install_locked_body(plan)


def _apply_install_locked_body(plan):
    """Apply a prepared InstallPlan after rechecking its pack inputs."""
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
                desired_text = bind_managed_hook_config(
                    source_path.read_text(encoding="utf-8"),
                    plan.target_dir,
                    plan.manifest,
                )
                merged = merge_managed_hook_config(
                    destination.read_text(encoding="utf-8"),
                    desired_text,
                )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise PackwrightValidationError([
                    f"cannot safely merge managed hook entries in {artifact}: {exc}"
                ]) from exc
            _write_text_if_changed(destination, merged)
            merged_managed_configs.append(artifact)
        elif artifact in automation_configs:
            desired_text = bind_managed_hook_config(
                source_path.read_text(encoding="utf-8"),
                plan.target_dir,
                plan.manifest,
            )
            _write_text_if_changed(destination, desired_text)
        else:
            if not destination.is_file() or destination.read_bytes() != source_path.read_bytes():
                _write_bytes_atomic(destination, source_path.read_bytes())
        if artifact in HANDOFF_EXECUTABLE_ARTIFACTS or artifact == automation_runner:
            _make_executable(destination)
        installed.append(artifact)

    sidecars = {}
    retired_legacy_state = []
    if plan.sidecar_plan:
        sidecars[EMOTION_ENGINE_SIDECAR] = _install_emotion_engine(
            plan.target_dir,
            plan.sidecar_plan,
        )
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
    _clear_emotion_projection_pending(plan.target_dir)
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


def _install_sidecar_transaction_paths(plan):
    """Enumerate every host-owned file a force sidecar install may mutate."""
    target_dir = Path(plan.target_dir)
    paths = set(plan.destinations.values())
    paths.update({
        resolve_destination_path(target_dir, "manifest.json", "install transaction manifest"),
        resolve_destination_path(target_dir, LOCK_PATH, "install transaction artifact lock"),
        resolve_destination_path(target_dir, INSTALL_PROVENANCE_PATH, "install provenance"),
        resolve_destination_path(target_dir, ".packwright/baseline-path", "automation baseline"),
        _emotion_engine_state_path(target_dir),
        _emotion_engine_managed_path(
            target_dir,
            EMOTION_ENGINE_PROJECTION_PENDING_PATH,
            "install transaction pending marker",
        ),
        _emotion_engine_managed_path(
            target_dir,
            EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
            "install transaction projection receipt",
        ),
        _emotion_engine_managed_path(
            target_dir,
            EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH,
            "install transaction MCP receipt",
        ),
        _emotion_engine_managed_path(
            target_dir,
            EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH,
            "install transaction lifecycle receipt",
        ),
    })
    sidecar = plan.sidecar_plan
    paths.update(
        resolve_destination_path(target_dir, rel_path, "install sidecar transaction artifact")
        for rel_path in sidecar["projection"]
    )
    paths.add(sidecar["mcp_config"]["destination"])
    if sidecar.get("lifecycle_config"):
        paths.add(resolve_destination_path(
            target_dir,
            sidecar["lifecycle_config"]["path"],
            "install lifecycle transaction artifact",
        ))
    if plan.adapter != "cursor":
        paths.add(resolve_destination_path(
            target_dir,
            adapter_entry(plan.adapter),
            "install shared adapter entry",
        ))
    manifest_path = target_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            current_manifest = _load_manifest(target_dir)
            paths.update(
                resolve_destination_path(target_dir, rel_path, "stale install transaction artifact")
                for rel_path in _manifest_artifacts(current_manifest)
                if not _is_portable_path(rel_path)
            )
        except PackwrightValidationError:
            pass
    for item in _emotion_legacy_retirement_plan(target_dir) if plan.retire_legacy_state else ():
        paths.add(_emotion_engine_managed_path(target_dir, item["from"], "legacy retirement source"))
        paths.add(_emotion_engine_managed_path(target_dir, item["to"], "legacy retirement backup"))
    return paths


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
    _write_json_atomic(path, data)


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
        source = _emotion_engine_managed_path(
            target_dir,
            rel_path,
            "legacy Emotion Engine retirement source",
        )
        if not source.is_file():
            continue
        backup_rel = f"{rel_path}.bak"
        backup = _emotion_engine_managed_path(
            target_dir,
            backup_rel,
            "legacy Emotion Engine retirement backup",
        )
        if backup.exists():
            raise PackwrightValidationError([
                f"cannot retire legacy Emotion Engine state because backup already exists: {backup}"
            ])
        planned.append({
            "from": rel_path,
            "to": backup_rel,
            "operation": "rename_backup",
        })
    return planned


def _retire_legacy_emotion_states(target_dir):
    target_dir = Path(target_dir)
    canonical = _emotion_engine_state_path(target_dir)
    if not canonical.is_file():
        raise PackwrightValidationError([
            f"cannot retire legacy Emotion Engine state before {EMOTION_ENGINE_STATE_PATH} exists"
        ])
    planned = _emotion_legacy_retirement_plan(target_dir)
    canonical_hash = _file_sha256(canonical)
    for item in planned:
        source = _emotion_engine_managed_path(
            target_dir,
            item["from"],
            "legacy Emotion Engine retirement source",
        )
        source_hash = _file_sha256(source)
        if source_hash != canonical_hash:
            raise PackwrightValidationError([
                "legacy Emotion Engine state differs from canonical state; Packwright's "
                "compatibility bridge cannot authenticate sidecar-private lineage and will "
                f"not retire it: {source}"
            ])
    for item in planned:
        source = _emotion_engine_managed_path(
            target_dir,
            item["from"],
            "legacy Emotion Engine retirement source",
        )
        destination = _emotion_engine_managed_path(
            target_dir,
            item["to"],
            "legacy Emotion Engine retirement backup",
        )
        source.rename(destination)
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
    with _emotion_engine_target_lock(target_dir):
        _assert_no_incomplete_emotion_engine_migration(target_dir)
        _resume_emotion_projection_commit(target_dir)
        manifest = _load_manifest(target_dir)
        previous_artifacts = set(_manifest_artifacts(manifest))
        manifest_adapter = manifest.get("adapter")
        if manifest_adapter not in SUPPORTED_INSTALL_ADAPTERS:
            raise PackwrightValidationError([f"target adapter is unsupported: {manifest_adapter!r}"])
        if not emotion_engine_runtime_supported(manifest_adapter):
            raise PackwrightValidationError([
                f"Emotion Engine runtime is unavailable for {manifest_adapter}"
            ])

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
        previous_sidecar = manifest.get("sidecars", {}).get(EMOTION_ENGINE_SIDECAR, {})
        previous_runtime_root = (
            previous_sidecar.get("runtime_root")
            if isinstance(previous_sidecar, dict)
            else None
        )
        refresh_owned_paths = {
            *plan["projection"],
            *plan.get("stale_projection_receipts", []),
            EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
        }
        entry_rel_path = adapter_entry(manifest_adapter)
        refresh_owned_fragments = set()
        mcp_rel_path = plan["mcp_config"]["path"]
        mcp_path = resolve_source_path(target_dir, mcp_rel_path, "shared MCP configuration")
        plan["mcp_unmanaged_sha256"] = _emotion_mcp_unmanaged_digest(
            mcp_path.read_text(encoding="utf-8"),
            manifest_adapter,
        )
        refresh_owned_fragments.add(mcp_rel_path)
        if manifest_adapter != "cursor":
            entry_path = resolve_source_path(
                target_dir,
                entry_rel_path,
                "shared adapter entry",
            )
            plan["entry_unmanaged_sha256"] = _emotion_entry_unmanaged_digest(
                entry_path.read_text(encoding="utf-8")
            )
            refresh_owned_fragments.add(entry_rel_path)
        if plan.get("lifecycle_config"):
            refresh_owned_paths.add(plan["lifecycle_config"]["path"])
        if isinstance(previous_runtime_root, str) and previous_runtime_root:
            refresh_owned_paths.update(
                rel_path
                for rel_path in previous_artifacts
                if rel_path == previous_runtime_root
                or rel_path.startswith(previous_runtime_root.rstrip("/") + "/")
            )
        _assert_emotion_artifact_lock_current(
            target_dir,
            owned_paths=refresh_owned_paths,
            owned_fragments=refresh_owned_fragments,
        )
        plan["lock_owned_paths"] = sorted({
            *refresh_owned_paths,
            *refresh_owned_fragments,
            "manifest.json",
        })
        retirement_plan = _emotion_legacy_retirement_plan(target_dir) if retire_legacy_state else []
        transaction_paths = {
            *(resolve_destination_path(
                target_dir,
                rel_path,
                "Emotion Engine refresh transaction path",
            ) for rel_path in plan["projection"]),
            _emotion_engine_state_path(target_dir),
            resolve_destination_path(
                target_dir,
                plan["mcp_config"]["path"],
                "Emotion Engine MCP config transaction path",
            ),
            resolve_destination_path(target_dir, "manifest.json", "manifest transaction path"),
            resolve_destination_path(target_dir, LOCK_PATH, "artifact lock transaction path"),
            resolve_destination_path(
                target_dir,
                adapter_entry(manifest_adapter),
                "adapter entry transaction path",
            ),
            _emotion_engine_managed_path(
                target_dir,
                EMOTION_ENGINE_PROJECTION_PENDING_PATH,
                "Emotion Engine pending transaction path",
            ),
            _emotion_engine_managed_path(
                target_dir,
                EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
                "Emotion Engine projection receipt transaction path",
            ),
            _emotion_engine_managed_path(
                target_dir,
                EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH,
                "Emotion Engine activation receipt transaction path",
            ),
            _emotion_engine_managed_path(
                target_dir,
                EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH,
                "Emotion Engine lifecycle receipt transaction path",
            ),
            *(resolve_destination_path(
                target_dir,
                rel_path,
                "stale Emotion Engine receipt transaction path",
            ) for rel_path in plan.get("stale_projection_receipts", [])),
        }
        if plan.get("lifecycle_config"):
            transaction_paths.add(resolve_destination_path(
                target_dir,
                plan["lifecycle_config"]["path"],
                "Emotion Engine lifecycle config transaction path",
            ))
        for item in retirement_plan:
            transaction_paths.add(_emotion_engine_managed_path(
                target_dir,
                item["from"],
                "legacy Emotion Engine retirement transaction source",
            ))
            transaction_paths.add(_emotion_engine_managed_path(
                target_dir,
                item["to"],
                "legacy Emotion Engine retirement transaction backup",
            ))
        snapshot = _snapshot_target_files(transaction_paths)
        try:
            sidecar = _install_emotion_engine(target_dir, plan)
            retired_legacy_state = (
                _retire_legacy_emotion_states(target_dir)
                if retire_legacy_state
                else []
            )
            _mark_emotion_engine_installed(
                target_dir,
                sidecar,
                manifest_adapter,
                resolved_emotion_engine_mode,
            )
            current_manifest = _load_manifest(target_dir)
            current_artifacts = set(_manifest_artifacts(current_manifest))
            owned_artifacts = {
                *plan["projection"],
                plan["mcp_config"]["path"],
                adapter_entry(manifest_adapter),
                "manifest.json",
                EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
                *(current_artifacts - previous_artifacts),
            }
            if plan.get("lifecycle_config"):
                owned_artifacts.add(plan["lifecycle_config"]["path"])
            _update_artifact_lock_paths(
                target_dir,
                owned_artifacts,
                removed_paths=previous_artifacts - current_artifacts,
            )
            _clear_emotion_projection_pending(target_dir)
        except Exception:
            _restore_target_files(snapshot)
            raise
        result = {
            "adapter": manifest_adapter,
            "target_dir": str(target_dir),
            "refreshed_artifacts": _existing_sidecar_artifacts(target_dir),
            "sidecars": {EMOTION_ENGINE_SIDECAR: sidecar},
            "client_restart_required": True,
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


def bootstrap_emotion_engine_artifact_lock(target_dir, apply=False, preview_digest=None):
    """Preview or explicitly adopt an old EE target into Packwright's lock baseline."""
    target_dir = Path(target_dir)
    with _emotion_engine_target_lock(target_dir):
        _assert_no_incomplete_emotion_engine_migration(target_dir)
        pending_path = _emotion_engine_managed_path(
            target_dir,
            EMOTION_ENGINE_PROJECTION_PENDING_PATH,
            "legacy lock adoption pending marker",
        )
        if pending_path.is_file():
            raise PackwrightValidationError([
                "cannot bootstrap an artifact lock while a sidecar projection transaction is pending"
            ])
        manifest = _load_manifest(target_dir)
        if not emotion_engine_expected(manifest):
            raise PackwrightValidationError([
                "target does not declare an installed Emotion Engine runtime"
            ])
        lock_path = resolve_destination_path(target_dir, LOCK_PATH, "artifact lock adoption destination")
        if lock_path.is_file():
            _assert_emotion_artifact_lock_current(target_dir)
            return {
                "schema": "packwright-artifact-lock-adoption/v1",
                "status": "already_locked",
                "applied": False,
                "target_dir": str(target_dir),
                "lock_path": LOCK_PATH,
            }
        preview = []
        for rel_path in sorted(set(_manifest_artifacts(manifest)) | {"manifest.json"}):
            if rel_path == LOCK_PATH or _is_portable_path(rel_path) or _is_sidecar_private_path(rel_path):
                continue
            path = resolve_source_path(target_dir, rel_path, "legacy lock adoption artifact")
            preview.append({
                "path": rel_path,
                "sha256": _file_sha256(path),
                "record": _artifact_lock_record(manifest, rel_path, path),
            })
        report = {
            "schema": "packwright-artifact-lock-adoption/v1",
            "status": "confirmation_required",
            "applied": False,
            "target_dir": str(target_dir),
            "lock_path": LOCK_PATH,
            "artifacts": preview,
            "preview_digest": _sha256_bytes(
                json.dumps(preview, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ),
            "required_confirmation": (
                "review every current artifact digest, then rerun with explicit confirmation; "
                "ordinary refresh will never adopt this baseline"
            ),
        }
        if not apply:
            return report
        if not isinstance(preview_digest, str) or preview_digest != report["preview_digest"]:
            raise PackwrightValidationError([
                "legacy artifact-lock adoption preview changed or was not supplied; "
                "review the current preview and confirm its exact preview_digest"
            ])
        manifest_path = resolve_destination_path(target_dir, "manifest.json", "legacy lock adoption manifest")
        snapshot = _snapshot_target_files({manifest_path, lock_path})
        try:
            manifest.setdefault("packwright", {})["lock"] = LOCK_PATH
            manifest["artifacts"] = sorted(set(manifest.get("artifacts", [])) | {LOCK_PATH})
            _write_json_atomic(manifest_path, manifest)
            _refresh_artifact_lock(target_dir)
        except Exception:
            _restore_target_files(snapshot)
            raise
        report.update({
            "status": "adopted",
            "applied": True,
            "required_confirmation": None,
            "lock_sha256": _file_sha256(lock_path),
        })
        return report


def migrate_emotion_engine_state(
    target_dir,
    apply=False,
    character_id=None,
    relationship_id=None,
):
    """Serialize and plan/apply one explicit state migration or capability upgrade."""
    target_dir = Path(target_dir)
    with _emotion_engine_target_lock(target_dir):
        _recover_incomplete_emotion_engine_migration(target_dir)
        _assert_emotion_artifact_lock_current(target_dir)
        return _migrate_emotion_engine_state_locked(
            target_dir,
            apply=apply,
            character_id=character_id,
            relationship_id=relationship_id,
        )


def _migrate_emotion_engine_state_locked(
    target_dir,
    apply=False,
    character_id=None,
    relationship_id=None,
):
    """Plan or apply one explicit Emotion Engine migration/upgrade transaction.

    Packwright derives the owner identity from the installed character slug,
    creates a separate timestamped backup before applying, delegates the state
    rewrite to the pinned Emotion Engine helper, and verifies activation plus
    state integrity before updating manifest activation layers.
    """
    manifest = _load_manifest(target_dir)
    adapter = manifest.get("adapter")
    if not emotion_engine_expected(manifest):
        raise PackwrightValidationError(["target does not declare an installed Emotion Engine runtime"])
    if not emotion_engine_runtime_supported(adapter):
        raise PackwrightValidationError([f"Emotion Engine runtime is unavailable for {adapter}"])
    mode = _manifest_emotion_engine_mode(manifest)
    plan = _prepare_installed_emotion_engine_plan(target_dir, adapter, mode, manifest)
    identity = _emotion_engine_migration_identity(
        manifest,
        character_id=character_id,
        relationship_id=relationship_id,
    )
    if identity is None:
        report = {
            "status": "identity_confirmation_required",
            "applied": False,
            "state_file": str(_emotion_engine_state_path(target_dir)),
            "manifest_character_slug": manifest.get("character", {}).get("slug"),
            "required_confirmation": (
                "rerun with explicit --character-id and --relationship-id; "
                "the placeholder character slug cannot own relationship state"
            ),
        }
        if apply:
            raise PackwrightValidationError([report["required_confirmation"]])
        return report
    plan["identity"] = identity
    preflight = _emotion_engine_doctor_issues(
        target_dir,
        manifest,
        plan,
        runtime_probes_trusted=not _artifact_lock_doctor_issues(target_dir, manifest),
    )
    blocking = [
        issue for issue in preflight
        if issue["id"] not in {
            "emotion_engine_state_migration_required",
            "emotion_engine_state_capability_mismatch",
            "emotion_engine_manifest_identity_mismatch",
            "emotion_engine_mcp_restart_required",
            "emotion_engine_activation_manifest_stale",
        }
    ]
    if blocking:
        raise PackwrightValidationError([
            "Emotion Engine state migration preflight failed; refresh rc.4 and restart the MCP client first",
            *[f"{issue['id']}: {issue['message']}" for issue in blocking],
        ])

    state_file = _emotion_engine_state_path(target_dir)
    state = json.loads(state_file.read_text(encoding="utf-8"))
    schema = state.get("_schema") if isinstance(state, dict) else None
    if schema == EMOTION_ENGINE_STATE_SCHEMA:
        issue = _emotion_engine_state_issue(state_file, expected_identity=identity)
        if issue and issue["id"] != "emotion_engine_state_capability_mismatch":
            raise PackwrightValidationError([issue["message"]])
        if issue is None:
            return {
                "status": "already_v3",
                "applied": False,
                "state_file": str(state_file),
                "identity": identity,
                "activation": _emotion_engine_activation_status(target_dir, plan),
            }
        operation = "upgrade_v3_capabilities"
        helper_command = "upgrade_state"
        ready_status = "upgrade_ready"
        applied_statuses = {"upgraded", "already_current"}
        final_status = "upgraded"
        from_schema = EMOTION_ENGINE_STATE_SCHEMA
    elif schema == EMOTION_ENGINE_LEGACY_STATE_SCHEMA:
        operation = "migrate_v2_to_v3"
        helper_command = "migrate_state"
        ready_status = "migration_ready"
        applied_statuses = {"migrated", "already_v3"}
        final_status = "migrated"
        from_schema = EMOTION_ENGINE_LEGACY_STATE_SCHEMA
    else:
        raise PackwrightValidationError([
            f"Emotion Engine state schema cannot be migrated: {schema!r}"
        ])

    with tempfile.TemporaryDirectory(prefix="packwright-emotion-migration-") as tmpdir:
        dry_run_state = Path(tmpdir) / "state.json"
        shutil.copy2(state_file, dry_run_state)
        helper_args = (
            (
                "--character-id",
                identity["character_id"],
                "--relationship-id",
                identity["relationship_id"],
            )
            if operation == "migrate_v2_to_v3"
            else ()
        )
        dry_run = _run_installed_emotion_helper(
            target_dir,
            helper_command,
            *helper_args,
            state_file=dry_run_state,
        )
    if dry_run.get("returncode") != 0 or dry_run.get("status") != ready_status:
        raise PackwrightValidationError([
            f"Emotion Engine helper rejected the {operation} dry run: "
            + dry_run.get("message", dry_run.get("stderr", "unknown error"))
        ])
    report = {
        "status": ready_status,
        "applied": False,
        "operation": operation,
        "state_file": str(state_file),
        "from_schema": from_schema,
        "to_schema": EMOTION_ENGINE_STATE_SCHEMA,
        "identity": identity,
        "dry_run": dry_run,
        "required_confirmation": "rerun with --yes after reviewing the identity and backup path",
    }
    if not apply:
        return report

    report.pop("required_confirmation", None)
    backup = _emotion_engine_migration_backup_path(target_dir, schema=from_schema)
    backup.parent.mkdir(parents=True, exist_ok=True)
    journal_path = _emotion_engine_migration_journal_path(target_dir)
    lineage_path = _emotion_engine_migration_lineage_path(target_dir)
    snapshot = _snapshot_target_files({
        state_file,
        resolve_destination_path(target_dir, "manifest.json", "manifest migration destination"),
        resolve_destination_path(target_dir, LOCK_PATH, "artifact lock migration destination"),
        lineage_path,
    })
    source_sha256 = _file_sha256(state_file)
    legacy_sources = []
    if operation == "migrate_v2_to_v3":
        for rel_path in EMOTION_ENGINE_LEGACY_STATE_PATHS:
            legacy_path = _emotion_engine_managed_path(
                target_dir,
                rel_path,
                "legacy Emotion Engine migration source",
            )
            if legacy_path.is_file() and _file_sha256(legacy_path) == source_sha256:
                legacy_sources.append({"path": rel_path, "sha256": source_sha256})
    lineage_id = (
        _sha256_bytes(
            (json.dumps({
                "source_sha256": source_sha256,
                "identity": identity,
                "writer_generation": EMOTION_ENGINE_GENERATION,
                "legacy_sources": legacy_sources,
            }, sort_keys=True) + "\n").encode("utf-8")
        )
        if operation == "migrate_v2_to_v3"
        else None
    )
    manifest_path = resolve_destination_path(
        target_dir,
        "manifest.json",
        "manifest migration destination",
    )
    artifact_lock_path = resolve_destination_path(
        target_dir,
        LOCK_PATH,
        "artifact lock migration destination",
    )
    journal = {
        "schema": "packwright-emotion-migration-transaction/v1",
        "status": "in_progress",
        "operation": operation,
        "phase": "backup",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "state_file": EMOTION_ENGINE_STATE_PATH,
        "source_sha256": source_sha256,
        "backup_sha256": source_sha256,
        "backup": backup.resolve().relative_to(target_dir.resolve()).as_posix(),
        "identity": identity,
        "lineage_id": lineage_id,
        "legacy_sources": legacy_sources,
        "projection_nonce": plan.get("projection_nonce"),
        "manifest_before": manifest_path.read_text(encoding="utf-8"),
        "lock_before": (
            artifact_lock_path.read_text(encoding="utf-8")
            if artifact_lock_path.is_file()
            else None
        ),
        "lineage_before": (
            lineage_path.read_text(encoding="utf-8")
            if lineage_path.is_file()
            else None
        ),
    }
    _write_json_atomic(journal_path, journal)
    try:
        _write_bytes_atomic(backup, state_file.read_bytes())
        journal["phase"] = helper_command
        _write_json_atomic(journal_path, journal)
        migrated = _run_installed_emotion_helper(
            target_dir,
            helper_command,
            *helper_args,
            "--apply",
        )
        if (
            operation == "migrate_v2_to_v3"
            and migrated.get("returncode") == 0
            and migrated.get("status") in applied_statuses
        ):
            migrated_state = json.loads(state_file.read_text(encoding="utf-8"))
            migrated_state["packwright_migration_lineage"] = {
                "schema": "packwright-emotion-migration-lineage-ref/v1",
                "lineage_id": lineage_id,
            }
            _write_json_atomic(state_file, migrated_state)
        mode_sync = (
            _sync_emotion_engine_mode(target_dir, state_file, mode)
            if migrated.get("returncode") == 0
            and migrated.get("status") in applied_statuses
            else {"status": "migration_not_ready", "changed": False}
        )
        journal["phase"] = "verify"
        _write_json_atomic(journal_path, journal)
        activation = _emotion_engine_activation_probe(target_dir, plan)
        audit = _run_installed_emotion_helper(target_dir, "audit_state")
        verified = (
            migrated.get("returncode") == 0
            and migrated.get("status") in applied_statuses
            and activation.get("returncode") == 0
            and activation.get("status") == "ready"
            and audit.get("returncode") == 0
            and audit.get("ok") is True
            and _emotion_engine_state_issue(state_file, expected_identity=identity) is None
            and _emotion_engine_mode_issue(state_file, mode) is None
        )
        if verified:
            journal["phase"] = "commit_manifest"
            _write_json_atomic(journal_path, journal)
            lineage = None
            if operation == "migrate_v2_to_v3":
                lineage = {
                    "schema": "packwright-emotion-migration-lineage/v1",
                    "status": "completed",
                    "lineage_id": lineage_id,
                    "operation": operation,
                    "writer_generation": EMOTION_ENGINE_GENERATION,
                    "state_path": EMOTION_ENGINE_STATE_PATH,
                    "source_sha256": source_sha256,
                    "legacy_sources": legacy_sources,
                    "identity": identity,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
                _write_json_atomic(lineage_path, lineage)
            activation_status = _emotion_engine_activation_status(target_dir, plan)
            _update_emotion_engine_activation_manifest(
                target_dir,
                activation_status,
                identity=identity,
            )
            _update_artifact_lock_paths(target_dir, ["manifest.json", EMOTION_ENGINE_STATE_PATH])
            journal.update({
                "status": "completed",
                "phase": "complete",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "destination_sha256": _file_sha256(state_file),
                "lineage_path": (
                    EMOTION_ENGINE_MIGRATION_LINEAGE_PATH
                    if lineage is not None
                    else None
                ),
            })
            _write_json_atomic(journal_path, journal)
        else:
            _restore_target_files(snapshot)
            activation_status = _emotion_engine_activation_status(target_dir, plan)
            journal.update({
                "status": "rolled_back",
                "phase": "verification_failed",
                "rolled_back_at": datetime.now(timezone.utc).isoformat(),
            })
            _write_json_atomic(journal_path, journal)
    except Exception as exc:
        _restore_target_files(snapshot)
        journal.update({
            "status": "rolled_back",
            "phase": "exception",
            "rolled_back_at": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        })
        _write_json_atomic(journal_path, journal)
        raise
    report.update({
        "status": final_status if verified else "verification_failed",
        "applied": True,
        "backup": str(backup),
        "journal": str(journal_path),
        "lineage": (
            str(lineage_path)
            if operation == "migrate_v2_to_v3" and verified
            else None
        ),
        "migration": migrated,
        "mode_sync": mode_sync,
        "activation_check": activation,
        "audit_state": audit,
        "activation": activation_status,
    })
    if not verified:
        report["rolled_back"] = True
        report["recovery"] = f"the original v2 state was restored from: {backup}"
    return report


def _recover_incomplete_emotion_engine_migration(target_dir):
    journal_path = _emotion_engine_migration_journal_path(target_dir)
    if not journal_path.is_file():
        return None
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise PackwrightValidationError([
            f"Emotion Engine migration journal is unreadable: {journal_path}"
        ])
    if not isinstance(journal, dict) or journal.get("status") != "in_progress":
        return None
    recovery_issues = []
    if journal.get("schema") != "packwright-emotion-migration-transaction/v1":
        recovery_issues.append("migration journal schema is unsupported")
    if journal.get("operation") not in {"migrate_v2_to_v3", "upgrade_v3_capabilities"}:
        recovery_issues.append("migration journal operation is invalid")
    if not isinstance(journal.get("phase"), str) or not journal.get("phase"):
        recovery_issues.append("migration journal phase is invalid")
    if journal.get("state_file") != EMOTION_ENGINE_STATE_PATH:
        recovery_issues.append("migration journal state path does not match the managed state")
    backup_value = journal.get("backup")
    try:
        if not isinstance(backup_value, str) or not backup_value:
            raise ValueError("backup path is missing")
        backup_relative = validate_relative_path(
            backup_value,
            "Emotion Engine recovery backup",
        ).as_posix()
        backup = resolve_source_path(
            target_dir,
            backup_relative,
            "Emotion Engine recovery backup",
        )
    except (OSError, ValueError, PackwrightValidationError) as exc:
        raise PackwrightValidationError([
            "Emotion Engine migration backup is missing, unsafe, or escapes the installed target"
        ]) from exc
    try:
        backup_bytes = backup.read_bytes()
    except OSError as exc:
        raise PackwrightValidationError([
            "Emotion Engine migration backup could not be read; the global writer fuse remains active"
        ]) from exc
    expected_backup_sha256 = journal.get("backup_sha256") or journal.get("source_sha256")
    if (
        not isinstance(expected_backup_sha256, str)
        or len(expected_backup_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_backup_sha256.lower())
    ):
        recovery_issues.append("migration journal backup digest is invalid")
    elif _sha256_bytes(backup_bytes) != expected_backup_sha256.lower():
        recovery_issues.append("migration backup digest does not match the journal")

    manifest_before = journal.get("manifest_before")
    try:
        manifest_snapshot = json.loads(manifest_before) if isinstance(manifest_before, str) else None
        if not isinstance(manifest_snapshot, dict):
            raise ValueError("manifest snapshot is not an object")
        _manifest_artifacts(manifest_snapshot)
    except (json.JSONDecodeError, ValueError, PackwrightValidationError) as exc:
        recovery_issues.append(f"migration manifest snapshot is invalid: {exc}")

    lock_before = journal.get("lock_before")
    try:
        lock_snapshot = json.loads(lock_before) if isinstance(lock_before, str) else None
        if (
            not isinstance(lock_snapshot, dict)
            or lock_snapshot.get("schema") != "packwright-lock/v1"
            or not isinstance(lock_snapshot.get("artifacts"), dict)
            or not lock_snapshot["artifacts"]
        ):
            raise ValueError("artifact-lock snapshot is incomplete")
    except (json.JSONDecodeError, ValueError) as exc:
        recovery_issues.append(f"migration artifact-lock snapshot is invalid: {exc}")

    lineage_before = journal.get("lineage_before")
    if lineage_before is not None:
        try:
            lineage_snapshot = json.loads(lineage_before) if isinstance(lineage_before, str) else None
            if not isinstance(lineage_snapshot, dict):
                raise ValueError("lineage snapshot is not an object")
        except (json.JSONDecodeError, ValueError) as exc:
            recovery_issues.append(f"migration lineage snapshot is invalid: {exc}")

    if recovery_issues:
        raise PackwrightValidationError([
            "cannot safely recover the incomplete Emotion Engine migration; the global writer fuse remains active",
            *recovery_issues,
        ])

    state_file = _emotion_engine_state_path(target_dir)
    _write_bytes_atomic(state_file, backup_bytes)
    manifest_path = resolve_destination_path(
        target_dir,
        "manifest.json",
        "manifest recovery destination",
    )
    _write_text_atomic(manifest_path, manifest_before)
    artifact_lock_path = resolve_destination_path(
        target_dir,
        LOCK_PATH,
        "artifact lock recovery destination",
    )
    _write_text_atomic(artifact_lock_path, lock_before)
    lineage_path = _emotion_engine_migration_lineage_path(target_dir)
    if isinstance(lineage_before, str):
        _write_text_atomic(lineage_path, lineage_before)
    elif lineage_before is None and lineage_path.is_file():
        lineage_path.unlink()
    journal.update({
        "status": "rolled_back",
        "phase": "recovered_incomplete_transaction",
        "rolled_back_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_json_atomic(journal_path, journal)
    return journal


def _emotion_engine_migration_backup_path(target_dir, schema=EMOTION_ENGINE_LEGACY_STATE_SCHEMA):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = _emotion_engine_managed_path(
        target_dir,
        ".emotion-engine/backups",
        "Emotion Engine migration backup directory",
    )
    label = "v2" if schema == EMOTION_ENGINE_LEGACY_STATE_SCHEMA else "v3"
    candidate = root / f"state.{label}.{stamp}.json"
    suffix = 1
    while candidate.exists():
        candidate = root / f"state.{label}.{stamp}.{suffix}.json"
        suffix += 1
    return candidate


def _update_emotion_engine_activation_manifest(target_dir, activation, identity=None):
    manifest = _load_manifest(target_dir)
    feature = manifest.get("features", {}).get("emotion_engine")
    sidecar = manifest.get("sidecars", {}).get(EMOTION_ENGINE_SIDECAR)
    if not isinstance(feature, dict) or not isinstance(sidecar, dict):
        raise PackwrightValidationError(["manifest Emotion Engine records are missing"])
    feature["activation"] = dict(activation)
    sidecar["activation"] = dict(activation)
    if identity is not None:
        sidecar["identity"] = dict(identity)
    _write_json_atomic(resolve_destination_path(
        target_dir,
        "manifest.json",
        "Emotion Engine activation manifest destination",
    ), manifest)


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
    initial_manifest = _load_manifest(target_dir)
    if fix and _emotion_engine_expected_in_target(initial_manifest, target_dir):
        with _emotion_engine_target_lock(target_dir):
            _assert_no_incomplete_emotion_engine_migration(target_dir)
            return _doctor_target_locked(
                target_dir,
                fix=fix,
                emotion_engine_codex_source=emotion_engine_codex_source,
                emotion_style=emotion_style,
                emotion_engine_mode=emotion_engine_mode,
                emotion_engine_source=emotion_engine_source,
            )
    return _doctor_target_locked(
        target_dir,
        fix=fix,
        emotion_engine_codex_source=emotion_engine_codex_source,
        emotion_style=emotion_style,
        emotion_engine_mode=emotion_engine_mode,
        emotion_engine_source=emotion_engine_source,
    )


def _doctor_target_locked(
    target_dir,
    fix=False,
    emotion_engine_codex_source=None,
    emotion_style=None,
    emotion_engine_mode=None,
    emotion_engine_source=None,
):
    """Run doctor after acquiring the project writer lock when it may mutate."""
    manifest = _load_manifest(target_dir)
    adapter = manifest.get("adapter")
    result = {
        "target_dir": str(target_dir),
        "adapter": adapter,
        "scope": "managed_projection",
        "provenance": _target_provenance(target_dir, manifest),
        "ok": True,
        "issues": [],
        "warnings": _legacy_emotion_state_warnings(target_dir)
        + _adapter_activation_warnings(manifest),
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
        return _finalize_doctor_readiness(result, target_dir, manifest)

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
    issues = _emotion_engine_doctor_issues(
        target_dir,
        manifest,
        plan,
        runtime_probes_trusted=not lock_issues,
    )
    result["warnings"].extend(_emotion_engine_lifecycle_warnings(target_dir, manifest))
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
        refreshed_lock_issues = _artifact_lock_doctor_issues(target_dir, refreshed_manifest)
        after_issues = _emotion_engine_doctor_issues(
            target_dir,
            refreshed_manifest,
            refreshed_plan,
            runtime_probes_trusted=not refreshed_lock_issues,
        )
        result["fixes"].append({
            "id": "emotion_engine_refreshed",
            "result": refresh_result,
        })
        result["after_issues"] = after_issues
        result["issues"] = (
            _target_layout_doctor_issues(target_dir, refreshed_manifest)
            + refreshed_lock_issues
            + after_issues
        )
        result["warnings"] = (
            _legacy_emotion_state_warnings(target_dir)
            + _emotion_engine_lifecycle_warnings(target_dir, refreshed_manifest)
        )
        result["ok"] = not result["issues"]
    elif issues and fix and not source:
        result["warnings"].append({
            "id": "emotion_engine_source_required_for_fix",
            "message": "diagnosis completed without upstream source; pass --emotion-engine-source to refresh managed runtime files",
        })
    result["provenance"] = _target_provenance(target_dir, _load_manifest(target_dir))
    return _finalize_doctor_readiness(
        result,
        target_dir,
        _load_manifest(target_dir),
    )


def _finalize_doctor_readiness(result, target_dir, manifest):
    result["readiness"] = target_readiness(
        target_dir,
        manifest,
        structural_ok=result["ok"],
        issues=result["issues"],
        warnings=result["warnings"],
    )
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
    canonical_present = _emotion_engine_state_path(target_dir).is_file()
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


def _emotion_engine_lifecycle_warnings(target_dir, manifest):
    if not isinstance(manifest, dict) or manifest.get("adapter") != "codex":
        return []
    feature = manifest.get("features", {}).get("emotion_engine", {})
    activation = feature.get("activation", {}) if isinstance(feature, dict) else {}
    if activation.get("active") is not True:
        return []
    receipt = target_dir / EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH
    if receipt.is_file():
        return []
    return [{
        "id": "emotion_engine_lifecycle_unverified",
        "path": EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH,
        "message": (
            "the local v3 runtime is ready, but no host-native Codex SessionStart "
            "has produced a matching lifecycle receipt yet"
        ),
    }]


def _adapter_activation_warnings(manifest):
    if not isinstance(manifest, dict) or manifest.get("adapter") != "pi":
        return []
    return [
        {
            "id": "pi_project_trust_unverified",
            "message": (
                "Packwright cannot inspect Pi's user-scoped project trust decision; "
                "open the target in Pi and confirm /trust before relying on project Agent Skills"
            ),
        }
    ]


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
    if _migrate_should_include_emotion_engine(
        resolved_emotion_engine_source
    ) and not emotion_engine_runtime_supported(to_adapter):
        raise PackwrightValidationError([
            f"Emotion Engine runtime is unavailable for {to_adapter}; "
            "omit --emotion-engine-source to carry state as an inert snapshot"
        ])
    available_emotion_state_source = _select_emotion_state_source(source_target_dir)
    emotion_state_source = (
        available_emotion_state_source if include_emotion_state else None
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
    pack = bind_pack_runtime_paths(pack, target_dir)
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
    emotion_state_reset = bool(
        _migrate_should_include_emotion_engine(resolved_emotion_engine_source)
        and available_emotion_state_source
        and not include_emotion_state
        and _directory_is_empty_or_missing(target_dir)
    )
    changes["emotion_state_resets"] = (
        [
            {
                "path": EMOTION_ENGINE_STATE_PATH,
                "source_path": str(available_emotion_state_source),
                "operation": "initialize_fresh_state",
                "trust_anchor": 0.1,
                "reason": (
                    "--no-emotion-state excludes existing source continuity while the "
                    "destination runtime initializes a fresh state"
                ),
            }
        ]
        if emotion_state_reset
        else []
    )
    if emotion_state_reset:
        warnings.append(
            {
                "id": "emotion_state_reset",
                "path": EMOTION_ENGINE_STATE_PATH,
                "message": (
                    "source Emotion Engine continuity is excluded; the empty destination "
                    "will initialize fresh state with trust_anchor=0.1"
                ),
            }
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
            reset=emotion_state_reset,
            excluded_source=available_emotion_state_source if emotion_state_reset else None,
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
        emotion_state_sha256=(
            _file_sha256(emotion_state_source)
            if emotion_state_source is not None
            else None
        ),
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
            "migration contains runtime automation behavior gaps that will not be reproduced in the destination",
            "review the degraded receipt and explicitly accept the behavior gap before applying",
        ])
    planned_score = plan.report["score"]["planned"]
    if not planned_score["passed"]:
        raise PackwrightValidationError(["destination adapter pack failed its planned checker score"])

    state_snapshot_temp = None
    applied_state_source = plan.emotion_state_source
    with _emotion_engine_target_lock(plan.source_target_dir):
        _assert_no_incomplete_emotion_engine_migration(plan.source_target_dir)
        pending_path = _emotion_engine_managed_path(
            plan.source_target_dir,
            EMOTION_ENGINE_PROJECTION_PENDING_PATH,
            "migration source sidecar pending marker",
        )
        if pending_path.is_file():
            raise PackwrightValidationError([
                "migration source has an incomplete sidecar projection transaction"
            ])
        source_integrity = _verify_migration_source(plan.report["changes"], plan.source_target_dir)
        if not source_integrity["passed"]:
            raise PackwrightValidationError(
                [
                    "migration source changed after the plan was prepared; prepare a new plan before writing",
                    *[issue["message"] for issue in source_integrity["issues"]],
                ]
            )
        if plan.emotion_state_source is not None:
            state_bytes = Path(plan.emotion_state_source).read_bytes()
            if _sha256_bytes(state_bytes) != plan.emotion_state_sha256:
                raise PackwrightValidationError([
                    "migration source Emotion Engine state changed after planning; no destination files were written"
                ])
            state_snapshot_temp = tempfile.TemporaryDirectory(
                prefix="packwright-emotion-export-snapshot-"
            )
            applied_state_source = Path(state_snapshot_temp.name) / "state.packet"
            _write_bytes_atomic(applied_state_source, state_bytes)
    destination_integrity = _verify_migration_destination(
        plan.report["changes"],
        plan.source_target_dir,
        plan.target_dir,
    )
    if not destination_integrity["passed"]:
        raise PackwrightValidationError(
            [
                "migration destination changed after the plan was prepared; prepare a new plan before writing",
                *[issue["message"] for issue in destination_integrity["issues"]],
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
            emotion_state_source=applied_state_source,
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
            applied_state_source,
        )
    finally:
        if temp_pack is not None:
            temp_pack.cleanup()
        if state_snapshot_temp is not None:
            state_snapshot_temp.cleanup()

    integrity = _verify_migration_integrity(plan.report["changes"], plan.target_dir)
    installed_pack = _read_installed_pack(plan.target_dir)
    installed_score = _score_migration_pack(plan.resolved, installed_pack, plan.to_adapter)
    receipt = plan.to_dict()
    receipt.update(
        {
            "status": "applied_with_degradations" if degraded else "applied",
            "ready": True,
            "ok": integrity["passed"],
            "installed_score_passed": bool(installed_score["passed"]),
            "verification_attention": (
                []
                if installed_score["passed"]
                else ["installed checker score did not pass; operation integrity still passed"]
            ),
            "integrity": integrity,
            "source_integrity": source_integrity,
            "destination_integrity": destination_integrity,
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
                reset=bool(plan.report["changes"].get("emotion_state_resets")),
                excluded_source=(
                    plan.report["changes"]["emotion_state_resets"][0]["source_path"]
                    if plan.report["changes"].get("emotion_state_resets")
                    else None
                ),
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
    pack = bind_pack_runtime_paths(pack, target_dir)
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
    changes, conflicts = _plan_reconcile_changes(
        target_dir,
        installed_manifest,
        pack,
        to_spec_hash,
    )
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
    relocation_reanchors = [
        item
        for item in changes["side_effect_writes"]
        if item.get("reason") == "reanchor_relocation_baseline"
    ]
    if relocation_reanchors:
        required_confirmations.append(
            {
                "id": "accept_relocation_baseline_reanchor",
                "kind": "relocation",
                "paths": [item["path"] for item in relocation_reanchors],
                "message": "accept rebinding path-sensitive automation to the current target",
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
        "warnings": (
            [
                {
                    "id": "relocation_baseline_reanchor",
                    "path": relocation_reanchors[0]["path"],
                    "message": (
                        "the installed relocation baseline differs from the current target; "
                        "reconcile will explicitly re-anchor path-sensitive automation"
                    ),
                }
            ]
            if relocation_reanchors
            else []
        ),
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
    if emotion_engine_expected(plan.installed_manifest):
        with _emotion_engine_target_lock(plan.target_dir):
            _assert_no_incomplete_emotion_engine_migration(plan.target_dir)
            _assert_emotion_artifact_lock_current(plan.target_dir)
            return _apply_reconcile_locked(plan, accept_degraded=accept_degraded)
    return _apply_reconcile_locked(plan, accept_degraded=accept_degraded)


def _apply_reconcile_locked(plan, accept_degraded=False):
    """Apply reconcile after any required project transaction lock is held."""
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
        install_plan = plan_install(
            pack_dir,
            plan.target_dir,
            adapter=plan.report["adapter"],
            force=True,
            persist_provenance=False,
        )
        install_result = _apply_install_locked(install_plan)
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
        _update_artifact_lock_paths(
            plan.target_dir,
            [adapter_entry(plan.report["adapter"])],
        )

    installed_pack = _read_installed_pack(plan.target_dir)
    installed_score = _score_migration_pack(
        plan.resolved,
        installed_pack,
        plan.report["adapter"],
    )
    installed_spec = resolve_source_path(
        plan.target_dir, SPEC_PATH, "reconciled canonical spec"
    )
    installed_spec_hash = _sha256_bytes(installed_spec.read_bytes())
    doctor = doctor_target(plan.target_dir)
    spec_applied = installed_spec_hash == plan.report["spec"]["to_sha256"]
    verification_attention = []
    if not installed_score["passed"]:
        verification_attention.append(
            "installed checker score did not pass; reconcile operation still applied the requested spec"
        )
    if not doctor["ok"]:
        verification_attention.append(
            "managed projection doctor found structural issues after reconcile"
        )
    receipt = plan.to_dict()
    receipt.update(
        {
            "status": "applied_with_degradations" if degraded else "applied",
            "ok": spec_applied,
            "spec_applied": spec_applied,
            "installed_score_passed": bool(installed_score["passed"]),
            "doctor_ok": bool(doctor["ok"]),
            "verification_attention": verification_attention,
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
    _write_json_atomic(receipt_path, receipt)
    return receipt


def _plan_reconcile_changes(target_dir, installed_manifest, pack, to_spec_hash):
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
                merged_text = merge_managed_hook_config(existing_text, desired)
                same = existing_text == merged_text
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
    side_effect_writes = _reconcile_side_effect_writes(
        target_dir,
        desired_manifest,
        to_spec_hash,
    )
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
            "side_effect_writes": side_effect_writes,
        },
        conflicts,
    )


def _reconcile_side_effect_writes(target_dir, desired_manifest, to_spec_hash):
    writes = []
    feature = (
        desired_manifest.get("features", {}).get("automations", {})
        if isinstance(desired_manifest, dict)
        else {}
    )
    records = feature.get("records", []) if isinstance(feature, dict) else []
    needs_baseline = any(
        isinstance(record, dict)
        and record.get("producer") == "relocation_guard"
        and str(record.get("status", "")).startswith("projected")
        for record in records
    )
    if needs_baseline:
        rel_path = ".packwright/baseline-path"
        destination = target_dir / rel_path
        desired = str(target_dir.resolve()) + "\n"
        current = None
        try:
            current = destination.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            pass
        if current != desired:
            writes.append(
                {
                    "path": rel_path,
                    "operation": "add" if current is None else "update",
                    "reason": (
                        "initialize_relocation_baseline"
                        if current is None
                        else "reanchor_relocation_baseline"
                    ),
                }
            )
    receipt_path = (
        f".packwright/receipts/reconcile-{to_spec_hash[:12]}.json"
    )
    writes.append(
        {
            "path": receipt_path,
            "operation": "update" if (target_dir / receipt_path).is_file() else "add",
            "reason": "write_reconcile_receipt",
        }
    )
    return writes


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
    for rel_path in emotion_engine_managed_artifacts(adapter):
        path = target_dir / rel_path
        if path.is_file():
            enriched[rel_path] = path.read_text(encoding="utf-8")
            sidecar_paths.append(rel_path)
    mcp_config_path = emotion_engine_mcp_config_path(adapter)
    mcp_config = target_dir / mcp_config_path
    if mcp_config.is_file():
        enriched[mcp_config_path] = mcp_config.read_text(encoding="utf-8")
        sidecar_paths.append(mcp_config_path)
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
        if rel_path == LOCK_PATH or _is_sidecar_private_path(rel_path):
            continue
        content = normalized.get(rel_path)
        if content is None:
            continue
        if is_managed_automation_config(manifest, rel_path):
            artifacts[rel_path] = {
                "mode": "managed_json_hooks",
                "sha256": managed_hook_fragment_digest(content),
            }
        elif emotion_engine_expected(manifest) and rel_path == adapter_entry(manifest.get("adapter")):
            artifacts[rel_path] = {
                "mode": "managed_text_block",
                "sha256": _sha256_bytes(content.encode("utf-8")),
                "unmanaged_sha256": _emotion_entry_unmanaged_digest(content),
            }
        elif (
            emotion_engine_expected(manifest)
            and rel_path == emotion_engine_mcp_config_path(manifest.get("adapter"))
        ):
            artifacts[rel_path] = {
                "mode": "managed_mcp_config",
                "sha256": _sha256_bytes(content.encode("utf-8")),
                "unmanaged_sha256": _emotion_mcp_unmanaged_digest(
                    content,
                    manifest.get("adapter"),
                ),
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
    removed_destination_state = _plan_destination_portable_state_removals(
        source_target_dir,
        target_dir,
        source_files,
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

    target_manifest = json.loads(pack["manifest.json"])
    automation_feature = target_manifest.get("features", {}).get("automations", {})
    automation_records = (
        automation_feature.get("records", [])
        if isinstance(automation_feature, dict)
        else []
    )
    pending_activation = [
        copy.deepcopy(record)
        for record in automation_records
        if isinstance(record, dict)
        and record.get("status") == "projected_pending_user_review"
    ]
    degraded = _plan_runtime_automation_degradations(
        source_target_dir,
        source_manifest,
        from_adapter,
        to_adapter,
    )
    source_degraded = list(degraded)
    degraded.extend(
        _plan_destination_runtime_capability_gaps(
            target_manifest,
            from_adapter,
            to_adapter,
        )
    )
    if source_degraded:
        warnings.append(
            {
                "id": "runtime_automation_degraded",
                "paths": [item["path"] for item in source_degraded],
                "message": (
                    "unmanaged runtime automation is outside the installed canonical spec; "
                    "it will be left behind unless the user explicitly accepts the behavior gap"
                ),
            }
        )
    destination_gaps = [
        item for item in degraded
        if item.get("kind") == "canonical_runtime_capability_gap"
    ]
    if destination_gaps:
        warnings.append(
            {
                "id": "destination_runtime_capability_gap",
                "automations": [item["automation_id"] for item in destination_gaps],
                "message": (
                    f"{to_adapter} cannot reproduce these canonical automations "
                    "with its current projected runtime capabilities"
                ),
            }
        )

    carried_paths = {item["path"] for item in carried}
    rewritten_paths = {item["path"] for item in rewritten}
    degraded_paths = {item["path"] for item in degraded if item.get("path")}
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
            "removed_destination_state": removed_destination_state,
            "degraded": degraded,
            "excluded": excluded,
            "pending_activation": pending_activation,
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


def _plan_destination_portable_state_removals(
    source_target_dir,
    target_dir,
    source_files,
):
    if not target_dir.is_dir():
        return []
    source_paths = set(source_files)
    removed = []
    for root_name in PORTABLE_STATE_DIRS:
        source_root = source_target_dir / root_name
        destination_root = target_dir / root_name
        if not source_root.exists() or not destination_root.exists():
            continue
        resolve_source_path(
            target_dir,
            root_name,
            "portable destination state root",
            require_file=False,
        )
        if not destination_root.is_dir():
            raise PackwrightValidationError(
                [f"destination portable state path is not a directory: {destination_root}"]
            )
        for path in sorted(destination_root.rglob("*")):
            rel_path = str(path.relative_to(target_dir))
            resolved = resolve_source_path(
                target_dir,
                rel_path,
                "portable destination state",
                require_file=False,
            )
            if not resolved.is_file() or rel_path in source_paths:
                continue
            removed.append(
                {
                    "path": rel_path,
                    "sha256": _file_sha256(resolved),
                    "reason": (
                        f"destination-only file removed when source {root_name}/ "
                        "is mirrored into the destination"
                    ),
                }
            )
    return sorted(removed, key=lambda item: item["path"])


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
                "reason": _emotion_engine_projection_exclusion_reason(to_adapter),
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


def _plan_destination_runtime_capability_gaps(target_manifest, from_adapter, to_adapter):
    feature = target_manifest.get("features", {}).get("automations", {})
    records = feature.get("records", []) if isinstance(feature, dict) else []
    return [
        {
            "id": "destination_runtime_capability_gap",
            "kind": "canonical_runtime_capability_gap",
            "automation_id": record.get("id"),
            "canonical_event": record.get("canonical_event"),
            "effect": record.get("effect"),
            "status": record.get("status"),
            "reason_code": (
                "destination_requires_reviewed_extension"
                if record.get("status") == "unavailable_requires_extension"
                else "destination_missing_runtime_capability"
            ),
            "reason": record.get(
                "reason",
                f"{to_adapter} cannot reproduce this canonical automation",
            ),
            "source_adapter": from_adapter,
            "destination_adapter": to_adapter,
            "required_decision": "accept_behavior_gap",
        }
        for record in records
        if str(record.get("status", "")).startswith("unavailable_")
    ]


def _emotion_engine_projection_exclusion_reason(to_adapter):
    if not emotion_engine_runtime_supported(to_adapter):
        return (
            f"{to_adapter} has no Emotion Engine runtime projection; "
            "the source runtime artifact is not copied"
        )
    return f"replaced by the {to_adapter} Emotion Engine runtime projection"


def _migration_required_confirmations(changes):
    degraded = changes.get("degraded", [])
    confirmations = []
    removed = changes.get("removed_destination_state", [])
    if removed:
        confirmations.append(
            {
                "id": "accept_destination_portable_state_removal",
                "kind": "removal",
                "paths": [item["path"] for item in removed],
                "message": (
                    "accept removal of destination-only portable files when source state "
                    "is mirrored into the destination"
                ),
            }
        )
    resets = changes.get("emotion_state_resets", [])
    if resets:
        confirmations.append(
            {
                "id": "accept_emotion_state_reset",
                "kind": "reset",
                "paths": [item["path"] for item in resets],
                "source_paths": [item["source_path"] for item in resets],
                "message": (
                    "accept excluding source Emotion Engine continuity and initializing "
                    "fresh destination state with trust_anchor=0.1"
                ),
            }
        )
    if not degraded:
        return confirmations
    paths = [item["path"] for item in degraded if item.get("path")]
    automations = [
        item.get("automation_id", item.get("id"))
        for item in degraded
        if item.get("kind") == "canonical_runtime_capability_gap"
    ]
    confirmations.append(
        {
            "id": "accept_degraded_runtime_automation",
            "kind": "degradation",
            "paths": paths,
            "automations": automations,
            "message": (
                "accept that listed source or canonical runtime automation will not be "
                "reproduced in the destination"
            ),
        }
    )
    return confirmations


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
    planned_portable_paths = {
        item["path"]
        for category in ("carried", "rewritten")
        for item in changes[category]
        if _is_portable_path(item["path"])
    }
    actual_portable_paths = set(_portable_source_files(source_target_dir))
    for rel_path in sorted(actual_portable_paths - planned_portable_paths):
        checks.append({"path": rel_path, "passed": False})
        issues.append(
            {
                "path": rel_path,
                "message": f"source added after planning: {rel_path}",
            }
        )
    for rel_path in sorted(planned_portable_paths - actual_portable_paths):
        checks.append({"path": rel_path, "passed": False})
        issues.append(
            {
                "path": rel_path,
                "message": f"source removed after planning: {rel_path}",
            }
        )
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
        if not item.get("path"):
            continue
        path = source_target_dir / item["path"]
        actual = _file_sha256(path) if path.is_file() else None
        passed = actual == item["sha256"]
        checks.append({"path": item["path"], "passed": passed})
        if not passed:
            issues.append({"path": item["path"], "message": f"source changed: {item['path']}"})
    return {"passed": not issues, "checked": len(checks), "issues": issues}


def _verify_migration_destination(changes, source_target_dir, target_dir):
    checks = []
    issues = []
    planned = {
        item["path"]: item["sha256"]
        for item in changes.get("removed_destination_state", [])
    }
    actual = {
        item["path"]: item["sha256"]
        for item in _plan_destination_portable_state_removals(
            source_target_dir,
            target_dir,
            _portable_source_files(source_target_dir),
        )
    }
    for rel_path in sorted(set(planned) | set(actual)):
        passed = actual.get(rel_path) == planned.get(rel_path)
        checks.append({"path": rel_path, "passed": passed})
        if not passed:
            issues.append(
                {
                    "path": rel_path,
                    "message": f"destination changed: {rel_path}",
                }
            )
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
    for item in changes.get("removed_destination_state", []):
        path = target_dir / item["path"]
        passed = not path.exists() and not path.is_symlink()
        checks.append(
            {
                "path": item["path"],
                "category": "removed_destination_state",
                "passed": passed,
            }
        )
        if not passed:
            issues.append(
                {
                    "path": item["path"],
                    "category": "removed_destination_state",
                    "message": "destination-only portable file was not removed as planned",
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
            mode = record.get("mode")
            if mode not in {"managed_json_hooks", "managed_text_block", "managed_mcp_config"}:
                issues.append(f"artifact lock mode is unsupported: {rel_path}")
                continue
            digest = record.get("sha256")
            if mode in {"managed_text_block", "managed_mcp_config"}:
                unmanaged_digest = record.get("unmanaged_sha256")
                if (
                    not isinstance(unmanaged_digest, str)
                    or len(unmanaged_digest) != 64
                    or any(char not in "0123456789abcdef" for char in unmanaged_digest.lower())
                ):
                    issues.append(
                        f"managed text block baseline must include an unmanaged SHA-256 digest: {rel_path}"
                    )
                    continue
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
            issues.append(f"artifact lock digest must be a SHA-256 hex string: {rel_path}")
            continue
        if isinstance(record, dict):
            normalized_record = {"mode": record["mode"], "sha256": digest.lower()}
            if record["mode"] in {"managed_text_block", "managed_mcp_config"}:
                normalized_record["unmanaged_sha256"] = record["unmanaged_sha256"].lower()
            normalized[relative] = normalized_record
        else:
            normalized[relative] = digest.lower()
    if issues:
        raise PackwrightValidationError(issues)
    return normalized


def _is_sidecar_private_path(rel_path):
    """Return whether a path is live sidecar-owned state, never Packwright baseline."""
    return rel_path == ".emotion-engine" or rel_path.startswith(".emotion-engine/")


def _assert_emotion_artifact_lock_current(
    target_dir,
    owned_paths=(),
    owned_fragments=(),
):
    """Verify the complete Packwright-managed baseline before any writer transaction."""
    target_dir = Path(target_dir)
    manifest_path = resolve_destination_path(
        target_dir,
        "manifest.json",
        "installed manifest",
    )
    if not manifest_path.is_file():
        return True
    lock_path = resolve_destination_path(
        target_dir,
        LOCK_PATH,
        "artifact lock",
    )
    if not lock_path.is_file():
        raise PackwrightValidationError([
            "Packwright artifact lock is missing; refusing to create a new baseline over an existing target"
        ])
    locked = _load_artifact_lock(target_dir)
    manifest = _load_manifest(target_dir)
    operation_owned = {str(rel_path) for rel_path in owned_paths}
    operation_fragments = {str(rel_path) for rel_path in owned_fragments}
    issues = []
    expected_paths = {
        rel_path
        for rel_path in _manifest_artifacts(manifest)
        if rel_path != LOCK_PATH
        and not _is_portable_path(rel_path)
        and not _is_sidecar_private_path(rel_path)
    }
    expected_paths.add("manifest.json")
    for rel_path in sorted(expected_paths):
        if rel_path not in locked and rel_path not in operation_owned:
            issues.append(
                f"Packwright artifact lock has no baseline for managed artifact: {rel_path}"
            )
    for rel_path, expected_record in sorted(locked.items()):
        if (
            rel_path == LOCK_PATH
            or _is_portable_path(rel_path)
            or _is_sidecar_private_path(rel_path)
            or rel_path in operation_owned
        ):
            continue
        try:
            path = resolve_source_path(target_dir, rel_path, "managed artifact baseline")
            if rel_path in operation_fragments:
                if isinstance(expected_record, dict) and expected_record.get("mode") in {
                    "managed_text_block",
                    "managed_mcp_config",
                }:
                    if expected_record["mode"] == "managed_text_block":
                        actual_unmanaged = _emotion_entry_unmanaged_digest(
                            path.read_text(encoding="utf-8")
                        )
                    else:
                        actual_unmanaged = _emotion_mcp_unmanaged_digest(
                            path.read_text(encoding="utf-8"),
                            manifest.get("adapter"),
                        )
                    if actual_unmanaged != expected_record["unmanaged_sha256"]:
                        issues.append(
                            f"unmanaged shared artifact content changed outside its Packwright baseline: {rel_path}"
                        )
                    continue
                # A pre-fragment lock can be upgraded only while the complete old
                # baseline still matches. This never adopts current drift.
            actual = _artifact_lock_actual_digest(expected_record, path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, PackwrightValidationError) as exc:
            issues.append(f"managed artifact baseline is missing, unsafe, or unreadable: {rel_path}: {exc}")
            continue
        if actual != _artifact_lock_digest(expected_record):
            issues.append(
                f"managed artifact changed outside its Packwright artifact-lock baseline: {rel_path}"
            )
    if issues:
        raise PackwrightValidationError([
            "refusing to wash managed artifact drift into a writer transaction",
            *issues,
        ])
    return True


def _refresh_artifact_lock(target_dir):
    lock_path = target_dir / LOCK_PATH
    manifest = _load_manifest(target_dir)
    if not _artifact_lock_enabled(manifest):
        return False
    artifacts = {}
    for rel_path in _manifest_artifacts(manifest):
        if (
            rel_path == LOCK_PATH
            or _is_sidecar_private_path(rel_path)
        ):
            continue
        path = resolve_source_path(target_dir, rel_path, "installed artifact")
        artifacts[rel_path] = _artifact_lock_record(manifest, rel_path, path)
    manifest_path = resolve_source_path(target_dir, "manifest.json", "installed manifest")
    artifacts["manifest.json"] = _artifact_lock_record(
        manifest,
        "manifest.json",
        manifest_path,
    )
    destination = resolve_destination_path(target_dir, LOCK_PATH, "artifact lock destination")
    return _write_text_if_changed(
        destination,
        json.dumps(
            {"schema": "packwright-lock/v1", "artifacts": artifacts},
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _update_artifact_lock_paths(target_dir, rel_paths, removed_paths=()):
    """Commit only artifacts owned by the completed transaction."""
    lock_path = target_dir / LOCK_PATH
    if not lock_path.is_file():
        return False
    locked = _load_artifact_lock(target_dir)
    for rel_path in tuple(locked):
        if _is_sidecar_private_path(rel_path):
            locked.pop(rel_path, None)
    for rel_path in removed_paths:
        locked.pop(rel_path, None)
    manifest = _load_manifest(target_dir)
    manifest_artifacts = set(_manifest_artifacts(manifest))
    for rel_path in rel_paths:
        if (
            rel_path == LOCK_PATH
            or _is_portable_path(rel_path)
            or _is_sidecar_private_path(rel_path)
        ):
            continue
        if rel_path != "manifest.json" and rel_path not in manifest_artifacts:
            continue
        path = resolve_source_path(target_dir, rel_path, "managed artifact")
        locked[rel_path] = _artifact_lock_record(manifest, rel_path, path)
    destination = resolve_destination_path(target_dir, LOCK_PATH, "artifact lock destination")
    _write_text_atomic(
        destination,
        json.dumps({"schema": "packwright-lock/v1", "artifacts": locked}, indent=2, sort_keys=True) + "\n",
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
        if rel_path == LOCK_PATH or _is_portable_path(rel_path) or _is_sidecar_private_path(rel_path):
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
            or _is_sidecar_private_path(rel_path)
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
        expected = bind_pack_runtime_paths(expected, target_dir)
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
        if isinstance(expected_record, dict) and expected_record.get("mode") == "managed_json_hooks":
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
        if (
            isinstance(expected_record, dict)
            and expected_record.get("mode") == "managed_json_hooks"
            and destination.is_file()
        ):
            try:
                content = merge_managed_hook_config(
                    destination.read_text(encoding="utf-8"), content
                )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                continue
        _write_text_atomic(destination, content)
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
    if emotion_engine_expected(manifest) and rel_path == adapter_entry(manifest.get("adapter")):
        text = path.read_text(encoding="utf-8")
        return {
            "mode": "managed_text_block",
            "sha256": _sha256_bytes(text.encode("utf-8")),
            "unmanaged_sha256": _emotion_entry_unmanaged_digest(text),
        }
    if (
        emotion_engine_expected(manifest)
        and rel_path == emotion_engine_mcp_config_path(manifest.get("adapter"))
    ):
        text = path.read_text(encoding="utf-8")
        return {
            "mode": "managed_mcp_config",
            "sha256": _sha256_bytes(text.encode("utf-8")),
            "unmanaged_sha256": _emotion_mcp_unmanaged_digest(
                text,
                manifest.get("adapter"),
            ),
        }
    return _file_sha256(path)


def _artifact_lock_digest(record):
    return record["sha256"] if isinstance(record, dict) else record


def _artifact_lock_actual_digest(record, path):
    if isinstance(record, dict) and record.get("mode") == "managed_json_hooks":
        return managed_hook_fragment_digest(path.read_text(encoding="utf-8"))
    return _file_sha256(path)


def _emotion_entry_unmanaged_text(text):
    """Return a shared adapter entry with only Packwright's EE h2 removed."""
    lines = text.splitlines(keepends=True)
    output = []
    skipping = False
    for line in lines:
        stripped = line.rstrip("\r\n")
        if stripped in {"## Emotion Engine", "## Optional Emotion Engine"}:
            skipping = True
            continue
        if skipping and stripped.startswith("## "):
            skipping = False
        if not skipping:
            output.append(line)
    return "".join(output)


def _emotion_entry_unmanaged_digest(text):
    return _sha256_bytes(_emotion_entry_unmanaged_text(text).encode("utf-8"))


def _emotion_mcp_unmanaged_digest(text, adapter):
    if adapter == "codex":
        accepted_headers = {
            f"[mcp_servers.{EMOTION_ENGINE_SIDECAR}]",
            f'[mcp_servers."{EMOTION_ENGINE_SIDECAR}"]',
            f"[mcp_servers.'{EMOTION_ENGINE_SIDECAR}']",
        }
        lines = text.splitlines(keepends=True)
        output = []
        index = 0
        while index < len(lines):
            if lines[index].strip() not in accepted_headers:
                output.append(lines[index])
                index += 1
                continue
            index += 1
            while index < len(lines) and not lines[index].lstrip().startswith("["):
                index += 1
        payload = "".join(output).encode("utf-8")
    else:
        data = json.loads(text or "{}")
        if not isinstance(data, dict):
            raise ValueError("MCP configuration must be an object")
        unmanaged = copy.deepcopy(data)
        servers = unmanaged.get("mcpServers")
        if isinstance(servers, dict):
            servers.pop(EMOTION_ENGINE_SIDECAR, None)
            if not servers:
                unmanaged.pop("mcpServers", None)
        payload = json.dumps(unmanaged, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(payload)


def _write_automation_baseline(target_dir, manifest):
    feature = manifest.get("features", {}).get("automations", {}) if isinstance(manifest, dict) else {}
    records = feature.get("records", []) if isinstance(feature, dict) else []
    if not any(
        record.get("producer") == "relocation_guard"
        and str(record.get("status", "")).startswith("projected")
        for record in records
        if isinstance(record, dict)
    ):
        return False
    destination = resolve_destination_path(
        target_dir, ".packwright/baseline-path", "automation relocation baseline"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    return _write_text_if_changed(destination, str(target_dir.resolve()) + "\n")


def _write_text_if_changed(path, content):
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            return False
    except (OSError, UnicodeError):
        pass
    _write_text_atomic(path, content)
    return True


def _emotion_engine_managed_path(target_dir, rel_path, label):
    """Resolve every Packwright-owned Emotion Engine path without symlinks."""
    return resolve_destination_path(target_dir, rel_path, label)


def _emotion_engine_state_path(target_dir):
    return _emotion_engine_managed_path(
        target_dir,
        EMOTION_ENGINE_STATE_PATH,
        "Emotion Engine state destination",
    )


def _emotion_engine_migration_journal_path(target_dir):
    return _emotion_engine_managed_path(
        target_dir,
        EMOTION_ENGINE_MIGRATION_JOURNAL_PATH,
        "Emotion Engine migration journal",
    )


def _emotion_engine_migration_lineage_path(target_dir):
    return _emotion_engine_managed_path(
        target_dir,
        EMOTION_ENGINE_MIGRATION_LINEAGE_PATH,
        "Emotion Engine migration lineage",
    )


def _clear_emotion_projection_pending(target_dir):
    pending_path = _emotion_engine_managed_path(
        target_dir,
        EMOTION_ENGINE_PROJECTION_PENDING_PATH,
        "Emotion Engine projection transaction marker",
    )
    try:
        pending_path.unlink()
    except FileNotFoundError:
        return False
    return True


def _resume_emotion_projection_commit(target_dir):
    """Forward-commit a verified manifest-to-lock crash window, or fail closed."""
    pending_path = _emotion_engine_managed_path(
        target_dir,
        EMOTION_ENGINE_PROJECTION_PENDING_PATH,
        "Emotion Engine projection transaction marker",
    )
    if not pending_path.is_file():
        return False
    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackwrightValidationError([
            f"Emotion Engine projection transaction marker is unreadable: {exc}"
        ]) from exc
    if (
        not isinstance(pending, dict)
        or pending.get("schema") != "packwright-sidecar-projection-transaction/v1"
        or pending.get("status") != "host_commit_pending"
    ):
        raise PackwrightValidationError([
            "Emotion Engine projection transaction is incomplete and cannot be safely resumed",
            f"projection phase: {pending.get('status') if isinstance(pending, dict) else 'invalid'}",
        ])
    owned_paths = pending.get("lock_owned_paths")
    removed_paths = pending.get("lock_removed_paths", [])
    after_digests = pending.get("after_digests")
    if (
        not isinstance(owned_paths, list)
        or not all(isinstance(path, str) for path in owned_paths)
        or not isinstance(removed_paths, list)
        or not all(isinstance(path, str) for path in removed_paths)
        or not isinstance(after_digests, dict)
    ):
        raise PackwrightValidationError([
            "Emotion Engine projection transaction has invalid resume metadata"
        ])
    manifest_path = resolve_source_path(target_dir, "manifest.json", "projection resume manifest")
    if _file_sha256(manifest_path) != pending.get("manifest_after_sha256"):
        raise PackwrightValidationError([
            "resume_conflict: manifest changed after the interrupted sidecar commit"
        ])
    receipt_path = _emotion_engine_managed_path(
        target_dir,
        EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
        "projection resume receipt",
    )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackwrightValidationError([f"resume_conflict: projection receipt is invalid: {exc}"]) from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("projection_nonce") != pending.get("projection_nonce")
        or receipt.get("source_digest") != pending.get("source_digest")
    ):
        raise PackwrightValidationError([
            "resume_conflict: projection receipt does not match the interrupted transaction"
        ])
    for rel_path, expected_digest in sorted(after_digests.items()):
        path = resolve_source_path(target_dir, rel_path, "projection resume artifact")
        if _file_sha256(path) != expected_digest:
            raise PackwrightValidationError([
                f"resume_conflict: sidecar transaction artifact changed after interruption: {rel_path}"
            ])
    for rel_path in removed_paths:
        path = resolve_destination_path(target_dir, rel_path, "projection resume removed artifact")
        if path.exists() or path.is_symlink():
            raise PackwrightValidationError([
                f"resume_conflict: removed sidecar artifact reappeared after interruption: {rel_path}"
            ])

    locked = _load_artifact_lock(target_dir)
    operation_owned = set(owned_paths) | set(removed_paths)
    for rel_path, record in locked.items():
        if rel_path in operation_owned or _is_portable_path(rel_path) or _is_sidecar_private_path(rel_path):
            continue
        path = resolve_source_path(target_dir, rel_path, "projection resume baseline")
        if _artifact_lock_actual_digest(record, path) != _artifact_lock_digest(record):
            raise PackwrightValidationError([
                f"resume_conflict: unrelated managed artifact changed after interruption: {rel_path}"
            ])
    _update_artifact_lock_paths(target_dir, owned_paths, removed_paths=removed_paths)
    _clear_emotion_projection_pending(target_dir)
    return True


def _incomplete_emotion_engine_migration(target_dir):
    journal_path = _emotion_engine_migration_journal_path(target_dir)
    if not journal_path.is_file():
        return None
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackwrightValidationError([
            f"Emotion Engine migration journal is unreadable: {journal_path}: {exc}"
        ]) from exc
    if not isinstance(journal, dict):
        raise PackwrightValidationError([
            f"Emotion Engine migration journal is invalid: {journal_path}"
        ])
    return journal if journal.get("status") == "in_progress" else None


def _assert_no_incomplete_emotion_engine_migration(target_dir):
    journal = _incomplete_emotion_engine_migration(target_dir)
    if journal is not None:
        raise PackwrightValidationError([
            "an Emotion Engine migration transaction is still in progress; "
            "rerun migrate-emotion-state to recover it before install, refresh, or runtime writes",
            f"migration phase: {journal.get('phase') or 'unknown'}",
        ])


@contextmanager
def _emotion_engine_target_lock(target_dir):
    """Serialize every Packwright-owned Emotion Engine writer transition."""
    path = resolve_destination_path(
        target_dir,
        EMOTION_ENGINE_TARGET_LOCK_PATH,
        "Emotion Engine target transaction lock",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path.resolve())
    with _EMOTION_TARGET_THREAD_LOCKS_GUARD:
        thread_lock = _EMOTION_TARGET_THREAD_LOCKS.setdefault(key, threading.RLock())
    with thread_lock:
        depths = getattr(_EMOTION_TARGET_LOCK_LOCAL, "depths", {})
        depth = depths.get(key, 0)
        if depth:
            depths[key] = depth + 1
            _EMOTION_TARGET_LOCK_LOCAL.depths = depths
            try:
                yield
            finally:
                depths[key] -= 1
            return
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise PackwrightValidationError([
                f"Emotion Engine transaction lock is unsafe or unavailable: {path}: {exc}"
            ]) from exc
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise PackwrightValidationError([
                f"Emotion Engine transaction lock is not a regular file: {path}"
            ])
        handle = os.fdopen(descriptor, "a+b")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            elif msvcrt is not None:  # pragma: no cover - Windows fallback
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            depths[key] = 1
            _EMOTION_TARGET_LOCK_LOCAL.depths = depths
            yield
        finally:
            depths.pop(key, None)
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows fallback
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            handle.close()


def _snapshot_target_files(paths):
    snapshot = {}
    for path in {Path(value) for value in paths}:
        if path.is_file():
            snapshot[path] = {
                "content": path.read_bytes(),
                "mode": stat.S_IMODE(path.stat().st_mode),
            }
        else:
            snapshot[path] = None
    return snapshot


def _restore_target_files(snapshot):
    errors = []
    for path, record in snapshot.items():
        try:
            if record is None:
                if path.is_file() or path.is_symlink():
                    path.unlink()
                continue
            _write_bytes_atomic(path, record["content"])
            path.chmod(record["mode"])
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    if errors:
        raise PackwrightValidationError([
            "Emotion Engine transaction rollback was incomplete",
            *errors,
        ])


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


def _migration_emotion_state_report(
    state_source,
    runtime_active,
    reset=False,
    excluded_source=None,
):
    source_schema = None
    if state_source:
        try:
            value = json.loads(Path(state_source).read_text(encoding="utf-8"))
            source_schema = value.get("_schema") if isinstance(value, dict) else None
        except (OSError, UnicodeError, json.JSONDecodeError):
            source_schema = "invalid"
    if reset:
        status = "reset_to_fresh_state"
    elif runtime_active and source_schema == EMOTION_ENGINE_LEGACY_STATE_SCHEMA:
        status = "migration_required"
    elif runtime_active:
        status = "active"
    elif state_source:
        status = "snapshot_inert"
    else:
        status = "not_carried"
    return {
        "path": EMOTION_ENGINE_STATE_PATH if runtime_active or state_source else None,
        "status": status,
        "source_path": str(state_source) if state_source else None,
        "source_schema": source_schema,
        "will_initialize": bool(runtime_active and not state_source),
        "excluded_source_path": str(excluded_source) if excluded_source else None,
        "initialized_trust_anchor": 0.1 if reset else None,
    }


def _directory_is_empty_or_missing(path):
    path = Path(path)
    if not path.exists():
        return True
    if not path.is_dir():
        return False
    try:
        next(path.iterdir())
    except StopIteration:
        return True
    return False


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
        _write_text_atomic(path, content)
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
            _write_text_atomic(path, workspace_readme())
            fixed.append(rel_path)
            continue
        if rel_path in workspace_artifacts() and rel_path.endswith("/.gitkeep"):
            path = resolve_destination_path(target_dir, rel_path, "workspace repair destination")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                _write_text_atomic(path, "")
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
            _write_text_atomic(path, knowledge_files()[rel_path])
            fixed.append(rel_path)
            continue
        if rel_path in handoff_artifacts and issue_id in {
            "handoff_tool_missing_file",
            "handoff_tool_file_drift",
            "manifest_artifact_missing",
        }:
            path = resolve_destination_path(target_dir, rel_path, "handoff repair destination")
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_text_atomic(path, handoff_artifacts[rel_path])
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
    _write_text_atomic(manifest_path, manifest_text)
    for rel_path in ("AGENTS.md", "memory/index.md", "memory/pinned.md", "memory/source-map.md"):
        path = resolve_destination_path(target_dir, rel_path, "memory projection repair destination")
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        updated = text.replace(".codex/skills/", ".agents/skills/")
        if updated != text:
            _write_text_atomic(path, updated)
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
            _write_text_atomic(path, projected)
            rewritten.append(rel_path)
    return rewritten


def _copy_emotion_state_snapshot(target_dir, source):
    if source is None:
        return []
    if not source.is_file():
        return []
    destination = _emotion_engine_state_path(target_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        _write_bytes_atomic(destination, source.read_bytes())
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
                "reason": _emotion_engine_projection_exclusion_reason(to_adapter),
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


def _stale_emotion_projection_receipts(target_dir, manifest):
    """Return previous-generation receipts that must be revoked on refresh."""
    target_dir = Path(target_dir)
    candidates = set()
    recorded = (
        manifest.get("sidecars", {}).get(EMOTION_ENGINE_SIDECAR, {}).get("projection_receipt")
        if isinstance(manifest, dict)
        else None
    )
    if isinstance(recorded, str) and recorded.strip():
        recorded_path = resolve_destination_path(
            target_dir,
            recorded.strip(),
            "manifest Emotion Engine projection receipt",
        )
        if recorded_path.is_file():
            candidates.add(recorded_path.resolve())
    generations_root = target_dir / ".packwright" / "runtime" / "emotion-engine" / "generations"
    if generations_root.is_dir():
        candidates.update(path.resolve() for path in generations_root.glob("*/projection.json") if path.is_file())

    current = (target_dir / EMOTION_ENGINE_PROJECTION_RECEIPT_PATH).resolve()
    stale = []
    root = target_dir.resolve()
    for path in candidates:
        if path == current:
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise PackwrightValidationError([
                f"Emotion Engine projection receipt escapes target: {path}"
            ]) from exc
        stale.append(validate_relative_path(relative, "stale Emotion Engine projection receipt").as_posix())
    return sorted(set(stale))


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
    approved = _approved_emotion_engine_source(source, adapter)
    source_root = approved["source_root"]
    snapshot = approved["files"]
    common = {
        target_path: snapshot[source_path]
        for target_path, source_path in EMOTION_ENGINE_COMMON_SOURCE_FILES.items()
    }
    upstream_skill = snapshot.get(approved["skill_path"], b"").decode("utf-8")
    _validate_emotion_engine_source(common, upstream_skill, adapter)

    projection = dict(common)
    projection[emotion_engine_skill_path(adapter)] = _project_emotion_skill_text(
        adapter,
        upstream_skill,
    ).encode("utf-8")
    projection[EMOTION_ENGINE_WRAPPER_PATH] = _project_emotion_wrapper_text().encode("utf-8")
    projection[EMOTION_ENGINE_WRITER_GATEWAY_PATH] = render_emotion_engine_writer_gateway().encode("utf-8")
    projection[EMOTION_ENGINE_MCP_WRAPPER_PATH] = _project_emotion_mcp_wrapper_text().encode("utf-8")
    projection[EMOTION_ENGINE_LIFECYCLE_PATH] = render_emotion_engine_lifecycle().encode("utf-8")
    projection[EMOTION_ENGINE_MCP_LAUNCHER_PATH] = render_emotion_engine_mcp_launcher().encode("utf-8")

    existing = [path for path in projection if (target_dir / path).exists()]

    identity = _emotion_engine_identity(manifest)
    declared_state = (
        manifest.get("sidecars", {}).get(EMOTION_ENGINE_SIDECAR, {}).get("state_file")
        if isinstance(manifest, dict)
        else None
    )
    selected_state = _select_emotion_state_source(
        target_dir,
        explicit=state_source,
        declared=declared_state,
    )
    if selected_state:
        issue = _emotion_engine_state_issue_for_path(
            selected_state,
            expected_identity=identity,
        )
        if issue and issue["id"] not in {
            "emotion_engine_state_migration_required",
            "emotion_engine_state_capability_mismatch",
        }:
            raise PackwrightValidationError([issue["message"] + f": {selected_state}"])

    config_plan = _prepare_emotion_engine_mcp_config(target_dir, adapter, force)
    lifecycle_config = prepare_codex_lifecycle_config(target_dir) if adapter == "codex" else None
    source_digest = _emotion_engine_source_digest(snapshot)
    installed_feature = manifest.get("features", {}).get("emotion_engine", {})
    return {
        "adapter": adapter,
        "source_root": source_root,
        "projection": projection,
        "existing_projection": existing,
        "source_digest": source_digest,
        "projection_nonce": (
            installed_feature.get("projection_nonce")
            if isinstance(installed_feature, dict)
            else None
        ),
        "state_file": _emotion_engine_state_path(target_dir),
        "state_source": selected_state,
        "emotion_style": emotion_style or _manifest_emotion_style(manifest),
        "relationship_continuity": _manifest_relationship_continuity(manifest),
        "identity": identity,
        "mode": emotion_engine_mode,
        "force": force,
        "mcp_config": config_plan,
        "lifecycle_config": lifecycle_config,
        "stale_projection_receipts": _stale_emotion_projection_receipts(
            target_dir,
            manifest,
        ),
    }


def _approved_emotion_engine_source(source, adapter):
    """Load an immutable file snapshot from the one approved upstream commit."""
    source_root = _resolve_emotion_engine_source(source)
    required = set(EMOTION_ENGINE_COMMON_SOURCE_FILES.values())
    skill_path = _emotion_engine_skill_source_path(adapter)
    if adapter != "cursor":
        required.add(skill_path)
    required.update({
        "integrations/codex/emotion-engine-codex/SKILL.md",
        "integrations/claude-skill/emotion-engine/SKILL.md",
    })
    snapshot = {}
    missing = []
    for rel_path in sorted(required):
        result = _run_bounded_subprocess(
            _safe_git_argv(
                "show",
                f"{EMOTION_ENGINE_UPSTREAM_COMMIT}:{rel_path}",
            ),
            cwd=source_root,
            timeout=15,
            output_limit=2_000_000,
        )
        if result["returncode"] != 0:
            if rel_path == skill_path and adapter == "cursor":
                continue
            missing.append(rel_path)
            continue
        snapshot[rel_path] = result["stdout"]
    if missing:
        raise PackwrightValidationError([
            f"approved Emotion Engine source is missing committed file: {path}"
            for path in missing
        ])
    return {
        "source_root": source_root,
        "files": snapshot,
        "skill_path": skill_path,
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
    top = _run_bounded_subprocess(
        _safe_git_argv("rev-parse", "--show-toplevel"),
        cwd=supplied,
        timeout=10,
        output_limit=16_384,
    )
    if top["returncode"] != 0:
        raise PackwrightValidationError([
            f"Emotion Engine source must be an approved Git checkout: {supplied}"
        ])
    try:
        source_root = Path(top["stdout"].decode("utf-8").strip()).resolve(strict=True)
    except (OSError, UnicodeError) as exc:
        raise PackwrightValidationError([f"invalid Emotion Engine Git root: {exc}"]) from exc
    approved_commit = _run_bounded_subprocess(
        _safe_git_argv(
            "cat-file",
            "-e",
            f"{EMOTION_ENGINE_UPSTREAM_COMMIT}^{{commit}}",
        ),
        cwd=source_root,
        timeout=10,
        output_limit=16_384,
    )
    if approved_commit["returncode"] != 0:
        raise PackwrightValidationError([
            "Emotion Engine source does not contain the approved revision "
            f"{EMOTION_ENGINE_UPSTREAM_COMMIT}"
        ])
    return source_root


def _emotion_engine_skill_source_path(adapter):
    if adapter == "claude-code":
        return "integrations/claude-skill/emotion-engine/SKILL.md"
    elif adapter in {"codex", "cursor"}:
        return "integrations/codex/emotion-engine-codex/SKILL.md"
    else:
        raise PackwrightValidationError([f"unsupported Emotion Engine adapter: {adapter}"])


def _validate_emotion_engine_source(common, skill_text, adapter):
    issues = []
    try:
        engine_text = common[f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_utils.py"].decode("utf-8")
        mcp_text = common[f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_mcp.py"].decode("utf-8")
    except UnicodeError as exc:
        raise PackwrightValidationError([f"approved Emotion Engine source is not UTF-8: {exc}"]) from exc
    required_engine_markers = [
        f'ENGINE_VERSION = "{EMOTION_ENGINE_VERSION}"',
        f'STATE_SCHEMA = "{EMOTION_ENGINE_STATE_SCHEMA}"',
        f'LEGACY_STATE_SCHEMA = "{EMOTION_ENGINE_LEGACY_STATE_SCHEMA}"',
        "STATE_CAPABILITIES",
        "activation_check",
        "migrate_state",
        "upgrade_state",
        "session_idempotency/v1",
        "bounded_active_session/v1",
        "missing_state_capabilities",
        "require_current_state_capabilities",
        "ManagedStateError",
        "require_managed_runtime_writable",
        "--managed-runtime",
        "settle_trust",
        "record_policy",
        "reply_bias",
    ]
    missing_markers = [marker for marker in required_engine_markers if marker not in engine_text]
    if missing_markers:
        issues.append(
            "Emotion Engine helper does not match the rc.4 state/identity/session contract: "
            + ", ".join(missing_markers)
        )
    if "SERVER_VERSION = engine.ENGINE_VERSION" not in mcp_text:
        issues.append(f"Emotion Engine MCP server must inherit helper version {EMOTION_ENGINE_VERSION}")
    if "--locked-state" not in mcp_text or "--managed-runtime" not in mcp_text:
        issues.append("Emotion Engine MCP server must support locked managed-runtime state access")
    if "tools/call requires a non-null request id" not in mcp_text:
        issues.append("Emotion Engine MCP server must reject id-less write RPC requests")
    if "Tool arguments must be an object" not in mcp_text:
        issues.append("Emotion Engine MCP server must reject non-object tool arguments")
    if "managed_runtime=managed_runtime" not in mcp_text:
        issues.append("Emotion Engine MCP server must propagate managed-runtime policy to state access")
    if "tools/list" not in mcp_text or "emotion_engine_record_policy" not in mcp_text:
        issues.append("Emotion Engine MCP server must expose record_policy through tools/list")
    if '"name": "emotion_engine_repair"' in mcp_text or "doctor_target" in mcp_text:
        issues.append("Emotion Engine MCP server must not expose Packwright repair commands")
    lowered_skill = skill_text.lower()
    if adapter != "cursor" and any(
        not any(candidate in lowered_skill for candidate in candidates)
        for candidates in (
            ("settle_trust",),
            ("event_id", "event-id"),
            ("pause",),
        )
    ):
        issues.append(
            f"Emotion Engine {adapter} guidance must document rc.4 identity, event-id, pause, and settlement controls"
        )
    if issues:
        raise PackwrightValidationError(issues)


def _emotion_engine_source_digest(files):
    digest = hashlib.sha256()
    for rel_path, content in sorted(files.items()):
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def _project_emotion_skill_text(adapter, upstream_text):
    if adapter == "cursor":
        return f"""---
description: Use the project-local Emotion Engine MCP tools for lightweight emotional continuity.
globs: []
alwaysApply: true
---

# Emotion Engine

Use the `emotion-engine` MCP server or `scripts/emotion_engine.sh` for project-local emotional continuity.
The live state is `{EMOTION_ENGINE_STATE_PATH}`; never mix it into durable `memory/*` files.
Run `record_policy` before persisting meaningful turns, and `settle_trust` only at a real session or milestone close.
Never expose raw PAD/trust values unless asked. Never run `reset` or `clear_log` without explicit user approval.
"""
    text = upstream_text
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
        f"live state is `{EMOTION_ENGINE_STATE_PATH}`. Call `record_policy` before any "
        "emotional persistence. In `paused` mode, do not record, decay, or modulate turns. "
        "Every emotional write requires the native session id, a unique event id, and the "
        "bound character and relationship ids.\n"
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
exec python3 "$PROJECT_DIR/{EMOTION_ENGINE_WRITER_GATEWAY_PATH}" "$COMMAND" "$@"
"""


def _project_emotion_mcp_wrapper_text():
    return f"""#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
exec python3 "$PROJECT_DIR/{EMOTION_ENGINE_MCP_LAUNCHER_PATH}"
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
        "projection_nonce": feature.get("projection_nonce"),
        "state_file": _emotion_engine_state_path(target_dir),
        "state_source": _select_emotion_state_source(
            target_dir,
            declared=manifest.get("sidecars", {}).get(EMOTION_ENGINE_SIDECAR, {}).get("state_file"),
        ),
        "identity": _emotion_engine_identity(manifest),
        "mode": mode,
        "mcp_config": _prepare_emotion_engine_mcp_config(target_dir, adapter, force=True),
        "lifecycle_config": prepare_codex_lifecycle_config(target_dir) if adapter == "codex" else None,
        "stale_projection_receipts": _stale_emotion_projection_receipts(
            target_dir,
            manifest,
        ),
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


def _emotion_engine_identity(manifest):
    recorded = (
        manifest.get("sidecars", {}).get(EMOTION_ENGINE_SIDECAR, {}).get("identity")
        if isinstance(manifest, dict)
        else None
    )
    if (
        isinstance(recorded, dict)
        and isinstance(recorded.get("character_id"), str)
        and recorded.get("character_id").strip()
        and isinstance(recorded.get("relationship_id"), str)
        and recorded.get("relationship_id").strip()
    ):
        return {
            "character_id": recorded["character_id"].strip(),
            "relationship_id": recorded["relationship_id"].strip(),
        }
    character = manifest.get("character", {}) if isinstance(manifest, dict) else {}
    character_id = character.get("slug") if isinstance(character, dict) else None
    if not isinstance(character_id, str) or not character_id.strip():
        raise PackwrightValidationError([
            "Emotion Engine v3 requires a stable character slug for state identity"
        ])
    character_id = character_id.strip()
    return {
        "character_id": character_id,
        "relationship_id": f"{character_id}:primary-user",
    }


def _emotion_engine_migration_identity(manifest, character_id=None, relationship_id=None):
    explicit = character_id is not None or relationship_id is not None
    if explicit:
        if not (
            isinstance(character_id, str)
            and character_id.strip()
            and isinstance(relationship_id, str)
            and relationship_id.strip()
        ):
            raise PackwrightValidationError([
                "Emotion Engine migration requires both explicit character_id and relationship_id"
            ])
        return {
            "character_id": character_id.strip(),
            "relationship_id": relationship_id.strip(),
        }
    identity = _emotion_engine_identity(manifest)
    if identity["character_id"].lower() in {
        "character",
        "agent",
        "assistant",
        "default",
        "unnamed",
    }:
        return None
    return identity


def _emotion_engine_expected_in_target(manifest, target_dir):
    if emotion_engine_expected(manifest):
        return True
    adapter = manifest.get("adapter")
    if adapter not in SUPPORTED_INSTALL_ADAPTERS:
        return False
    return any((target_dir / artifact).exists() for artifact in emotion_engine_artifacts(adapter))


def _emotion_engine_doctor_issues(
    target_dir,
    manifest,
    plan,
    *,
    runtime_probes_trusted=True,
):
    issues = []
    probe_trust_intact = bool(runtime_probes_trusted)
    adapter = plan["adapter"]
    # Sidecar-private state is owned and verified by the sidecar, not by the
    # host manifest. Only host-managed projection artifacts belong here.
    expected_artifacts = set(emotion_engine_managed_artifacts(adapter))
    recorded_identity = manifest.get("sidecars", {}).get(EMOTION_ENGINE_SIDECAR, {}).get("identity")
    if recorded_identity != plan.get("identity"):
        issues.append(_doctor_issue(
            "emotion_engine_manifest_identity_mismatch",
            "manifest.json",
            "manifest Emotion Engine identity does not match the installed Packwright character",
        ))

    try:
        incomplete_migration = _incomplete_emotion_engine_migration(target_dir)
    except PackwrightValidationError as exc:
        issues.append(_doctor_issue(
            "emotion_engine_migration_journal_invalid",
            EMOTION_ENGINE_MIGRATION_JOURNAL_PATH,
            "; ".join(exc.issues),
        ))
        incomplete_migration = None
        probe_trust_intact = False
    if incomplete_migration is not None:
        issues.append(_doctor_issue(
            "emotion_engine_migration_incomplete",
            EMOTION_ENGINE_MIGRATION_JOURNAL_PATH,
            "an incomplete migration transaction is a global writer fuse until explicit recovery",
        ))
        probe_trust_intact = False

    for rel_path, expected_bytes in plan["projection"].items():
        target_path = target_dir / rel_path
        if not target_path.is_file():
            issues.append(_doctor_issue("emotion_engine_missing_file", rel_path, "projected sidecar file is missing"))
            probe_trust_intact = False
            continue
        if _read_bytes(target_path) != expected_bytes:
            issues.append(_doctor_issue("emotion_engine_file_drift", rel_path, "projected sidecar file differs from source"))
            probe_trust_intact = False

    pending = target_dir / EMOTION_ENGINE_PROJECTION_PENDING_PATH
    if pending.exists():
        issues.append(_doctor_issue(
            "emotion_engine_projection_incomplete",
            EMOTION_ENGINE_PROJECTION_PENDING_PATH,
            "an interrupted Emotion Engine projection is not safe to activate; refresh the complete writer cohort",
        ))
        probe_trust_intact = False

    state_issue = _emotion_engine_state_issue(
        plan["state_file"],
        expected_identity=plan.get("identity"),
    )
    if state_issue:
        issues.append(state_issue)

    projection_issue = _emotion_engine_projection_issue(target_dir, plan)
    if projection_issue:
        issues.append(projection_issue)
        probe_trust_intact = False

    mcp_activation_issue = _emotion_engine_mcp_activation_issue(target_dir, plan)
    if mcp_activation_issue:
        issues.append(mcp_activation_issue)
    activation_manifest_issue = (
        _emotion_engine_activation_manifest_issue(
            target_dir,
            manifest,
            plan,
            mcp_activation_issue=mcp_activation_issue,
        )
        if probe_trust_intact
        else None
    )
    if activation_manifest_issue:
        issues.append(activation_manifest_issue)

    config_issue = _emotion_engine_mcp_config_issue(target_dir, plan["mcp_config"], adapter)
    if config_issue:
        issues.append(config_issue)
    if adapter == "codex":
        lifecycle_issue = codex_lifecycle_config_issue(target_dir)
        if lifecycle_issue:
            issues.append(_doctor_issue(
                "emotion_engine_lifecycle_config_drift",
                ".codex/hooks.json",
                lifecycle_issue,
            ))
        lifecycle_receipt_issue = _emotion_engine_lifecycle_receipt_issue(target_dir, manifest)
        if lifecycle_receipt_issue:
            issues.append(lifecycle_receipt_issue)

    if state_issue is None and probe_trust_intact:
        mode_issue = _emotion_engine_mode_issue(plan["state_file"], plan["mode"])
        if mode_issue:
            issues.append(mode_issue)
        activation = _emotion_engine_activation_probe(target_dir, plan)
        if activation.get("status") != "ready":
            issues.append(_doctor_issue(
                "emotion_engine_activation_failed",
                EMOTION_ENGINE_STATE_PATH,
                activation.get("message") or "Emotion Engine activation_check did not report ready",
            ))
        audit = _run_installed_emotion_helper(target_dir, "audit_state")
        if audit.get("returncode") != 0 or audit.get("ok") is not True:
            issues.append(_doctor_issue(
                "emotion_engine_state_audit_failed",
                EMOTION_ENGINE_STATE_PATH,
                "Emotion Engine audit_state did not pass",
            ))
    elif state_issue is None:
        issues.append(_doctor_issue(
            "runtime_probe_skipped_untrusted_artifact",
            f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_utils.py",
            "activation and audit probes were skipped because managed runtime trust checks failed",
        ))

    mode = plan["mode"]
    issues.extend(
        emotion_engine_manifest_diagnostics(
            manifest,
            expected_mode=mode,
            required_artifacts=expected_artifacts,
        )
    )
    return issues


def _emotion_engine_lifecycle_receipt_issue(target_dir, manifest):
    receipt_path = target_dir / EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH
    if not receipt_path.exists():
        return None
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _doctor_issue(
            "emotion_engine_lifecycle_receipt_invalid",
            EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH,
            "native lifecycle receipt is not valid JSON",
        )
    feature = manifest.get("features", {}).get("emotion_engine", {})
    helper = target_dir / EMOTION_ENGINE_RUNTIME_ROOT / "scripts" / "emotion_engine_utils.py"
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != "packwright-emotion-lifecycle/v1"
        or receipt.get("adapter") != "codex"
        or receipt.get("native_event") != "SessionStart"
        or not isinstance(receipt.get("native_session_id"), str)
        or not receipt.get("native_session_id")
        or receipt.get("source_digest") != feature.get("source_digest")
        or receipt.get("projection_nonce") != feature.get("projection_nonce")
        or not helper.is_file()
        or receipt.get("helper_sha256") != _file_sha256(helper)
    ):
        return _doctor_issue(
            "emotion_engine_lifecycle_receipt_stale",
            EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH,
            "native lifecycle receipt does not match the current adapter, helper, or source cohort",
        )
    operations = receipt.get("operations")
    if (
        not isinstance(operations, list)
        or not operations
        or operations[-1].get("command") != "session_start"
        or operations[-1].get("status") not in {
            "started", "already_active", "duplicate_event"
        }
    ):
        return _doctor_issue(
            "emotion_engine_lifecycle_receipt_invalid",
            EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH,
            "native lifecycle receipt has no successful idempotent session_start result",
        )
    return None


def _emotion_engine_projection_issue(target_dir, plan):
    receipt_path = target_dir / EMOTION_ENGINE_PROJECTION_RECEIPT_PATH
    if not receipt_path.is_file():
        return _doctor_issue(
            "emotion_engine_projection_receipt_missing",
            EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
            "writer cohort has no completed projection receipt",
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _doctor_issue(
            "emotion_engine_projection_receipt_invalid",
            EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
            "writer cohort projection receipt is invalid",
        )
    if (
        not isinstance(receipt, dict)
        or receipt.get("engine_version") != EMOTION_ENGINE_VERSION
        or receipt.get("writer_generation") != EMOTION_ENGINE_GENERATION
        or receipt.get("state_schema") != EMOTION_ENGINE_STATE_SCHEMA
        or receipt.get("projection_nonce") != plan.get("projection_nonce")
        or receipt.get("source_digest") != plan.get("source_digest")
        or receipt.get("required_capabilities") != list(EMOTION_ENGINE_REQUIRED_CAPABILITIES)
        or receipt.get("legacy_writer_fence_supported") is not True
        or receipt.get("legacy_writer_fence") != EMOTION_ENGINE_LEGACY_WRITER_FENCE_PATH
    ):
        return _doctor_issue(
            "emotion_engine_projection_cohort_mismatch",
            EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
            "writer cohort projection receipt reports a mixed version, schema, capability, or source digest",
        )
    files = receipt.get("files")
    if not isinstance(files, dict):
        return _doctor_issue(
            "emotion_engine_projection_receipt_invalid",
            EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
            "writer cohort projection receipt does not list file hashes",
        )
    for rel_path, expected_hash in files.items():
        path = target_dir / rel_path
        if not path.is_file() or _file_sha256(path) != expected_hash:
            return _doctor_issue(
                "emotion_engine_projection_cohort_drift",
                rel_path,
                "installed writer cohort no longer matches its completed projection receipt",
            )
    return None


def _emotion_engine_mcp_activation_issue(target_dir, plan):
    path = target_dir / EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH
    if not path.is_file():
        return _doctor_issue(
            "emotion_engine_mcp_restart_required",
            EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH,
            "restart the MCP client so the pinned writer cohort can complete a live initialize handshake",
        )
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        receipt = None
    helper = target_dir / EMOTION_ENGINE_RUNTIME_ROOT / "scripts" / "emotion_engine_utils.py"
    mcp = target_dir / EMOTION_ENGINE_RUNTIME_ROOT / "scripts" / "emotion_engine_mcp.py"
    launcher = target_dir / EMOTION_ENGINE_MCP_LAUNCHER_PATH
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != "packwright-emotion-mcp-activation/v1"
        or receipt.get("engine_version") != EMOTION_ENGINE_VERSION
        or receipt.get("projection_nonce") != plan.get("projection_nonce")
        or receipt.get("source_digest") != plan.get("source_digest")
        or receipt.get("runtime_root") != EMOTION_ENGINE_RUNTIME_ROOT
        or receipt.get("state_path") != EMOTION_ENGINE_STATE_PATH
        or receipt.get("legacy_writer_fence_supported") is not True
        or receipt.get("activation_check_status") != "ready"
        or receipt.get("audit_ok") is not True
        or not isinstance(receipt.get("state_sha256"), str)
        or not helper.is_file()
        or receipt.get("helper_sha256") != _file_sha256(helper)
        or not mcp.is_file()
        or receipt.get("mcp_sha256") != _file_sha256(mcp)
        or not launcher.is_file()
        or receipt.get("launcher_sha256") != _file_sha256(launcher)
    ):
        return _doctor_issue(
            "emotion_engine_mcp_cohort_stale",
            EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH,
            "the MCP initialize receipt does not match the current projection nonce, hashes, paths, or writer cohort; restart the client",
        )
    return None


def _emotion_engine_activation_manifest_issue(
    target_dir,
    manifest,
    plan,
    mcp_activation_issue=None,
):
    feature = manifest.get("features", {}).get("emotion_engine", {})
    sidecar = manifest.get("sidecars", {}).get(EMOTION_ENGINE_SIDECAR, {})
    if not isinstance(feature, dict) or not isinstance(sidecar, dict):
        return None
    actual = _emotion_engine_activation_status(target_dir, plan)
    expected_mcp_status = (
        "configured_client_restart_required"
        if mcp_activation_issue is not None
        else "active"
    )
    if (
        feature.get("activation") != actual
        or sidecar.get("activation") != actual
        or feature.get("mcp_status") != expected_mcp_status
        or sidecar.get("mcp_status") != expected_mcp_status
    ):
        return _doctor_issue(
            "emotion_engine_activation_manifest_stale",
            "manifest.json",
            "manifest activation or MCP status does not match the current live cohort receipt",
        )
    return None


def _emotion_engine_mode_issue(state_file, expected_mode):
    try:
        state = json.loads(Path(state_file).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict) or state.get("_schema") != EMOTION_ENGINE_STATE_SCHEMA:
        return None
    expected_enabled = expected_mode != "paused"
    if (
        state.get("runtime_mode") != expected_mode
        or state.get("enabled") is not expected_enabled
    ):
        return _doctor_issue(
            "emotion_engine_mode_mismatch",
            EMOTION_ENGINE_STATE_PATH,
            f"runtime state mode/enabled flags do not match manifest mode {expected_mode!r}",
        )
    return None


def _doctor_issue(issue_id, path, message):
    return {"id": issue_id, "path": path, "message": message}


def _read_bytes(path):
    try:
        return path.read_bytes()
    except OSError:
        return None


_SUBPROCESS_ENV_ALLOWLIST = (
    "LANG",
    "LC_ALL",
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
)


def _bounded_subprocess_environment():
    environment = {
        key: os.environ[key]
        for key in _SUBPROCESS_ENV_ALLOWLIST
        if key in os.environ
    }
    environment.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    })
    return environment


def _safe_git_argv(*arguments):
    """Build a read-only Git command that ignores checkout-local execution hooks."""
    return [
        "git",
        "--no-optional-locks",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "core.pager=cat",
        "-c",
        "color.ui=false",
        *arguments,
    ]


def _run_bounded_subprocess(argv, *, cwd, input_bytes=None, timeout=30, output_limit=1_000_000):
    """Run a fixed argv without a shell while bounding time and captured output."""
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            completed = subprocess.run(
                list(argv),
                cwd=str(cwd),
                check=False,
                env=_bounded_subprocess_environment(),
                input=input_bytes,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "returncode": 124,
                "stdout": b"",
                "stderr": b"subprocess timed out",
                "timed_out": True,
                "output_exceeded": False,
            }
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read(output_limit + 1)
        stderr = stderr_file.read(output_limit + 1)
    exceeded = len(stdout) > output_limit or len(stderr) > output_limit
    return {
        "returncode": completed.returncode,
        "stdout": stdout[:output_limit],
        "stderr": stderr[:output_limit],
        "timed_out": False,
        "output_exceeded": exceeded,
    }


def _run_installed_emotion_helper(target_dir, command, *args, state_file=None):
    helper = target_dir / EMOTION_ENGINE_RUNTIME_ROOT / "scripts" / "emotion_engine_utils.py"
    state_file = Path(state_file) if state_file is not None else _emotion_engine_state_path(target_dir)
    if not helper.is_file():
        return {
            "returncode": 127,
            "status": "helper_missing",
            "message": f"Emotion Engine helper is missing: {helper}",
        }
    installer_owned_commands = {
        "init",
        "bind_identity",
        "migrate_state",
        "upgrade_state",
        "reset",
    }
    runtime_prefix = [] if command in installer_owned_commands else ["--managed-runtime"]
    completed = _run_bounded_subprocess(
        [
            sys.executable,
            str(helper),
            *runtime_prefix,
            command,
            str(state_file),
            *map(str, args),
        ],
        cwd=str(target_dir),
        timeout=30,
        output_limit=1_000_000,
    )
    if completed["timed_out"]:
        return {
            "returncode": completed["returncode"],
            "status": "helper_timeout",
            "message": "Emotion Engine helper exceeded its execution timeout",
        }
    if completed["output_exceeded"]:
        return {
            "returncode": completed["returncode"],
            "status": "helper_output_limit_exceeded",
            "message": "Emotion Engine helper exceeded its output limit",
        }
    try:
        payload = json.loads(completed["stdout"].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        payload = {
            "status": "invalid_helper_output",
            "message": "Emotion Engine helper did not return JSON",
        }
    if not isinstance(payload, dict):
        payload = {
            "status": "invalid_helper_output",
            "message": "Emotion Engine helper returned a non-object JSON value",
        }
    payload = dict(payload)
    payload["returncode"] = completed["returncode"]
    if completed["stderr"]:
        payload["stderr"] = completed["stderr"].decode("utf-8", errors="replace").strip()
    return payload


def _emotion_engine_activation_probe(target_dir, plan=None):
    result = _run_installed_emotion_helper(target_dir, "activation_check")
    if plan is not None:
        result["expected_identity"] = dict(plan.get("identity") or {})
    return result


def _emotion_engine_activation_status(target_dir, plan):
    state = None
    try:
        state = json.loads(_emotion_engine_state_path(target_dir).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    schema = state.get("_schema") if isinstance(state, dict) else None
    if schema == EMOTION_ENGINE_LEGACY_STATE_SCHEMA:
        return {
            "installed": True,
            "configured": True,
            "active": False,
            "verified": False,
            "status": "migration_required",
        }
    state_issue = _emotion_engine_state_issue(
        _emotion_engine_state_path(target_dir),
        expected_identity=plan.get("identity"),
    )
    if state_issue is not None:
        return {
            "installed": True,
            "configured": True,
            "active": False,
            "verified": False,
            "status": (
                "capability_upgrade_required"
                if state_issue.get("id") == "emotion_engine_state_capability_mismatch"
                else "verification_failed"
            ),
        }
    activation = _emotion_engine_activation_probe(target_dir, plan)
    audit = _run_installed_emotion_helper(target_dir, "audit_state")
    ready = activation.get("returncode") == 0 and activation.get("status") == "ready"
    audit_ok = audit.get("returncode") == 0 and audit.get("ok") is True
    enabled = isinstance(state, dict) and state.get("enabled") is True
    expected_mode = plan.get("mode")
    mode_ok = (
        isinstance(state, dict)
        and state.get("runtime_mode") == expected_mode
        and enabled is (expected_mode != "paused")
    )
    live_issue = _emotion_engine_mcp_activation_issue(target_dir, plan)
    live_ok = live_issue is None
    if not live_ok:
        status = "client_restart_required"
    elif not mode_ok:
        status = "mode_mismatch"
    elif ready and not enabled:
        status = "paused"
    elif ready and audit_ok:
        status = "ready"
    else:
        status = "verification_failed"
    return {
        "installed": True,
        "configured": True,
        "active": bool(ready and enabled and mode_ok and live_ok),
        "verified": bool(ready and audit_ok and mode_ok and live_ok),
        "status": status,
    }


def _emotion_engine_state_issue(state_file, expected_identity=None):
    return _emotion_engine_state_issue_for_path(
        state_file,
        display_path=EMOTION_ENGINE_STATE_PATH,
        expected_identity=expected_identity,
    )


def _emotion_engine_state_issue_for_path(state_file, display_path=None, expected_identity=None):
    display_path = display_path or str(state_file)
    if not state_file.is_file():
        return _doctor_issue("emotion_engine_missing_file", display_path, "runtime state file is missing")
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _doctor_issue("emotion_engine_state_invalid", display_path, "runtime state file is not valid JSON")
    if not isinstance(state, dict):
        return _doctor_issue("emotion_engine_state_invalid", display_path, "runtime state file has an unexpected schema")
    schema = state.get("_schema")
    if schema == EMOTION_ENGINE_LEGACY_STATE_SCHEMA:
        return _doctor_issue(
            "emotion_engine_state_migration_required",
            display_path,
            "runtime v2 state is preserved read-only; run the explicit Emotion Engine state migration before activation",
        )
    if schema != EMOTION_ENGINE_STATE_SCHEMA:
        return _doctor_issue("emotion_engine_state_invalid", display_path, "runtime state file has an unexpected schema")
    identity = state.get("identity")
    if not isinstance(identity, dict) or identity.get("status") != "bound":
        return _doctor_issue(
            "emotion_engine_state_identity_unbound",
            display_path,
            "runtime v3 state is not bound to an explicit character and relationship identity",
        )
    if expected_identity and any(
        identity.get(key) != value for key, value in expected_identity.items()
    ):
        return _doctor_issue(
            "emotion_engine_state_identity_mismatch",
            display_path,
            "runtime v3 state identity does not match the installed Packwright character",
        )
    capabilities = state.get("capabilities")
    missing = [
        capability
        for capability in EMOTION_ENGINE_REQUIRED_CAPABILITIES
        if not isinstance(capabilities, list) or capability not in capabilities
    ]
    if missing:
        return _doctor_issue(
            "emotion_engine_state_capability_mismatch",
            display_path,
            "runtime v3 state is missing required capabilities: " + ", ".join(missing),
        )
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
    state_file = _emotion_engine_state_path(target_dir)
    planned_state = Path(plan["state_file"])
    if planned_state.resolve(strict=False) != state_file.resolve(strict=False):
        raise PackwrightValidationError([
            "Emotion Engine state destination changed after planning; re-plan the install"
        ])
    state_source = plan.get("state_source")
    if state_source is not None:
        state_source = Path(state_source)
        try:
            source_relative = state_source.relative_to(Path(target_dir).resolve()).as_posix()
        except ValueError:
            pass
        else:
            state_source = resolve_source_path(
                target_dir,
                source_relative,
                "Emotion Engine state source",
            )
    projection_nonce = uuid.uuid4().hex
    pending_path = resolve_destination_path(
        target_dir,
        EMOTION_ENGINE_PROJECTION_PENDING_PATH,
        "Emotion Engine projection marker",
    )
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    default_lock_owned = {
        *plan["projection"],
        plan["mcp_config"]["path"],
        EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
        "manifest.json",
    }
    if plan["adapter"] != "cursor":
        default_lock_owned.add(adapter_entry(plan["adapter"]))
    if plan.get("lifecycle_config"):
        default_lock_owned.add(plan["lifecycle_config"]["path"])
    _write_json_atomic(pending_path, {
        "schema": "packwright-sidecar-projection-transaction/v1",
        "engine_version": EMOTION_ENGINE_VERSION,
        "writer_generation": EMOTION_ENGINE_GENERATION,
        "projection_nonce": projection_nonce,
        "source_digest": plan["source_digest"],
        "status": "projecting",
        "lock_owned_paths": sorted(plan.get("lock_owned_paths") or default_lock_owned),
        "lock_removed_paths": sorted(plan.get("lock_removed_paths") or plan.get("stale_projection_receipts", [])),
        "manifest_before_sha256": _file_sha256(target_dir / "manifest.json"),
    })
    for stale_receipt in plan.get("stale_projection_receipts", []):
        try:
            resolve_destination_path(
                target_dir,
                stale_receipt,
                "stale Emotion Engine projection receipt",
            ).unlink()
        except FileNotFoundError:
            pass
    for stale_receipt in (
        EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH,
        EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH,
    ):
        try:
            _emotion_engine_managed_path(
                target_dir,
                stale_receipt,
                "stale Emotion Engine activation receipt",
            ).unlink()
        except FileNotFoundError:
            pass
    for rel_path, content in plan["projection"].items():
        destination = resolve_destination_path(target_dir, rel_path, "Emotion Engine projection destination")
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_bytes_atomic(destination, content)
        if rel_path in {
            EMOTION_ENGINE_WRAPPER_PATH,
            EMOTION_ENGINE_WRITER_GATEWAY_PATH,
            EMOTION_ENGINE_MCP_WRAPPER_PATH,
            EMOTION_ENGINE_LIFECYCLE_PATH,
            EMOTION_ENGINE_MCP_LAUNCHER_PATH,
            f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/emotion_engine_mcp.py",
            f"{EMOTION_ENGINE_RUNTIME_ROOT}/scripts/register_mcp_client.py",
        }:
            _make_executable(destination)

    state_result = _ensure_emotion_state(
        state_file,
        plan["emotion_style"],
        plan["mode"],
        plan["relationship_continuity"],
        plan["identity"],
        target_dir,
        source=state_source,
    )
    mode_sync = _sync_emotion_engine_mode(target_dir, state_file, plan["mode"])
    config = plan["mcp_config"]
    config_destination = resolve_destination_path(
        target_dir,
        config["path"],
        "Emotion Engine MCP config destination",
    )
    config_destination.parent.mkdir(parents=True, exist_ok=True)
    if plan.get("mcp_unmanaged_sha256") is not None:
        current_mcp_text = config_destination.read_text(encoding="utf-8")
        if (
            _emotion_mcp_unmanaged_digest(current_mcp_text, plan["adapter"])
            != plan["mcp_unmanaged_sha256"]
        ):
            raise PackwrightValidationError([
                f"unmanaged MCP configuration changed after planning: {config['path']}"
            ])
        if _file_sha256(config_destination) != config.get("original_sha256"):
            raise PackwrightValidationError([
                f"MCP configuration changed after planning: {config['path']}"
            ])
    _write_text_atomic(config_destination, config["rendered"])
    lifecycle_config = (
        prepare_codex_lifecycle_config(target_dir)
        if plan["adapter"] == "codex"
        else plan.get("lifecycle_config")
    )
    if lifecycle_config:
        lifecycle_destination = resolve_destination_path(
            target_dir,
            lifecycle_config["path"],
            "Emotion Engine lifecycle config destination",
        )
        lifecycle_destination.parent.mkdir(parents=True, exist_ok=True)
        _write_text_atomic(lifecycle_destination, lifecycle_config["rendered"])
    entry_updated = _ensure_emotion_section(
        target_dir,
        plan["adapter"],
        plan["mode"],
        expected_unmanaged_sha256=plan.get("entry_unmanaged_sha256"),
    )
    if plan["adapter"] != "cursor":
        plan["entry_after_sha256"] = _file_sha256(
            resolve_source_path(
                target_dir,
                adapter_entry(plan["adapter"]),
                "shared adapter entry after projection",
            )
        )

    receipt = {
        "engine_version": EMOTION_ENGINE_VERSION,
        "writer_generation": EMOTION_ENGINE_GENERATION,
        "projection_nonce": projection_nonce,
        "state_schema": EMOTION_ENGINE_STATE_SCHEMA,
        "required_capabilities": list(EMOTION_ENGINE_REQUIRED_CAPABILITIES),
        "legacy_writer_fence_supported": True,
        "legacy_writer_fence": EMOTION_ENGINE_LEGACY_WRITER_FENCE_PATH,
        "source_digest": plan["source_digest"],
        "files": {
            rel_path: _file_sha256(resolve_source_path(
                target_dir,
                rel_path,
                "installed Emotion Engine projection",
            ))
            for rel_path in sorted(plan["projection"])
        },
    }
    _write_json_atomic(_emotion_engine_managed_path(
        target_dir,
        EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
        "Emotion Engine projection receipt",
    ), receipt)
    plan["projection_nonce"] = projection_nonce
    activation = _emotion_engine_activation_status(target_dir, plan)
    return {
        "version": EMOTION_ENGINE_VERSION,
        "upstream_commit": EMOTION_ENGINE_UPSTREAM_COMMIT,
        "source_digest": plan["source_digest"],
        "projection_nonce": projection_nonce,
        "skill_path": emotion_engine_skill_path(plan["adapter"]),
        "state_file": str(state_file),
        "wrapper": str(target_dir / EMOTION_ENGINE_WRAPPER_PATH),
        "mcp_config": config["path"],
        "mcp_status": "configured_client_restart_required",
        "mode": plan["mode"],
        "identity": dict(plan["identity"]),
        "activation": activation,
        **state_result,
        "mode_sync": mode_sync,
        "entry_updated": entry_updated,
        "entry_after_sha256": plan.get("entry_after_sha256"),
    }


def _mark_emotion_engine_installed(target_dir, sidecar, adapter, mode):
    manifest_path = resolve_destination_path(
        target_dir,
        "manifest.json",
        "Emotion Engine manifest destination",
    )
    if not manifest_path.exists():
        return False
    expected_entry_digest = sidecar.get("entry_after_sha256")
    if adapter != "cursor" and expected_entry_digest:
        entry_path = resolve_source_path(
            target_dir,
            adapter_entry(adapter),
            "shared adapter entry before manifest commit",
        )
        if _file_sha256(entry_path) != expected_entry_digest:
            raise PackwrightValidationError([
                f"shared adapter entry changed before sidecar commit: {adapter_entry(adapter)}"
            ])
    manifest = _load_manifest(target_dir)
    previous_sidecar = manifest.get("sidecars", {}).get(EMOTION_ENGINE_SIDECAR, {})
    previous_runtime_root = (
        previous_sidecar.get("runtime_root")
        if isinstance(previous_sidecar, dict)
        else None
    )
    previous_state_file = (
        previous_sidecar.get("state_file")
        if isinstance(previous_sidecar, dict)
        else None
    )
    previous_projection_receipt = (
        previous_sidecar.get("projection_receipt")
        if isinstance(previous_sidecar, dict)
        else None
    )
    manifest.setdefault("features", {})["emotion_engine"] = emotion_engine_feature(
        mode=mode,
        adapter=adapter,
        installed=True,
        source_digest=sidecar["source_digest"],
        mcp_status=sidecar["mcp_status"],
        activation=sidecar["activation"],
        projection_nonce=sidecar["projection_nonce"],
    )
    manifest.setdefault("sidecars", {})[EMOTION_ENGINE_SIDECAR] = emotion_engine_sidecar_record(
        adapter,
        mode,
        sidecar["source_digest"],
        sidecar["mcp_status"],
        activation=sidecar["activation"],
        projection_nonce=sidecar["projection_nonce"],
    )
    manifest["sidecars"][EMOTION_ENGINE_SIDECAR]["identity"] = dict(sidecar["identity"])
    boundaries = manifest.setdefault("boundaries", {})
    boundaries["emotion_engine_runtime"] = EMOTION_ENGINE_RUNTIME
    boundaries["emotion_engine_mode"] = mode
    manifest.setdefault("packwright", {})["lock"] = LOCK_PATH
    artifacts = set(manifest.get("artifacts", []))
    artifacts.add(LOCK_PATH)
    if isinstance(previous_runtime_root, str) and previous_runtime_root != EMOTION_ENGINE_RUNTIME_ROOT:
        artifacts = {
            artifact for artifact in artifacts
            if not (
                artifact == previous_runtime_root
                or artifact.startswith(previous_runtime_root.rstrip("/") + "/")
            )
        }
    if isinstance(previous_state_file, str) and previous_state_file != EMOTION_ENGINE_STATE_PATH:
        artifacts.discard(previous_state_file)
    if (
        isinstance(previous_projection_receipt, str)
        and previous_projection_receipt != EMOTION_ENGINE_PROJECTION_RECEIPT_PATH
    ):
        artifacts.discard(previous_projection_receipt)
    artifacts = {artifact for artifact in artifacts if not _is_sidecar_private_path(artifact)}
    artifacts.update(
        artifact
        for artifact in _existing_sidecar_artifacts(target_dir, adapter)
        if not _is_sidecar_private_path(artifact)
    )
    artifacts.add(emotion_engine_mcp_config_path(adapter))
    if adapter == "codex" and resolve_destination_path(
        target_dir,
        ".codex/hooks.json",
        "Codex hooks destination",
    ).is_file():
        artifacts.add(".codex/hooks.json")
    manifest["artifacts"] = sorted(artifacts)
    _write_json_atomic(manifest_path, manifest)
    pending_path = _emotion_engine_managed_path(
        target_dir,
        EMOTION_ENGINE_PROJECTION_PENDING_PATH,
        "Emotion Engine pending marker",
    )
    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackwrightValidationError([
            f"Emotion Engine projection transaction marker is unreadable during commit: {exc}"
        ]) from exc
    if not isinstance(pending, dict) or pending.get("status") != "projecting":
        raise PackwrightValidationError([
            "Emotion Engine projection transaction marker changed before host commit"
        ])
    if pending.get("projection_nonce") != sidecar.get("projection_nonce"):
        raise PackwrightValidationError([
            "Emotion Engine projection transaction nonce changed before host commit"
        ])
    owned_paths = [
        str(path)
        for path in pending.get("lock_owned_paths", [])
        if isinstance(path, str)
    ]
    after_digests = {}
    removed_paths = set(pending.get("lock_removed_paths", []))
    for rel_path in owned_paths:
        if rel_path == LOCK_PATH or _is_sidecar_private_path(rel_path):
            continue
        path = resolve_destination_path(target_dir, rel_path, "projection commit artifact")
        if path.is_file():
            after_digests[rel_path] = _file_sha256(path)
        else:
            removed_paths.add(rel_path)
    pending.update({
        "status": "host_commit_pending",
        "manifest_after_sha256": _file_sha256(manifest_path),
        "after_digests": after_digests,
        "lock_removed_paths": sorted(removed_paths),
    })
    _write_json_atomic(pending_path, pending)
    return True


def _existing_sidecar_artifacts(target_dir, adapter=None):
    if adapter is None:
        adapter = _load_manifest(target_dir).get("adapter")
    existing = []
    for artifact in emotion_engine_artifacts(adapter):
        path = resolve_destination_path(
            target_dir,
            artifact,
            "Emotion Engine installed artifact",
        )
        if path.is_file():
            existing.append(artifact)
    return existing


def _make_executable(path):
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _read_emotion_state_packet(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _emotion_migration_lineage_proves_source(root_dir, canonical, legacy):
    # The canonical packet and this record are both writable by the target.
    # They cannot authenticate each other, so retirement must stay fail-closed
    # until the sidecar Admin owns and verifies lineage in its private namespace.
    return False


def _assert_emotion_state_candidates_compatible(root_dir, selected, candidates):
    selected_hash = _file_sha256(selected)
    conflicts = []
    for candidate in candidates:
        if candidate == selected or _file_sha256(candidate) == selected_hash:
            continue
        if _emotion_migration_lineage_proves_source(root_dir, selected, candidate):
            continue
        conflicts.append(candidate)
    if conflicts:
        listed = ", ".join(str(path) for path in [selected, *conflicts])
        raise PackwrightValidationError([
            "Emotion Engine canonical and legacy state candidates differ without persistent migration lineage; choose or reconcile the latest writer before migration",
            f"state candidates: {listed}",
        ])


def _select_emotion_state_source(root_dir, explicit=None, declared=None):
    root_dir = Path(root_dir)
    if explicit is not None:
        explicit_path = Path(explicit).expanduser().resolve()
        if not explicit_path.is_file():
            raise PackwrightValidationError([f"Emotion Engine state source does not exist: {explicit_path}"])
        return explicit_path

    candidates = []
    canonical = _emotion_engine_state_path(root_dir).resolve()
    if canonical.is_file():
        candidates.append(canonical)
    declared_path = None
    if isinstance(declared, str) and declared.strip():
        declared_path = resolve_destination_path(
            root_dir,
            declared.strip(),
            "manifest Emotion Engine state source",
        )
        if declared_path.is_file():
            candidates.append(declared_path.resolve())

    for rel_path in EMOTION_ENGINE_LEGACY_STATE_PATHS:
        candidate = _emotion_engine_managed_path(
            root_dir,
            rel_path,
            "legacy Emotion Engine state source",
        )
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
    selected = (
        canonical
        if canonical in unique
        else declared_path.resolve()
        if declared_path is not None and declared_path.resolve() in unique
        else unique[0]
    )
    selected_state = _read_emotion_state_packet(selected)
    if (
        selected == canonical
        and isinstance(selected_state, dict)
        and selected_state.get("_schema") == EMOTION_ENGINE_STATE_SCHEMA
    ):
        # A current canonical generation is the only runtime source. Retained
        # legacy files are inert compatibility data and cannot block normal
        # writers; their divergent retirement remains forbidden above.
        return selected
    _assert_emotion_state_candidates_compatible(root_dir, selected, unique)
    return selected


def _ensure_emotion_state(
    state_file,
    emotion_style,
    mode,
    relationship_continuity="warm_selective",
    identity=None,
    target_dir=None,
    source=None,
):
    if source is not None:
        source = Path(source)
        before_hash = _file_sha256(source)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != state_file.resolve():
            content = source.read_bytes()
            if hashlib.sha256(content).hexdigest() != before_hash:
                raise PackwrightValidationError([
                    f"Emotion Engine state source changed while it was being carried: {source}"
                ])
            _write_bytes_atomic(state_file, content)
        return {
            "state_created": False,
            "state_preserved": True,
            "state_sha256": before_hash,
            "state_carried_from": str(source),
            "state_migrated_from": None,
        }
    if state_file.exists():
        return {
            "state_created": False,
            "state_preserved": True,
            "state_sha256": _file_sha256(state_file),
            "state_carried_from": str(state_file),
            "state_migrated_from": None,
        }
    if not identity or target_dir is None:
        raise PackwrightValidationError([
            "Emotion Engine v3 initialization requires an explicit Packwright identity and installed helper"
        ])
    state_file.parent.mkdir(parents=True, exist_ok=True)
    initialized = _run_installed_emotion_helper(
        target_dir,
        "init",
        "--character-id",
        identity["character_id"],
        "--relationship-id",
        identity["relationship_id"],
    )
    if initialized.get("returncode") != 0 or initialized.get("ok") is not True:
        raise PackwrightValidationError([
            "Emotion Engine helper failed to initialize a bound v3 state: "
            + initialized.get("message", initialized.get("stderr", "unknown error"))
        ])
    if emotion_style:
        configured = _run_installed_emotion_helper(
            target_dir,
            "configure",
            "--style",
            str(emotion_style),
        )
        if configured.get("returncode") != 0 or configured.get("ok") is not True:
            raise PackwrightValidationError(["Emotion Engine helper failed to configure the initialized state"])
    if mode == "paused":
        paused = _run_installed_emotion_helper(target_dir, "pause")
        if paused.get("returncode") != 0 or paused.get("ok") is not True:
            raise PackwrightValidationError(["Emotion Engine helper failed to pause the initialized state"])
    return {
        "state_created": True,
        "state_preserved": False,
        "state_sha256": _file_sha256(state_file),
        "state_carried_from": None,
        "state_migrated_from": None,
    }


def _sync_emotion_engine_mode(target_dir, state_file, mode):
    """Delegate runtime-mode changes to Emotion Engine instead of editing state."""
    try:
        state = json.loads(Path(state_file).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "state_unavailable", "changed": False}
    if not isinstance(state, dict) or state.get("_schema") != EMOTION_ENGINE_STATE_SCHEMA:
        return {"status": "migration_required", "changed": False}
    capabilities = state.get("capabilities")
    if not isinstance(capabilities, list) or any(
        capability not in capabilities
        for capability in EMOTION_ENGINE_REQUIRED_CAPABILITIES
    ):
        return {"status": "capability_upgrade_required", "changed": False}
    expected_enabled = mode != "paused"
    if state.get("runtime_mode") == mode and state.get("enabled") is expected_enabled:
        return {"status": "already_synced", "changed": False, "mode": mode}
    if mode == "paused":
        result = _run_installed_emotion_helper(target_dir, "pause", state_file=state_file)
    else:
        result = _run_installed_emotion_helper(
            target_dir,
            "resume",
            "--mode",
            mode,
            state_file=state_file,
        )
    if result.get("returncode") != 0 or result.get("ok") is not True:
        raise PackwrightValidationError([
            f"Emotion Engine helper failed to synchronize runtime mode {mode}: "
            + result.get("message", result.get("stderr", "unknown error"))
        ])
    return {"status": "synced", "changed": True, "mode": mode}


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


def _ensure_emotion_section(target_dir, adapter, mode, expected_unmanaged_sha256=None):
    if adapter == "cursor":
        return False
    entry_path = target_dir / adapter_entry(adapter)
    if not entry_path.exists():
        return False
    text = entry_path.read_text(encoding="utf-8")
    if (
        expected_unmanaged_sha256 is not None
        and _emotion_entry_unmanaged_digest(text) != expected_unmanaged_sha256
    ):
        raise PackwrightValidationError([
            f"unmanaged shared adapter entry changed after planning: {adapter_entry(adapter)}"
        ])
    updated, changed = _render_emotion_section(text, adapter, mode)
    if changed:
        if entry_path.read_text(encoding="utf-8") != text:
            raise PackwrightValidationError([
                f"shared adapter entry changed while its Emotion Engine block was being updated: {adapter_entry(adapter)}"
            ])
        _write_text_atomic(entry_path, updated)
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
