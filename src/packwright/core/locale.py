"""Deterministic localization for compiler-owned projection text.

User-authored identity, memory, and skill prose is deliberately not translated.
Only strings emitted by Packwright itself are routed through this catalog.
"""

from .naming import character_name, character_user_name


DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ("en", "zh-CN")

_ALIASES = {
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
}

_SECTIONS = {
    "en": {
        "work_focus": "Work Focus",
        "personality": "Personality",
        "voice": "Voice",
        "working_rules": "Working Rules",
        "use_when_needed": "Use When Needed",
        "load_when_needed": "Load When Needed",
        "memory_contract": "Memory Contract",
        "loading_policy": "Loading Policy",
        "core_files": "Core Files",
        "save_context": "Save Context",
        "procedure": "Procedure",
        "memory_tracks": "Memory Tracks",
        "boundary_notes": "Boundary Notes",
        "write_rules": "Write Rules",
    },
    "zh-CN": {
        "work_focus": "工作重点",
        "personality": "性格",
        "voice": "表达方式",
        "working_rules": "工作规则",
        "use_when_needed": "按需使用",
        "load_when_needed": "按需加载",
        "memory_contract": "记忆契约",
        "loading_policy": "加载策略",
        "core_files": "核心文件",
        "save_context": "保存上下文",
        "procedure": "操作步骤",
        "memory_tracks": "记忆轨道",
        "boundary_notes": "边界说明",
        "write_rules": "写入规则",
    },
}

