import json
from pathlib import Path


KNOWLEDGE_ROOT = "knowledge"
SOURCES_ROOT = "sources"
KNOWLEDGE_INDEX = "knowledge/index.md"
KNOWLEDGE_MANIFEST = "knowledge/manifest.json"
SOURCE_MANIFESTS = (
    "sources/local/manifest.json",
    "sources/notion/manifest.json",
    "sources/repos/manifest.json",
    "sources/web/manifest.json",
)
KNOWLEDGE_SCHEMA = "packwright-knowledge-manifest/v1"
SOURCE_SCHEMA = "packwright-source-manifest/v1"
MAX_KNOWLEDGE_INDEX_LINES = 200
MAX_DOMAIN_INDEX_LINES = 300


def knowledge_required_dirs():
    return (
        KNOWLEDGE_ROOT,
        SOURCES_ROOT,
        "sources/local",
        "sources/notion",
        "sources/repos",
        "sources/web",
    )


def knowledge_artifacts():
    return (KNOWLEDGE_INDEX, KNOWLEDGE_MANIFEST, *SOURCE_MANIFESTS)


def knowledge_files():
    files = {
        KNOWLEDGE_INDEX: knowledge_index_text(),
        KNOWLEDGE_MANIFEST: json.dumps(empty_knowledge_manifest(), indent=2, sort_keys=True) + "\n",
    }
    for rel_path in SOURCE_MANIFESTS:
        provider = Path(rel_path).parent.name
        files[rel_path] = json.dumps(empty_source_manifest(provider), indent=2, sort_keys=True) + "\n"
    return files


def knowledge_index_text():
    return (
        "# Knowledge Recall Index\n\n"
        "Use this file only when a request needs reusable domain knowledge beyond current project state, todos, or source lookup.\n\n"
        "Do not load every note by default. Use this file as a short routing block, then read the selected domain index or note.\n\n"
        "## Loading Rules\n\n"
        "1. Read `memory/index.md` first for local memory routing.\n"
        "2. If the request needs reusable models, principles, or domain patterns, read this file.\n"
        "3. Match the request against domain entries below.\n"
        "4. Read the smallest useful note set.\n"
        "5. Follow `source_refs` only when factual evidence, citation, or source verification matters.\n\n"
        "## Domains\n\n"
        "No reviewed knowledge notes have been recorded yet.\n"
    )


def empty_knowledge_manifest():
    return {
        "schema": KNOWLEDGE_SCHEMA,
        "generated": False,
        "updated": None,
        "notes": [],
    }


def empty_source_manifest(provider):
    return {
        "schema": SOURCE_SCHEMA,
        "provider": provider,
        "updated": None,
        "sources": {},
    }


def knowledge_feature():
    return {
        "root": KNOWLEDGE_ROOT,
        "recall_index": KNOWLEDGE_INDEX,
        "manifest": KNOWLEDGE_MANIFEST,
        "sources_root": SOURCES_ROOT,
        "source_manifests": list(SOURCE_MANIFESTS),
        "loading_policy": "explicit_gate_then_smallest_useful_note_set",
        "status": "scaffold",
    }


def knowledge_entry_lines(prefix=""):
    return [
        f"{prefix}Read `knowledge/index.md` only when the task needs reusable domain knowledge beyond current memory or source lookup.",
        f"{prefix}Use `knowledge/**/*.md` for reviewed reusable models and patterns; do not put current project status or todos there.",
        f"{prefix}Use `sources/*/manifest.json` for provenance; source manifests are not runtime knowledge bodies.",
    ]


def knowledge_manifest_diagnostics(root_dir):
    root_dir = Path(root_dir)
    issues = []
    manifest_path = root_dir / KNOWLEDGE_MANIFEST
    manifest = _read_json(manifest_path, issues, "knowledge_manifest_invalid")
    source_manifests = {}
    for rel_path in SOURCE_MANIFESTS:
        data = _read_json(root_dir / rel_path, issues, "source_manifest_invalid")
        if isinstance(data, dict):
            source_manifests[Path(rel_path).parent.name] = data.get("sources", {})
    if isinstance(manifest, dict):
        issues.extend(_knowledge_notes_diagnostics(root_dir, manifest, source_manifests))
    issues.extend(_knowledge_index_diagnostics(root_dir))
    return issues


