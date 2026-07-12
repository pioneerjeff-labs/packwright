# Packwright CLI contract

This is the public command surface for Packwright 0.1. Commands not listed here
are compatibility or development commands and are intentionally omitted from
the default help screen.

## Core commands

| Command | Purpose |
|---|---|
| `packwright init` | Create editable agent source from a starter template or intake file. |
| `packwright build` | Validate the source, compile an adapter pack, and score it. |
| `packwright install` | Install an adapter pack into a local runtime target. |
| `packwright migrate` | Compile and install an existing target for another adapter. |
| `packwright doctor` | Diagnose and optionally repair deterministic target drift. |
| `packwright score` | Score an adapter pack against its mechanism source. |

Check the installed version with `packwright --version`.

## Canonical syntax

```bash
packwright init --template creator --user-name Morgan -o work/mira
packwright build work/mira --adapter claude-code -o pack/mira-claude
packwright install pack/mira-claude --adapter claude-code --target project/mira-claude
packwright migrate project/mira-claude --to codex --target project/mira-codex --json --dry-run
packwright migrate project/mira-claude --to codex --target project/mira-codex --json --yes
packwright doctor project/mira-codex
packwright score work/mira --adapter claude-code --pack-dir pack/mira-claude
packwright score project/mira-codex
```

`init` and `build` accept `-o` as the short form of `--out-dir`. `install`,
`migrate`, and `doctor` accept `--target` as the short form of `--target-dir`.
The longer pre-release forms such as `--pack-dir` and `--source-target-dir`
remain accepted for compatibility.

Packs built by Packwright and their installed targets include portable
`.packwright/` metadata: a canonical spec/source snapshot, artifact lock, and
checker receipt. `score`, `doctor`, and `migrate` can therefore use a relocated
installed target without its original work or pack directory. Shareable
`manifest.json` uses relative metadata references instead of the build
machine's absolute source path.

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
`compile`, `draft-character`, `handoff-export`, `adopt`, and
`refresh-emotion-engine-codex`.
