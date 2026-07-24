# Character Drafting Architecture

Packwright character creation has two layers.

```text
messy user intent
  -> LLM interviewer / normalizer
  -> confirmed canonical character_intake.yaml
  -> deterministic compiler
  -> mechanism.yaml
  -> adapter pack
  -> install target
```

The normal path begins with the user's description and chosen name. For a shorter path, Packwright also exposes three nameless capability presets—`code`, `work`, and `companion`—but the resulting character instance still requires a user-supplied name.

## LLM Interviewer

The interviewer is responsible for understanding the user. It should ask dynamic questions, reject or follow up on unrelated answers, and normalize casual phrasing into canonical fields.

Examples:

- `叫 Alice 吧` -> `name: Alice`
- `是我的工作搭档` -> `relationship: work partner`
- `有点毒舌但别刻薄` -> put the sharpness in `voice`, and put the boundary in `avoid`

The interviewer must not generate runtime files. It outputs only a confirmed `CharacterIntake` YAML document.

Generate the interviewer contract with:

```bash
packwright draft-character \
  --user-name Morgan \
  --prompt-out build/character-interviewer.md
```

## Basic Terminal Fallback

For a fixed-question flow without an LLM interviewer, run:

```bash
packwright init --interactive --user-name Morgan -o work/nova
```

This fallback performs only deterministic normalization. It prints the completed canonical `CharacterIntake` YAML and asks for confirmation before writing either the intake or generated source. Rejecting the preview writes nothing.

## Canonical Intake

The compiler expects this shape:

```yaml
version: "0.1"
kind: CharacterIntake
locale: en
character:
  name: Alice
  user_name: Morgan
  relationship: media work partner
  role: "Morgan's media planning and publishing work partner."
  voice: direct, proactive about risks, occasionally sharp and playful, but not cruel
  avoid:
    - bland assistant tone
    - excessive politeness
    - mechanical audit-log replies
    - cruelty or personal attacks
  primary_work:
    - plan media topics
    - polish copy
    - develop cover and title ideas
    - prepare content for final publishing
  traits:
    - direct
    - perceptive
    - playful
    - editorially practical
  direct_emotional_interaction: some_direct_emotional_interaction
```

`locale` controls only Packwright's compiler-owned headings and behavioral
guidance. Supported values are `en` and `zh-CN`; missing or unsupported values
deterministically use English. User-authored identity, memory, and skill prose
is preserved verbatim rather than translated. The LLM interviewer should emit
`zh-CN` when the conversation is clearly Chinese and `en` otherwise.

## Deterministic Compiler

`packwright init <intake.yaml>` is deliberately boring. It validates a clean YAML document and generates editable agent source. It does not infer meaning from messy natural language.

```bash
packwright init \
  build/alice-intake.yaml \
  -o build/alice-work
```

Then compile and install:

```bash
packwright build \
  build/alice-work \
  --adapter codex \
  -o build/alice-codex-pack

packwright install \
  build/alice-codex-pack \
  --adapter codex \
  --target build/alice-codex-target
```

For a confirmed intake and fresh directories, `packwright new` performs those
three deterministic stages in one command while keeping the editable source
and built pack:

```bash
packwright new build/alice-intake.yaml \
  --adapter codex \
  --work-dir work/alice \
  --pack-dir pack/alice-codex \
  --target project/alice-codex
```

The one-command path refuses existing or overlapping directories. Preset use
also requires `--accept-preset` after inspecting `packwright presets <name>`.

## Boundary

- `memory/*` stores durable facts, todos, pickup notes, knowledge pointers, and human-readable relationship continuity.
- `.codex/<character>/references/emotion/**` stores emotion policy/spec references.
- `.agents/skills/emotion-engine/SKILL.md` is the optional Codex guidance projection; other adapters receive their native guidance path.
- `.packwright/runtime/emotion-engine/**` is the shared optional v1.0.0 runtime.
- `.emotion-engine/state.json` is the optional live Emotion Engine runtime state.

Do not mix live Emotion Engine PAD/trust state into `memory/relationship-state.md`.

## Semantic skills

Every entry in the mechanism's `skills:` list is a canonical semantic skill.
Do not put an `adapters:` list in a skill:

```yaml
skills:
  - id: research-brief
    path: skills/research-brief/SKILL.md
    layer: task_workflow
    trigger: Use when a claim needs a compact evidence brief.
    capabilities: [local-files, mcp]
```

`capabilities` is optional. It describes what the workflow genuinely needs,
not where it should run. The adapter registry chooses the destination path,
front matter, entry-file routing, and any explicit unavailable status:

| Adapter | Example projection |
|---|---|
| Codex | `.agents/skills/<character>-research-brief/SKILL.md` |
| Claude Code | `.claude/skills/<character>-research-brief/SKILL.md` |
| Cursor | `.cursor/rules/<character>-research-brief.mdc` |
| Pi | `.agents/skills/<character>-research-brief/SKILL.md` |

Files users add directly under an installed target's root `skills/` directory
remain unmanaged. Migration carries them unchanged and lists them separately
from Packwright-managed projections.
