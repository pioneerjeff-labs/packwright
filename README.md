# Packwright

Packwright migrates a working coding-agent setup between Codex, Claude Code, and Cursor, showing exactly what will be generated, carried, rewritten, and excluded before it writes.

The output is plain files you can read.

> Packwright itself makes no network requests and sends no telemetry. Your files stay under your control; your coding runtime's own data policy still applies.

## Quickstart

Install the current release candidate:

```bash
python -m pip install packwright==0.1.0rc1
```

Create an editable source and build it for one of the three adapters:

```bash
packwright init --template creator -o work/mira
packwright build work/mira --adapter codex -o pack/mira-codex
packwright install pack/mira-codex --target project/mira-codex
```

Supported adapters are `codex`, `claude-code`, and `cursor`. Codex emits `AGENTS.md` and `.agents/skills/`; Claude Code emits `CLAUDE.md` and `.claude/skills/`; Cursor emits `.cursor/rules/*.mdc`.

Preview a migration without creating its destination:

```bash
packwright migrate project/mira-codex \
  --to cursor \
  --target project/mira-cursor \
  --dry-run
```

Review the generated, carried, rewritten, and excluded paths. Then apply that plan explicitly:

```bash
packwright migrate project/mira-codex \
  --to cursor \
  --target project/mira-cursor \
  --yes
packwright doctor project/mira-cursor
packwright score project/mira-cursor
```

For machine-readable migration receipts, add `--json` to both the dry run and the confirmed run. Existing targets are not overwritten unless you separately opt into `--force`.

## What the score means

Packwright validates the pack structure and its public artifact contract. A score of 100.0 means those rules pass; it does not claim that a coding runtime will behave perfectly. Runtime compatibility is verified separately.

Installed targets include self-contained `.packwright/` metadata, so `migrate`, `doctor`, and `score` do not depend on the original source or build directory. Migration receipts identify the small set of adapter-routing lines that Packwright may rewrite; carried files are hash-verified.

## Use it through a coding agent

[Use Packwright with your coding agent](docs/USE_WITH_YOUR_AGENT.md) provides a paste-ready operating prompt. It requires a dry run, user confirmation, and a final receipt.

## Documentation

- [CLI contract](docs/CLI.md)
- [Character drafting](docs/CHARACTER_DRAFTING.md)
- [Agent archetypes](docs/AGENT_ARCHETYPES.md)
- [Chinese README](README.zh-CN.md)
- [0.1.0rc1 release notes](docs/releases/0.1.0rc1.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

Packwright is licensed under the [MIT License](LICENSE).
