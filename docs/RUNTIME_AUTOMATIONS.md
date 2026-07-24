# Local Runtime Automations Design Contract

Status: included in Packwright 0.1.2 through the runtime-neutral mechanism 0.8
contract.

## Outcome

Packwright stores runtime-neutral automation intent in the editable canonical
source, projects that intent into each supported local runtime, and reports any
missing destination capability without pretending that behavior was preserved.

The first slice is intentionally local-only. Cloud agents, remote runners, and
hosted task systems require a separate capability and trust model.

## First-slice scope

The first slice supports two lifecycle events:

- `session_start`
- `user_prompt`

It supports one effect, adding bounded dynamic context, through three
declarative producers:

- `memory_view`
- `freshness_facts`
- `relocation_guard`

The first slice does not support `pre_compact`, `session_end`, scheduled tasks,
or arbitrary `custom_command` definitions. Rebecca's production hook lineage
uses `SessionStart` and `UserPromptSubmit`; it does not use `SessionEnd`.
Unsupported future events must not be mapped to a differently timed event. In
particular, a session-end intent must never be projected to a turn-level stop
event.

Prompt keyword matching is not an automation trigger. Runtime lifecycle events
trigger automation; declarative producers decide which local facts are emitted.

## Canonical 0.8 shape

Each entry under `automations` declares one local lifecycle intent:

```yaml
automations:
  - id: user-prompt-current-todos
    scope: local
    event: user_prompt
    effect: add_context
    producer:
      kind: memory_view
      source: memory/todos.md
      select:
        max_bytes: 4096
    budget_bytes: 4096
```

`memory_view` supports bounded UTF-8 output plus optional Markdown `section`,
`until_section`, and `bullets_latest` selectors. `freshness_facts` reads only
`system_date` or `system_datetime`. `relocation_guard` compares the live target
with `.packwright/baseline-path`. It does not infer intent from prompt words.

Generated runners require `python3`, which is already Packwright's installation
runtime. They read only project-local files and perform no network or cloud work.

## Ownership layers

Packwright keeps four different kinds of files separate:

1. Editable canonical source
   - `mechanism.yaml` declares runtime-neutral intent.
   - Files referenced by the mechanism remain alongside that source.
2. Installed Packwright control plane
   - `.packwright/spec.json` is the resolved installed canonical snapshot.
   - `.packwright/source/**` is the embedded source needed for offline rebuilds.
   - `.packwright/lock.json` records managed projection hashes.
   - Packwright receipts record what was planned and applied.
3. Runtime-native projection
   - Claude Code uses project-local `.claude/**` files.
   - Codex uses project-local `.codex/**` files.
   - Cursor uses project-local `.cursor/**` files.
   - Pi Core emits no executable automation projection; separately authored
     Pi extensions live under project-local `.pi/extensions/**`.
4. Portable instance state
   - `memory/`, `workspace/`, `knowledge/`, `sources/`, and unmanaged root
     `skills/` contain user or instance state under the existing portability
     rules.

Deleting `.packwright/` detaches the instance from reproducible Packwright
management. The runtime may still execute its generated files, but Packwright
can no longer reliably diagnose, migrate, reconcile, or rebuild it. Detachment
is not an implicit cleanup operation.

Runtime files are generated artifacts, not a second canonical source. A direct
runtime hook edit can be inventoried as a proposal, but another runtime must not
be produced by reverse-compiling that hook.

## Local capability contract

The adapter registry owns event and effect support. The first-slice contract is:

| Adapter | `session_start` dynamic context | `user_prompt` dynamic context | Activation note |
|---|---:|---:|---|
| Claude Code | native | native | project hook remains subject to runtime review |
| Codex | native | native | project hook may require project trust and hook review |
| Cursor | native | unavailable | prompt hook can allow or block but cannot add model context |
| Pi | extension required | extension required | Packwright does not generate executable project extensions |

The projector returns one result for every canonical automation:

- `projected`
- `projected_pending_user_review`
- `unavailable_missing_event`
- `unavailable_missing_effect`
- `unavailable_requires_extension`
- `unmanaged_requires_canonicalization`

An unavailable result is not a static-rule fallback. The canonical intent is
preserved and the receipt explains which behavior is absent.

## Command boundaries

### `handoff`

Handoff carries work continuity only: current items, progress, decisions,
todos, evidence, recommended reads, and next steps. It must not install, update,
or transfer hooks, skills, schemas, settings, or other mechanism definitions.

