import json
import shlex

from .emotion_engine_contract import (
    EMOTION_ENGINE_GENERATION,
    EMOTION_ENGINE_LIFECYCLE_PATH,
    EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH,
    EMOTION_ENGINE_LEGACY_WRITER_FENCE_PATH,
    EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH,
    EMOTION_ENGINE_MCP_LAUNCHER_PATH,
    EMOTION_ENGINE_MIGRATION_JOURNAL_PATH,
    EMOTION_ENGINE_PROJECTION_PENDING_PATH,
    EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
    EMOTION_ENGINE_REQUIRED_CAPABILITIES,
    EMOTION_ENGINE_RUNTIME_ROOT,
    EMOTION_ENGINE_STATE_PATH,
    EMOTION_ENGINE_TARGET_LOCK_PATH,
    EMOTION_ENGINE_VERSION,
    EMOTION_ENGINE_WRITER_GATEWAY_PATH,
)
from .path_safety import resolve_destination_path


EMOTION_ENGINE_LIFECYCLE_MARKER = "emotion_engine_lifecycle.py"


def render_emotion_engine_writer_gateway():
    """Render the fixed-state, target-locked shell writer gateway."""
    template = r'''#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - Unix fallback
    msvcrt = None

ENGINE_VERSION = "__ENGINE_VERSION__"
WRITER_GENERATION = "__WRITER_GENERATION__"
STATE_REL = "__STATE_PATH__"
HELPER_REL = "__RUNTIME_ROOT__/scripts/emotion_engine_utils.py"
GATEWAY_REL = "__GATEWAY_PATH__"
WRAPPER_REL = "scripts/emotion_engine.sh"
PENDING_REL = "__PENDING_PATH__"
PROJECTION_REL = "__PROJECTION_PATH__"
ACTIVATION_REL = "__MCP_ACTIVATION_PATH__"
LOCK_REL = "__LOCK_PATH__"
MIGRATION_JOURNAL_REL = "__MIGRATION_JOURNAL_PATH__"
LEGACY_WRITER_FENCE_REL = "__LEGACY_WRITER_FENCE_PATH__"
ARTIFACT_LOCK_REL = ".packwright/lock.json"
MANIFEST_REL = "manifest.json"
BLOCKED_COMMANDS = {"init", "bind_identity", "migrate_state", "upgrade_state", "reset"}


def project_root():
    for candidate in Path(__file__).resolve().parents:
        if (candidate / MANIFEST_REL).is_file():
            return candidate
    return Path.cwd()


def safe_path(root, rel_path):
    root = root.resolve()
    relative = Path(rel_path)
    if relative.is_absolute() or relative == Path(".") or ".." in relative.parts:
        raise ValueError(f"unsafe managed path: {rel_path}")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"managed path traverses a symlink: {rel_path}")
    current.resolve(strict=False).relative_to(root)
    return current


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def sha256(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def baseline_excluded(rel_path):
    return (
        rel_path == ARTIFACT_LOCK_REL
        or rel_path == ".emotion-engine"
        or rel_path.startswith(".emotion-engine/")
        or any(
            rel_path == root or rel_path.startswith(root + "/")
            for root in ("memory", "workspace", "knowledge", "sources", "skills")
        )
    )


def entry_has_marker(value):
    if isinstance(value, dict):
        return any(entry_has_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(entry_has_marker(item) for item in value)
    return isinstance(value, str) and "packwright_automation.py" in value


def artifact_digest(path, record):
    if isinstance(record, dict):
        if record.get("mode") in {"managed_text_block", "managed_mcp_config"}:
            return sha256(path)
        if record.get("mode") != "managed_json_hooks":
            return None
        data = read_json(path)
        if data is None:
            return None
        hooks = data.get("hooks", {})
        if not isinstance(hooks, dict):
            return None
        fragment = {
            event: [entry for entry in entries if entry_has_marker(entry)]
            for event, entries in sorted(hooks.items())
            if isinstance(entries, list) and any(entry_has_marker(entry) for entry in entries)
        }
        payload = json.dumps(fragment, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    return sha256(path)


def write_bytes_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_json_atomic(path, value):
    write_bytes_atomic(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


@contextmanager
def target_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows fallback
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:  # pragma: no cover - Windows fallback
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


def migration_fuse(root):
    try:
        path = safe_path(root, MIGRATION_JOURNAL_REL)
    except (OSError, ValueError):
        return False, "migration_journal_unsafe"
    if not path.is_file():
        return True, None
    journal = read_json(path)
    if journal is None:
        return False, "migration_journal_invalid"
    if journal.get("status") == "in_progress":
        return False, "migration_in_progress"
    return True, None


def artifact_lock_current(root):
    try:
        manifest_path = safe_path(root, MANIFEST_REL)
        lock_path = safe_path(root, ARTIFACT_LOCK_REL)
    except (OSError, ValueError):
        return False
    lock = read_json(lock_path)
    manifest = read_json(manifest_path)
    if (
        lock is None
        or lock.get("schema") != "packwright-lock/v1"
        or not isinstance(lock.get("artifacts"), dict)
        or manifest is None
        or not isinstance(manifest.get("artifacts"), list)
    ):
        return False
    locked = lock["artifacts"]
    expected_paths = {
        rel_path
        for rel_path in manifest["artifacts"]
        if isinstance(rel_path, str) and not baseline_excluded(rel_path)
    }
    expected_paths.add(MANIFEST_REL)
    if any(rel_path not in locked for rel_path in expected_paths):
        return False
    for rel_path, record in locked.items():
        if not isinstance(rel_path, str) or baseline_excluded(rel_path):
            continue
        expected = record.get("sha256") if isinstance(record, dict) else record
        if not isinstance(expected, str):
            return False
        try:
            path = safe_path(root, rel_path)
        except (OSError, ValueError):
            return False
        if artifact_digest(path, record) != expected:
            return False
    return True


def projection_ready(root):
    try:
        if safe_path(root, LEGACY_WRITER_FENCE_REL).exists():
            return False, "legacy_writer_disabled"
    except (OSError, ValueError):
        return False, "legacy_writer_fence_unsafe"
    fuse_ready, fuse_reason = migration_fuse(root)
    if not fuse_ready:
        return False, fuse_reason
    try:
        pending_path = safe_path(root, PENDING_REL)
        manifest_path = safe_path(root, MANIFEST_REL)
        projection_path = safe_path(root, PROJECTION_REL)
    except (OSError, ValueError):
        return False, "writer_path_unsafe"
    if pending_path.exists():
        return False, "projection_pending"
    if not artifact_lock_current(root):
        return False, "manifest_lock_drift"
    manifest = read_json(manifest_path)
    receipt = read_json(projection_path)
    if manifest is None or receipt is None:
        return False, "projection_receipt_missing"
    feature = manifest.get("features", {}).get("emotion_engine", {})
    sidecar = manifest.get("sidecars", {}).get("emotion-engine", {})
    if (
        not isinstance(feature, dict)
        or not isinstance(sidecar, dict)
        or feature.get("installed") is not True
        or feature.get("version") != ENGINE_VERSION
        or feature.get("writer_generation") != WRITER_GENERATION
        or sidecar.get("writer_generation") != WRITER_GENERATION
        or sidecar.get("state_file") != STATE_REL
        or receipt.get("engine_version") != ENGINE_VERSION
        or receipt.get("writer_generation") != WRITER_GENERATION
        or receipt.get("projection_nonce") != feature.get("projection_nonce")
        or receipt.get("source_digest") != feature.get("source_digest")
    ):
        return False, "projection_cohort_changed"
    files = receipt.get("files")
    if not isinstance(files, dict):
        return False, "projection_receipt_invalid"
    for rel_path in (HELPER_REL, GATEWAY_REL, WRAPPER_REL):
        try:
            candidate = safe_path(root, rel_path)
        except (OSError, ValueError):
            return False, "writer_path_unsafe"
        if files.get(rel_path) != sha256(candidate):
            return False, "writer_cohort_drift"
    return True, None


def activation_receipt_current(root, feature):
    try:
        receipt = read_json(safe_path(root, ACTIVATION_REL))
    except (OSError, ValueError):
        return False
    return bool(
        isinstance(receipt, dict)
        and receipt.get("schema") == "packwright-emotion-mcp-activation/v1"
        and receipt.get("engine_version") == ENGINE_VERSION
        and receipt.get("projection_nonce") == feature.get("projection_nonce")
        and receipt.get("source_digest") == feature.get("source_digest")
    )


def sync_mode_manifest(root, state):
    manifest_path = safe_path(root, MANIFEST_REL)
    lock_path = safe_path(root, ARTIFACT_LOCK_REL)
    manifest_before = manifest_path.read_bytes()
    if not lock_path.is_file():
        raise ValueError("Packwright artifact lock is missing")
    lock_before = lock_path.read_bytes()
    try:
        artifact_lock = json.loads(lock_before)
        if (
            not isinstance(artifact_lock, dict)
            or artifact_lock.get("schema") != "packwright-lock/v1"
            or not isinstance(artifact_lock.get("artifacts"), dict)
            or artifact_lock["artifacts"].get(MANIFEST_REL) != hashlib.sha256(manifest_before).hexdigest()
        ):
            raise ValueError("manifest changed outside the Packwright artifact lock")
        manifest = json.loads(manifest_before)
        feature = manifest["features"]["emotion_engine"]
        sidecar = manifest["sidecars"]["emotion-engine"]
        mode = state.get("runtime_mode")
        enabled = state.get("enabled") is True
        if mode not in {"light", "always", "paused"} or enabled is (mode == "paused"):
            raise ValueError("helper returned inconsistent runtime mode")
        live = activation_receipt_current(root, feature)
        activation = {
            "installed": True,
            "configured": True,
            "active": bool(live and enabled),
            "verified": bool(live),
            "status": (
                "client_restart_required"
                if not live
                else ("paused" if mode == "paused" else "ready")
            ),
        }
        feature["mode"] = mode
        sidecar["mode"] = mode
        manifest.setdefault("boundaries", {})["emotion_engine_mode"] = mode
        feature["activation"] = dict(activation)
        sidecar["activation"] = dict(activation)
        if live:
            feature["mcp_status"] = "active"
            sidecar["mcp_status"] = "active"
        write_json_atomic(manifest_path, manifest)
        artifact_lock["artifacts"][MANIFEST_REL] = sha256(manifest_path)
        write_json_atomic(lock_path, artifact_lock)
    except Exception:
        write_bytes_atomic(manifest_path, manifest_before)
        write_bytes_atomic(lock_path, lock_before)
        raise


def main():
    if len(sys.argv) < 2:
        print("usage: emotion_engine.sh <command> [args...]", file=sys.stderr)
        return 2
    command = sys.argv[1]
    if command in BLOCKED_COMMANDS:
        print(
            f"{command} is owned by the Packwright state transaction; use packwright instead",
            file=sys.stderr,
        )
        return 64
    root = project_root()
    try:
        lock_path = safe_path(root, LOCK_REL)
    except (OSError, ValueError) as exc:
        print(f"Emotion Engine writer path is unsafe: {exc}", file=sys.stderr)
        return 75
    with target_lock(lock_path):
        ready, reason = projection_ready(root)
        if not ready:
            print(
                f"Emotion Engine writer cohort is unavailable ({reason}); run packwright doctor/refresh",
                file=sys.stderr,
            )
            return 75
        try:
            state_path = safe_path(root, STATE_REL)
            helper_path = safe_path(root, HELPER_REL)
        except (OSError, ValueError) as exc:
            print(f"Emotion Engine writer path is unsafe: {exc}", file=sys.stderr)
            return 75
        state_before = state_path.read_bytes() if state_path.is_file() else None
        completed = subprocess.run(
            [
                sys.executable,
                str(helper_path),
                "--managed-runtime",
                command,
                str(state_path),
                *sys.argv[2:],
            ],
            cwd=str(root),
            check=False,
            capture_output=True,
        )
        if completed.returncode == 0 and command in {"pause", "resume"}:
            state = read_json(state_path)
            try:
                if state is None:
                    raise ValueError("helper did not leave valid state")
                sync_mode_manifest(root, state)
            except Exception as exc:
                if state_before is not None:
                    write_bytes_atomic(state_path, state_before)
                print(f"Packwright mode transaction rolled back: {exc}", file=sys.stderr)
                return 70
        sys.stdout.buffer.write(completed.stdout)
        sys.stdout.buffer.flush()
        sys.stderr.buffer.write(completed.stderr)
        sys.stderr.buffer.flush()
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
'''
    return (
        template.replace("__ENGINE_VERSION__", EMOTION_ENGINE_VERSION)
        .replace("__WRITER_GENERATION__", EMOTION_ENGINE_GENERATION)
        .replace("__STATE_PATH__", EMOTION_ENGINE_STATE_PATH)
        .replace("__RUNTIME_ROOT__", EMOTION_ENGINE_RUNTIME_ROOT)
        .replace("__GATEWAY_PATH__", EMOTION_ENGINE_WRITER_GATEWAY_PATH)
        .replace("__PENDING_PATH__", EMOTION_ENGINE_PROJECTION_PENDING_PATH)
        .replace("__PROJECTION_PATH__", EMOTION_ENGINE_PROJECTION_RECEIPT_PATH)
        .replace("__MCP_ACTIVATION_PATH__", EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH)
        .replace("__LOCK_PATH__", EMOTION_ENGINE_TARGET_LOCK_PATH)
        .replace("__MIGRATION_JOURNAL_PATH__", EMOTION_ENGINE_MIGRATION_JOURNAL_PATH)
        .replace("__LEGACY_WRITER_FENCE_PATH__", EMOTION_ENGINE_LEGACY_WRITER_FENCE_PATH)
    )


