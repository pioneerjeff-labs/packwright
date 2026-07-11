# Use Packwright with your coding agent

Paste the following into Codex, Claude Code, or Cursor:

```text
Operate Packwright for me. First run `packwright --version`. Ask whether I want to build a new agent or migrate an existing target, and ask for the destination adapter (`codex`, `claude-code`, or `cursor`).

For a new agent, run `packwright init --template <productivity|creator|companion> -o <work-dir>`, edit only the generated source according to my description, then run `packwright build <work-dir> --adapter <adapter> -o <pack-dir>` and `packwright install <pack-dir> --target <target-dir>`.

Before every migration run `packwright migrate <source> --to <adapter> --target <destination> --json --dry-run`. Show the complete generated, carried, rewritten, and excluded report, then wait for my confirmation. After confirmation, rerun the same command with `--json --yes`. Never add `--force` without separate approval.

After build, install, or migrate, report the checker score. Run `packwright doctor <target>` and `packwright score <target>` after migration. If a command fails, show its real command and output. Never claim that a 100.0 structure score guarantees runtime behavior.

Packwright itself makes no network requests and sends no telemetry. My files stay under my control; the coding runtime's own data policy still applies.
```
