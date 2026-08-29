# Emotion Engine runtime

Packwright can install Emotion Engine v2.0.0-rc.4 as an optional, project-local MCP runtime for Codex, Claude Code, or Cursor. The engine and live state are adapter-neutral; only native guidance, project configuration, and verified lifecycle bindings vary by runtime.

Pi Core is not in this list because Pi has no built-in MCP surface. Packwright
rejects `--include-emotion-engine` for Pi and may carry existing state only as
an inert recovery snapshot; see [Pi Core adapter](PI.md).

New character sources use `emotion/state-schema.yaml` as the state-shape
contract. The installed manifest declares the only live runtime state path,
inside `.emotion-engine/generations/<writer-generation>/state.json`.
They do not generate or session-start inject the former
`memory/emotion-state.json.example` placeholder. Existing mechanisms that
still declare that placeholder remain valid and projectable for compatibility.

## What is installed

Every enabled target receives:

- `.packwright/runtime/emotion-engine/generations/2.0.0-rc.4-edd9604/` — the pinned helper, fixed-state shell gateway, MCP server, cohort-aware launcher, schema, template, registration helper, projection receipt, and license;
- `.emotion-engine/generations/2.0.0-rc.4-edd9604/state.json` — the rc.4 generation's live state;
- `scripts/emotion_engine.sh` — shell access through the target-locked fixed-state gateway;
- `scripts/emotion_engine_mcp.sh` — the project-relative MCP launcher.
- `scripts/emotion_engine_lifecycle.py` — a capability-gated lifecycle bridge that never edits state directly.

The thin native projections are:

| Adapter | Guidance | MCP configuration |
|---|---|---|
| Codex | `.agents/skills/emotion-engine/SKILL.md` | `.codex/config.toml` |
| Claude Code | `.claude/skills/emotion-engine/SKILL.md` | `.mcp.json` |
| Cursor | `.cursor/rules/emotion-engine.mdc` | `.cursor/mcp.json` |

Packwright merges only the `emotion-engine` MCP entry and preserves unrelated servers. A client may still request approval when it first loads a project MCP server. Install or refresh reports `configured_client_restart_required`; restart the client so the launcher can complete a live version/nonce handshake.

Codex also receives one managed `.codex/hooks.json` `SessionStart` entry. It
forwards the host-native session id only when the installed state declares
`session_idempotency/v1`. Repeated startup, resume, clear, or compact events
for the same native id are idempotent. Because this hook surface has no
reliable close event, the bridge closes the old session only after a different
native session id appears. Claude Code and Cursor receive no synthetic
lifecycle events until an equivalent native identity contract is verified.

The live state is separate from durable `memory/` files. Do not copy PAD/trust values into `memory/collaboration.md`, `memory/relationship-state.md`, or other human-maintained memory.

## Install explicitly

The runtime source is not bundled into an ordinary adapter pack. Pass the Emotion Engine v2.0.0-rc.4 repository root or set `PACKWRIGHT_EMOTION_ENGINE_DIR`:

```bash
packwright install pack/nova-claude \
  --target project/nova-claude \
  --include-emotion-engine \
  --emotion-engine-source /path/to/emotion-engine \
  --emotion-engine-mode light
```

The pack manifest supplies the adapter. `--adapter` remains an optional assertion.

Available modes are:

| Mode | Behavior |
|---|---|
| `light` | Use state selectively when continuity, emotional interaction, repair, or milestone settlement matters. |
| `always` | Track each meaningful turn while keeping summaries compact. |
| `paused` | Preserve installed state without recording or modulating turns. |

`light` is the default recommendation.

## State safety

Packwright reads the current generation path plus the legacy paths:

- `.emotion-engine/generations/2.0.0-rc.4-edd9604/state.json`
- `.emotion-engine/state.json`
- `.emotion-engine/codex-state.json`
- `.emotion-engine/emotion-state.json`

The current generation is canonical whenever it exists. Otherwise Packwright first carries the state path explicitly declared by the installed manifest, then considers the fixed legacy paths. One selected older state is copied byte-for-byte into the current generation and retained at its old path. An old MCP process therefore keeps writing only its previous generation and cannot downgrade the canonical packet. If canonical and legacy bytes later diverge, Packwright refuses migration instead of silently discarding the legacy writer's newer data; only a persistent migration-lineage record can prove that the difference is expected.

Packwright does not construct or patch Emotion Engine state JSON. Fresh v3
state is initialized and identity-bound by the pinned helper. Existing v3
state is preserved byte-for-byte during projection refresh. Existing v2 state
is also preserved byte-for-byte, but rc.4 keeps it read-only and Packwright
reports `migration_required`; installing new runtime files does not mark that
state active.