def render_emotion_engine_lifecycle():
    """Render the source-independent host lifecycle bridge.

    The bridge never edits Emotion Engine state directly. It only forwards a
    host-native SessionStart after checking the installed v3 capability and
    bound identity, and it serializes deferred close/start transitions.
    """
    template = r'''#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - Unix fallback
    msvcrt = None

STATE_SCHEMA = "emotion-engine-state/v3"
SESSION_CAPABILITY = "session_idempotency/v1"
RECEIPT_SCHEMA = "packwright-emotion-lifecycle/v1"
STATE_REL = "__STATE_PATH__"
HELPER_REL = "__RUNTIME_ROOT__/scripts/emotion_engine_utils.py"
PENDING_REL = "__PENDING_PATH__"
PROJECTION_REL = "__PROJECTION_PATH__"
LOCK_REL = "__LOCK_PATH__"
MIGRATION_JOURNAL_REL = "__MIGRATION_JOURNAL_PATH__"
LEGACY_WRITER_FENCE_REL = "__LEGACY_WRITER_FENCE_PATH__"
ARTIFACT_LOCK_REL = ".packwright/lock.json"
MANIFEST_REL = "manifest.json"
LIFECYCLE_RECEIPT_REL = "__LIFECYCLE_RECEIPT_PATH__"


def project_root():
    return Path(__file__).resolve().parent.parent


def safe_path(root, rel_path):
    root = root.resolve()
    relative = Path(rel_path)
    if relative.is_absolute() or relative == Path(".") or ".." in relative.parts:
        raise ValueError(f"unsafe managed path: {rel_path}")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"managed path traverses a symlink: {rel_path}")
    current.resolve(strict=False).relative_to(root)
    return current


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def file_sha256(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def baseline_excluded(rel_path):
    return (
        rel_path == ARTIFACT_LOCK_REL
        or rel_path == ".emotion-engine"
        or rel_path.startswith(".emotion-engine/")
        or any(
            rel_path == root or rel_path.startswith(root + "/")
            for root in ("memory", "workspace", "knowledge", "sources", "skills")
        )
    )


def entry_has_marker(value):
    if isinstance(value, dict):
        return any(entry_has_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(entry_has_marker(item) for item in value)
    return isinstance(value, str) and "packwright_automation.py" in value


def artifact_digest(path, record):
    if isinstance(record, dict):
        if record.get("mode") in {"managed_text_block", "managed_mcp_config"}:
            return file_sha256(path)
        if record.get("mode") != "managed_json_hooks":
            return None
        data = read_json(path)
        if data is None:
            return None
        hooks = data.get("hooks", {})
        if not isinstance(hooks, dict):
            return None
        fragment = {
            event: [entry for entry in entries if entry_has_marker(entry)]
            for event, entries in sorted(hooks.items())
            if isinstance(entries, list) and any(entry_has_marker(entry) for entry in entries)
        }
        payload = json.dumps(fragment, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    return file_sha256(path)


def artifact_lock_current(root):
    try:
        manifest_path = safe_path(root, MANIFEST_REL)
        lock_path = safe_path(root, ARTIFACT_LOCK_REL)
    except (OSError, ValueError):
        return False
    lock = read_json(lock_path)
    manifest = read_json(manifest_path)
    if (
        lock is None
        or lock.get("schema") != "packwright-lock/v1"
        or not isinstance(lock.get("artifacts"), dict)
        or manifest is None
        or not isinstance(manifest.get("artifacts"), list)
    ):
        return False
    locked = lock["artifacts"]
    expected_paths = {
        rel_path
        for rel_path in manifest["artifacts"]
        if isinstance(rel_path, str) and not baseline_excluded(rel_path)
    }
    expected_paths.add(MANIFEST_REL)
    if any(rel_path not in locked for rel_path in expected_paths):
        return False
    for rel_path, record in locked.items():
        if not isinstance(rel_path, str) or baseline_excluded(rel_path):
            continue
        expected = record.get("sha256") if isinstance(record, dict) else record
        if not isinstance(expected, str):
            return False
        try:
            path = safe_path(root, rel_path)
        except (OSError, ValueError):
            return False
        if artifact_digest(path, record) != expected:
            return False
    return True


def writer_ready(root):
    try:
        journal_path = safe_path(root, MIGRATION_JOURNAL_REL)
        legacy_writer_fence = safe_path(root, LEGACY_WRITER_FENCE_REL)
        pending_path = safe_path(root, PENDING_REL)
    except (OSError, ValueError):
        return False
    if legacy_writer_fence.exists():
        return False
    if pending_path.exists():
        return False
    if journal_path.is_file():
        journal = read_json(journal_path)
        if journal is None or journal.get("status") == "in_progress":
            return False
    return artifact_lock_current(root)


def read_hook_input():
    if sys.stdin.isatty():
        return {}
    try:
        value = json.loads(sys.stdin.read())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


@contextmanager
def lifecycle_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows fallback
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:  # pragma: no cover - Windows fallback
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


def run_helper(helper, command, state_file, identity, session_id, event_id):
    completed = subprocess.run(
        [
            sys.executable,
            str(helper),
            "--managed-runtime",
            command,
            str(state_file),
            "--session-id",
            session_id,
            "--event-id",
            event_id,
            "--character-id",
            identity["character_id"],
            "--relationship-id",
            identity["relationship_id"],
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"status": "invalid_helper_output"}
    payload["returncode"] = completed.returncode
    return payload


def write_receipt(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main():
    adapter = sys.argv[1] if len(sys.argv) > 1 else ""
    hook_input = read_hook_input()
    native_event = hook_input.get("hook_event_name")
    session_id = hook_input.get("session_id")
    if adapter != "codex" or native_event != "SessionStart":
        return 0
    if not isinstance(session_id, str) or not session_id.strip() or len(session_id.strip()) > 160:
        return 0
    session_id = session_id.strip()

    root = project_root()
    if not writer_ready(root):
        return 0
    try:
        manifest_path = safe_path(root, MANIFEST_REL)
        state_file = safe_path(root, STATE_REL)
        helper = safe_path(root, HELPER_REL)
        lock_path = safe_path(root, LOCK_REL)
        projection_path = safe_path(root, PROJECTION_REL)
        lifecycle_receipt_path = safe_path(root, LIFECYCLE_RECEIPT_REL)
    except (OSError, ValueError):
        return 0
    manifest = read_json(manifest_path)
    if manifest is None or not helper.is_file() or not state_file.is_file():
        return 0
    feature = manifest.get("features", {}).get("emotion_engine", {})
    sidecar = manifest.get("sidecars", {}).get("emotion-engine", {})
    identity = sidecar.get("identity", {}) if isinstance(sidecar, dict) else {}
    if (
        not isinstance(feature, dict)
        or feature.get("installed") is not True
        or SESSION_CAPABILITY not in feature.get("required_capabilities", [])
        or not isinstance(identity, dict)
        or not isinstance(identity.get("character_id"), str)
        or not isinstance(identity.get("relationship_id"), str)
    ):
        return 0

    with lifecycle_lock(lock_path):
        if not writer_ready(root):
            return 0
        projection = read_json(projection_path)
        if (
            projection is None
            or projection.get("projection_nonce") != feature.get("projection_nonce")
            or projection.get("source_digest") != feature.get("source_digest")
            or projection.get("files", {}).get(HELPER_REL) != file_sha256(helper)
        ):
            return 0
        state = read_json(state_file)
        if (
            state is None
            or state.get("_schema") != STATE_SCHEMA
            or SESSION_CAPABILITY not in state.get("capabilities", [])
            or state.get("enabled") is not True
            or state.get("runtime_mode") != feature.get("mode")
            or state.get("identity", {}).get("status") != "bound"
            or state.get("identity", {}).get("character_id") != identity["character_id"]
            or state.get("identity", {}).get("relationship_id") != identity["relationship_id"]
        ):
            return 0

        incoming_record = next(
            (
                item for item in state.get("session_ledger", [])
                if isinstance(item, dict) and item.get("session_id") == session_id
            ),
            None,
        )
        if incoming_record and incoming_record.get("status") in {"closed", "settled"}:
            return 0

        native_event_id = hook_input.get("event_id")
        event_id_source = "native"
        if (
            not isinstance(native_event_id, str)
            or not native_event_id.strip()
            or len(native_event_id.strip()) > 160
        ):
            native_event_id = None
            event_id_source = "derived_from_native_event_and_session"
        else:
            native_event_id = native_event_id.strip()
        start_event_id = native_event_id or (
            f"packwright:{adapter}:{native_event}:"
            + hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        )
        operations = []
        active_session_id = state.get("session", {}).get("active_session_id")
        if isinstance(active_session_id, str) and active_session_id and active_session_id != session_id:
            transition = f"{active_session_id}\0{session_id}".encode("utf-8")
            close_event_id = (
                f"packwright:{adapter}:deferred-session-end:"
                + hashlib.sha256(transition).hexdigest()
            )
            closed = run_helper(
                helper,
                "session_end",
                state_file,
                identity,
                active_session_id,
                close_event_id,
            )
            operations.append({"command": "session_end", **closed})
            if closed.get("returncode") != 0 or closed.get("status") not in {"closed", "already_closed"}:
                return 0

        started = run_helper(
            helper,
            "session_start",
            state_file,
            identity,
            session_id,
            start_event_id,
        )
        operations.append({"command": "session_start", **started})
        if started.get("returncode") != 0 or started.get("status") not in {
            "started", "already_active", "duplicate_event"
        }:
            return 0

        current = read_json(state_file)
        if (
            current is None
            or current.get("session", {}).get("status") != "active"
            or current.get("session", {}).get("active_session_id") != session_id
        ):
            return 0

        receipt = {
            "schema": RECEIPT_SCHEMA,
            "adapter": adapter,
            "native_event": native_event,
            "native_event_id": native_event_id,
            "native_session_id": session_id,
            "native_source": (
                hook_input.get("source")[:80]
                if isinstance(hook_input.get("source"), str)
                else None
            ),
            "event_id": start_event_id,
            "event_id_source": event_id_source,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "helper_sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
            "source_digest": feature.get("source_digest"),
            "projection_nonce": feature.get("projection_nonce"),
            "operations": operations,
        }
        write_receipt(lifecycle_receipt_path, receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    return (
        template.replace("__STATE_PATH__", EMOTION_ENGINE_STATE_PATH)
        .replace("__RUNTIME_ROOT__", EMOTION_ENGINE_RUNTIME_ROOT)
        .replace("__PENDING_PATH__", EMOTION_ENGINE_PROJECTION_PENDING_PATH)
        .replace("__PROJECTION_PATH__", EMOTION_ENGINE_PROJECTION_RECEIPT_PATH)
        .replace("__LOCK_PATH__", EMOTION_ENGINE_TARGET_LOCK_PATH)
        .replace("__MIGRATION_JOURNAL_PATH__", EMOTION_ENGINE_MIGRATION_JOURNAL_PATH)
        .replace("__LEGACY_WRITER_FENCE_PATH__", EMOTION_ENGINE_LEGACY_WRITER_FENCE_PATH)
        .replace("__LIFECYCLE_RECEIPT_PATH__", EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH)
    )


def render_emotion_engine_mcp_launcher():
    """Render a cohort-aware stdio proxy around the pinned MCP server.

    Each request is serialized with Packwright refresh/migration operations.
    A process whose projection nonce is stale refuses to forward writes, and a
    successful initialize response produces the live cohort activation receipt.
    """
    template = r'''#!/usr/bin/env python3
