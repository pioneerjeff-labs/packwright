import importlib.util
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_python_blocks_indirect_network_and_execution_surfaces(self):
        samples = (
            "import subprocess\nsubprocess.run(['curl', 'https://example.test'])\n",
            "import webbrowser\nwebbrowser.open('https://example.test')\n",
            "import asyncio\nasyncio.open_connection('example.test', 443)\n",
            "import importlib\nimportlib.import_module('requests')\n",
            "import os\nos.system('curl https://example.test')\n",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.py"
            for source in samples:
                with self.subTest(source=source.splitlines()[0]):
                    path.write_text(source, encoding="utf-8")
                    self.assertTrue(audit.audit_python(path))

    def test_embedded_generated_python_is_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "generator.py"
            path.write_text(
                'HELPER = """\nimport socket\nsocket.create_connection((\"example.test\", 443))\n"""\n',
                encoding="utf-8",
            )
            self.assertEqual(audit.audit_python(path), [])
            self.assertTrue(audit.audit_embedded_python(path))

    def test_landing_blocks_auto_load_but_allows_links(self):
        csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; img-src 'self' data:; connect-src 'none'"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><a href="https://example.test">link</a>', encoding="utf-8")
            self.assertEqual(audit.audit_landing(path), [])
            path.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><script src="https://example.test/x.js"></script>', encoding="utf-8")
            self.assertTrue(audit.audit_landing(path))

    def test_landing_detects_css_and_javascript_network_calls(self):
        csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; img-src 'self' data:; connect-src 'none'"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><style>x{{background:url(https://example.test/x)}}</style>', encoding="utf-8")
            self.assertTrue(audit.audit_landing(path))
            path.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><script>fetch("/beacon")</script>', encoding="utf-8")
            self.assertTrue(audit.audit_landing(path))

    def test_landing_rejects_inline_script_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; img-src \'self\' data:; connect-src \'none\'">', encoding="utf-8")
            self.assertTrue(audit.audit_landing(path))

    def test_landing_requires_an_exact_connect_src_none_directive(self):
        base = "default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; img-src 'self' data:"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text(
                f'<meta http-equiv="Content-Security-Policy" content="{base}; x-connect-src \'none\'">',
                encoding="utf-8",
            )
            self.assertTrue(audit.audit_landing(path))
            path.write_text(
                f'<meta http-equiv="Content-Security-Policy" content="{base}; connect-src https:">',
                encoding="utf-8",
            )
            self.assertTrue(audit.audit_landing(path))

    def test_landing_allows_self_hosted_script_and_audits_its_source(self):
        csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'none'"
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

    def test_javascript_blocks_dynamic_import_and_image_src_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.js"
            path.write_text('import("./remote-module.js");', encoding="utf-8")
            self.assertTrue(audit.audit_javascript(path))
            path.write_text('new Image().src = "https://example.test/pixel.png";', encoding="utf-8")
            self.assertTrue(audit.audit_javascript(path))

    def test_external_preload_is_treated_as_an_auto_load(self):
        csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; img-src 'self' data:; connect-src 'none'"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text(
                f'<meta http-equiv="Content-Security-Policy" content="{csp}"><link rel="preload" href="https://example.test/font.woff2" as="font">',
                encoding="utf-8",
            )
            self.assertTrue(audit.audit_landing(path))

    def test_run_scans_scripts_and_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "examples").mkdir()
            (root / "scripts" / "helper.py").write_text("import webbrowser\n", encoding="utf-8")
            (root / "examples" / "sample.py").write_text("import asyncio\n", encoding="utf-8")
            issues = audit.run(root)
            self.assertTrue(any("scripts/helper.py" in issue for issue in issues))
            self.assertTrue(any("examples/sample.py" in issue for issue in issues))


