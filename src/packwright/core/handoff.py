import hashlib
import json
from pathlib import Path

from .adapter_layout import supported_adapters
from .errors import PackwrightValidationError


HANDOFF_SCHEMA = "packwright-handoff/v1"
HANDOFF_HELPER_PATH = "scripts/packwright_handoff.py"
HANDOFF_WRAPPER_PATH = "scripts/handoff_export.sh"
HANDOFF_ARTIFACTS = (HANDOFF_HELPER_PATH, HANDOFF_WRAPPER_PATH)
HANDOFF_EXECUTABLE_ARTIFACTS = (HANDOFF_WRAPPER_PATH,)
DEFAULT_HANDOFF_DIR = "workspace/shared/artifacts/handoffs"
DEFAULT_SESSION_BRIEF_DIR = "workspace/shared/artifacts/session-briefs"
SUPPORTED_HANDOFF_ADAPTERS = set(supported_adapters())
PORTABLE_STATE_DIRS = ("memory", "workspace")
DEFAULT_HANDOFF_READS = (
    "memory/index.md",
    "memory/todos.md",
    "memory/session-index.md",
    "memory/source-map.md",
)


def create_handoff(
    source_target_dir,
    out_path,
    summary=None,
    changed_paths=None,
    recommended_reads=None,
    next_steps=None,
    include_inventory=False,
):
    """Write a reviewable cross-agent handoff file without syncing targets."""
    source_target_dir = Path(source_target_dir)
    out_path = Path(out_path)
    manifest = _load_manifest(source_target_dir)
    adapter = _validated_manifest_adapter(manifest, "source")
    changed = _normalize_handoff_paths(changed_paths or [])
    reads = _normalize_handoff_paths(recommended_reads or _default_handoff_reads(source_target_dir))
    steps = [step.strip() for step in (next_steps or []) if step and step.strip()]
    handoff = {
        "schema": HANDOFF_SCHEMA,
        "source_target_dir": str(source_target_dir),
        "source_adapter": adapter,
        "character": _manifest_character(manifest),
        "summary": summary or "",
        "changed_paths": _handoff_path_records(source_target_dir, changed),
        "recommended_reads": _handoff_path_records(source_target_dir, reads),
        "next_steps": steps,
        "apply_policy": [
            "Use workspace/shared/artifacts/handoffs/ for real cross-agent or cross-runtime handoffs.",
            "Use workspace/shared/artifacts/session-briefs/ for same-agent next-session briefs.",
            "Do not blindly copy memory or workspace files across targets.",
            "Update the receiving target's own memory only after review.",
        ],
    }
    if include_inventory:
        handoff["portable_inventory"] = {
            root: _handoff_path_records(source_target_dir, _portable_files_under(source_target_dir, root))
            for root in PORTABLE_STATE_DIRS
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_handoff_markdown(handoff), encoding="utf-8")
    return {
        "schema": HANDOFF_SCHEMA,
        "source_target_dir": str(source_target_dir),
        "source_adapter": adapter,
        "handoff_file": str(out_path),
        "changed_paths": changed,
        "recommended_reads": reads,
        "next_steps": steps,
        "include_inventory": include_inventory,
        "default_handoff_dir": DEFAULT_HANDOFF_DIR,
        "session_brief_dir": DEFAULT_SESSION_BRIEF_DIR,
    }


def handoff_feature():
    return {
        "schema": HANDOFF_SCHEMA,
        "helper": HANDOFF_HELPER_PATH,
        "command": HANDOFF_WRAPPER_PATH,
        "default_handoff_dir": DEFAULT_HANDOFF_DIR,
        "session_brief_dir": DEFAULT_SESSION_BRIEF_DIR,
        "policy": "handoffs are reviewable communication artifacts, not target sync",
    }


def target_handoff_artifacts():
    return {
        HANDOFF_HELPER_PATH: render_target_handoff_helper(),
        HANDOFF_WRAPPER_PATH: render_target_handoff_wrapper(),
    }


