import re
import warnings


SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slugify(value, default="character"):
    text = str(value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if text and not slug:
        warnings.warn(
            f"{value!r} cannot produce an ASCII slug; using {default!r}. "
            "Provide an explicit --slug to avoid collisions.",
            RuntimeWarning,
            stacklevel=2,
        )
    return slug or default


def normalize_slug(value, default="character"):
    return slugify(value, default=default)


def is_valid_slug(value):
    return isinstance(value, str) and bool(SLUG_PATTERN.fullmatch(value))


def character_name(mechanism):
    identity = mechanism.get("identity", {}) if isinstance(mechanism, dict) else {}
    metadata = mechanism.get("metadata", {}) if isinstance(mechanism, dict) else {}
    return identity.get("name") or metadata.get("name") or "Character"


def character_slug(mechanism):
    identity = mechanism.get("identity", {}) if isinstance(mechanism, dict) else {}
    if identity.get("slug"):
        return normalize_slug(identity["slug"])
    metadata = mechanism.get("metadata", {}) if isinstance(mechanism, dict) else {}
    if metadata.get("slug"):
        return normalize_slug(metadata["slug"])
    name = identity.get("name")
    if name:
        return slugify(name)
    return slugify(metadata.get("name"))


def character_user_name(mechanism):
    identity = mechanism.get("identity", {}) if isinstance(mechanism, dict) else {}
    if identity.get("user_name"):
        return identity["user_name"]

    role = identity.get("role", "")
    match = re.match(r"^([^\s'’]+)(?:'s|’s)\b", role)
    if match:
        return match.group(1)
    match = re.match(r"^([^\s的]{1,64})的", role)
    if match:
        return match.group(1)
    return "the user"


def character_voice_summary(mechanism):
    identity = mechanism.get("identity", {}) if isinstance(mechanism, dict) else {}
    return identity.get("voice_summary") or "Calm, direct, perceptive, and lightly warm."


def character_mission(mechanism):
    identity = mechanism.get("identity", {}) if isinstance(mechanism, dict) else {}
    if identity.get("mission"):
        return identity["mission"]
    name = character_name(mechanism)
    user_name = character_user_name(mechanism)
    return f"{name} helps {user_name} preserve intent, notice stale assumptions, and turn messy work into concrete next steps."


def save_context_skill_path(mechanism, adapter):
    from .adapter_layout import save_context_artifact

    slug = character_slug(mechanism)
    return save_context_artifact(adapter, slug)


def reference_prefix(mechanism, adapter):
    from .adapter_layout import adapter_reference_root

    return adapter_reference_root(adapter, character_slug(mechanism))


def durable_memory_source(mechanism):
    return f"{character_slug(mechanism)}_local_files"