_ZH_LINES = {
    "- Say what matters first.": "- 先说最重要的事。",
    "- Use warmth through attentiveness, not decoration.": "- 用认真和关照体现温度，不靠修饰。",
    "- Treat file reads as internal work unless the user asks for evidence; do not turn normal replies into audit logs.": "- 除非用户要求证据，否则把读取文件视为内部工作；不要把正常回复写成审计日志。",
    "- When uncertain, name the uncertainty and check the source.": "- 不确定时，明确指出不确定之处并核对来源。",
    "- When corrected, restate the corrected model and adjust without defensiveness.": "- 被纠正时，重述修正后的理解并直接调整，不要辩解。",
    "- Preserve the user's stated intent and scope.": "- 保持用户明确表达的意图和范围。",
    "- Read relevant files before making factual claims.": "- 在作出事实判断前读取相关文件。",
    "- Keep durable memory in files, not in long prompt text.": "- 把持久记忆保存在文件中，不要塞进冗长提示词。",
    "- Use session index notes to make prior work discoverable.": "- 用会话索引记录让先前工作可被查找。",
    "- Use `workspace/<domain>/` for generated drafts, artifacts, and archives; keep memory files focused on state, decisions, and indexes.": "- 生成的草稿、产物和归档放在 `workspace/<domain>/`；记忆文件只聚焦状态、决策和索引。",
    "- Use `knowledge/` only for reviewed reusable models and patterns; keep current project state in `memory/`.": "- `knowledge/` 只存放审阅过的可复用模型和模式；当前项目状态放在 `memory/`。",
    "- Ask before consequential changes.": "- 进行会产生重要后果的修改前先询问。",
    "- Do not invent emotional or relationship state.": "- 不要虚构情绪或关系状态。",
    "- Read `memory/index.md` first when prior context may matter; it is the memory router, not a project state source.": "- 先前上下文可能相关时，先读 `memory/index.md`；它是记忆路由，不是项目状态来源。",
    "- Read `memory/profile.md` when stable user, subject, learner, creator, or relationship facts could affect the task.": "- 稳定的用户、主题、学习者、创作者或关系事实可能影响任务时，读取 `memory/profile.md`。",
    "- Read `memory/workstreams.md` when the request belongs to a long-running domain, needs domain routing, or may later be promoted to a separate agent.": "- 请求属于长期领域、需要领域路由或以后可能升级为独立 agent 时，读取 `memory/workstreams.md`。",
    "- Read `memory/projects/<slug>.md` when a specific project is named or clearly implied; project files are the source of project state and decisions.": "- 明确提到或明显指向某个项目时，读取 `memory/projects/<slug>.md`；项目文件是项目状态和决策的来源。",
    "- Read `memory/session-index.md` when the user refers to earlier sessions, previous work, or an unnamed prior plan.": "- 用户提到早先会话、先前工作或未命名的旧计划时，读取 `memory/session-index.md`。",
    "- Read `memory/source-map.md` when facts need source lookup, verification paths, or source-of-truth files.": "- 事实需要查找来源、验证路径或事实源文件时，读取 `memory/source-map.md`。",
    "- Read `knowledge/index.md` only when reusable domain knowledge may help; load the smallest useful note set.": "- 仅在可复用领域知识可能有帮助时读取 `knowledge/index.md`；只加载最小够用的笔记集。",
    "- Read `sources/*/manifest.json` only when provenance or original source lookup matters.": "- 仅在需要溯源或查找原始来源时读取 `sources/*/manifest.json`。",
    "- Read `memory/todos.md` for current action queues and commitments.": "- 读取 `memory/todos.md` 获取当前行动队列和承诺。",
    "- Read `memory/collaboration.md` when collaboration calibration, repair history, or user-specific working preferences affect the response.": "- 协作校准、修复历史或用户特定工作偏好会影响回复时，读取 `memory/collaboration.md`。",
    "- Treat `memory/pinned.md`, `memory/recent-activity.md`, `memory/knowledge_map.md`, and `memory/relationship-state.md` only as compatibility files unless the memory index points to them.": "- 除非记忆索引指向，否则仅把 `memory/pinned.md`、`memory/recent-activity.md`、`memory/knowledge_map.md` 和 `memory/relationship-state.md` 视为兼容文件。",
    "- Use `scripts/handoff_export.sh` for real cross-agent or cross-runtime handoff files.": "- 真正跨 agent 或跨 runtime 的交接文件使用 `scripts/handoff_export.sh`。",
    "- Use `workspace/shared/artifacts/handoffs/` for real cross-agent or cross-runtime handoff files.": "- 真正跨 agent 或跨 runtime 的交接文件放在 `workspace/shared/artifacts/handoffs/`。",
    "- Use `workspace/shared/artifacts/session-briefs/` for same-agent next-session briefs; do not label them handoffs.": "- 同一 agent 的下次会话简报放在 `workspace/shared/artifacts/session-briefs/`；不要称为交接。",
    "- Read `memory/index.md` first; it routes to the owner file for each kind of memory.": "- 先读 `memory/index.md`；它会把每类记忆路由到负责该信息的文件。",
    "- Load only the relevant owner files for the current task.": "- 只加载与当前任务相关的归属文件。",
    "- Prefer source-map pointers and source files when factual accuracy matters.": "- 事实准确性重要时，优先使用 source map 指针和源文件。",
    "- Read `knowledge/index.md` only for reviewed reusable domain knowledge; do not treat it as current project state.": "- `knowledge/index.md` 只用于审阅过的可复用领域知识；不要把它当作当前项目状态。",
    "- Use `sources/*/manifest.json` for provenance lookup when source evidence matters.": "- 来源证据重要时，使用 `sources/*/manifest.json` 溯源。",
    "- Do not load compatibility files by default unless the memory index points to them.": "- 除非记忆索引指向，否则默认不加载兼容文件。",
    "- Keep generated work products in `workspace/<domain>/`, not in memory files.": "- 生成的工作产物放在 `workspace/<domain>/`，不要放进记忆文件。",
    "- `memory/profile.md`: explicit stable facts and preferences.": "- `memory/profile.md`：明确的稳定事实和偏好。",
    "- `memory/workstreams.md`: long-running domain routing.": "- `memory/workstreams.md`：长期领域路由。",
    "- `memory/workstreams/<slug>.md`: dense domain state.": "- `memory/workstreams/<slug>.md`：密集领域状态。",
    "- `memory/projects/<slug>.md`: project state, decisions, and open loops.": "- `memory/projects/<slug>.md`：项目状态、决策和未闭环事项。",
    "- `memory/session-index.md`: earlier session lookup.": "- `memory/session-index.md`：早先会话查找。",
    "- `memory/source-map.md`: source, account, file, and artifact lookup.": "- `memory/source-map.md`：来源、账号、文件和产物查找。",
    "- `memory/todos.md`: action queues and commitments.": "- `memory/todos.md`：行动队列和承诺。",
    "- `memory/collaboration.md`: stable collaboration calibration.": "- `memory/collaboration.md`：稳定的协作校准。",
}


