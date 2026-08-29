"""Static registry for Packwright-managed local sidecars."""


_DRIVER_MODULES = {"emotion-engine": ".emotion_engine"}


def supported_sidecars():
    return tuple(sorted(_DRIVER_MODULES))


def get_sidecar_driver(sidecar_id, **kwargs):
    try:
        module_name = _DRIVER_MODULES[sidecar_id]
    except KeyError as exc:
        raise ValueError(f"unsupported sidecar: {sidecar_id}") from exc
    if module_name == ".emotion_engine":
        from .emotion_engine import EmotionEngineDriver

        driver = EmotionEngineDriver
    return driver(**kwargs)


__all__ = [
    "get_sidecar_driver",
    "supported_sidecars",
]
