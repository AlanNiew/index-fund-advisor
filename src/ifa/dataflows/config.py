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
    """获取当前配置的浅拷贝。

    contextvars 在新线程中默认值为 None（不会被父线程继承），因此这里必须兜底初始化，
    否则工作线程（如 asyncio.to_thread 中执行的数据工具）会读到 None。
    """
    config = _config_var.get()
    if config is None:
        initialize_config()
        config = _config_var.get()
    if config is None:  # 兜底：initialize_config 理论上必然填充，防御性保留
        config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    return config.copy()


initialize_config()
