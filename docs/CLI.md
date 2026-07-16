# Packwright CLI contract

This is the public command surface for Packwright 0.1. Commands not listed here
are compatibility or development commands and are intentionally omitted from
the default help screen.

## Core commands

| Command | Purpose |
|---|---|
| `packwright init` | Create editable agent source from your intake or a nameless starter preset. |
| `packwright draft-character` | Print the interviewer contract used by a coding agent to draft a custom intake. |
| `packwright presets` | List or inspect the exact defaults for nameless starter presets. |
| `packwright adopt` | Inventory an existing local agent for review before adoption. |
| `packwright build` | Validate the source, compile an adapter pack, and score it. |
| `packwright install` | Install an adapter pack into a local runtime target. |
| `packwright migrate` | Compile and install an existing target for another adapter. |
| `packwright doctor` | Diagnose and optionally repair deterministic target drift. |
| `packwright score` | Score an adapter pack against its mechanism source. |

Check the installed version with `packwright --version`.

## Canonical syntax

```bash
packwright draft-character --user-name Morgan --prompt-out work/character-interviewer.md
packwright init work/nova-intake.yaml -o work/nova

# Basic terminal fallback: preview and confirm canonical YAML before any write.
packwright init --interactive --user-name Morgan -o work/nova

# Shortcut: choose a nameless capability preset, then supply the name yourself.
packwright presets code
packwright init --template code --name Nova --user-name Morgan -o work/nova

packwright build work/nova --adapter claude-code -o pack/nova-claude
packwright install pack/nova-claude --adapter claude-code --target project/nova-claude
packwright migrate project/nova-claude --to codex --target project/nova-codex --json --dry-run
packwright migrate project/nova-claude --to codex --target project/nova-codex --json --yes
packwright doctor project/nova-codex
packwright score work/nova --adapter claude-code --pack-dir pack/nova-claude
packwright score project/nova-codex

# Existing agent: inventory first; adoption never merges memory automatically.
packwright adopt --from existing-agent --dry-run
packwright adopt --from existing-agent --target project/nova
```

The three public starter presets are `code`, `work`, and `companion`. They contain capability, voice, boundary, memory, and continuity defaults, but no character name. Run `packwright presets` to list all exact defaults or `packwright presets <name>` to inspect one. `--name` is required with `--template`; the generated source remains fully editable.

Preset-based `init` output includes the complete `character_summary`, the source files most relevant for editing it, and an explicit review step before `build`. Show that summary to the user instead of reporting only the generated file list.

`init --interactive` is a deterministic terminal fallback, not an LLM interviewer. It prints the completed canonical `CharacterIntake` YAML and requires confirmation before writing the intake or source directory. Rejecting the preview writes nothing.

`adopt --dry-run` only returns the inventory and review summary. With an explicit target, adopt writes `inventory.json`, a Markdown report, and `adoption-review.yaml` under `workspace/shared/artifacts/migrations/`. The `packwright-adoption-review/v1` queue records path, category, size, SHA-256, a `pending` decision, optional destination, and rationale for every candidate. Packwright 0.1 does not apply this queue or merge content automatically.

`init` and `build` accept `-o` as the short form of `--out-dir`. `install`,
`migrate`, and `doctor` accept `--target` as the short form of `--target-dir`.
The longer pre-release forms such as `--pack-dir` and `--source-target-dir`
remain accepted for compatibility.

`build` refuses to overwrite existing pack artifacts unless `--force` is
explicitly supplied. `install --force` replaces Packwright-managed runtime
projections while preserving existing `memory/`, `workspace/`, `knowledge/`,
and `sources/` state.

Packs built by Packwright and their installed targets include portable
`.packwright/` metadata: a canonical spec/source snapshot, artifact lock, and
checker receipt. `score`, `doctor`, and `migrate` can therefore use a relocated
installed target without its original work or pack directory. Shareable
`manifest.json` uses relative metadata references instead of the build
machine's absolute source path.

`doctor` consumes the artifact lock for Packwright-managed projections.
Portable state and live Emotion Engine state are intentionally excluded from
managed hash repair.

See [Emotion Engine sidecar](EMOTION_ENGINE.md) for the explicit Codex install,
mode, refresh, and migration boundaries.

## Adapter layout contract

Packwright 0.1 emits one canonical repository layout per runtime:

| Adapter | Entry | Reusable procedure |
|---|---|---|
| Codex | `AGENTS.md` | `.agents/skills/<name>/SKILL.md` |
| Claude Code | `CLAUDE.md` | `.claude/skills/<name>/SKILL.md` |
| Cursor | `.cursor/rules/<name>.mdc` | `.cursor/rules/<name>-save-context.mdc` |

New Codex packs do not emit `.codex/skills/`. `doctor` reports that legacy
Packwright layout and `doctor --fix` moves it to `.agents/skills/`, updating
managed manifest and routing references. If old and new copies both exist,
doctor reports a conflict and does not overwrite either copy. Claude Code and
Cursor already use their current canonical project layouts and require no path
migration.

## Migration safety contract

`packwright migrate` separates planning from writing:

1. Run with `--dry-run` to receive the complete path-level plan. Neither the
   destination target nor `--pack-dir` is created.
2. Review `generated`, `carried`, `rewritten`, and `excluded`, plus the planned
   checker score and any destination conflicts.
3. After confirmation, rerun the same command with `--yes`. Non-interactive
   execution without `--dry-run` or `--yes` exits without writing.

Use `--json` for the `packwright-migration/v1` receipt. Interactive terminals
otherwise show a compact directory-level summary and prompt before applying.
After apply, the receipt contains the planned score, installed-target score,
and SHA-256 verification for every carried or rewritten file. Packwright may
rewrite only adapter-routing lines in `memory/index.md`, `memory/pinned.md`,
and `memory/source-map.md`; every actual rewrite is disclosed.

## Compatibility commands

The following commands remain callable but are not part of the default 0.1
help surface: `init-character`, `run`, `migrate-target`, `validate`, `resolve`,
`compile`, `handoff-export`, and `refresh-emotion-engine-codex`.
