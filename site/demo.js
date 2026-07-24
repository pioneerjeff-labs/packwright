(() => {
  "use strict";

  const englishLines = [
    { className: "cmd", text: "python -m pip install packwright==0.3.0" },
    { className: "t-ok", text: "  ✓ installed packwright 0.3.0 · Pi Core included" },
    { className: "cmd", text: "packwright init --template code --name Nova -o work/nova" },
    { className: "cmd", text: "packwright build work/nova --adapter claude-code -o pack/nova-claude" },
    { className: "t-ok", text: "  ✓ pack compiled · checker score 100.0" },
    { className: "cmd", text: "packwright install pack/nova-claude --adapter claude-code --target project/nova-claude" },
    { className: "t-ok", text: "  ✓ installed native Claude Code target" },
    { className: "t-dim", text: "# the same agent has lived in Claude Code for months — carry it to Codex" },
    { className: "cmd", text: "packwright migrate project/nova-claude --to codex --target project/nova-codex --dry-run" },
    { className: "t-fg", text: "  would carry:   memory/** · workspace/** · knowledge/** · sources/**" },
    { className: "t-note", text: "  would exclude: CLAUDE.md · .claude/** · no files written" },
    { className: "cmd", text: "packwright migrate project/nova-claude --to codex --target project/nova-codex --yes" },
    { className: "t-ok", text: "  ✓ carried hashes verified · installed score 100.0" },
    { className: "t-dim", text: "# structure verified · operational readiness reported separately" },
  ];
  const chineseLines = [
    { className: "cmd", text: "python -m pip install packwright==0.3.0" },
    { className: "t-ok", text: "  ✓ 已安装 packwright 0.3.0 · 已支持 Pi Core" },
    { className: "cmd", text: "packwright init --template code --name Nova -o work/nova" },
    { className: "cmd", text: "packwright build work/nova --adapter claude-code -o pack/nova-claude" },
    { className: "t-ok", text: "  ✓ pack 编译完成 · checker 评分 100.0" },
    { className: "cmd", text: "packwright install pack/nova-claude --adapter claude-code --target project/nova-claude" },
    { className: "t-ok", text: "  ✓ 已安装原生 Claude Code target" },
    { className: "t-dim", text: "# 该 agent 已在 Claude Code 中稳定运行数月——现在将其迁移至 Codex" },
    { className: "cmd", text: "packwright migrate project/nova-claude --to codex --target project/nova-codex --dry-run" },
    { className: "t-fg", text: "  计划携带：memory/** · workspace/** · knowledge/** · sources/**" },
    { className: "t-note", text: "  计划排除：CLAUDE.md · .claude/** · 未写入任何文件" },
    { className: "cmd", text: "packwright migrate project/nova-claude --to codex --target project/nova-codex --yes" },
    { className: "t-ok", text: "  ✓ 携带文件哈希验证通过 · 安装后评分 100.0" },
    { className: "t-dim", text: "# 结构已验证 · 运行就绪度另行报告" },
  ];
  const isChinese = document.documentElement.lang.toLowerCase().startsWith("zh");
  const lines = isChinese ? chineseLines : englishLines;
  const quickstartCommands = {
    pi: [
      "python -m pip install packwright==0.3.0",
      "packwright init --template code --name Nova -o work/nova",
      "packwright build work/nova --adapter pi -o pack/nova-pi",
      "packwright install pack/nova-pi --adapter pi --target project/nova-pi",
    ].join("\n"),
    "claude-code": [
      "python -m pip install packwright==0.3.0",
      "packwright init --template code --name Nova -o work/nova",
      "packwright build work/nova --adapter claude-code -o pack/nova-claude",
      "packwright install pack/nova-claude --adapter claude-code --target project/nova-claude",
    ].join("\n"),
    codex: [
      "python -m pip install packwright==0.3.0",
      "packwright init --template code --name Nova -o work/nova",
      "packwright build work/nova --adapter codex -o pack/nova-codex",
      "packwright install pack/nova-codex --adapter codex --target project/nova-codex",
    ].join("\n"),
    cursor: [
      "python -m pip install packwright==0.3.0",
      "packwright init --template code --name Nova -o work/nova",
      "packwright build work/nova --adapter cursor -o pack/nova-cursor",
      "packwright install pack/nova-cursor --adapter cursor --target project/nova-cursor",
    ].join("\n"),
  };
  const terminal = document.getElementById("term");
  const reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function renderLine(line) {
    const row = document.createElement("div");
    if (line.className === "cmd") {
      const prompt = document.createElement("span");
      prompt.className = "t-cop";
      prompt.textContent = "$ ";
      const text = document.createElement("span");
      text.className = "t-fg";
      text.textContent = line.text;
      row.append(prompt, text);
    } else {
      row.className = line.className;
      row.textContent = line.text;
    }
    return row;
  }

  if (terminal) {
    if (reducedMotion) {
      lines.forEach((line) => terminal.appendChild(renderLine(line)));
    } else {
      let lineIndex = 0;
      const nextLine = () => {
        if (lineIndex >= lines.length) {
          const row = document.createElement("div");
          const prompt = document.createElement("span");
          prompt.className = "t-cop";
          prompt.textContent = "$ ";
          const cursor = document.createElement("span");
          cursor.className = "cursor";
          row.append(prompt, cursor);
          terminal.appendChild(row);
          window.setTimeout(() => {
            terminal.replaceChildren();
            lineIndex = 0;
            nextLine();
          }, 6000);
          return;
        }

        const line = lines[lineIndex];
        lineIndex += 1;
        if (line.className === "cmd") {
          const row = document.createElement("div");
          const prompt = document.createElement("span");
          prompt.className = "t-cop";
          prompt.textContent = "$ ";
          const text = document.createElement("span");
          text.className = "t-fg";
          const cursor = document.createElement("span");
          cursor.className = "cursor";
          row.append(prompt, text, cursor);
          terminal.appendChild(row);
          let characterIndex = 0;
          const type = () => {
            if (characterIndex < line.text.length) {
              text.textContent += line.text.charAt(characterIndex);
              characterIndex += 1;
              window.setTimeout(type, 34);
            } else {
              cursor.remove();
              window.setTimeout(nextLine, 420);
            }
          };
          type();
        } else {
          terminal.appendChild(renderLine(line));
          const delay = line.className === "t-note" ? 1400 : (line.className === "t-dim" ? 900 : 650);
          window.setTimeout(nextLine, delay);
        }
      };
      nextLine();
    }
  }

  const quickstartTabs = Array.from(document.querySelectorAll(".runtime-tab"));
  const quickstartCode = document.getElementById("qs-code");
  const quickstartPanel = document.getElementById("quickstart-panel");

  function activateQuickstartTab(activeTab, moveFocus = false) {
    quickstartTabs.forEach((tab) => {
      const selected = tab === activeTab;
      tab.setAttribute("aria-selected", selected ? "true" : "false");
      tab.tabIndex = selected ? 0 : -1;
    });
    quickstartCode.textContent = quickstartCommands[activeTab.dataset.adapter];
    quickstartPanel.setAttribute("aria-labelledby", activeTab.id);
    if (moveFocus) activeTab.focus();
  }

  quickstartTabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activateQuickstartTab(tab));
    tab.addEventListener("keydown", (event) => {
      let nextIndex = null;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % quickstartTabs.length;
      if (event.key === "ArrowLeft") nextIndex = (index - 1 + quickstartTabs.length) % quickstartTabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = quickstartTabs.length - 1;
      if (nextIndex !== null) {
        event.preventDefault();
        activateQuickstartTab(quickstartTabs[nextIndex], true);
      }
    });
  });

  function legacyCopy(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    if (!copied) throw new Error("Clipboard copy failed");
  }

  function copyText(text) {
    if (!navigator.clipboard || !navigator.clipboard.writeText) {
      legacyCopy(text);
      return Promise.resolve();
    }
    return navigator.clipboard.writeText(text).catch(() => legacyCopy(text));
  }

  const copyButton = document.getElementById("copyqs");
  if (copyButton && quickstartCode) {
    const idleLabel = copyButton.dataset.idleLabel || "copy";
    const copiedLabel = copyButton.dataset.copiedLabel || "copied";
    copyButton.addEventListener("click", () => {
      const text = quickstartCode.textContent;
      copyText(text).then(() => {
        copyButton.textContent = copiedLabel;
        window.setTimeout(() => { copyButton.textContent = idleLabel; }, 1600);
      });
    });
  }
})();
