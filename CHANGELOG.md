# Changelog

All notable changes are documented here. Packwright follows Semantic Versioning.

## Unreleased

## [0.3.4] - 2026-08-29

### Security and integrity

- Route managed shell writes through a fixed-state gateway that shares the target lock with refresh, migration, lifecycle, and MCP operations; identity binding, v2 migration, v3 capability upgrade, initialization, and reset cannot bypass Packwright transactions.
- Launch MCP in locked managed-runtime mode, reject state overrides and id-less write RPCs, validate exact child response ids, and hold the target lock through the matching response.
- Require a full non-mutating activation check and state audit before a live MCP handshake can converge the activation manifest; compare the previous artifact-lock digest before any manifest update so drift cannot be washed into a new baseline.
- Make an incomplete migration journal a global writer fuse across install, refresh, shell, lifecycle, and MCP, with complete state/manifest/lock/lineage rollback on recovery.
- Reject symlink traversal for managed state, generation, journal, backup, and lineage paths.
- Detect divergent canonical and legacy state before migration, and preserve explicit migration lineage so a reviewed legacy packet can still retire after ordinary canonical writes.
- Pin Emotion Engine release commit `48e6f3fff767209e3d96721935e5476734e740a4`, whose managed runtime rejects malformed raw state before normalization, backup, audit probes, or mutation.
- Route generated shell, lifecycle, activation, and audit helper calls through the explicit managed-runtime contract; keep installer-owned initialization, migration, capability upgrade, identity binding, and reset inside the Packwright transaction.
- Extend the exact-source release smoke across missing primary state, malformed raw shape, hard-corrupt state, and semantic-warning-only state for shell, lifecycle, activation/audit, and MCP writers.

### Added

- Add `packwright migrate-emotion-state`, which previews the exact v2-to-v3
  identity binding or v3 capability upgrade without writes and, with `--yes`, creates a separate
  timestamped backup before delegating migration to Emotion Engine and running
  `activation_check` plus `audit_state`.
- Add a Codex-native lifecycle bridge gated by `session_idempotency/v1`.
  Replayed startup/resume/clear/compact events for one native session are
  idempotent; when no close event exists, a different native session triggers
  a deferred close before the new start.
- Add a target-wide Emotion Engine transaction lock, per-refresh projection
  nonce, live MCP initialize receipt, and persistent migration journal with
  automatic recovery of interrupted state/manifest/lock commits.

### Changed

- Pin optional Emotion Engine projections to `v2.0.0-rc.4` and record state
  schema, required capabilities, stable identity, writer cohort, and separate
  installed/configured/active/verified layers in the target manifest.
- Verify helper, MCP server, skill, wrappers, lifecycle bridge, projection
  receipt, state capabilities, bound identity, activation, audit, and managed
  configuration as one coherent cohort in `doctor`.
- Project the upstream Claude Code skill natively, synchronize
  `light`/`always`/`paused` through the engine helper, and require explicit
  migration ids when a manifest still uses a placeholder character slug.

### Fixed

- Stop Packwright from constructing or directly patching Emotion Engine state.
  Fresh state is initialized by the pinned helper; existing v2 and v3 state is
  preserved byte-for-byte during install and refresh.
- Keep v2 state read-only and report `migration_required` instead of treating a
  newly projected runtime as active. Projection uses a pending marker and a
  digest receipt so interrupted or mixed-version refreshes fail closed.
- Place runtime code and live state in a release-generation directory so an
  already-running v1/rc.3 MCP process can write only its legacy state path.
  Pending projections now fuse shell, lifecycle, and MCP writers; concurrent
  refreshes cannot publish mismatched files and receipts.

## [0.3.3] - 2026-08-02

### Changed

- Emit Codex `SessionStart` and `UserPromptSubmit` context through the explicit
  `hookSpecificOutput.additionalContext` JSON envelope. Codex handlers use a
  `100000` token threshold and reject projected per-event byte budgets above a
  conservative 96000-byte transport ceiling; Claude Code and Cursor output
  protocols are unchanged.
- Upgrade Codex activation stamps and receipts to v2. Verification now requires
  the exact emitted context to appear as a developer message in the Codex
  transcript, binds evidence to both the managed hook and runner digests, and
  rejects manual runner invocations or execution-only v1 evidence.

## [0.3.2] - 2026-07-31

### Added

- Add `packwright verify-activation TARGET --adapter codex`. Successful Codex
  hook runs write local event evidence, and verification persists a receipt
  bound to the current target, managed hook digest, and required lifecycle
  events.

