import json
import subprocess
import tempfile
import unittest
from pathlib import Path

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


class RuntimeAutomationTest(unittest.TestCase):
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
