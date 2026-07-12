(() => {
  "use strict";

  const lines = [
    { className: "cmd", text: "python -m pip install packwright==0.1.0rc1" },
    { className: "t-ok", text: "  ✓ installed packwright 0.1.0rc1" },
    { className: "cmd", text: "packwright init --template creator -o work/mira" },
    { className: "cmd", text: "packwright build work/mira --adapter claude-code -o pack/mira-claude" },
    { className: "t-ok", text: "  ✓ pack compiled · checker score 100.0" },
    { className: "cmd", text: "packwright install pack/mira-claude --adapter claude-code --target project/mira-claude" },
    { className: "t-ok", text: "  ✓ installed native Claude Code target" },
    { className: "t-dim", text: "# the same agent has lived in Claude Code for months — carry it to Codex" },
    { className: "cmd", text: "packwright migrate project/mira-claude --to codex --target project/mira-codex --dry-run" },
    { className: "t-fg", text: "  would carry:   memory/** · workspace/** · knowledge/** · sources/**" },
    { className: "t-note", text: "  would exclude: CLAUDE.md · .claude/** · no files written" },
    { className: "cmd", text: "packwright migrate project/mira-claude --to codex --target project/mira-codex --yes" },
    { className: "t-ok", text: "  ✓ carried hashes verified · installed score 100.0" },
    { className: "t-dim", text: "# the output is files you can read" },
  ];
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

  const copyButton = document.getElementById("copyqs");
  if (copyButton) {
    copyButton.addEventListener("click", () => {
      const text = document.getElementById("qs-code").textContent;
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
          copyButton.textContent = "copied";
          window.setTimeout(() => { copyButton.textContent = "copy"; }, 1600);
        });
      }
    });
  }
})();
