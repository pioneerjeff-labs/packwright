import re

from .path_safety import resolve_mechanism_file


_ATX_HEADING = re.compile(r"^(#{1,6})(\s+.*)$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


def entry_working_rule_lines(mechanism, fallback):
    """Render canonical operating principles inside an entry Working Rules section."""
    rel_path = mechanism.get("operating", {}).get("principles_path")
    if not rel_path:
        return list(fallback)
    try:
        text = resolve_mechanism_file(mechanism, rel_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return list(fallback)
    body = _without_primary_heading(text)
    if not body.strip():
        return list(fallback)
    return _demote_headings(body.rstrip().splitlines())


def _without_primary_heading(text):
    lines = text.lstrip("\ufeff").splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if re.match(r"^#\s+", line):
            del lines[index]
        break
    return "\n".join(lines).strip()


def _demote_headings(lines):
    output = []
    fence = None
    for line in lines:
        marker = _FENCE.match(line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token[0]
            elif token[0] == fence:
                fence = None
            output.append(line)
            continue
        match = _ATX_HEADING.match(line) if fence is None else None
        if match:
            hashes, suffix = match.groups()
            line = f"{hashes}#{suffix}" if len(hashes) < 6 else line
        output.append(line)
    return output
