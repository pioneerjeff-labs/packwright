# Packwright

Build once, deploy your agent behavior everywhere.

Packwright is an agent pack compiler for AI-native builders and teams. It turns working style, project memory, collaboration rules, and agent behavior into portable, checkable, versionable packs for AI coding tools.

Today: Codex, Claude Code, and Cursor.

```text
Working style + memory contract + collaboration rules
        |
        v
      one spec
        |
        v
  runtime-specific agent packs
        |
        +-- Codex
        +-- Claude Code
        `-- Cursor
```

Most AI coding tools now have their own instruction format: `AGENTS.md`, `CLAUDE.md`, project rules, local skills, and workspace conventions. That creates a new maintenance problem: your agent's behavior and memory get locked into one tool's folder format.

Packwright gives you one source of truth:

- define the agent's working style once
- generate runtime-specific packs
- keep memory and workspace boundaries explicit
- score the generated pack before using it
- install and repair local targets without resetting state

This is not just a prompt. It is a local operating package for long-running AI work.

## What It Generates

For Codex:

- `AGENTS.md`
- `.agents/skills/<agent>-save-context/SKILL.md`
- `.codex/<agent>/references/**`
- `memory/**`
- `workspace/**`
- `manifest.json`

For Claude Code:

- `CLAUDE.md`
- `.claude/skills/<agent>-save-context/SKILL.md`
- `.claude/settings.local.json.example`
- `.claude/<agent>/references/**`
- `memory/**`
- `workspace/**`
- `manifest.json`

For Cursor:

- `.cursor/rules/<agent>.mdc`
- `.cursor/rules/<agent>-memory.mdc`
- `.cursor/rules/<agent>-save-context.mdc`
- `.cursor/<agent>/references/**`
- `memory/**`
- `workspace/**`
- `manifest.json`

The same mechanism spec can project into different runtime packages while keeping the same memory contract and collaboration model.

## Quickstart

Install Packwright:

```bash
pipx install packwright
```

Or run it directly with `uvx`:

```bash
uvx packwright --help
```

The stable command surface is documented in [docs/CLI.md](docs/CLI.md).

Generate a starter character from a built-in template:

```bash
packwright init \
  --template creator \
  --user-name Morgan \
  -o build/mira-work \
  --save-intake build/mira-intake.yaml
```

Starter templates include `productivity`/`system`, `creator`/`mira`, and `companion`/`lumen`. Use `--interactive` only when you want the basic fixed-question fallback.

Build and score a Codex pack:

```bash
packwright build \
  build/mira-work \
  --adapter codex \
  -o build/mira-codex-pack
```

Build and score a Claude Code pack:

```bash
packwright build \
  build/mira-work \
  --adapter claude-code \
  -o build/mira-claude-pack
```

Build and score a Cursor pack:

```bash
packwright build \
  build/mira-work \
  --adapter cursor \
  -o build/mira-cursor-pack
```

Install a generated Codex pack into a local Codex project:

```bash
packwright install \
  build/mira-codex-pack \
  --adapter codex \
  --target /path/to/codex-project
```

Install refuses to overwrite existing target artifacts by default. Use `--force` only after reviewing the target files.

Migrate an installed target into another adapter while preserving portable memory and workspace state:

```bash
# Preview the exact plan. This creates neither the target nor the pack directory.
packwright migrate \
  /path/to/codex-project \
  --to cursor \
  --target /path/to/cursor-project \
  --pack-dir build/mira-cursor-migration-pack \
  --slug mira \
  --json \
  --dry-run

# After reviewing generated/carried/rewritten/excluded, apply the same plan.
packwright migrate \
  /path/to/codex-project \
  --to cursor \
  --target /path/to/cursor-project \
  --pack-dir build/mira-cursor-migration-pack \
  --slug mira \
  --json \
  --yes
```

Migration reports every manifest-owned path under `generated`, `carried`,
`rewritten`, or `excluded`. Carried files are verified by SHA-256 after apply;
adapter routing lines in `memory/index.md`, `memory/pinned.md`, and
`memory/source-map.md` are listed explicitly when rewritten. The destination
projection is scored before writing and the installed target is scored again
after apply. Non-interactive writes require `--yes`; an interactive terminal
shows the plan and asks for confirmation. Existing target or pack content is a
conflict unless `--force` is explicitly supplied. For non-Codex targets,
`.emotion-engine/codex-state.json` is carried only as an inert snapshot.

## Why Not Just Prompts?

Prompts are easy to copy and hard to maintain.

Packwright treats agent behavior as a compiled package:

- **portable**: one spec can project into different AI coding tools
- **structured**: identity, operating rules, memory, workspace, and skills have separate owners
- **checkable**: generated packs can be validated and scored
- **repairable**: installed Codex sidecars can be refreshed and doctored without resetting local state
- **promotable**: mature workstreams can become dedicated agents instead of bloating one master prompt

## Product Pillars

### Agent Pack Compiler

Compile one behavior spec into runtime-specific files for AI coding tools.

```text
character_intake.yaml
        |
        v
mechanism.yaml  ---- validate / resolve ---- score
        |
        v
  Packwright
        |
        +--> Codex: AGENTS.md + skills + memory + workspace + manifest
        |
        +--> Claude Code: CLAUDE.md + skills + memory + workspace + manifest
        |
        `--> Cursor: .cursor/rules/*.mdc + memory + workspace + manifest
```

### Memory Contract

Keep long-running context in explicit owner files instead of one giant prompt.

The generated memory model separates:

- `memory/index.md`: default router and owner map
- `memory/profile.md`: stable user, team, creator, or relationship facts
- `memory/workstreams.md`: long-running domain routing
- `memory/workstreams/<slug>.md`: mature domain state
- `memory/projects/<slug>.md`: project state, decisions, and open loops
- `memory/session-index.md`: session/thread recall
- `memory/source-map.md`: source and verification pointers
- `memory/todos.md`: action queues and commitments
- `memory/collaboration.md`: collaboration calibration
- `workspace/`: generated drafts, artifacts, and archives

Memory files are not a content warehouse. Generated deliverables belong in `workspace/<domain>/drafts|artifacts|archive`, with important outputs indexed through `memory/source-map.md`.

### Runtime Adapters

Codex is the primary adapter. Claude Code and Cursor are supported as secondary projections. Cursor support emits project rules under `.cursor/rules/*.mdc`; it does not implement a separate runtime.

The source tree separates durable identity from mechanisms and run state:

- `identity/`: persona, voice, and relationship model
- `operating/`: durable principles and behavior boundaries
- `mechanism/`: context loading, session guards, and memory policy
- `emotion/`: reserved Emotion Engine schema and policies
- `projection/`: platform capabilities and ownership contracts
- `skills/`: repeatable heavy procedures, currently `save-context`
- `memory/`: local file-memory skeletons
- `workspace/`: generated drafts, reusable artifacts, and archived outputs

### Quality Checker

Generated packs can be validated and scored before they break your workflow.

Useful commands:

```bash
packwright validate templates/atlas-work/mechanism.yaml
packwright resolve templates/atlas-work/mechanism.yaml --out build/resolved.json
packwright compile templates/atlas-work/mechanism.yaml --adapter codex --out-dir build/codex
packwright score templates/atlas-work/mechanism.yaml --pack-dir build/codex
```

### Workstream Promotion

Start with one AI partner. Promote mature workstreams into dedicated agents when they deserve their own memory, cadence, source map, and acceptance criteria.

This is a product direction, not a fully automated command yet. The current architecture already models the path:

```text
memory/workstreams.md entry
  -> memory/workstreams/<slug>.md detail file
  -> generated independent agent
  -> parent agent keeps routing and final acceptance unless ownership moves
```

See [docs/AGENT_ARCHETYPES.md](docs/AGENT_ARCHETYPES.md) for archetypes and the workstream-to-agent promotion model.

## Codex-First Character Creation

In normal use, stay in Codex and ask for a new agent directly:

```text
Make me an Alice agent. She is my media planning and publishing partner, direct, sharp but not cruel, and she can support light emotional continuity.
```

Codex should interview you dynamically, write `build/<slug>-intake.yaml`, show a short confirmation summary, then run the deterministic compiler and installer internally. You should not need to switch between Codex and Terminal.

See [docs/CODEX_CHARACTER_WORKFLOW.md](docs/CODEX_CHARACTER_WORKFLOW.md) for the Codex-side workflow.

## CLI Backend

The CLI remains useful for automation, tests, and debugging.

Generate the interviewer contract for another LLM surface:

```bash
packwright draft-character \
  --user-name Morgan \
  --prompt-out build/character-interviewer.md
```

Then compile the confirmed intake:

```bash
packwright init \
  build/alice-intake.yaml \
  -o build/alice-work
```

The deterministic compiler starts from canonical intake YAML. It does not interpret messy natural language; the interviewer layer does that before compilation.

There is also a basic fallback prompt mode:

```bash
packwright init \
  --interactive \
  --user-name Morgan \
  -o build/basic-character-work \
  --save-intake build/basic-character-intake.yaml
```

This fallback is intentionally simple and does not semantically normalize answers. Prefer the LLM interviewer path for real character creation.

## Cross-Agent Handoffs

Handoffs are reviewable communication files, not target sync. The source target declares changed paths, recommended reads, and next steps; the receiving agent decides what to inspect and records any durable state in its own memory files.

Source-repo command:

```bash
packwright handoff-export \
  --source-target-dir /path/to/source-target \
  --out /path/to/source-target/workspace/shared/artifacts/handoffs/source-to-target.md \
  --summary "What changed and what the receiver should know" \
  --changed memory/projects/example.md \
  --read memory/source-map.md \
  --next-step "Review the changed project state"
```

Generated Cursor targets also include `scripts/handoff_export.sh` and `scripts/packwright_handoff.py`, so they can write handoff files without importing the Packwright source package.

Use `workspace/shared/artifacts/handoffs/` for real cross-agent or cross-runtime handoffs. Use `workspace/shared/artifacts/session-briefs/` for same-agent next-session preparation files.

## Optional Emotion Engine Codex Sidecar

Codex installs can include the Emotion Engine sidecar for local state modulation in long-running collaboration. Durable memory and Emotion Engine runtime state stay separate.

The sidecar is optional. Plain Codex installs do not require Emotion Engine. To install the sidecar, pass a local sidecar source path or set `PACKWRIGHT_EMOTION_ENGINE_CODEX_DIR`.

Install a generated Codex pack with the sidecar:

```bash
packwright install \
  build/codex-pack \
  --adapter codex \
  --target /path/to/codex-project \
  --include-emotion-engine-codex \
  --emotion-engine-codex-source /path/to/emotion-engine/integrations/codex/emotion-engine-codex
```

Refresh an already installed sidecar without resetting runtime state:

```bash
packwright refresh-emotion-engine-codex \
  --target-dir /path/to/codex-project \
  --emotion-engine-codex-source /path/to/emotion-engine/integrations/codex/emotion-engine-codex
```

Inspect and repair installed target drift:

```bash
packwright doctor \
  /path/to/codex-project \
  --emotion-engine-codex-source /path/to/emotion-engine/integrations/codex/emotion-engine-codex \
  --fix
```

Without `--fix`, doctor reports detected drift and exits non-zero. With `--fix`, it applies deterministic repairs while preserving `.emotion-engine/codex-state.json`. Doctor also checks installed target layout, manifest artifacts, workspace shared handoff/session-brief directories, and Cursor target-local handoff helpers; it only repairs deterministic scaffold/helper drift. Compatibility-only memory files such as `memory/pinned.md` are reported as warnings, not failures.

## Current Scope

Packwright currently focuses on local agent pack compilation for AI coding tools.

Included:

- canonical character intake
- mechanism spec generation
- Codex pack projection
- Claude Code pack projection
- Cursor project rules projection
- memory and workspace scaffold
- save-context skill
- manifest generation
- validation and scoring
- local install
- installed-target migration across supported adapters
- reviewable handoff export for cross-agent/runtime collaboration
- Codex Emotion Engine sidecar install, refresh, and doctor

Not included yet:

- hosted runtime
- UI
- cloud sync
- automatic background agents
- full RAG or vector knowledge base
- team registry

## Roadmap

- v0.1 release/demo hygiene
- product-facing lint checks
- agent pack diff
- workstream promotion workflow
- lightweight knowledge layer
- team registry

## Development

Install locally in editable mode:

```bash
python3 -m pip install -e .
```

Run tests:

```bash
python3 -m unittest discover -s tests
```
