import json
from datetime import datetime, timezone
from pathlib import Path

from .automation_projection import automation_config_paths, managed_hook_fragment_digest
from .errors import PackwrightValidationError
from .path_safety import resolve_destination_path, resolve_source_path


ACTIVATION_STAMP_SCHEMA = "packwright-runtime-activation-stamp/v1"
ACTIVATION_RECEIPT_SCHEMA = "packwright-runtime-activation-receipt/v1"
ACTIVATION_STAMP_PATH = ".packwright/activation/codex-hooks.json"


def verify_runtime_activation(target_dir, adapter=None):
    """Verify live Codex hook evidence and persist a digest-bound activation receipt."""
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
    if not evidence["stamp_verified"]:
        return {
            "schema": ACTIVATION_RECEIPT_SCHEMA,
            "status": "verification_failed",
            "ok": False,
            "next_steps": [
                "run /hooks in Codex CLI and trust the Packwright SessionStart and UserPromptSubmit hooks",
                "start a new Codex session in this target and submit one prompt",
                "run packwright verify-activation again",
            ],
            **evidence,
        }

    receipt_path = _receipt_path(target_dir, evidence["hook_digest"])
    receipt = {
        "schema": ACTIVATION_RECEIPT_SCHEMA,
        "status": "verified",
        "ok": True,
        "adapter": "codex",
        "target_dir": str(target_dir.resolve()),
        "hook_digest": evidence["hook_digest"],
        "required_events": evidence["required_events"],
        "required_automations": evidence["required_automations"],
        "verified_events": evidence["verified_events"],
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
    """Return activation evidence for the current managed hook fragment."""
    target_dir = Path(target_dir)
    required_automations = _required_automations(manifest)
    required_events = sorted(required_automations)
    result = {
        "adapter": manifest.get("adapter") if isinstance(manifest, dict) else None,
        "target_dir": str(target_dir.resolve()),
        "hook_digest": None,
        "required_events": required_events,
        "required_automations": required_automations,
        "verified_events": [],
        "stamp_verified": False,
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
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        result["reasons"].append(f"cannot read current managed hook fragment: {exc}")
        return result
    result["hook_digest"] = hook_digest

    stamp = _read_json(target_dir / ACTIVATION_STAMP_PATH)
    if not _valid_evidence_document(
        stamp,
        schema=ACTIVATION_STAMP_SCHEMA,
        target_dir=target_dir,
        hook_digest=hook_digest,
    ):
        result["reasons"].append(
            "no activation stamp matches the current target and managed hook digest; "
            "run /hooks in Codex CLI, trust the Packwright hooks, start a new session, "
            "submit one prompt, then run packwright verify-activation"
        )
        return result
    events = stamp.get("events", {})
    verified_events = sorted(
        event
        for event in required_events
        if isinstance(events.get(event), dict)
        and isinstance(events[event].get("executed_at"), str)
        and isinstance(events[event].get("context_bytes"), int)
        and isinstance(events[event].get("automation_ids"), list)
        and set(required_automations[event]).issubset(
            events[event]["automation_ids"]
        )
    )
    result["verified_events"] = verified_events
    missing = sorted(set(required_events) - set(verified_events))
    if missing:
        result["reasons"].append(
            "live hook evidence is missing event(s): "
            + ", ".join(missing)
            + "; start a new Codex session and submit one prompt"
        )
        return result
    result["stamp_verified"] = True
    if not require_receipt:
        result["reasons"] = []
        return result

    receipt_path = _receipt_path(target_dir, hook_digest)
    receipt = _read_json(receipt_path)
    if not _valid_evidence_document(
        receipt,
        schema=ACTIVATION_RECEIPT_SCHEMA,
        target_dir=target_dir,
        hook_digest=hook_digest,
    ):
        result["reasons"].append(
            "live hooks ran, but packwright verify-activation has not verified the current digest"
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
        or not isinstance(receipt_events, list)
        or not set(required_events).issubset(receipt_events)
    ):
        result["reasons"].append(
            "activation receipt does not verify every currently required event"
        )
        return result
    result["receipt_verified"] = True
    result["reasons"] = []
    result["receipt"] = str(receipt_path)
    return result


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


def _receipt_path(target_dir, hook_digest):
    return resolve_destination_path(
        target_dir,
        f".packwright/receipts/activation-codex-{hook_digest[:12]}.json",
        "runtime activation receipt",
    )


def _valid_evidence_document(data, schema, target_dir, hook_digest):
    return (
        isinstance(data, dict)
        and data.get("schema") == schema
        and data.get("adapter") == "codex"
        and data.get("target_dir") == str(target_dir.resolve())
        and data.get("hook_digest") == hook_digest
    )


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
