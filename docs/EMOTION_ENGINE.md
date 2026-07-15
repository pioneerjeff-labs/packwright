# Emotion Engine sidecar

Packwright keeps emotional continuity optional and adapter-specific. Every generated character can describe emotional style and relationship continuity in its editable source, but live PAD/trust state is installed only when a Codex target explicitly includes the Emotion Engine sidecar.

## What is installed

An enabled Codex sidecar adds:

- `.agents/skills/emotion-engine-codex/` for the runtime procedure and local helper scripts;
- `.emotion-engine/codex-state.json` for project-local live state;
- `scripts/codex_emotion.sh` as the project-local wrapper.

The live state is separate from durable `memory/` files. Do not copy PAD/trust values into `memory/relationship-state.md` or other human-maintained memory.

## Install explicitly

The sidecar source is not bundled into a normal Packwright adapter pack. Provide its directory directly or set `PACKWRIGHT_EMOTION_ENGINE_CODEX_DIR`:

```bash
packwright install pack/nova-codex \
  --adapter codex \
  --target project/nova-codex \
  --include-emotion-engine-codex \
  --emotion-engine-codex-source /path/to/emotion-engine-codex \
  --emotion-engine-mode light
```

Available modes are:

| Mode | Behavior |
|---|---|
| `light` | Use state selectively when continuity, emotional interaction, repair, or milestone settlement matters. |
| `always` | Track each meaningful turn while keeping summaries compact. |
| `paused` | Preserve installed state without recording or modulating turns. |

`light` is the default recommendation. Mode changes update runtime controls without resetting valid existing state.

## Verify and refresh

```bash
packwright doctor project/nova-codex
packwright refresh-emotion-engine-codex \
  --target project/nova-codex \
  --emotion-engine-codex-source /path/to/emotion-engine-codex
```

`doctor` reports missing or drifted sidecar projections and invalid state JSON. The compatibility refresh command rewrites the installed sidecar projection and manifest bookkeeping while preserving the project-local runtime state.

## Migration boundary

Migration can carry `.emotion-engine/codex-state.json` as an explicitly reported snapshot, but non-Codex adapters use the character's spec-guided behavior rather than the Codex sidecar runtime. Packwright never treats live Emotion Engine state as a generated artifact eligible for deterministic `doctor --fix` replacement.
