# Save Context

Use this skill at milestone handoff, session close, or when the user asks Atlas to preserve state.

## Procedure

1. Identify the current objective, scope, decisions, changed files, verification, and open questions.
2. Update the canonical owner file instead of copying the same fact across layers.
3. Update `memory/projects/<slug>.md` for project state, decisions, open loops, and project-specific sources.
4. Update `memory/session-index.md` for session/thread lookup entries, not project state summaries.
5. Update `memory/source-map.md` for source-of-truth paths, verification routes, and lookup pointers.
6. Update `memory/todos.md` for action queues and commitments.
7. Update `memory/collaboration.md` only for stable collaboration calibrations.
8. Update `memory/index.md` only when active projects, memory owners, or routing rules change.
9. Report what was saved and what remains unsaved.

## Memory Tracks

- index: Default memory router; points to active projects and canonical memory owners.
- profile: Stable user, subject, learner, creator, or relationship facts that matter across workstreams.
- workstreams: Domain router for long-running work areas; route to workstream detail files when useful.
- workstream_details: Optional detailed domain files for mature workstreams and future agent promotion.
- projects: Source of truth for project state, decisions, open loops, and project-specific sources.
- session_index: Lookup index for prior sessions, thread recall, and earlier work references.
- source_map: Source registry for lookup and verification paths; not a knowledge base.
- todos: Action queues and commitments.
- collaboration: Learned collaboration calibrations and repair notes.
- pinned: Compatibility-only in the MVP; avoid using it as a normal memory layer.
- light: Compatibility alias for memory/session-index.md.
- heavy: Persist context into the canonical owner files.
- relationship: Compatibility alias for memory/collaboration.md.
- workspace: Domain-first draft, artifact, and archive storage; important outputs are indexed in memory/source-map.md.

## Write Rules

- Do not write cloud state in the current local projection.
- Do not put current status into `CLAUDE.md` or `AGENTS.md`.
- Prefer one compact session-index lookup entry over copying long context.
- Do not store live Emotion Engine runtime JSON in durable memory files.
