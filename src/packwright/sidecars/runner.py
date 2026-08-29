"""Bounded JSON client for an already verified local Sidecar Admin."""

import json
import hashlib
import os
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from packwright.core.errors import PackwrightValidationError
from packwright.core.path_safety import resolve_destination_path


class SidecarAdminClient:
    def __init__(self, descriptor, bundle_root, project_root, timeout=30, output_limit=1_000_000):
        self.descriptor = descriptor
        self.bundle_root = Path(bundle_root).resolve(strict=True)
        self.project_root = Path(project_root).resolve()
        self.timeout = timeout
        self.output_limit = output_limit
        self.entrypoint = resolve_destination_path(
            self.bundle_root,
            descriptor.admin_entrypoint,
            "verified sidecar Admin entrypoint",
        )

    def describe(self):
        return self.request("describe")

    def plan(self, action, intent):
        if action not in self.descriptor.supported_actions:
            raise PackwrightValidationError([f"sidecar action is not declared: {action}"])
        return self.request("plan", action=action, intent=dict(intent or {}))

    def apply(self, action, plan_token, plan_id, idempotency_key, confirmed):
        if action not in self.descriptor.supported_actions:
            raise PackwrightValidationError([f"sidecar action is not declared: {action}"])
        return self.request(
            "apply",
            action=action,
            plan_token=plan_token,
            idempotency_key=idempotency_key,
            confirmation={"accepted": bool(confirmed), "plan_id": plan_id},
        )

    def verify(self, expected):
        return self.request("verify", expected=dict(expected or {}))

    def export(self, intent):
        return self.request("export", intent=dict(intent or {}))

    def request(self, operation, **payload):
        request_id = uuid.uuid4().hex
        request = {
            "protocol": self.descriptor.admin_protocol,
            "sidecar_id": self.descriptor.sidecar_id,
            "request_id": request_id,
            "operation": operation,
            **payload,
        }
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        response = self._run(operation, encoded)
        if response.get("protocol") != self.descriptor.admin_protocol:
            raise PackwrightValidationError(["sidecar Admin response protocol mismatch"])
        if response.get("sidecar_id") != self.descriptor.sidecar_id:
            raise PackwrightValidationError(["sidecar Admin response id mismatch"])
        if response.get("request_id") != request_id:
            raise PackwrightValidationError(["sidecar Admin response request_id mismatch"])
        if response.get("ok") is not True:
            error = response.get("error")
            code = error.get("code") if isinstance(error, dict) else "invalid_error"
            message = error.get("message") if isinstance(error, dict) else "sidecar Admin failed"
            raise PackwrightValidationError([f"sidecar Admin {code}: {message}"])
        result = response.get("result")
        if not isinstance(result, dict):
            raise PackwrightValidationError(["sidecar Admin result must be an object"])
        return {"request": request, "request_digest": _request_digest(request), "result": result}

    def _run(self, operation, encoded):
        self._verify_entrypoint()
        environment = {
            key: os.environ[key]
            for key in ("LANG", "LC_ALL", "PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR")
            if key in os.environ
        }
        environment.update({
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
        })
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(self.entrypoint),
                        "--project-root",
                        str(self.project_root),
                        operation,
                    ],
                    cwd=str(self.bundle_root),
                    env=environment,
                    input=encoded,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    check=False,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise PackwrightValidationError(["sidecar Admin timed out"]) from exc
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read(self.output_limit + 1)
            stderr = stderr_file.read(self.output_limit + 1)
        if len(stdout) > self.output_limit or len(stderr) > self.output_limit:
            raise PackwrightValidationError(["sidecar Admin output exceeded the configured limit"])
        try:
            response = json.loads(stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PackwrightValidationError(["sidecar Admin stdout must contain exactly one JSON object"]) from exc
        if not isinstance(response, dict):
            raise PackwrightValidationError(["sidecar Admin response must be an object"])
        if completed.returncode != 0 and response.get("ok") is True:
            raise PackwrightValidationError(["sidecar Admin exit status contradicts its response"])
        return response

    def _verify_entrypoint(self):
        try:
            mode = os.lstat(self.entrypoint).st_mode
        except FileNotFoundError as exc:
            raise PackwrightValidationError(["verified sidecar Admin entrypoint is missing"]) from exc
        if not stat.S_ISREG(mode):
            raise PackwrightValidationError(["verified sidecar Admin entrypoint is not a regular file"])
        expected = self.descriptor.artifacts_by_path[self.descriptor.admin_entrypoint].sha256
        actual = "sha256:" + hashlib.sha256(self.entrypoint.read_bytes()).hexdigest()
        if actual != expected:
            raise PackwrightValidationError(["verified sidecar Admin entrypoint digest changed"])


def _request_digest(request):
    import hashlib

    payload = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
