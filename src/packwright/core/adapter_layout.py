import yaml


ADAPTER_LAYOUTS = {
    "codex": {
        "display_name": "Codex",
        "entry": "AGENTS.md",
        "pack_kind": "CodexAdapterPack",
        "skill_root": ".agents/skills",
        "skill_artifact": "{slug}-{skill_id}/SKILL.md",
        "legacy_skill_roots": (".codex/skills",),
        "reference_root": ".codex/<slug>/references",
        "lifecycle": "project_guidance",
        "capabilities": ("local-files", "mcp", "shell", "skills"),
        "guidance_kind": "skill",
        "emotion_engine_runtime": "optional_project_mcp_sidecar",
    },
    "claude-code": {
        "display_name": "Claude Code",
        "entry": "CLAUDE.md",
        "pack_kind": "ClaudeCodeAdapterPack",
        "skill_root": ".claude/skills",
        "skill_artifact": "{slug}-{skill_id}/SKILL.md",
        "legacy_skill_roots": (),
        "reference_root": ".claude/<slug>/references",
        "lifecycle": "SessionStart",
        "capabilities": ("hooks", "local-files", "mcp", "shell", "skills"),
        "guidance_kind": "skill",
        "emotion_engine_runtime": "optional_project_mcp_sidecar",
    },
    "cursor": {
        "display_name": "Cursor",
        "entry": ".cursor/rules/<slug>.mdc",
        "pack_kind": "CursorAdapterPack",
        "skill_root": ".cursor/rules",
        "skill_artifact": "{slug}-{skill_id}.mdc",
        "legacy_skill_roots": (),
        "reference_root": ".cursor/<slug>/references",
        "lifecycle": "project_rules",
        "capabilities": ("local-files", "mcp", "rules", "shell"),
        "guidance_kind": "rule",
        "emotion_engine_runtime": "optional_project_mcp_sidecar",
    },
}


def supported_adapters():
    return tuple(ADAPTER_LAYOUTS)


def adapter_contract(adapter):
    try:
        return ADAPTER_LAYOUTS[adapter]
    except KeyError as exc:
        raise ValueError(f"unsupported adapter: {adapter}") from exc


def adapter_entry(adapter, slug="<slug>"):
    return adapter_contract(adapter)["entry"].replace("<slug>", slug)


def adapter_skill_root(adapter):
    return adapter_contract(adapter)["skill_root"]


def legacy_skill_roots(adapter):
    return adapter_contract(adapter)["legacy_skill_roots"]


def adapter_pack_kind(adapter):
    return adapter_contract(adapter)["pack_kind"]


def adapter_reference_root(adapter, slug="<slug>"):
    return adapter_contract(adapter)["reference_root"].replace("<slug>", slug)


def adapter_lifecycle(adapter):
    return adapter_contract(adapter)["lifecycle"]


def adapter_capabilities(adapter):
    return adapter_contract(adapter)["capabilities"]


def adapter_display_name(adapter):
    return adapter_contract(adapter)["display_name"]


def adapter_guidance_kind(adapter):
    return adapter_contract(adapter)["guidance_kind"]


def adapter_emotion_engine_runtime(adapter):
    return adapter_contract(adapter)["emotion_engine_runtime"]


def save_context_artifact(adapter, slug):
    return projected_skill_artifact(adapter, slug, "save-context")


def projected_skill_artifact(adapter, slug, skill_id):
    contract = adapter_contract(adapter)
    artifact = contract["skill_artifact"].format(slug=slug, skill_id=skill_id)
    return f"{contract['skill_root']}/{artifact}"


def render_adapter_capabilities(adapter, slug):
    contract = adapter_contract(adapter)
    return yaml.safe_dump(
        {
            "schema": "packwright-adapter-capabilities/v1",
            "adapter": adapter,
            "entry": adapter_entry(adapter, slug),
            "skill_root": contract["skill_root"],
            "reference_root": adapter_reference_root(adapter, slug),
            "lifecycle_projection": contract["lifecycle"],
            "capabilities": list(contract["capabilities"]),
            "emotion_engine_runtime": contract["emotion_engine_runtime"],
        },
        sort_keys=False,
    )


def render_ownership_contract(adapter, durable_memory_source):
    return yaml.safe_dump(
        {
            "schema": "packwright-ownership-contract/v1",
            "adapter": adapter,
            "core_owns": [
                "identity",
                "voice",
                "operating_boundaries",
                "memory_policy",
                "skill_semantics",
            ],
            "adapter_owns": [
                "file_layout",
                "platform_entry_rendering",
                "platform_skill_rendering",
                "platform_manifest",
            ],
            "runtime_owns": {
                "model_loop": True,
                "thread_state": True,
                "tools": True,
                "lifecycle": adapter_lifecycle(adapter),
            },
            "durable_memory_source_of_truth": durable_memory_source,
            "rules": [
                "Adapters may project character semantics but must not change them.",
                "Generated runtime files do not own durable character memory.",
                "A missing platform capability must not be faked.",
            ],
        },
        sort_keys=False,
    )
