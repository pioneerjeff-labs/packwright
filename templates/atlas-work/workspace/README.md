# Workspace

Use this directory for generated work products, not durable memory.

## Directories

- `workspace/<domain>/drafts/`: temporary drafts, explorations, and working versions.
- `workspace/<domain>/artifacts/`: final or reusable deliverables.
- `workspace/<domain>/archive/`: old outputs kept for reference.
- `workspace/shared/`: cross-domain outputs only.
- `workspace/shared/artifacts/handoffs/`: real cross-agent or cross-runtime handoff files.
- `workspace/shared/artifacts/session-briefs/`: same-agent next-session preparation files.
- `workspace/_template/`: copy when a new workstream needs workspace storage.

## Rules

- Keep memory files focused on state, decisions, and pointers.
- Index important workspace outputs in `memory/source-map.md`.
- Move durable project state into `memory/projects/<slug>.md`, not workspace files.
