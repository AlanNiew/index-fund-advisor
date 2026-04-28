import contextvars

import ifa.default_config as default_config

_config_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar("ifa_config", default=None)


def initialize_config():
    """使用默认值初始化配置。"""
    if _config_var.get() is None:
        _config_var.set(default_config.DEFAULT_CONFIG.copy())


def set_config(config: dict):
    """使用自定义值更新配置。"""
    current = _config_var.get()
    if current is None:
        current = default_config.DEFAULT_CONFIG.copy()
    current.update(config)
    _config_var.set(current)


def get_config() -> dict:
    """获取当前配置。"""
    if _config_var.get() is None:
        initialize_config()
    return _config_var.get().copy()


initialize_config()
