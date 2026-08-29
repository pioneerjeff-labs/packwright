"""Sidecar descriptor and opaque Admin receipt contracts.

This module deliberately contains no product-specific state or migration rules.
"""

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from packwright.core.errors import PackwrightValidationError
from packwright.core.path_safety import resolve_destination_path, validate_relative_path


DESCRIPTOR_SCHEMA = "packwright-sidecar-descriptor/v1"
HOST_BINDING_SCHEMA = "sidecar-host-bindings/v1"
DESCRIPTOR_PATH = "managed/sidecar-descriptor.json"


@dataclass(frozen=True)
class ImmutableArtifact:
    path: str
    sha256: str
    executable: bool
    role: str


@dataclass(frozen=True)
class SidecarDescriptor:
    sidecar_id: str
    version: str
    bundle_digest: str
    admin_protocol: str
    admin_entrypoint: str
    supported_adapters: tuple
    supported_actions: tuple
    immutable_artifacts: tuple
    host_bindings: tuple

    @property
    def artifacts_by_path(self):
        return {artifact.path: artifact for artifact in self.immutable_artifacts}


@dataclass(frozen=True)
class SidecarReceipt:
    sidecar_id: str
    action: str
    outcome: str
    request_digest: str
    receipt_digest: str
    host_binding_ids: tuple


@dataclass(frozen=True)
class SidecarPlan:
    sidecar_id: str
    action: str
    plan_id: str
    plan_token: str
    current_status: str
    outcome_if_applied: str
    effects: tuple
    requires_confirmation: bool


@dataclass(frozen=True)
class SidecarDiagnostic:
    sidecar_id: str
    status: str
    problems: tuple
    revision: str


