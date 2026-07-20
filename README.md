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
  <strong><a href="https://pioneerjeff-labs.github.io/packwright/">Explore the live product website →</a></strong><br>
  Watch the animated CLI, follow a Claude Code → Codex migration, and switch the Quickstart between Claude Code, Codex, and Cursor.<br>
  <a href="https://pioneerjeff-labs.github.io/packwright/">English</a> · <a href="https://pioneerjeff-labs.github.io/packwright/zh-CN.html">简体中文</a>
</p>

<p align="center">
  <a href="https://pioneerjeff-labs.github.io/packwright/">
    <img alt="Open the Packwright live product website" src="assets/social-preview.png" width="800">
  </a>
</p>

<p align="center">
  <a href="https://pioneerjeff-labs.github.io/packwright/"><img alt="Packwright website" src="https://img.shields.io/badge/website-live-9C4F16?style=flat-square"></a>
  <a href="https://github.com/pioneerjeff-labs/packwright/actions/workflows/ci.yml"><img alt="CI status" src="https://github.com/pioneerjeff-labs/packwright/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-5C5245?style=flat-square"></a>
  <a href="README.zh-CN.md"><img alt="中文 README" src="https://img.shields.io/badge/README-中文-B87333?style=flat-square"></a>
</p>

<p align="center"><strong>Native packs. Portable state. Preview every migration before any files are written.</strong></p>

> [!NOTE]
> Packwright itself makes no network requests and sends no telemetry. Your coding runtime may still send files it reads to its own model provider; its data policy continues to apply.

## Start with your coding agent

The shortest interface is a conversation. Install Packwright, then paste the operating prompt into Codex, Claude Code, or Cursor:

```bash
python -m pip install packwright==0.1.2
```

**[Open the paste-ready agent prompt →](docs/USE_WITH_YOUR_AGENT.md)**

For a new agent, describe what it should do and choose its name. The prompt makes your coding agent draft a canonical intake, confirm it with you, build the pack, and verify the installed target. For migration, it previews the receipt and waits for approval before writing.

## Create your own

Generate Packwright's interviewer contract, then let your coding agent turn the conversation into a confirmed `character_intake.yaml`:

```bash
packwright draft-character \
  --user-name Morgan \
  --prompt-out work/character-interviewer.md
```

After the agent saves the confirmed intake, create editable source and build it:

```bash
packwright init work/nova-intake.yaml -o work/nova
packwright build work/nova --adapter claude-code -o pack/nova-claude
packwright install pack/nova-claude --adapter claude-code --target project/nova-claude
```

Already have an agent or workspace? Inventory it before importing anything:

```bash
packwright adopt --from existing-agent --dry-run
```

To create review materials, add `--target <target-dir>`. Packwright writes a source-scoped `adoption-review-<source>-<hash>.yaml` queue with every decision set to `pending`, so multiple source inventories do not overwrite one another. Review items individually, preview with `packwright adopt --review <queue> --target-dir <target> --dry-run`, then replace `--dry-run` with `--yes`. Approved safe copies and source registrations can be applied; memory merge and knowledge promotion remain manual.

Without a coding agent, `packwright init --interactive` offers a fixed-question fallback. It shows the completed canonical YAML and waits for confirmation before writing.

## Or use a nameless starter

Three presets cover common starting points. Customize responsibilities, capabilities, voice, boundaries, and emotional feedback; the preset shapes how the agent works, while you always choose its name.

| Preset | Starting role |
|---|---|
| `code` | Expert engineer — builds, reviews, debugs, tests, and ships technical work |
| `work` | Versatile assistant — plans projects, drafts deliverables, clarifies decisions, and keeps execution moving |
| `companion` | Personal secretary — supports daily routines, life decisions, travel planning, and emotional support |

Inspect the exact defaults, choose a preset, and supply the character name yourself. Preset-based init returns the full character summary for review before build.

If you already have a confirmed intake, `packwright new` can run init, build,
and install together without discarding the intermediate source or pack:

```bash
packwright new work/nova-intake.yaml --adapter claude-code \
  --work-dir work/nova --pack-dir pack/nova-claude \
  --target project/nova-claude
```

It is fresh-path only: work, pack, and target must not already exist or overlap.
Preset use requires an explicit `--accept-preset` assertion after review.

```bash
packwright presets code
packwright init --template code --name Nova --user-name Morgan -o work/nova
packwright build work/nova --adapter claude-code -o pack/nova-claude
packwright install pack/nova-claude --adapter claude-code --target project/nova-claude
```

Compiler-owned boilerplate supports English and Simplified Chinese. Put
`locale: zh-CN` in a `CharacterIntake`, or pass `--locale zh-CN` with a preset.
English is the deterministic fallback for missing or unsupported values;
Packwright leaves user-authored prose unchanged.

`Nova` is only an example of a user-chosen name. Edit the generated name, relationship, voice, and boundaries whenever you need.

Preview a move from Claude Code to Codex. The destination is not created during this step:

```bash
packwright migrate project/nova-claude \
  --to codex \
  --target project/nova-codex --dry-run
```

The plan names four kinds of paths:

| Receipt section | Meaning |
|---|---|
| `generated` | Files compiled for the destination runtime |
| `carried` | Portable user files copied and SHA-256 verified |
| `rewritten` | Packwright-managed routing lines changed for the destination |
| `degraded` | Unmanaged runtime automation detected but not reproduced without explicit acceptance |
| `excluded` | Runtime-specific files deliberately left behind |

After reviewing the receipt, apply that exact move and verify the result:

```bash
packwright migrate project/nova-claude \
  --to codex \
  --target project/nova-codex --yes
packwright doctor project/nova-codex
packwright score project/nova-codex
```

Upgrade the mechanism of one installed local instance separately from work
handoff or cross-runtime migration:

```bash
packwright reconcile --target project/nova-codex --mechanism work/nova --json --dry-run
packwright reconcile --target project/nova-codex --mechanism work/nova --json --yes
```

Mechanism 0.8 projects bounded local `session_start` and `user_prompt` context
from canonical `automations`. Claude Code and Codex support both events. Cursor
supports session-start context but reports prompt-time context as an explicit
capability gap. Existing user settings and hook entries are preserved by
entry-level managed merges.

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
- `doctor` verifies Packwright-managed projection hashes and can repair reproducible drift without treating portable user state as generated output.
- Migration verifies carried and rewritten files in the destination, rechecks detected degraded source files before writing, records planned and installed scores, and never silently treats runtime automation as portable. When degraded items exist, non-interactive apply also requires `--accept-degraded`.
- Reconcile compares installed and desired canonical spec hashes, preserves instance state, and writes a local receipt without reverse-compiling another runtime's hooks.
- Packwright ships six directed migration paths across the three current adapters. New adapters land when they pass the checker.

## Current release boundary

`0.1.2` is the current stable release; `0.1.0` remains the first stable baseline. The supported destination adapters are Codex, Claude Code, and Cursor. Packwright is local tooling, not cloud sync, and its plain-file structure score is separate from real runtime compatibility.

## Documentation

- [Live product website](https://pioneerjeff-labs.github.io/packwright/) · [简体中文](https://pioneerjeff-labs.github.io/packwright/zh-CN.html)
- [CLI contract](docs/CLI.md)
- [Use Packwright with your coding agent](docs/USE_WITH_YOUR_AGENT.md)
- [Character drafting](docs/CHARACTER_DRAFTING.md)
- [Agent archetypes](docs/AGENT_ARCHETYPES.md)
- [Optional Emotion Engine MCP runtime](docs/EMOTION_ENGINE.md)
- [Local runtime automations](docs/RUNTIME_AUTOMATIONS.md)
- [0.1.2 release notes](docs/releases/0.1.2.md)
- [0.1.1 release notes](docs/releases/0.1.1.md)
- [0.1.0 release notes](docs/releases/0.1.0.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

Packwright is open source under the [MIT License](LICENSE).
