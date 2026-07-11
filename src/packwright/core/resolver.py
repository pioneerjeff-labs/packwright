import copy
import re
from collections.abc import Mapping, Sequence

from .errors import PackwrightValidationError
from .validation import validate_mechanism


PLACEHOLDER_PATTERN = re.compile(r"{{\s*([A-Za-z0-9_.-]+)\s*}}")


def resolve_mechanism(data, parameters=None):
    """Validate and resolve a character mechanism spec using parameter overrides."""
    validate_mechanism(data)
    values = _resolve_parameter_values(data.get("parameters", {}), parameters or {})
    resolved = _replace_placeholders(copy.deepcopy(data), values)
    resolved["resolved_parameters"] = copy.deepcopy(values)
    validate_mechanism(resolved)
    return resolved
def _resolve_parameter_values(parameter_specs, overrides):
    issues = []
    values = {}

    for name in overrides:
        if name not in parameter_specs:
            issues.append(f"unknown parameter override: {name}")

    for name, spec in parameter_specs.items():
        if name in overrides:
            values[name] = overrides[name]
        elif "default" in spec:
            values[name] = spec["default"]
        elif spec.get("required"):
            issues.append(f"missing required parameter: {name}")
        else:
            values[name] = ""

    if issues:
        raise PackwrightValidationError(issues)
    return values


def _replace_placeholders(value, parameters):
    if isinstance(value, str):
        return _replace_string(value, parameters)
    if isinstance(value, Mapping):
        return {key: _replace_placeholders(item, parameters) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_replace_placeholders(item, parameters) for item in value]
    return value


def _replace_string(value, parameters):
    issues = []

    def replace(match):
        name = match.group(1)
        if name not in parameters:
            issues.append(f"unknown placeholder: {name}")
            return match.group(0)
        return str(parameters[name])

    rendered = PLACEHOLDER_PATTERN.sub(replace, value)
    if issues:
        raise PackwrightValidationError(issues)
    return rendered