class PublicTreeAuditTest(unittest.TestCase):
    def test_private_metadata_exception_is_commit_scoped(self):
        private_metadata = "person" + "@" + "gmail.com"
        allowed_revision = next(iter(public_audit.ALLOWED_PRIVATE_METADATA_COMMITS))

        with mock.patch.object(public_audit, "history_revisions", return_value=[allowed_revision]):
            with mock.patch.object(
                public_audit,
                "git",
                side_effect=[private_metadata.encode(), b""],
            ):
                issues, commits = public_audit.history_issues(ROOT)
        self.assertEqual(issues, [])
        self.assertEqual(commits, 1)

        different_revision = "0" * 40
        with mock.patch.object(public_audit, "history_revisions", return_value=[different_revision]):
            with mock.patch.object(
                public_audit,
                "git",
                side_effect=[private_metadata.encode(), b""],
            ):
                issues, commits = public_audit.history_issues(ROOT)
        self.assertTrue(any("commit metadata private email" in item for item in issues))
        self.assertEqual(commits, 1)

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

    def test_pr_head_revision_excludes_unpublished_synthetic_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@users.noreply.github.com"],
                cwd=root,
                check=True,
            )
            safe = root / "safe.txt"
            safe.write_text("safe\n", encoding="utf-8")
            subprocess.run(["git", "add", "safe.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "safe"], cwd=root, check=True)
            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

            subprocess.run(
                ["git", "config", "user.email", "person" + "@" + "gmail.com"],
                cwd=root,
                check=True,
            )
            later = root / "later.txt"
            later.write_text("later\n", encoding="utf-8")
            subprocess.run(["git", "add", "later.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "synthetic"], cwd=root, check=True)

            all_issues, _, all_commits = public_audit.run(root)
            self.assertEqual(all_commits, 2)
            self.assertTrue(any("commit metadata private email" in item for item in all_issues))

            head_issues, _, head_commits = public_audit.run(root, revision=head)
            self.assertEqual(head_commits, 1)
            self.assertFalse(any("commit metadata private email" in item for item in head_issues))

    def test_ci_scans_pr_head_instead_of_github_synthetic_merge(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn(
            "PACKWRIGHT_PUBLIC_AUDIT_REVISION: ${{ github.event.pull_request.head.sha }}",
            workflow,
        )
        self.assertEqual(
            workflow.count('git fetch --no-tags origin "pull/${{ github.event.number }}/head"'),
            2,
        )

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
        documents = {
            ROOT / "README.md": "claude-code",
            ROOT / "README.zh-CN.md": "claude-code",
            ROOT / "site" / "index.html": "pi",
            ROOT / "site" / "zh-CN.html": "pi",
        }
        required = (
            "packwright init --template code --name Nova",
            "packwright migrate project/nova-claude",
            "--target project/nova-codex --dry-run",
            "--target project/nova-codex --yes",
            "packwright doctor project/nova-codex",
            "packwright score project/nova-codex",
        )
        for path, quickstart_adapter in documents.items():
            text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8").replace("\\", " "))
            with self.subTest(path=path.name):
                for command in required:
                    self.assertIn(command, text)
                suffix = "claude" if quickstart_adapter == "claude-code" else "pi"
                self.assertIn(
                    f"packwright build work/nova --adapter {quickstart_adapter} -o pack/nova-{suffix}",
                    text,
                )
                self.assertIn(
                    f"packwright install pack/nova-{suffix} --adapter {quickstart_adapter} "
                    f"--target project/nova-{suffix}",
                    text,
                )
                self.assertIsNone(re.search(r"packwright migrate project/nova(?!-claude)", text))
                self.assertNotIn("--template creator", text)

    def test_agent_prompt_keeps_adapter_and_write_guardrails_executable(self):
        prompt = (ROOT / "docs" / "USE_WITH_YOUR_AGENT.md").read_text(encoding="utf-8")
        self.assertIn(
            "packwright install <pack-dir> --adapter <adapter> --target <target-dir>",
            prompt,
        )
        self.assertIn("where `<source>` is the directory previously installed into", prompt)
        self.assertIn("with `--yes` in place of `--dry-run`", prompt)
        self.assertIn("never edit user-authored content under `memory/` or `workspace/`", prompt)
        self.assertIn("doctor --fix` requires my separate approval", prompt)
        self.assertIn("packwright presets <chosen-preset>", prompt)
        self.assertIn("Do not begin build until I confirm or edit that summary", prompt)

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
                for receipt_kind in ("generated", "carried", "rewritten", "degraded", "excluded"):
                    self.assertIn(f"`{receipt_kind}`", text)

        readme = readmes[0].read_text(encoding="utf-8")
        chinese_readme = readmes[1].read_text(encoding="utf-8")
        self.assertIn("python -m pip install packwright==0.3.0", readme)
        self.assertIn("python -m pip install packwright==0.3.0", chinese_readme)
        self.assertIn("The plan names five kinds of paths:", readme)
        self.assertIn("迁移计划会明确列出五类路径：", chinese_readme)
        self.assertIn("Build your agent once. Carry it everywhere.", readme)
        self.assertIn("Explore the live product website", readme)
        self.assertIn("一次构建 agent，随处皆可运行。", chinese_readme)
        self.assertIn("查看在线产品网站", chinese_readme)
        self.assertLess(readme.index("assets/social-preview.png"), readme.index("## Start with your coding agent"))
        self.assertLess(chinese_readme.index("assets/social-preview.png"), chinese_readme.index("## 先交给 coding agent 代驾"))

        landing = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Packwright dovetail mark", landing)
        self.assertIn("Build your agent once. Carry it everywhere.", landing)
        self.assertIn("Three agent presets. Make each one your own.", landing)
        self.assertIn("Expert engineer:", landing)
        self.assertIn("Versatile assistant:", landing)
        self.assertIn("Personal secretary:", landing)
        self.assertIn("build a Claude Code target and migrate it to Codex", landing)
        self.assertIn('<span class="wm">Packwright</span>', landing)
        self.assertIn('>Packwright</text>', landing)
        self.assertIn('<span>Packwright · MIT</span>', landing)
        self.assertIn('<script src="demo.js" defer></script>', landing)
        self.assertTrue((ROOT / "site" / "demo.js").is_file())

        chinese_landing = (ROOT / "site" / "zh-CN.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="zh-CN"', chinese_landing)
        self.assertIn("一次构建 agent，", chinese_landing)
        self.assertIn("随处皆可运行。", chinese_landing)
        self.assertIn("三种预设 agent 模板，满足你多样的定制化需求。", chinese_landing)
        self.assertIn("天才工程师：", chinese_landing)
        self.assertIn("全能助手：", chinese_landing)
        self.assertIn("私人秘书：", chinese_landing)
        self.assertNotIn("无缝", chinese_landing)
        self.assertIn("自己掌舵，或让 agent 代驾", chinese_landing)
        self.assertIn('font-family:"Packwright Han Serif"', chinese_landing)
        self.assertIn('href="../assets/fonts/packwright-han-serif-600.otf"', chinese_landing)
        self.assertIn('"Packwright Han Serif","Songti SC"', chinese_landing)
        self.assertIsNone(
            re.search(r"\b(?:Agent|Runtime|Pack|Prompt|Target|Skills|Instruction)\b", chinese_landing)
        )
        self.assertIn('<script src="demo.js" defer></script>', chinese_landing)
        self.assertIn('href="index.html"', chinese_landing)
        self.assertIn('href="zh-CN.html"', landing)
        self.assertNotIn("Claude is selected by default", landing)
        self.assertNotIn("默认选择 Claude", chinese_landing)

        social_preview = (ROOT / "assets" / "social-preview.svg").read_text(encoding="utf-8")
        self.assertIn(">Packwright</text>", social_preview)
        self.assertIn("Pi  ·  Codex  ·  Claude Code  ·  Cursor", social_preview)
        self.assertIn("NATIVE PACKS · PORTABLE STATE · MIGRATION RECEIPTS", social_preview)

        self.assertIn(
            "Native packs. Portable state. Preview every migration before any files are written.",
            readme,
        )
        self.assertIn("原生 pack。可移植状态。每次迁移都先预览，再写入。", chinese_readme)

        public_copy = (readme, chinese_readme, landing, chinese_landing, social_preview)
        for document in public_copy:
            self.assertIsNone(re.search(r"\bClaude\b(?! Code)", document))
            self.assertNotIn("The output is files you can read", document)
            self.assertNotIn("输出是你可以直接阅读的普通文件", document)
            self.assertNotIn("输出结果皆为清晰可读的普通文件", document)

        for document in (landing, chinese_landing):
            self.assertLess(document.index('id="start"'), document.index('id="why"'))
            self.assertLess(document.index('id="migrate"'), document.index('id="quickstart"'))
            self.assertIn('<span class="wm">Packwright</span>', document)
            self.assertIn('>Packwright</text>', document)
            self.assertIn('<span>Packwright · MIT</span>', document)
            self.assertIn('data-adapter="claude-code"', document)
            self.assertIn('data-adapter="codex"', document)
            self.assertIn('data-adapter="cursor"', document)
            self.assertIn('data-adapter="pi"', document)
            self.assertIn('id="runtime-pi"', document)
            self.assertIn('id="runtime-pi" type="button" role="tab" aria-selected="true"', document)
            self.assertIn('data-adapter="claude-code"', document)
            self.assertIn('>Claude Code</button>', document)
            self.assertLess(document.index('data-adapter="pi"'), document.index('data-adapter="claude-code"'))
            self.assertIn("python -m pip install packwright==0.3.0", document)

        demo = (ROOT / "site" / "demo.js").read_text(encoding="utf-8")
        self.assertIn("const englishLines = [", demo)
        self.assertIn("const chineseLines = [", demo)
        self.assertIn('startsWith("zh")', demo)
        self.assertIn("pack compiled · checker score 100.0", demo)
        self.assertIn("pack 编译完成 · checker 评分 100.0", demo)
        self.assertIn("structure verified · operational readiness reported separately", demo)
        self.assertIn("结构已验证 · 运行就绪度另行报告", demo)
        self.assertNotIn("the output is files you can read", demo)
        self.assertIn('"packwright build work/nova --adapter pi -o pack/nova-pi"', demo)
        self.assertIn('"packwright build work/nova --adapter codex -o pack/nova-codex"', demo)
        self.assertIn('"packwright build work/nova --adapter cursor -o pack/nova-cursor"', demo)
        self.assertIn("packwright init --template code --name Nova", demo)
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
