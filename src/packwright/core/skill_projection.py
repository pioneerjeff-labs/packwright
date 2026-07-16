import re

import yaml

from .adapter_layout import adapter_capabilities, projected_skill_artifact
from .naming import character_slug
from .path_safety import resolve_mechanism_file


SKILL_CAPABILITIES = {
    "browser",
    "hooks",
    "local-files",
    "mcp",
    "shell",
    "web",
}


def skill_spec(mechanism, skill_id):
    return next(skill for skill in mechanism.get("skills", []) if skill.get("id") == skill_id)


def projected_skill_path(mechanism, adapter, skill):
    return projected_skill_artifact(adapter, character_slug(mechanism), skill["id"])


def skill_projection_records(mechanism, adapter):
    available = set(adapter_capabilities(adapter))
    records = []
    for skill in mechanism.get("skills", []):
        required = set(skill.get("capabilities", []))
        missing = sorted(required - available)
        records.append(
            {
                "id": skill["id"],
                "path": projected_skill_path(mechanism, adapter, skill),
                "status": "projected" if not missing else "unavailable_missing_capabilities",
                "required_capabilities": sorted(required),
                "missing_capabilities": missing,
            }
        )
    return records


def skill_projection_feature(mechanism, adapter):
    records = skill_projection_records(mechanism, adapter)
    return {
        "count": len(records),
        "projected": sum(record["status"] == "projected" for record in records),
        "unavailable": sum(record["status"] != "projected" for record in records),
        "items": records,
    }


def render_skill_projection(mechanism, adapter, skill, body=None):
    if body is None:
        source = resolve_mechanism_file(mechanism, skill["path"])
        body = source.read_text(encoding="utf-8")
    body = _strip_front_matter(body).strip()
    trigger = skill["trigger"].strip()
    slug = character_slug(mechanism)
    if adapter == "cursor":
        front_matter = {
            "description": trigger,
            "alwaysApply": False,
        }
    else:
        front_matter = {
            "name": f"{slug}-{skill['id']}",
            "description": trigger,
        }
    return "---\n" + yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip() + "\n---\n\n" + body + "\n"


def projected_generic_skill_files(mechanism, adapter, excluded_ids=("save-context",)):
    excluded = set(excluded_ids)
    records = {record["id"]: record for record in skill_projection_records(mechanism, adapter)}
    files = {}
    for skill in mechanism.get("skills", []):
        record = records[skill["id"]]
        if skill["id"] in excluded or record["status"] != "projected":
            continue
        files[record["path"]] = render_skill_projection(mechanism, adapter, skill)
    return files


def _strip_front_matter(text):
    return re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.DOTALL)
