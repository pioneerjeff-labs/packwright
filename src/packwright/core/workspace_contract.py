WORKSPACE_ROOT = "workspace"
WORKSPACE_LAYOUT = "domain_first_lifecycle_second"
WORKSPACE_DOMAIN_TEMPLATE_DIR = "workspace/_template"
WORKSPACE_SHARED_DIR = "workspace/shared"
WORKSPACE_INDEX_OWNER = "memory/source-map.md"
WORKSPACE_LIFECYCLE_DIRS = ("drafts", "artifacts", "archive")
WORKSPACE_SHARED_ARTIFACT_DIRS = (
    "workspace/shared/artifacts/handoffs",
    "workspace/shared/artifacts/session-briefs",
)


def workspace_skeleton_paths():
    return tuple(
        f"{WORKSPACE_DOMAIN_TEMPLATE_DIR}/{name}/.gitkeep"
        for name in WORKSPACE_LIFECYCLE_DIRS
    ) + (f"{WORKSPACE_SHARED_DIR}/.gitkeep",) + tuple(
        f"{path}/.gitkeep" for path in WORKSPACE_SHARED_ARTIFACT_DIRS
    )


def workspace_required_dirs():
    return (
        WORKSPACE_ROOT,
        WORKSPACE_DOMAIN_TEMPLATE_DIR,
        *(f"{WORKSPACE_DOMAIN_TEMPLATE_DIR}/{name}" for name in WORKSPACE_LIFECYCLE_DIRS),
        WORKSPACE_SHARED_DIR,
        "workspace/shared/artifacts",
        *WORKSPACE_SHARED_ARTIFACT_DIRS,
    )


def workspace_artifacts():
    return ("workspace/README.md", *workspace_skeleton_paths())


def workspace_files(readme):
    files = {"workspace/README.md": readme}
    files.update({path: "" for path in workspace_skeleton_paths()})
    return files


def workspace_readme():
    return (
        "# Workspace\n\n"
        "Use this directory for generated work products, not durable memory.\n\n"
        "## Directories\n\n"
        "- `workspace/<domain>/drafts/`: temporary drafts, explorations, and working versions.\n"
        "- `workspace/<domain>/artifacts/`: final or reusable deliverables.\n"
        "- `workspace/<domain>/archive/`: old outputs kept for reference.\n"
        "- `workspace/shared/`: cross-domain outputs only.\n"
        "- `workspace/shared/artifacts/handoffs/`: real cross-agent or cross-runtime handoff files.\n"
        "- `workspace/shared/artifacts/session-briefs/`: same-agent next-session preparation files.\n"
        "- `workspace/_template/`: copy when a new workstream needs workspace storage.\n\n"
        "## Rules\n\n"
        "- Keep memory files focused on state, decisions, and pointers.\n"
        "- Index important workspace outputs in `memory/source-map.md`.\n"
        "- Move durable project state into `memory/projects/<slug>.md`, not workspace files.\n"
    )


def workspace_feature():
    return {
        "root": WORKSPACE_ROOT,
        "layout": WORKSPACE_LAYOUT,
        "domain_template": WORKSPACE_DOMAIN_TEMPLATE_DIR,
        "shared": WORKSPACE_SHARED_DIR,
        "shared_artifact_dirs": list(WORKSPACE_SHARED_ARTIFACT_DIRS),
        "lifecycle_dirs": list(WORKSPACE_LIFECYCLE_DIRS),
        "index_owner": WORKSPACE_INDEX_OWNER,
    }


def workspace_spec():
    return {
        "root": WORKSPACE_ROOT,
        "layout": WORKSPACE_LAYOUT,
        "domain_template_dir": WORKSPACE_DOMAIN_TEMPLATE_DIR,
        "shared_dir": WORKSPACE_SHARED_DIR,
        "lifecycle_dirs": list(WORKSPACE_LIFECYCLE_DIRS),
        "index_owner": WORKSPACE_INDEX_OWNER,
        "rules": [
            "Use workspace/<domain>/drafts for temporary generated work.",
            "Use workspace/<domain>/artifacts for durable deliverables the user may reuse.",
            "Use workspace/<domain>/archive for old deliverables kept for reference.",
            "Use workspace/shared only for cross-domain outputs.",
            "Use workspace/shared/artifacts/handoffs for real cross-agent or cross-runtime handoff files.",
            "Use workspace/shared/artifacts/session-briefs for same-agent next-session preparation files.",
            "Index important workspace outputs in memory/source-map.md instead of copying content into memory files.",
        ],
    }


def workspace_readme_required_markers():
    return (
        WORKSPACE_INDEX_OWNER,
        "workspace/<domain>/drafts/",
        "workspace/<domain>/artifacts/",
        "workspace/shared/",
        "workspace/shared/artifacts/handoffs/",
        "workspace/shared/artifacts/session-briefs/",
    )
