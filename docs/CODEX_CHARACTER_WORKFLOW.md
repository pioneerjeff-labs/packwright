# Codex-First Character Creation

The intended user experience is inside Codex, not a terminal handoff.

```text
user talks to Codex
  -> Codex interviews dynamically
  -> Codex drafts canonical character_intake.yaml
  -> Codex shows summary/YAML for confirmation
  -> Codex runs deterministic compiler commands
  -> Codex reports generated folders
```

The CLI is the backend. Users should not need to copy prompts between Codex and Terminal during normal use.

## User Invocation

The user should be able to say:

```text
帮我派生一个新角色
```

or:

```text
帮我做一个 Alice，媒体选题和发布搭档，说话直接一点，可以吐槽但不要刻薄，也可以有一点情绪互动。
```

Codex should then run the workflow below.

## Codex Workflow

1. Interview the user dynamically.
   - Ask one concise question at a time.
   - Do not force exactly five questions.
   - If the answer is off-topic, vague, or only partially useful, ask a follow-up.
   - Extract meaning from casual phrasing.

2. Draft canonical intake YAML in a workspace file, usually:

   ```text
   build/<slug>-intake.yaml
   ```

3. Show a short confirmation summary.
   - Name
   - Relationship
   - Primary work
   - Voice and avoid rules
   - Direct emotional interaction choice

4. After user confirmation, run:

   ```bash
   packwright init \
     build/<slug>-intake.yaml \
     -o build/<slug>-work \
     --force

   packwright build \
     build/<slug>-work \
     --adapter codex \
     -o build/<slug>-codex-pack

   packwright install \
     build/<slug>-codex-pack \
     --adapter codex \
     --target build/<slug>-codex-target \
     --force
   ```

5. Report the result with paths:

   ```text
   build/<slug>-intake.yaml
   build/<slug>-work/
   build/<slug>-codex-pack/
   build/<slug>-codex-target/
   ```

6. Point the user at the files that matter:

   ```text
   build/<slug>-codex-target/AGENTS.md
   build/<slug>-codex-target/.agents/skills/<slug>-save-context/SKILL.md
   build/<slug>-codex-target/memory/
   ```

   The optional Emotion Engine files exist only when installation explicitly
   includes `--include-emotion-engine-codex` and a sidecar source:

   ```text
   build/<slug>-codex-target/.agents/skills/emotion-engine-codex/SKILL.md
   build/<slug>-codex-target/.emotion-engine/codex-state.json
   ```

## Boundary

Codex owns the human-facing intelligence in this workflow. The Python CLI owns deterministic compilation, scoring, and installation.

Do not ask the user to manually run terminal commands unless they explicitly want to.
