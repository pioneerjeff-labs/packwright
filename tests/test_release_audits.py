import importlib.util
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audit_zero_network", ROOT / "scripts" / "audit_zero_network.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
PUBLIC_SPEC = importlib.util.spec_from_file_location("audit_public_tree", ROOT / "scripts" / "audit_public_tree.py")
public_audit = importlib.util.module_from_spec(PUBLIC_SPEC)
PUBLIC_SPEC.loader.exec_module(public_audit)


class ZeroNetworkAuditTest(unittest.TestCase):
    def test_python_positive_and_negative_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.py"
            path.write_text("import requests as r\nr.get('https://example.test')\n", encoding="utf-8")
            self.assertTrue(audit.audit_python(path))
            path.write_text("value = 'https://example.test'\n", encoding="utf-8")
            self.assertEqual(audit.audit_python(path), [])

    def test_landing_blocks_auto_load_but_allows_links(self):
        csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; img-src 'self' data:"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><a href="https://example.test">link</a>', encoding="utf-8")
            self.assertEqual(audit.audit_landing(path), [])
            path.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><script src="https://example.test/x.js"></script>', encoding="utf-8")
            self.assertTrue(audit.audit_landing(path))

    def test_landing_detects_css_and_javascript_network_calls(self):
        csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; img-src 'self' data:"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><style>x{{background:url(https://example.test/x)}}</style>', encoding="utf-8")
            self.assertTrue(audit.audit_landing(path))
            path.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><script>fetch("/beacon")</script>', encoding="utf-8")
            self.assertTrue(audit.audit_landing(path))

    def test_landing_rejects_inline_script_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; img-src \'self\' data:">', encoding="utf-8")
            self.assertTrue(audit.audit_landing(path))


class PublicTreeAuditTest(unittest.TestCase):
    def test_old_name_variants_are_detected(self):
        for separator in (" ", "_", "-"):
            value = "agent" + separator + "harness"
            self.assertTrue(public_audit.scan_text("fixture", value))

    def test_reachable_deleted_snapshot_and_metadata_are_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "person" + "@" + "gmail.com"], cwd=root, check=True)
            old = root / "old.txt"
            old.write_text("agent" + "_" + "harness", encoding="utf-8")
            subprocess.run(["git", "add", "old.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "old"], cwd=root, check=True)
            old.unlink()
            subprocess.run(["git", "add", "-u"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "delete"], cwd=root, check=True)
            issues, _, commits = public_audit.run(root)
            self.assertEqual(commits, 2)
            self.assertTrue(any("commit metadata private email" in item for item in issues))
            self.assertTrue(any("old product name" in item for item in issues))

    def test_release_gate_declares_portable_temp_and_output_dir(self):
        script = (ROOT / "scripts" / "release-gate.sh").read_text(encoding="utf-8")
        self.assertIn('TEMP_ROOT="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"', script)
        self.assertIn("--output-dir", script)
        self.assertNotIn("/private/tmp", script)

    def test_release_workflow_uses_isolated_trusted_publishing_job(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("release:\n    types: [published]", workflow)
        self.assertNotIn("workflow_dispatch", workflow)
        self.assertIn("Verify release tag matches package version", workflow)
        self.assertIn('test "$GITHUB_REF_NAME" = "v$PACKAGE_VERSION"', workflow)
        self.assertIn('scripts/release-gate.sh --output-dir "$RUNNER_TEMP/packwright-dist"', workflow)
        self.assertIn("needs: build", workflow)
        self.assertIn("name: pypi", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("pypa/gh-action-pypi-publish@release/v1", workflow)

        build_job, publish_job = workflow.split("\n  publish:\n", 1)
        self.assertNotIn("id-token: write", build_job)
        self.assertNotIn("actions/checkout", publish_job)

    def test_public_quickstart_and_migration_paths_share_one_contract(self):
        documents = [ROOT / "README.md", ROOT / "README.zh-CN.md", ROOT / "site" / "index.html"]
        required = (
            "packwright init --template creator -o work/mira",
            "packwright build work/mira --adapter codex -o pack/mira-codex",
            "packwright install pack/mira-codex --target project/mira-codex",
            "packwright migrate project/mira-codex",
            "--target project/mira-cursor --dry-run",
            "--target project/mira-cursor --yes",
            "packwright doctor project/mira-cursor",
            "packwright score project/mira-cursor",
        )
        for path in documents:
            text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8").replace("\\", " "))
            with self.subTest(path=path.name):
                for command in required:
                    self.assertIn(command, text)
                self.assertIsNone(re.search(r"packwright migrate project/mira(?!-codex)", text))


if __name__ == "__main__": unittest.main()
