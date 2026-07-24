# Pi Core adapter

Status: released in Packwright 0.3.0 and runtime-smoke-tested
against `@earendil-works/pi-coding-agent` 0.81.1.

## What Packwright emits

Build and install use the normal commands:

```bash
packwright build work/nova --adapter pi -o pack/nova-pi
packwright install pack/nova-pi --target project/nova-pi
packwright doctor project/nova-pi
packwright score project/nova-pi
```

The Pi pack uses Pi's native project discovery:

| Purpose | Path |
|---|---|
| Project context | `AGENTS.md` |
| Reusable procedures | `.agents/skills/<name>-<skill>/SKILL.md` |
| Packwright projection references | `.pi/<name>/references/**` |
| Portable instance state | `memory/`, `workspace/`, `knowledge/`, `sources/` |

Packwright does not generate `.pi/settings.json` or `.pi/extensions/**` for Pi
Core. A `100.0` Packwright score proves the emitted structure and contracts; its
`readiness` block keeps runtime activation explicitly separate from that score.

## Project trust

Pi loads `AGENTS.md` as project context, but project `.agents/skills` are
trust-gated. Open the installed target in Pi and approve the project before
depending on Packwright skills:

```bash
cd project/nova-pi
pi
# confirm the trust prompt, or use /trust in the session
```

For a one-run non-interactive check, Pi exposes `--approve`. Trust is stored in
Pi's user-scoped state, so `packwright doctor` cannot prove it. Doctor therefore
returns the non-fatal `pi_project_trust_unverified` warning.

## Lifecycle automation boundary

The canonical Packwright mechanism currently declares bounded
`session_start` and `user_prompt` context automation. Pi can implement lifecycle
behavior with TypeScript extensions, but Pi project extensions execute with the
user's full permissions and require trust.

Pi Core therefore does not synthesize executable extension code. Its manifest
records every canonical automation as `unavailable_requires_extension`. A
migration to Pi lists those records under `degraded`, and apply requires:

```bash
packwright migrate project/nova-codex \
  --to pi \
  --target project/nova-pi \
  --yes --accept-degraded
```

Use `--accept-degraded` only after reviewing the named behavior gaps. Existing
`.pi/settings.json` extension declarations and `.pi/extensions/**` files are
detected as unmanaged runtime automation during migration or adoption; they are
inventoried, never reverse-compiled into another adapter.

Generating a reviewed Pi extension is a separate follow-up surface, not part of
Pi Core.

## Emotion Engine boundary

Packwright's optional Emotion Engine runtime is an MCP sidecar. Pi does not
provide built-in MCP support, so `--include-emotion-engine` is rejected for the
Pi adapter. During migration, an existing state file may still be carried as an
inert recovery snapshot when no Emotion Engine source is supplied.

Packwright does not claim that the snapshot is active in Pi.

## Validation performed

The adapter test matrix covers:

- build and checker score;
- install and doctor;
- explicit trust reporting;
- rejection of the MCP-based Emotion Engine runtime;
- Codex to Pi migration with required degradation acceptance;
- Pi to Codex state-preserving migration;
- all 12 directed migration plans across the four adapters; and
- unmanaged Pi settings and extension discovery.

The runtime smoke test installed Pi 0.81.1 in an isolated temporary prefix and
used Pi's own `DefaultResourceLoader`. With project trust enabled, Pi discovered
the generated `AGENTS.md` and save-context skill with no diagnostics. With
project trust disabled, it still discovered `AGENTS.md` but correctly omitted
the project skill.

Pi 0.81.1 declares Node.js `>=22.19.0`; use a matching Node.js runtime for
production verification.
