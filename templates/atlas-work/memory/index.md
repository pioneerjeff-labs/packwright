# Memory Index

This is the default memory router. Read this first when prior context may matter.

## Core Rule

- Do not treat this file as the source of project truth. It points to the owner file for each kind of memory.

## Active Projects

- No active projects have been recorded yet.

## Memory Owners

- Stable identity, voice, and default work rules -> `AGENTS.md` or equivalent platform entry file
- Stable user, subject, learner, creator, or relationship facts -> `memory/profile.md`
- Long-running domains and workstream routing -> `memory/workstreams.md`
- Current project state and decisions -> `memory/projects/<slug>.md`
- Session/thread recall and lookup hints -> `memory/session-index.md`
- Source lookup and verification paths -> `memory/source-map.md`
- Reviewed reusable knowledge -> `knowledge/index.md`
- Knowledge source manifests -> `sources/*/manifest.json`
- Drafts, durable artifacts, and archived outputs -> `workspace/`
- Action queue -> `memory/todos.md`
- Collaboration calibration notes -> `memory/collaboration.md`
- Dynamic emotion state and compact emotion history -> `.emotion-engine/codex-state.json` when enabled

## Compatibility Files

- `memory/pinned.md` is compatibility-only in the MVP; avoid using it as a normal memory layer.
- `memory/recent-activity.md` is an old name for session recall; prefer `memory/session-index.md`.
- `memory/knowledge_map.md` is an old name for source lookup; prefer `memory/source-map.md`.
- `memory/relationship-state.md` is an old name for collaboration calibration; prefer `memory/collaboration.md`.