def render_target_handoff_wrapper():
    return (
        "#!/usr/bin/env sh\n"
        "set -eu\n"
        "SCRIPT_DIR=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "TARGET_DIR=$(CDPATH= cd -- \"$SCRIPT_DIR/..\" && pwd)\n"
        "PYTHON=${PYTHON:-python3}\n"
        "exec \"$PYTHON\" \"$SCRIPT_DIR/packwright_handoff.py\" --source-target-dir \"$TARGET_DIR\" \"$@\"\n"
    )


def render_target_handoff_helper():
    return (
        _TARGET_HANDOFF_HELPER_SOURCE.replace("__HANDOFF_SCHEMA__", HANDOFF_SCHEMA)
        .replace("__DEFAULT_HANDOFF_DIR__", DEFAULT_HANDOFF_DIR)
        .replace("__DEFAULT_SESSION_BRIEF_DIR__", DEFAULT_SESSION_BRIEF_DIR)
        .replace("__SUPPORTED_ADAPTERS__", repr(list(supported_adapters())))
        .lstrip()
    )


def _load_manifest(target_dir):
    manifest_path = target_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PackwrightValidationError([f"cannot read adapter target manifest {manifest_path}: {exc}"])
    except json.JSONDecodeError as exc:
        raise PackwrightValidationError([f"invalid adapter target manifest {manifest_path}: {exc}"])
    if not isinstance(manifest, dict):
        raise PackwrightValidationError([f"adapter target manifest must be a mapping: {manifest_path}"])
    return manifest


def _validated_manifest_adapter(manifest, label):
    adapter = manifest.get("adapter")
    if adapter not in SUPPORTED_HANDOFF_ADAPTERS:
        raise PackwrightValidationError([f"{label} target adapter is unsupported: {adapter!r}"])
    return adapter


def _manifest_character(manifest):
    character = manifest.get("character", {}) if isinstance(manifest, dict) else {}
    if not isinstance(character, dict):
        return {}
    return {
        key: character.get(key)
        for key in ("name", "slug", "relationship_continuity", "direct_emotional_interaction")
        if character.get(key) is not None
    }


def _default_handoff_reads(source_target_dir):
    return [rel_path for rel_path in DEFAULT_HANDOFF_READS if (source_target_dir / rel_path).exists()]


def _normalize_handoff_paths(paths):
    normalized = []
    issues = []
    for raw_path in paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            issues.append("handoff paths must be non-empty relative strings")
            continue
        path = Path(raw_path.strip())
        if path.is_absolute() or ".." in path.parts:
            issues.append(f"handoff path must be relative and stay inside the target: {raw_path}")
            continue
        rel_path = path.as_posix()
        if rel_path not in normalized:
            normalized.append(rel_path)
    if issues:
        raise PackwrightValidationError(issues)
    return normalized


def _handoff_path_records(source_target_dir, rel_paths):
    return [_handoff_path_record(source_target_dir, rel_path) for rel_path in rel_paths]


def _handoff_path_record(source_target_dir, rel_path):
    path = source_target_dir / rel_path
    record = {"path": rel_path}
    if path.is_file():
        data = path.read_bytes()
        record.update({
            "kind": "file",
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    elif path.is_dir():
        files = _portable_files_under(source_target_dir, rel_path)
        record.update({
            "kind": "directory",
            "file_count": len(files),
        })
    else:
        record["kind"] = "missing"
    return record


def _portable_files_under(source_target_dir, rel_root):
    root = source_target_dir / rel_root
    if not root.exists():
        return []
    if root.is_file():
        return [rel_root]
    if not root.is_dir():
        return []
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and _path_stays_in_root(path, source_target_dir):
            files.append(path.relative_to(source_target_dir).as_posix())
    return files


def _render_handoff_markdown(handoff):
    metadata = json.dumps(handoff, indent=2, sort_keys=True, ensure_ascii=False)
    changed = _render_handoff_path_list(handoff["changed_paths"])
    reads = _render_handoff_path_list(handoff["recommended_reads"])
    steps = _render_handoff_steps(handoff["next_steps"])
    summary = handoff["summary"] or "_Source agent has not written a human summary yet._"
    return (
        "# Packwright Handoff\n\n"
        "```json\n"
        f"{metadata}\n"
        "```\n\n"
        "## Summary\n\n"
        f"{summary}\n\n"
        "## Changed State\n\n"
        f"{changed}\n\n"
        "## Recommended Reads\n\n"
        f"{reads}\n\n"
        "## Next Steps\n\n"
        f"{steps}\n\n"
        "## Apply Policy\n\n"
        "- Use `workspace/shared/artifacts/handoffs/` for real cross-agent or cross-runtime handoffs.\n"
        "- Use `workspace/shared/artifacts/session-briefs/` for same-agent next-session briefs.\n"
        "- The receiving agent reads this file first and decides which referenced source files to inspect.\n"
        "- The receiving agent updates its own memory after review; do not blindly copy target files.\n"
    )


def _render_handoff_path_list(records):
    if not records:
        return "- No paths declared."
    lines = []
    for record in records:
        detail = record["kind"]
        if record["kind"] == "file":
            detail = f"file, sha256 `{record['sha256']}`"
        elif record["kind"] == "directory":
            detail = f"directory, {record['file_count']} files"
        lines.append(f"- `{record['path']}` ({detail})")
    return "\n".join(lines)


def _render_handoff_steps(steps):
    if not steps:
        return "- No next steps declared."
    return "\n".join(f"- {step}" for step in steps)


def _path_stays_in_root(path, root_dir):
    try:
        path.resolve().relative_to(root_dir.resolve())
    except ValueError:
        return False
    return True


_TARGET_HANDOFF_HELPER_SOURCE = r'''
#!/usr/bin/env python3
import argparse
import hashlib
import json
import sys
from pathlib import Path


HANDOFF_SCHEMA = "__HANDOFF_SCHEMA__"
DEFAULT_HANDOFF_DIR = "__DEFAULT_HANDOFF_DIR__"
DEFAULT_SESSION_BRIEF_DIR = "__DEFAULT_SESSION_BRIEF_DIR__"
SUPPORTED_ADAPTERS = set(__SUPPORTED_ADAPTERS__)
PORTABLE_STATE_DIRS = ("memory", "workspace")
DEFAULT_READS = (
    "memory/index.md",
    "memory/todos.md",
    "memory/session-index.md",
    "memory/source-map.md",
)


class HandoffError(Exception):
    pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Write a Packwright cross-agent handoff file without syncing targets."
    )
    parser.add_argument("--source-target-dir", default=".", help="installed source target directory")
    parser.add_argument("--out", required=True, help="handoff Markdown output path")
    parser.add_argument("--summary", help="human handoff summary written by the source agent")
    parser.add_argument("--changed", action="append", default=[], help="relative source target path changed")
    parser.add_argument("--read", action="append", default=[], dest="reads", help="relative source path to inspect")
    parser.add_argument("--next-step", action="append", default=[], help="next step for the receiving agent")
    parser.add_argument(
        "--include-inventory",
        action="store_true",
        help="include a portable memory/workspace file inventory for review; does not copy files",
    )
    args = parser.parse_args(argv)

    try:
        result = create_handoff(
            args.source_target_dir,
            args.out,
            summary=args.summary,
            changed_paths=args.changed,
            recommended_reads=args.reads or None,
            next_steps=args.next_step,
            include_inventory=args.include_inventory,
        )
    except HandoffError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def create_handoff(
    source_target_dir,
    out_path,
    summary=None,
    changed_paths=None,
    recommended_reads=None,
    next_steps=None,
    include_inventory=False,
):
    source_target_dir = Path(source_target_dir)
    out_path = Path(out_path)
    manifest = _load_manifest(source_target_dir)
    adapter = _validated_manifest_adapter(manifest)
    changed = _normalize_paths(changed_paths or [])
    reads = _normalize_paths(recommended_reads or _default_reads(source_target_dir))
    steps = [step.strip() for step in (next_steps or []) if step and step.strip()]
    handoff = {
        "schema": HANDOFF_SCHEMA,
        "source_target_dir": str(source_target_dir),
        "source_adapter": adapter,
        "character": _manifest_character(manifest),
        "summary": summary or "",
        "changed_paths": _path_records(source_target_dir, changed),
        "recommended_reads": _path_records(source_target_dir, reads),
        "next_steps": steps,
        "apply_policy": [
            "Use workspace/shared/artifacts/handoffs/ for real cross-agent or cross-runtime handoffs.",
            "Use workspace/shared/artifacts/session-briefs/ for same-agent next-session briefs.",
            "Do not blindly copy memory or workspace files across targets.",
            "Update the receiving target's own memory only after review.",
        ],
    }
    if include_inventory:
        handoff["portable_inventory"] = {
            root: _path_records(source_target_dir, _portable_files_under(source_target_dir, root))
            for root in PORTABLE_STATE_DIRS
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_markdown(handoff), encoding="utf-8")
    return {
        "schema": HANDOFF_SCHEMA,
        "source_target_dir": str(source_target_dir),
        "source_adapter": adapter,
        "handoff_file": str(out_path),
        "changed_paths": changed,
        "recommended_reads": reads,
        "next_steps": steps,
        "include_inventory": include_inventory,
        "default_handoff_dir": DEFAULT_HANDOFF_DIR,
        "session_brief_dir": DEFAULT_SESSION_BRIEF_DIR,
    }


def _load_manifest(target_dir):
    path = target_dir / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HandoffError(f"cannot read target manifest {path}: {exc}")
    except json.JSONDecodeError as exc:
        raise HandoffError(f"invalid target manifest {path}: {exc}")
    if not isinstance(manifest, dict):
        raise HandoffError(f"target manifest must be a mapping: {path}")
    return manifest


def _validated_manifest_adapter(manifest):
    adapter = manifest.get("adapter")
    if adapter not in SUPPORTED_ADAPTERS:
        raise HandoffError(f"source target adapter is unsupported: {adapter!r}")
    return adapter


def _manifest_character(manifest):
    character = manifest.get("character", {}) if isinstance(manifest, dict) else {}
    if not isinstance(character, dict):
        return {}
    return {
        key: character.get(key)
        for key in ("name", "slug", "relationship_continuity", "direct_emotional_interaction")
        if character.get(key) is not None
    }


def _default_reads(source_target_dir):
    return [rel_path for rel_path in DEFAULT_READS if (source_target_dir / rel_path).exists()]


def _normalize_paths(paths):
    normalized = []
    issues = []
    for raw_path in paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            issues.append("handoff paths must be non-empty relative strings")
            continue
        path = Path(raw_path.strip())
        if path.is_absolute() or ".." in path.parts:
            issues.append(f"handoff path must be relative and stay inside the target: {raw_path}")
            continue
        rel_path = path.as_posix()
        if rel_path not in normalized:
            normalized.append(rel_path)
    if issues:
        raise HandoffError("; ".join(issues))
    return normalized


def _path_records(source_target_dir, rel_paths):
    return [_path_record(source_target_dir, rel_path) for rel_path in rel_paths]


def _path_record(source_target_dir, rel_path):
    path = source_target_dir / rel_path
    record = {"path": rel_path}
    if path.is_file():
        data = path.read_bytes()
        record.update({
            "kind": "file",
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    elif path.is_dir():
        files = _portable_files_under(source_target_dir, rel_path)
        record.update({
            "kind": "directory",
            "file_count": len(files),
        })
    else:
        record["kind"] = "missing"
    return record


def _portable_files_under(source_target_dir, rel_root):
    root = source_target_dir / rel_root
    if not root.exists():
        return []
    if root.is_file():
        return [rel_root]
    if not root.is_dir():
        return []
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and _path_stays_in_root(path, source_target_dir):
            files.append(path.relative_to(source_target_dir).as_posix())
    return files


def _render_markdown(handoff):
    metadata = json.dumps(handoff, indent=2, sort_keys=True, ensure_ascii=False)
    changed = _render_path_list(handoff["changed_paths"])
    reads = _render_path_list(handoff["recommended_reads"])
    steps = _render_steps(handoff["next_steps"])
    summary = handoff["summary"] or "_Source agent has not written a human summary yet._"
    return (
        "# Packwright Handoff\n\n"
        "```json\n"
        f"{metadata}\n"
        "```\n\n"
        "## Summary\n\n"
        f"{summary}\n\n"
        "## Changed State\n\n"
        f"{changed}\n\n"
        "## Recommended Reads\n\n"
        f"{reads}\n\n"
        "## Next Steps\n\n"
        f"{steps}\n\n"
        "## Apply Policy\n\n"
        "- Use `workspace/shared/artifacts/handoffs/` for real cross-agent or cross-runtime handoffs.\n"
        "- Use `workspace/shared/artifacts/session-briefs/` for same-agent next-session briefs.\n"
        "- The receiving agent reads this file first and decides which referenced source files to inspect.\n"
        "- The receiving agent updates its own memory after review; do not blindly copy target files.\n"
    )


def _render_path_list(records):
    if not records:
        return "- No paths declared."
    lines = []
    for record in records:
        detail = record["kind"]
        if record["kind"] == "file":
            detail = f"file, sha256 `{record['sha256']}`"
        elif record["kind"] == "directory":
            detail = f"directory, {record['file_count']} files"
        lines.append(f"- `{record['path']}` ({detail})")
    return "\n".join(lines)


def _render_steps(steps):
    if not steps:
        return "- No next steps declared."
    return "\n".join(f"- {step}" for step in steps)


def _path_stays_in_root(path, root_dir):
    try:
        path.resolve().relative_to(root_dir.resolve())
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
'''
