import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from packwright.core import PackwrightValidationError
from packwright.core.sidecar_orchestrator import SidecarShadowOrchestrator
from packwright.sidecars.protocol import (
    DESCRIPTOR_PATH,
    _bundle_digest,
    load_verified_descriptor,
    receipt_from_result,
)
from packwright.sidecars.runner import SidecarAdminClient


class SidecarProtocolTest(unittest.TestCase):
    def test_shadow_orchestrator_cross_checks_contract_without_apply(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = _write_bundle(root / "bundle", _contract_admin_source())
            descriptor = load_verified_descriptor(bundle)
            client = SidecarAdminClient(descriptor, bundle, root / "target")
            orchestrator = SidecarShadowOrchestrator(
                descriptor,
                client,
                version_field="engine_version",
            )

            report = orchestrator.inspect(
                "ensure",
                {"adapter": "codex", "mode": "light"},
                {"mode": "light"},
            )

            self.assertEqual(report.plan.action, "ensure")
            self.assertTrue(report.plan.requires_confirmation)
            self.assertEqual(report.diagnostic.status, "ready")
            self.assertFalse((root / "target").exists())

    def test_receipt_digest_and_binding_selection_are_not_self_asserted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = _write_bundle(root / "bundle", _echo_admin_source())
            descriptor = load_verified_descriptor(bundle)
            request_digest = _digest(b"request")
            receipt = {
                "schema": "emotion-engine-admin-receipt/v1",
                "action": "ensure",
                "outcome": "applied",
                "request_digest": request_digest,
                "host_binding_selection": {
                    "schema": "sidecar-host-bindings/v1",
                    "binding_ids": ["emotion-engine-mcp-stdio/v1"],
                },
                "integrity": {"ok": True},
            }
            digest_payload = json.dumps(
                receipt,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            receipt["integrity"]["receipt_digest"] = _digest(digest_payload)

            parsed = receipt_from_result(
                descriptor,
                "ensure",
                request_digest,
                {"receipt": receipt},
            )
            self.assertEqual(parsed.host_binding_ids, ("emotion-engine-mcp-stdio/v1",))

            receipt["outcome"] = "tampered"
            with self.assertRaisesRegex(PackwrightValidationError, "integrity digest"):
                receipt_from_result(
                    descriptor,
                    "ensure",
                    request_digest,
                    {"receipt": receipt},
                )

    def test_verified_descriptor_and_bounded_admin_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = _write_bundle(root / "bundle", _echo_admin_source())
            descriptor = load_verified_descriptor(bundle, expected_sidecar_id="emotion-engine")
            client = SidecarAdminClient(descriptor, bundle, root / "target")

            described = client.describe()

            self.assertEqual(described["result"]["status"], "ready")
            self.assertEqual(
                described["request_digest"],
                described["result"]["request_digest"],
            )

    def test_descriptor_rejects_digest_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = _write_bundle(root / "bundle", _echo_admin_source())
            wrapper = bundle / "scripts/wrapper.sh"
            wrapper.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(PackwrightValidationError, "digest mismatch"):
                load_verified_descriptor(bundle)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = _write_bundle(root / "bundle", _echo_admin_source())
            outside = root / "outside.sh"
            outside.write_text("outside\n", encoding="utf-8")
            wrapper = bundle / "scripts/wrapper.sh"
            wrapper.unlink()
            wrapper.symlink_to(outside)
            descriptor_path = bundle / DESCRIPTOR_PATH
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            descriptor["immutable_artifacts"][1]["sha256"] = _digest(outside.read_bytes())
            descriptor["bundle_digest"] = _bundle_digest({
                "scripts/admin.py": (bundle / "scripts/admin.py").read_bytes(),
                "scripts/wrapper.sh": outside.read_bytes(),
            })
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            with self.assertRaisesRegex(PackwrightValidationError, "(symlink|escapes its root)"):
                load_verified_descriptor(bundle)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = _write_bundle(root / "bundle", _echo_admin_source())
            descriptor_path = bundle / DESCRIPTOR_PATH
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            descriptor["host_binding_templates"][0]["args"] = ["-c", "touch /tmp/victim"]
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            with self.assertRaisesRegex(PackwrightValidationError, "inject a shell command"):
                load_verified_descriptor(bundle)

    def test_admin_runner_fails_closed_on_protocol_faults(self):
        cases = {
            "wrong request id": (
                _echo_admin_source("response['request_id'] = 'wrong'"),
                "request_id mismatch",
                {},
            ),
            "malformed stdout": (
                "import sys\nsys.stdin.read()\nprint('not-json')\n",
                "exactly one JSON object",
                {},
            ),
            "oversized stdout": (
                "import sys\nsys.stdin.read()\nprint('x' * 10000)\n",
                "output exceeded",
                {"output_limit": 256},
            ),
            "timeout": (
                "import sys, time\nsys.stdin.read()\ntime.sleep(2)\n",
                "timed out",
                {"timeout": 0.05},
            ),
        }
        for name, (admin_source, message, client_options) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                bundle = _write_bundle(root / "bundle", admin_source)
                descriptor = load_verified_descriptor(bundle)
                client = SidecarAdminClient(
                    descriptor,
                    bundle,
                    root / "target",
                    **client_options,
                )
                with self.assertRaisesRegex(PackwrightValidationError, message):
                    client.describe()


def _write_bundle(root, admin_source):
    (root / "managed").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    files = {
        "scripts/admin.py": admin_source.encode("utf-8"),
        "scripts/wrapper.sh": b"#!/bin/sh\nexit 0\n",
    }
    for rel_path, content in files.items():
        (root / rel_path).write_bytes(content)
    descriptor = {
        "schema": "packwright-sidecar-descriptor/v1",
        "sidecar_id": "emotion-engine",
        "version": "test",
        "bundle_digest": _bundle_digest(files),
        "admin": {
            "protocol": "emotion-engine-admin/v1",
            "entrypoint": "scripts/admin.py",
            "interpreter": "python",
        },
        "supported_adapters": ["codex"],
        "supported_actions": ["ensure", "migrate", "import"],
        "immutable_artifacts": [
            {
                "path": rel_path,
                "sha256": _digest(content),
                "executable": True,
                "role": "admin" if rel_path.endswith("admin.py") else "mcp_wrapper",
            }
            for rel_path, content in files.items()
        ],
        "host_binding_schema": "sidecar-host-bindings/v1",
        "host_binding_templates": [
            {
                "id": "emotion-engine-mcp-stdio/v1",
                "adapter": "codex",
                "kind": "mcp_stdio",
                "name": "emotion-engine",
                "command_artifact": "scripts/wrapper.sh",
                "args": [],
            }
        ],
    }
    (root / DESCRIPTOR_PATH).write_text(
        json.dumps(descriptor, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root


def _echo_admin_source(extra=""):
    return f'''import hashlib
import json
import sys

request = json.loads(sys.stdin.read())
request_digest = "sha256:" + hashlib.sha256(
    json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
response = {{
    "protocol": request["protocol"],
    "sidecar_id": request["sidecar_id"],
    "request_id": request["request_id"],
    "ok": True,
    "result": {{"status": "ready", "request_digest": request_digest}},
}}
{extra}
print(json.dumps(response))
'''


def _contract_admin_source():
    return '''import hashlib
import json
import pathlib
import sys

request = json.loads(sys.stdin.read())
descriptor = json.loads(pathlib.Path("managed/sidecar-descriptor.json").read_text(encoding="utf-8"))
operation = request["operation"]
if operation == "describe":
    result = {
        "engine_version": descriptor["version"],
        "admin_protocols": [descriptor["admin"]["protocol"]],
        "bundle_digest": descriptor["bundle_digest"],
        "supported_actions": descriptor["supported_actions"],
        "host_binding_schema": descriptor["host_binding_schema"],
    }
elif operation == "plan":
    result = {
        "plan_id": "sha256:" + ("1" * 64),
        "plan_token": "opaque-plan-token",
        "action": request["action"],
        "current_status": "ready",
        "outcome_if_applied": "ready",
        "effects": [{"code": "HOST_BINDING_VERIFY", "count": 1, "reversible": True}],
        "requires_confirmation": True,
    }
elif operation == "verify":
    result = {"status": "ready", "revision": "opaque-1", "problems": []}
else:
    result = {}
print(json.dumps({
    "protocol": request["protocol"],
    "sidecar_id": request["sidecar_id"],
    "request_id": request["request_id"],
    "ok": True,
    "result": result,
}))
'''


def _digest(content):
    return "sha256:" + hashlib.sha256(content).hexdigest()


if __name__ == "__main__":
    unittest.main()
