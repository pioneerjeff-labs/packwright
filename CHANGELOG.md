# Changelog

All notable changes are documented here. Packwright follows Semantic Versioning.

## [0.1.0] - 2026-07-14

### Added

- Stable public release for Codex, Claude Code, and Cursor pack generation, installation, migration, diagnosis, and scoring.
- Artifact-lock verification and deterministic repair for Packwright-managed projections.

### Changed

- `build` now refuses to overwrite existing pack artifacts unless `--force` is explicit.
- `install --force` preserves portable user state under `memory/`, `workspace/`, `knowledge/`, and `sources/`.
- Emotion Engine sidecar installation is explicit instead of being implied by the default light mode.
- Distributable metadata no longer records build-machine absolute source paths.

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

[0.1.0]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.1.0
[0.1.0rc1]: https://github.com/pioneerjeff-labs/packwright/releases/tag/v0.1.0rc1
