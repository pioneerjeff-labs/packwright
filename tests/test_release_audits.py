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

    def test_landing_allows_self_hosted_script_and_audits_its_source(self):
        csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; img-src 'self' data:"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = root / "index.html"
            script = root / "demo.js"
            html.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><script src="demo.js" defer></script>', encoding="utf-8")
            script.write_text("document.body.dataset.ready = 'true';", encoding="utf-8")
            self.assertEqual(audit.audit_landing(html), [])
            self.assertEqual(audit.audit_javascript(script), [])
            script.write_text("fetch('/beacon');", encoding="utf-8")
            self.assertTrue(audit.audit_javascript(script))


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
        documents = [
            ROOT / "README.md",
            ROOT / "README.zh-CN.md",
            ROOT / "site" / "index.html",
            ROOT / "site" / "zh-CN.html",
        ]
        required = (
            "packwright init --template creator -o work/mira",
            "packwright build work/mira --adapter claude-code -o pack/mira-claude",
            "packwright install pack/mira-claude --adapter claude-code --target project/mira-claude",
            "packwright migrate project/mira-claude",
            "--target project/mira-codex --dry-run",
            "--target project/mira-codex --yes",
            "packwright doctor project/mira-codex",
            "packwright score project/mira-codex",
        )
        for path in documents:
            text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8").replace("\\", " "))
            with self.subTest(path=path.name):
                for command in required:
                    self.assertIn(command, text)
                self.assertIsNone(re.search(r"packwright migrate project/mira(?!-claude)", text))

    def test_public_entrypoints_share_brand_and_receipt_contract(self):
        readmes = [ROOT / "README.md", ROOT / "README.zh-CN.md"]
        for path in readmes:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("assets/mark-dark.svg", text)
                self.assertIn("assets/mark-light.svg", text)
                self.assertIn("assets/social-preview.png", text)
                self.assertIn("https://pioneerjeff-labs.github.io/packwright/", text)
                self.assertIn("https://pioneerjeff-labs.github.io/packwright/zh-CN.html", text)
                for receipt_kind in ("generated", "carried", "rewritten", "excluded"):
                    self.assertIn(f"`{receipt_kind}`", text)

        readme = readmes[0].read_text(encoding="utf-8")
        chinese_readme = readmes[1].read_text(encoding="utf-8")
        self.assertIn("Build your agent once. Carry it everywhere.", readme)
        self.assertIn("Explore the live product website", readme)
        self.assertIn("一次构建 Agent。随心迁移，无缝运行。", chinese_readme)
        self.assertIn("查看在线产品网站", chinese_readme)
        self.assertLess(readme.index("assets/social-preview.png"), readme.index("## Start with your coding agent"))
        self.assertLess(chinese_readme.index("assets/social-preview.png"), chinese_readme.index("## 先交给 coding agent 代驾"))

        landing = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Packwright dovetail mark", landing)
        self.assertIn("Build your agent once. Carry it everywhere.", landing)
        self.assertIn("plain files in · plain files out", landing)
        self.assertIn('<script src="demo.js" defer></script>', landing)
        self.assertTrue((ROOT / "site" / "demo.js").is_file())

        chinese_landing = (ROOT / "site" / "zh-CN.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="zh-CN"', chinese_landing)
        self.assertIn("一次构建 Agent。", chinese_landing)
        self.assertIn("随心迁移，无缝运行。", chinese_landing)
        self.assertIn("自己掌舵，或让 Agent 代驾", chinese_landing)
        self.assertIn("packwright-han-serif-600.otf", chinese_landing)
        self.assertIn('<script src="demo.js" defer></script>', chinese_landing)
        self.assertIn('href="index.html"', chinese_landing)
        self.assertIn('href="zh-CN.html"', landing)
        self.assertNotIn("Claude is selected by default", landing)
        self.assertNotIn("默认选择 Claude", chinese_landing)

        for document in (landing, chinese_landing):
            self.assertLess(document.index('id="migrate"'), document.index('id="quickstart"'))
            self.assertIn('data-adapter="claude-code"', document)
            self.assertIn('data-adapter="codex"', document)
            self.assertIn('data-adapter="cursor"', document)
            self.assertIn('id="runtime-claude"', document)
            self.assertIn('id="runtime-claude" type="button" role="tab" aria-selected="true"', document)

        demo = (ROOT / "site" / "demo.js").read_text(encoding="utf-8")
        self.assertIn("const englishLines = [", demo)
        self.assertIn("const chineseLines = [", demo)
        self.assertIn('startsWith("zh")', demo)
        self.assertIn("pack compiled · checker score 100.0", demo)
        self.assertIn("Pack 编译完成 · checker 评分 100.0", demo)
        self.assertIn('"packwright build work/mira --adapter codex -o pack/mira-codex"', demo)
        self.assertIn('"packwright build work/mira --adapter cursor -o pack/mira-cursor"', demo)
        self.assertIn("function legacyCopy(text)", demo)
        self.assertIn('document.execCommand("copy")', demo)

        han_font = ROOT / "assets" / "fonts" / "packwright-han-serif-600.otf"
        self.assertTrue(han_font.is_file())
        self.assertLess(han_font.stat().st_size, 500_000)
        self.assertTrue((ROOT / "assets" / "fonts" / "OFL-Packwright-Han-Serif.txt").is_file())
        self.assertIn("*.otf", (ROOT / "MANIFEST.in").read_text(encoding="utf-8"))

    def test_workflows_use_node24_setup_python_action(self):
        for path in (ROOT / ".github" / "workflows").glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("actions/setup-python@v5", text)
                if "setup-python" in text:
                    self.assertIn("actions/setup-python@v6", text)

    def test_pages_workflow_stages_the_landing_and_runtime_assets(self):
        workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        for expected in (
            "actions/configure-pages@v6",
            "actions/upload-pages-artifact@v5",
            "actions/deploy-pages@v5",
            "cp -R site/. _site/",
            "cp -R assets/fonts/. _site/assets/fonts/",
            "cp assets/social-preview.png _site/assets/social-preview.png",
            "_site/*.html",
        ):
            self.assertIn(expected, workflow)
        self.assertIn("pages: write", workflow)
        self.assertIn("id-token: write", workflow)

        landing = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        pages_url = "https://pioneerjeff-labs.github.io/packwright/"
        self.assertIn(f'<link rel="canonical" href="{pages_url}">', landing)
        self.assertIn(f'<meta property="og:url" content="{pages_url}">', landing)
        self.assertIn(f'{pages_url}assets/social-preview.png', landing)

        chinese_landing = (ROOT / "site" / "zh-CN.html").read_text(encoding="utf-8")
        chinese_url = f"{pages_url}zh-CN.html"
        self.assertIn(f'<link rel="canonical" href="{chinese_url}">', chinese_landing)
        self.assertIn(f'<meta property="og:url" content="{chinese_url}">', chinese_landing)
        for document in (landing, chinese_landing):
            self.assertIn(f'hreflang="en" href="{pages_url}"', document)
            self.assertIn(f'hreflang="zh-CN" href="{chinese_url}"', document)


if __name__ == "__main__": unittest.main()