def normalize_locale(value):
    """Return a supported deterministic locale; unknown values use English."""
    if not isinstance(value, str):
        return DEFAULT_LOCALE
    return _ALIASES.get(value.strip().lower(), DEFAULT_LOCALE)


def mechanism_locale(mechanism):
    metadata = mechanism.get("metadata", {}) if isinstance(mechanism, dict) else {}
    return normalize_locale(metadata.get("locale"))


def section_heading(locale, section_id):
    return "## " + _SECTIONS[normalize_locale(locale)][section_id]


def identity_line(locale, name):
    if normalize_locale(locale) == "zh-CN":
        return f"你是 {name}。"
    return f"You are {name}."


def locale_feature(mechanism, adapter):
    metadata = mechanism.get("metadata", {}) if isinstance(mechanism, dict) else {}
    requested = metadata.get("locale")
    resolved = mechanism_locale(mechanism)
    on_demand = "load_when_needed" if adapter == "claude-code" else "use_when_needed"
    return {
        "requested": requested,
        "resolved": resolved,
        "fallback_to_english": bool(requested) and normalize_locale(requested) == "en" and str(requested).lower() not in {
            "en", "en-us", "en-gb"
        },
        "sections": {
            "voice": section_heading(resolved, "voice"),
            "working_rules": section_heading(resolved, "working_rules"),
            "on_demand": section_heading(resolved, on_demand),
        },
    }


def localize_entry_markdown(text, mechanism, adapter):
    """Localize only known compiler-emitted lines in an adapter entry file."""
    if mechanism_locale(mechanism) != "zh-CN":
        return text
    identity = mechanism.get("identity", {})
    name = character_name(mechanism)
    user_name = character_user_name(mechanism)
    protected = {
        *(f"- {item}" for item in identity.get("work_focus", [])),
        *(f"- {item}" for item in identity.get("personality", [])),
        f"- {str(identity.get('voice_summary', '')).strip()}",
    }
    dynamic = {
        f"You are {name}.": f"你是 {name}。",
        f"{name} is {identity.get('role', '')}": f"{name} 的角色是：{identity.get('role', '')}",
        f"- When memory is empty, say there is no pickup yet and help {user_name} establish the first useful context; do not quote template placeholders.": f"- 记忆为空时，说明目前没有可接续的上下文，并帮助 {user_name} 建立第一份有用记录；不要引用模板占位符。",
        f"description: Core behavior and working rules for {name}.": f"description: {name} 的核心行为与工作规则。",
        f"description: Memory loading and ownership rules for {name}. Use when prior context may matter.": f"description: {name} 的记忆加载与归属规则；先前上下文可能相关时使用。",
        f"# {name} Memory Contract": f"# {name} 记忆契约",
        f"Use this rule when a request needs prior project, domain, source, todo, session, or collaboration context.": "请求需要先前的项目、领域、来源、待办、会话或协作上下文时，使用此规则。",
    }
    voice = str(identity.get("voice_summary", "")).strip()
    if voice and voice[-1:] not in ".!?。！？":
        dynamic[f"- {voice}."] = f"- {voice}。"
    headings = {
        "## Work Focus": section_heading("zh-CN", "work_focus"),
        "## Personality": section_heading("zh-CN", "personality"),
        "## Voice": section_heading("zh-CN", "voice"),
        "## Working Rules": section_heading("zh-CN", "working_rules"),
        "## Use When Needed": section_heading("zh-CN", "use_when_needed"),
        "## Load When Needed": section_heading("zh-CN", "load_when_needed"),
        "## Loading Policy": section_heading("zh-CN", "loading_policy"),
        "## Core Files": section_heading("zh-CN", "core_files"),
    }
    output = []
    for line in text.splitlines():
        if line in protected:
            output.append(line)
        elif line in dynamic:
            output.append(dynamic[line])
        elif line in headings:
            output.append(headings[line])
        else:
            output.append(_ZH_LINES.get(line, _localize_runtime_entry_line(line, adapter)))
    return "\n".join(output)


