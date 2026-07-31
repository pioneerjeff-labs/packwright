import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .automation_projection import automation_config_paths, managed_hook_fragment_digest
from .errors import PackwrightValidationError
from .path_safety import resolve_destination_path, resolve_source_path


ACTIVATION_STAMP_SCHEMA = "packwright-runtime-activation-stamp/v2"
ACTIVATION_RECEIPT_SCHEMA = "packwright-runtime-activation-receipt/v2"
ACTIVATION_STAMP_PATH = ".packwright/activation/codex-hooks.json"
_NATIVE_EVENTS = {
    "session_start": "SessionStart",
    "user_prompt": "UserPromptSubmit",
}


def verify_runtime_activation(target_dir, adapter=None):
    """Verify delivered Codex hook context and persist a digest-bound receipt."""
    target_dir = Path(target_dir)
    manifest = _load_manifest(target_dir)
    manifest_adapter = manifest.get("adapter")
    if adapter is not None and adapter != manifest_adapter:
        raise PackwrightValidationError(
            [f"target adapter is {manifest_adapter!r}, expected {adapter!r}"]
        )
    if manifest_adapter != "codex":
        raise PackwrightValidationError(
            ["runtime activation receipts are currently supported for the codex adapter"]
        )

    evidence = runtime_activation_evidence(target_dir, manifest, require_receipt=False)
    if not evidence["delivery_verified"]:
        return {
            "schema": ACTIVATION_RECEIPT_SCHEMA,
            "status": "verification_failed",
            "ok": False,
            "next_steps": [
                "run /hooks in Codex CLI and trust the Packwright SessionStart and UserPromptSubmit hooks",
                "start a new Codex session in this target and submit one prompt",
                "run packwright verify-activation again after Codex records the delivered developer context",
            ],
            **evidence,
        }

    receipt_path = _receipt_path(target_dir, evidence["activation_digest"])
    receipt = {
        "schema": ACTIVATION_RECEIPT_SCHEMA,
        "status": "verified",
        "ok": True,
        "adapter": "codex",
        "target_dir": str(target_dir.resolve()),
        "hook_digest": evidence["hook_digest"],
        "runner_digest": evidence["runner_digest"],
        "activation_digest": evidence["activation_digest"],
        "required_events": evidence["required_events"],
        "required_automations": evidence["required_automations"],
        "executed_events": evidence["executed_events"],
        "verified_events": evidence["verified_events"],
        "delivery_verified": True,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "stamp_path": ACTIVATION_STAMP_PATH,
        "receipt": str(receipt_path),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(receipt_path)
    return receipt


def runtime_activation_evidence(target_dir, manifest, require_receipt=True):
    """Return execution and transcript-delivery evidence for current Codex hooks."""
    target_dir = Path(target_dir)
    required_automations = _required_automations(manifest)
    required_events = sorted(required_automations)
    result = {
        "adapter": manifest.get("adapter") if isinstance(manifest, dict) else None,
        "target_dir": str(target_dir.resolve()),
        "hook_digest": None,
        "runner_digest": None,
        "activation_digest": None,
        "required_events": required_events,
        "required_automations": required_automations,
        "executed_events": [],
        "verified_events": [],
        "stamp_verified": False,
        "execution_verified": False,
        "delivery_verified": False,
        "receipt_verified": False,
        "reasons": [],
    }
    config_paths = sorted(automation_config_paths(manifest))
    if len(config_paths) != 1:
        result["reasons"].append("managed automation config is not uniquely declared")
        return result
    try:
        config_path = resolve_source_path(
            target_dir, config_paths[0], "installed automation configuration"
        )
        hook_digest = managed_hook_fragment_digest(
            config_path.read_text(encoding="utf-8")
        )
        runner_digest = _runner_digest(target_dir, manifest)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        result["reasons"].append(f"cannot read current managed Codex runtime: {exc}")
        return result
    activation_digest = _activation_digest(hook_digest, runner_digest)
    result["hook_digest"] = hook_digest
    result["runner_digest"] = runner_digest
    result["activation_digest"] = activation_digest

    stamp = _read_json(target_dir / ACTIVATION_STAMP_PATH)
    if not _valid_evidence_document(
        stamp,
        schema=ACTIVATION_STAMP_SCHEMA,
        target_dir=target_dir,
        hook_digest=hook_digest,
        runner_digest=runner_digest,
        activation_digest=None,
    ):
        result["reasons"].append(
            "no activation stamp matches the current target, managed hook digest, and runner digest; "
            "run /hooks in Codex CLI, trust changed hooks if requested, start a new session, "
            "submit one prompt, then run packwright verify-activation"
        )
        return result

    events = stamp.get("events", {})
    executed_events = sorted(
        event
        for event in required_events
        if _valid_event_execution(
            events.get(event),
            event=event,
            required_automations=required_automations[event],
        )
    )
    result["executed_events"] = executed_events
    missing_execution = sorted(set(required_events) - set(executed_events))
    if missing_execution:
        result["reasons"].append(
            "live hook execution evidence is missing event(s): "
            + ", ".join(missing_execution)
            + "; start a new Codex session and submit one prompt"
        )
        return result
    result["stamp_verified"] = True
    result["execution_verified"] = True

    delivery_failures = []
    verified_events = []
    for event in required_events:
        delivered, reason = _verify_event_delivery(events[event])
        if delivered:
            verified_events.append(event)
        else:
            delivery_failures.append(f"{event}: {reason}")
    result["verified_events"] = sorted(verified_events)
    if delivery_failures:
        result["reasons"].append(
            "hooks executed, but complete developer-context delivery was not verified: "
            + "; ".join(delivery_failures)
        )
        return result
    result["delivery_verified"] = True
    if not require_receipt:
        result["reasons"] = []
        return result

    receipt_path = _receipt_path(target_dir, activation_digest)
    receipt = _read_json(receipt_path)
    if not _valid_evidence_document(
        receipt,
        schema=ACTIVATION_RECEIPT_SCHEMA,
        target_dir=target_dir,
        hook_digest=hook_digest,
        runner_digest=runner_digest,
        activation_digest=activation_digest,
    ):
        result["reasons"].append(
            "complete hook context was delivered, but packwright verify-activation has not "
            "verified the current hook and runner digests"
        )
        return result
    if sorted(receipt.get("required_events", [])) != required_events:
        result["reasons"].append(
            "activation receipt does not cover the currently required events"
        )
        return result
    if receipt.get("required_automations") != required_automations:
        result["reasons"].append(
            "activation receipt does not cover the currently required automations"
        )
        return result
    receipt_events = receipt.get("verified_events", [])
    if (
        receipt.get("status") != "verified"
        or receipt.get("ok") is not True
        or receipt.get("delivery_verified") is not True
        or not isinstance(receipt_events, list)
        or not set(required_events).issubset(receipt_events)
    ):
        result["reasons"].append(
            "activation receipt does not verify delivery for every currently required event"
        )
        return result
    result["receipt_verified"] = True
    result["reasons"] = []
    result["receipt"] = str(receipt_path)
    return result


def _valid_event_execution(record, event, required_automations):
    if not isinstance(record, dict):
        return False
    return (
        isinstance(record.get("executed_at"), str)
        and isinstance(record.get("context_bytes"), int)
        and record["context_bytes"] > 0
        and _is_sha256(record.get("context_sha256"))
        and isinstance(record.get("delivery_marker"), str)
        and record["delivery_marker"].startswith("[packwright:delivery:")
        and record["delivery_marker"].endswith("]")
        and isinstance(record.get("automation_ids"), list)
        and set(required_automations).issubset(record["automation_ids"])
        and record.get("native_event") == _NATIVE_EVENTS.get(event)
        and isinstance(record.get("session_id"), str)
        and bool(record["session_id"])
        and (record.get("transcript_path") is None or isinstance(record["transcript_path"], str))
    )


def _verify_event_delivery(record):
    transcript_path = record.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        return False, "Codex did not provide a transcript_path for this hook run"
    try:
        path = Path(transcript_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return False, "the recorded Codex transcript does not exist"
    if path.suffix != ".jsonl":
        return False, "the recorded transcript is not a JSONL file"
    if not any(_path_is_within(path, root) for root in _codex_session_roots()):
        return False, "the recorded transcript is outside the active Codex sessions directory"
    marker = record["delivery_marker"]
    expected_hash = record["context_sha256"]
    try:
        found_marker = False
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for candidate in _developer_context_candidates(item):
                    if marker not in candidate:
                        continue
                    found_marker = True
                    if hashlib.sha256(candidate.encode("utf-8")).hexdigest() == expected_hash:
                        return True, None
    except (OSError, UnicodeError):
        return False, "the recorded Codex transcript could not be read"
    if found_marker:
        return False, "the developer message contains only a changed, truncated, or spilled payload"
    return False, "no matching developer message is present in the recorded transcript"


def _developer_context_candidates(value):
    if isinstance(value, dict):
        if value.get("role") == "developer" and "content" in value:
            strings = list(_nested_strings(value["content"]))
            yield from strings
            if len(strings) > 1:
                yield "".join(strings)
        for item in value.values():
            yield from _developer_context_candidates(item)
    elif isinstance(value, list):
        for item in value:
            yield from _developer_context_candidates(item)


def _nested_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        if isinstance(value.get("text"), str):
            yield value["text"]
        else:
            for item in value.values():
                yield from _nested_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _nested_strings(item)


def _codex_session_roots():
    roots = []
    configured = os.environ.get("CODEX_HOME")
    if configured:
        roots.append(Path(configured).expanduser() / "sessions")
    roots.append(Path.home() / ".codex" / "sessions")
    resolved = []
    for root in roots:
        try:
            candidate = root.resolve()
        except (OSError, RuntimeError):
            continue
        if candidate not in resolved:
            resolved.append(candidate)
    return resolved


def _path_is_within(path, root):
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _runner_digest(target_dir, manifest):
    feature = manifest.get("features", {}).get("automations", {})
    runner = feature.get("runner", {}) if isinstance(feature, dict) else {}
    runner_path = runner.get("path") if isinstance(runner, dict) else None
    if not isinstance(runner_path, str) or not runner_path:
        raise ValueError("managed automation runner is not uniquely declared")
    path = resolve_source_path(target_dir, runner_path, "installed automation runner")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _activation_digest(hook_digest, runner_digest):
    return hashlib.sha256(f"{hook_digest}:{runner_digest}".encode("ascii")).hexdigest()


def _is_sha256(value):
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _required_automations(manifest):
    feature = manifest.get("features", {}).get("automations", {})
    records = feature.get("records", []) if isinstance(feature, dict) else []
    required = {}
    for record in records:
        if (
            not isinstance(record, dict)
            or record.get("status") != "projected_pending_user_review"
            or not isinstance(record.get("canonical_event"), str)
            or not isinstance(record.get("id"), str)
        ):
            continue
        required.setdefault(record["canonical_event"], []).append(record["id"])
    return {
        event: sorted(set(automation_ids))
        for event, automation_ids in sorted(required.items())
    }


def _receipt_path(target_dir, activation_digest):
    return resolve_destination_path(
        target_dir,
        f".packwright/receipts/activation-codex-{activation_digest[:12]}.json",
        "runtime activation receipt",
    )


def _valid_evidence_document(
    data,
    schema,
    target_dir,
    hook_digest,
    runner_digest,
    activation_digest,
):
    valid = (
        isinstance(data, dict)
        and data.get("schema") == schema
        and data.get("adapter") == "codex"
        and data.get("target_dir") == str(target_dir.resolve())
        and data.get("hook_digest") == hook_digest
        and data.get("runner_digest") == runner_digest
    )
    if activation_digest is not None:
        valid = valid and data.get("activation_digest") == activation_digest
    return valid


def _read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _load_manifest(target_dir):
    try:
        manifest_path = resolve_source_path(
            target_dir, "manifest.json", "installed adapter manifest"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackwrightValidationError(
            [f"cannot read installed adapter manifest: {exc}"]
        ) from exc
    if not isinstance(manifest, dict):
        raise PackwrightValidationError(
            ["installed adapter manifest must be a JSON object"]
        )
    return manifest
