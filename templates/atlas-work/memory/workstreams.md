# Workstreams

This file is the domain router for long-running areas of responsibility.

Use it when a request belongs to an ongoing domain, needs domain-specific context, or may later be promoted into a separate agent.

## Archetype

- Type: Productivity
- Scope: Long-running domains of responsibility that may contain multiple projects.

## Routing Rules

- Keep router entries compact; create `memory/workstreams/<slug>.md` when a domain needs detailed state.
- A workstream can contain many projects; a project file should still own project-specific decisions and current state.
- Generated drafts and final outputs belong in `workspace/<domain>/`, with important pointers indexed in `memory/source-map.md`.
- Do not load every workstream by default; load the router first, then the relevant detail file.

## Promotion To Agent

- Promote a workstream only when it needs a distinct persona, toolchain, cadence, memory contract, or acceptance criteria.
- Keep the parent agent responsible for routing and final acceptance unless ownership is explicitly moved.
- Use `memory/workstreams/_template.md` when creating a detail file for a mature domain.

## Current

### 1. Business judgment and decisions

- Purpose: Prepare business decisions by organizing context, options, risks, and tradeoffs.
- Detail file: create one under `memory/workstreams/` when this domain needs denser state.
- Promotion status: not promoted.

### 2. Work organization and follow-through

- Purpose: Keep work items, priorities, dependencies, and follow-ups clear.
- Detail file: create one under `memory/workstreams/` when this domain needs denser state.
- Promotion status: not promoted.

### 3. Durable context and knowledge

- Purpose: Preserve working context and maintain useful personal or team knowledge assets.
- Detail file: create one under `memory/workstreams/` when this domain needs denser state.
- Promotion status: not promoted.
