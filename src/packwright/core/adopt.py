import hashlib
import json
from datetime import date
from pathlib import Path

import yaml

from .errors import PackwrightValidationError
from .knowledge_contract import empty_source_manifest, knowledge_files
from .path_safety import resolve_destination_path, resolve_source_path, validate_relative_path


MIGRATION_DIR = "workspace/shared/artifacts/migrations"
ADOPTION_REVIEW_SCHEMA = "packwright-adoption-review/v1"
ADOPTION_APPLY_SCHEMA = "packwright-adoption-apply/v1"
ADOPTION_REVIEW_DECISIONS = (
    "pending",
    "exclude",
    "register_source",
    "carry_verbatim",
    "copy_to_workspace",
    "manual_memory_merge",
)
RUNTIME_PATTERNS = (
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor/rules/",
    ".codex/",
    ".claude/",
)
MEMORY_PATTERNS = (
    "memory/",
    "todo",
    "session",
    "project",
    "workstream",
    "collaboration",
)
KNOWLEDGE_PATTERNS = (
    "knowledge/",
    "principle",
    "model",
    "playbook",
    "framework",
    "method",
)


def adopt_existing(source_dir, target_dir=None, dry_run=True, force=False):
    """Inventory an existing local agent/workspace for reviewable Packwright adoption.

    Adoption treats the existing instance as source material. It writes a
    migration report and inventory only when dry_run is false; it does not
    merge old memory or promote knowledge notes.
    """
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise PackwrightValidationError([f"adopt source directory does not exist: {source_dir}"])

    inventory = _inventory(source_dir)
    categories = _category_counts(inventory)
    review_queue = _review_queue(source_dir, inventory)
    result = {
        "source_dir": str(source_dir),
        "dry_run": bool(dry_run),
        "files": len(inventory),
        "categories": categories,
        "adoption_policy": {
            "existing_instance_role": "source_material",
            "memory_merge": "review_required",
            "knowledge_promotion": "review_required",
            "in_place_modification": False,
        },
        "inventory": inventory,
        "review_queue": {
            "schema": ADOPTION_REVIEW_SCHEMA,
            "items": len(review_queue["items"]),
            "pending": len(review_queue["items"]),
            "applies_decisions": False,
        },
    }
    if dry_run:
        return result
    if target_dir is None:
        raise PackwrightValidationError(["adopt target_dir is required unless dry_run is true"])
    target_dir = Path(target_dir)
    report_path = target_dir / MIGRATION_DIR / f"adopt-report-{date.today().isoformat()}.md"
    inventory_path = target_dir / MIGRATION_DIR / "inventory.json"
    review_path = target_dir / MIGRATION_DIR / "adoption-review.yaml"
    existing = [path for path in (report_path, inventory_path, review_path) if path.exists()]
    if not force and existing:
        raise PackwrightValidationError([
            "adopt migration report already exists; rerun with --force after reviewing it",
            *[
                f"existing target artifact: {path.relative_to(target_dir)}"
                for path in existing
            ],
        ])
    _write_knowledge_scaffold(target_dir, force=force)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(source_dir, inventory, categories), encoding="utf-8")
    inventory_path.write_text(json.dumps({"files": inventory}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    review_path.write_text(
        yaml.safe_dump(review_queue, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    result.update({
        "target_dir": str(target_dir),
        "report": str(report_path),
        "inventory_json": str(inventory_path),
        "review_queue_yaml": str(review_path),
        "written": [
            str(report_path.relative_to(target_dir)),
            str(inventory_path.relative_to(target_dir)),
            str(review_path.relative_to(target_dir)),
        ],
    })
    return result


def _inventory(source_dir):
    files = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(source_dir).as_posix()
        if _skip_path(rel_path):
            continue
        files.append({
            "path": rel_path,
            "size": path.stat().st_size,
            "sha256": _sha256(path),
            "category": _classify(rel_path),
        })
    return files


def _skip_path(rel_path):
    parts = set(Path(rel_path).parts)
    return bool(parts & {".git", "__pycache__", "node_modules", ".venv", "venv"})


def _classify(rel_path):
    lowered = rel_path.lower()
    if any(lowered == pattern.lower() or lowered.startswith(pattern.lower()) for pattern in RUNTIME_PATTERNS):
        return "runtime_instruction"
    if lowered.startswith(("workspace/", "artifacts/", "drafts/", "archive/")):
        return "workspace_artifact"
    if any(pattern in lowered for pattern in MEMORY_PATTERNS):
        return "memory_candidate"
    if any(pattern in lowered for pattern in KNOWLEDGE_PATTERNS):
        return "knowledge_candidate"
    if lowered.endswith((".md", ".txt", ".yaml", ".yml", ".json", ".pdf", ".docx")):
        return "source_candidate"
    return "unclassified"


def _category_counts(inventory):
    counts = {}
    for item in inventory:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    return counts


def _review_queue(source_dir, inventory):
    return {
        "schema": ADOPTION_REVIEW_SCHEMA,
        "source_dir": str(source_dir),
        "policy": {
            "all_items_require_review": True,
            "automatic_memory_merge": False,
            "automatic_knowledge_promotion": False,
            "apply_supported": True,
        },
        "allowed_decisions": list(ADOPTION_REVIEW_DECISIONS),
        "items": [
            {
                "source": item["path"],
                "category": item["category"],
                "size": item["size"],
                "sha256": item["sha256"],
                "decision": "pending",
                "destination": None,
                "rationale": None,
            }
            for item in inventory
        ],
    }


def plan_adoption_review(review_path, target_dir):
    """Validate a reviewed adoption queue and return a zero-write action plan."""
    review_path = Path(review_path)
    target_dir = Path(target_dir)
    review = _load_review(review_path)
    if not target_dir.is_dir():
        raise PackwrightValidationError([f"adoption target directory does not exist: {target_dir}"])
    source_dir = Path(review.get("source_dir", ""))
    if not source_dir.is_dir():
        raise PackwrightValidationError([f"adoption source directory does not exist: {source_dir}"])

    actions = []
    conflicts = []
    destination_sources = {}
    items = review.get("items")
    if not isinstance(items, list):
        raise PackwrightValidationError(["adoption review items must be a list"])
    for index, item in enumerate(items):
        action, item_conflicts = _plan_review_item(
            item,
            index=index,
            source_dir=source_dir,
            target_dir=target_dir,
        )
        actions.append(action)
        conflicts.extend(item_conflicts)
        destination = action.get("destination")
        if action.get("operation") == "copy" and destination:
            previous = destination_sources.get(destination)
            if previous and previous != action["sha256"]:
                conflicts.append({
                    "item": index,
                    "source": action["source"],
                    "destination": destination,
                    "message": "multiple approved items select the same destination with different content",
                })
            destination_sources[destination] = action["sha256"]

    counts = {}
    for action in actions:
        counts[action["status"]] = counts.get(action["status"], 0) + 1
    approved = sum(action["decision"] != "pending" for action in actions)
    if not approved:
        conflicts.append({"item": None, "source": None, "message": "no review decisions have been approved"})
    return {
        "schema": ADOPTION_APPLY_SCHEMA,
        "status": "planned" if not conflicts else "blocked",
        "dry_run": True,
        "ready": not conflicts,
        "review": str(review_path),
        "source_dir": str(source_dir),
        "target_dir": str(target_dir),
        "items": len(actions),
        "approved": approved,
        "counts": counts,
        "actions": actions,
        "conflicts": conflicts,
        "policy": {
            "pending_items_are_not_applied": True,
            "memory_merge_is_never_automatic": True,
            "knowledge_promotion_is_never_automatic": True,
            "existing_destination_content_is_never_overwritten": True,
        },
    }


def apply_adoption_review(review_path, target_dir):
    """Apply only explicit, safe queue decisions and write a path-level receipt."""
    plan = plan_adoption_review(review_path, target_dir)
    if not plan["ready"]:
        raise PackwrightValidationError([
            "adoption review is not ready to apply",
            *[conflict["message"] for conflict in plan["conflicts"]],
        ])
    source_dir = Path(plan["source_dir"])
    target_dir = Path(plan["target_dir"])
    applied = []
    registrations = []
    for action in plan["actions"]:
        if action["operation"] == "copy" and action["status"] == "approved_copy":
            source = resolve_source_path(source_dir, action["source"], "adoption source")
            if _sha256(source) != action["sha256"]:
                raise PackwrightValidationError([f"adoption source changed after review: {action['source']}"])
            destination = resolve_destination_path(target_dir, action["destination"], "adoption destination")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            applied.append({**action, "status": "copied"})
        elif action["operation"] == "register_source":
            registrations.append(action)
            applied.append({**action, "status": "registered"})
        else:
            applied.append(action)
    if registrations:
        _apply_source_registrations(target_dir, source_dir, registrations)

    receipt = {
        **plan,
        "status": "applied",
        "dry_run": False,
        "actions": applied,
        "conflicts": [],
    }
    receipt_path = resolve_destination_path(
        target_dir,
        f"{MIGRATION_DIR}/adoption-apply-receipt.json",
        "adoption receipt",
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt["receipt"] = str(receipt_path)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _load_review(review_path):
    try:
        review = yaml.safe_load(review_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PackwrightValidationError([f"cannot read adoption review {review_path}: {exc}"])
    except yaml.YAMLError as exc:
        raise PackwrightValidationError([f"invalid adoption review YAML {review_path}: {exc}"])
    if not isinstance(review, dict) or review.get("schema") != ADOPTION_REVIEW_SCHEMA:
        raise PackwrightValidationError([f"adoption review schema must be {ADOPTION_REVIEW_SCHEMA}"])
    return review


def _plan_review_item(item, index, source_dir, target_dir):
    conflicts = []
    if not isinstance(item, dict):
        return ({"item": index, "decision": None, "status": "invalid", "operation": "none"}, [{
            "item": index, "source": None, "message": "review item must be a mapping"
        }])
    source_value = item.get("source")
    decision = item.get("decision")
    action = {
        "item": index,
        "source": source_value,
        "category": item.get("category"),
        "decision": decision,
        "destination": item.get("destination"),
        "sha256": item.get("sha256"),
        "size": item.get("size"),
        "rationale": item.get("rationale"),
        "operation": "none",
        "status": "pending" if decision == "pending" else "approved",
    }
    if decision not in ADOPTION_REVIEW_DECISIONS:
        conflicts.append(_review_conflict(index, source_value, "decision is not allowed"))
        action["status"] = "invalid"
        return action, conflicts
    if decision == "pending":
        try:
            source = resolve_source_path(source_dir, source_value, "pending adoption review source")
            if action["sha256"] != _sha256(source) or action["size"] != source.stat().st_size:
                action["status"] = "pending_changed"
        except PackwrightValidationError:
            action["status"] = "pending_unavailable"
        return action, conflicts
    if not isinstance(action["rationale"], str) or not action["rationale"].strip():
        conflicts.append(_review_conflict(index, source_value, "approved decision requires a rationale"))
    if decision == "exclude":
        action["status"] = "excluded"
        if action["destination"] is not None:
            conflicts.append(_review_conflict(index, source_value, "exclude must not set a destination"))
        return action, conflicts
    try:
        source = resolve_source_path(source_dir, source_value, "adoption review source")
    except PackwrightValidationError as exc:
        conflicts.extend(_review_conflict(index, source_value, issue) for issue in exc.issues)
        action["status"] = "invalid"
        return action, conflicts
    actual_sha = _sha256(source)
    if action["sha256"] != actual_sha or action["size"] != source.stat().st_size:
        conflicts.append(_review_conflict(index, source_value, "source size or SHA-256 changed after inventory"))
    if decision == "register_source":
        action["operation"] = "register_source"
        action["status"] = "approved_registration"
        if action["destination"] is not None:
            conflicts.append(_review_conflict(index, source_value, "register_source must not set a destination"))
        return action, conflicts
    if decision == "manual_memory_merge":
        action["status"] = "manual_merge_required"
        if action["category"] != "memory_candidate":
            conflicts.append(_review_conflict(index, source_value, "manual_memory_merge is only valid for memory candidates"))
        if not _destination_under(action["destination"], ("memory",)):
            conflicts.append(_review_conflict(index, source_value, "manual_memory_merge must name the intended memory/* owner file"))
        return action, conflicts

    prefixes = ("workspace",) if decision == "copy_to_workspace" else ("workspace", "skills")
    if not _destination_under(action["destination"], prefixes):
        allowed = " or ".join(f"{prefix}/*" for prefix in prefixes)
        conflicts.append(_review_conflict(index, source_value, f"{decision} destination must stay under {allowed}"))
        action["status"] = "invalid"
        return action, conflicts
    try:
        destination = resolve_destination_path(target_dir, action["destination"], "adoption destination")
    except PackwrightValidationError as exc:
        conflicts.extend(_review_conflict(index, source_value, issue) for issue in exc.issues)
        action["status"] = "invalid"
        return action, conflicts
    action["operation"] = "copy"
    if destination.exists():
        if destination.is_file() and _sha256(destination) == actual_sha:
            action["status"] = "already_present"
        else:
            action["status"] = "conflict"
            conflicts.append(_review_conflict(index, source_value, "approved destination already exists with different content", action["destination"]))
    else:
        action["status"] = "approved_copy"
    return action, conflicts


def _destination_under(value, prefixes):
    try:
        path = validate_relative_path(value, "adoption destination")
    except PackwrightValidationError:
        return False
    return bool(path.parts and path.parts[0] in prefixes and len(path.parts) > 1)


def _review_conflict(index, source, message, destination=None):
    result = {"item": index, "source": source, "message": message}
    if destination is not None:
        result["destination"] = destination
    return result


def _apply_source_registrations(target_dir, source_dir, registrations):
    manifest_path = resolve_destination_path(
        target_dir,
        "sources/local/manifest.json",
        "local source manifest",
    )
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PackwrightValidationError([f"invalid local source manifest: {exc}"])
    else:
        manifest = empty_source_manifest("local")
    sources = manifest.setdefault("sources", {})
    for action in registrations:
        source_id = f"adopt-{action['sha256'][:12]}"
        entry = {
            "kind": "local_file",
            "path": str((source_dir / action["source"]).resolve()),
            "source_path": action["source"],
            "sha256": action["sha256"],
            "size": action["size"],
            "rationale": action["rationale"],
        }
        existing = sources.get(source_id)
        if existing is not None and existing != entry:
            raise PackwrightValidationError([f"local source registration conflicts with existing entry: {source_id}"])
        sources[source_id] = entry
    manifest["updated"] = date.today().isoformat()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_knowledge_scaffold(target_dir, force=False):
    for rel_path, text in knowledge_files().items():
        path = target_dir / rel_path
        if path.exists() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _render_report(source_dir, inventory, categories):
    lines = [
        "# Packwright Adopt Report",
        "",
        f"Source: `{source_dir}`",
        "",
        "## Policy",
        "",
        "- Existing instances are source material, not automatic memory or knowledge.",
        "- Runtime instructions need review before becoming Packwright mechanism or adapter projections.",
        "- Memory candidates need review before writing to `memory/*` owner files.",
        "- Knowledge candidates need review before promotion to `knowledge/**/*.md`.",
        "- Source candidates may be registered in `sources/*/manifest.json` for provenance.",
        "",
        "## Inventory Summary",
        "",
    ]
    for category, count in sorted(categories.items()):
        lines.append(f"- {category}: {count}")
    lines.extend(["", "## Review Queues", ""])
    for category in (
        "runtime_instruction",
        "memory_candidate",
        "knowledge_candidate",
        "source_candidate",
        "workspace_artifact",
        "unclassified",
    ):
        items = [item for item in inventory if item["category"] == category]
        if not items:
            continue
        lines.extend([f"### {category}", ""])
        for item in items[:50]:
            lines.append(f"- `{item['path']}` ({item['size']} bytes)")
        if len(items) > 50:
            lines.append(f"- ... {len(items) - 50} more")
        lines.append("")
    lines.extend(
        [
            "## Next Steps",
            "",
            "1. Open `adoption-review.yaml` and choose a decision for each item.",
            "2. Leave uncertain items as `pending`; pending items are never applied.",
            "3. Preview approved actions with `packwright adopt --review <queue> --target-dir <target> --dry-run`.",
            "4. Apply reviewed safe-copy and source-registration decisions by replacing `--dry-run` with `--yes`.",
            "5. `manual_memory_merge` records the intended owner file but never writes memory automatically.",
            "6. Promote reusable knowledge manually after reviewing its content and provenance.",
        ]
    )
    return "\n".join(lines) + "\n"
