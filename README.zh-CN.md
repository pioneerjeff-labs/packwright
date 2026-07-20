<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/mark-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/mark-light.svg">
    <img alt="Packwright 燕尾榫标识" src="assets/mark-light.svg" width="88" height="88">
  </picture>
</p>

<h1 align="center">Packwright</h1>

<p align="center"><strong>一次构建 agent，随处皆可运行。</strong></p>

<p align="center">
  一次定义 agent 的规则、记忆、skills 与工作区，编译成 Codex、Claude Code 和 Cursor 的原生 pack；<br>
  构建并安装原生 pack；迁移时把记忆、工作区与知识状态一起带走。
</p>

<p align="center">
  <strong><a href="https://pioneerjeff-labs.github.io/packwright/zh-CN.html">查看在线产品网站 →</a></strong><br>
  看动画终端完整跑一遍 Claude Code → Codex 迁移，并在 Claude Code、Codex 与 Cursor 之间切换快速开始命令。<br>
  <a href="https://pioneerjeff-labs.github.io/packwright/zh-CN.html">简体中文</a> · <a href="https://pioneerjeff-labs.github.io/packwright/">English</a>
</p>

<p align="center">
  <a href="https://pioneerjeff-labs.github.io/packwright/zh-CN.html">
    <img alt="打开 Packwright 中文产品网站" src="assets/social-preview.png" width="800">
  </a>
</p>

<p align="center">
  <a href="https://pioneerjeff-labs.github.io/packwright/zh-CN.html"><img alt="Packwright 中文官网" src="https://img.shields.io/badge/中文官网-访问-9C4F16?style=flat-square"></a>
  <a href="https://github.com/pioneerjeff-labs/packwright/actions/workflows/ci.yml"><img alt="CI 状态" src="https://github.com/pioneerjeff-labs/packwright/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT 许可证" src="https://img.shields.io/badge/license-MIT-5C5245?style=flat-square"></a>
  <a href="README.md"><img alt="English README" src="https://img.shields.io/badge/README-English-B87333?style=flat-square"></a>
</p>

<p align="center"><strong>原生 pack。可移植状态。每次迁移都先预览，再写入。</strong></p>

> [!NOTE]
> Packwright 自身不会发起网络请求，也不会发送遥测数据。coding runtime 仍可能把它读取的文件发送给自己的模型服务商，其数据政策继续适用。

## 先交给 coding agent 代驾

最短的使用界面是一段对话。安装 Packwright，然后把现成提示词粘贴给 Codex、Claude Code 或 Cursor：

```bash
python -m pip install packwright==0.1.2
```

**[打开可直接粘贴的 agent 操作提示词 →](docs/USE_WITH_YOUR_AGENT.md)**

创建新 agent 时，你只需描述它要做什么并亲自选名字。提示词会让 coding agent 起草 canonical intake、交给你确认、构建 pack，并验证最终 target；迁移时则会先预览收据，等待确认后再写入。

## 创建你自己的 agent

先生成 Packwright 的采访契约，再让 coding agent 把对话整理成经你确认的 `character_intake.yaml`：

```bash
packwright draft-character \
  --user-name Morgan \
  --prompt-out work/character-interviewer.md
```

agent 保存确认后的 intake 后，再创建可编辑源并完成构建：

```bash
packwright init work/nova-intake.yaml -o work/nova
packwright build work/nova --adapter claude-code -o pack/nova-claude
packwright install pack/nova-claude --adapter claude-code --target project/nova-claude
```

已经有 agent 或工作区？先做清单盘点，不会直接导入任何内容：

```bash
packwright adopt --from existing-agent --dry-run
```

如需生成审核材料，可增加 `--target <target-dir>`。Packwright 会写出一份所有决定均为 `pending` 的源隔离队列 `adoption-review-<source>-<hash>.yaml`，多个来源不会互相覆盖；它不会自动应用队列或合并内容。

不通过 coding agent 时，可使用 `packwright init --interactive` 的固定问题后备流程。它会先展示完整 canonical YAML，确认后才写入。

## 或从无名 starter 开始

三种 preset 分别覆盖常见高频需求。支持自定义 agent 的职责、能力、语气、边界与情绪反馈；preset 只决定 agent 怎么工作，名字始终由你自己选择。

| preset | 起始角色 |
|---|---|
| `code` | 天才工程师——擅长编写、审查、调试、测试并交付技术工作 |
| `work` | 全能助手——规划项目、起草产出、理清决策并推动后续执行 |
| `companion` | 私人秘书——支持日常安排、生活决策、出行计划与情感陪伴 |

先查看精确默认值，再选择一种 preset，并由你亲自为角色命名。preset 路径的 init 会返回完整角色摘要，供你在 build 前确认。

```bash
packwright presets code
packwright init --template code --name Nova --user-name Morgan -o work/nova
packwright build work/nova --adapter claude-code -o pack/nova-claude
packwright install pack/nova-claude --adapter claude-code --target project/nova-claude
```

这里的 `Nova` 只是用户自选名字的示例；生成后仍可修改名字、关系、语气和边界。

先预览从 Claude Code 到 Codex 的迁移。此时不会创建目标目录：

```bash
packwright migrate project/nova-claude \
  --to codex \
  --target project/nova-codex --dry-run
```

