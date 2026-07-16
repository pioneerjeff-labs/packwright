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

## Boundary

- `memory/*` stores durable facts, todos, pickup notes, knowledge pointers, and human-readable relationship continuity.
- `.codex/<character>/references/emotion/**` stores emotion policy/spec references.
- `.agents/skills/emotion-engine-codex/**` is the optional sidecar skill.
- `.emotion-engine/codex-state.json` is the optional live Emotion Engine runtime state.

Do not mix live Emotion Engine PAD/trust state into `memory/relationship-state.md`.
