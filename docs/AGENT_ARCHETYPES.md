# Agent Archetypes And Memory Contract

Packwright treats a character as an agent instance generated from an archetype. The archetype sets the default memory shape and promotion rules; the instance supplies the name, role, voice, work focus, and local state.

```text
archetype
  -> character instance
    -> platform entry file
    -> memory contract
    -> workspace contract
    -> optional runtime state
```

## Core Layers

- `AGENTS.md` or `CLAUDE.md`: stable identity, voice, and default behavior.
- `memory/index.md`: default router and owner map.
- `memory/profile.md`: explicit stable profile facts that may matter across workstreams.
- `memory/workstreams.md`: router for long-running domains.
- `memory/workstreams/<slug>.md`: optional detailed domain file for mature workstreams.
- `memory/projects/<slug>.md`: project state, decisions, and open loops.
- `memory/source-map.md`: source, account, file, and artifact lookup pointers.
- `memory/todos.md`: action queue and commitments.
- `memory/collaboration.md`: collaboration calibration and repair notes.
- `workspace/`: domain-first generated drafts, durable artifacts, and archives.
- `.emotion-engine/codex-state.json`: optional dynamic emotion state, separate from durable memory.

## Archetypes

### Productivity

For task execution, project work, planning, and operational follow-through.

Default bias:

- profile stores stable user, team, or operating preferences.
- workstreams represent durable areas of responsibility.
- projects own concrete deliverables and current state.

### Learning Coach

For teaching, coaching, deliberate practice, and feedback loops.

Default bias:

- profile stores learner level, goals, constraints, preferences, and recurring errors.
- workstreams represent curriculum, practice, feedback, assessment, and habit tracks.
- projects represent courses, exams, training blocks, or learning deliverables.

### Companion

For companion-style continuity where relationship tone matters.

Default bias:

- profile stores only user-approved stable facts and preferences.
- transient emotion, inferred psychology, and relationship dynamics do not belong in profile.
- dynamic state belongs in the Emotion Engine sidecar when enabled.
- workstreams represent shared routines, creative threads, or boundary-safe support contexts.

### Creator

For media, writing, publishing, editorial systems, and audience development.

Default bias:

- profile stores creator identity, public positioning, style preferences, and platform constraints.
- workstreams represent content pillars, publishing operations, asset pipelines, and campaign tracks.
- workspace stores drafts, scripts, title sets, thumbnail briefs, and final publishing artifacts under the creator domain.

### Operations

For recurring maintenance, monitoring, community, and administrative workflows.

Default bias:

- profile stores stakeholders, constraints, service expectations, and escalation preferences.
- workstreams represent recurring operational domains with checklists and cadence.
- source-map indexes dashboards, accounts, documents, and monitoring sources.

## Workstream Promotion

A workstream should stay inside the parent agent while it only needs domain routing and compact state. Promote it to an independent agent when one or more of these become stable:

- different default personality or voice
- distinct toolchain or source map
- independent cadence, checks, or maintenance
- multiple projects with a stable domain router
- enough context that loading it would pollute unrelated work
- separate acceptance criteria or ownership boundary

Promotion path:

```text
memory/workstreams.md entry
  -> memory/workstreams/<slug>.md detail file
  -> generated independent agent
  -> parent agent keeps routing and acceptance unless ownership moves
```

## Workspace Rules

Memory files are not a content warehouse. Workspace layout is domain-first and lifecycle-second so workstream artifacts are easy to migrate with the domain later.

- Use `workspace/<domain>/drafts/` for temporary drafts and explorations.
- Use `workspace/<domain>/artifacts/` for final or reusable deliverables.
- Use `workspace/<domain>/archive/` for old outputs kept for reference.
- Use `workspace/shared/` only for cross-domain outputs.
- Use `workspace/shared/artifacts/handoffs/` for real cross-agent or cross-runtime handoffs.
- Use `workspace/shared/artifacts/session-briefs/` for same-agent next-session preparation files.
- Use `workspace/_template/` as the skeleton for a new workstream workspace.
- Index important outputs in `memory/source-map.md`.
- Move durable project state into `memory/projects/<slug>.md`, not workspace files.
