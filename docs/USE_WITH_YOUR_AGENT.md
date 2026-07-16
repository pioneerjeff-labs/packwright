# Use Packwright with your coding agent

Packwright's CLI is the deterministic engine. Codex, Claude Code, or Cursor can be the conversational interface: it can ask what you want, run the commands, explain the migration receipt, and stop before anything is written.

## Before you paste the prompt

Install Packwright in the environment your coding agent can access:

```bash
python -m pip install packwright==0.1.0
packwright --version
```

Use synthetic or reviewed files while evaluating Packwright. Do not give a coding runtime access to secrets or private memory that its own data policy does not permit.

## Paste this prompt

```text
Operate Packwright for me. First run `packwright --version`. Ask whether I want to create a new agent, adopt an existing local agent, or migrate an installed target. Ask for the destination adapter (`codex`, `claude-code`, or `cursor`) when build or migration begins, and use that same adapter for install.

For a new agent, ask what I need it to do and what name I choose. Never invent or assign the character name. Run `packwright draft-character --user-name <user-name> --prompt-out <interviewer-prompt>` and use that contract to interview me. Ask one concise question at a time, show the completed canonical `CharacterIntake` YAML, and wait for my confirmation. Save the confirmed intake, run `packwright init <intake.yaml> -o <work-dir>`, then run `packwright build <work-dir> --adapter <adapter> -o <pack-dir>` and `packwright install <pack-dir> --adapter <adapter> --target <target-dir>`.

If I explicitly prefer a shortcut, offer the three nameless presets: `code`, `work`, and `companion`. Ask me to choose a preset, run `packwright presets <chosen-preset>`, and show me its exact role, voice, traits, avoid list, work areas, and continuity defaults. Ask for the character name and wait for my confirmation before running `packwright init --template <code|work|companion> --name <chosen-name> --user-name <user-name> -o <work-dir>`. After init, show the returned `character_summary` and editable files. Do not begin build until I confirm or edit that summary. Explain that the preset shapes capabilities, voice, boundaries, memory, and continuity but does not define who the character is.

For an existing local agent, begin with `packwright adopt --from <source-dir> --dry-run`. Show the inventory and review summary. If I ask to create review materials, run `packwright adopt --from <source-dir> --target-dir <target-dir>` and show me the generated `adoption-review.yaml`. Its decisions begin as `pending`; review them with me one by one. Preview reviewed actions with `packwright adopt --review <queue> --target-dir <target-dir> --dry-run`, wait for confirmation, then replace `--dry-run` with `--yes`. Never turn `manual_memory_merge` into an automatic copy; memory merge and knowledge promotion remain manual.

Before every migration run `packwright migrate <source> --to <adapter> --target <destination> --json --dry-run`, where `<source>` is the directory previously installed into. Show the complete generated, carried, rewritten, and excluded report, then wait for my confirmation. After confirmation, run the same command again with `--yes` in place of `--dry-run`. Never add `--force` without separate approval. During migration, never edit user-authored content under `memory/` or `workspace/`; let Packwright perform only the adapter-routing rewrites reported in the receipt.

After build, install, or migrate, report the checker score. After install, read `.packwright/checker-receipt.json` in the target or run `packwright score <target>`. Run `packwright doctor <target>` and `packwright score <target>` after migration. `doctor --fix` requires my separate approval, just like `--force`. If a command fails, show its real command and output. Never claim that a 100.0 structure score guarantees runtime behavior.

Packwright itself makes no network requests and sends no telemetry. It reads and writes local files; the coding runtime's own data policy still applies to anything that runtime can access.
```

## What this prompt asks the agent to do

1. The agent names the real command it is about to run.
2. Migration starts with a zero-write dry run.
3. The agent shows all four receipt sections: `generated`, `carried`, `rewritten`, and `excluded`.
4. The agent does not hand-edit user-authored `memory/` or `workspace/` content during migration.
5. Writing waits for your confirmation; `--force` and `doctor --fix` require separate approval.
6. The final target is checked with `doctor` and `score`.

These are instructions to the coding agent, not CLI-enforced permissions. The CLI mechanically guarantees that migration dry-run does not write; the other stops depend on the agent following the prompt. Packwright remains the source of truth for migration plans, writes, receipts, and scores.

For direct operation and exact flags, see the [CLI contract](CLI.md).
