"""Read-only orchestration for descriptor/Admin sidecars.

The first cut is intentionally shadow-only.  It proves the external contract
without creating a second writer while a release is still using its legacy
bridge.  Mutating orchestration must not be enabled until the approved sidecar
ships an Admin implementation and an immutable descriptor.
"""

from dataclasses import dataclass

from .errors import PackwrightValidationError
from packwright.sidecars.protocol import diagnostic_from_result, plan_from_result


@dataclass(frozen=True)
class SidecarShadowReport:
    sidecar_id: str
    version: str
    bundle_digest: str
    admin_protocol: str
    plan: object
    diagnostic: object


class SidecarShadowOrchestrator:
    """Exercise describe/plan/verify without invoking any mutating operation."""

    def __init__(self, descriptor, admin_client, version_field="version"):
        self.descriptor = descriptor
        self.admin = admin_client
        self.version_field = version_field

    def describe(self):
        response = self.admin.describe()
        result = response["result"]
        expected = {
            self.version_field: self.descriptor.version,
            "bundle_digest": self.descriptor.bundle_digest,
            "host_binding_schema": "sidecar-host-bindings/v1",
        }
        mismatches = [
            f"{key} is {result.get(key)!r}, expected {value!r}"
            for key, value in expected.items()
            if result.get(key) != value
        ]
        protocols = result.get("admin_protocols")
        if not isinstance(protocols, list) or self.descriptor.admin_protocol not in protocols:
            mismatches.append("approved Admin protocol was not reported")
        actions = result.get("supported_actions")
        if not isinstance(actions, list) or set(actions) != set(self.descriptor.supported_actions):
            mismatches.append("reported actions do not match the verified descriptor")
        if mismatches:
            raise PackwrightValidationError([
                "sidecar Admin describe does not match the verified descriptor: "
                + "; ".join(mismatches)
            ])
        return result

    def plan(self, action, intent):
        response = self.admin.plan(action, intent)
        return plan_from_result(self.descriptor, action, response["result"])

    def verify(self, expected):
        response = self.admin.verify(expected)
        return diagnostic_from_result(self.descriptor, response["result"])

    def inspect(self, action, intent, expected):
        self.describe()
        plan = self.plan(action, intent)
        diagnostic = self.verify(expected)
        return SidecarShadowReport(
            sidecar_id=self.descriptor.sidecar_id,
            version=self.descriptor.version,
            bundle_digest=self.descriptor.bundle_digest,
            admin_protocol=self.descriptor.admin_protocol,
            plan=plan,
            diagnostic=diagnostic,
        )