### Changed

- Make canonical `operating/principles.md` the single source for entry-file
  Working Rules across Codex, Claude Code, Cursor, and Pi. The compiler strips
  the source H1, nests its remaining headings under Working Rules, and uses the
  previous adapter defaults only when the canonical file is empty.
- Report destination-only portable files that `migrate --force` will remove,
  require an explicit removal confirmation in the plan, and reject apply when
  those files change after planning.
- Bind installed Codex hook commands to the target's absolute runner path, pass
  budget-bounded additional context without Codex's secondary spill threshold,
  and require fresh activation evidence whenever the managed hook digest
  changes.
- Separate successful migrate/reconcile application from installed-tree
  checker attention. Applied receipts now expose `installed_score_passed`,
  reconcile also exposes `doctor_ok`, and CLI exit status follows operation
  integrity.

### Fixed

- Accept populated session-index files as user-ready live memory, matching the
  existing pinned, recent-activity, and todo behavior.
- Mark truncated `memory_view` context with its byte budget and canonical source
  path while keeping the complete producer payload within `budget_bytes`.
- Score reconcile receipts from the installed live tree instead of re-scoring
  the planned pack, so preserved portable-state failures cannot produce a false
  green installed score.
- Make reconcile dry-run report receipt writes, relocation-baseline changes,
  and full managed-config normalization; explicitly warn before re-anchoring a
  moved target.
- Report that `--no-emotion-state` will initialize fresh continuity with
  `trust_anchor=0.1` when the source has live state and the destination is
  empty.
- Describe declared Emotion Engine MCP configuration as unverified instead of
  incorrectly claiming that the manifest declares no environment bindings.

## [0.3.1] - 2026-07-26

### Fixed

- Treat unavailable destination automations as explicit migration capability
  gaps for Cursor as well as Pi. Non-interactive apply now requires
  `--accept-degraded` after review instead of silently dropping prompt-time
  behavior.
- Render pathless automation gaps as readable `automation:<id>` receipt items
  instead of crashing the human-readable migration report after planning or
  apply.
- Accept populated pinned, recent-activity, and todo memory files as user-ready
  state, while keeping placeholder detection and structural checks intact.
- Match runtime names at token boundaries so ordinary words such as `Pinpoint`
  and `Picture` do not create false Pi projection failures.
- Report Emotion Engine migrations to Pi honestly: portable state remains inert,
  and no Pi runtime projection is claimed.
- Cover legacy Emotion Engine backup and diverged-state retirement guards,
  applied receipts across all 12 directed migrations, dry-run provenance
  preservation, and the exact Pi skill, reference, and trust-reload guidance.

## [0.3.0] - 2026-07-24

### Added

- Add a Pi Core adapter that compiles `AGENTS.md`, project Agent
  Skills, Pi-scoped reference files, install/doctor support, and all 12
  directed migration plans across the four adapters.
- Record Pi project trust as an activation requirement, detect unmanaged
  `.pi/settings.json` and `.pi/extensions/**` automation resources, and require
  explicit acceptance when canonical lifecycle automation needs a separately
  reviewed Pi extension.
- Add a no-write `install --dry-run` plan with explicit add, overwrite,
  managed-config merge, stale-removal, portable-state, Emotion Engine, and
  required-`--force` reporting.
- Persist local install provenance under `.packwright/install-provenance.json`
  and expose source-pack, installed-spec, and installed-lock digests through
  `doctor`.
- Warn when canonical and legacy Emotion Engine state paths coexist, with an
  explicit `--retire-legacy-state` option that verifies identical content and
  renames legacy files as `.bak` backups.

### Fixed

- Make checker and doctor results distinguish managed structural integrity from
  operational readiness. A score of `100.0` no longer presents runtime
  activation, environment bindings, portable-state integrity, or workflow
  acceptance as verified; doctor also surfaces Pi trust, canonical automation
  gaps, and pending adoption-review items.
- Stop generating and session-start injecting the obsolete
  `memory/emotion-state.json.example` placeholder for new character sources,
  while continuing to validate and project legacy mechanisms that contain it.
- Make `python -m packwright.cli` execute the CLI instead of exiting silently
  with status 0.
- Make reconcile planning, application, scoring, entry guidance, sidecar
  preservation, and artifact locking use the same final desired projection so
  a successful apply converges to a zero-update re-plan.
- Preserve an existing live `.emotion-engine/state.json` during forced
  projection updates instead of rewriting it from a temporary reconcile pack.

## [0.2.0] - 2026-07-21

### Changed