def load_verified_descriptor(bundle_root, expected_sidecar_id=None):
    """Validate descriptor shape, safe paths, and every immutable artifact byte."""
    bundle_root = Path(bundle_root).resolve(strict=True)
    descriptor_path = _bundle_regular_file(bundle_root, DESCRIPTOR_PATH, "sidecar descriptor")
    try:
        value = json.loads(descriptor_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackwrightValidationError([f"invalid sidecar descriptor: {exc}"]) from exc
    if not isinstance(value, dict) or value.get("schema") != DESCRIPTOR_SCHEMA:
        raise PackwrightValidationError([
            f"sidecar descriptor schema must be {DESCRIPTOR_SCHEMA}"
        ])
    sidecar_id = _nonempty_string(value.get("sidecar_id"), "sidecar_id")
    if expected_sidecar_id is not None and sidecar_id != expected_sidecar_id:
        raise PackwrightValidationError([
            f"sidecar descriptor id is {sidecar_id!r}, expected {expected_sidecar_id!r}"
        ])
    version = _nonempty_string(value.get("version"), "version")
    bundle_digest = _sha256_value(value.get("bundle_digest"), "bundle_digest")
    admin = value.get("admin")
    if not isinstance(admin, dict):
        raise PackwrightValidationError(["sidecar descriptor admin must be an object"])
    admin_protocol = _nonempty_string(admin.get("protocol"), "admin.protocol")
    admin_entrypoint = _safe_relative(admin.get("entrypoint"), "admin.entrypoint")
    if admin.get("interpreter") != "python":
        raise PackwrightValidationError(["sidecar Admin interpreter must be python"])

    adapters = _unique_strings(value.get("supported_adapters"), "supported_adapters")
    actions = _unique_strings(value.get("supported_actions"), "supported_actions")
    raw_artifacts = value.get("immutable_artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise PackwrightValidationError(["immutable_artifacts must be a non-empty list"])
    artifacts = []
    artifact_bytes = {}
    for index, item in enumerate(raw_artifacts):
        if not isinstance(item, dict):
            raise PackwrightValidationError([f"immutable_artifacts[{index}] must be an object"])
        rel_path = _safe_relative(item.get("path"), f"immutable_artifacts[{index}].path")
        digest = _sha256_value(item.get("sha256"), f"immutable_artifacts[{index}].sha256")
        path = _bundle_regular_file(bundle_root, rel_path, "immutable sidecar artifact")
        content = path.read_bytes()
        actual = "sha256:" + hashlib.sha256(content).hexdigest()
        if actual != digest:
            raise PackwrightValidationError([f"immutable sidecar artifact digest mismatch: {rel_path}"])
        artifacts.append(ImmutableArtifact(
            path=rel_path,
            sha256=digest,
            executable=bool(item.get("executable")),
            role=_nonempty_string(item.get("role"), f"immutable_artifacts[{index}].role"),
        ))
        artifact_bytes[rel_path] = content
    if len({artifact.path for artifact in artifacts}) != len(artifacts):
        raise PackwrightValidationError(["immutable sidecar artifact paths must be unique"])
    if admin_entrypoint not in artifact_bytes:
        raise PackwrightValidationError(["sidecar Admin entrypoint must be an immutable artifact"])
    actual_bundle_digest = _bundle_digest(artifact_bytes)
    if actual_bundle_digest != bundle_digest:
        raise PackwrightValidationError(["sidecar bundle digest does not match immutable artifacts"])

    if value.get("host_binding_schema") != HOST_BINDING_SCHEMA:
        raise PackwrightValidationError([
            f"host_binding_schema must be {HOST_BINDING_SCHEMA}"
        ])
    bindings = value.get("host_binding_templates", [])
    if not isinstance(bindings, list):
        raise PackwrightValidationError(["host_binding_templates must be a list"])
    normalized_bindings = []
    binding_ids = set()
    for index, binding in enumerate(bindings):
        if not isinstance(binding, dict):
            raise PackwrightValidationError([f"host_binding_templates[{index}] must be an object"])
        binding_id = _nonempty_string(binding.get("id"), f"host_binding_templates[{index}].id")
        if binding_id in binding_ids:
            raise PackwrightValidationError([f"duplicate host binding id: {binding_id}"])
        binding_ids.add(binding_id)
        adapter = _nonempty_string(binding.get("adapter"), f"host_binding_templates[{index}].adapter")
        if adapter not in adapters:
            raise PackwrightValidationError([f"host binding adapter is not supported: {adapter}"])
        kind = _nonempty_string(binding.get("kind"), f"host_binding_templates[{index}].kind")
        if kind not in {"mcp_stdio", "guidance", "lifecycle"}:
            raise PackwrightValidationError([f"unsupported host binding kind: {kind}"])
        allowed_keys = {
            "mcp_stdio": {"id", "adapter", "kind", "name", "command_artifact", "args"},
            "guidance": {"id", "adapter", "kind", "source_artifact", "destination"},
            "lifecycle": {"id", "adapter", "kind", "source_artifact", "destination", "event"},
        }[kind]
        unknown_keys = set(binding) - allowed_keys
        if unknown_keys:
            raise PackwrightValidationError([
                f"host binding contains unsupported fields: {binding_id}: {sorted(unknown_keys)}"
            ])
        command_artifact = binding.get("command_artifact")
        if kind == "mcp_stdio" and command_artifact is None:
            raise PackwrightValidationError([f"MCP host binding has no command artifact: {binding_id}"])
        if command_artifact is not None:
            command_artifact = _safe_relative(command_artifact, "host binding command_artifact")
            if command_artifact not in artifact_bytes:
                raise PackwrightValidationError([
                    f"host binding command is not an immutable artifact: {command_artifact}"
                ])
        source_artifact = binding.get("source_artifact")
        if kind in {"guidance", "lifecycle"} and source_artifact is None:
            raise PackwrightValidationError([f"{kind} host binding has no source artifact: {binding_id}"])
        if source_artifact is not None:
            source_artifact = _safe_relative(source_artifact, "host binding source_artifact")
            if source_artifact not in artifact_bytes:
                raise PackwrightValidationError([
                    f"host binding source is not an immutable artifact: {source_artifact}"
                ])
        destination = binding.get("destination")
        if kind in {"guidance", "lifecycle"} and destination is None:
            raise PackwrightValidationError([f"{kind} host binding has no destination: {binding_id}"])
        if destination is not None:
            _safe_relative(destination, "host binding destination")
        args = binding.get("args", [])
        if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
            raise PackwrightValidationError([f"host binding args must be a string list: {binding_id}"])
        for argument in args:
            if (
                argument in {"-c", "--command"}
                or any(character in argument for character in ("\x00", "\n", "\r", "`", "$"))
                or ("{" in argument or "}" in argument)
                and argument not in {"{target_root}", "{bundle_root}"}
            ):
                raise PackwrightValidationError([f"host binding may not inject a shell command: {binding_id}"])
        normalized_bindings.append(json.loads(json.dumps(binding, sort_keys=True)))

    return SidecarDescriptor(
        sidecar_id=sidecar_id,
        version=version,
        bundle_digest=bundle_digest,
        admin_protocol=admin_protocol,
        admin_entrypoint=admin_entrypoint,
        supported_adapters=adapters,
        supported_actions=actions,
        immutable_artifacts=tuple(artifacts),
        host_bindings=tuple(normalized_bindings),
    )


def receipt_from_result(descriptor, action, request_digest, result):
    receipt = result.get("receipt") if isinstance(result, dict) else None
    if not isinstance(receipt, dict):
        raise PackwrightValidationError(["sidecar Admin result has no receipt object"])
    if receipt.get("action") != action:
        raise PackwrightValidationError(["sidecar receipt action does not match the request"])
    if receipt.get("request_digest") != request_digest:
        raise PackwrightValidationError(["sidecar receipt request digest does not match"])
    integrity = receipt.get("integrity")
    receipt_digest = integrity.get("receipt_digest") if isinstance(integrity, dict) else None
    receipt_digest = _sha256_value(receipt_digest, "receipt.integrity.receipt_digest")
    digest_payload = json.loads(json.dumps(receipt, sort_keys=True))
    digest_payload["integrity"].pop("receipt_digest", None)
    actual_receipt_digest = "sha256:" + hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if receipt_digest != actual_receipt_digest:
        raise PackwrightValidationError(["sidecar receipt integrity digest does not match"])
    selection = receipt.get("host_binding_selection", {})
    binding_ids = selection.get("binding_ids", []) if isinstance(selection, dict) else []
    known = {binding["id"] for binding in descriptor.host_bindings}
    if not isinstance(binding_ids, list) or any(binding_id not in known for binding_id in binding_ids):
        raise PackwrightValidationError(["sidecar receipt selected an unknown host binding"])
    return SidecarReceipt(
        sidecar_id=descriptor.sidecar_id,
        action=action,
        outcome=_nonempty_string(receipt.get("outcome"), "receipt.outcome"),
        request_digest=request_digest,
        receipt_digest=receipt_digest,
        host_binding_ids=tuple(binding_ids),
    )


def plan_from_result(descriptor, action, result):
    if not isinstance(result, dict):
        raise PackwrightValidationError(["sidecar Admin plan result must be an object"])
    if result.get("action") != action:
        raise PackwrightValidationError(["sidecar plan action does not match the request"])
    plan_id = _sha256_value(result.get("plan_id"), "plan.plan_id")
    plan_token = _nonempty_string(result.get("plan_token"), "plan.plan_token")
    effects = result.get("effects", [])
    if not isinstance(effects, list):
        raise PackwrightValidationError(["sidecar plan effects must be a list"])
    normalized_effects = []
    for index, effect in enumerate(effects):
        if not isinstance(effect, dict):
            raise PackwrightValidationError([f"sidecar plan effects[{index}] must be an object"])
        code = _nonempty_string(effect.get("code"), f"plan.effects[{index}].code")
        count = effect.get("count")
        reversible = effect.get("reversible")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise PackwrightValidationError([f"plan.effects[{index}].count must be a non-negative integer"])
        if not isinstance(reversible, bool):
            raise PackwrightValidationError([f"plan.effects[{index}].reversible must be a boolean"])
        normalized_effects.append({"code": code, "count": count, "reversible": reversible})
    if not isinstance(result.get("requires_confirmation"), bool):
        raise PackwrightValidationError(["sidecar plan requires_confirmation must be a boolean"])
    return SidecarPlan(
        sidecar_id=descriptor.sidecar_id,
        action=action,
        plan_id=plan_id,
        plan_token=plan_token,
        current_status=_nonempty_string(result.get("current_status"), "plan.current_status"),
        outcome_if_applied=_nonempty_string(
            result.get("outcome_if_applied"),
            "plan.outcome_if_applied",
        ),
        effects=tuple(normalized_effects),
        requires_confirmation=result["requires_confirmation"],
    )


def diagnostic_from_result(descriptor, result):
    if not isinstance(result, dict):
        raise PackwrightValidationError(["sidecar Admin verify result must be an object"])
    problems = result.get("problems", [])
    if not isinstance(problems, list) or any(not isinstance(item, dict) for item in problems):
        raise PackwrightValidationError(["sidecar diagnostic problems must be an object list"])
    normalized = []
    for index, problem in enumerate(problems):
        normalized.append({
            "code": _nonempty_string(problem.get("code"), f"problems[{index}].code"),
            "message": _nonempty_string(problem.get("message"), f"problems[{index}].message"),
        })
    return SidecarDiagnostic(
        sidecar_id=descriptor.sidecar_id,
        status=_nonempty_string(result.get("status"), "diagnostic.status"),
        problems=tuple(normalized),
        revision=_nonempty_string(result.get("revision"), "diagnostic.revision"),
    )


def _bundle_digest(files):
    digest = hashlib.sha256()
    for rel_path, content in sorted(files.items()):
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _safe_relative(value, label):
    if not isinstance(value, str) or not value.strip():
        raise PackwrightValidationError([f"{label} must be a non-empty relative path"])
    return validate_relative_path(value, label).as_posix()


def _bundle_regular_file(bundle_root, rel_path, label):
    path = resolve_destination_path(bundle_root, rel_path, label)
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError as exc:
        raise PackwrightValidationError([f"{label} does not exist: {rel_path}"]) from exc
    if not stat.S_ISREG(mode):
        raise PackwrightValidationError([f"{label} is not a regular file: {rel_path}"])
    return path


def _nonempty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise PackwrightValidationError([f"{label} must be a non-empty string"])
    return value.strip()


def _unique_strings(value, label):
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise PackwrightValidationError([f"{label} must be a non-empty string list"])
    if len(set(value)) != len(value):
        raise PackwrightValidationError([f"{label} values must be unique"])
    return tuple(value)


def _sha256_value(value, label):
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(char not in "0123456789abcdef" for char in value[7:].lower())
    ):
        raise PackwrightValidationError([f"{label} must be a sha256:<hex> digest"])
    return "sha256:" + value[7:].lower()
