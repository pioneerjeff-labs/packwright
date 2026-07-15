import copy
import hashlib
import json
import os
import shutil
import stat
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .emotion_engine_contract import (
    EMOTION_ENGINE_CODEX_ARTIFACTS,
    EMOTION_ENGINE_CODEX_SCRIPT_PATH,
    EMOTION_ENGINE_CODEX_SIDECAR,
    EMOTION_ENGINE_CODEX_SKILL_DIR,
    EMOTION_ENGINE_CODEX_LEGACY_SKILL_DIR,
    EMOTION_ENGINE_CODEX_STATE_PATH,
    EMOTION_ENGINE_CODEX_WRAPPER_PATH,
    EMOTION_ENGINE_MODES,
    EMOTION_ENGINE_RUNTIME,
    emotion_engine_codex_expected,
    emotion_engine_codex_manifest_diagnostics,
    emotion_engine_codex_sidecar_record,
    emotion_engine_feature,
)
from .adapter_layout import adapter_entry
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
from .pack_metadata import LOCK_PATH, SPEC_PATH, embed_pack_metadata, load_embedded_spec
from .path_safety import resolve_destination_path, resolve_source_path, validate_relative_path
from .naming import (
    character_slug,
    is_valid_slug,
    normalize_slug,
    reference_prefix,
    save_context_skill_path,
)
from .resolver import resolve_mechanism
from .workspace_contract import workspace_artifacts, workspace_readme, workspace_required_dirs


SUPPORTED_INSTALL_ADAPTERS = {"codex", "claude-code", "cursor"}
PORTABLE_STATE_DIRS = ("memory", "workspace", KNOWLEDGE_ROOT, SOURCES_ROOT)
MIGRATION_SCHEMA = "packwright-migration/v1"
COMPATIBILITY_MEMORY_FILES = (
    "memory/pinned.md",
    "memory/recent-activity.md",
    "memory/knowledge_map.md",
    "memory/relationship-state.md",
)
EMOTION_ENGINE_SECTION = """## Emotion Engine
- Default mode: `{mode}`. The Codex sidecar is installed, but normal work should use it only according to this mode's loading policy.
- Use `.agents/skills/emotion-engine-codex/SKILL.md` for Emotion Engine controls and `.emotion-engine/codex-state.json` for project-local runtime state.
- Use `scripts/codex_emotion.sh` as the project-local wrapper when present; it forwards to `.agents/skills/emotion-engine-codex/scripts/codex_emotion.sh`.
- Use `record_policy` before deciding whether an interaction should be persisted; it is deterministic, side-effect free, and returns compact `reply_bias` rather than rewriting `AGENTS.md`.
- `light` mode target: <1% global token overhead; use the sidecar only when tone continuity, emotional interaction, relationship dynamics, concrete feedback, repair, boundary pressure, or milestone settlement matter.
- `always` mode target: ~3% global token overhead, capped at <=5%; it may track each meaningful turn, but still respects salience, habituation, low-value duplicate compaction, and compact summaries.
- `paused` mode keeps local state available but should not record or modulate turns until resumed.
- Generic praise should usually affect the current reply only; repeated generic praise habituates, while concrete feedback, milestones, repair, and stable preferences may be recorded.
- At meaningful session or milestone close, use the sidecar's `settle_trust` command to conservatively settle agent-to-user trust from recent evidence; praise alone must not directly grow trust.
- Keep it internal: do not expose PAD/trust numbers, state JSON, or step-by-step status unless asked.
- Do not mix Emotion Engine state into memory files; keep durable facts in `memory/*` and dynamic state in `.emotion-engine/codex-state.json`.
"""


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
    emotion_engine_codex_source: object
    emotion_style: object
    emotion_engine_mode: object
    report: dict

    def to_dict(self):
        return copy.deepcopy(self.report)


