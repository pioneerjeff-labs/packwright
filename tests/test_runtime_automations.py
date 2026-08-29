import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from packwright.adapters import compile_adapter_pack
from packwright.checker import score_mechanism
from packwright.core import (
    PackwrightValidationError,
    adopt_existing,
    apply_adoption_review,
    apply_reconcile,
    doctor_target,
    generate_character_source_from_data,
    install_pack,
    load_mechanism,
    plan_reconcile,
    resolve_mechanism,
    verify_runtime_activation,
)
from packwright.core.pack_metadata import embed_pack_metadata


def _intake():
    return {
        "version": "0.1",
        "kind": "CharacterIntake",
        "character": {
            "name": "Rebecca",
            "slug": "rebecca",
            "user_name": "Morgan",
            "relationship": "work partner",
            "role": "Morgan's direct work partner.",
            "voice": "direct and steady",
            "avoid": ["empty reassurance"],
            "primary_work": ["plan work", "review decisions"],
            "relationship_continuity": "warm_selective",
            "traits": ["direct", "steady"],
        },
    }


def _source(root):
    source = Path(root) / "source"
    generate_character_source_from_data(_intake(), source)
    return source


def _embedded_pack(source, adapter):
    resolved = resolve_mechanism(load_mechanism(source))
    pack = compile_adapter_pack(adapter, resolved, references={"source_mechanism": str(source)})
    score = score_mechanism(resolved, pack, adapter=adapter)
    return resolved, embed_pack_metadata(pack, resolved, score)


def _write_pack(pack, directory):
    directory.mkdir(parents=True, exist_ok=True)
    for rel_path, text in pack.items():
        path = directory / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _runner_context(adapter, stdout):
    if adapter == "cursor":
        return json.loads(stdout)["additional_context"]
    if adapter == "codex":
        return json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
    return stdout.rstrip("\n")


def _codex_hook_input(target, transcript, native_event):
    return json.dumps(
        {
            "session_id": "test-session",
            "transcript_path": str(transcript),
            "cwd": str(target),
            "hook_event_name": native_event,
            "model": "test-model",
        }
    )


def _append_developer_context(transcript, context):
    transcript.parent.mkdir(parents=True, exist_ok=True)
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "developer",
                        "content": [{"type": "input_text", "text": context}],
                    },
                }
            )
            + "\n"
        )


