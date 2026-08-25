import json
import shlex

from .emotion_engine_contract import EMOTION_ENGINE_LIFECYCLE_PATH
from .path_safety import resolve_destination_path


EMOTION_ENGINE_LIFECYCLE_MARKER = "emotion_engine_lifecycle.py"


def render_emotion_engine_lifecycle():
    """Render the source-independent host lifecycle bridge.

    The bridge never edits Emotion Engine state directly. It only forwards a
    host-native SessionStart after checking the installed v3 capability and
    bound identity, and it serializes deferred close/start transitions.
    """
    return r'''#!/usr/bin/env python3
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
    manifest = read_json(root / "manifest.json")
    state_file = root / ".emotion-engine" / "state.json"
    helper = root / ".packwright" / "runtime" / "emotion-engine" / "scripts" / "emotion_engine_utils.py"
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

    lock_path = root / ".emotion-engine" / "packwright-lifecycle.lock"
    with lifecycle_lock(lock_path):
        state = read_json(state_file)
        if (
            state is None
            or state.get("_schema") != STATE_SCHEMA
            or SESSION_CAPABILITY not in state.get("capabilities", [])
            or state.get("enabled") is not True
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
            "operations": operations,
        }
        write_receipt(
            root / ".packwright" / "activation" / "emotion-engine-lifecycle.json",
            receipt,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


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
