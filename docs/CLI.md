# Packwright CLI contract

This is the public command surface for Packwright 0.1. Commands not listed here
are compatibility or development commands and are intentionally omitted from
the default help screen.

## Core commands

| Command | Purpose |
|---|---|
| `packwright new` | Create source, build a pack, and install a fresh target while preserving all three directories. |
| `packwright init` | Create editable agent source from your intake or a nameless starter preset. |
| `packwright draft-character` | Print the interviewer contract used by a coding agent to draft a custom intake. |
| `packwright presets` | List or inspect the exact defaults for nameless starter presets. |
| `packwright adopt` | Inventory an existing local agent for review before adoption. |
| `packwright build` | Validate the source, compile an adapter pack, and score it. |
| `packwright install` | Install an adapter pack into a local runtime target. |
| `packwright migrate` | Compile and install an existing target for another adapter. |
| `packwright reconcile` | Upgrade one installed target from a newer canonical mechanism without mixing work-state into mechanism. |
| `packwright doctor` | Diagnose and optionally repair deterministic target drift. |
| `packwright score` | Score an adapter pack against its mechanism source. |

Check the installed version with `packwright --version`.

## Canonical syntax

For a confirmed intake and fresh paths, the one-command form preserves the
same source and pack artifacts as the three-command flow:

```bash
packwright new work/nova-intake.yaml \
  --adapter claude-code \
  --work-dir work/nova \
  --pack-dir pack/nova-claude \
  --target project/nova-claude
```

`new` never overwrites or nests its work, pack, and target directories. A
preset can be used only with `--accept-preset`, which asserts that its exact
defaults were already reviewed. Existing targets still use `migrate`, not
`new`.

```bash
packwright draft-character --user-name Morgan --prompt-out work/character-interviewer.md
packwright init work/nova-intake.yaml -o work/nova

# Basic terminal fallback: preview and confirm canonical YAML before any write.
packwright init --interactive --user-name Morgan -o work/nova

# Shortcut: choose a nameless capability preset, then supply the name yourself.
packwright presets code
packwright init --template code --name Nova --user-name Morgan -o work/nova

# Simplified Chinese compiler boilerplate; unknown locale values fall back to English.
packwright init --template work --name 小北 --slug xiaobei --user-name 老登 --locale zh-CN -o work/xiaobei

packwright build work/nova --adapter claude-code -o pack/nova-claude
packwright install pack/nova-claude --adapter claude-code --target project/nova-claude --dry-run
packwright install pack/nova-claude --adapter claude-code --target project/nova-claude
packwright migrate project/nova-claude --to codex --target project/nova-codex --json --dry-run
packwright migrate project/nova-claude --to codex --target project/nova-codex --json --yes
packwright reconcile --target project/nova-codex --mechanism work/nova --json --dry-run
packwright reconcile --target project/nova-codex --mechanism work/nova --json --yes
packwright doctor project/nova-codex
packwright score work/nova --adapter claude-code --pack-dir pack/nova-claude
packwright score project/nova-codex

# Existing agent: inventory first; adoption never merges memory automatically.
packwright adopt --from existing-agent --dry-run
packwright adopt --from existing-agent --target project/nova
```

`install` reads the adapter from the pack manifest. `--adapter` is optional and
acts as an assertion: when supplied, it must match the manifest. Keeping it in
an automated command is useful for making the expected runtime explicit.

The three public starter presets are `code`, `work`, and `companion`. They contain capability, voice, boundary, memory, and continuity defaults, but no character name. Run `packwright presets` to list all exact defaults or `packwright presets <name>` to inspect one. `--name` is required with `--template`; the generated source remains fully editable.

Preset-based `init` output includes the complete `character_summary`, the source files most relevant for editing it, and an explicit review step before `build`. Show that summary to the user instead of reporting only the generated file list.

`init --interactive` is a deterministic terminal fallback, not an LLM interviewer. It prints the completed canonical `CharacterIntake` YAML and requires confirmation before writing the intake or source directory. Rejecting the preview writes nothing.

For intake-file creation, put `locale: en` or `locale: zh-CN` at the document
root. `--locale` applies to `--template` and `--interactive`. Locale changes
only compiler-owned text; Packwright never translates user-authored prose.

`adopt --dry-run` only returns the inventory and review summary. With an explicit target, adopt writes source-scoped `inventory-<source>-<hash>.json`, a Markdown report, and `adoption-review-<source>-<hash>.yaml` under `workspace/shared/artifacts/migrations/`. The source key prevents multi-source review artifacts from colliding. Existing knowledge and source manifests are never replaced by scaffold content, including when `--force` refreshes review artifacts. The `packwright-adoption-review/v1` queue records path, category, size, SHA-256, a `pending` decision, optional destination, and rationale for every candidate.