def _localize_runtime_entry_line(line, adapter):
    if line.startswith("- Read `") and " for milestone handoff or explicit context-save requests." in line:
        return line.replace("- Read `", "- 读取 `", 1).replace(
            " for milestone handoff or explicit context-save requests.", "，用于里程碑交接或明确的上下文保存请求。"
        )
    if line.startswith("- Use `") and " for milestone handoff, session close, or explicit context-save requests." in line:
        return line.replace("- Use `", "- 使用 `", 1).replace(
            " for milestone handoff, session close, or explicit context-save requests.", "，用于里程碑交接、会话结束或明确的上下文保存请求。"
        )
    if line.startswith("- Use `") and " when " in line:
        localized = line.replace("- Use `", "- 使用 `", 1).replace(" when ", "，使用时机：", 1)
        return localized.replace(
            "prior context, domain routing, project state, or source lookup may matter.",
            "先前上下文、领域路由、项目状态或来源查找可能相关。",
        )
    if line.startswith("- Read `") and " when " in line:
        return line.replace("- Read `", "- 读取 `", 1).replace(" when ", "，读取时机：", 1)
    if line.startswith("- @") and ": " in line:
        path, purpose = line.split(": ", 1)
        purpose_map = {
            "milestone handoff, session close, or explicit context-save requests.": "用于里程碑交接、会话结束或明确的上下文保存请求。",
            "default memory router when prior context may matter.": "先前上下文可能相关时使用的默认记忆路由。",
            "action queues and active commitments.": "行动队列和当前承诺。",
            "learned collaboration calibrations and repair notes.": "已形成的协作校准和修复记录。",
            "stable user, subject, learner, creator, or relationship facts when they affect the task.": "稳定的用户、主题、学习者、创作者或关系事实影响任务时使用。",
            "long-running domain routing, domain context, and future agent-promotion decisions.": "用于长期领域路由、领域上下文和未来的 agent 升级决策。",
            "project state and decisions when a project is named or implied.": "明确提到或指向某个项目时，用于项目状态和决策。",
            "session/thread recall when earlier work is referenced.": "提到早先工作时，用于查找会话。",
            "source lookup and verification paths.": "用于来源查找和验证路径。",
            "reusable domain knowledge recall router; load only the smallest useful note set.": "可复用领域知识的召回路由；只加载最小够用的笔记集。",
            "provenance lookup when source evidence matters.": "来源证据重要时用于溯源。",
            "use only as compatibility files unless the memory index points to them.": "除非记忆索引指向，否则仅作为兼容文件使用。",
            "reserved Emotion Engine state shape only; do not treat it as live runtime state.": "仅为预留的 Emotion Engine 状态结构；不要当作活运行状态。",
        }
        return f"{path}：{purpose_map.get(purpose, purpose)}"
    if "prior context, domain routing, project state, or source lookup may matter." in line:
        return line.replace(
            "prior context, domain routing, project state, or source lookup may matter.",
            "先前上下文、领域路由、项目状态或来源查找可能相关。",
        )
    return line


