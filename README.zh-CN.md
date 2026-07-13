<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/mark-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/mark-light.svg">
    <img alt="Packwright 燕尾榫标识" src="assets/mark-light.svg" width="88" height="88">
  </picture>
</p>

<h1 align="center">Packwright</h1>

<p align="center"><strong>一次构建 Agent。随心迁移，无缝运行。</strong></p>

<p align="center">
  一次定义 agent 的规则、记忆、skills 与工作区，编译成 Codex、Claude Code 和 Cursor 的原生 pack；<br>
  构建、安装、迁移与验证，全部落在可阅读的普通文件里。
</p>

<p align="center">
  <strong><a href="https://pioneerjeff-labs.github.io/packwright/zh-CN.html">查看在线产品网站 →</a></strong><br>
  看动画终端完整跑一遍 Claude Code → Codex 迁移，并在 Claude、Codex 与 Cursor 之间切换快速开始命令。<br>
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

<p align="center"><strong>输出是你可以直接阅读的普通文件。</strong></p>

> [!NOTE]
> Packwright 自身不会发起网络请求，也不会发送遥测数据。coding runtime 仍可能把它读取的文件发送给自己的模型服务商，其数据政策继续适用。

## 先交给 coding agent 代驾

最短的使用界面是一段对话。安装 Packwright，然后把现成提示词粘贴给 Codex、Claude Code 或 Cursor：

```bash
python -m pip install packwright==0.1.0rc1
```

**[打开可直接粘贴的 agent 操作提示词 →](docs/USE_WITH_YOUR_AGENT.md)**

提示词会要求 agent 先做迁移预览、解释完整收据、等待你的确认，再写入并验证最终 target。

## 或者手动运行

创建可编辑源，构建并安装一个 Claude Code target：

```bash
packwright init --template creator -o work/mira
packwright build work/mira --adapter claude-code -o pack/mira-claude
packwright install pack/mira-claude --adapter claude-code --target project/mira-claude
```

先预览从 Claude Code 到 Codex 的迁移。此时不会创建目标目录：

```bash
packwright migrate project/mira-claude \
  --to codex \
  --target project/mira-codex --dry-run
```

迁移计划会明确列出四类路径：

| 收据分类 | 含义 |
|---|---|
| `generated` | 为目标 runtime 编译生成的文件 |
| `carried` | 原样复制并用 SHA-256 验证的可移植文件 |
| `rewritten` | 针对目标 runtime 改写的 Packwright 路由行 |
| `excluded` | 明确留在原 runtime 的专属文件 |

审阅收据后，再应用同一迁移并验证结果：

```bash
packwright migrate project/mira-claude \
  --to codex \
  --target project/mira-codex --yes
packwright doctor project/mira-codex
packwright score project/mira-codex
```

在预览和确认命令中加入 `--json`，即可得到机器可读的 `packwright-migration/v1` 收据。除非另行使用 `--force`，Packwright 不会覆盖已有 target。

## 为什么不只是提示词

一个正在工作的 coding agent 不只有顶层 instructions，而且三个 runtime 要求不同的原生文件布局：

| Runtime | 原生入口 | 可复用流程 |
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
- `doctor` 诊断确定性的投影漂移，并能修复 Packwright 管理的文件，不把用户记忆当成生成物。
- 迁移会对 carried 与 rewritten 文件逐个做哈希验证，同时记录计划分数和安装后分数。
- 当前三个 adapter 共覆盖六个有向迁移路径。新 adapter 只有通过 checker 才会加入。

## 当前发布边界

`0.1.0rc1` 是用于外部安装和 runtime 测试的候选版本。当前支持 Codex、Claude Code 与 Cursor。Packwright 是本地工具，不是云同步服务；plain-file 结构分数与真实 runtime 兼容性是两件事。

## 文档

- [在线产品网站](https://pioneerjeff-labs.github.io/packwright/zh-CN.html) · [English](https://pioneerjeff-labs.github.io/packwright/)
- [CLI 契约](docs/CLI.md)
- [交给 coding agent 使用](docs/USE_WITH_YOUR_AGENT.md)
- [角色起草](docs/CHARACTER_DRAFTING.md)
- [Agent archetype](docs/AGENT_ARCHETYPES.md)
- [0.1.0rc1 发布说明](docs/releases/0.1.0rc1.md)
- [参与贡献](CONTRIBUTING.md)
- [安全政策](SECURITY.md)

Packwright 采用 [MIT License](LICENSE) 开源。