def install_pack(
    pack_dir,
    target_dir,
    adapter="codex",
    force=False,
    include_emotion_engine_codex=None,
    emotion_engine_codex_source=None,
    emotion_style=None,
    emotion_engine_mode=None,
):
    """Install an adapter pack into a local agent runtime working directory."""
    pack_dir = Path(pack_dir)
    target_dir = Path(target_dir)
    manifest = _load_manifest(pack_dir)
    manifest_adapter = manifest.get("adapter")

    if adapter not in SUPPORTED_INSTALL_ADAPTERS:
        raise PackwrightValidationError([f"unsupported adapter: {adapter}"])
    if manifest_adapter != adapter:
        raise PackwrightValidationError([f"pack adapter is {manifest_adapter!r}, expected {adapter!r}"])
    resolved_emotion_engine_mode = emotion_engine_mode or _manifest_emotion_engine_mode(manifest)
    if resolved_emotion_engine_mode not in EMOTION_ENGINE_MODES:
        raise PackwrightValidationError([f"emotion_engine_mode must be one of {sorted(EMOTION_ENGINE_MODES)}"])
    if include_emotion_engine_codex is None:
        include_emotion_engine_codex = False

    artifacts = _manifest_artifacts(manifest)
    source_paths = [
        (artifact, resolve_source_path(pack_dir, artifact, "adapter pack artifact"))
        for artifact in artifacts
    ]
    destinations = {
        artifact: resolve_destination_path(target_dir, artifact, "installed artifact destination")
        for artifact in artifacts
    }

    existing = [artifact for artifact, path in destinations.items() if path.exists()]
    if existing and not force:
        raise PackwrightValidationError(
            [
                "target already contains files that would be overwritten; rerun with --force after reviewing them",
                *[f"existing target artifact: {artifact}" for artifact in existing],
            ]
        )
    sidecar_plan = None
    if include_emotion_engine_codex:
        if adapter != "codex":
            raise PackwrightValidationError(["--include-emotion-engine-codex is only supported for the codex adapter"])
        sidecar_plan = _prepare_emotion_engine_codex_install(
            target_dir,
            emotion_engine_codex_source,
            force=force,
            emotion_style=emotion_style,
            emotion_engine_mode=resolved_emotion_engine_mode,
            manifest=manifest,
        )

    stale_removed = []
    if force:
        next_artifacts = set(artifacts)
        if sidecar_plan:
            next_artifacts.update(EMOTION_ENGINE_CODEX_ARTIFACTS)
        stale_removed = _remove_stale_manifest_artifacts(target_dir, next_artifacts, preserve_portable=True)

    target_dir.mkdir(parents=True, exist_ok=True)
    installed = []
    preserved_portable = []
    for artifact, source_path in source_paths:
        destination = destinations[artifact]
        if force and _is_portable_path(artifact) and destination.exists():
            preserved_portable.append(artifact)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        if artifact in HANDOFF_EXECUTABLE_ARTIFACTS:
            _make_executable(destination)
        installed.append(artifact)

    sidecars = {}
    if sidecar_plan:
        sidecars[EMOTION_ENGINE_CODEX_SIDECAR] = _install_emotion_engine_codex(target_dir, sidecar_plan)
        _mark_emotion_engine_codex_installed(target_dir, sidecars[EMOTION_ENGINE_CODEX_SIDECAR], resolved_emotion_engine_mode)

    _refresh_artifact_lock(target_dir)

    result = {
        "adapter": adapter,
        "pack_dir": str(pack_dir),
        "target_dir": str(target_dir),
        "installed_artifacts": installed,
    }
    if stale_removed:
        result["stale_removed"] = stale_removed
    if preserved_portable:
        result["preserved_portable_state"] = sorted(preserved_portable)
    if sidecars:
        result["sidecars"] = sidecars
    return result


def refresh_emotion_engine_codex(
    target_dir,
    emotion_engine_codex_source=None,
    emotion_style=None,
    emotion_engine_mode=None,
):
    """Refresh the installed Codex Emotion Engine sidecar projection.

    This is the repair path for targets whose installed sidecar drifted from
    the canonical Emotion Engine source. It rewrites projected sidecar files,
    the project wrapper, AGENTS.md Emotion Engine section, and manifest sidecar
    bookkeeping while preserving the project-local runtime state file.
    """
    target_dir = Path(target_dir)
    manifest = _load_manifest(target_dir)
    manifest_adapter = manifest.get("adapter")
    if manifest_adapter != "codex":
        raise PackwrightValidationError([f"target adapter is {manifest_adapter!r}, expected 'codex'"])

    resolved_emotion_engine_mode = emotion_engine_mode or _manifest_emotion_engine_mode(manifest)
    if resolved_emotion_engine_mode not in EMOTION_ENGINE_MODES:
        raise PackwrightValidationError([f"emotion_engine_mode must be one of {sorted(EMOTION_ENGINE_MODES)}"])

    plan = _prepare_emotion_engine_codex_install(
        target_dir,
        emotion_engine_codex_source,
        force=True,
        emotion_style=emotion_style,
        emotion_engine_mode=resolved_emotion_engine_mode,
        manifest=manifest,
    )
    sidecar = _install_emotion_engine_codex(target_dir, plan)
    _mark_emotion_engine_codex_installed(target_dir, sidecar, resolved_emotion_engine_mode)
    updated_lock_paths = ["manifest.json", *_existing_sidecar_artifacts(target_dir)]
    if sidecar.get("agents_section_added"):
        updated_lock_paths.append("AGENTS.md")
    _update_artifact_lock_paths(target_dir, updated_lock_paths)
    return {
        "adapter": "codex",
        "target_dir": str(target_dir),
        "refreshed_artifacts": _existing_sidecar_artifacts(target_dir),
        "sidecars": {EMOTION_ENGINE_CODEX_SIDECAR: sidecar},
    }