def localize_save_context_markdown(text, mechanism):
    """Localize compiler-owned save-context instructions for Chinese packs."""
    if mechanism_locale(mechanism) != "zh-CN":
        return text
    name = character_name(mechanism)
    user_name = character_user_name(mechanism)
    replacements = {
        "# Save Context": "# 保存上下文",
        f"# {name} Save Context": f"# {name} 保存上下文",
        "## Procedure": section_heading("zh-CN", "procedure"),
        "## Memory Tracks": section_heading("zh-CN", "memory_tracks"),
        "## Boundary Notes": section_heading("zh-CN", "boundary_notes"),
        "## Write Rules": section_heading("zh-CN", "write_rules"),
        f"Use this skill at milestone handoff, session close, or when {user_name} explicitly asks {name} to preserve context.": f"在里程碑交接、会话结束，或 {user_name} 明确要求 {name} 保存上下文时使用此 skill。",
        f"Use this rule at milestone handoff, session close, or when {user_name} explicitly asks {name} to preserve context.": f"在里程碑交接、会话结束，或 {user_name} 明确要求 {name} 保存上下文时使用此规则。",
        "1. Identify the current objective, scope, decisions, changed files, verification, and open questions.": "1. 确认当前目标、范围、决策、已改文件、验证结果和待解决问题。",
        "2. Update the canonical owner file instead of copying the same fact across layers.": "2. 更新唯一负责该信息的规范文件，不要跨层复制同一事实。",
        "3. Update `memory/profile.md` only for stable cross-workstream profile facts the user intentionally provides or confirms.": "3. 仅把用户主动提供或确认的、跨工作流稳定的资料事实写入 `memory/profile.md`。",
        "4. Update `memory/workstreams.md` for long-running domain routing, and `memory/workstreams/<slug>.md` for dense domain state.": "4. 长期领域路由写入 `memory/workstreams.md`，密集领域状态写入 `memory/workstreams/<slug>.md`。",
        "5. Update `memory/projects/<slug>.md` for project state, decisions, open loops, and project-specific sources.": "5. 项目状态、决策、未闭环事项和项目来源写入 `memory/projects/<slug>.md`。",
        "6. Update `memory/session-index.md` for session/thread lookup entries, not project state summaries.": "6. `memory/session-index.md` 只写会话查找条目，不写项目状态摘要。",
        "7. Update `memory/source-map.md` for source-of-truth paths, verification routes, workspace artifacts, and lookup pointers.": "7. 事实源路径、验证路线、工作区产物和查找指针写入 `memory/source-map.md`。",
        "8. Update `memory/todos.md` for action queues and commitments.": "8. 行动队列和承诺写入 `memory/todos.md`。",
        "9. Update `memory/collaboration.md` only for stable collaboration calibrations; do not write ordinary praise, transient mood, or live Emotion Engine state.": "9. `memory/collaboration.md` 只写稳定的协作校准；不要写普通夸奖、短暂情绪或 Emotion Engine 活状态。",
        "10. Put generated drafts, artifacts, and archives under `workspace/<domain>/`; do not copy full deliverables into memory files.": "10. 生成的草稿、产物和归档放在 `workspace/<domain>/`；不要把完整交付物复制到记忆文件。",
        "11. Update `memory/index.md` only when active projects, memory owners, or routing rules change.": "11. 仅在活跃项目、记忆归属或路由规则变化时更新 `memory/index.md`。",
        "12. Report what was saved, what remains unsaved, and where the next session should resume.": "12. 报告已保存内容、未保存内容，以及下次会话应从哪里继续。",
        "9. Update `memory/collaboration.md` only for stable collaboration calibrations.": "9. `memory/collaboration.md` 只写稳定的协作校准。",
        "11. Update `memory/index.md` only when active projects, memory owners, or routing rules change.": "11. 仅在活跃项目、记忆归属或路由规则变化时更新 `memory/index.md`。",
        "12. Report what was saved and what remains unsaved.": "12. 报告已保存内容和未保存内容。",
        "11. Use `workspace/shared/artifacts/session-briefs/` for same-agent next-session briefs.": "11. 同一 agent 的下次会话简报放在 `workspace/shared/artifacts/session-briefs/`。",
        "12. Use `workspace/shared/artifacts/handoffs/` only for real cross-agent or cross-runtime handoff files.": "12. `workspace/shared/artifacts/handoffs/` 只存放真正跨 agent 或跨 runtime 的交接文件。",
        "13. Update `memory/index.md` only when active projects, memory owners, or routing rules change.": "13. 仅在活跃项目、记忆归属或路由规则变化时更新 `memory/index.md`。",
        "14. Report what was saved, what remains unsaved, and where the next session should resume.": "14. 报告已保存内容、未保存内容，以及下次会话应从哪里继续。",
        "- Fact assertion gates are session guards, not a skill.": "- 事实断言 gate 属于会话守则，不是 skill。",
        "- Fact assertion gates are session guards, not a rule file.": "- 事实断言 gate 属于会话守则，不是规则文件。",
        "- Pulse, Emotion Engine runtime, Hermes, and OpenClaw remain reserved; this skill does not implement runtimes.": "- Pulse、Emotion Engine runtime、Hermes 和 OpenClaw 仍为预留项；此 skill 不实现这些 runtime。",
        "- `memory/profile.md` stores explicit stable profile facts, not inferred mood or secrets.": "- `memory/profile.md` 保存明确的稳定资料事实，不保存推断出的情绪或秘密。",
        "- `memory/workstreams.md` is a domain router for long-running areas; project files still own project-specific state.": "- `memory/workstreams.md` 是长期领域的路由；项目特定状态仍由项目文件负责。",
        "- `memory/session-index.md` is a lookup index, not a project state source.": "- `memory/session-index.md` 是查找索引，不是项目状态来源。",
        "- `AGENTS.md` is stable identity/default behavior, not learned collaboration calibration.": "- `AGENTS.md` 保存稳定身份和默认行为，不保存后天形成的协作校准。",
        "- `CLAUDE.md` is stable identity/default behavior, not learned collaboration calibration.": "- `CLAUDE.md` 保存稳定身份和默认行为，不保存后天形成的协作校准。",
        "- `knowledge/index.md` is a recall router for reviewed reusable knowledge, not current project status.": "- `knowledge/index.md` 是已审阅可复用知识的召回路由，不是当前项目状态。",
        "- `sources/*/manifest.json` stores provenance for knowledge notes and external sources; it is not the knowledge body.": "- `sources/*/manifest.json` 保存知识笔记和外部来源的溯源信息，不是知识正文。",
        "- `workspace/<domain>/` stores drafts, deliverables, and archives; important outputs should be indexed in `memory/source-map.md`.": "- `workspace/<domain>/` 保存草稿、交付物和归档；重要产物应在 `memory/source-map.md` 建立索引。",
        "- `.emotion-engine/state.json` stores dynamic emotion state; do not mirror it into memory files.": "- `.emotion-engine/state.json` 保存动态情绪状态；不要把它复制到记忆文件。",
        "- `.emotion-engine/state.json` stores dynamic emotion state when enabled; do not mirror it into memory files.": "- 启用后，`.emotion-engine/state.json` 保存动态情绪状态；不要把它复制到记忆文件。",
        "- Do not write cloud state in the current local projection.": "- 当前本地投影不要写入云端状态。",
        "- Do not put current status into `CLAUDE.md` or `AGENTS.md`.": "- 不要把当前状态写入 `CLAUDE.md` 或 `AGENTS.md`。",
        "- Prefer one compact session-index lookup entry over copying long context.": "- 优先写一条紧凑的会话索引，而不是复制长上下文。",
        "- Keep profile facts explicit and user-confirmed.": "- 资料事实必须明确且经过用户确认。",
        "- Do not store live Emotion Engine runtime JSON in durable memory files.": "- 不要把 Emotion Engine 的活运行 JSON 写入持久记忆文件。",
    }
    output = []
    for line in text.splitlines():
        localized = replacements.get(line)
        if localized is None and line.startswith(f"- {name} local memory files remain"):
            localized = f"- {name} 的本地记忆文件仍是持久记忆的事实源。"
        if localized is None:
            localized = _localize_default_memory_track(line)
        output.append(localized)
    return "\n".join(output)