import hashlib
import json
import os
import select
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - Unix fallback
    msvcrt = None

ENGINE_VERSION = "__ENGINE_VERSION__"
WRITER_GENERATION = "__WRITER_GENERATION__"
STATE_SCHEMA = "emotion-engine-state/v3"
LEGACY_STATE_SCHEMA = "emotion-engine-state/v2"
REQUIRED_CAPABILITIES = __REQUIRED_CAPABILITIES__
STATE_REL = "__STATE_PATH__"
MCP_REL = "__RUNTIME_ROOT__/scripts/emotion_engine_mcp.py"
HELPER_REL = "__RUNTIME_ROOT__/scripts/emotion_engine_utils.py"
GATEWAY_REL = "__GATEWAY_PATH__"
LAUNCHER_REL = "__MCP_LAUNCHER_PATH__"
WRAPPER_REL = "scripts/emotion_engine_mcp.sh"
LIFECYCLE_REL = "scripts/emotion_engine_lifecycle.py"
PENDING_REL = "__PENDING_PATH__"
PROJECTION_REL = "__PROJECTION_PATH__"
ACTIVATION_REL = "__MCP_ACTIVATION_PATH__"
LOCK_REL = "__LOCK_PATH__"
MIGRATION_JOURNAL_REL = "__MIGRATION_JOURNAL_PATH__"
LEGACY_WRITER_FENCE_REL = "__LEGACY_WRITER_FENCE_PATH__"
MANIFEST_REL = "manifest.json"
ARTIFACT_LOCK_REL = ".packwright/lock.json"
ACTIVATION_SCHEMA = "packwright-emotion-mcp-activation/v1"
MANAGED_RUNTIME_BLOCKED_TOOLS = {
    "emotion_engine_bind_identity",
    "emotion_engine_migrate_state",
}


