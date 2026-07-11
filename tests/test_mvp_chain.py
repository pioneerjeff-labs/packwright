import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from packwright.adapters import compile_to_claude_code_pack, compile_to_codex_pack, compile_to_cursor_pack
from packwright.checker import score_mechanism
from packwright.core import (
    PackwrightValidationError,
    adopt_existing,
    apply_migration,
    create_handoff,
    doctor_target,
    generate_character_template,
    generate_character_template_from_data,
    install_pack,
    load_mechanism,
    migrate_target,
    plan_migration,
    refresh_emotion_engine_codex,
    resolve_mechanism,
    starter_character_intake,
    validate_mechanism,
)
from packwright.core.handoff import (
    DEFAULT_HANDOFF_DIR,
    DEFAULT_SESSION_BRIEF_DIR,
    HANDOFF_HELPER_PATH,
    HANDOFF_SCHEMA,
    HANDOFF_WRAPPER_PATH,
)
from packwright.core.workspace_contract import (
    WORKSPACE_DOMAIN_TEMPLATE_DIR,
    WORKSPACE_LAYOUT,
    workspace_artifacts,
)


MECHANISM_PATH = PROJECT_ROOT / "templates" / "atlas-work" / "mechanism.yaml"


class MvpChainTest(unittest.TestCase):
    def test_atlas_mechanism_validates(self):
        data = load_mechanism(MECHANISM_PATH)
        self.assertIs(validate_mechanism(data), data)

    def test_resolve_applies_parameter_overrides(self):
        data = load_mechanism(MECHANISM_PATH)
        resolved = resolve_mechanism(
            data,
            {
                "task": "Build a Codex adapter pack.",
                "scope": "Keep other runtimes reserved.",
            },
        )

        self.assertEqual(resolved["run"]["objective"], "Build a Codex adapter pack.")
        self.assertEqual(resolved["run"]["scope"], "Keep other runtimes reserved.")
        self.assertEqual(resolved["resolved_parameters"]["task"], "Build a Codex adapter pack.")

    def test_compile_to_codex_pack_has_architecture_layers(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved)

        self.assertIn("AGENTS.md", pack)
        self.assertIn(".agents/skills/atlas-save-context/SKILL.md", pack)
        self.assertIn(".codex/atlas/references/projection/ownership-contract.yaml", pack)
        self.assertIn("memory/index.md", pack)
        self.assertIn("memory/profile.md", pack)
        self.assertIn("memory/session-index.md", pack)
        self.assertIn("memory/source-map.md", pack)
        self.assertIn("memory/collaboration.md", pack)
        self.assertIn("memory/pinned.md", pack)
        self.assertIn("memory/workstreams.md", pack)
        self.assertIn("memory/workstreams/_template.md", pack)
        self.assertIn("memory/projects/_template.md", pack)
        self.assertIn("memory/relationship-state.md", pack)
        self.assertIn("memory/emotion-state.json.example", pack)
        self.assertIn("knowledge/index.md", pack)
        self.assertIn("knowledge/manifest.json", pack)
        self.assertIn("sources/local/manifest.json", pack)
        self.assertIn("sources/notion/manifest.json", pack)
        self.assertIn("sources/repos/manifest.json", pack)
        self.assertIn("sources/web/manifest.json", pack)
        for artifact in workspace_artifacts():
            self.assertIn(artifact, pack)
        self.assertIn("manifest.json", pack)
        self.assertNotIn("workspace/<domain>/drafts|artifacts|archive", pack["memory/source-map.md"])

        self.assertIn("You are Atlas.", pack["AGENTS.md"])
        self.assertIn("Atlas helps Morgan", pack["AGENTS.md"])
        self.assertIn("## Voice", pack["AGENTS.md"])
        self.assertIn(".agents/skills/atlas-save-context/SKILL.md", pack["AGENTS.md"])
        self.assertNotIn(resolved["run"]["objective"], pack["AGENTS.md"])
        self.assertNotIn("Packwright", pack["AGENTS.md"])
        self.assertNotIn("MVP", pack["AGENTS.md"])
        self.assertIn("## Work Focus", pack["AGENTS.md"])
        self.assertIn("## Personality", pack["AGENTS.md"])
        self.assertIn("## Working Rules", pack["AGENTS.md"])
        self.assertNotIn("## Stable Presence", pack["AGENTS.md"])
        self.assertNotIn("## Entry Boundary", pack["AGENTS.md"])
        self.assertIn("## Procedure", pack[".agents/skills/atlas-save-context/SKILL.md"])
        self.assertIn("## Boundary Notes", pack[".agents/skills/atlas-save-context/SKILL.md"])
        self.assertNotIn("Codex Projection Notes", pack[".agents/skills/atlas-save-context/SKILL.md"])
        self.assertNotIn(".agents/skills/atlas-recent-activity/SKILL.md", pack)
        self.assertNotIn(".agents/skills/atlas-fact-check/SKILL.md", pack)
        self.assertNotIn("SessionStart", pack["AGENTS.md"])
        self.assertNotIn("@memory/recent-activity.md", pack["AGENTS.md"])
        self.assertNotIn("memory/emotion-state.json.example", pack["AGENTS.md"])
        self.assertIn("memory/index.md", pack["AGENTS.md"])
        self.assertIn("memory/profile.md", pack["AGENTS.md"])
        self.assertIn("memory/workstreams.md", pack["AGENTS.md"])
        self.assertIn("memory/session-index.md", pack["AGENTS.md"])
        self.assertIn("memory/source-map.md", pack["AGENTS.md"])
        self.assertIn("knowledge/index.md", pack["AGENTS.md"])
        self.assertIn("sources/*/manifest.json", pack["AGENTS.md"])
        self.assertIn("memory/collaboration.md", pack["AGENTS.md"])
        self.assertIn("memory/projects/<slug>.md", pack["AGENTS.md"])
        self.assertIn("Treat file reads as internal work", pack["AGENTS.md"])
        self.assertIn("When memory is empty", pack["AGENTS.md"])

        manifest = json.loads(pack["manifest.json"])
        self.assertEqual(manifest["features"]["emotion_engine"]["default_mode"], "light")
        self.assertEqual(manifest["features"]["emotion_engine"]["mode"], "light")
        self.assertFalse(manifest["features"]["emotion_engine"]["installed"])
        self.assertEqual(
            manifest["features"]["memory"]["workstream_load_policy"],
            "load_router_then_relevant_detail",
        )
        self.assertEqual(manifest["features"]["workspace"]["layout"], WORKSPACE_LAYOUT)
        self.assertEqual(manifest["features"]["workspace"]["domain_template"], WORKSPACE_DOMAIN_TEMPLATE_DIR)
        self.assertEqual(manifest["features"]["knowledge"]["root"], "knowledge")
        self.assertEqual(manifest["features"]["knowledge"]["recall_index"], "knowledge/index.md")
        self.assertIn("memory/index.md", manifest["features"]["memory"]["core_files"])

    def test_character_intake_generates_template_that_compiles_and_scores(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            intake_path = root / "character_intake.yaml"
            out_dir = root / "templates" / "mira-work"
            intake_path.write_text(
                """version: "0.1"
kind: CharacterIntake
character:
  name: Mira
  user_name: Morgan
  relationship: research partner
  role: Morgan's direct research partner for synthesis, critique, and follow-through.
  voice: calm, exact, lightly warm, not over-compliant
  avoid:
    - mechanical audit-log replies
    - decorative warmth
  primary_work:
    - synthesize research notes into decisions
    - challenge weak assumptions before plans harden
    - keep follow-up work explicit
  direct_emotional_interaction: some_direct_emotional_interaction
""",
                encoding="utf-8",
            )

            generated = generate_character_template(intake_path, out_dir=out_dir)
            self.assertEqual(generated["character"], "Mira")
            self.assertEqual(generated["direct_emotional_interaction"], "some_direct_emotional_interaction")

            resolved = resolve_mechanism(load_mechanism(out_dir / "mechanism.yaml"))
            pack = compile_to_codex_pack(resolved)
            manifest = json.loads(pack["manifest.json"])

            self.assertIn("You are Mira.", pack["AGENTS.md"])
            self.assertNotIn("You are Atlas.", pack["AGENTS.md"])
            self.assertIn(".agents/skills/mira-save-context/SKILL.md", pack)
            self.assertIn(".codex/mira/references/identity/persona.md", pack)
            self.assertEqual(manifest["character"]["slug"], "mira")
            self.assertEqual(
                manifest["character"]["direct_emotional_interaction"],
                "some_direct_emotional_interaction",
            )
            self.assertEqual(manifest["character"]["relationship_continuity"], "warm_selective")
            self.assertEqual(manifest["features"]["emotion_engine"]["mode"], "light")

            result = score_mechanism(resolved, pack, adapter="codex")
            self.assertTrue(result["passed"], result)
            self.assertEqual(result["score"], 100.0)

    def test_starter_companion_template_generates_clean_lumen_work_spec(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            out_dir = root / "lumen-work"
            intake = starter_character_intake("lumen", user_name="Morgan")

            generated = generate_character_template_from_data(intake, out_dir=out_dir)
            self.assertEqual(generated["character"], "Lumen")
            self.assertEqual(generated["slug"], "lumen")
            self.assertEqual(generated["recommended_emotion_engine_mode"], "always")

            resolved = resolve_mechanism(load_mechanism(out_dir / "mechanism.yaml"))
            self.assertEqual(resolved["metadata"]["archetype"], "companion")
            self.assertEqual(resolved["identity"]["user_name"], "Morgan")
            self.assertEqual(resolved["emotion"]["recommended_mode"], "always")

            cursor_pack = compile_to_cursor_pack(resolved)
            self.assertIn(".cursor/rules/lumen.mdc", cursor_pack)
            result = score_mechanism(resolved, cursor_pack, adapter="cursor")
            self.assertTrue(result["passed"], result)

    def test_character_intake_uses_explicit_slug_for_non_latin_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            intake_path = root / "system-intake.yaml"
            out_dir = root / "system-work"
            intake_path.write_text(
                """version: "0.1"
kind: CharacterIntake
character:
  name: Planner
  slug: system
  user_name: Morgan
  relationship: personal system
  role: Morgan's direct personal system for planning and execution.
  voice: simple, direct, playful, execution-focused
  primary_work:
    - plan technical work
    - keep project state organized
  relationship_continuity: warm_selective
""",
                encoding="utf-8",
            )

            generated = generate_character_template(intake_path, out_dir=out_dir)
            self.assertEqual(generated["slug"], "system")

            resolved = resolve_mechanism(load_mechanism(out_dir / "mechanism.yaml"))
            self.assertEqual(resolved["identity"]["slug"], "system")
            self.assertEqual(resolved["metadata"]["slug"], "system")

            cursor_pack = compile_to_cursor_pack(resolved)
            manifest = json.loads(cursor_pack["manifest.json"])
            self.assertIn(".cursor/rules/system.mdc", cursor_pack)
            self.assertIn(".cursor/rules/system-save-context.mdc", cursor_pack)
            self.assertIn(HANDOFF_HELPER_PATH, cursor_pack)
            self.assertIn(HANDOFF_WRAPPER_PATH, cursor_pack)
            self.assertIn(".cursor/system/references/identity/persona.md", cursor_pack)
            self.assertEqual(manifest["character"]["slug"], "system")
            self.assertEqual(manifest["features"]["handoff"]["schema"], HANDOFF_SCHEMA)
            self.assertEqual(manifest["local_tools"]["handoff_export"]["command"], HANDOFF_WRAPPER_PATH)

    def test_character_intake_canonicalizes_legacy_decide_later_direct_emotion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            intake_path = root / "character_intake.yaml"
            out_dir = root / "templates" / "legacy-work"
            intake_path.write_text(
                """version: "0.1"
kind: CharacterIntake
character:
  name: Legacy
  user_name: Morgan
  relationship: work partner
  role: Morgan's work partner for planning and review.
  voice: direct, calm, lightly warm
  primary_work:
    - plan technical work
  direct_emotional_interaction: decide_later
""",
                encoding="utf-8",
            )

            generated = generate_character_template(intake_path, out_dir=out_dir)

            self.assertEqual(generated["relationship_continuity"], "warm_selective")
            self.assertEqual(generated["direct_emotional_interaction"], "some_direct_emotional_interaction")

            resolved = resolve_mechanism(load_mechanism(out_dir / "mechanism.yaml"))
            self.assertEqual(resolved["emotion"]["relationship_continuity"], "warm_selective")
            self.assertEqual(resolved["emotion"]["direct_interaction"], "some_direct_emotional_interaction")

    def test_companion_intake_maps_relationship_continuity_to_workstreams_and_always_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            intake_path = root / "lumen-intake.yaml"
            out_dir = root / "lumen-work"
            pack_dir = root / "pack"
            target_dir = root / "target"
            sidecar_source = root / "emotion-engine-codex"
            intake_path.write_text(
                """version: "0.1"
kind: CharacterIntake
character:
  name: Lumen
  user_name: Morgan
  relationship: supportive lifestyle planning companion
  archetype: companion
  role: Morgan's planning companion for schedules, daily-life logistics, clothing choices, and fictional travel itineraries.
  voice: warm, lightly assertive, occasionally playful, practical without becoming generic
  avoid:
    - generic assistant tone
    - letting closeness overwhelm practical help
  primary_work:
    - plan a fictional weekly schedule and routines
    - help solve day-to-day life problems
    - recommend clothing, styling, and shopping choices
    - suggest travel destinations and trip plans
    - give practical advice while respecting stated preferences
  relationship_continuity: close_continuous
  traits:
    - warm
    - observant
    - practical
""",
                encoding="utf-8",
            )

            generated = generate_character_template(intake_path, out_dir=out_dir)
            self.assertEqual(generated["relationship_continuity"], "close_continuous")
            self.assertEqual(generated["direct_emotional_interaction"], "some_direct_emotional_interaction")
            self.assertEqual(generated["recommended_emotion_engine_mode"], "always")

            resolved = resolve_mechanism(load_mechanism(out_dir / "mechanism.yaml"))
            self.assertEqual(resolved["emotion"]["recommended_mode"], "always")
            self.assertEqual(resolved["emotion"]["relationship_continuity"], "close_continuous")

            pack = compile_to_codex_pack(resolved)
            manifest = json.loads(pack["manifest.json"])
            self.assertEqual(manifest["features"]["emotion_engine"]["mode"], "always")
            self.assertEqual(manifest["boundaries"]["emotion_engine_mode"], "always")
            self.assertEqual(manifest["character"]["relationship_continuity"], "close_continuous")
            self.assertIn("### 1. Schedule And Routines", pack["memory/workstreams.md"])
            self.assertIn("### 3. Style And Shopping", pack["memory/workstreams.md"])
            self.assertNotIn("### 1. plan Morgan", pack["memory/workstreams.md"])

            _write_pack(pack, pack_dir)
            _write_fake_emotion_engine_sidecar(sidecar_source)
            install_pack(
                pack_dir,
                target_dir,
                adapter="codex",
                include_emotion_engine_codex=True,
                emotion_engine_codex_source=sidecar_source,
            )
            state = json.loads((target_dir / ".emotion-engine" / "codex-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["runtime_mode"], "always")
            self.assertEqual(state["volatility_profile"], "expressive")
            self.assertGreater(state["personality_baseline"]["pleasure"], 0.3)
            self.assertGreater(state["personality_baseline"]["dominance"], 0.55)
            self.assertEqual(state["affective_pulse"]["intensity"], 0.0)
            target_manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(target_manifest["features"]["emotion_engine"]["mode"], "always")
            self.assertEqual(target_manifest["boundaries"]["emotion_engine_mode"], "always")

    def test_cli_draft_character_outputs_llm_interviewer_contract(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "interviewer.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "draft-character",
                    "--user-name",
                    "Morgan",
                    "--prompt-out",
                    str(prompt_path),
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            manifest = json.loads(completed.stdout)
            self.assertEqual(manifest["interviewer_prompt"], str(prompt_path))
            prompt = prompt_path.read_text(encoding="utf-8")
            self.assertIn("Ask one concise question at a time.", prompt)
            self.assertIn("Do not use a fixed questionnaire.", prompt)
            self.assertIn("If an answer is unrelated", prompt)
            self.assertIn("name: Alice", prompt)
            self.assertIn("slug: alice", prompt)
            self.assertIn("user_name: Morgan", prompt)
            self.assertIn("关系连续性", prompt)
            self.assertIn("relationship_continuity", prompt)

    def test_public_cli_contract_supports_core_commands_and_short_paths(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

        def run_cli(*args):
            return subprocess.run(
                [sys.executable, "-m", "packwright", *args],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

        version = run_cli("--version")
        self.assertEqual(version.returncode, 0, version.stderr + version.stdout)
        self.assertEqual(version.stdout.strip(), "packwright 0.1.0rc1")

        help_result = run_cli("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr + help_result.stdout)
        self.assertIn("{init,build,install,migrate,doctor,score}", help_result.stdout)
        for hidden_command in ("init-character", "migrate-target", "handoff-export", "adopt"):
            self.assertNotIn(hidden_command, help_result.stdout)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            work_dir = root / "mira-work"
            codex_pack_dir = root / "mira-codex-pack"
            codex_target_dir = root / "mira-codex-target"
            cursor_target_dir = root / "mira-cursor-target"

            initialized = run_cli(
                "init",
                "--template",
                "creator",
                "--user-name",
                "Morgan",
                "-o",
                str(work_dir),
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr + initialized.stdout)
            self.assertEqual(json.loads(initialized.stdout)["slug"], "mira")

            built = run_cli(
                "build",
                str(work_dir),
                "--adapter",
                "codex",
                "-o",
                str(codex_pack_dir),
            )
            self.assertEqual(built.returncode, 0, built.stderr + built.stdout)
            self.assertEqual(json.loads(built.stdout)["score"], 100.0)

            installed = run_cli(
                "install",
                str(codex_pack_dir),
                "--adapter",
                "codex",
                "--target",
                str(codex_target_dir),
            )
            self.assertEqual(installed.returncode, 0, installed.stderr + installed.stdout)
            self.assertEqual(json.loads(installed.stdout)["target_dir"], str(codex_target_dir))

            diagnosed = run_cli("doctor", str(codex_target_dir))
            self.assertEqual(diagnosed.returncode, 0, diagnosed.stderr + diagnosed.stdout)
            self.assertTrue(json.loads(diagnosed.stdout)["ok"])

            migrated = run_cli(
                "migrate",
                str(codex_target_dir),
                "--to",
                "cursor",
                "--target",
                str(cursor_target_dir),
                "--yes",
            )
            self.assertEqual(migrated.returncode, 0, migrated.stderr + migrated.stdout)
            self.assertEqual(json.loads(migrated.stdout)["to_adapter"], "cursor")

            scored = run_cli(
                "score",
                str(work_dir),
                "--adapter",
                "codex",
                "--pack-dir",
                str(codex_pack_dir),
            )
            self.assertEqual(scored.returncode, 0, scored.stderr + scored.stdout)
            self.assertEqual(json.loads(scored.stdout)["score"], 100.0)

    def test_installed_target_is_self_contained_after_source_pack_removal_and_relocation(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

        def run_cli(*args):
            return subprocess.run(
                [sys.executable, "-m", "packwright", *args],
                cwd=str(PROJECT_ROOT), env=env, check=False, capture_output=True, text=True,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            work = root / "work"
            pack = root / "pack"
            target = root / "target"
            relocated = root / "new-root" / "target"
            migrated = root / "new-root" / "cursor-target"

            self.assertEqual(run_cli("init", "--template", "creator", "-o", str(work)).returncode, 0)
            self.assertEqual(run_cli("build", str(work), "-o", str(pack)).returncode, 0)
            self.assertEqual(run_cli("install", str(pack), "--target", str(target)).returncode, 0)
            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_mechanism"], ".packwright/spec.json")
            self.assertFalse(any(str(root) in json.dumps(manifest) for _ in [0]))
            for path in ("spec.json", "lock.json", "checker-receipt.json"):
                self.assertTrue((target / ".packwright" / path).is_file())

            shutil.copytree(target, relocated)
            shutil.rmtree(work)
            shutil.rmtree(pack)
            shutil.rmtree(target)

            dry_run = run_cli("migrate", str(relocated), "--to", "cursor", "--target", str(migrated), "--dry-run", "--json")
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr + dry_run.stdout)
            self.assertTrue(json.loads(dry_run.stdout)["ready"])
            self.assertFalse(migrated.exists())
            applied = run_cli("migrate", str(relocated), "--to", "cursor", "--target", str(migrated), "--yes", "--json")
            self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
            self.assertEqual(run_cli("doctor", str(relocated)).returncode, 0)
            score = run_cli("score", str(relocated))
            self.assertEqual(score.returncode, 0, score.stderr + score.stdout)
            self.assertEqual(json.loads(score.stdout)["score"], 100.0)

    def test_cli_init_character_generates_from_starter_template(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            out_dir = root / "mira-work"
            intake_path = root / "mira-intake.yaml"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "init-character",
                    "--template",
                    "creator",
                    "--user-name",
                    "Morgan",
                    "--out-dir",
                    str(out_dir),
                    "--save-intake",
                    str(intake_path),
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            manifest = json.loads(completed.stdout)
            self.assertEqual(manifest["character"], "Mira")
            self.assertEqual(manifest["slug"], "mira")
            self.assertEqual(manifest["intake"], str(intake_path))
            self.assertTrue((out_dir / "mechanism.yaml").exists())

            intake = yaml.safe_load(intake_path.read_text(encoding="utf-8"))
            self.assertEqual(intake["character"]["archetype"], "creator")
            self.assertEqual(intake["character"]["user_name"], "Morgan")

            resolved = resolve_mechanism(load_mechanism(out_dir / "mechanism.yaml"))
            pack = compile_to_cursor_pack(resolved)
            result = score_mechanism(resolved, pack, adapter="cursor")
            self.assertTrue(result["passed"], result)

    def test_cli_init_character_basic_interactive_generates_from_answers(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            out_dir = root / "pulse-work"
            intake_path = root / "answered-intake.yaml"
            result_path = root / "result.json"
            answers = "\n".join(
                [
                    "Pulse",
                    "",
                    "coach",
                    "organize priorities; challenge weak assumptions",
                    "calm, direct, warm through precision",
                    "B",
                    "",
                ]
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "init-character",
                    "--interactive",
                    "--user-name",
                    "Morgan",
                    "--out-dir",
                    str(out_dir),
                    "--save-intake",
                    str(intake_path),
                    "--out",
                    str(result_path),
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                input=answers,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            self.assertIn("basic fallback", completed.stdout)

            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["character"], "Pulse")
            self.assertEqual(result["relationship_continuity"], "warm_selective")
            self.assertEqual(result["direct_emotional_interaction"], "some_direct_emotional_interaction")
            self.assertEqual(result["recommended_emotion_engine_mode"], "light")
            self.assertTrue((out_dir / "mechanism.yaml").exists())
            self.assertTrue(intake_path.exists())

            resolved = resolve_mechanism(load_mechanism(out_dir / "mechanism.yaml"))
            pack = compile_to_codex_pack(resolved)
            self.assertIn("You are Pulse.", pack["AGENTS.md"])
            self.assertIn(".agents/skills/pulse-save-context/SKILL.md", pack)
            self.assertIn("Morgan's coach", resolved["identity"]["role"])

    def test_projection_fixture_boundaries_stay_runtime_appropriate(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        codex_pack = compile_to_codex_pack(resolved)
        claude_pack = compile_to_claude_code_pack(resolved)
        cursor_pack = compile_to_cursor_pack(resolved)

        self.assertIn("- Read `memory/index.md` first when prior context may matter", codex_pack["AGENTS.md"])
        self.assertIn("- Read `memory/profile.md` when stable user", codex_pack["AGENTS.md"])
        self.assertIn("- Read `memory/workstreams.md` when the request belongs", codex_pack["AGENTS.md"])
        self.assertIn("- Read `memory/session-index.md` when the user refers to earlier sessions", codex_pack["AGENTS.md"])
        self.assertIn("- Read `memory/source-map.md` when facts need source lookup", codex_pack["AGENTS.md"])
        self.assertIn("- Read `memory/collaboration.md` when collaboration calibration", codex_pack["AGENTS.md"])
        self.assertNotIn("@memory/", codex_pack["AGENTS.md"])
        self.assertNotIn("memory/emotion-state.json.example", codex_pack["AGENTS.md"])
        self.assertIn("@memory/index.md: default memory router", claude_pack["CLAUDE.md"])
        self.assertIn("@memory/profile.md: stable user", claude_pack["CLAUDE.md"])
        self.assertIn("@memory/workstreams.md: long-running domain routing", claude_pack["CLAUDE.md"])
        self.assertIn("@memory/session-index.md: session/thread recall", claude_pack["CLAUDE.md"])
        self.assertIn("@memory/source-map.md: source lookup", claude_pack["CLAUDE.md"])
        self.assertIn("@memory/collaboration.md: learned collaboration", claude_pack["CLAUDE.md"])
        self.assertIn("@.claude/skills/atlas-save-context/SKILL.md", claude_pack["CLAUDE.md"])
        self.assertIn("default work rules -> `AGENTS.md`", codex_pack["memory/index.md"])
        self.assertIn("default work rules -> `CLAUDE.md`", claude_pack["memory/index.md"])
        self.assertNotIn("AGENTS.md` or equivalent", codex_pack["memory/index.md"])
        self.assertNotIn("AGENTS.md", claude_pack["memory/index.md"])
        self.assertIn("`AGENTS.md` for stable behavior", codex_pack["memory/pinned.md"])
        self.assertIn("`CLAUDE.md` for stable behavior", claude_pack["memory/pinned.md"])
        self.assertIn(".cursor/rules/atlas.mdc", cursor_pack)
        self.assertIn(".cursor/rules/atlas-memory.mdc", cursor_pack)
        self.assertIn(".cursor/rules/atlas-save-context.mdc", cursor_pack)
        self.assertIn("alwaysApply: true", cursor_pack[".cursor/rules/atlas.mdc"])
        self.assertIn("alwaysApply: false", cursor_pack[".cursor/rules/atlas-memory.mdc"])
        self.assertIn("memory/index.md", cursor_pack[".cursor/rules/atlas.mdc"])
        self.assertIn("## Procedure", cursor_pack[".cursor/rules/atlas-save-context.mdc"])
        self.assertIn("default work rules -> `.cursor/rules/atlas.mdc`", cursor_pack["memory/index.md"])
        self.assertNotIn("AGENTS.md", cursor_pack["memory/index.md"])
        self.assertIn("`.cursor/rules/atlas.mdc` for stable behavior", cursor_pack["memory/pinned.md"])

        codex_skill = codex_pack[".agents/skills/atlas-save-context/SKILL.md"]
        claude_skill = claude_pack[".claude/skills/atlas-save-context/SKILL.md"]
        cursor_skill = cursor_pack[".cursor/rules/atlas-save-context.mdc"]
        for forbidden in ("Codex", "Claude", "Projection Notes", "adapter pack", ".codex", ".claude"):
            self.assertNotIn(forbidden, codex_skill)
            self.assertNotIn(forbidden, claude_skill)
            self.assertNotIn(forbidden, cursor_skill)

        codex_pack[".agents/skills/atlas-work/references/source-skills/fact-check/SKILL.md"] = "stale"
        result = score_mechanism(resolved, codex_pack, adapter="codex")
        failed = {check["id"] for check in result["checks"] if not check["passed"]}
        self.assertIn("foundation_mechanisms_not_projected_as_skills", failed)

    def test_empty_memory_skeleton_avoids_template_leakage(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved)

        self.assertIn("This is the default memory router.", pack["memory/index.md"])
        self.assertIn("No active projects have been recorded yet.", pack["memory/index.md"])
        self.assertIn("No profile facts have been recorded yet.", pack["memory/profile.md"])
        self.assertIn("No session index entries have been recorded yet.", pack["memory/session-index.md"])
        self.assertIn("No source mappings have been recorded yet.", pack["memory/source-map.md"])
        self.assertIn("No collaboration calibrations have been recorded yet.", pack["memory/collaboration.md"])
        self.assertIn("No pickup entries have been recorded yet.", pack["memory/recent-activity.md"])
        self.assertIn("newest 20", pack["memory/recent-activity.md"])
        self.assertIn("No pinned memory has been recorded yet.", pack["memory/pinned.md"])
        self.assertIn("domain router", pack["memory/workstreams.md"])
        self.assertIn("Promotion To Agent", pack["memory/workstreams.md"])
        self.assertIn("No workstream state has been recorded yet.", pack["memory/workstreams/_template.md"])
        self.assertIn("No project state has been recorded yet.", pack["memory/projects/_template.md"])
        self.assertIn("Use this directory for generated work products", pack["workspace/README.md"])
        self.assertIn("No current todos have been recorded yet.", pack["memory/todos.md"])
        self.assertIn("not a knowledge base by itself", pack["memory/knowledge_map.md"])
        self.assertIn("No relationship continuity notes have been recorded yet.", pack["memory/relationship-state.md"])
        self.assertIn("No reviewed knowledge notes have been recorded yet.", pack["knowledge/index.md"])
        self.assertEqual(json.loads(pack["knowledge/manifest.json"])["notes"], [])
        self.assertEqual(json.loads(pack["sources/local/manifest.json"])["sources"], {})
        for text in (
            pack["memory/pinned.md"],
            pack["memory/workstreams.md"],
            pack["memory/workstreams/_template.md"],
            pack["memory/recent-activity.md"],
            pack["memory/index.md"],
            pack["memory/profile.md"],
            pack["memory/session-index.md"],
            pack["memory/source-map.md"],
            pack["memory/collaboration.md"],
            pack["memory/projects/_template.md"],
            pack["memory/todos.md"],
            pack["memory/knowledge_map.md"],
            pack["memory/relationship-state.md"],
            pack["workspace/README.md"],
            pack["knowledge/index.md"],
            pack["AGENTS.md"],
        ):
            self.assertNotIn("template skeleton", text)

    def test_install_pack_copies_manifest_artifacts_only_and_refuses_overwrite(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pack_dir = root / "pack"
            target_dir = root / "target"
            for rel_path, content in pack.items():
                path = pack_dir / rel_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            stale_skill = pack_dir / ".agents" / "skills" / "atlas-work" / "SKILL.md"
            stale_skill.parent.mkdir(parents=True, exist_ok=True)
            stale_skill.write_text("old projection", encoding="utf-8")

            result = install_pack(pack_dir, target_dir, adapter="codex")
            self.assertIn("AGENTS.md", result["installed_artifacts"])
            self.assertNotIn("sidecars", result)
            self.assertTrue((target_dir / "AGENTS.md").exists())
            self.assertTrue((target_dir / ".agents" / "skills" / "atlas-save-context" / "SKILL.md").exists())
            self.assertTrue((target_dir / "memory" / "recent-activity.md").exists())
            self.assertFalse((target_dir / ".agents" / "skills" / "atlas-work" / "SKILL.md").exists())

            with self.assertRaises(PackwrightValidationError):
                install_pack(pack_dir, target_dir, adapter="codex")

            forced = install_pack(pack_dir, target_dir, adapter="codex", force=True, include_emotion_engine_codex=False)
            self.assertEqual(forced["adapter"], "codex")

    def test_install_pack_can_explicitly_include_light_emotion_engine_codex_sidecar(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pack_dir = root / "pack"
            target_dir = root / "target"
            sidecar_source = root / "emotion-engine-codex"
            _write_pack(pack, pack_dir)
            _write_fake_emotion_engine_sidecar(sidecar_source)

            result = install_pack(
                pack_dir,
                target_dir,
                adapter="codex",
                include_emotion_engine_codex=True,
                emotion_engine_codex_source=sidecar_source,
                emotion_style="warm through precision, calm, direct, not over-compliant",
            )

            sidecar = result["sidecars"]["emotion-engine-codex"]
            wrapper = target_dir / "scripts" / "codex_emotion.sh"
            self.assertTrue(wrapper.exists())
            self.assertTrue(os.access(wrapper, os.X_OK))
            self.assertIn(
                ".agents/skills/emotion-engine-codex/scripts/codex_emotion.sh",
                wrapper.read_text(encoding="utf-8"),
            )
            self.assertTrue((target_dir / ".agents" / "skills" / "emotion-engine-codex" / "SKILL.md").exists())
            self.assertTrue(
                (target_dir / ".agents" / "skills" / "emotion-engine-codex" / "scripts" / "emotion_engine_utils.py").exists()
            )
            self.assertTrue(
                (target_dir / ".agents" / "skills" / "emotion-engine-codex" / "scripts" / "emotion_engine_mcp.py").exists()
            )
            self.assertTrue(
                (target_dir / ".agents" / "skills" / "emotion-engine-codex" / "scripts" / "register_mcp_client.py").exists()
            )
            self.assertTrue((target_dir / ".emotion-engine" / "codex-state.json").exists())
            self.assertTrue(sidecar["state_created"])
            self.assertTrue(sidecar["agents_section_added"])

            state = json.loads((target_dir / ".emotion-engine" / "codex-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["_schema"], "emotion-engine-state/v2")
            self.assertEqual(state["runtime_mode"], "light")
            self.assertEqual(state["volatility_profile"], "steady")
            self.assertIn("affective_pulse", state)
            self.assertIn("warm through precision", state["character_profile"]["description"])
            self.assertIn("## Emotion Engine", (target_dir / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertNotIn("pleasure", (target_dir / "memory" / "relationship-state.md").read_text(encoding="utf-8"))

            target_manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(target_manifest["features"]["emotion_engine"]["installed"])
            self.assertEqual(target_manifest["features"]["emotion_engine"]["mode"], "light")
            self.assertEqual(target_manifest["boundaries"]["emotion_engine_runtime"], "adapter_sidecar")
            self.assertIn("scripts/codex_emotion.sh", target_manifest["artifacts"])
            self.assertIn(".agents/skills/emotion-engine-codex/scripts/emotion_engine_mcp.py", target_manifest["artifacts"])
            self.assertIn(".agents/skills/emotion-engine-codex/scripts/register_mcp_client.py", target_manifest["artifacts"])

            installed_pack = _read_pack_from_dir(target_dir)

            scored = score_mechanism(resolved, installed_pack, adapter="codex")
            self.assertTrue(scored["passed"], scored)
            optional = {check["id"] for check in scored["checks"] if check["id"].startswith("emotion_engine_codex")}
            self.assertEqual(
                optional,
                {
                    "emotion_engine_codex_skill_present",
                    "emotion_engine_codex_state_present",
                    "emotion_engine_codex_settle_trust_present",
                    "emotion_engine_codex_record_policy_present",
                    "emotion_engine_codex_mcp_present",
                    "emotion_engine_codex_project_wrapper_present",
                    "emotion_engine_codex_entry_internal",
                    "emotion_engine_codex_manifest_consistent",
                },
            )

    def test_install_pack_requires_source_for_explicit_emotion_engine_codex_sidecar(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pack_dir = root / "pack"
            target_dir = root / "target"
            _write_pack(pack, pack_dir)

            with self.assertRaises(PackwrightValidationError) as raised:
                install_pack(
                    pack_dir,
                    target_dir,
                    adapter="codex",
                    include_emotion_engine_codex=True,
                )
            self.assertIn("PACKWRIGHT_EMOTION_ENGINE_CODEX_DIR", str(raised.exception))

    def test_migrate_target_to_cursor_preserves_portable_state_and_rewrites_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            intake_path = root / "system-intake.yaml"
            work_dir = root / "system-work"
            source_pack_dir = root / "codex-pack"
            source_target_dir = root / "codex-target"
            cursor_pack_dir = root / "cursor-pack"
            cursor_target_dir = root / "cursor-target"
            back_codex_pack_dir = root / "back-codex-pack"
            back_codex_target_dir = root / "back-codex-target"
            sidecar_source = root / "emotion-engine-codex"
            intake_path.write_text(
                """version: "0.1"
kind: CharacterIntake
character:
  name: Planner
  slug: system
  user_name: Morgan
  relationship: personal system
  role: Morgan's direct personal system for planning and execution.
  voice: simple, direct, playful, execution-focused
  primary_work:
    - plan technical work
    - keep project state organized
  relationship_continuity: warm_selective
""",
                encoding="utf-8",
            )
            generate_character_template(intake_path, out_dir=work_dir)
            mechanism_path = work_dir / "mechanism.yaml"
            resolved = resolve_mechanism(load_mechanism(mechanism_path))
            codex_pack = compile_to_codex_pack(resolved, references={"source_mechanism": str(mechanism_path)})
            _write_pack(codex_pack, source_pack_dir)
            _write_fake_emotion_engine_sidecar(sidecar_source)
            install_pack(
                source_pack_dir,
                source_target_dir,
                adapter="codex",
                include_emotion_engine_codex=True,
                emotion_engine_codex_source=sidecar_source,
            )

            (source_target_dir / "memory" / "projects").mkdir(parents=True, exist_ok=True)
            (source_target_dir / "memory" / "projects" / "packwright.md").write_text(
                "# Packwright\n\nLive migrated project state.\n",
                encoding="utf-8",
            )
            (source_target_dir / "workspace" / "engineering" / "drafts").mkdir(parents=True, exist_ok=True)
            (source_target_dir / "workspace" / "engineering" / "drafts" / "cursor-smoke.md").write_text(
                "live workspace draft\n",
                encoding="utf-8",
            )
            state_path = source_target_dir / ".emotion-engine" / "codex-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["session_count"] = 5
            state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            (source_target_dir / "memory" / "source-map.md").write_text(
                "# Source Map\n\n"
                "## Runtime Sources\n\n"
                "- Current Codex entry -> `AGENTS.md`\n"
                "- Current save-context skill -> `.agents/skills/system-save-context/SKILL.md`\n"
                "- Current Codex sidecar skill -> `.agents/skills/emotion-engine-codex/SKILL.md`\n"
                "- Current Codex sidecar helper -> `.agents/skills/emotion-engine-codex/scripts/emotion_engine_utils.py`\n"
                "- Project-local Emotion Engine runtime state -> `.emotion-engine/codex-state.json`\n"
                "- Emotion update policy reference -> `.codex/system/references/emotion/update-policy.yaml`\n",
                encoding="utf-8",
            )

            old_mechanism = yaml.safe_load(mechanism_path.read_text(encoding="utf-8"))
            old_mechanism["identity"].pop("slug", None)
            old_mechanism["metadata"].pop("slug", None)
            old_mechanism["targets"]["supported"] = ["codex", "claude-code"]
            old_mechanism["emotion"]["projection"].pop("cursor", None)
            old_mechanism["outputs"].pop("cursor", None)
            mechanism_path.write_text(yaml.safe_dump(old_mechanism, sort_keys=False, allow_unicode=True), encoding="utf-8")

            result = migrate_target(
                source_target_dir,
                cursor_target_dir,
                to_adapter="cursor",
                pack_dir=cursor_pack_dir,
                slug="system",
            )

            self.assertEqual(result["from_adapter"], "codex")
            self.assertEqual(result["to_adapter"], "cursor")
            self.assertEqual(result["character"]["slug"], "system")
            self.assertIn("memory", result["portable_state"])
            self.assertIn("workspace", result["portable_state"])
            self.assertIn("knowledge", result["portable_state"])
            self.assertIn("sources", result["portable_state"])
            self.assertIn("memory/index.md", result["memory_projection"])
            self.assertIn(".emotion-engine/codex-state.json", result["state_snapshots"])
            self.assertIn("outputs_added", {change["id"] for change in result["mechanism_changes"]})
            self.assertIn("codex_runtime_sidecar_excluded", {item["id"] for item in result["runtime_exclusions"]})

            self.assertTrue((cursor_target_dir / ".cursor" / "rules" / "system.mdc").exists())
            self.assertTrue((cursor_target_dir / ".cursor" / "rules" / "system-memory.mdc").exists())
            self.assertTrue((cursor_target_dir / ".cursor" / "rules" / "system-save-context.mdc").exists())
            self.assertFalse((cursor_target_dir / "AGENTS.md").exists())
            self.assertFalse((cursor_target_dir / ".agents" / "skills" / "emotion-engine-codex").exists())
            self.assertIn(
                "Live migrated project state",
                (cursor_target_dir / "memory" / "projects" / "packwright.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "live workspace draft\n",
                (cursor_target_dir / "workspace" / "engineering" / "drafts" / "cursor-smoke.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertIn(
                "default work rules -> `.cursor/rules/system.mdc`",
                (cursor_target_dir / "memory" / "index.md").read_text(encoding="utf-8"),
            )
            migrated_state = json.loads(
                (cursor_target_dir / ".emotion-engine" / "codex-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(migrated_state["session_count"], 5)
            cursor_manifest = json.loads((cursor_target_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(cursor_manifest["adapter"], "cursor")
            self.assertFalse(cursor_manifest["features"]["emotion_engine"]["installed"])
            self.assertEqual(cursor_manifest["character"]["slug"], "system")

            with self.assertRaises(PackwrightValidationError):
                migrate_target(source_target_dir, cursor_target_dir, to_adapter="cursor", slug="system")

            back_result = migrate_target(
                cursor_target_dir,
                back_codex_target_dir,
                to_adapter="codex",
                pack_dir=back_codex_pack_dir,
                slug="system",
                emotion_engine_codex_source=sidecar_source,
            )
            self.assertEqual(back_result["from_adapter"], "cursor")
            self.assertEqual(back_result["to_adapter"], "codex")
            self.assertIn(
                {
                    "id": "source_runtime_entry_replaced",
                    "path": ".cursor/rules/system.mdc",
                    "reason": "replaced by codex adapter entry",
                },
                back_result["runtime_exclusions"],
            )
            self.assertTrue((back_codex_target_dir / "AGENTS.md").exists())
            self.assertTrue((back_codex_target_dir / ".agents" / "skills" / "system-save-context" / "SKILL.md").exists())
            self.assertTrue((back_codex_target_dir / ".agents" / "skills" / "emotion-engine-codex" / "SKILL.md").exists())
            self.assertIn(
                "default work rules -> `AGENTS.md`",
                (back_codex_target_dir / "memory" / "index.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "`AGENTS.md` for stable behavior",
                (back_codex_target_dir / "memory" / "pinned.md").read_text(encoding="utf-8"),
            )
            back_source_map = (back_codex_target_dir / "memory" / "source-map.md").read_text(encoding="utf-8")
            self.assertIn("Current Codex entry -> `AGENTS.md`", back_source_map)
            self.assertIn("Current save-context skill -> `.agents/skills/system-save-context/SKILL.md`", back_source_map)
            self.assertIn(
                "Current Codex sidecar skill -> `.agents/skills/emotion-engine-codex/SKILL.md`",
                back_source_map,
            )
            self.assertIn(
                "Live migrated project state",
                (back_codex_target_dir / "memory" / "projects" / "packwright.md").read_text(encoding="utf-8"),
            )

    def test_migrate_target_force_removes_stale_managed_artifacts(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        codex_pack = compile_to_codex_pack(resolved, references={"source_mechanism": str(MECHANISM_PATH)})

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_pack_dir = root / "codex-pack"
            source_target_dir = root / "codex-target"
            cursor_pack_dir = root / "cursor-pack"
            cursor_target_dir = root / "cursor-target"
            _write_pack(codex_pack, source_pack_dir)
            install_pack(
                source_pack_dir,
                source_target_dir,
                adapter="codex",
                include_emotion_engine_codex=False,
            )

            stale_artifacts = [
                ".cursor/rules/character.mdc",
                ".cursor/rules/character-memory.mdc",
                ".cursor/rules/character-save-context.mdc",
                "manifest.json",
            ]
            for root_dir in (cursor_pack_dir, cursor_target_dir):
                for rel_path in stale_artifacts:
                    path = root_dir / rel_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if rel_path == "manifest.json":
                        path.write_text(
                            json.dumps(
                                {
                                    "adapter": "cursor",
                                    "artifacts": stale_artifacts,
                                    "kind": "CursorAdapterPack",
                                },
                                indent=2,
                                sort_keys=True,
                            )
                            + "\n",
                            encoding="utf-8",
                        )
                    else:
                        path.write_text("stale managed artifact\n", encoding="utf-8")

            result = migrate_target(
                source_target_dir,
                cursor_target_dir,
                to_adapter="cursor",
                pack_dir=cursor_pack_dir,
                force=True,
            )

            self.assertIn(".cursor/rules/character.mdc", result["stale_removed"])
            self.assertFalse((cursor_target_dir / ".cursor" / "rules" / "character.mdc").exists())
            self.assertFalse((cursor_pack_dir / ".cursor" / "rules" / "character.mdc").exists())
            self.assertTrue((cursor_target_dir / ".cursor" / "rules" / "atlas.mdc").exists())
            self.assertTrue((cursor_pack_dir / ".cursor" / "rules" / "atlas.mdc").exists())

    def test_migration_plan_is_no_write_and_receipt_is_path_level(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        codex_pack = compile_to_codex_pack(
            resolved,
            references={"source_mechanism": str(MECHANISM_PATH)},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_pack_dir = root / "codex-pack"
            source_target_dir = root / "codex-target"
            cursor_pack_dir = root / "cursor-pack"
            cursor_target_dir = root / "cursor-target"
            _write_pack(codex_pack, source_pack_dir)
            install_pack(source_pack_dir, source_target_dir, adapter="codex")
            live_draft = source_target_dir / "workspace" / "engineering" / "drafts" / "live.md"
            live_draft.parent.mkdir(parents=True, exist_ok=True)
            live_draft.write_text("live draft\n", encoding="utf-8")

            plan = plan_migration(
                source_target_dir,
                cursor_target_dir,
                to_adapter="cursor",
                pack_dir=cursor_pack_dir,
            )
            report = plan.to_dict()

            self.assertEqual(report["schema"], "packwright-migration/v1")
            self.assertEqual(report["status"], "planned")
            self.assertTrue(report["ready"])
            self.assertEqual(report["score"]["planned"]["score"], 100.0)
            self.assertFalse(cursor_pack_dir.exists())
            self.assertFalse(cursor_target_dir.exists())

            carried = {item["path"]: item for item in report["changes"]["carried"]}
            rewritten = {item["path"]: item for item in report["changes"]["rewritten"]}
            excluded = {item["path"]: item for item in report["changes"]["excluded"]}
            self.assertIn("workspace/engineering/drafts/live.md", carried)
            self.assertEqual(len(carried["workspace/engineering/drafts/live.md"]["sha256"]), 64)
            self.assertIn("memory/index.md", rewritten)
            self.assertNotEqual(
                rewritten["memory/index.md"]["source_sha256"],
                rewritten["memory/index.md"]["destination_sha256"],
            )
            self.assertIn("AGENTS.md", excluded)
            self.assertIn("manifest.json", excluded)
            self.assertTrue(any(path.startswith(".codex/") for path in excluded))

            result = apply_migration(plan)
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["integrity"]["passed"], result)
            self.assertEqual(result["score"]["installed"]["score"], 100.0)
            self.assertEqual(live_draft.read_bytes(), (cursor_target_dir / live_draft.relative_to(source_target_dir)).read_bytes())

            blocked = plan_migration(
                source_target_dir,
                cursor_target_dir,
                to_adapter="cursor",
                pack_dir=cursor_pack_dir,
            ).to_dict()
            self.assertFalse(blocked["ready"])
            self.assertEqual({item["location"] for item in blocked["conflicts"]}, {"pack", "target"})

            stale_target_dir = root / "stale-plan-target"
            stale_plan = plan_migration(source_target_dir, stale_target_dir, to_adapter="cursor")
            live_draft.write_text("changed after planning\n", encoding="utf-8")
            with self.assertRaises(PackwrightValidationError):
                apply_migration(stale_plan)
            self.assertFalse(stale_target_dir.exists())

            with self.assertRaises(PackwrightValidationError):
                plan_migration(source_target_dir, source_target_dir / "nested-target", to_adapter="cursor")
            with self.assertRaises(PackwrightValidationError):
                plan_migration(
                    source_target_dir,
                    root / "separate-target",
                    to_adapter="cursor",
                    pack_dir=source_target_dir / "nested-pack",
                )

    def test_all_directed_cross_adapter_migrations_pass_plan_apply_and_score(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        compilers = {
            "codex": compile_to_codex_pack,
            "claude-code": compile_to_claude_code_pack,
            "cursor": compile_to_cursor_pack,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_targets = {}
            for adapter, compiler in compilers.items():
                pack_dir = root / f"{adapter}-pack"
                target_dir = root / f"{adapter}-target"
                pack = compiler(resolved, references={"source_mechanism": str(MECHANISM_PATH)})
                _write_pack(pack, pack_dir)
                install_pack(pack_dir, target_dir, adapter=adapter)
                source_targets[adapter] = target_dir

            for from_adapter in compilers:
                for to_adapter in compilers:
                    if from_adapter == to_adapter:
                        continue
                    target_dir = root / f"{from_adapter}-to-{to_adapter}"
                    result = migrate_target(source_targets[from_adapter], target_dir, to_adapter=to_adapter)
                    self.assertTrue(result["ok"], (from_adapter, to_adapter, result))
                    self.assertEqual(result["score"]["planned"]["score"], 100.0)
                    self.assertEqual(result["score"]["installed"]["score"], 100.0)
                    self.assertTrue(result["integrity"]["passed"])
                    self.assertTrue(result["changes"]["excluded"])

    def test_create_handoff_writes_review_file_without_modifying_target(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        codex_pack = compile_to_codex_pack(resolved, references={"source_mechanism": str(MECHANISM_PATH)})
        cursor_pack = compile_to_cursor_pack(resolved, references={"source_mechanism": str(MECHANISM_PATH)})

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            codex_pack_dir = root / "codex-pack"
            cursor_pack_dir = root / "cursor-pack"
            codex_target_dir = root / "codex-target"
            cursor_target_dir = root / "cursor-target"
            handoff_path = root / "handoffs" / "codex-to-cursor.md"
            _write_pack(codex_pack, codex_pack_dir)
            _write_pack(cursor_pack, cursor_pack_dir)
            install_pack(
                codex_pack_dir,
                codex_target_dir,
                adapter="codex",
                include_emotion_engine_codex=False,
            )
            install_pack(cursor_pack_dir, cursor_target_dir, adapter="cursor")

            (codex_target_dir / "memory" / "projects").mkdir(parents=True, exist_ok=True)
            (codex_target_dir / "memory" / "projects" / "packwright.md").write_text(
                "# Packwright\n\nCodex side finished the implementation pass.\n",
                encoding="utf-8",
            )
            (codex_target_dir / "workspace" / "engineering" / "drafts").mkdir(parents=True, exist_ok=True)
            (codex_target_dir / "workspace" / "engineering" / "drafts" / "handoff.md").write_text(
                "handoff draft\n",
                encoding="utf-8",
            )

            result = create_handoff(
                codex_target_dir,
                handoff_path,
                summary="Codex finished the implementation pass; Cursor should review and update its own memory.",
                changed_paths=[
                    "memory/projects/packwright.md",
                    "workspace/engineering/drafts/handoff.md",
                ],
                recommended_reads=[
                    "memory/index.md",
                    "memory/projects/packwright.md",
                    "workspace/engineering/drafts/handoff.md",
                ],
                next_steps=[
                    "Read the changed project note.",
                    "Decide whether to record the handoff in the receiving target's memory.",
                ],
            )

            self.assertEqual(result["schema"], "packwright-handoff/v1")
            self.assertEqual(result["source_adapter"], "codex")
            self.assertEqual(result["handoff_file"], str(handoff_path))
            self.assertEqual(result["default_handoff_dir"], DEFAULT_HANDOFF_DIR)
            self.assertEqual(result["session_brief_dir"], DEFAULT_SESSION_BRIEF_DIR)
            self.assertTrue(handoff_path.exists())

            text = handoff_path.read_text(encoding="utf-8")
            self.assertIn("# Packwright Handoff", text)
            self.assertIn('"schema": "packwright-handoff/v1"', text)
            self.assertIn("Codex finished the implementation pass", text)
            self.assertIn("memory/projects/packwright.md", text)
            self.assertIn("workspace/engineering/drafts/handoff.md", text)
            self.assertIn("workspace/shared/artifacts/handoffs/", text)
            self.assertIn("workspace/shared/artifacts/session-briefs/", text)
            self.assertIn("do not blindly copy target files", text)

            self.assertFalse((cursor_target_dir / "memory" / "projects" / "packwright.md").exists())
            self.assertFalse((cursor_target_dir / "workspace" / "engineering" / "drafts" / "handoff.md").exists())

    def test_cursor_target_local_handoff_export_runs_without_source_package(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        cursor_pack = compile_to_cursor_pack(resolved, references={"source_mechanism": str(MECHANISM_PATH)})

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cursor_pack_dir = root / "cursor-pack"
            cursor_target_dir = root / "cursor-target"
            _write_pack(cursor_pack, cursor_pack_dir)
            install_pack(cursor_pack_dir, cursor_target_dir, adapter="cursor")

            (cursor_target_dir / "memory" / "projects").mkdir(parents=True, exist_ok=True)
            (cursor_target_dir / "memory" / "projects" / "packwright.md").write_text(
                "# Packwright\n\nCursor side produced a return handoff.\n",
                encoding="utf-8",
            )
            handoff_rel = Path(DEFAULT_HANDOFF_DIR) / "cursor-to-codex.md"
            wrapper = cursor_target_dir / HANDOFF_WRAPPER_PATH

            completed = subprocess.run(
                [
                    "sh",
                    str(wrapper),
                    "--out",
                    handoff_rel.as_posix(),
                    "--summary",
                    "Cursor return handoff",
                    "--changed",
                    "memory/projects/packwright.md",
                    "--next-step",
                    "Codex should review the Cursor project note.",
                ],
                cwd=str(cursor_target_dir),
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            result = json.loads(completed.stdout)
            self.assertEqual(result["schema"], HANDOFF_SCHEMA)
            self.assertEqual(result["source_adapter"], "cursor")
            self.assertEqual(result["default_handoff_dir"], DEFAULT_HANDOFF_DIR)
            self.assertEqual(result["session_brief_dir"], DEFAULT_SESSION_BRIEF_DIR)
            handoff_path = cursor_target_dir / handoff_rel
            self.assertTrue(handoff_path.exists())
            text = handoff_path.read_text(encoding="utf-8")
            self.assertIn("Cursor return handoff", text)
            self.assertIn('"source_adapter": "cursor"', text)
            self.assertIn(DEFAULT_SESSION_BRIEF_DIR, text)

    def test_checker_uses_shared_emotion_engine_manifest_diagnostics(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pack_dir = root / "pack"
            target_dir = root / "target"
            sidecar_source = root / "emotion-engine-codex"
            _write_pack(pack, pack_dir)
            _write_fake_emotion_engine_sidecar(sidecar_source)
            install_pack(
                pack_dir,
                target_dir,
                adapter="codex",
                include_emotion_engine_codex=True,
                emotion_engine_codex_source=sidecar_source,
            )

            manifest_path = target_dir / "manifest.json"
            target_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            target_manifest["artifacts"].remove("scripts/codex_emotion.sh")
            manifest_path.write_text(json.dumps(target_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            scored = score_mechanism(resolved, _read_pack_from_dir(target_dir), adapter="codex")
            manifest_check = next(
                check for check in scored["checks"] if check["id"] == "emotion_engine_codex_manifest_consistent"
            )
            self.assertFalse(manifest_check["passed"])
            self.assertIn("manifest artifacts missing scripts/codex_emotion.sh", manifest_check["message"])

            diagnosed = doctor_target(
                target_dir,
                emotion_engine_codex_source=sidecar_source,
            )
            manifest_issues = {
                (issue["id"], issue["message"])
                for issue in diagnosed["issues"]
                if issue["path"] == "manifest.json"
            }
            self.assertIn(
                (
                    "emotion_engine_codex_manifest_missing_artifact",
                    "manifest artifacts missing scripts/codex_emotion.sh",
                ),
                manifest_issues,
            )

    def test_install_pack_preserves_existing_emotion_baseline_when_adding_new_fields(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pack_dir = root / "pack"
            target_dir = root / "target"
            sidecar_source = root / "emotion-engine-codex"
            state_file = target_dir / ".emotion-engine" / "codex-state.json"
            pack_with_stale_agents = dict(pack)
            pack_with_stale_agents["AGENTS.md"] = (
                pack["AGENTS.md"].rstrip()
                + "\n\n## Emotion Engine\n- stale section\n"
            )
            _write_pack(pack_with_stale_agents, pack_dir)
            _write_fake_emotion_engine_sidecar(sidecar_source)
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(
                json.dumps(
                    {
                        "_schema": "emotion-engine-state/v2",
                        "enabled": True,
                        "runtime_mode": "light",
                        "emotion": {"pleasure": 0.0, "arousal": 0.3, "dominance": 0.5},
                        "personality_baseline": {"pleasure": 0.0, "arousal": 0.3, "dominance": 0.5},
                        "character_profile": {
                            "source": "packwright-install",
                            "description": "old installed default",
                            "interpretation": "old installed default",
                            "traits": ["old"],
                        },
                        "trust": 0.1,
                        "trust_anchor": 0.1,
                        "session_count": 0,
                        "total_turns": 0,
                        "last_interaction_iso": None,
                        "emotion_trajectory": [],
                        "emotion_log": [],
                        "trust_history": [],
                        "log_limit": 200,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            install_pack(
                pack_dir,
                target_dir,
                adapter="codex",
                include_emotion_engine_codex=True,
                emotion_engine_codex_source=sidecar_source,
                emotion_style="warm, intimate, playful",
            )

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["personality_baseline"], {"pleasure": 0.0, "arousal": 0.3, "dominance": 0.5})
            self.assertEqual(state["character_profile"]["description"], "old installed default")
            self.assertEqual(state["volatility_profile"], "steady")
            self.assertEqual(state["affective_pulse"]["intensity"], 0.0)
            agents = (target_dir / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("scripts/codex_emotion.sh", agents)
            self.assertIn("low-value duplicate compaction", agents)
            self.assertNotIn("stale section", agents)

    def test_refresh_emotion_engine_codex_updates_sidecar_without_resetting_state(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pack_dir = root / "pack"
            target_dir = root / "target"
            sidecar_source = root / "emotion-engine-codex"
            _write_pack(pack, pack_dir)
            _write_fake_emotion_engine_sidecar(sidecar_source)

            install_pack(
                pack_dir,
                target_dir,
                adapter="codex",
                include_emotion_engine_codex=True,
                emotion_engine_codex_source=sidecar_source,
            )

            state_file = target_dir / ".emotion-engine" / "codex-state.json"
            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["session_count"] = 7
            state["character_profile"]["description"] = "preserve this installed profile"
            state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            target_helper = target_dir / ".agents" / "skills" / "emotion-engine-codex" / "scripts" / "emotion_engine_utils.py"
            unmanaged_note = target_dir / ".agents" / "skills" / "emotion-engine-codex" / "scripts" / "local-note.txt"
            unmanaged_note.write_text("preserve local sidecar note\n", encoding="utf-8")
            target_helper.write_text("# stale installed helper\n", encoding="utf-8")
            source_helper_text = (
                "def state_file_lock(path):\n    return path\n\n"
                "def write_json_file_atomic(path, value):\n    return None\n\n"
                "def recover_state_from_backup(path, error):\n    return {}\n\n"
                "def settle_trust(state):\n    return state, {}\n\n"
                "def parse_record_policy_args(args):\n    return {}\n\n"
                "def record_policy(state, message, mode=None, contexts=None):\n"
                "    return {\"decision\": \"respond_only\", \"reply_bias\": [], \"reason\": \"generic_praise_habituated\"}\n"
            )
            (sidecar_source / "scripts" / "emotion_engine_utils.py").write_text(source_helper_text, encoding="utf-8")

            result = refresh_emotion_engine_codex(
                target_dir,
                emotion_engine_codex_source=sidecar_source,
            )

            self.assertFalse(result["sidecars"]["emotion-engine-codex"]["state_created"])
            self.assertIn("state_file_lock", target_helper.read_text(encoding="utf-8"))
            self.assertEqual(unmanaged_note.read_text(encoding="utf-8"), "preserve local sidecar note\n")
            refreshed_state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(refreshed_state["session_count"], 7)
            self.assertEqual(refreshed_state["character_profile"]["description"], "preserve this installed profile")
            target_manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(target_manifest["features"]["emotion_engine"]["installed"])
            self.assertIn(".agents/skills/emotion-engine-codex/scripts/emotion_engine_utils.py", target_manifest["artifacts"])
            self.assertIn(".agents/skills/emotion-engine-codex/scripts/emotion_engine_mcp.py", target_manifest["artifacts"])
            self.assertIn(".agents/skills/emotion-engine-codex/scripts/register_mcp_client.py", target_manifest["artifacts"])

            installed_pack = _read_pack_from_dir(target_dir)
            scored = score_mechanism(resolved, installed_pack, adapter="codex")
            self.assertTrue(scored["passed"], scored)

    def test_doctor_fix_repairs_emotion_engine_sidecar_drift(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pack_dir = root / "pack"
            target_dir = root / "target"
            sidecar_source = root / "emotion-engine-codex"
            _write_pack(pack, pack_dir)
            _write_fake_emotion_engine_sidecar(sidecar_source)
            install_pack(
                pack_dir,
                target_dir,
                adapter="codex",
                include_emotion_engine_codex=True,
                emotion_engine_codex_source=sidecar_source,
            )

            state_file = target_dir / ".emotion-engine" / "codex-state.json"
            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["session_count"] = 11
            state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            target_helper = target_dir / ".agents" / "skills" / "emotion-engine-codex" / "scripts" / "emotion_engine_utils.py"
            target_mcp = target_dir / ".agents" / "skills" / "emotion-engine-codex" / "scripts" / "emotion_engine_mcp.py"
            target_register = target_dir / ".agents" / "skills" / "emotion-engine-codex" / "scripts" / "register_mcp_client.py"
            target_helper.write_text("# stale installed helper\n", encoding="utf-8")
            target_mcp.unlink()
            target_register.unlink()

            diagnosed = doctor_target(
                target_dir,
                emotion_engine_codex_source=sidecar_source,
            )

            self.assertFalse(diagnosed["ok"])
            self.assertIn("emotion_engine_codex_file_drift", {issue["id"] for issue in diagnosed["issues"]})
            self.assertIn("emotion_engine_codex_missing_file", {issue["id"] for issue in diagnosed["issues"]})

            fixed = doctor_target(
                target_dir,
                fix=True,
                emotion_engine_codex_source=sidecar_source,
            )

            self.assertTrue(fixed["ok"], fixed)
            self.assertEqual(fixed["after_issues"], [])
            self.assertEqual(fixed["fixes"][0]["id"], "emotion_engine_codex_refreshed")
            self.assertNotIn("stale installed helper", target_helper.read_text(encoding="utf-8"))
            self.assertTrue(target_mcp.exists())
            self.assertTrue(target_register.exists())
            refreshed_state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(refreshed_state["session_count"], 11)

    def test_doctor_fix_repairs_cursor_handoff_and_workspace_layout(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_cursor_pack(resolved)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pack_dir = root / "cursor-pack"
            target_dir = root / "cursor-target"
            _write_pack(pack, pack_dir)
            install_pack(pack_dir, target_dir, adapter="cursor")

            session_brief_keep = target_dir / DEFAULT_SESSION_BRIEF_DIR / ".gitkeep"
            session_brief_keep.unlink()
            wrapper = target_dir / HANDOFF_WRAPPER_PATH
            wrapper.write_text("# stale wrapper\n", encoding="utf-8")

            diagnosed = doctor_target(target_dir)

            self.assertFalse(diagnosed["ok"])
            issue_ids = {issue["id"] for issue in diagnosed["issues"]}
            self.assertIn("workspace_layout_missing_file", issue_ids)
            self.assertIn("handoff_tool_file_drift", issue_ids)

            fixed = doctor_target(target_dir, fix=True)

            self.assertTrue(fixed["ok"], fixed)
            self.assertTrue(session_brief_keep.exists())
            self.assertIn("packwright_handoff.py", wrapper.read_text(encoding="utf-8"))
            self.assertIn("target_layout_repaired", {fix["id"] for fix in fixed["fixes"]})

    def test_doctor_fix_repairs_knowledge_scaffold(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pack_dir = root / "codex-pack"
            target_dir = root / "codex-target"
            _write_pack(pack, pack_dir)
            install_pack(
                pack_dir,
                target_dir,
                adapter="codex",
                include_emotion_engine_codex=False,
            )

            (target_dir / "knowledge" / "index.md").unlink()
            (target_dir / "sources" / "local" / "manifest.json").unlink()

            diagnosed = doctor_target(target_dir)

            self.assertFalse(diagnosed["ok"])
            issue_ids = {issue["id"] for issue in diagnosed["issues"]}
            self.assertIn("knowledge_scaffold_missing_file", issue_ids)

            fixed = doctor_target(target_dir, fix=True)

            self.assertTrue(fixed["ok"], fixed)
            self.assertTrue((target_dir / "knowledge" / "index.md").exists())
            self.assertTrue((target_dir / "sources" / "local" / "manifest.json").exists())
            self.assertIn("target_layout_repaired", {fix["id"] for fix in fixed["fixes"]})

    def test_doctor_reports_compatibility_memory_files_without_failing(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pack_dir = root / "codex-pack"
            target_dir = root / "codex-target"
            _write_pack(pack, pack_dir)
            install_pack(
                pack_dir,
                target_dir,
                adapter="codex",
                include_emotion_engine_codex=False,
            )

            diagnosed = doctor_target(target_dir)

            self.assertTrue(diagnosed["ok"], diagnosed)
            warning_paths = {
                warning["path"]
                for warning in diagnosed["warnings"]
                if warning["id"] == "compatibility_memory_file_present"
            }
            self.assertIn("memory/pinned.md", warning_paths)
            self.assertIn("memory/recent-activity.md", warning_paths)
            self.assertIn("memory/knowledge_map.md", warning_paths)
            self.assertIn("memory/relationship-state.md", warning_paths)

    def test_doctor_upgrades_legacy_codex_skill_layout_and_migration_recognizes_it(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved, references={"source_mechanism": str(MECHANISM_PATH)})
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pack_dir = root / "pack"
            target_dir = root / "legacy-target"
            cursor_target = root / "cursor-target"
            _write_pack(pack, pack_dir)
            install_pack(pack_dir, target_dir, adapter="codex")
            canonical = target_dir / ".agents" / "skills" / "atlas-save-context"
            legacy = target_dir / ".codex" / "skills" / "atlas-save-context"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(canonical), str(legacy))
            for rel_path in ("manifest.json", "AGENTS.md", "memory/index.md", "memory/pinned.md", "memory/source-map.md"):
                path = target_dir / rel_path
                path.write_text(path.read_text(encoding="utf-8").replace(".agents/skills/", ".codex/skills/"), encoding="utf-8")

            diagnosis = doctor_target(target_dir)
            self.assertFalse(diagnosis["ok"])
            self.assertIn("legacy_codex_skill_layout", {issue["id"] for issue in diagnosis["issues"]})
            plan = plan_migration(target_dir, cursor_target, to_adapter="cursor").to_dict()
            self.assertIn(".codex/skills/atlas-save-context/SKILL.md", {item["path"] for item in plan["changes"]["excluded"]})
            repaired = doctor_target(target_dir, fix=True)
            self.assertTrue(repaired["ok"], repaired)
            self.assertTrue((canonical / "SKILL.md").is_file())
            self.assertFalse(legacy.exists())

    def test_doctor_refuses_ambiguous_legacy_codex_skill_conflict(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
        pack = compile_to_codex_pack(resolved)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pack_dir = root / "pack"
            target_dir = root / "target"
            _write_pack(pack, pack_dir)
            install_pack(pack_dir, target_dir, adapter="codex")
            legacy = target_dir / ".codex" / "skills" / "atlas-save-context" / "SKILL.md"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text("legacy conflicting copy\n", encoding="utf-8")
            result = doctor_target(target_dir, fix=True)
            self.assertFalse(result["ok"])
            self.assertIn("legacy_codex_skill_conflict", {issue["id"] for issue in result["issues"]})
            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy conflicting copy\n")

    def test_checker_scores_codex_claude_and_cursor_adapter_packs(self):
        resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))

        codex_pack = compile_to_codex_pack(resolved)
        codex_result = score_mechanism(resolved, codex_pack, adapter="codex")
        self.assertTrue(codex_result["passed"])
        self.assertEqual(codex_result["score"], 100.0)

        claude_pack = compile_to_claude_code_pack(resolved)
        claude_result = score_mechanism(resolved, claude_pack, adapter="claude-code")
        self.assertTrue(claude_result["passed"])
        self.assertEqual(claude_result["score"], 100.0)

        cursor_pack = compile_to_cursor_pack(resolved)
        cursor_result = score_mechanism(resolved, cursor_pack, adapter="cursor")
        self.assertTrue(cursor_result["passed"], cursor_result)
        self.assertEqual(cursor_result["score"], 100.0)
        cursor_checks = {check["id"]: check for check in cursor_result["checks"]}
        self.assertTrue(cursor_checks["cursor_handoff_tool_present"]["passed"])
        self.assertTrue(cursor_checks["knowledge_skeleton_present"]["passed"])

    def test_adopt_existing_inventories_without_merging_old_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "old-agent"
            target = root / "new-target"
            (source / ".cursor" / "rules").mkdir(parents=True)
            (source / "memory").mkdir()
            (source / "docs").mkdir()
            (source / ".cursor" / "rules" / "agent.mdc").write_text("old cursor rules\n", encoding="utf-8")
            (source / "memory" / "todos.md").write_text("# Todos\n\nold state\n", encoding="utf-8")
            (source / "docs" / "playbook.md").write_text("# Playbook\n\nold method\n", encoding="utf-8")

            dry_run = adopt_existing(source, dry_run=True)

            self.assertTrue(dry_run["dry_run"])
            self.assertEqual(dry_run["categories"]["runtime_instruction"], 1)
            self.assertGreaterEqual(dry_run["categories"]["memory_candidate"], 1)
            self.assertFalse(target.exists())

            applied = adopt_existing(source, target_dir=target, dry_run=False)

            self.assertFalse(applied["dry_run"])
            self.assertTrue((target / "workspace" / "shared" / "artifacts" / "migrations" / "inventory.json").exists())
            self.assertTrue(Path(applied["report"]).exists())
            self.assertTrue((target / "knowledge" / "index.md").exists())
            self.assertTrue((target / "sources" / "local" / "manifest.json").exists())
            self.assertFalse((target / "memory" / "todos.md").exists())
            report = Path(applied["report"]).read_text(encoding="utf-8")
            self.assertIn("Existing instances are source material", report)
            self.assertIn("memory_candidate", report)

    def test_cli_run_writes_cursor_pack(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        with tempfile.TemporaryDirectory() as tmpdir:
            build_dir = Path(tmpdir) / "cursor-pack"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "build",
                    str(MECHANISM_PATH),
                    "--adapter",
                    "cursor",
                    "--out-dir",
                    str(build_dir),
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            manifest = json.loads(completed.stdout)
            self.assertTrue(manifest["passed"])
            self.assertTrue((build_dir / ".cursor" / "rules" / "atlas.mdc").exists())
            self.assertTrue((build_dir / ".cursor" / "rules" / "atlas-memory.mdc").exists())
            self.assertTrue((build_dir / ".cursor" / "rules" / "atlas-save-context.mdc").exists())
            self.assertTrue((build_dir / HANDOFF_HELPER_PATH).exists())
            self.assertTrue((build_dir / HANDOFF_WRAPPER_PATH).exists())
            self.assertTrue((build_dir / "memory" / "index.md").exists())
            self.assertTrue((build_dir / "workspace" / "README.md").exists())
            pack_manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(pack_manifest["adapter"], "cursor")
            self.assertEqual(pack_manifest["kind"], "CursorAdapterPack")
            self.assertEqual(pack_manifest["features"]["handoff"]["default_handoff_dir"], DEFAULT_HANDOFF_DIR)

    def test_cli_run_writes_codex_pack_and_scores_existing_pack(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        with tempfile.TemporaryDirectory() as tmpdir:
            build_dir = Path(tmpdir) / "pack"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "run",
                    str(MECHANISM_PATH),
                    "--adapter",
                    "codex",
                    "--build-dir",
                    str(build_dir),
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            manifest = json.loads(completed.stdout)
            self.assertTrue(manifest["passed"])
            self.assertTrue((build_dir / "AGENTS.md").exists())
            self.assertTrue((build_dir / ".agents" / "skills" / "atlas-save-context" / "SKILL.md").exists())
            self.assertTrue((build_dir / "memory" / "index.md").exists())
            self.assertTrue((build_dir / "memory" / "session-index.md").exists())
            self.assertTrue((build_dir / "memory" / "source-map.md").exists())
            self.assertTrue((build_dir / "memory" / "collaboration.md").exists())
            self.assertTrue((build_dir / "memory" / "pinned.md").exists())
            self.assertTrue((build_dir / "memory" / "workstreams.md").exists())
            self.assertTrue((build_dir / "memory" / "recent-activity.md").exists())
            self.assertTrue((build_dir / "memory" / "projects" / "_template.md").exists())
            self.assertTrue((build_dir / "memory" / "relationship-state.md").exists())
            self.assertTrue((build_dir / "memory" / "emotion-state.json.example").exists())
            self.assertTrue((build_dir / "resolved.json").exists())
            self.assertTrue((build_dir / "score.json").exists())

            scored = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "score",
                    str(MECHANISM_PATH),
                    "--pack-dir",
                    str(build_dir),
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(scored.returncode, 0, scored.stderr + scored.stdout)

    def test_cli_install_writes_codex_working_directory(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir) / "pack"
            target_dir = Path(tmpdir) / "codex-project"
            sidecar_source = Path(tmpdir) / "emotion-engine-codex"
            _write_fake_emotion_engine_sidecar(sidecar_source)

            run_completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "run",
                    str(MECHANISM_PATH),
                    "--adapter",
                    "codex",
                    "--build-dir",
                    str(pack_dir),
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(run_completed.returncode, 0, run_completed.stderr + run_completed.stdout)

            installed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "install",
                    "--adapter",
                    "codex",
                    "--pack-dir",
                    str(pack_dir),
                    "--target-dir",
                    str(target_dir),
                    "--include-emotion-engine-codex",
                    "--emotion-engine-codex-source",
                    str(sidecar_source),
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr + installed.stdout)
            manifest = json.loads(installed.stdout)
            self.assertEqual(manifest["target_dir"], str(target_dir))
            self.assertTrue((target_dir / "AGENTS.md").exists())
            self.assertTrue((target_dir / ".codex" / "atlas" / "references" / "mechanism" / "session-guards.yaml").exists())
            self.assertTrue((target_dir / ".agents" / "skills" / "emotion-engine-codex" / "SKILL.md").exists())
            self.assertTrue((target_dir / ".agents" / "skills" / "emotion-engine-codex" / "scripts" / "emotion_engine_mcp.py").exists())
            self.assertTrue((target_dir / ".agents" / "skills" / "emotion-engine-codex" / "scripts" / "register_mcp_client.py").exists())
            self.assertTrue((target_dir / ".emotion-engine" / "codex-state.json").exists())
            target_manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(target_manifest["features"]["emotion_engine"]["installed"])
            self.assertEqual(target_manifest["features"]["emotion_engine"]["mode"], "light")
            self.assertIn(".agents/skills/emotion-engine-codex/scripts/emotion_engine_mcp.py", target_manifest["artifacts"])
            self.assertIn(".agents/skills/emotion-engine-codex/scripts/register_mcp_client.py", target_manifest["artifacts"])

            refused = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "install",
                    "--adapter",
                    "codex",
                    "--pack-dir",
                    str(pack_dir),
                    "--target-dir",
                    str(target_dir),
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("would be overwritten", refused.stdout)

            target_helper = target_dir / ".agents" / "skills" / "emotion-engine-codex" / "scripts" / "emotion_engine_utils.py"
            target_helper.write_text("# stale installed helper\n", encoding="utf-8")
            (sidecar_source / "scripts" / "emotion_engine_utils.py").write_text(
                "def state_file_lock(path):\n    return path\n\n"
                "def settle_trust(state):\n    return state, {}\n\n"
                "def parse_record_policy_args(args):\n    return {}\n\n"
                "def record_policy(state, message, mode=None, contexts=None):\n"
                "    return {\"decision\": \"respond_only\", \"reply_bias\": [], \"reason\": \"generic_praise_habituated\"}\n",
                encoding="utf-8",
            )
            refreshed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "refresh-emotion-engine-codex",
                    "--target-dir",
                    str(target_dir),
                    "--emotion-engine-codex-source",
                    str(sidecar_source),
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(refreshed.returncode, 0, refreshed.stderr + refreshed.stdout)
            refresh_manifest = json.loads(refreshed.stdout)
            self.assertEqual(refresh_manifest["target_dir"], str(target_dir))
            self.assertIn("state_file_lock", target_helper.read_text(encoding="utf-8"))

            target_helper.write_text("# stale installed helper again\n", encoding="utf-8")
            diagnosed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "doctor",
                    "--target-dir",
                    str(target_dir),
                    "--emotion-engine-codex-source",
                    str(sidecar_source),
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(diagnosed.returncode, 1, diagnosed.stderr + diagnosed.stdout)
            diagnosis = json.loads(diagnosed.stdout)
            self.assertFalse(diagnosis["ok"])

            fixed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "doctor",
                    "--target-dir",
                    str(target_dir),
                    "--emotion-engine-codex-source",
                    str(sidecar_source),
                    "--fix",
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(fixed.returncode, 0, fixed.stderr + fixed.stdout)
            fixed_manifest = json.loads(fixed.stdout)
            self.assertTrue(fixed_manifest["ok"])
            self.assertIn("state_file_lock", target_helper.read_text(encoding="utf-8"))

    def test_cli_migrate_target_writes_cursor_working_directory(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            codex_pack_dir = root / "codex-pack"
            codex_target_dir = root / "codex-target"
            cursor_pack_dir = root / "cursor-pack"
            cursor_target_dir = root / "cursor-target"
            resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
            codex_pack = compile_to_codex_pack(resolved, references={"source_mechanism": str(MECHANISM_PATH)})
            _write_pack(codex_pack, codex_pack_dir)
            install_pack(
                codex_pack_dir,
                codex_target_dir,
                adapter="codex",
                include_emotion_engine_codex=False,
            )

            command = [
                sys.executable,
                "-m",
                "packwright",
                "migrate",
                "--source-target-dir",
                str(codex_target_dir),
                "--target-dir",
                str(cursor_target_dir),
                "--to",
                "cursor",
                "--pack-dir",
                str(cursor_pack_dir),
            ]
            dry_run = subprocess.run(
                [*command, "--dry-run", "--json"],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr + dry_run.stdout)
            dry_report = json.loads(dry_run.stdout)
            self.assertTrue(dry_report["dry_run"])
            self.assertEqual(dry_report["status"], "planned")
            self.assertEqual(dry_report["score"]["planned"]["score"], 100.0)
            self.assertFalse(cursor_pack_dir.exists())
            self.assertFalse(cursor_target_dir.exists())

            unconfirmed = subprocess.run(
                [*command, "--json"],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(unconfirmed.returncode, 2, unconfirmed.stderr + unconfirmed.stdout)
            self.assertEqual(json.loads(unconfirmed.stdout)["status"], "confirmation_required")
            self.assertFalse(cursor_pack_dir.exists())
            self.assertFalse(cursor_target_dir.exists())

            completed = subprocess.run(
                [*command, "--yes", "--json"],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            manifest = json.loads(completed.stdout)
            self.assertEqual(manifest["from_adapter"], "codex")
            self.assertEqual(manifest["to_adapter"], "cursor")
            self.assertTrue(manifest["integrity"]["passed"])
            self.assertEqual(manifest["score"]["installed"]["score"], 100.0)
            self.assertTrue((cursor_target_dir / ".cursor" / "rules" / "atlas.mdc").exists())
            self.assertTrue((cursor_target_dir / "memory" / "index.md").exists())
            self.assertTrue((cursor_target_dir / "knowledge" / "index.md").exists())
            self.assertTrue((cursor_target_dir / "sources" / "local" / "manifest.json").exists())
            self.assertTrue((cursor_target_dir / "workspace" / "README.md").exists())

    def test_cli_adopt_writes_reviewable_migration_report(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "old-agent"
            target = root / "target"
            (source / ".cursor" / "rules").mkdir(parents=True)
            (source / ".cursor" / "rules" / "agent.mdc").write_text("old rules\n", encoding="utf-8")
            (source / "memory").mkdir()
            (source / "memory" / "todos.md").write_text("old todos\n", encoding="utf-8")

            dry_run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "adopt",
                    "--from",
                    str(source),
                    "--dry-run",
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr + dry_run.stdout)
            dry_manifest = json.loads(dry_run.stdout)
            self.assertTrue(dry_manifest["dry_run"])
            self.assertFalse(target.exists())

            applied = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "adopt",
                    "--from",
                    str(source),
                    "--target-dir",
                    str(target),
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
            manifest = json.loads(applied.stdout)
            self.assertFalse(manifest["dry_run"])
            self.assertTrue((target / "workspace" / "shared" / "artifacts" / "migrations" / "inventory.json").exists())
            self.assertTrue((target / "knowledge" / "index.md").exists())
            self.assertFalse((target / "memory" / "todos.md").exists())

    def test_pyproject_exposes_packwright_console_script_only(self):
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('name = "packwright"', pyproject)
        self.assertIn('version = "0.1.0rc1"', pyproject)
        self.assertIn('packwright = "packwright.cli:main"', pyproject)

    def test_cli_handoff_export_writes_review_file(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            codex_pack_dir = root / "codex-pack"
            codex_target_dir = root / "codex-target"
            handoff_path = root / "handoff.md"
            resolved = resolve_mechanism(load_mechanism(MECHANISM_PATH))
            codex_pack = compile_to_codex_pack(resolved, references={"source_mechanism": str(MECHANISM_PATH)})
            _write_pack(codex_pack, codex_pack_dir)
            install_pack(
                codex_pack_dir,
                codex_target_dir,
                adapter="codex",
                include_emotion_engine_codex=False,
            )
            (codex_target_dir / "memory" / "projects").mkdir(parents=True, exist_ok=True)
            (codex_target_dir / "memory" / "projects" / "packwright.md").write_text(
                "# Packwright\n\nCLI handoff source.\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "packwright",
                    "handoff-export",
                    "--source-target-dir",
                    str(codex_target_dir),
                    "--out",
                    str(handoff_path),
                    "--summary",
                    "CLI handoff summary",
                    "--changed",
                    "memory/projects/packwright.md",
                    "--next-step",
                    "Receiver should review the project note.",
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            manifest = json.loads(completed.stdout)
            self.assertEqual(manifest["schema"], "packwright-handoff/v1")
            self.assertEqual(manifest["handoff_file"], str(handoff_path))
            self.assertEqual(manifest["default_handoff_dir"], DEFAULT_HANDOFF_DIR)
            self.assertEqual(manifest["session_brief_dir"], DEFAULT_SESSION_BRIEF_DIR)
            self.assertTrue(handoff_path.exists())
            self.assertIn("CLI handoff summary", handoff_path.read_text(encoding="utf-8"))

def _write_pack(pack, pack_dir):
    for rel_path, content in pack.items():
        path = pack_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _read_pack_from_dir(pack_dir):
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    pack = {}
    for rel_path in manifest["artifacts"]:
        path = pack_dir / rel_path
        if path.exists():
            pack[rel_path] = path.read_text(encoding="utf-8")
    return pack


def _write_fake_emotion_engine_sidecar(source_dir):
    (source_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (source_dir / "spec").mkdir(parents=True, exist_ok=True)
    (source_dir / "SKILL.md").write_text(
        "# Emotion Engine For Codex\n\nUse this skill for lightweight emotional continuity. Run record_policy before record_turn. Run settle_trust at session close.\n\n## Runtime Modes And Record Policy\n",
        encoding="utf-8",
    )
    (source_dir / "README.md").write_text("# Emotion Engine For Codex\n", encoding="utf-8")
    (source_dir / "install.sh").write_text("#!/usr/bin/env sh\n", encoding="utf-8")
    (source_dir / "scripts" / "codex_emotion.sh").write_text(
        '#!/usr/bin/env sh\nexec "$PYTHON" "$ENGINE" "$COMMAND" "$STATE_FILE" "$@"\n',
        encoding="utf-8",
    )
    (source_dir / "scripts" / "pulse_demo.py").write_text("# demo\n", encoding="utf-8")
    (source_dir / "scripts" / "emotion_engine_utils.py").write_text(
        "def settle_trust(state):\n    return state, {}\n\ndef parse_record_policy_args(args):\n    return {}\n\ndef record_policy(state, message, mode=None, contexts=None):\n    return {\"decision\": \"respond_only\", \"reply_bias\": [], \"reason\": \"generic_praise_habituated\"}\n",
        encoding="utf-8",
    )
    (source_dir / "scripts" / "emotion_engine_mcp.py").write_text(
        "#!/usr/bin/env python3\n# tools/list exposes emotion_engine_record_policy and no Packwright repair tools.\n",
        encoding="utf-8",
    )
    (source_dir / "scripts" / "register_mcp_client.py").write_text(
        "#!/usr/bin/env python3\n# register_mcp_client supports codex MCP registration with explicit state paths.\n",
        encoding="utf-8",
    )
    (source_dir / "emotion-state-template.json").write_text(
        '{"_schema": "emotion-engine-state/v2"}\n',
        encoding="utf-8",
    )
    (source_dir / "spec" / "emotion-state.schema.json").write_text("{}\n", encoding="utf-8")
    (source_dir / "LICENSE").write_text("test\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
