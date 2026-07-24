import json

from .codex import compile_to_agents_md_pack


ADAPTER_NAME = "pi"


def compile_to_pi_pack(mechanism, references=None):
    """Compile a resolved character mechanism into a Pi Core adapter pack."""
    pack = compile_to_agents_md_pack(
        mechanism,
        ADAPTER_NAME,
        references=references,
    )
    manifest = json.loads(pack["manifest.json"])
    manifest["features"]["project_trust"] = {
        "required_for_project_resources": True,
        "status": "requires_runtime_confirmation",
        "resources": [".agents/skills/"],
        "interactive_activation": "/trust",
        "non_interactive_activation": "pi --approve",
    }
    manifest["boundaries"]["pi_extensions"] = "not_projected"
    manifest["boundaries"]["mcp"] = "unavailable_no_builtin_mcp"
    pack["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    return pack
