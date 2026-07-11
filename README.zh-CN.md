# Packwright

Packwright 可在 Codex、Claude Code 与 Cursor 之间迁移已经在工作的 coding agent 配置，并在写入之前准确展示将生成、原样携带、改写和排除的内容。

输出是你可以直接阅读的普通文件。

> Packwright 自身不会发起任何网络请求，也不会发送遥测数据。你的文件始终由你控制；你所使用的 coding runtime 自身的数据政策仍然适用。

## 快速开始

安装当前候选版本：

```bash
python -m pip install packwright==0.1.0rc1
```

创建可编辑的源文件、构建并安装：

```bash
packwright init --template creator -o work/mira
packwright build work/mira --adapter codex -o pack/mira-codex
packwright install pack/mira-codex --target project/mira-codex
```

支持的 adapter 为 `codex`、`claude-code` 与 `cursor`。所有输出均为普通文件。

先预览迁移，不创建目标目录：

```bash
packwright migrate project/mira-codex \
  --to cursor \
  --target project/mira-cursor \
  --dry-run
```

检查生成、原样携带、改写与排除清单后，再明确确认写入：

```bash
packwright migrate project/mira-codex \
  --to cursor \
  --target project/mira-cursor \
  --yes
packwright doctor project/mira-cursor
packwright score project/mira-cursor
```

如需机器可读的迁移收据，请在预览与确认命令中都加入 `--json`。除非另行使用 `--force`，Packwright 不会覆盖已有目标。

## 分数边界

100.0 分表示 pack 通过 Packwright 的公开结构规则，不代表 coding runtime 的实际行为获得 100% 保证。三种 runtime 的真实交互兼容性需要独立验证。

更多内容请参阅 [CLI 契约](docs/CLI.md)、[coding agent 使用提示词](docs/USE_WITH_YOUR_AGENT.md)与 [0.1.0rc1 发布说明](docs/releases/0.1.0rc1.md)。