def project_root():
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "manifest.json").is_file():
            return candidate
    return Path.cwd()


def safe_path(root, rel_path):
    root = root.resolve()
    relative = Path(rel_path)
    if relative.is_absolute() or relative == Path(".") or ".." in relative.parts:
        raise ValueError(f"unsafe managed path: {rel_path}")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"managed path traverses a symlink: {rel_path}")
    current.resolve(strict=False).relative_to(root)
    return current


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def sha256(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def baseline_excluded(rel_path):
    return (
        rel_path == ARTIFACT_LOCK_REL
        or rel_path == ".emotion-engine"
        or rel_path.startswith(".emotion-engine/")
        or any(
            rel_path == root or rel_path.startswith(root + "/")
            for root in ("memory", "workspace", "knowledge", "sources", "skills")
        )
    )


def entry_has_marker(value):
    if isinstance(value, dict):
        return any(entry_has_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(entry_has_marker(item) for item in value)
    return isinstance(value, str) and "packwright_automation.py" in value


def artifact_digest(path, record):
    if isinstance(record, dict):
        if record.get("mode") in {"managed_text_block", "managed_mcp_config"}:
            return sha256(path)
        if record.get("mode") != "managed_json_hooks":
            return None
        data = read_json(path)
        if data is None:
            return None
        hooks = data.get("hooks", {})
        if not isinstance(hooks, dict):
            return None
        fragment = {
            event: [entry for entry in entries if entry_has_marker(entry)]
            for event, entries in sorted(hooks.items())
            if isinstance(entries, list) and any(entry_has_marker(entry) for entry in entries)
        }
        payload = json.dumps(fragment, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    return sha256(path)


def write_json_atomic(path, value):
    write_bytes_atomic(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def write_bytes_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def target_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows fallback
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:  # pragma: no cover - Windows fallback
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


def migration_fuse(root):
    try:
        path = safe_path(root, MIGRATION_JOURNAL_REL)
    except (OSError, ValueError):
        return False, "migration_journal_unsafe"
    if not path.is_file():
        return True, None
    journal = read_json(path)
    if journal is None:
        return False, "migration_journal_invalid"
    if journal.get("status") == "in_progress":
        return False, "migration_in_progress"
    return True, None


def artifact_lock_current(root):
    try:
        manifest_path = safe_path(root, MANIFEST_REL)
        lock_path = safe_path(root, ARTIFACT_LOCK_REL)
    except (OSError, ValueError):
        return False
    lock = read_json(lock_path)
    manifest = read_json(manifest_path)
    if (
        lock is None
        or lock.get("schema") != "packwright-lock/v1"
        or not isinstance(lock.get("artifacts"), dict)
        or manifest is None
        or not isinstance(manifest.get("artifacts"), list)
    ):
        return False
    locked = lock["artifacts"]
    expected_paths = {
        rel_path
        for rel_path in manifest["artifacts"]
        if isinstance(rel_path, str) and not baseline_excluded(rel_path)
    }
    expected_paths.add(MANIFEST_REL)
    if any(rel_path not in locked for rel_path in expected_paths):
        return False
    for rel_path, record in locked.items():
        if not isinstance(rel_path, str) or baseline_excluded(rel_path):
            continue
        expected = record.get("sha256") if isinstance(record, dict) else record
        if not isinstance(expected, str):
            return False
        try:
            path = safe_path(root, rel_path)
        except (OSError, ValueError):
            return False
        if artifact_digest(path, record) != expected:
            return False
    return True


def projection_ready(root, expected_nonce, expected_digest):
    try:
        if safe_path(root, LEGACY_WRITER_FENCE_REL).exists():
            return False, "legacy_writer_disabled"
    except (OSError, ValueError):
        return False, "legacy_writer_fence_unsafe"
    fuse_ready, fuse_reason = migration_fuse(root)
    if not fuse_ready:
        return False, fuse_reason
    try:
        pending_path = safe_path(root, PENDING_REL)
        projection_path = safe_path(root, PROJECTION_REL)
    except (OSError, ValueError):
        return False, "writer_path_unsafe"
    if pending_path.exists():
        return False, "projection_pending"
    if not artifact_lock_current(root):
        return False, "manifest_lock_drift"
    receipt = read_json(projection_path)
    if (
        receipt is None
        or receipt.get("engine_version") != ENGINE_VERSION
        or receipt.get("projection_nonce") != expected_nonce
        or receipt.get("source_digest") != expected_digest
    ):
        return False, "projection_cohort_changed"
    files = receipt.get("files")
    if not isinstance(files, dict):
        return False, "projection_receipt_invalid"
    for rel_path in (HELPER_REL, MCP_REL, GATEWAY_REL, LAUNCHER_REL, WRAPPER_REL, LIFECYCLE_REL):
        try:
            candidate = safe_path(root, rel_path)
        except (OSError, ValueError):
            return False, "writer_path_unsafe"
        if files.get(rel_path) != sha256(candidate):
            return False, "writer_cohort_drift"
    return True, None


def emit_error(request_id, reason):
    if request_id is None:
        return
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32041,
            "message": "Emotion Engine writer cohort is not active; restart the MCP client",
            "data": {"reason": reason},
        },
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def emit_policy_error(request_id, code, message):
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def request_policy_issue(request):
    if request.get("jsonrpc") != "2.0":
        return -32600, "request must declare jsonrpc 2.0"
    method = request.get("method")
    if not isinstance(method, str) or not method:
        return -32600, "request method must be a non-empty string"
    request_id = request.get("id")
    if request_id is None and not method.startswith("notifications/"):
        return -32600, "MCP requests require a non-null id"
    params = request.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return -32602, "request params must be an object"
    if method != "tools/call":
        return None
    if request_id is None:
        return -32600, "tools/call requires a non-null request id"
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return -32602, "tool arguments must be an object"
    if "state_file" in arguments:
        return -32602, "state_file is fixed by Packwright and cannot be overridden"
    if params.get("name") in MANAGED_RUNTIME_BLOCKED_TOOLS:
        return -32601, "tool is disabled in the Packwright managed runtime; use the Packwright transaction"
    return None


def read_child_response(child, timeout_seconds=30):
    readable, _, _ = select.select([child.stdout], [], [], timeout_seconds)
    if not readable:
        return None
    return child.stdout.readline()


def run_helper_check(root, command):
    helper = safe_path(root, HELPER_REL)
    state_file = safe_path(root, STATE_REL)
    completed = subprocess.run(
        [
            sys.executable,
            str(helper),
            "--managed-runtime",
            command,
            str(state_file),
        ],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"status": "invalid_helper_output"}
    if not isinstance(payload, dict):
        payload = {"status": "invalid_helper_output"}
    payload["returncode"] = completed.returncode
    return payload


def verify_state_for_activation(root):
    state_path = safe_path(root, STATE_REL)
    before_hash = sha256(state_path)
    activation_check = run_helper_check(root, "activation_check")
    audit = run_helper_check(root, "audit_state")
    if (
        activation_check.get("returncode") != 0
        or activation_check.get("status") != "ready"
        or audit.get("returncode") != 0
        or audit.get("ok") is not True
        or before_hash is None
        or sha256(state_path) != before_hash
    ):
        return None
    return {
        "state_sha256": before_hash,
        "activation_check": activation_check,
        "audit_state": audit,
    }


def activation_for_state(state, feature, sidecar):
    schema = state.get("_schema")
    capabilities = state.get("capabilities")
    identity = state.get("identity")
    if schema == LEGACY_STATE_SCHEMA:
        status = "migration_required"
        active = verified = False
    elif schema != STATE_SCHEMA:
        status = "verification_failed"
        active = verified = False
    elif not isinstance(capabilities, list) or any(
        capability not in capabilities for capability in REQUIRED_CAPABILITIES
    ):
        status = "capability_upgrade_required"
        active = verified = False
    elif (
        state.get("runtime_mode") != feature.get("mode")
        or state.get("enabled") is (feature.get("mode") == "paused")
    ):
        status = "mode_mismatch"
        active = verified = False
    elif (
        not isinstance(identity, dict)
        or identity.get("status") != "bound"
        or identity.get("character_id") != sidecar.get("identity", {}).get("character_id")
        or identity.get("relationship_id") != sidecar.get("identity", {}).get("relationship_id")
    ):
        status = "identity_mismatch"
        active = verified = False
    else:
        verified = True
        active = state.get("enabled") is True
        status = "ready" if active else "paused"
    return {
        "installed": True,
        "configured": True,
        "active": active,
        "verified": verified,
        "status": status,
    }


def write_activation(root, projection, child_pid, verification):
    state_path = safe_path(root, STATE_REL)
    state = read_json(state_path) or {}
    manifest_path = safe_path(root, MANIFEST_REL)
    lock_path = safe_path(root, ARTIFACT_LOCK_REL)
    activation_path = safe_path(root, ACTIVATION_REL)
    snapshots = {
        path: path.read_bytes() if path.is_file() else None
        for path in (activation_path, manifest_path, lock_path)
    }
    try:
        if sha256(state_path) != verification.get("state_sha256"):
            raise ValueError("state changed after activation verification")
        if not lock_path.is_file():
            raise ValueError("Packwright artifact lock is missing during MCP activation")
        artifact_lock = read_json(lock_path)
        if (
            artifact_lock is None
            or artifact_lock.get("schema") != "packwright-lock/v1"
            or not isinstance(artifact_lock.get("artifacts"), dict)
            or artifact_lock["artifacts"].get(MANIFEST_REL) != sha256(manifest_path)
        ):
            raise ValueError("manifest changed outside the Packwright artifact lock")
        write_json_atomic(
            activation_path,
            {
            "schema": ACTIVATION_SCHEMA,
            "engine_version": ENGINE_VERSION,
            "projection_nonce": projection["projection_nonce"],
            "source_digest": projection["source_digest"],
            "runtime_root": "__RUNTIME_ROOT__",
            "state_path": STATE_REL,
            "state_schema": state.get("_schema"),
            "state_sha256": verification["state_sha256"],
            "activation_check_status": verification["activation_check"].get("status"),
            "audit_ok": verification["audit_state"].get("ok") is True,
            "helper_sha256": sha256(safe_path(root, HELPER_REL)),
            "mcp_sha256": sha256(safe_path(root, MCP_REL)),
            "launcher_sha256": sha256(safe_path(root, LAUNCHER_REL)),
            "legacy_writer_fence_supported": True,
            "pid": os.getpid(),
            "child_pid": child_pid,
            "initialized_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        manifest = read_json(manifest_path)
        if manifest is None:
            raise ValueError("manifest is unavailable during MCP activation")
        feature = manifest.get("features", {}).get("emotion_engine", {})
        sidecar = manifest.get("sidecars", {}).get("emotion-engine", {})
        if (
            not isinstance(feature, dict)
            or not isinstance(sidecar, dict)
            or feature.get("projection_nonce") != projection.get("projection_nonce")
            or sidecar.get("projection_nonce") != projection.get("projection_nonce")
            or feature.get("writer_generation") != WRITER_GENERATION
            or sidecar.get("writer_generation") != WRITER_GENERATION
        ):
            raise ValueError("manifest writer cohort changed during MCP activation")
        activation = activation_for_state(state, feature, sidecar)
        feature["activation"] = dict(activation)
        sidecar["activation"] = dict(activation)
        feature["mcp_status"] = "active"
        sidecar["mcp_status"] = "active"
        write_json_atomic(manifest_path, manifest)
        artifact_lock["artifacts"][MANIFEST_REL] = sha256(manifest_path)
        write_json_atomic(lock_path, artifact_lock)
    except Exception:
        for path, content in snapshots.items():
            if content is None:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            else:
                write_bytes_atomic(path, content)
        raise


def main():
    root = project_root()
    try:
        projection_path = safe_path(root, PROJECTION_REL)
        lock_path = safe_path(root, LOCK_REL)
        mcp_path = safe_path(root, MCP_REL)
        state_path = safe_path(root, STATE_REL)
    except (OSError, ValueError):
        return 2
    initial = read_json(projection_path)
    if initial is None:
        return 2
    nonce = initial.get("projection_nonce")
    source_digest = initial.get("source_digest")
    child = subprocess.Popen(
        [
            sys.executable,
            str(mcp_path),
            "--state",
            str(state_path),
            "--locked-state",
            "--managed-runtime",
        ],
        cwd=str(root),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(request, dict):
                emit_error(None, "batch_requests_unsupported")
                continue
            request_id = request.get("id")
            policy_issue = request_policy_issue(request)
            if policy_issue is not None:
                emit_policy_error(request_id, *policy_issue)
                continue
            with target_lock(lock_path):
                ready, reason = projection_ready(root, nonce, source_digest)
                if not ready:
                    emit_error(request_id, reason)
                    return 4
                child.stdin.write(line if line.endswith("\n") else line + "\n")
                child.stdin.flush()
                if request_id is None:
                    continue
                response_line = read_child_response(child)
                if not response_line:
                    return child.poll() or 5
                try:
                    response = json.loads(response_line)
                except json.JSONDecodeError:
                    emit_error(request_id, "invalid_child_response")
                    return 8
                if (
                    not isinstance(response, dict)
                    or response.get("jsonrpc") != "2.0"
                    or response.get("id") != request_id
                ):
                    emit_error(request_id, "child_response_id_mismatch")
                    return 8
                if request.get("method") == "initialize":
                    try:
                        version = response.get("result", {}).get("serverInfo", {}).get("version")
                    except AttributeError:
                        version = None
                    if version != ENGINE_VERSION:
                        sys.stdout.write(response_line)
                        sys.stdout.flush()
                        return 6
                    try:
                        verification = verify_state_for_activation(root)
                        if verification is None:
                            emit_error(request_id, "activation_state_verification_failed")
                            return 7
                        write_activation(root, initial, child.pid, verification)
                    except Exception:
                        emit_error(request_id, "activation_manifest_commit_failed")
                        return 7
                sys.stdout.write(response_line)
                sys.stdout.flush()
    finally:
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    return (
        template.replace("__ENGINE_VERSION__", EMOTION_ENGINE_VERSION)
        .replace("__WRITER_GENERATION__", EMOTION_ENGINE_GENERATION)
        .replace("__REQUIRED_CAPABILITIES__", json.dumps(list(EMOTION_ENGINE_REQUIRED_CAPABILITIES)))
        .replace("__STATE_PATH__", EMOTION_ENGINE_STATE_PATH)
        .replace("__RUNTIME_ROOT__", EMOTION_ENGINE_RUNTIME_ROOT)
        .replace("__GATEWAY_PATH__", EMOTION_ENGINE_WRITER_GATEWAY_PATH)
        .replace("__MCP_LAUNCHER_PATH__", EMOTION_ENGINE_MCP_LAUNCHER_PATH)
        .replace("__PENDING_PATH__", EMOTION_ENGINE_PROJECTION_PENDING_PATH)
        .replace("__PROJECTION_PATH__", EMOTION_ENGINE_PROJECTION_RECEIPT_PATH)
        .replace("__MCP_ACTIVATION_PATH__", EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH)
        .replace("__LOCK_PATH__", EMOTION_ENGINE_TARGET_LOCK_PATH)
        .replace("__MIGRATION_JOURNAL_PATH__", EMOTION_ENGINE_MIGRATION_JOURNAL_PATH)
        .replace("__LEGACY_WRITER_FENCE_PATH__", EMOTION_ENGINE_LEGACY_WRITER_FENCE_PATH)
    )


def prepare_codex_lifecycle_config(target_dir):
    path = target_dir / ".codex" / "hooks.json"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    absolute = resolve_destination_path(
        target_dir,
        EMOTION_ENGINE_LIFECYCLE_PATH,
        "Emotion Engine lifecycle bridge",
    )
    command = f"python3 {shlex.quote(str(absolute))} codex"
    desired = {
        "matcher": "startup|resume|clear|compact",
        "hooks": [{"type": "command", "command": command}],
    }
    data = json.loads(existing) if existing.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("Codex hook configuration root must be an object")
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Codex hook configuration hooks must be an object")
    entries = hooks.setdefault("SessionStart", [])
    if not isinstance(entries, list):
        raise ValueError("Codex hook configuration hooks.SessionStart must be a list")
    preserved = [entry for entry in entries if not _has_marker(entry)]
    hooks["SessionStart"] = preserved + [desired]
    data.setdefault("description", "Packwright-managed local hooks.")
    return {
        "path": ".codex/hooks.json",
        "destination": path,
        "entry": desired,
        "rendered": json.dumps(data, indent=2, sort_keys=True) + "\n",
    }


def codex_lifecycle_config_issue(target_dir):
    path = target_dir / ".codex" / "hooks.json"
    if not path.is_file():
        return "Emotion Engine Codex lifecycle hook configuration is missing"
    try:
        expected = prepare_codex_lifecycle_config(target_dir)["entry"]
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("hooks", {}).get("SessionStart", [])
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, AttributeError):
        return "Emotion Engine Codex lifecycle hook configuration is invalid"
    managed = [entry for entry in entries if _has_marker(entry)]
    if managed != [expected]:
        return "Emotion Engine Codex lifecycle hook differs from the expected native SessionStart bridge"
    return None


def _has_marker(value):
    if isinstance(value, dict):
        return any(_has_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_marker(item) for item in value)
    return isinstance(value, str) and EMOTION_ENGINE_LIFECYCLE_MARKER in value
