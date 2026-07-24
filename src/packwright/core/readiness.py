from pathlib import Path

import yaml


READINESS_SCHEMA = "packwright-readiness/v1"
ADOPTION_REVIEW_SCHEMA = "packwright-adoption-review/v1"
ADOPTION_REVIEW_DIR = "workspace/shared/artifacts/migrations"


def score_readiness(structural_passed):
    """Describe what a mechanism score does and does not prove."""
    structural_status = "passed" if structural_passed else "failed"
    return {
        "schema": READINESS_SCHEMA,
        "status": "not_evaluated",
        "operational_ready": None,
        "layers": {
            "structural_integrity": {
                "status": structural_status,
                "message": "canonical mechanism and generated adapter artifacts were scored",
            },
            "portable_state_integrity": {
                "status": "not_evaluated",
                "message": "score does not inspect a live target's portable state",
            },
            "runtime_activation": {
                "status": "not_evaluated",
                "message": "score does not verify runtime trust, reloads, hooks, or extensions",
            },
            "environment_bindings": {
                "status": "not_evaluated",
                "message": "score does not verify MCP, plugin, schedule, account, or secret bindings",
            },
            "workflow_acceptance": {
                "status": "not_evaluated",
                "message": "score does not run user workflow acceptance checks",
            },
        },
        "message": (
            "structural score passed; operational readiness was not evaluated"
            if structural_passed
            else "structural score failed; operational readiness was not evaluated"
        ),
    }


def target_readiness(target_dir, manifest, structural_ok, issues, warnings):
    """Aggregate honest target readiness without changing legacy doctor semantics."""
    target_dir = Path(target_dir)
    structural = _structural_layer(structural_ok, issues)
    runtime = _runtime_activation_layer(manifest, warnings)
    workflow = _workflow_acceptance_layer(target_dir)
    layers = {
        "structural_integrity": structural,
        "portable_state_integrity": {
            "status": "not_evaluated",
            "message": (
                "doctor intentionally preserves portable memory and workspace state; "
                "content-level integrity needs a reviewed migration receipt"
            ),
        },
        "runtime_activation": runtime,
        "environment_bindings": {
            "status": "not_evaluated",
            "message": (
                "the current manifest does not declare MCP, plugin, schedule, account, "
                "or secret bindings"
            ),
        },
        "workflow_acceptance": workflow,
    }
    attention = [
        {
            "layer": layer_id,
            "reason": reason,
        }
        for layer_id, layer in layers.items()
        if layer["status"] in {"failed", "attention_required"}
        for reason in layer.get("reasons", [layer.get("message", "attention required")])
    ]
    operational_ready = False if attention else None
    status = "attention_required" if attention else "not_evaluated"
    return {
        "schema": READINESS_SCHEMA,
        "status": status,
        "operational_ready": operational_ready,
        "layers": layers,
        "attention": attention,
        "message": (
            "managed structure was checked, but runtime or workflow attention is still required"
            if attention
            else "managed structure was checked; operational readiness remains unverified"
        ),
    }


def _structural_layer(structural_ok, issues):
    if structural_ok:
        return {
            "status": "passed",
            "message": "managed projection layout and artifact locks passed doctor checks",
        }
    reason_ids = sorted(
        {
            issue.get("id", "unknown_structural_issue")
            for issue in issues
            if isinstance(issue, dict)
        }
    )
    return {
        "status": "failed",
        "reasons": reason_ids or ["managed projection doctor checks failed"],
        "message": "managed projection layout or artifact lock checks failed",
    }


def _runtime_activation_layer(manifest, warnings):
    features = manifest.get("features", {}) if isinstance(manifest, dict) else {}
    automation = features.get("automations", {}) if isinstance(features, dict) else {}
    records = automation.get("records", []) if isinstance(automation, dict) else []
    reasons = []
    unavailable = sorted(
        {
            record.get("id", "unknown_automation")
            for record in records
            if isinstance(record, dict)
            and str(record.get("status", "")).startswith("unavailable_")
        }
    )
    pending = sorted(
        {
            record.get("id", "unknown_automation")
            for record in records
            if isinstance(record, dict)
            and record.get("status") == "projected_pending_user_review"
        }
    )
    if unavailable:
        reasons.append(
            "canonical automations unavailable in this runtime: " + ", ".join(unavailable)
        )
    if pending:
        reasons.append(
            "projected automations still require user review: " + ", ".join(pending)
        )
    warning_ids = {
        warning.get("id")
        for warning in warnings
        if isinstance(warning, dict)
    }
    if "pi_project_trust_unverified" in warning_ids:
        reasons.append("Pi project trust has not been verified by Packwright")
    if reasons:
        return {
            "status": "attention_required",
            "reasons": reasons,
            "message": "runtime activation has unresolved or unverifiable steps",
        }
    return {
        "status": "not_evaluated",
        "message": "managed files exist, but live runtime activation was not inspected",
    }


def _workflow_acceptance_layer(target_dir):
    review_dir = target_dir / ADOPTION_REVIEW_DIR
    review_paths = sorted(review_dir.glob("adoption-review-*.yaml"))
    pending = 0
    invalid = []
    for review_path in review_paths:
        try:
            review = yaml.safe_load(review_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            invalid.append(review_path.name)
            continue
        if not isinstance(review, dict) or review.get("schema") != ADOPTION_REVIEW_SCHEMA:
            invalid.append(review_path.name)
            continue
        items = review.get("items", [])
        if not isinstance(items, list):
            invalid.append(review_path.name)
            continue
        pending += sum(
            item.get("decision") == "pending"
            for item in items
            if isinstance(item, dict)
        )
    reasons = []
    if pending:
        reasons.append(f"{pending} adoption review item(s) are still pending")
    if invalid:
        reasons.append("unreadable adoption review queue(s): " + ", ".join(invalid))
    if reasons:
        return {
            "status": "attention_required",
            "review_queues": len(review_paths),
            "pending_items": pending,
            "reasons": reasons,
            "message": "workflow adoption review is incomplete",
        }
    if review_paths:
        return {
            "status": "not_evaluated",
            "review_queues": len(review_paths),
            "pending_items": 0,
            "message": (
                "adoption review queues have no pending items, but workflow behavior "
                "has no acceptance evidence"
            ),
        }
    return {
        "status": "not_evaluated",
        "review_queues": 0,
        "pending_items": 0,
        "message": "no workflow acceptance evidence was found",
    }
