ADAPTER_LAYOUTS = {
    "codex": {
        "entry": "AGENTS.md",
        "skill_root": ".agents/skills",
        "legacy_skill_roots": (".codex/skills",),
    },
    "claude-code": {
        "entry": "CLAUDE.md",
        "skill_root": ".claude/skills",
        "legacy_skill_roots": (),
    },
    "cursor": {
        "entry": ".cursor/rules/<slug>.mdc",
        "skill_root": ".cursor/rules",
        "legacy_skill_roots": (),
    },
}


def adapter_entry(adapter, slug="<slug>"):
    return ADAPTER_LAYOUTS[adapter]["entry"].replace("<slug>", slug)


def adapter_skill_root(adapter):
    return ADAPTER_LAYOUTS[adapter]["skill_root"]


def legacy_skill_roots(adapter):
    return ADAPTER_LAYOUTS[adapter]["legacy_skill_roots"]


def save_context_artifact(adapter, slug):
    root = adapter_skill_root(adapter)
    suffix = ".mdc" if adapter == "cursor" else "/SKILL.md"
    return f"{root}/{slug}-save-context{suffix}"
