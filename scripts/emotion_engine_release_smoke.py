#!/usr/bin/env python3
"""Run the release-critical Packwright/Emotion Engine cross-repository smoke."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from packwright.adapters import (
    compile_to_claude_code_pack,
    compile_to_codex_pack,
    compile_to_cursor_pack,
)
from packwright.core import (
    doctor_target,
    install_pack,
    load_mechanism,
    migrate_emotion_engine_state,
    refresh_emotion_engine,
    resolve_mechanism,
)
from packwright.core.emotion_engine_contract import (
    EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH,
    EMOTION_ENGINE_MIGRATION_JOURNAL_PATH,
    EMOTION_ENGINE_REQUIRED_CAPABILITIES,
    EMOTION_ENGINE_RUNTIME_ROOT,
    EMOTION_ENGINE_STATE_PATH,
    EMOTION_ENGINE_UPSTREAM_COMMIT,
    EMOTION_ENGINE_VERSION,
)
from packwright.core.pack_metadata import LOCK_PATH


MECHANISM = ROOT / "examples" / "atlas-work" / "mechanism.yaml"


def write_pack(pack, destination):
    for rel_path, content in pack.items():
        path = destination / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def initialize_mcp(target, request_id=1):
    completed = subprocess.run(
        ["sh", str(target / "scripts" / "emotion_engine_mcp.sh")],
        cwd=str(target),
        input=json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {},
        }) + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    response = json.loads(completed.stdout)
    version = response.get("result", {}).get("serverInfo", {}).get("version")
    if version != EMOTION_ENGINE_VERSION:
        raise RuntimeError(f"unexpected Emotion Engine MCP version: {response}")


def run_shell_writer(target, command, *args):
    return subprocess.run(
        [str(target / "scripts" / "emotion_engine.sh"), command, *map(str, args)],
        cwd=str(target),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def run_lifecycle_writer(target, session_id):
    return subprocess.run(
        [sys.executable, str(target / "scripts" / "emotion_engine_lifecycle.py"), "codex"],
        cwd=str(target),
        input=json.dumps({
            "hook_event_name": "SessionStart",
            "session_id": session_id,
        }),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def run_mcp_requests(target, requests):
    completed = subprocess.run(
        ["sh", str(target / "scripts" / "emotion_engine_mcp.sh")],
        cwd=str(target),
        input="".join(json.dumps(request) + "\n" for request in requests),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    responses = [
        json.loads(line)
        for line in completed.stdout.splitlines()
        if line.strip()
    ]
    return completed, responses


def session_start_arguments(session_id, event_id):
    return {
        "session_id": session_id,
        "event_id": event_id,
        "character_id": "atlas",
        "relationship_id": "atlas:primary-user",
    }


def require_clean_doctor(target):
    report = doctor_target(target)
    if not report["ok"]:
        raise RuntimeError(json.dumps(report, indent=2, ensure_ascii=False))


def assert_pinned_checkout(source):
    completed = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("real Emotion Engine release smoke requires a git checkout")
    head = completed.stdout.strip()
    if head != EMOTION_ENGINE_UPSTREAM_COMMIT:
        raise RuntimeError(
            f"Emotion Engine checkout is {head}; expected pinned {EMOTION_ENGINE_UPSTREAM_COMMIT}"
        )


def smoke_fresh_adapters(root, source, resolved):
    compilers = {
        "codex": compile_to_codex_pack,
        "claude-code": compile_to_claude_code_pack,
        "cursor": compile_to_cursor_pack,
    }
    targets = {}
    for adapter, compiler in compilers.items():
        pack_dir = root / f"pack-{adapter}"
        target = root / f"target-{adapter}"
        write_pack(compiler(resolved), pack_dir)
        install_pack(
            pack_dir,
            target,
            include_emotion_engine=True,
            emotion_engine_source=source,
        )
        initialize_mcp(target)
        require_clean_doctor(target)
        targets[adapter] = (pack_dir, target)
    return targets


def smoke_managed_writer_fail_closed(target):
    state_path = target / EMOTION_ENGINE_STATE_PATH
    backup_path = Path(f"{state_path}.bak")
    original_state = state_path.read_bytes()
    original_backup = backup_path.read_bytes() if backup_path.is_file() else None

    def restore_original():
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_bytes(original_state)
        if original_backup is None:
            backup_path.unlink(missing_ok=True)
        else:
            backup_path.write_bytes(original_backup)

    try:
        state_path.unlink()
        backup_path.unlink(missing_ok=True)
        shell = run_shell_writer(
            target,
            "session_start",
            "--session-id", "missing-shell",
            "--event-id", "missing-shell-start",
            "--character-id", "atlas",
            "--relationship-id", "atlas:primary-user",
        )
        if shell.returncode == 0 or state_path.exists() or backup_path.exists():
            raise RuntimeError("managed shell recreated a missing primary state")
        lifecycle = run_lifecycle_writer(target, "missing-lifecycle")
        if lifecycle.returncode != 0 or state_path.exists() or backup_path.exists():
            raise RuntimeError("managed lifecycle recreated a missing primary state")
        mcp, responses = run_mcp_requests(target, [{
            "jsonrpc": "2.0",
            "id": "missing-mcp",
            "method": "tools/call",
            "params": {
                "name": "emotion_engine_session_start",
                "arguments": session_start_arguments("missing-mcp", "missing-mcp-start"),
            },
        }])
        if (
            not responses
            or "error" not in responses[0]
            or responses[0]["error"].get("code") != -32043
            or responses[0]["error"].get("data", {}).get("status") != "state_file_missing"
            or state_path.exists()
            or backup_path.exists()
        ):
            raise RuntimeError(
                "managed MCP recreated a missing primary state: "
                f"returncode={mcp.returncode}, responses={responses}, "
                f"state_exists={state_path.exists()}, backup_exists={backup_path.exists()}, "
                f"stderr={mcp.stderr!r}"
            )

        restore_original()
        corrupt = json.loads(state_path.read_text(encoding="utf-8"))
        corrupt["processed_event_ids"] = ["release-duplicate", "release-duplicate"]
        state_path.write_text(
            json.dumps(corrupt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        corrupt_bytes = state_path.read_bytes()
        backup_bytes = b'{"release-smoke":"keep"}\n'
        backup_path.write_bytes(backup_bytes)

        shell = run_shell_writer(
            target,
            "session_start",
            "--session-id", "corrupt-shell",
            "--event-id", "corrupt-shell-start",
            "--character-id", "atlas",
            "--relationship-id", "atlas:primary-user",
        )
        if shell.returncode == 0:
            raise RuntimeError("managed shell accepted hard-corrupt state")
        lifecycle = run_lifecycle_writer(target, "corrupt-lifecycle")
        if lifecycle.returncode != 0:
            raise RuntimeError(lifecycle.stderr or lifecycle.stdout)
        mcp, responses = run_mcp_requests(target, [{
            "jsonrpc": "2.0",
            "id": "corrupt-mcp",
            "method": "tools/call",
            "params": {
                "name": "emotion_engine_session_start",
                "arguments": session_start_arguments("corrupt-mcp", "corrupt-mcp-start"),
            },
        }])
        if not responses or "error" not in responses[0]:
            raise RuntimeError(
                "managed MCP accepted hard-corrupt state: "
                f"returncode={mcp.returncode}, responses={responses}, stderr={mcp.stderr!r}"
            )
        if state_path.read_bytes() != corrupt_bytes or backup_path.read_bytes() != backup_bytes:
            raise RuntimeError("hard-corrupt writer changed state or its backup")

        restore_original()
        started = run_shell_writer(
            target,
            "session_start",
            "--session-id", "semantic-warning",
            "--event-id", "semantic-warning-start",
            "--character-id", "atlas",
            "--relationship-id", "atlas:primary-user",
        )
        if started.returncode != 0:
            raise RuntimeError(started.stderr or started.stdout)
        warning_state = json.loads(state_path.read_text(encoding="utf-8"))
        warning_state["emotion_log"].append({
            "timestamp": warning_state["session_ledger"][-1]["opened_at"],
            "event_type": "turn",
            "session_id": "semantic-warning",
            "event_id": "semantic-warning-task",
            "subject": "task",
            "semantic_event_type": "work_checkpoint",
            "situation": "release smoke tests passed",
        })
        warning_state["session_ledger"][-1]["turn_count"] = 1
        state_path.write_text(
            json.dumps(warning_state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        warning_bytes = state_path.read_bytes()
        helper = target / EMOTION_ENGINE_RUNTIME_ROOT / "scripts" / "emotion_engine_utils.py"
        audit = subprocess.run(
            [
                sys.executable,
                str(helper),
                "--managed-runtime",
                "audit_state",
                str(state_path),
            ],
            cwd=str(target),
            text=True,
            capture_output=True,
            check=False,
        )
        audit_payload = json.loads(audit.stdout)
        if audit.returncode != 0 or audit_payload.get("ok") is not True or not audit_payload.get("semantic_warnings"):
            raise RuntimeError(
                "semantic-warning fixture is not a warning-only valid state: "
                f"returncode={audit.returncode}, payload={audit_payload}, stderr={audit.stderr!r}"
            )

        shell = run_shell_writer(
            target,
            "pre_turn_decay",
            "--session-id", "semantic-warning",
            "--event-id", "semantic-shell-decay",
            "--character-id", "atlas",
            "--relationship-id", "atlas:primary-user",
        )
        if shell.returncode != 0 or state_path.read_bytes() == warning_bytes:
            raise RuntimeError("semantic warnings incorrectly blocked the managed shell writer")
        state_path.write_bytes(warning_bytes)

        lifecycle = run_lifecycle_writer(target, "semantic-lifecycle")
        receipt_path = target / EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            lifecycle.returncode != 0
            or state_path.read_bytes() == warning_bytes
            or not receipt.get("operations")
            or receipt["operations"][-1].get("status") != "started"
        ):
            raise RuntimeError("semantic warnings incorrectly blocked the lifecycle writer")
        state_path.write_bytes(warning_bytes)

        mcp, responses = run_mcp_requests(target, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "emotion_engine_record_turn",
                    "arguments": {
                        **session_start_arguments("semantic-warning", "semantic-mcp-turn"),
                        "pleasure": 0.1,
                        "arousal": 0.3,
                        "dominance": 0.5,
                        "host_approved": True,
                    },
                },
            },
        ])
        if (
            mcp.returncode != 0
            or len(responses) != 2
            or "result" not in responses[1]
            or state_path.read_bytes() == warning_bytes
        ):
            raise RuntimeError("semantic warnings incorrectly blocked the managed MCP writer")
    finally:
        restore_original()
        (target / EMOTION_ENGINE_LIFECYCLE_RECEIPT_PATH).unlink(missing_ok=True)

    initialize_mcp(target, request_id=90)
    require_clean_doctor(target)


def smoke_capability_upgrade(source, target):
    state_path = target / EMOTION_ENGINE_STATE_PATH
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["capabilities"].remove("bounded_active_session/v1")
    state.pop("active_session_retention", None)
    state["release_smoke_extension"] = {"preserve": True}
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    incomplete_bytes = state_path.read_bytes()
    pause = subprocess.run(
        [str(target / "scripts" / "emotion_engine.sh"), "pause"],
        cwd=str(target),
        text=True,
        capture_output=True,
        check=False,
    )
    if pause.returncode == 0 or state_path.read_bytes() != incomplete_bytes:
        raise RuntimeError("ordinary writer implicitly upgraded incomplete v3 state")

    refresh_emotion_engine(target, emotion_engine_source=source)
    if state_path.read_bytes() != incomplete_bytes:
        raise RuntimeError("refresh changed incomplete v3 state before reviewed upgrade")
    preview = migrate_emotion_engine_state(target)
    if preview.get("status") != "upgrade_ready":
        raise RuntimeError(preview)
    applied = migrate_emotion_engine_state(target, apply=True)
    if applied.get("status") != "upgraded":
        raise RuntimeError(applied)
    upgraded = json.loads(state_path.read_text(encoding="utf-8"))
    if any(item not in upgraded.get("capabilities", []) for item in EMOTION_ENGINE_REQUIRED_CAPABILITIES):
        raise RuntimeError("reviewed upgrade did not install every required capability")
    if upgraded.get("release_smoke_extension") != {"preserve": True}:
        raise RuntimeError("reviewed upgrade lost a host extension")
    initialize_mcp(target, request_id=2)
    require_clean_doctor(target)


def smoke_crash_recovery(target):
    state_path = target / EMOTION_ENGINE_STATE_PATH
    state_before = state_path.read_bytes()
    manifest_path = target / "manifest.json"
    lock_path = target / LOCK_PATH
    backup = target / ".emotion-engine" / "backups" / "release-smoke-crash.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(state_before)
    journal_path = target / EMOTION_ENGINE_MIGRATION_JOURNAL_PATH
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        json.dumps({
            "schema": "packwright-emotion-migration-transaction/v1",
            "status": "in_progress",
            "phase": "apply_helper",
            "backup": backup.relative_to(target).as_posix(),
            "manifest_before": manifest_path.read_text(encoding="utf-8"),
            "lock_before": lock_path.read_text(encoding="utf-8"),
            "lineage_before": None,
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    state_path.write_text('{"_schema":"corrupt-after-crash"}\n', encoding="utf-8")
    migrate_emotion_engine_state(target)
    recovered = json.loads(journal_path.read_text(encoding="utf-8"))
    if recovered.get("status") != "rolled_back" or state_path.read_bytes() != state_before:
        raise RuntimeError("incomplete migration recovery did not restore state")


def smoke_v2_lineage(root, source, resolved):
    pack_dir = root / "pack-v2"
    target = root / "target-v2"
    write_pack(compile_to_codex_pack(resolved), pack_dir)
    legacy = target / ".emotion-engine" / "state.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        json.dumps({
            "_schema": "emotion-engine-state/v2",
            "enabled": True,
            "runtime_mode": "light",
            "boundary_state": {"last_boundary": "release-smoke"},
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    install_pack(
        pack_dir,
        target,
        include_emotion_engine=True,
        emotion_engine_source=source,
    )
    migrated = migrate_emotion_engine_state(target, apply=True)
    if migrated.get("status") != "migrated" or not migrated.get("lineage"):
        raise RuntimeError(migrated)
    initialize_mcp(target)
    pause = subprocess.run(
        [str(target / "scripts" / "emotion_engine.sh"), "pause"],
        cwd=str(target),
        text=True,
        capture_output=True,
        check=False,
    )
    if pause.returncode != 0:
        raise RuntimeError(pause.stderr or pause.stdout)
    retired = refresh_emotion_engine(
        target,
        emotion_engine_source=source,
        retire_legacy_state=True,
    )
    if not retired.get("retired_legacy_state") or legacy.exists():
        raise RuntimeError("persistent migration lineage did not authorize reviewed retirement")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("emotion_engine_source")
    args = parser.parse_args()
    source = Path(args.emotion_engine_source).resolve()
    assert_pinned_checkout(source)
    resolved = resolve_mechanism(load_mechanism(MECHANISM))
    with tempfile.TemporaryDirectory(prefix="packwright-real-emotion-") as tmpdir:
        root = Path(tmpdir)
        targets = smoke_fresh_adapters(root, source, resolved)
        codex_target = targets["codex"][1]
        smoke_managed_writer_fail_closed(codex_target)
        smoke_capability_upgrade(source, codex_target)
        smoke_crash_recovery(codex_target)
        smoke_v2_lineage(root, source, resolved)
    print("real Emotion Engine cross-repository smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
