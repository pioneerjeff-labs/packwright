from pathlib import Path

import yaml

from .errors import PackwrightValidationError


def load_mechanism(path):
    """Load a character mechanism YAML document from disk.

    A directory input resolves to `<directory>/mechanism.yaml`.
    """
    input_path = Path(path)
    mechanism_path = input_path / "mechanism.yaml" if input_path.is_dir() else input_path
    try:
        raw = mechanism_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PackwrightValidationError([f"cannot read mechanism file {mechanism_path}: {exc}"])

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PackwrightValidationError([f"invalid YAML in {mechanism_path}: {exc}"])

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise PackwrightValidationError([f"mechanism root must be a mapping in {mechanism_path}"])

    data = dict(data)
    data["source"] = {
        "path": str(mechanism_path),
        "base_dir": str(mechanism_path.parent),
    }
    return data