Normal shell, lifecycle, and MCP writers run in explicit managed-runtime mode.
They require the canonical primary state to exist and reject structural
integrity errors before the Emotion Engine mutator or backup path runs.
Diagnostic audit and repair-plan reads remain available on an existing damaged
packet, and semantic warnings alone do not block writes. Initialization,
identity binding, migration, capability upgrade, and reset remain exclusive to
Packwright's locked, journaled owner transaction.

`doctor` warns whenever a legacy state remains. After reviewing the canonical
copy, pass `--retire-legacy-state` to an Emotion Engine install or refresh to
verify that each legacy file either has identical bytes or matches the source
hash in persistent migration lineage, then rename it as a `.bak` backup. The
lineage reference remains in canonical v3 state across normal runtime writes,
so retirement does not depend on the canonical packet retaining its original
post-migration digest.
Packwright never retires legacy state by default.

Review the derived character and relationship identity before applying the
separate state migration:

```bash
packwright migrate-emotion-state --target-dir project/nova-claude
packwright migrate-emotion-state --target-dir project/nova-claude --yes
```

If the manifest slug is a placeholder, supply confirmed ids explicitly:

```bash
packwright migrate-emotion-state --target-dir project/nova-claude \
  --character-id nova --relationship-id nova:primary-user
```

The first command runs the engine migration or capability upgrade in dry-run mode and does not change
the state. `--yes` creates a timestamped v2 or v3 backup under
`.emotion-engine/backups/`, delegates the rewrite to Emotion Engine, then
runs both `activation_check` and `audit_state` before committing the new state.
The manifest then remains at `client_restart_required` until a fresh rc.4 MCP
initialize performs the same full verification and records the live client
cohort. A persistent transaction journal restores state, manifest, artifact
lock, and migration lineage after any exception and recovers an interrupted
transaction on the next migration run. While that journal is `in_progress`,
install, refresh, shell, lifecycle, and MCP writers all fail closed. The
engine's own `.bak` remains as a second recovery copy.

## Verify and refresh

```bash
packwright doctor project/nova-claude
packwright refresh-emotion-engine \
  --target-dir project/nova-claude \
  --emotion-engine-source /path/to/emotion-engine
```

`doctor` can diagnose a moved target without the upstream source by using the target's manifest, artifact lock, completed writer-cohort projection receipt, and MCP initialize receipt. It checks the helper, MCP server, launcher, wrappers, lifecycle bridge, schema, required capabilities, bound identity, mode, activation check, state audit, and managed configuration as one versioned cohort. Pass `--emotion-engine-source` with `--fix` when managed runtime files must be refreshed. Refresh rewrites managed runtime/guidance files and the managed MCP/lifecycle entries, but preserves live state and unrelated local files. A new projection nonce deliberately leaves doctor at `emotion_engine_mcp_restart_required` until the client restarts.

Refresh, migration, lifecycle events, shell gateway commands, and MCP requests share one target lock.
The pending marker and an `in_progress` migration journal are runtime fuses for
shell, lifecycle, MCP, install, and refresh writers, not only diagnostics.
Refresh snapshots every file it can change and restores the previous cohort on
exceptions; successful refresh removes pending only after the manifest and
receipt agree. Every managed state, backup, journal, and generation path is
resolved without symlink traversal.

Managed MCP starts with `--locked-state --managed-runtime`: tool calls cannot override the generation state path, and identity/migration tools are not exposed. The launcher rejects non-notification requests without an id, validates params and exact child response ids, and holds the target lock until the matching child response is received. A successful live initialize runs `activation_check` plus `audit_state`, verifies the state hash did not change, and atomically updates its receipt, manifest activation, MCP status, and artifact lock.
Shell mode changes and MCP activation both compare the current manifest digest with the pre-existing artifact-lock baseline before updating it; drift is rejected rather than absorbed into a new lock.
When refresh changes generation, Packwright removes every older generation's projection receipt before releasing the shared target lock. A previously running managed launcher therefore fails its next cohort check even though its old files remain available for recovery.

The manifest records four separate activation layers:

- `installed`: the pinned runtime cohort is present;
- `configured`: project-local configuration is present;
- `active`: a bound v3 state is enabled and ready;
- `verified`: local activation and state audit checks passed.

Live client MCP approval and Codex context delivery remain separate readiness
checks; local verification does not claim that the client approved or loaded
the runtime.

## Migration receipts

Migration always reports the state separately:

- `active`: the state was carried byte-for-byte and the destination received its native runtime/MCP wiring;
- `migration_required`: a carried v2 state remains read-only until the explicit migration command succeeds;
- `snapshot_inert`: the state was carried for recovery, but no Emotion Engine source was supplied, so no runtime was activated;
- `not_carried`: no state was found or `--no-emotion-state` was used.

Supply `--emotion-engine-source` when migrating to any of the three
MCP-capable adapters to keep the state active. The deprecated Codex-specific
flags and `refresh-emotion-engine-codex` alias remain accepted for one
compatibility cycle.
