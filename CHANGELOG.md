# Changelog

All notable changes are documented here. Packwright follows Semantic Versioning.

## Unreleased

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

[0.1.2]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.1.2
[0.1.1]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.1.1
[0.1.0]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.1.0
[0.1.0rc1]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.1.0rc1
