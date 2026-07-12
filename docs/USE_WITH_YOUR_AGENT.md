# Use Packwright with your coding agent

Packwright's CLI is the deterministic engine. Codex, Claude Code, or Cursor can be the conversational interface: it can ask what you want, run the commands, explain the migration receipt, and stop before anything is written.

## Before you paste the prompt

Install the current release candidate in the environment your coding agent can access:

```bash
python -m pip install packwright==0.1.0rc1
packwright --version
```

Use synthetic or reviewed files while evaluating the release candidate. Do not give a coding runtime access to secrets or private memory that its own data policy does not permit.

## Paste this prompt

```text
Operate Packwright for me. First run `packwright --version`. Ask whether I want to build a new agent or migrate an existing target, and ask for the destination adapter (`codex`, `claude-code`, or `cursor`).

For a new agent, run `packwright init --template <productivity|creator|companion> -o <work-dir>`, edit only the generated source according to my description, then run `packwright build <work-dir> --adapter <adapter> -o <pack-dir>` and `packwright install <pack-dir> --target <target-dir>`.

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
