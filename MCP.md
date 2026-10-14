# IFA MCP Server

把 IFA 的**基金数据查询 / 估值 / AI 分析**能力通过 [MCP（Model Context Protocol）](https://modelcontextprotocol.io) 暴露给 AI 客户端（Claude Desktop、Claude Code、OpenCode 等），让 AI 在对话里直接查基金、看估值、跑分析。

- 实现代码：[`src/ifa/mcp/server.py`](src/ifa/mcp/server.py)
- 传输方式：**stdio**（本地子进程，无需单独起服务）
- 依赖：`mcp`（Python SDK / FastMCP），通过可选额外依赖安装

---

## 安装

```bash
pip install -e ".[mcp]"
```

安装后会注册 `ifa-mcp` 命令行入口，同时 `ifa.mcp` 子包可被 `python -m ifa.mcp.server` 直接启动。

全局安装（`uv tool install --from git+https://github.com/AlanNiew/index-fund-advisor.git ifa`）时不需要仓库目录：
MCP server 与 CLI 一样走 `ifa.env_loader.load_env_files()`，会**同时**读取工作目录向上找到的 `.env` 与用户级 `.env`
（`IFA_CONFIG_DIR` → `%APPDATA%\ifa\.env`），因此 Key 放用户级 `.env` 即可。

---

## 暴露的工具（共 9 个）

| 工具 | 作用 | 参数 | 返回 | 需 LLM Key |
| --- | --- | --- | --- | --- |
| `search_funds` | 按关键词 / 代码搜索公募基金 | `query: str=""`, `limit: int=20` | `{query, results: list[str], total}` | 否 |
| `get_fund_info` | 基金基本信息（类型/规模/经理/费率） | `code: str` | `{fund_code, data: str}` | 否 |
| `get_index_valuation_metrics` | 指数结构化估值指标 | `index_name: str="沪深300"` | dict：`pe_ttm/pb/roe/dividend_yield/earnings_yield/risk_free_rate/erp/date` | 否 |
| `get_index_valuation_report` | 指数综合估值报告（含历史百分位） | `index_name: str="沪深300"` | str（Markdown） | 否 |
| `get_valuation_signal` | 估值信号（买入/持有/卖出） | `index_name: str="沪深300"` | str | 否 |
| `screen_index_funds` | 按分类+跟踪方式筛选指数基金 | `index_category="全部"`, `tracking_method="全部"` | str（CSV） | 否 |
| `get_index_constituents` | 指数成份股 | `index_name: str` | str | 否 |
| `get_north_flow` | 北向资金流向（市场情绪） | `symbol: str="北向资金"` | str | 否 |
| `analyze_fund` | 单基金 AI 深度分析 | `code: str`, `analysis_date=""`, `mode="deep_simple"` | `{fund_code, mode, final_rating, final_confidence, final_report, error}` | **是** |

**参数取值说明**

- `screen_index_funds.index_category`：`全部` / `沪深指数` / `行业主题` / `大盘指数` / `中盘指数` / `小盘指数`
- `screen_index_funds.tracking_method`：`全部` / `被动指数型` / `增强指数型`
- `analyze_fund.mode`：`deep_simple`（快速，~30-60 秒）/ `deep`（含看涨/看跌辩论，~1-3 分钟）

> 数据 / 估值工具走 AkShare 公开数据，**无需任何 Key**；只有 `analyze_fund` 需要在 `.env` 配置有效的 LLM API Key（默认提供方为 OpenCode Go，需 `OPENCODE_API_KEY`；可用 `IFA_LLM_PROVIDER` 切换）。

---

## 接入客户端

### Claude Desktop

配置文件路径：
- macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows：`%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ifa": { "command": "ifa-mcp" }
  }
}
```

### Claude Code

```bash
claude mcp add ifa -- ifa-mcp
```

### OpenCode（Windows 推荐）

在 `opencode.json`（项目根或 `~/.config/opencode/opencode.json`）的 `mcp` 段加入：

```jsonc
{
  "mcp": {
    "ifa": {
      "type": "local",
      "command": ["python", "-m", "ifa.mcp.server"],
      "cwd": "D:/Programing/PythonProjects/index-fund-advisor",
      "enabled": true
    }
  }
}
```

> Windows 下用 `["python", "-m", "ifa.mcp.server"]` 比 `["ifa-mcp"]` 更稳——直接跑模块，绕开 `.exe` 壳的 spawn 问题（`server.py` 含 `__main__` 守卫）。
> `cwd` 指向 IFA 项目根，使 `analyze_fund` 能读到 `.env` 里的 LLM Key。

---

## 使用示例

接入后，在 AI 客户端里直接用自然语言驱动：

```
查一下沪深300 的 PE、ERP 和估值信号
```
→ 命中 `get_index_valuation_metrics` + `get_valuation_signal`

```
筛选大盘被动指数基金，给我前 10 只
```
→ 命中 `screen_index_funds`

```
分析一下 510300，用快速模式
```
→ 命中 `analyze_fund(code="510300", mode="deep_simple")`

**真实返回样例**（`get_index_valuation_metrics("沪深300")`，2026-06-25 实测）：

```json
{
  "index_name": "沪深300",
  "date": "2026-06-25",
  "pe_ttm": 13.98,
  "pb": 1.47,
  "roe": 10.52,
  "dividend_yield": 2.47,
  "earnings_yield": 7.15,
  "risk_free_rate": 1.74,
  "erp": 5.42
}
```

---

## 设计说明

- **直接复用 IFA 既有层，不包 HTTP、不重复实现**
  - 数据工具 → [`ifa.data_tools.api.run_data_tool`](src/ifa/data_tools/api.py)（声明式注册表，36 个数据工具）
  - 结构化估值 → [`ifa.dataflows.a_share_macro.fetch_valuation_metrics`](src/ifa/dataflows/a_share_macro.py)
  - AI 分析 → [`ifa.common.build_advisor`](src/ifa/common.py) / `build_state` + `AdvisorGraph.run`
- **异步包装**：底层调用都是同步阻塞（AkShare 网络 / LLM），用 `asyncio.to_thread`（Python 3.10+ 自带）包到线程池，不卡事件循环，**无新依赖**。
- **健壮性继承**：`analyze_fund` 复用 `AdvisorGraph.run()` 的顶层异常保护，失败时返回 `error` 字段而非抛异常；估值指标在数据源头清洗 NaN/inf。
- **stdio 传输**：MCP `initialize` 握手已实测通过，返回 `serverInfo: IFA - Index Fund Advisor`。

---

## 故障排查

| 症状 | 原因 / 修复 |
| --- | --- |
| 客户端报「找不到 python」 | `command` 第一项换成 python 全路径，如 `D:/Programing/devEnvironment/python3.13/python.exe` |
| Windows 下 `ifa-mcp` spawn 失败 | 改用 `["python", "-m", "ifa.mcp.server"]` |
| `analyze_fund` 报 401 / Key 错误 | `.env` 未加载：设置 `cwd` 指向 IFA 项目根，或在配置里加 `"environment": {"DEEPSEEK_API_KEY": "..."}`（按实际配置的提供方填对应 Key） |
| 数据工具返回错误文本 | 多为 AkShare 网络/限流；重试即可，底层有 3 次指数退避 |
| 工具调用超时 | `analyze_fund` 深度模式可达数分钟；数据工具若卡住通常是网络问题 |

---

## 扩展

**加一个新工具**：在 [`src/ifa/mcp/server.py`](src/ifa/mcp/server.py) 里仿照现有模式加一个 `@mcp.tool()` 装饰的 async 函数，复用 `run_data_tool` / `fetch_valuation_metrics` 即可：

```python
@mcp.tool()
async def get_fund_holdings(code: str) -> str:
    """基金股票持仓。"""
    return await _run_data_tool("get_fund_stock_holdings", symbol=code)
```

可复用的数据工具全名单见 [`src/ifa/data_tools/builtin.py`](src/ifa/data_tools/builtin.py) 的 `_TOOL_SPECS`。

**后续路线**

- v1 只暴露了「数据 + 估值 + 单基金轻量分析」。后续可补：
  - `analyze_portfolio` —— 组合配置分析（需 Key，~2-4 分钟）
  - `screen_funds` —— 自然语言筛选 + 辩论（需 Key，~1-2 分钟）
  - HTTP/SSE 传输 —— 远程共享给多客户端时启用
