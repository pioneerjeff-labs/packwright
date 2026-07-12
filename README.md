<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/mark-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/mark-light.svg">
    <img alt="Packwright dovetail mark" src="assets/mark-light.svg" width="88" height="88">
  </picture>
</p>

<h1 align="center">Packwright</h1>

<p align="center"><strong>Build your agent once. Carry it everywhere.</strong></p>

<p align="center">
  Compile one agent definition—rules, memory, skills, and workspace—into native packs<br>
  for Codex, Claude Code, and Cursor. Build, install, migrate, and verify with plain files.
</p>

<p align="center">
  <a href="https://pioneerjeff-labs.github.io/packwright/"><img alt="Packwright website" src="https://img.shields.io/badge/website-live-9C4F16?style=flat-square"></a>
  <a href="https://github.com/pioneerjeff-labs/packwright/actions/workflows/ci.yml"><img alt="CI status" src="https://github.com/pioneerjeff-labs/packwright/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-5C5245?style=flat-square"></a>
  <a href="README.zh-CN.md"><img alt="中文 README" src="https://img.shields.io/badge/README-中文-B87333?style=flat-square"></a>
</p>

<p align="center"><strong>The output is files you can read.</strong></p>

> [!NOTE]
> Packwright itself makes no network requests and sends no telemetry. Your coding runtime may still send files it reads to its own model provider; its data policy continues to apply.

## Start with your coding agent

The shortest interface is a conversation. Install Packwright, then paste the operating prompt into Codex, Claude Code, or Cursor:

```bash
python -m pip install packwright==0.1.0rc1
```

**[Open the paste-ready agent prompt →](docs/USE_WITH_YOUR_AGENT.md)**

The prompt makes the agent preview every migration, explain the receipt, wait for your approval, and verify the installed target afterward.

## Or run it by hand

Build and install an editable Claude Code target:

```bash
packwright init --template creator -o work/mira
packwright build work/mira --adapter claude-code -o pack/mira-claude
packwright install pack/mira-claude --adapter claude-code --target project/mira-claude
```

Preview a move from Claude Code to Codex. The destination is not created during this step:

```bash
packwright migrate project/mira-claude \
  --to codex \
  --target project/mira-codex --dry-run
```

The plan names four kinds of paths:

| Receipt section | Meaning |
|---|---|
| `generated` | Files compiled for the destination runtime |
| `carried` | Portable user files copied and SHA-256 verified |
| `rewritten` | Packwright-managed routing lines changed for the destination |
| `excluded` | Runtime-specific files deliberately left behind |

After reviewing the receipt, apply that exact move and verify the result:

```bash
packwright migrate project/mira-claude \
  --to codex \
  --target project/mira-codex --yes
packwright doctor project/mira-codex
packwright score project/mira-codex
```

Add `--json` to the dry run and confirmed run for a machine-readable `packwright-migration/v1` receipt. Packwright refuses to overwrite an existing target unless you separately opt into `--force`.

## Why not just prompts?

A working coding agent is more than its top-level instructions, and each runtime expects a different native layout:

| Runtime | Native entry | Reusable procedures |
|---|---|---|
| Codex | `AGENTS.md` | `.agents/skills/<name>/SKILL.md` |
| Claude Code | `CLAUDE.md` | `.claude/skills/<name>/SKILL.md` |
| Cursor | `.cursor/rules/<name>.mdc` | `.cursor/rules/<name>-save-context.mdc` |

Packwright treats those files as compiled projections. Your editable source owns the behavior; adapters own the runtime layout; migration carries portable state and reports the seams instead of hiding them.

## Build once, carry everywhere

```text
editable source
  identity · memory contract · skills · workspace rules
         │
         ├── packwright build --adapter codex       → AGENTS.md + .agents/skills/
         ├── packwright build --adapter claude-code → CLAUDE.md + .claude/skills/
         └── packwright build --adapter cursor      → .cursor/rules/*.mdc
```

Every pack and installed target includes self-contained `.packwright/` metadata: the canonical source snapshot, artifact lock, and checker receipt. You can relocate a target and still run `migrate`, `doctor`, and `score` without its original build directory.

## Move a working agent

`migrate` recompiles runtime-native files and carries portable state into the destination. It reports what cannot carry before it writes, then waits for an explicit `--yes`. The receipt is the proof behind “carry it everywhere,” not a promise that unlike runtimes have no seams.

## What the checks prove

- `score` evaluates the public pack structure and artifact contract. `100.0` is a structural pass, not a promise that a runtime will behave perfectly.
- `doctor` diagnoses deterministic drift and can repair Packwright-managed files without treating user memory as generated output.
- Migration verifies carried and rewritten files by hash and records planned and installed scores.
- Packwright ships six directed migration paths across the three current adapters. New adapters land when they pass the checker.

## Current release boundary

`0.1.0rc1` is a release candidate for external installation and runtime testing. The supported destination adapters are Codex, Claude Code, and Cursor. Packwright is local tooling, not cloud sync, and its plain-file structure score is separate from real runtime compatibility.

## Documentation

- [CLI contract](docs/CLI.md)
- [Use Packwright with your coding agent](docs/USE_WITH_YOUR_AGENT.md)
- [Character drafting](docs/CHARACTER_DRAFTING.md)
- [Agent archetypes](docs/AGENT_ARCHETYPES.md)
- [0.1.0rc1 release notes](docs/releases/0.1.0rc1.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

Packwright is open source under the [MIT License](LICENSE).
