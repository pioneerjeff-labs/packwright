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
Operate Packwright for me. First run `packwright --version`. Ask whether I want to create a new agent, adopt an existing local agent, or migrate an installed target. Ask for the destination adapter (`codex`, `claude-code`, or `cursor`) when build or migration begins.

For a new agent, ask what I need it to do and what name I choose. Never invent or assign the character name. Run `packwright draft-character --user-name <user-name> --prompt-out <interviewer-prompt>` and use that contract to interview me. Ask one concise question at a time, show the completed canonical `CharacterIntake` YAML, and wait for my confirmation. Save the confirmed intake, run `packwright init <intake.yaml> -o <work-dir>`, then run `packwright build <work-dir> --adapter <adapter> -o <pack-dir>` and `packwright install <pack-dir> --target <target-dir>`.

If I explicitly prefer a shortcut, offer the three nameless presets: `code`, `work`, and `companion`. Ask me to choose both the preset and the character name, then run `packwright init --template <code|work|companion> --name <chosen-name> --user-name <user-name> -o <work-dir>`. Explain that the preset shapes capabilities, voice, boundaries, memory, and continuity but does not define who the character is.

For an existing local agent, begin with `packwright adopt --from <source-dir> --dry-run`. Show the inventory and review queues. Do not merge memory or import files automatically.

Before every migration run `packwright migrate <source> --to <adapter> --target <destination> --json --dry-run`. Show the complete generated, carried, rewritten, and excluded report, then wait for my confirmation. After confirmation, rerun the same command with `--json --yes`. Never add `--force` without separate approval.

After build, install, or migrate, report the checker score. Run `packwright doctor <target>` and `packwright score <target>` after migration. If a command fails, show its real command and output. Never claim that a 100.0 structure score guarantees runtime behavior.

Packwright itself makes no network requests and sends no telemetry. My files stay under my control; the coding runtime's own data policy still applies.
```

## What this guardrail enforces

1. The agent names the real command it is about to run.
2. Migration starts with a zero-write dry run.
3. The agent shows all four receipt sections: `generated`, `carried`, `rewritten`, and `excluded`.
4. Writing waits for your confirmation; `--force` requires a separate approval.
5. The final target is checked with `doctor` and `score`.

The agent narrates the workflow. The CLI remains the source of truth for planning, writing, hashes, and scores.

For direct operation and exact flags, see the [CLI contract](CLI.md).
