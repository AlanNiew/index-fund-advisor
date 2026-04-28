import contextvars
import copy

import ifa.default_config as default_config

_config_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar("ifa_config", default=None)


def initialize_config():
    if _config_var.get() is None:
        _config_var.set(copy.deepcopy(default_config.DEFAULT_CONFIG))


def set_config(config: dict):
    current = _config_var.get()
    if current is None:
        current = copy.deepcopy(default_config.DEFAULT_CONFIG)
    current.update(config)
    _config_var.set(current)


def get_config() -> dict:
    if _config_var.get() is None:
        initialize_config()
    return _config_var.get().copy()


initialize_config()
