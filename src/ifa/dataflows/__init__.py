"""
数据流层：AkShare 接口封装（重试、资产类型识别、统一清洗）。

导入本包时会装上两项全局保护：

- `_mini_racer_guard` —— 串行化 py_mini_racer 的构造（并发构造会让 V8 直接 abort 进程）；
- `_network_guard` —— 给没写 timeout 的 requests 调用补默认超时（AkShare 多个接口
  直接 requests.get(url)，上游不响应时整条分析链会无限期挂住）。
"""

from ._mini_racer_guard import install_mini_racer_guard
from ._network_guard import install_data_source_timeout

install_mini_racer_guard()
install_data_source_timeout()