class RuntimeAutomationTest(unittest.TestCase):
    def test_codex_rejects_unbounded_aggregate_event_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            resolved = resolve_mechanism(load_mechanism(source))
            resolved["automations"][0]["budget_bytes"] = 96_000
            with self.assertRaisesRegex(
                PackwrightValidationError,
                "codex session_start context budget",
            ):
                compile_adapter_pack("codex", resolved)
            compile_adapter_pack("claude-code", resolved)

    def test_codex_context_limit_and_installed_absolute_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            resolved = resolve_mechanism(load_mechanism(source))
            for adapter in ("claude-code", "codex", "cursor"):
                with self.subTest(adapter=adapter):
                    pack = compile_adapter_pack(adapter, resolved)
                    config_path = json.loads(pack["manifest.json"])[
                        "features"
                    ]["automations"]["config"]["path"]
                    config_text = pack[config_path]
                    if adapter == "codex":
                        config = json.loads(config_text)
                        handlers = [
                            handler
                            for groups in config["hooks"].values()
                            for group in groups
                            for handler in group["hooks"]
                        ]
                        self.assertTrue(handlers)
                        self.assertTrue(
                            all(handler["additionalContextLimit"] == 100000 for handler in handlers)
                        )
                    else:
                        self.assertNotIn("additionalContextLimit", config_text)

            _, pack = _embedded_pack(source, "codex")
            pack_dir = Path(tmpdir) / "pack"
            target = Path(tmpdir) / "target with spaces"
            _write_pack(pack, pack_dir)
            install_pack(pack_dir, target)
            hooks = json.loads((target / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
            absolute_runner = str(
                (target / ".codex" / "hooks" / "packwright_automation.py").resolve()
            )
            self.assertIn(shlex.quote(absolute_runner), command)
            self.assertNotIn("git rev-parse", command)
            nested = target / "nested" / "working"
            nested.mkdir(parents=True)
            result = subprocess.run(
                command,
                cwd=nested,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("[packwright:session-start-current-time]", result.stdout)
            output = json.loads(result.stdout)
            self.assertEqual(
                output["hookSpecificOutput"]["hookEventName"],
                "SessionStart",
            )

    def test_codex_activation_receipt_tracks_current_hook_digest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            _, pack = _embedded_pack(source, "codex")
            pack_dir = Path(tmpdir) / "pack"
            target = Path(tmpdir) / "target"
            _write_pack(pack, pack_dir)
            install_pack(pack_dir, target)
            runner = target / ".codex" / "hooks" / "packwright_automation.py"
            codex_home = Path(tmpdir) / "codex-home"
            transcript = codex_home / "sessions" / "2026" / "07" / "test.jsonl"

            before = doctor_target(target)
            self.assertFalse(before["readiness"]["operational_ready"])
            self.assertIn(
                "/hooks",
                " ".join(
                    before["readiness"]["layers"]["runtime_activation"]["reasons"]
                ),
            )

            manual = subprocess.run(
                ["python3", str(runner), "session_start"],
                cwd=target,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                json.loads(manual.stdout)["hookSpecificOutput"]["hookEventName"],
                "SessionStart",
            )
            incomplete = verify_runtime_activation(target, adapter="codex")
            self.assertFalse(incomplete["ok"], incomplete)
            self.assertFalse(
                (target / ".packwright" / "activation" / "codex-hooks.json").exists()
            )
            self.assertIn("activation stamp", incomplete["reasons"][0])

            session_start = subprocess.run(
                ["python3", str(runner), "session_start"],
                cwd=target,
                check=True,
                capture_output=True,
                text=True,
                input=_codex_hook_input(target, transcript, "SessionStart"),
            )
            session_context = _runner_context("codex", session_start.stdout)
            executed_only = verify_runtime_activation(target, adapter="codex")
            self.assertFalse(executed_only["ok"], executed_only)
            self.assertIn("user_prompt", executed_only["reasons"][0])

            prompt = subprocess.run(
                ["python3", str(runner), "user_prompt"],
                cwd=target,
                check=True,
                capture_output=True,
                text=True,
                input=_codex_hook_input(target, transcript, "UserPromptSubmit"),
            )
            prompt_context = _runner_context("codex", prompt.stdout)
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                not_delivered = verify_runtime_activation(target, adapter="codex")
            self.assertFalse(not_delivered["ok"], not_delivered)
            self.assertTrue(not_delivered["execution_verified"])
            self.assertFalse(not_delivered["delivery_verified"])
            self.assertIn("transcript does not exist", not_delivered["reasons"][0])

            _append_developer_context(transcript, session_context)
            _append_developer_context(transcript, prompt_context + " truncated")
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                changed_delivery = verify_runtime_activation(target, adapter="codex")
            self.assertFalse(changed_delivery["ok"], changed_delivery)
            self.assertIn("changed, truncated, or spilled", changed_delivery["reasons"][0])

            _append_developer_context(transcript, prompt_context)
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                verified = verify_runtime_activation(target, adapter="codex")
            self.assertTrue(verified["ok"], verified)
            self.assertTrue(verified["delivery_verified"])
            self.assertTrue(Path(verified["receipt"]).is_file())
            receipt_path = Path(verified["receipt"])
            receipt_path.unlink()
            receipt_victim = Path(tmpdir) / "activation-victim.txt"
            receipt_victim.write_text("do not truncate\n", encoding="utf-8")
            old_predictable_temp = receipt_path.with_suffix(".tmp")
            old_predictable_temp.symlink_to(receipt_victim)
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                verified_again = verify_runtime_activation(target, adapter="codex")
            self.assertTrue(verified_again["ok"], verified_again)
            self.assertEqual(receipt_victim.read_text(encoding="utf-8"), "do not truncate\n")
            self.assertTrue(receipt_path.is_file())
            self.assertTrue(old_predictable_temp.is_symlink())
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                after = doctor_target(target)
            self.assertEqual(
                after["readiness"]["layers"]["runtime_activation"]["status"],
                "passed",
            )

            hooks_path = target / ".codex" / "hooks.json"
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
            hooks["description"] = "user key outside the managed fragment"
            hooks_path.write_text(
                json.dumps(hooks, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                still_verified = doctor_target(target)
            self.assertEqual(
                still_verified["readiness"]["layers"]["runtime_activation"]["status"],
                "passed",
            )
            hooks["hooks"]["SessionStart"][0]["hooks"][0][
                "additionalContextLimit"
            ] = 1024
            hooks_path.write_text(
                json.dumps(hooks, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                changed = doctor_target(target)
            self.assertEqual(
                changed["readiness"]["layers"]["runtime_activation"]["status"],
                "attention_required",
            )

            hooks["hooks"]["SessionStart"][0]["hooks"][0][
                "additionalContextLimit"
            ] = 100000
            hooks_path.write_text(
                json.dumps(hooks, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            runner.write_text(runner.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                changed_runner = doctor_target(target)
            self.assertEqual(
                changed_runner["readiness"]["layers"]["runtime_activation"]["status"],
                "attention_required",
            )
            self.assertIn(
                "runner digest",
                " ".join(
                    changed_runner["readiness"]["layers"]["runtime_activation"]["reasons"]
                ),
            )

    def test_canonical_principles_are_the_single_entry_working_rules_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            principles = source / "operating" / "principles.md"
            principles.write_text(
                "# Rebecca Custom Principles\n\n"
                "## Hard Rules\n\n"
                "- CANONICAL-HOT-RULE\n"
                "- Run `packwright reconcile` when the installed projection is stale.\n",
                encoding="utf-8",
            )
            resolved = resolve_mechanism(load_mechanism(source))
            entry_paths = {
                "claude-code": "CLAUDE.md",
                "codex": "AGENTS.md",
                "cursor": ".cursor/rules/rebecca.mdc",
                "pi": "AGENTS.md",
            }
            for adapter, entry_path in entry_paths.items():
                with self.subTest(adapter=adapter):
                    pack = compile_adapter_pack(adapter, resolved)
                    entry = pack[entry_path]
                    self.assertIn("## Working Rules", entry)
                    self.assertIn("### Hard Rules", entry)
                    self.assertIn("CANONICAL-HOT-RULE", entry)
                    self.assertIn("`packwright reconcile`", entry)
                    self.assertNotIn("# Rebecca Custom Principles", entry)
                    self.assertNotIn(
                        "- Preserve the user's stated intent and scope.",
                        entry,
                    )
                    self.assertTrue(
                        score_mechanism(resolved, pack, adapter=adapter)["passed"]
                    )

            principles.write_text("", encoding="utf-8")
            fallback = compile_adapter_pack("codex", resolved)["AGENTS.md"]
            self.assertIn(
                "- Preserve the user's stated intent and scope.",
                fallback,
            )

    def test_entry_implementation_scope_matching_keeps_exact_case_semantics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            principles = source / "operating" / "principles.md"
            resolved = resolve_mechanism(load_mechanism(source))
            for token in ("Packwright", "MVP"):
                with self.subTest(token=token):
                    principles.write_text(
                        f"# Rebecca Principles\n\n- {token} implementation detail.\n",
                        encoding="utf-8",
                    )
                    pack = compile_adapter_pack("codex", resolved)
                    result = score_mechanism(resolved, pack, adapter="codex")
                    failed = {
                        check["id"]
                        for check in result["checks"]
                        if not check["passed"]
                    }
                    self.assertIn("entry_excludes_implementation_scope", failed)

    def test_memory_view_marks_utf8_truncation_within_budget_for_three_runners(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            resolved = resolve_mechanism(load_mechanism(source))
            budget = 128
            resolved["automations"] = [
                {
                    "id": "session-start-bounded-todos",
                    "scope": "local",
                    "event": "session_start",
                    "effect": "add_context",
                    "producer": {
                        "kind": "memory_view",
                        "source": "memory/todos.md",
                        "select": {"max_bytes": budget},
                    },
                    "budget_bytes": budget,
                }
            ]
            for adapter in ("claude-code", "codex", "cursor"):
                with self.subTest(adapter=adapter):
                    pack = compile_adapter_pack(adapter, resolved)
                    manifest = json.loads(pack["manifest.json"])
                    target = Path(tmpdir) / f"bounded-{adapter}"
                    _write_pack(pack, target)
                    todos = target / "memory" / "todos.md"
                    todos.write_text(("待办事项🙂\n" * 200), encoding="utf-8")
                    runner = target / manifest["features"]["automations"]["runner"]["path"]
                    result = subprocess.run(
                        ["python3", str(runner), "session_start"],
                        cwd=target,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    context = _runner_context(adapter, result.stdout)
                    if adapter == "codex":
                        context = context.split("\n", 1)[1]
                    header = "[packwright:session-start-bounded-todos]\n"
                    self.assertTrue(context.startswith(header), context)
                    payload = context[len(header):]
                    self.assertIn("[truncated: budget 128/", payload)
                    self.assertIn(
                        "read memory/todos.md for the rest]",
                        payload,
                    )
                    self.assertLessEqual(len(payload.encode("utf-8")), budget)

                    todos.write_text("short todo\n", encoding="utf-8")
                    short_result = subprocess.run(
                        ["python3", str(runner), "session_start"],
                        cwd=target,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    short_context = _runner_context(adapter, short_result.stdout)
                    if adapter == "codex":
                        short_context = short_context.split("\n", 1)[1]
                    self.assertNotIn("[truncated", short_context)
                    self.assertTrue(short_context.endswith("short todo"))

    def test_three_adapters_project_honest_local_capabilities_and_runners_execute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            for adapter in ("claude-code", "codex", "cursor"):
                resolved, pack = _embedded_pack(source, adapter)
                manifest = json.loads(pack["manifest.json"])
                records = manifest["features"]["automations"]["records"]
                user_prompt = [item for item in records if item["canonical_event"] == "user_prompt"]
                if adapter == "cursor":
                    self.assertTrue(all(item["status"] == "unavailable_missing_effect" for item in user_prompt))
                    self.assertNotIn("beforeSubmitPrompt", pack[".cursor/hooks.json"])
                else:
                    self.assertTrue(all(item["status"].startswith("projected") for item in user_prompt))

                pack_dir = Path(tmpdir) / f"pack-{adapter}"
                target = Path(tmpdir) / f"target-{adapter}"
                _write_pack(pack, pack_dir)
                install_pack(pack_dir, target)
                runner = target / manifest["features"]["automations"]["runner"]["path"]
                result = subprocess.run(
                    ["python3", str(runner), "session_start"],
                    cwd=target,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                if adapter == "cursor":
                    output = json.loads(result.stdout)
                    self.assertIn("current_time", output["additional_context"])
                else:
                    self.assertIn("[packwright:session-start-current-time]", result.stdout)
                    prompt_result = subprocess.run(
                        ["python3", str(runner), "user_prompt"],
                        cwd=target,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    self.assertIn("[packwright:user-prompt-current-todos]", prompt_result.stdout)
                self.assertEqual(
                    (target / ".packwright" / "baseline-path").read_text(encoding="utf-8").strip(),
                    str(target.resolve()),
                )
                self.assertEqual(resolved["version"], "0.8")

    def test_force_install_merges_only_managed_hook_entries_and_doctor_ignores_user_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            _, pack = _embedded_pack(source, "claude-code")
            pack_dir = Path(tmpdir) / "pack"
            target = Path(tmpdir) / "target"
            _write_pack(pack, pack_dir)
            settings = target / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "permissions": {"allow": ["Read"]},
                        "hooks": {
                            "SessionStart": [
                                {"hooks": [{"type": "command", "command": ".claude/hooks/user.sh"}]}
                            ]
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = install_pack(pack_dir, target, force=True)
            self.assertEqual(result["merged_managed_configs"], [".claude/settings.json"])
            merged = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(merged["permissions"], {"allow": ["Read"]})
            commands = json.dumps(merged["hooks"]["SessionStart"])
            self.assertIn("user.sh", commands)
            self.assertIn("packwright_automation.py", commands)

            merged["permissions"]["allow"].append("Glob")
            settings.write_text(json.dumps(merged) + "\n", encoding="utf-8")
            report = doctor_target(target)
            self.assertFalse(any(item.get("path") == ".claude/settings.json" for item in report["issues"]))

    def test_reconcile_upgrades_canonical_projection_and_preserves_state_and_user_hooks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            _, pack = _embedded_pack(source, "codex")
            pack_dir = Path(tmpdir) / "pack"
            target = Path(tmpdir) / "target"
            _write_pack(pack, pack_dir)
            install_pack(pack_dir, target)
            todos = target / "memory" / "todos.md"
            todos.write_text("# Current Actions\n\n- preserve me\n", encoding="utf-8")

            hooks_path = target / ".codex" / "hooks.json"
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
            hooks["hooks"].setdefault("SessionStart", []).append(
                {"hooks": [{"type": "command", "command": ".codex/hooks/user.sh"}]}
            )
            hooks_path.write_text(json.dumps(hooks) + "\n", encoding="utf-8")

            mechanism_path = source / "mechanism.yaml"
            mechanism = yaml.safe_load(mechanism_path.read_text(encoding="utf-8"))
            mechanism["automations"].append(
                {
                    "id": "user-prompt-fresh-clock",
                    "scope": "local",
                    "event": "user_prompt",
                    "effect": "add_context",
                    "producer": {
                        "kind": "freshness_facts",
                        "facts": [{"field": "prompt_time", "source": "system_datetime"}],
                    },
                    "budget_bytes": 512,
                }
            )
            mechanism_path.write_text(
                yaml.safe_dump(mechanism, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )

            plan = plan_reconcile(target, source)
            report = plan.to_dict()
            self.assertNotEqual(report["spec"]["from_sha256"], report["spec"]["to_sha256"])
            self.assertTrue(report["changes"]["manual_merges"])
            receipt = apply_reconcile(plan)
            self.assertTrue(receipt["ok"], receipt)
            self.assertIn("preserve me", todos.read_text(encoding="utf-8"))
            reconciled_hooks = hooks_path.read_text(encoding="utf-8")
            self.assertIn("user.sh", reconciled_hooks)
            runner = target / ".codex" / "hooks" / "packwright_automation.py"
            self.assertIn("user-prompt-fresh-clock", runner.read_text(encoding="utf-8"))
            self.assertTrue(Path(receipt["receipt"]).is_file())

    def test_reconcile_installed_score_reads_live_portable_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            _, pack = _embedded_pack(source, "codex")
            pack_dir = Path(tmpdir) / "pack"
            target = Path(tmpdir) / "target"
            _write_pack(pack, pack_dir)
            install_pack(pack_dir, target)
            (target / "memory" / "session-index.md").write_text(
                "# Session Index\n\nNo usable empty or live state.\n",
                encoding="utf-8",
            )

            plan = plan_reconcile(target, source)
            self.assertTrue(plan.to_dict()["score"]["planned"]["passed"])
            receipt = apply_reconcile(plan)
            self.assertTrue(receipt["doctor"]["ok"], receipt)
            self.assertFalse(receipt["score"]["installed"]["passed"], receipt)
            self.assertTrue(receipt["ok"], receipt)
            self.assertFalse(receipt["installed_score_passed"], receipt)
            self.assertTrue(receipt["doctor_ok"], receipt)
            self.assertTrue(receipt["verification_attention"], receipt)
            failed = {
                check["id"]
                for check in receipt["score"]["installed"]["checks"]
                if not check["passed"]
            }
            self.assertIn("empty_memory_skeleton_is_user_ready", failed)

    def test_generated_codex_hook_does_not_follow_old_pid_temp_symlink(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            _, pack = _embedded_pack(source, "codex")
            pack_dir = Path(tmpdir) / "pack"
            target = Path(tmpdir) / "target"
            _write_pack(pack, pack_dir)
            install_pack(pack_dir, target)
            runner = target / ".codex/hooks/packwright_automation.py"
            spec = importlib.util.spec_from_file_location("installed_packwright_automation", runner)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            stamp = target / ".packwright/activation/codex-hooks.json"
            stamp.parent.mkdir(parents=True, exist_ok=True)
            victim = Path(tmpdir) / "hook-victim.txt"
            victim.write_text("do not truncate\n", encoding="utf-8")
            old_predictable_temp = stamp.with_name(stamp.name + ".4242.tmp")
            old_predictable_temp.symlink_to(victim)
            with mock.patch.object(module.os, "getpid", return_value=4242):
                module.record_activation(
                    target,
                    "session_start",
                    "context",
                    {
                        "hook_event_name": "SessionStart",
                        "session_id": "atomic-test-session",
                    },
                    "delivery-marker",
                )

            self.assertEqual(victim.read_text(encoding="utf-8"), "do not truncate\n")
            self.assertTrue(stamp.is_file())
            self.assertTrue(old_predictable_temp.is_symlink())

    def test_reconcile_dry_run_matches_hash_changed_write_set(self):
        def hashes(root):
            return {
                path.relative_to(root).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in root.rglob("*")
                if path.is_file()
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            _, pack = _embedded_pack(source, "claude-code")
            pack_dir = Path(tmpdir) / "pack"
            installed = Path(tmpdir) / "installed"
            target = Path(tmpdir) / "moved"
            _write_pack(pack, pack_dir)
            install_pack(pack_dir, installed)
            installed.rename(target)

            settings_path = target / ".claude" / "settings.json"
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            settings["user_setting"] = {"preserve": True}
            settings_path.write_text(
                json.dumps(settings, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            before = hashes(target)
            plan = plan_reconcile(target, source)
            report = plan.to_dict()
            managed = {
                item["path"]
                for item in report["changes"]["managed_projection_updates"]
            }
            structural = {
                item["path"]
                for item in report["changes"][
                    "safe_structural_memory_migrations"
                ]
            }
            removed = {
                item["path"]
                for item in report["changes"]["removed_managed_artifacts"]
            }
            side_effects = {
                item["path"]
                for item in report["changes"]["side_effect_writes"]
            }
            planned_changed = managed | structural | removed | side_effects
            self.assertIn(".claude/settings.json", planned_changed)
            self.assertIn(".packwright/baseline-path", planned_changed)
            self.assertTrue(
                any(
                    item["reason"] == "reanchor_relocation_baseline"
                    for item in report["changes"]["side_effect_writes"]
                )
            )
            self.assertTrue(
                any(
                    warning["id"] == "relocation_baseline_reanchor"
                    for warning in report["warnings"]
                )
            )
            receipt = apply_reconcile(plan)
            self.assertTrue(receipt["ok"], receipt)
            after = hashes(target)
            actual_changed = {
                path
                for path in set(before) | set(after)
                if before.get(path) != after.get(path)
            }
            self.assertEqual(planned_changed, actual_changed)

    def test_reconcile_applies_source_only_save_context_as_managed_update(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            _, pack = _embedded_pack(source, "codex")
            pack_dir = Path(tmpdir) / "pack"
            target = Path(tmpdir) / "target"
            _write_pack(pack, pack_dir)
            install_pack(pack_dir, target)

            marker = "CANONICAL-SOURCE-ONLY-UPDATE"
            source_skill = source / "skills" / "save-context" / "SKILL.md"
            source_skill.write_text(
                source_skill.read_text(encoding="utf-8") + f"\n{marker}\n",
                encoding="utf-8",
            )

            plan = plan_reconcile(target, source)
            report = plan.to_dict()
            self.assertEqual(report["spec"]["from_sha256"], report["spec"]["to_sha256"])
            managed_updates = {
                item["path"]: item["operation"]
                for item in report["changes"]["managed_projection_updates"]
            }
            self.assertEqual(
                managed_updates[".agents/skills/rebecca-save-context/SKILL.md"], "update"
            )
            self.assertEqual(
                managed_updates[".packwright/source/skills/save-context/SKILL.md"], "update"
            )
            self.assertTrue(report["ready"], report)

            receipt = apply_reconcile(plan)
            self.assertTrue(receipt["ok"], receipt)
            self.assertIn(
                marker,
                (target / ".agents" / "skills" / "rebecca-save-context" / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertIn(
                marker,
                (target / ".packwright" / "source" / "skills" / "save-context" / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertTrue(doctor_target(target)["ok"])

    def test_doctor_refuses_pre_reconcile_repair_that_would_break_the_old_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            _, pack = _embedded_pack(source, "codex")
            projected_path = ".agents/skills/rebecca-save-context/SKILL.md"
            legacy_projection = "# Legacy managed save-context projection\n"
            pack[projected_path] = legacy_projection
            lock = json.loads(pack[".packwright/lock.json"])
            lock["artifacts"][projected_path] = hashlib.sha256(
                legacy_projection.encode("utf-8")
            ).hexdigest()
            pack[".packwright/lock.json"] = json.dumps(lock, indent=2, sort_keys=True) + "\n"

            pack_dir = Path(tmpdir) / "legacy-pack"
            target = Path(tmpdir) / "target"
            _write_pack(pack, pack_dir)
            install_pack(pack_dir, target)
            self.assertTrue(doctor_target(target)["ok"])

            projected = target / projected_path
            projected.write_text("# manual drift\n", encoding="utf-8")
            report = doctor_target(target, fix=True)
            self.assertFalse(report["ok"])
            self.assertIn("managed_artifact_drift", {item["id"] for item in report["issues"]})
            self.assertFalse(
                any(item["id"] == "managed_artifact_drift_repaired" for item in report["fixes"])
            )
            self.assertEqual(projected.read_text(encoding="utf-8"), "# manual drift\n")

    def test_adopt_can_create_evidence_only_automation_canonicalization_draft(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "legacy"
            target = Path(tmpdir) / "target"
            config = source / ".claude" / "settings.json"
            config.parent.mkdir(parents=True)
            config.write_text(
                json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "date"}]}]}}),
                encoding="utf-8",
            )
            target.mkdir()
            adoption = adopt_existing(source, target, dry_run=False)
            review_path = Path(adoption["review_queue_yaml"])
            review = yaml.safe_load(review_path.read_text(encoding="utf-8"))
            candidate = next(item for item in review["items"] if item["source"] == ".claude/settings.json")
            self.assertEqual(candidate["category"], "automation_candidate")
            candidate["decision"] = "manual_automation_merge"
            candidate["rationale"] = "Preserve intent for manual canonical review."
            review_path.write_text(
                yaml.safe_dump(review, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
            receipt = apply_adoption_review(review_path, target)
            draft_path = target / receipt["automation_draft"]["path"]
            draft = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
            self.assertFalse(draft["policy"]["reverse_compilation"])
            self.assertEqual(draft["canonical_automations"], [])
            self.assertEqual(draft["evidence"][0]["path"], ".claude/settings.json")


if __name__ == "__main__":
    unittest.main()
