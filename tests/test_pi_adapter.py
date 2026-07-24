import json
import tempfile
import unittest
from pathlib import Path

import yaml

from packwright.adapters import compile_adapter_pack
from packwright.checker import score_mechanism
from packwright.core import (
    PackwrightValidationError,
    apply_migration,
    doctor_target,
    generate_character_source_from_data,
    install_pack,
    load_mechanism,
    plan_install,
    plan_migration,
    resolve_mechanism,
)
from packwright.core.pack_metadata import embed_pack_metadata
from packwright.core.runtime_automation import (
    discover_unmanaged_runtime_automation_assets,
)


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
    pack = compile_adapter_pack(
        adapter,
        resolved,
        references={"source_mechanism": str(source)},
    )
    score = score_mechanism(resolved, pack, adapter=adapter)
    return resolved, embed_pack_metadata(pack, resolved, score)


def _write_pack(pack, directory):
    directory.mkdir(parents=True, exist_ok=True)
    for rel_path, text in pack.items():
        path = directory / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class PiAdapterTest(unittest.TestCase):
    def test_pi_core_pack_uses_native_context_and_skills_with_explicit_boundaries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            resolved = resolve_mechanism(load_mechanism(source))
            pack = compile_adapter_pack("pi", resolved)
            score = score_mechanism(resolved, pack, adapter="pi")
            manifest = json.loads(pack["manifest.json"])

            self.assertTrue(score["passed"], score)
            self.assertEqual(score["score"], 100.0)
            self.assertEqual(score["scope"], "managed_structure")
            self.assertIsNone(score["readiness"]["operational_ready"])
            self.assertEqual(score["readiness"]["status"], "not_evaluated")
            self.assertEqual(manifest["kind"], "PiAdapterPack")
            self.assertIn("AGENTS.md", pack)
            self.assertIn(".agents/skills/rebecca-save-context/SKILL.md", pack)
            self.assertTrue(
                any(path.startswith(".pi/rebecca/references/") for path in pack)
            )
            self.assertNotIn(".pi/settings.json", pack)
            self.assertFalse(any(path.startswith(".pi/extensions/") for path in pack))

            trust = manifest["features"]["project_trust"]
            self.assertTrue(trust["required_for_project_resources"])
            self.assertEqual(trust["interactive_activation"], "/trust")
            self.assertEqual(trust["non_interactive_activation"], "pi --approve")
            self.assertEqual(manifest["boundaries"]["pi_extensions"], "not_projected")
            self.assertEqual(
                manifest["boundaries"]["emotion_engine_runtime"],
                "unavailable_no_builtin_mcp",
            )
            automation = manifest["features"]["automations"]
            self.assertIsNone(automation["config"]["path"])
            self.assertIsNone(automation["runner"]["path"])
            self.assertTrue(automation["records"])
            self.assertTrue(
                all(
                    record["status"] == "unavailable_requires_extension"
                    for record in automation["records"]
                )
            )

    def test_pi_install_and_doctor_require_runtime_trust_without_fake_hooks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _source(tmpdir)
            _, pack = _embedded_pack(source, "pi")
            pack_dir = Path(tmpdir) / "pack"
            target = Path(tmpdir) / "target"
            _write_pack(pack, pack_dir)

            result = install_pack(pack_dir, target)
            self.assertEqual(result["adapter"], "pi")
            self.assertFalse((target / ".packwright" / "baseline-path").exists())
            self.assertFalse((target / ".pi" / "settings.json").exists())
            report = doctor_target(target)
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["scope"], "managed_projection")
            self.assertFalse(report["readiness"]["operational_ready"])
            self.assertEqual(report["readiness"]["status"], "attention_required")
            self.assertEqual(
                report["readiness"]["layers"]["runtime_activation"]["status"],
                "attention_required",
            )
            self.assertIn(
                "pi_project_trust_unverified",
                {warning["id"] for warning in report["warnings"]},
            )

            with self.assertRaisesRegex(
                PackwrightValidationError,
                "Emotion Engine runtime is unavailable for pi",
            ):
                plan_install(
                    pack_dir,
                    Path(tmpdir) / "target-with-emotion",
                    include_emotion_engine=True,
                )

    def test_codex_to_pi_migration_requires_explicit_capability_gap_acceptance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _source(root)
            _, codex_pack = _embedded_pack(source, "codex")
            source_pack = root / "codex-pack"
            source_target = root / "codex-target"
            pi_target = root / "pi-target"
            codex_roundtrip = root / "codex-roundtrip"
            _write_pack(codex_pack, source_pack)
            install_pack(source_pack, source_target)

            plan = plan_migration(source_target, pi_target, to_adapter="pi")
            report = plan.to_dict()
            degraded = report["changes"]["degraded"]
            self.assertTrue(report["ready"], report)
            self.assertTrue(degraded)
            self.assertTrue(
                all(
                    item["kind"] == "canonical_runtime_capability_gap"
                    for item in degraded
                )
            )
            self.assertEqual(
                report["required_confirmations"][0]["automations"],
                [item["automation_id"] for item in degraded],
            )
            with self.assertRaisesRegex(
                PackwrightValidationError,
                "explicitly accept the behavior gap",
            ):
                apply_migration(plan)

            result = apply_migration(plan, accept_degraded=True)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["status"], "applied_with_degradations")
            self.assertEqual(result["score"]["installed"]["score"], 100.0)

            live_note = pi_target / "memory" / "todos.md"
            live_note.write_text(
                live_note.read_text(encoding="utf-8") + "\n- keep this through Pi\n",
                encoding="utf-8",
            )
            reverse = plan_migration(pi_target, codex_roundtrip, to_adapter="codex")
            self.assertFalse(reverse.to_dict()["changes"]["degraded"])
            reverse_result = apply_migration(reverse)
            self.assertTrue(reverse_result["ok"], reverse_result)
            self.assertIn(
                "keep this through Pi",
                (codex_roundtrip / "memory" / "todos.md").read_text(encoding="utf-8"),
                )

    def test_doctor_surfaces_pending_adoption_without_changing_structural_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _source(root)
            _, pack = _embedded_pack(source, "claude-code")
            pack_dir = root / "pack"
            target = root / "target"
            _write_pack(pack, pack_dir)
            install_pack(pack_dir, target)
            review_path = (
                target
                / "workspace"
                / "shared"
                / "artifacts"
                / "migrations"
                / "adoption-review-existing.yaml"
            )
            review_path.parent.mkdir(parents=True, exist_ok=True)
            review_path.write_text(
                yaml.safe_dump(
                    {
                        "schema": "packwright-adoption-review/v1",
                        "items": [
                            {"source": "memory/todos.md", "decision": "pending"},
                            {"source": "docs/notes.md", "decision": "exclude"},
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            report = doctor_target(target)

            self.assertTrue(report["ok"], report)
            self.assertFalse(report["readiness"]["operational_ready"])
            workflow = report["readiness"]["layers"]["workflow_acceptance"]
            self.assertEqual(workflow["status"], "attention_required")
            self.assertEqual(workflow["pending_items"], 1)

    def test_pi_project_extensions_are_detected_as_unmanaged_automation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            settings = target / ".pi" / "settings.json"
            extension = target / ".pi" / "extensions" / "fresh-context.ts"
            extension.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps({"extensions": ["extensions/extra.ts"]}) + "\n",
                encoding="utf-8",
            )
            extension.write_text(
                'export default (pi) => pi.on("session_start", () => {});',
                encoding="utf-8",
            )

            assets = discover_unmanaged_runtime_automation_assets(target, "pi")
            by_path = {item["path"]: item for item in assets}
            self.assertEqual(
                by_path[".pi/settings.json"]["events"],
                ["pi_extension"],
            )
            self.assertEqual(
                by_path[".pi/extensions/fresh-context.ts"]["role"],
                "supporting_asset_candidate",
            )

    def test_all_twelve_directed_adapter_migrations_plan_at_full_score(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _source(root)
            adapters = ("codex", "claude-code", "cursor", "pi")
            installed = {}
            for adapter in adapters:
                _, pack = _embedded_pack(source, adapter)
                pack_dir = root / f"pack-{adapter}"
                target = root / f"target-{adapter}"
                _write_pack(pack, pack_dir)
                install_pack(pack_dir, target)
                installed[adapter] = target

            paths = []
            for from_adapter in adapters:
                for to_adapter in adapters:
                    if from_adapter == to_adapter:
                        continue
                    destination = root / f"migrate-{from_adapter}-to-{to_adapter}"
                    report = plan_migration(
                        installed[from_adapter],
                        destination,
                        to_adapter=to_adapter,
                    ).to_dict()
                    paths.append((from_adapter, to_adapter))
                    self.assertTrue(report["ready"], report)
                    self.assertEqual(report["score"]["planned"]["score"], 100.0)
                    gaps = [
                        item
                        for item in report["changes"]["degraded"]
                        if item.get("kind") == "canonical_runtime_capability_gap"
                    ]
                    self.assertEqual(bool(gaps), to_adapter == "pi")

            self.assertEqual(len(paths), 12)


if __name__ == "__main__":
    unittest.main()