- Save-context projections now use the canonical `skills[].path` source body
  across Codex, Claude Code, and Cursor; adapters own only destination paths
  and runtime front matter.
- Newly scaffolded save-context sources derive their Memory Tracks section from
  the same structured data used to generate `memory-policy.yaml`.
- The checker keeps the Procedure, session-index, canonical-owner, and
  runtime-neutrality invariants without requiring the scaffold-default Memory
  Tracks heading in customized sources.
- Save-context remains a mandatory, capability-agnostic artifact; validation
  rejects non-empty `capabilities` instead of allowing manifest and emitted-file
  state to disagree.

### Fixed

- Preserve customized save-context instructions in built, installed, migrated,
  and reconciled targets instead of replacing them with adapter-owned templates.
- Report the canonical source path and forbidden runtime token when a customized
  save-context body violates projection neutrality.

## [0.1.2] - 2026-07-20

### Added

- Runtime-neutral local automation contract 0.8 for bounded `session_start` and
  `user_prompt` context from memory views, freshness facts, and relocation guards.
- Native Claude Code, Codex, and Cursor project-hook projections with explicit
  Cursor `user_prompt` degradation instead of a false compatibility fallback.
- Dry-run-first `reconcile` with spec hashes, optional Git provenance, preserved
  instance state, managed hook-entry merging, activation notes, and receipts.
- Evidence-only adopt-to-canonical automation drafts; unmanaged hooks are never
  reverse-compiled into another runtime.

### Changed

- Managed hook JSON uses entry-level ownership and lock hashing, so user settings
  and unrelated hooks survive install, reconcile, and doctor checks.
- Legacy mechanism 0.5, 0.6, and 0.7 sources normalize to the 0.8 automation
  model without rewriting the editable source.

## [0.1.1] - 2026-07-17

### Added

- Runtime-neutral multi-skill projection with capability-based degradation.
- Generic Emotion Engine v1.0.0 installation, MCP configuration, state carry-forward, refresh, and diagnosis across Codex, Claude Code, and Cursor.
- Deterministic `en` and `zh-CN` compiler locales with English fallback and locale-aware checker contracts.
- Fresh-path `packwright new` orchestration that preserves editable source and built pack directories.
- Dry-run-first application of individually reviewed adoption decisions, with hash checks and manual-only memory merge and knowledge promotion.

### Changed

- Adapter metadata and artifact routing now come from a central registry, and install infers the adapter from the pack manifest.
- The character interviewer follows clearly established English or Chinese instead of embedding a Chinese-only relationship question.
- Installed handoff wrappers use the scoped `PACKWRIGHT_PYTHON` override so build-environment `PYTHON` values cannot leak into relocated targets.

## [0.1.0] - 2026-07-14

### Added

- Stable public release for Codex, Claude Code, and Cursor pack generation, installation, migration, diagnosis, and scoring.
- Artifact-lock verification and deterministic repair for Packwright-managed projections.
- First-class `draft-character` and `adopt` creation paths for custom and existing agents.

### Changed

- `build` now refuses to overwrite existing pack artifacts unless `--force` is explicit.
- `install --force` preserves portable user state under `memory/`, `workspace/`, `knowledge/`, and `sources/`.
- Emotion Engine sidecar installation is explicit instead of being implied by the default light mode.
- Distributable metadata no longer records build-machine absolute source paths.
- Public starter presets are now nameless `code`, `work`, and `companion` starting roles; users supply the character name with `--name` and can customize responsibilities, capabilities, voice, boundaries, and emotional feedback.

### Security

- Reject path traversal, absolute paths, source-root escapes, and destination symlink escapes across build, install, migration, doctor, and scoring paths.
- Keep `doctor --fix` limited to reproducible managed artifacts while excluding portable and live state.

## [0.1.0rc1] - 2026-07-11

### Added

- Six-command public CLI: `init`, `build`, `install`, `migrate`, `doctor`, and `score`.
- Native projections for Codex, Claude Code, and Cursor.
- Read-only migration plans with path-level generated, carried, rewritten, and excluded receipts.
- Self-contained installed-target metadata and pre/post-install scoring.
- Static zero-network audit, local release gate, packaging checks, and CI.

[0.3.4]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.3.4
[0.3.3]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.3.3
[0.3.2]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.3.2
[0.3.1]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.3.1
[0.3.0]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.3.0
[0.2.0]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.2.0
[0.1.2]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.1.2
[0.1.1]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.1.1
[0.1.0]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.1.0
[0.1.0rc1]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.1.0rc1
