from collections.abc import Mapping
from pathlib import Path

from .errors import PackwrightValidationError


def validate_relative_path(value, label="path"):
    """Return a normalized relative path or reject an unsafe path value."""
    if not isinstance(value, str) or not value.strip():
        raise PackwrightValidationError([f"{label} must be a non-empty relative path"])
    if "\x00" in value:
        raise PackwrightValidationError([f"{label} contains a null byte"])
    path = Path(value)
    if path.is_absolute() or path == Path(".") or ".." in path.parts:
        raise PackwrightValidationError([f"{label} must be relative and stay inside its root: {value}"])
    return path


def resolve_source_path(root, value, label="source path", require_file=True):
    """Resolve a readable path and require its final target to stay under root."""
    relative = validate_relative_path(value, label)
    resolved_root = Path(root).resolve()
    candidate = resolved_root / relative
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except FileNotFoundError:
        raise PackwrightValidationError([f"{label} does not exist: {value}"])
    except (OSError, ValueError):
        raise PackwrightValidationError([f"{label} escapes its root: {value}"])
    if require_file and not resolved.is_file():
        raise PackwrightValidationError([f"{label} is not a file: {value}"])
    return resolved


def resolve_destination_path(root, value, label="destination path"):
    """Resolve a write destination without allowing traversal through symlinks."""
    relative = validate_relative_path(value, label)
    resolved_root = Path(root).resolve()
    candidate = resolved_root / relative
    current = resolved_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PackwrightValidationError([f"{label} traverses a symlink: {value}"])
    try:
        candidate.resolve(strict=False).relative_to(resolved_root)
    except (OSError, ValueError):
        raise PackwrightValidationError([f"{label} escapes its root: {value}"])
    return candidate


def resolve_mechanism_file(mechanism, value, label="referenced file"):
    source = mechanism.get("source", {}) if isinstance(mechanism, Mapping) else {}
    base_dir = source.get("base_dir") if isinstance(source, Mapping) else None
    if not base_dir:
        raise PackwrightValidationError([f"{label} has no mechanism source root"])
    roots = [base_dir]
    fallback_roots = source.get("fallback_roots", []) if isinstance(source, Mapping) else []
    if isinstance(fallback_roots, list):
        roots.extend(root for root in fallback_roots if isinstance(root, str) and root)
    missing = []
    for root in roots:
        try:
            return resolve_source_path(root, value, label)
        except PackwrightValidationError as exc:
            if any("escapes its root" in issue or "must be relative" in issue for issue in exc.issues):
                raise
            missing.extend(exc.issues)
    raise PackwrightValidationError(missing[:1] or [f"{label} does not exist: {value}"])