If a handoff notices mechanism work in changed paths, it may point to the
canonical change or reconcile flow, but it must not apply that change.

### `migrate`

Migration creates a destination-runtime instance from the same installed
canonical intent and carries portable instance state. It calls the destination
projector but does not silently upgrade the canonical mechanism.

If unmanaged local automation is found in the source instance, migration:

1. inventories the configuration and referenced assets;
2. labels them `unmanaged_requires_canonicalization` rather than translating
   them;
3. lists the resulting destination behavior gap in the dry-run;
4. requires explicit acceptance before apply; and
5. records accepted degradations in the applied receipt.

Interactive apply must name the degradations in its confirmation prompt.
Non-interactive apply with degradations requires both the normal write
confirmation and an explicit degradation acceptance flag. A generic `--yes`
must not silently mean that missing behavior was accepted.

### `reconcile`

Reconcile upgrades an existing instance from installed canonical mechanism A to
desired canonical mechanism B. It reads the canonical definition and invokes
the current instance's adapter projector; it does not translate another
runtime's generated files.

Reconcile compares the installed spec hash and managed lock against the desired
canonical source. Its plan is generated on demand. There is no manually updated
"reconcile file."

The applied receipt records:

- from/to spec hashes;
- optional from/to Git commits as provenance only;
- managed projection updates;
- safe structural memory migrations;
- preserved instance state;
- manual merges; and
- pending runtime activation or trust steps.

### `doctor --fix`

Doctor repairs drift against the currently installed spec. It does not select a
new upstream version and does not perform a mechanism upgrade.

### `adopt`

Adopt inventories an unmanaged local instance. Existing runtime hooks become
automation candidates. A later review may produce a canonical change draft,
but adopt does not directly modify the canonical spec or another runtime.

## Memory boundary

Memory is split by semantic ownership, not just path:

| Change | Owner flow |
|---|---|
| Current todo, project status, recent activity, or field value | handoff or migrate state carry |
| New memory file, schema, template, routing rule, or required field | canonical mechanism and reconcile |

Reconcile must preserve existing memory content. It may create a missing
scaffold or perform a deterministic, idempotent structural migration. If safe
merging cannot be proven, it emits a manual merge instead of overwriting state.

For example, requiring `last_briefing_date` is a mechanism change; its current
date value is instance state.

## Receipt semantics

`ready` means the destination can be written without unresolved structural
conflicts. It does not mean every source-runtime behavior is portable.

A migration plan separately records:

- `generated`
- `carried`
- `rewritten`
- `degraded`
- `excluded`
- `required_confirmations`

A path-backed degraded source item records its source hash, source adapter,
destination adapter, known lifecycle events, reason code, and required user
decision; apply rechecks that hash. A canonical destination capability gap
instead records its automation id, event, status, reason, and required
decision. The applied receipt records `accepted_degradations`; it never claims
that absent behavior exists or works in the destination.

## Source history and upgrade discovery

Git may version the editable canonical source and provide optional commit
provenance. Git commits are not the cross-instance diff protocol.

An installed instance may record an upstream source path, spec hash, and Git
commit. When that source is reachable, `status`, `doctor`, or
`reconcile --dry-run` may report `reconcile_available` when the desired spec
hash differs. When it is unavailable, the result is `upstream_unavailable`, not
an inferred upgrade.

No command auto-applies a reconcile merely because a newer source is visible.

## Implementation order

1. Preserve existing user data during adopt and isolate multi-source review
   artifacts.
2. Add local unmanaged-automation discovery and explicit migration degradation
   acceptance without changing the canonical spec.
3. Add the minimal canonical automation model and one shared projector
   interface.
4. Implement Claude Code, Codex, and Cursor local projections, including honest
   Cursor degradation.
5. Add reconcile dry-run/apply and receipts.
6. Add reviewed adopt-to-canonical drafts.
7. Run the Rebecca acceptance matrix before deciding the release version.

All seven items are implemented in the current worktree. The acceptance matrix
executes generated runners for the three hook-capable adapters, verifies honest
Cursor degradation, preserves user hook entries during install/reconcile, and
exercises the evidence-only adopt draft flow. Packwright 0.3 adds Pi Core as a
fourth layout while leaving lifecycle automation as an explicit
extension-required gap.

Implementation batches and public releases are separate decisions. A small
automation increment can wait for a later release; a confirmed data-loss fix is
evaluated independently as a possible hotfix.
