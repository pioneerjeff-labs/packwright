import json
import shlex

from .emotion_engine_contract import (
    EMOTION_ENGINE_LIFECYCLE_PATH,
    EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH,
    EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH,
    EMOTION_ENGINE_MCP_LAUNCHER_PATH,
    EMOTION_ENGINE_PROJECTION_PENDING_PATH,
    EMOTION_ENGINE_PROJECTION_RECEIPT_PATH,
    EMOTION_ENGINE_RUNTIME_ROOT,
    EMOTION_ENGINE_STATE_PATH,
    EMOTION_ENGINE_TARGET_LOCK_PATH,
    EMOTION_ENGINE_VERSION,
)
from .path_safety import resolve_destination_path


EMOTION_ENGINE_LIFECYCLE_MARKER = "emotion_engine_lifecycle.py"


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
LIFECYCLE_RECEIPT_REL = "__LIFECYCLE_RECEIPT_PATH__"


def project_root():
    return Path(__file__).resolve().parent.parent


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


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
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


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
    if (root / PENDING_REL).exists():
        return 0
    manifest = read_json(root / "manifest.json")
    state_file = root / STATE_REL
    helper = root / HELPER_REL
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

    lock_path = root / LOCK_REL
    with lifecycle_lock(lock_path):
        if (root / PENDING_REL).exists():
            return 0
        projection = read_json(root / PROJECTION_REL)
        if (
            projection is None
            or projection.get("projection_nonce") != feature.get("projection_nonce")
            or projection.get("source_digest") != feature.get("source_digest")
            or projection.get("files", {}).get(HELPER_REL) != hashlib.sha256(helper.read_bytes()).hexdigest()
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
        write_receipt(root / LIFECYCLE_RECEIPT_REL, receipt)
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
import subprocess
import sys
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
STATE_REL = "__STATE_PATH__"
MCP_REL = "__RUNTIME_ROOT__/scripts/emotion_engine_mcp.py"
HELPER_REL = "__RUNTIME_ROOT__/scripts/emotion_engine_utils.py"
LAUNCHER_REL = "__MCP_LAUNCHER_PATH__"
WRAPPER_REL = "scripts/emotion_engine_mcp.sh"
LIFECYCLE_REL = "scripts/emotion_engine_lifecycle.py"
PENDING_REL = "__PENDING_PATH__"
PROJECTION_REL = "__PROJECTION_PATH__"
ACTIVATION_REL = "__MCP_ACTIVATION_PATH__"
LOCK_REL = "__LOCK_PATH__"
ACTIVATION_SCHEMA = "packwright-emotion-mcp-activation/v1"


def project_root():
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "manifest.json").is_file():
            return candidate
    return Path.cwd()


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


def write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


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


def projection_ready(root, expected_nonce, expected_digest):
    if (root / PENDING_REL).exists():
        return False, "projection_pending"
    receipt = read_json(root / PROJECTION_REL)
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
    for rel_path in (HELPER_REL, MCP_REL, LAUNCHER_REL, WRAPPER_REL, LIFECYCLE_REL):
        if files.get(rel_path) != sha256(root / rel_path):
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


def write_activation(root, projection, child_pid):
    state = read_json(root / STATE_REL) or {}
    write_json_atomic(
        root / ACTIVATION_REL,
        {
            "schema": ACTIVATION_SCHEMA,
            "engine_version": ENGINE_VERSION,
            "projection_nonce": projection["projection_nonce"],
            "source_digest": projection["source_digest"],
            "runtime_root": "__RUNTIME_ROOT__",
            "state_path": STATE_REL,
            "state_schema": state.get("_schema"),
            "helper_sha256": sha256(root / HELPER_REL),
            "mcp_sha256": sha256(root / MCP_REL),
            "launcher_sha256": sha256(root / LAUNCHER_REL),
            "pid": os.getpid(),
            "child_pid": child_pid,
            "initialized_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def main():
    root = project_root()
    initial = read_json(root / PROJECTION_REL)
    if initial is None:
        return 2
    nonce = initial.get("projection_nonce")
    source_digest = initial.get("source_digest")
    ready, _ = projection_ready(root, nonce, source_digest)
    if not ready:
        return 3
    child = subprocess.Popen(
        [sys.executable, str(root / MCP_REL), "--state", str(root / STATE_REL)],
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
            with target_lock(root / LOCK_REL):
                ready, reason = projection_ready(root, nonce, source_digest)
                if not ready:
                    emit_error(request_id, reason)
                    return 4
                child.stdin.write(line if line.endswith("\n") else line + "\n")
                child.stdin.flush()
                if request_id is None:
                    continue
                response_line = child.stdout.readline()
                if not response_line:
                    return child.poll() or 5
                if request.get("method") == "initialize":
                    try:
                        response = json.loads(response_line)
                        version = response.get("result", {}).get("serverInfo", {}).get("version")
                    except (json.JSONDecodeError, AttributeError):
                        version = None
                    if version != ENGINE_VERSION:
                        sys.stdout.write(response_line)
                        sys.stdout.flush()
                        return 6
                    write_activation(root, initial, child.pid)
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
        .replace("__STATE_PATH__", EMOTION_ENGINE_STATE_PATH)
        .replace("__RUNTIME_ROOT__", EMOTION_ENGINE_RUNTIME_ROOT)
        .replace("__MCP_LAUNCHER_PATH__", EMOTION_ENGINE_MCP_LAUNCHER_PATH)
        .replace("__PENDING_PATH__", EMOTION_ENGINE_PROJECTION_PENDING_PATH)
        .replace("__PROJECTION_PATH__", EMOTION_ENGINE_PROJECTION_RECEIPT_PATH)
        .replace("__MCP_ACTIVATION_PATH__", EMOTION_ENGINE_MCP_ACTIVATION_RECEIPT_PATH)
        .replace("__LOCK_PATH__", EMOTION_ENGINE_TARGET_LOCK_PATH)
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
