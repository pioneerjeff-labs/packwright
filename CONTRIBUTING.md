# Contributing

Packwright welcomes focused bug fixes, tests, documentation corrections, and adapter improvements. The project values receipts over broad claims: show the behavior, the command, and the verification.

## Development setup

```bash
git clone https://github.com/pioneerjeff-labs/packwright.git
cd packwright
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Verification

Run the quick gate while iterating:

```bash
scripts/release-gate.sh --quick
```

Before opening a pull request, run the complete gate:

```bash
scripts/release-gate.sh
```

Every user-visible behavior change needs a test or a concise explanation of why automated coverage is not practical.

## Adapter work

New adapters land when they pass the checker. Open an [adapter request](https://github.com/pioneerjeff-labs/packwright/issues/new?template=adapter_request.yml) first and include:

- the runtime's official instructions, rules, or skills documentation;
- the native file locations and formats;
- whether you can test a real local installation;
- known features that cannot be projected.

An adapter is not complete when it renders files. It must build, install, migrate in both directions where applicable, expose exclusions honestly, and pass the checker.

## Public-data rule

Use synthetic fixtures. Never include real agent memory, credentials, private paths, private launch material, or generated build artifacts. Migration changes must preserve the dry-run-before-write contract and report every generated, carried, rewritten, and excluded path.

## Documentation voice

State what Packwright does and what was tested. Avoid claims such as “seamless,” “magical,” or support for runtimes that do not have a passing adapter. A `100.0` structure score is not a runtime guarantee.