迁移计划会明确列出四类路径：

| 收据分类 | 含义 |
|---|---|
| `generated` | 为目标 runtime 编译生成的文件 |
| `carried` | 原样复制并用 SHA-256 验证的可移植文件 |
| `rewritten` | 针对目标 runtime 改写的 Packwright 路由行 |
| `degraded` | 已发现但未经显式接受、不会在目标端重现的非托管 runtime automation |
| `excluded` | 明确留在原 runtime 的专属文件 |

审阅收据后，再应用同一迁移并验证结果：

```bash
packwright migrate project/nova-claude \
  --to codex \
  --target project/nova-codex --yes
packwright doctor project/nova-codex
packwright score project/nova-codex
```

如果只是升级某一个已安装实例的基础机制，不要走 handoff，也不需要迁移到另一
runtime；使用独立的 reconcile：

```bash
packwright reconcile --target project/nova-codex --mechanism work/nova --json --dry-run
packwright reconcile --target project/nova-codex --mechanism work/nova --json --yes
```

机制 0.8 会从 canonical `automations` 投影有字节上限的本地
`session_start` 与 `user_prompt` 上下文。Claude Code 和 Codex 支持两个事件；
Cursor 只支持 session-start 上下文，prompt-time 能力缺口会明确出现在收据中。
用户已有的 settings 与 hook 条目会按条目保留，不会被整份覆盖。

在预览和确认命令中加入 `--json`，即可得到机器可读的 `packwright-migration/v1` 收据。除非另行使用 `--force`，Packwright 不会覆盖已有 target。

## 为什么不只是提示词

一个正在工作的 coding agent 不只有顶层 instructions，而且三个 runtime 要求不同的原生文件布局：

| runtime | 原生入口 | 可复用流程 |
|---|---|---|
| Codex | `AGENTS.md` | `.agents/skills/<name>/SKILL.md` |
| Claude Code | `CLAUDE.md` | `.claude/skills/<name>/SKILL.md` |
| Cursor | `.cursor/rules/<name>.mdc` | `.cursor/rules/<name>-save-context.mdc` |

Packwright 把这些文件当作编译投影：可编辑源拥有行为定义，adapter 拥有 runtime 布局；迁移负责携带可移植状态，并公开说明接缝。

## 一次定义，带着它到处走

```text
可编辑源
  identity · memory contract · skills · workspace rules
         │
         ├── packwright build --adapter codex       → AGENTS.md + .agents/skills/
         ├── packwright build --adapter claude-code → CLAUDE.md + .claude/skills/
         └── packwright build --adapter cursor      → .cursor/rules/*.mdc
```

每个 pack 和已安装 target 都包含自包含的 `.packwright/` 元数据：canonical source snapshot、artifact lock 与 checker receipt。即使移动 target、删除原 build 目录，也能继续运行 `migrate`、`doctor` 与 `score`。

## 迁移一个正在工作的 agent

`migrate` 会重新编译目标 runtime 的原生文件，并把可移植状态带到新 target。它会在写入前报告不能携带的内容，再等待明确的 `--yes`。收据是 “carry it everywhere” 背后的证明，不是假装不同 runtime 之间没有接缝。

## 检查结果究竟证明什么

- `score` 检查公开结构与 artifact contract。`100.0` 表示结构通过，不承诺 runtime 行为完美。
- `doctor` 校验 Packwright 管理的投影哈希，并能修复可重建的漂移，不把可移植用户状态当成生成物。
- 迁移会验证目标端的 carried 与 rewritten 文件，并在写入前重新核对 degraded 源文件，同时记录计划分数和安装后分数；runtime automation 不再被静默当作可移植能力。存在 degraded 项时，非交互应用还必须提供 `--accept-degraded`。
- Reconcile 会比较 installed 与 desired canonical spec 哈希，保留实例状态并写入本地收据，不会反编译另一 runtime 的 hooks。
- 当前三个 adapter 共覆盖六个有向迁移路径。新 adapter 只有通过 checker 才会加入。

## 当前发布边界

`0.1.2` 是当前稳定版本。当前支持 Codex、Claude Code 与 Cursor。Packwright 是本地工具，不是云
同步服务；plain-file 结构分数与真实 runtime 兼容性是两件事。

## 文档

- [在线产品网站](https://pioneerjeff-labs.github.io/packwright/zh-CN.html) · [English](https://pioneerjeff-labs.github.io/packwright/)
- [CLI 契约](docs/CLI.md)
- [交给 coding agent 使用](docs/USE_WITH_YOUR_AGENT.md)
- [角色起草](docs/CHARACTER_DRAFTING.md)
- [agent archetype](docs/AGENT_ARCHETYPES.md)
- [可选 Emotion Engine sidecar](docs/EMOTION_ENGINE.md)
- [本地 runtime automation](docs/RUNTIME_AUTOMATIONS.md)
- [0.1.2 发布说明](docs/releases/0.1.2.md)
- [0.1.1 发布说明](docs/releases/0.1.1.md)
- [0.1.0 发布说明](docs/releases/0.1.0.md)
- [参与贡献](CONTRIBUTING.md)
- [安全政策](SECURITY.md)

Packwright 采用 [MIT License](LICENSE) 开源。