def _knowledge_notes_diagnostics(root_dir, manifest, source_manifests):
    issues = []
    notes = manifest.get("notes", [])
    if not isinstance(notes, list):
        return [_issue("knowledge_manifest_notes_invalid", KNOWLEDGE_MANIFEST, "knowledge manifest notes must be a list")]
    for note in notes:
        if not isinstance(note, dict):
            issues.append(_issue("knowledge_manifest_note_invalid", KNOWLEDGE_MANIFEST, "knowledge manifest notes must be objects"))
            continue
        path = note.get("path")
        if not isinstance(path, str) or not path.startswith("knowledge/") or ".." in Path(path).parts:
            issues.append(_issue("knowledge_note_path_invalid", KNOWLEDGE_MANIFEST, "knowledge note path must stay under knowledge/"))
            continue
        note_path = root_dir / path
        if not note_path.is_file():
            issues.append(_issue("knowledge_note_missing", path, "knowledge note listed in manifest is missing"))
            continue
        frontmatter = _frontmatter(note_path)
        for field in ("id", "domain", "type", "status", "source_refs"):
            if field not in frontmatter:
                issues.append(_issue("knowledge_note_frontmatter_missing", path, f"knowledge note frontmatter missing {field}"))
        for ref in _note_source_refs(frontmatter):
            provider, _, key = ref.partition(":")
            if not provider or not key or key not in source_manifests.get(provider, {}):
                issues.append(_issue("knowledge_source_ref_unresolved", path, f"source ref is unresolved: {ref}"))
    return issues


def _knowledge_index_diagnostics(root_dir):
    issues = []
    index_path = root_dir / KNOWLEDGE_INDEX
    if not index_path.is_file():
        return issues
    lines = index_path.read_text(encoding="utf-8").splitlines()
    if len(lines) > MAX_KNOWLEDGE_INDEX_LINES:
        issues.append(_issue("knowledge_recall_index_too_long", KNOWLEDGE_INDEX, "knowledge recall index is too long"))
    for line in lines:
        marker = "Note: `"
        if marker not in line:
            continue
        rel_path = line.split(marker, 1)[1].split("`", 1)[0]
        if rel_path and not (root_dir / rel_path).is_file():
            issues.append(_issue("knowledge_index_note_missing", KNOWLEDGE_INDEX, f"index points to missing note: {rel_path}"))
    for domain_index in (root_dir / KNOWLEDGE_ROOT).glob("*/index.md"):
        count = len(domain_index.read_text(encoding="utf-8").splitlines())
        if count > MAX_DOMAIN_INDEX_LINES:
            issues.append(_issue("knowledge_domain_index_too_long", str(domain_index.relative_to(root_dir)), "knowledge domain index is too long"))
    return issues


def _read_json(path, issues, issue_id):
    if not path.is_file():
        issues.append(_issue("knowledge_scaffold_missing_file", str(path), "required knowledge scaffold file is missing"))
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.append(_issue(issue_id, str(path), f"invalid JSON: {exc}"))
        return None


def _frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    result = {}
    current = None
    for raw_line in text[4:end].splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("  - ") and current:
            result.setdefault(current, []).append(line[4:].strip())
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current = key.strip()
            value = value.strip()
            result[current] = value if value else []
    return result


def _note_source_refs(frontmatter):
    refs = frontmatter.get("source_refs", [])
    if isinstance(refs, list):
        return refs
    if isinstance(refs, str) and refs:
        return [refs]
    return []


def _issue(issue_id, path, message):
    return {"id": issue_id, "path": path, "message": message}