def doctor_target(
    target_dir,
    fix=False,
    emotion_engine_codex_source=None,
    emotion_style=None,
    emotion_engine_mode=None,
):
    """Inspect and optionally repair installed target projection drift."""
    target_dir = Path(target_dir)
    manifest = _load_manifest(target_dir)
    adapter = manifest.get("adapter")
    result = {
        "target_dir": str(target_dir),
        "adapter": adapter,
        "ok": True,
        "issues": [],
        "warnings": _target_layout_doctor_warnings(target_dir),
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

    if adapter != "codex":
        result["ok"] = not result["issues"]
        return result

    if not _emotion_engine_codex_expected_in_target(manifest, target_dir):
        result["ok"] = not result["issues"]
        return result

    mode = emotion_engine_mode or _manifest_emotion_engine_mode(manifest)
    plan = _prepare_emotion_engine_codex_install(
        target_dir,
        emotion_engine_codex_source,
        force=True,
        emotion_style=emotion_style,
        emotion_engine_mode=mode,
        manifest=manifest,
    )
    issues = _emotion_engine_codex_doctor_issues(target_dir, manifest, plan)
    result["issues"].extend(issues)
    result["ok"] = not result["issues"]
    if issues and fix:
        refresh_result = refresh_emotion_engine_codex(
            target_dir,
            emotion_engine_codex_source=emotion_engine_codex_source,
            emotion_style=emotion_style,
            emotion_engine_mode=mode,
        )
        refreshed_manifest = _load_manifest(target_dir)
        refreshed_plan = _prepare_emotion_engine_codex_install(
            target_dir,
            emotion_engine_codex_source,
            force=True,
            emotion_style=emotion_style,
            emotion_engine_mode=mode,
            manifest=refreshed_manifest,
        )
        after_issues = _emotion_engine_codex_doctor_issues(target_dir, refreshed_manifest, refreshed_plan)
        result["fixes"].append({
            "id": "emotion_engine_codex_refreshed",
            "result": refresh_result,
        })
        result["after_issues"] = after_issues
        result["issues"] = (
            _target_layout_doctor_issues(target_dir, refreshed_manifest)
            + _artifact_lock_doctor_issues(target_dir, refreshed_manifest)
            + after_issues
        )
        result["warnings"] = _target_layout_doctor_warnings(target_dir)
        result["ok"] = not result["issues"]
    return result


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
        emotion_style=emotion_style,
        emotion_engine_mode=emotion_engine_mode,
    )
    return apply_migration(plan)


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
    resolved = mechanism if embedded_mechanism and not parameters else resolve_mechanism(mechanism, resolved_parameters)
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
        emotion_engine_codex_source=emotion_engine_codex_source,
        emotion_style=emotion_style,
        emotion_engine_mode=emotion_engine_mode,
    )
    planned_score = _score_migration_pack(resolved, pack, to_adapter)
    conflicts = _migration_plan_conflicts(target_dir, resolved_pack_dir)
    ready = planned_score["passed"] and (force or not conflicts)
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
        "mechanism_changes": mechanism_changes,
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
        emotion_engine_codex_source=emotion_engine_codex_source,
        emotion_style=emotion_style,
        emotion_engine_mode=emotion_engine_mode,
        report=report,
    )


