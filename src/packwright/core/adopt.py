import hashlib
import json
from datetime import date
from pathlib import Path

from .errors import PackwrightValidationError
from .knowledge_contract import knowledge_files


MIGRATION_DIR = "workspace/shared/artifacts/migrations"
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
    }
    if dry_run:
        return result
    if target_dir is None:
        raise PackwrightValidationError(["adopt target_dir is required unless dry_run is true"])
    target_dir = Path(target_dir)
    report_path = target_dir / MIGRATION_DIR / f"adopt-report-{date.today().isoformat()}.md"
    inventory_path = target_dir / MIGRATION_DIR / "inventory.json"
    if not force and (report_path.exists() or inventory_path.exists()):
        raise PackwrightValidationError([
            "adopt migration report already exists; rerun with --force after reviewing it",
            f"existing target artifact: {report_path.relative_to(target_dir)}",
            f"existing target artifact: {inventory_path.relative_to(target_dir)}",
        ])
    _write_knowledge_scaffold(target_dir, force=force)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(source_dir, inventory, categories), encoding="utf-8")
    inventory_path.write_text(json.dumps({"files": inventory}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result.update({
        "target_dir": str(target_dir),
        "report": str(report_path),
        "inventory_json": str(inventory_path),
        "written": [
            str(report_path.relative_to(target_dir)),
            str(inventory_path.relative_to(target_dir)),
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
            "1. Review runtime instructions and decide which intent belongs in a Packwright mechanism.",
            "2. Promote only current, confirmed state into `memory/*` owner files.",
            "3. Promote only stable reusable models into `knowledge/**/*.md` with source refs.",
            "4. Keep original files registered as sources when provenance matters.",
        ]
    )
    return "\n".join(lines) + "\n"
