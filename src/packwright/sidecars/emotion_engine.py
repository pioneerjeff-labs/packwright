"""Packwright product policy for the Emotion Engine sidecar.

No Emotion Engine state schema, capability, legacy path, or migration rule belongs here.
"""

from dataclasses import dataclass

from packwright.core.errors import PackwrightValidationError
from packwright.core.sidecar_orchestrator import SidecarShadowOrchestrator

from .protocol import load_verified_descriptor
from .runner import SidecarAdminClient


@dataclass(frozen=True)
class EmotionEngineReleasePolicy:
    sidecar_id: str
    admin_protocol: str
    approved_revision: str


EMOTION_ENGINE_RELEASE_POLICY = EmotionEngineReleasePolicy(
    sidecar_id="emotion-engine",
    admin_protocol="emotion-engine-admin/v1",
    approved_revision="410c7e097c0a3e84a77d4bae2dc262324875b6ad",
)


class EmotionEngineDriver:
    def __init__(self, bundle_root, project_root):
        self.descriptor = load_verified_descriptor(
            bundle_root,
            expected_sidecar_id=EMOTION_ENGINE_RELEASE_POLICY.sidecar_id,
        )
        if self.descriptor.admin_protocol != EMOTION_ENGINE_RELEASE_POLICY.admin_protocol:
            raise PackwrightValidationError([
                f"unsupported Emotion Engine Admin protocol: {self.descriptor.admin_protocol}"
            ])
        self.admin = SidecarAdminClient(self.descriptor, bundle_root, project_root)
        self.shadow = SidecarShadowOrchestrator(
            self.descriptor,
            self.admin,
            version_field="engine_version",
        )

    def describe(self):
        return self.shadow.describe()

    def plan(self, action, intent):
        return self.shadow.plan(action, intent)

    def verify(self, expected):
        return self.shadow.verify(expected)