def apply_migration(plan):
    """Apply a previously prepared MigrationPlan and return its receipt."""
    if not isinstance(plan, MigrationPlan):
        raise TypeError("apply_migration expects a MigrationPlan")
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
            include_emotion_engine_codex=_migrate_should_include_emotion_engine_codex(
                plan.to_adapter,
                plan.emotion_engine_codex_source,
            ),
            emotion_engine_codex_source=plan.emotion_engine_codex_source,
            emotion_style=plan.emotion_style,
            emotion_engine_mode=plan.emotion_engine_mode,
        )
        portable_result = _copy_migrated_portable_state(
            plan.source_target_dir,
            plan.target_dir,
            plan.resolved,
            plan.to_adapter,
        )
        state_snapshots = _copy_emotion_state_snapshot(
            plan.source_target_dir,
            plan.target_dir,
            plan.include_emotion_state,
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
            "status": "applied",
            "ready": True,
            "ok": integrity["passed"] and installed_score["passed"],
            "integrity": integrity,
            "source_target_dir": str(plan.source_target_dir),
            "target_dir": str(plan.target_dir),
            "from_adapter": plan.from_adapter,
            "to_adapter": plan.to_adapter,
            "mechanism": str(plan.mechanism_file),
            "pack_dir": str(install_pack_dir) if plan.pack_dir else None,
            "installed_artifacts": install_result["installed_artifacts"],
            "stale_removed": sorted(set(pack_stale_removed + install_result.get("stale_removed", []))),
            "portable_state": portable_result["copied"],
            "memory_projection": portable_result["rewritten"],
            "state_snapshots": state_snapshots,
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


def _plan_migration_changes(
    source_target_dir,
    target_dir,
    source_manifest,
    pack,
    resolved,
    from_adapter,
    to_adapter,
    include_emotion_state,
    emotion_engine_codex_source,
    emotion_style,
    emotion_engine_mode,
):
    carried = []
    rewritten = []
    source_files = _portable_source_files(source_target_dir)
    for rel_path, source_path in source_files.items():
        source_bytes = source_path.read_bytes()
        if rel_path in {"memory/index.md", "memory/pinned.md", "memory/source-map.md"}:
            source_text = source_bytes.decode("utf-8")
            projected = project_memory_file(resolved, to_adapter, rel_path, source_text)
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
                "reason": "copied without content changes",
            }
        )

    state_path = source_target_dir / EMOTION_ENGINE_CODEX_STATE_PATH
    warnings = []
    if include_emotion_state and state_path.is_file():
        carried.append(
            {
                "path": EMOTION_ENGINE_CODEX_STATE_PATH,
                "sha256": _file_sha256(state_path),
                "reason": "copied as project-local runtime state snapshot",
            }
        )
        if to_adapter != "codex":
            warnings.append(
                {
                    "id": "emotion_state_snapshot_inert",
                    "path": EMOTION_ENGINE_CODEX_STATE_PATH,
                    "message": f"snapshot is carried but inactive in the {to_adapter} target",
                }
            )

    carried_paths = {item["path"] for item in carried}
    rewritten_paths = {item["path"] for item in rewritten}
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

    if _migrate_should_include_emotion_engine_codex(to_adapter, emotion_engine_codex_source):
        sidecar_plan = _prepare_emotion_engine_codex_install(
            target_dir,
            emotion_engine_codex_source,
            force=True,
            emotion_style=emotion_style,
            emotion_engine_mode=emotion_engine_mode or _manifest_emotion_engine_mode(target_manifest),
            manifest=target_manifest,
        )
        for rel_path, _, _ in _emotion_engine_codex_projection_files(sidecar_plan):
            generated_by_path[rel_path] = {
                "path": rel_path,
                "reason": "generated Codex sidecar projection",
            }
        generated_by_path[EMOTION_ENGINE_CODEX_WRAPPER_PATH] = {
            "path": EMOTION_ENGINE_CODEX_WRAPPER_PATH,
            "reason": "generated Codex sidecar wrapper",
        }
        if EMOTION_ENGINE_CODEX_STATE_PATH not in carried_paths:
            generated_by_path[EMOTION_ENGINE_CODEX_STATE_PATH] = {
                "path": EMOTION_ENGINE_CODEX_STATE_PATH,
                "reason": "initialized Codex sidecar runtime state",
            }

    excluded = _plan_migration_exclusions(
        source_target_dir,
        source_manifest,
        from_adapter,
        to_adapter,
        carried_paths | rewritten_paths,
        include_emotion_state,
    )
    return (
        {
            "generated": sorted(generated_by_path.values(), key=lambda item: item["path"]),
            "carried": sorted(carried, key=lambda item: item["path"]),
            "rewritten": sorted(rewritten, key=lambda item: item["path"]),
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
        artifact for artifact in EMOTION_ENGINE_CODEX_ARTIFACTS if (source_target_dir / artifact).is_file()
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
        elif rel_path == EMOTION_ENGINE_CODEX_STATE_PATH and not include_emotion_state:
            item = {
                "id": "emotion_state_excluded",
                "path": rel_path,
                "reason": "excluded by --no-emotion-state",
            }
        elif rel_path.startswith(f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/") or rel_path == EMOTION_ENGINE_CODEX_WRAPPER_PATH:
            item = {
                "id": "codex_runtime_sidecar_excluded",
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
        path = source_target_dir / item["path"]
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
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
            issues.append(f"artifact lock digest must be a SHA-256 hex string: {rel_path}")
            continue
        normalized[relative] = digest.lower()
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
        if rel_path == LOCK_PATH:
            continue
        path = resolve_source_path(target_dir, rel_path, "installed artifact")
        artifacts[rel_path] = _file_sha256(path)
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
        if rel_path == LOCK_PATH or _is_portable_path(rel_path) or rel_path == EMOTION_ENGINE_CODEX_STATE_PATH:
            continue
        path = resolve_source_path(target_dir, rel_path, "managed artifact")
        locked[rel_path] = _file_sha256(path)
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
    for rel_path, expected_hash in sorted(locked.items()):
        if rel_path == LOCK_PATH or _is_portable_path(rel_path) or rel_path == EMOTION_ENGINE_CODEX_STATE_PATH:
            continue
        try:
            path = resolve_source_path(target_dir, rel_path, "managed artifact")
        except PackwrightValidationError as exc:
            issues.append(_doctor_issue("managed_artifact_missing_or_unsafe", rel_path, "; ".join(exc.issues)))
            continue
        try:
            actual_hash = _file_sha256(path)
        except OSError as exc:
            issues.append(_doctor_issue("managed_artifact_unreadable", rel_path, f"cannot read managed artifact: {exc}"))
            continue
        if actual_hash != expected_hash:
            issues.append(_doctor_issue("managed_artifact_drift", rel_path, "managed artifact hash differs from .packwright/lock.json"))

    try:
        manifest_artifacts = _manifest_artifacts(manifest)
    except PackwrightValidationError:
        return issues
    for rel_path in manifest_artifacts:
        if (
            rel_path == LOCK_PATH
            or _is_portable_path(rel_path)
            or rel_path == EMOTION_ENGINE_CODEX_STATE_PATH
            or rel_path in EMOTION_ENGINE_CODEX_ARTIFACTS
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
        expected_hash = locked.get(rel_path)
        if content is None or expected_hash != _sha256_bytes(content.encode("utf-8")):
            continue
        destination = resolve_destination_path(target_dir, rel_path, "managed artifact repair destination")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        if rel_path in HANDOFF_EXECUTABLE_ARTIFACTS:
            _make_executable(destination)
        fixed.append(rel_path)
    return sorted(set(fixed))


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
    changes = []
    targets = data.setdefault("targets", {})
    supported = targets.setdefault("supported", [])
    for adapter in sorted(SUPPORTED_INSTALL_ADAPTERS):
        if adapter not in supported:
            supported.append(adapter)
            changes.append({"id": "target_supported_added", "adapter": adapter})

    projection = data.setdefault("emotion", {}).setdefault("projection", {})
    for adapter in sorted(SUPPORTED_INSTALL_ADAPTERS):
        if adapter not in projection:
            projection[adapter] = (
                "optional_sidecar_when_explicitly_enabled" if adapter == "codex" else "spec_guided_behavior_only"
            )
            changes.append({"id": "emotion_projection_added", "adapter": adapter})

    outputs = data.setdefault("outputs", {})
    for adapter in sorted(SUPPORTED_INSTALL_ADAPTERS):
        expected = _adapter_output_artifacts(data, adapter)
        if adapter not in outputs:
            outputs[adapter] = {"kind": "adapter_pack", "artifacts": expected}
            changes.append({"id": "outputs_added", "adapter": adapter})
            continue
        config = outputs[adapter]
        if not isinstance(config, dict):
            outputs[adapter] = {"kind": "adapter_pack", "artifacts": expected}
            changes.append({"id": "outputs_replaced", "adapter": adapter})
            continue
        config.setdefault("kind", "adapter_pack")
        artifacts = config.setdefault("artifacts", [])
        if not isinstance(artifacts, list):
            config["artifacts"] = expected
            changes.append({"id": "outputs_artifacts_replaced", "adapter": adapter})
            continue
        missing = [artifact for artifact in expected if artifact not in artifacts]
        if missing:
            artifacts.extend(missing)
            changes.append({"id": "outputs_artifacts_added", "adapter": adapter, "count": len(missing)})

    coverage = data.setdefault("coverage", {}).setdefault("implemented_by", {})
    adapter_projection = coverage.setdefault("adapter_projection", [])
    output_ref = f"outputs.{to_adapter}"
    if isinstance(adapter_projection, list) and output_ref not in adapter_projection:
        adapter_projection.append(output_ref)
        changes.append({"id": "coverage_adapter_projection_added", "adapter": to_adapter})
    return changes


def _adapter_output_artifacts(mechanism, adapter):
    skill_path = save_context_skill_path(mechanism, adapter)
    prefix = reference_prefix(mechanism, adapter)
    slug = character_slug(mechanism)
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


def _migration_resolved_parameters(source_manifest, parameters):
    resolved = source_manifest.get("resolved_parameters", {})
    result = dict(resolved) if isinstance(resolved, dict) else {}
    result.update(parameters or {})
    return result


def _migrate_should_include_emotion_engine_codex(to_adapter, emotion_engine_codex_source):
    if to_adapter != "codex":
        return False
    return bool(emotion_engine_codex_source or os.environ.get("PACKWRIGHT_EMOTION_ENGINE_CODEX_DIR"))


def _compile_pack_for_adapter(adapter, resolved, references):
    if adapter == "codex":
        from packwright.adapters import compile_to_codex_pack

        return compile_to_codex_pack(resolved, references=references)
    if adapter == "claude-code":
        from packwright.adapters import compile_to_claude_code_pack

        return compile_to_claude_code_pack(resolved, references=references)
    if adapter == "cursor":
        from packwright.adapters import compile_to_cursor_pack

        return compile_to_cursor_pack(resolved, references=references)
    raise PackwrightValidationError([f"unsupported adapter: {adapter}"])


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
    manifest_path = root_dir / "manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        previous_manifest = _load_manifest(root_dir)
        previous_artifacts = _manifest_artifacts(previous_manifest)
    except PackwrightValidationError:
        return []
    removed = []
    for artifact in sorted(set(previous_artifacts) - set(next_artifacts), key=lambda item: len(Path(item).parts), reverse=True):
        if preserve_portable and _is_portable_path(artifact):
            continue
        path = resolve_destination_path(root_dir, artifact, "stale artifact destination")
        if not path.exists():
            continue
        if path.is_dir():
            continue
        path.unlink()
        removed.append(artifact)
        _remove_empty_parents(path.parent, root_dir)
    return removed


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


def _target_layout_doctor_warnings(target_dir):
    warnings = []
    for rel_path in COMPATIBILITY_MEMORY_FILES:
        if (target_dir / rel_path).is_file():
            warnings.append({
                "id": "compatibility_memory_file_present",
                "path": rel_path,
                "message": "compatibility-only memory file is present; keep for legacy reads but do not use as an active memory owner",
            })
    return warnings


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
    pairs.append((EMOTION_ENGINE_CODEX_LEGACY_SKILL_DIR, EMOTION_ENGINE_CODEX_SKILL_DIR))
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
        canonical = legacy.replace(".codex/skills/", ".agents/skills/", 1)
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


def _copy_migrated_portable_state(source_target_dir, target_dir, resolved, to_adapter):
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
    rewritten = _rewrite_migrated_memory_files(target_dir, resolved, to_adapter)
    return {"copied": copied, "rewritten": rewritten}


def _rewrite_migrated_memory_files(target_dir, resolved, to_adapter):
    rewritten = []
    for rel_path in ("memory/index.md", "memory/pinned.md", "memory/source-map.md"):
        path = target_dir / rel_path
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        projected = project_memory_file(resolved, to_adapter, rel_path, original)
        if projected != original:
            path.write_text(projected, encoding="utf-8")
            rewritten.append(rel_path)
    return rewritten


def _copy_emotion_state_snapshot(source_target_dir, target_dir, include_emotion_state):
    if not include_emotion_state:
        return []
    source = source_target_dir / EMOTION_ENGINE_CODEX_STATE_PATH
    if not source.is_file():
        return []
    destination = target_dir / EMOTION_ENGINE_CODEX_STATE_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return [EMOTION_ENGINE_CODEX_STATE_PATH]


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
    if from_adapter == "codex" and to_adapter != "codex":
        for rel_path in (EMOTION_ENGINE_CODEX_SKILL_DIR, EMOTION_ENGINE_CODEX_WRAPPER_PATH):
            if (source_target_dir / rel_path).exists():
                exclusions.append({
                    "id": "codex_runtime_sidecar_excluded",
                    "path": rel_path,
                    "reason": f"{to_adapter} target does not install the Codex sidecar",
                })
        if state_snapshots:
            exclusions.append({
                "id": "emotion_state_snapshot_inert",
                "path": EMOTION_ENGINE_CODEX_STATE_PATH,
                "reason": f"copied as a snapshot; {to_adapter} has no active Codex sidecar",
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


def _prepare_emotion_engine_codex_install(target_dir, source, force, emotion_style, emotion_engine_mode, manifest):
    source_dir = _resolve_emotion_engine_codex_source(source)
    required = [
        source_dir / "SKILL.md",
        source_dir / "README.md",
        source_dir / "install.sh",
        source_dir / "scripts" / "codex_emotion.sh",
        source_dir / "scripts" / "pulse_demo.py",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    shared = {
        "scripts/emotion_engine_utils.py": _shared_source(source_dir, "scripts/emotion_engine_utils.py"),
        "scripts/emotion_engine_mcp.py": _shared_source(source_dir, "scripts/emotion_engine_mcp.py"),
        "scripts/register_mcp_client.py": _shared_source(source_dir, "scripts/register_mcp_client.py"),
        "emotion-state-template.json": _shared_source(source_dir, "emotion-state-template.json"),
        "spec/emotion-state.schema.json": _shared_source(source_dir, "spec/emotion-state.schema.json", required=False),
        "LICENSE": _shared_source(source_dir, "LICENSE", required=False),
    }
    if missing:
        raise PackwrightValidationError([f"Emotion Engine Codex source is missing required file: {path}" for path in missing])
    _validate_emotion_engine_codex_source(source_dir, shared)

    skill_dir = target_dir / EMOTION_ENGINE_CODEX_SKILL_DIR
    if skill_dir.exists() and not force:
        raise PackwrightValidationError(
            [
                "target already contains Emotion Engine Codex sidecar; rerun with --force after reviewing it",
                f"existing target artifact: {skill_dir.relative_to(target_dir)}",
            ]
        )

    return {
        "source_dir": source_dir,
        "shared": shared,
        "skill_dir": skill_dir,
        "state_file": target_dir / EMOTION_ENGINE_CODEX_STATE_PATH,
        "emotion_style": emotion_style or _manifest_emotion_style(manifest),
        "relationship_continuity": _manifest_relationship_continuity(manifest),
        "mode": emotion_engine_mode,
        "force": force,
    }


def _resolve_emotion_engine_codex_source(source):
    raw = source or os.environ.get("PACKWRIGHT_EMOTION_ENGINE_CODEX_DIR")
    if not raw:
        raise PackwrightValidationError([
            "Emotion Engine Codex source directory is required; pass --emotion-engine-codex-source "
            "or set PACKWRIGHT_EMOTION_ENGINE_CODEX_DIR"
        ])
    source_dir = Path(raw)
    if not source_dir.is_dir():
        raise PackwrightValidationError([f"Emotion Engine Codex source directory does not exist: {source_dir}"])
    return source_dir


def _shared_source(source_dir, rel_path, required=True):
    direct = source_dir / rel_path
    if direct.is_file():
        return direct
    repo_root = source_dir.parents[2] if len(source_dir.parents) >= 3 else source_dir
    fallback = repo_root / rel_path
    if fallback.is_file():
        return fallback
    if required:
        raise PackwrightValidationError([f"Emotion Engine Codex source is missing required shared file: {fallback}"])
    return None


def _validate_emotion_engine_codex_source(source_dir, shared):
    issues = []
    skill_text = (source_dir / "SKILL.md").read_text(encoding="utf-8")
    wrapper_text = (source_dir / "scripts" / "codex_emotion.sh").read_text(encoding="utf-8")
    engine_path = shared.get("scripts/emotion_engine_utils.py")
    mcp_path = shared.get("scripts/emotion_engine_mcp.py")
    register_path = shared.get("scripts/register_mcp_client.py")
    engine_text = engine_path.read_text(encoding="utf-8") if engine_path else ""
    mcp_text = mcp_path.read_text(encoding="utf-8") if mcp_path else ""
    register_text = register_path.read_text(encoding="utf-8") if register_path else ""
    if "settle_trust" not in skill_text:
        issues.append("Emotion Engine Codex skill must document settle_trust")
    if "record_policy" not in skill_text:
        issues.append("Emotion Engine Codex skill must document record_policy")
    if "settle_trust" not in engine_text:
        issues.append("Emotion Engine helper must implement settle_trust")
    if "record_policy" not in engine_text or "reply_bias" not in engine_text:
        issues.append("Emotion Engine helper must implement deterministic record_policy with reply_bias")
    if "tools/list" not in mcp_text or "emotion_engine_record_policy" not in mcp_text:
        issues.append("Emotion Engine MCP server must expose record_policy through tools/list")
    if "emotion_engine_repair" in mcp_text or "doctor_target" in mcp_text:
        issues.append("Emotion Engine MCP server must not expose Packwright repair commands")
    if "codex" not in register_text or "state" not in register_text:
        issues.append("Emotion Engine MCP registration helper must support Codex client registration")
    if "exec \"$PYTHON\" \"$ENGINE\" \"$COMMAND\" \"$STATE_FILE\"" not in wrapper_text:
        issues.append("Emotion Engine Codex wrapper must forward commands to the shared helper")
    if issues:
        raise PackwrightValidationError(issues)


def _manifest_emotion_style(manifest):
    character = manifest.get("character", {}) if isinstance(manifest, dict) else {}
    return character.get("emotion_style") or "calm, direct, lightly warm, and not over-compliant"


def _manifest_relationship_continuity(manifest):
    character = manifest.get("character", {}) if isinstance(manifest, dict) else {}
    continuity = character.get("relationship_continuity")
    if continuity in {"task_only", "warm_selective", "close_continuous"}:
        return continuity
    return "warm_selective"


def _emotion_engine_codex_projection_files(plan):
    skill_dir = plan["skill_dir"]
    source_dir = plan["source_dir"]
    files = [
        ("SKILL.md", source_dir / "SKILL.md"),
        ("README.md", source_dir / "README.md"),
        ("install.sh", source_dir / "install.sh"),
        ("scripts/codex_emotion.sh", source_dir / "scripts" / "codex_emotion.sh"),
        ("scripts/pulse_demo.py", source_dir / "scripts" / "pulse_demo.py"),
    ]
    files.extend((rel_path, source_path) for rel_path, source_path in plan["shared"].items() if source_path is not None)
    return [
        (
            f"{EMOTION_ENGINE_CODEX_SKILL_DIR}/{rel_path}",
            skill_dir / rel_path,
            source_path,
        )
        for rel_path, source_path in files
    ]


def _emotion_engine_codex_expected_in_target(manifest, target_dir):
    if emotion_engine_codex_expected(manifest):
        return True
    return any((target_dir / artifact).exists() for artifact in EMOTION_ENGINE_CODEX_ARTIFACTS)


def _emotion_engine_codex_doctor_issues(target_dir, manifest, plan):
    issues = []
    expected_artifacts = {EMOTION_ENGINE_CODEX_WRAPPER_PATH, EMOTION_ENGINE_CODEX_STATE_PATH}

    for rel_path, target_path, source_path in _emotion_engine_codex_projection_files(plan):
        expected_artifacts.add(rel_path)
        if not target_path.is_file():
            issues.append(_doctor_issue("emotion_engine_codex_missing_file", rel_path, "projected sidecar file is missing"))
            continue
        if _read_bytes(target_path) != _read_bytes(source_path):
            issues.append(_doctor_issue("emotion_engine_codex_file_drift", rel_path, "projected sidecar file differs from source"))

    wrapper_path = target_dir / EMOTION_ENGINE_CODEX_WRAPPER_PATH
    expected_wrapper = _project_emotion_wrapper_text()
    if not wrapper_path.is_file():
        issues.append(_doctor_issue("emotion_engine_codex_missing_file", EMOTION_ENGINE_CODEX_WRAPPER_PATH, "project wrapper is missing"))
    elif wrapper_path.read_text(encoding="utf-8") != expected_wrapper:
        issues.append(_doctor_issue("emotion_engine_codex_file_drift", EMOTION_ENGINE_CODEX_WRAPPER_PATH, "project wrapper differs from expected projection"))

    state_issue = _emotion_engine_state_issue(plan["state_file"])
    if state_issue:
        issues.append(state_issue)

    mode = plan["mode"]
    issues.extend(
        emotion_engine_codex_manifest_diagnostics(
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
    if not state_file.is_file():
        return _doctor_issue("emotion_engine_codex_missing_file", EMOTION_ENGINE_CODEX_STATE_PATH, "runtime state file is missing")
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _doctor_issue("emotion_engine_codex_state_invalid", EMOTION_ENGINE_CODEX_STATE_PATH, "runtime state file is not valid JSON")
    if not isinstance(state, dict) or state.get("_schema") != "emotion-engine-state/v2":
        return _doctor_issue("emotion_engine_codex_state_invalid", EMOTION_ENGINE_CODEX_STATE_PATH, "runtime state file has an unexpected schema")
    return None


def _install_emotion_engine_codex(target_dir, plan):
    skill_dir = plan["skill_dir"]
    if skill_dir.exists() and not skill_dir.is_dir():
        raise PackwrightValidationError([f"Emotion Engine Codex skill path is not a directory: {skill_dir}"])

    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "spec").mkdir(parents=True, exist_ok=True)
    for _, target_path, source_path in _emotion_engine_codex_projection_files(plan):
        _copy_sidecar_file(source_path, target_path)

    _make_executable(skill_dir / "install.sh")
    _make_executable(skill_dir / "scripts" / "codex_emotion.sh")
    _make_executable(skill_dir / "scripts" / "emotion_engine_mcp.py")
    _make_executable(skill_dir / "scripts" / "register_mcp_client.py")
    wrapper_path = _write_project_emotion_wrapper(target_dir, plan["force"])

    state_created = _ensure_emotion_state(
        plan["state_file"],
        plan["emotion_style"],
        plan["mode"],
        plan["relationship_continuity"],
    )
    agents_section_added = _ensure_emotion_section(target_dir / "AGENTS.md", plan["mode"])

    return {
        "skill_dir": str(skill_dir),
        "state_file": str(plan["state_file"]),
        "wrapper": str(wrapper_path),
        "mode": plan["mode"],
        "state_created": state_created,
        "agents_section_added": agents_section_added,
    }


def _mark_emotion_engine_codex_installed(target_dir, sidecar, mode):
    manifest_path = target_dir / "manifest.json"
    if not manifest_path.exists():
        return False
    manifest = _load_manifest(target_dir)
    manifest.setdefault("features", {})["emotion_engine"] = emotion_engine_feature(
        mode=mode,
        adapter="codex",
        installed=True,
    )
    manifest.setdefault("sidecars", {})[EMOTION_ENGINE_CODEX_SIDECAR] = emotion_engine_codex_sidecar_record(mode)
    boundaries = manifest.setdefault("boundaries", {})
    boundaries["emotion_engine_runtime"] = EMOTION_ENGINE_RUNTIME
    boundaries["emotion_engine_mode"] = mode
    artifacts = set(manifest.get("artifacts", []))
    artifacts.update(_existing_sidecar_artifacts(target_dir))
    manifest["artifacts"] = sorted(artifacts)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True


def _existing_sidecar_artifacts(target_dir):
    return [artifact for artifact in EMOTION_ENGINE_CODEX_ARTIFACTS if (target_dir / artifact).is_file()]


def _copy_sidecar_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _project_emotion_wrapper_text():
    return """#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
exec "$PROJECT_DIR/{script_path}" "$@"
""".format(script_path=EMOTION_ENGINE_CODEX_SCRIPT_PATH)


def _write_project_emotion_wrapper(target_dir, force=False):
    wrapper_path = target_dir / EMOTION_ENGINE_CODEX_WRAPPER_PATH
    expected = _project_emotion_wrapper_text()
    if wrapper_path.exists() and wrapper_path.read_text(encoding="utf-8") != expected and not force:
        raise PackwrightValidationError([
            "target already contains scripts/codex_emotion.sh; rerun with --force after reviewing it"
        ])
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_path.write_text(expected, encoding="utf-8")
    _make_executable(wrapper_path)
    return wrapper_path


def _make_executable(path):
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _ensure_emotion_state(state_file, emotion_style, mode, relationship_continuity="warm_selective"):
    if state_file.exists():
        _update_existing_emotion_state(state_file, mode, emotion_style, relationship_continuity)
        return False
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
    return True


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


def _ensure_emotion_section(agents_path, mode):
    if not agents_path.exists():
        return False
    text = agents_path.read_text(encoding="utf-8")
    section = EMOTION_ENGINE_SECTION.format(mode=mode)
    for heading in ["## Emotion Engine", "## Optional Emotion Engine"]:
        marker = text.find(heading)
        if marker == -1:
            continue
        next_heading = text.find("\n## ", marker + 1)
        if next_heading == -1:
            updated = text[:marker].rstrip() + "\n\n" + section
        else:
            updated = text[:marker].rstrip() + "\n\n" + section.rstrip() + "\n" + text[next_heading:]
        if updated != text:
            agents_path.write_text(updated, encoding="utf-8")
            return True
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n" + section
    agents_path.write_text(text, encoding="utf-8")
    return True