After reviewing individual items, preview the action plan and then apply it:

```bash
packwright adopt --review <adoption-review.yaml> --target-dir <target> --dry-run
packwright adopt --review <adoption-review.yaml> --target-dir <target> --yes
```

Approved copies are limited to explicit `workspace/*` or unmanaged `skills/*`
destinations, never overwrite different content, and are rechecked against the
inventoried SHA-256. `manual_memory_merge` records the intended `memory/*`
owner but never writes it; knowledge promotion also remains manual.
`manual_automation_merge` writes an evidence-only canonicalization draft with
an empty `canonical_automations` list. It never reverse-compiles hooks or edits
the canonical mechanism.

`init` and `build` accept `-o` as the short form of `--out-dir`. `install`,
`migrate`, and `doctor` accept `--target` as the short form of `--target-dir`.
The longer pre-release forms such as `--pack-dir` and `--source-target-dir`
remain accepted for compatibility.

`build` refuses to overwrite existing pack artifacts unless `--force` is
explicitly supplied. `install --force` replaces Packwright-managed runtime
projections while preserving existing `memory/`, `workspace/`, `knowledge/`,
and `sources/` state.

Before forcing an existing target, preview the exact forced operation with the
same arguments:

```bash
packwright install pack/nova-claude --target project/nova-claude --force --dry-run
packwright install pack/nova-claude --target project/nova-claude --force
```

The `packwright-install/v1` plan reports files that would be added,
overwritten, merged as managed hook configuration, removed as stale managed
projection, or preserved as portable/live state. Dry-run writes neither the
target nor its local provenance record. Apply rechecks the source pack, target
managed-artifact set, and Emotion Engine MCP configuration before writing.

Runtime-neutral mechanism 0.8 stores local `session_start` and `user_prompt`
context automation under `automations`. Build projects those entries into
`.claude/settings.json`, `.codex/hooks.json`, or `.cursor/hooks.json` plus a
bounded local Python runner. Cursor cannot inject dynamic context at
`beforeSubmitPrompt`, so its `user_prompt` entries are reported as
`unavailable_missing_effect` rather than mapped to a static rule.

Packs built by Packwright and their installed targets include portable
`.packwright/` metadata: a canonical spec/source snapshot, artifact lock, and
checker receipt. `score`, `doctor`, and `migrate` can therefore use a relocated
installed target without its original work or pack directory. Shareable
`manifest.json` uses relative metadata references instead of the build
machine's absolute source path.

`doctor` consumes the artifact lock for Packwright-managed projections.
Portable state and live Emotion Engine state are intentionally excluded from
managed hash repair. It also reports the installed spec/lock digests and the
local source-pack record stored in `.packwright/install-provenance.json` when
available; a moved or deleted source pack is reported as unavailable rather
than inferred.

See [Emotion Engine runtime](EMOTION_ENGINE.md) for the explicit multi-adapter
install, MCP configuration, state-safety, refresh, and migration boundaries.

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
2. Review `generated`, `carried`, `rewritten`, `degraded`, and `excluded`, plus the planned
   checker score and any destination conflicts.
3. After confirmation, rerun the same command with `--yes`. If the plan lists
   degraded runtime automation, non-interactive apply also requires
   `--accept-degraded`; `--yes` alone does not accept missing behavior.
   Non-interactive execution without `--dry-run` or `--yes` exits without
   writing.

Use `--json` for the `packwright-migration/v1` receipt. Interactive terminals
otherwise show a compact directory-level summary and prompt before applying.
After apply, the receipt contains the planned score, installed-target score,
and SHA-256 verification for every carried or rewritten destination file. It
also rechecks every detected degraded source file before writing. Packwright may
rewrite only adapter-routing lines in `memory/index.md`, `memory/pinned.md`,
and `memory/source-map.md`; every actual rewrite is disclosed.

## Reconcile safety contract

`packwright reconcile --target <installed> --mechanism <canonical> --dry-run`
compares installed and desired spec hashes and reports managed projection
updates, preserved instance state, safe missing scaffolds, manual JSON merges,
runtime capability gaps, and pending activation reviews. It never reads another
runtime's generated hook as its source.

After review, replace `--dry-run` with `--yes`. Capability gaps additionally
require `--accept-degraded`. Reconcile preserves existing portable state and
merges only entries containing the Packwright runner marker in runtime JSON;
unrelated user settings and hooks remain untouched. Its applied
`packwright-reconcile/v1` receipt is stored under `.packwright/receipts/`.

## Compatibility commands

The following commands remain callable but are not part of the default 0.1
help surface: `init-character`, `run`, `migrate-target`, `validate`, `resolve`,
`compile` and `handoff-export`. `refresh-emotion-engine-codex` remains a
deprecated alias for the public `refresh-emotion-engine` command.
