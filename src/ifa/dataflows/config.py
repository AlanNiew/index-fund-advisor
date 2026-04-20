import ifa.default_config as default_config

# 使用默认配置，并允许后续覆写
_config: dict | None = None


def initialize_config():
    """
    使用默认值初始化配置。

    返回：
        None: 无返回值。
    """
    global _config
    if _config is None:
        _config = default_config.DEFAULT_CONFIG.copy()


def set_config(config: dict):
    """
    使用自定义值更新配置。

    参数：
        config: 运行时配置映射。

    返回：
        None: 无返回值。
    """
    global _config
    if _config is None:
        _config = default_config.DEFAULT_CONFIG.copy()
    _config.update(config)


def get_config() -> dict:
    """
    获取当前配置。

    返回：
        Dict: 当前查询结果。
    """
    if _config is None:
        initialize_config()
    return _config.copy()


# 使用默认配置初始化
initialize_config()