def _localize_default_memory_track(line):
    purposes = {
        "Default memory router; points to active projects and canonical memory owners.": "默认记忆路由；指向活跃项目和规范记忆归属文件。",
        "Stable user, subject, learner, creator, or relationship facts that matter across workstreams.": "跨工作流有影响的稳定用户、主题、学习者、创作者或关系事实。",
        "Domain router for long-running work areas; route to workstream detail files when useful.": "长期工作领域的路由；需要时指向工作流详情文件。",
        "Optional detailed domain files for mature workstreams and future agent promotion.": "成熟工作流和未来 agent 升级所用的可选领域详情文件。",
        "Source of truth for project state, decisions, open loops, and project-specific sources.": "项目状态、决策、未闭环事项和项目特定来源的事实源。",
        "Lookup index for prior sessions, thread recall, and earlier work references.": "先前会话、任务回忆和早期工作引用的查找索引。",
        "Source registry for lookup and verification paths; not a knowledge base.": "查找和验证路径的来源登记表；不是知识库。",
        "Action queues and commitments.": "行动队列和承诺。",
        "Learned collaboration calibrations and repair notes.": "后天形成的协作校准和修复记录。",
        "Compatibility-only in the MVP; avoid using it as a normal memory layer.": "仅用于 MVP 兼容；不要作为常规记忆层。",
        "Compatibility alias for memory/session-index.md.": "memory/session-index.md 的兼容别名。",
        "Persist context into the canonical owner files.": "把上下文持久化到规范归属文件。",
        "Compatibility alias for memory/collaboration.md.": "memory/collaboration.md 的兼容别名。",
        "Domain-first draft, artifact, and archive storage; important outputs are indexed in memory/source-map.md.": "按领域保存草稿、产物和归档；重要产物在 memory/source-map.md 建立索引。",
    }
    if not line.startswith("- ") or ": " not in line:
        return line
    key, purpose = line.split(": ", 1)
    return f"{key}：{purposes[purpose]}" if purpose in purposes else line
