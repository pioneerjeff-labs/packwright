# Contributing

Packwright accepts focused bug fixes, tests, documentation corrections, and adapter improvements.

1. Create a branch from `main`.
2. Install development tools with `python -m pip install -e '.[dev]'`.
3. Run `scripts/release-gate.sh --quick` while iterating.
4. Run `scripts/release-gate.sh` before opening a pull request.
5. Explain user-visible behavior and add or update tests.

Do not include real agent memory, credentials, private paths, or generated build artifacts. Migration changes must preserve the dry-run-before-write contract and report every generated, carried, rewritten, and excluded path.
