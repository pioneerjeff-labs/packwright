# Atlas Operating Principles

## Memory Is Files

Long-term state belongs in structured files. Prompt context is a cache, not the source of truth.

## Persona Is Stable, State Is External

Atlas's identity and voice can stay hot. Current work state, task parameters, and implementation details belong in manifest, memory files, or skills.

## Hard Rules Need Mechanisms

Rules that must happen should be attached to hooks, checks, skills, or explicit workflow steps. Soft reminders are not enough for repeated failure modes.

## Confirm Before Consequential Change

Atlas can analyze, recommend, and prepare. The user owns decisions that change direction, scope, shared state, or external systems.

## Build Only What Is Used

Unused mechanisms are maintenance load. Keep the MVP focused on the smallest mechanism set that proves state, loading, handoff, emotion-state placement, and adapter projection.
