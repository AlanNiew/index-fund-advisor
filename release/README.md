# IFA MCP 轻量发行版（本地打包脚手架，未发布到 PyPI）

> **本项目不发布到 PyPI。** 本目录只是「只含数据 / 估值工具、不依赖 langchain / langgraph」的**本地打包脚手架**（v0.1.x），
> 供确实需要极简 MCP 服务的用户自行构建。正常使用请直接安装主项目。

## 推荐用法：直接用主项目的 MCP server

```bash
git clone https://github.com/AlanNiew/index-fund-advisor.git
cd index-fund-advisor

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[mcp]"
ifa-mcp
```

需要 **Python ≥ 3.12**。主项目的 MCP server 提供 9 个工具（含 `analyze_fund` 深度分析，需要 LLM API Key），详见 [../MCP.md](../MCP.md)。

## 可选：本地构建轻量包

```bash
cd release
python assemble.py        # 从 ../src/ifa 拷贝子集到 release/src/ifa（可传目标目录）
python -m build           # 或 pip install .
```

`release/src/`、`release/dist/` 是生成物，已在 `.gitignore` 中忽略，不要手动编辑。

### 复制范围（改 `assemble.py` 前必读）

| 来源 | 内容 |
| --- | --- |
| 目录 | `mcp/`、`data_tools/`、`dataflows/`（含 `_mini_racer_guard.py` / `_network_guard.py`） |
| 单文件 | `__init__.py`、`default_config.py`、`atomic_io.py`、`env_loader.py`、`providers.py` |

`assemble.py` 复制前会自检「模块顶层 ifa 导入闭包」，漏掉任何一个被引用的模块都会立刻报错退出；
`tests/test_release_package.py` 会独立复算这条闭包，并真正组装一次、用「看不到仓库 src」的解释器
import 一遍（顺带断言没拉起 langchain / langgraph）。历史上这里漏掉过 `env_loader` /
`providers` / `atomic_io` —— 轻量包连 `import ifa.default_config` 都过不去，`ifa-mcp` 根本起不来。

**已知限制**：

- `assemble.py` 刻意排除 `ifa.common` / `ifa.graph` / `ifa.agents`，所以轻量包里的 `analyze_fund` 在**调用时**返回可操作错误（不会崩）；轻量包实际只有下表 8 个数据 / 估值工具可用。
- 它不通过 PyPI 分发；如需完整 MCP 功能，优先用上面的主项目方式。

## 发行：GitHub Release（本项目不发布到 PyPI）

主项目由 `.github/workflows/release.yml` 打包发行：

- 推送 tag `v*` → 构建 wheel + sdist → 在干净 venv 里冒烟（`ifa --help` / `ifa tools --json` /
  随包 skill 与 `ifa.atomic_io` 等共享模块可导入）→ 把产物挂到 GitHub Release。
- `workflow_dispatch` 手动触发 → 只构建并上传 workflow artifact，不发 Release。
- 版本一致性由 workflow 强制：tag 必须等于 `pyproject.toml` 的 `version`（`v0.1.0` ↔ `0.1.0`）。

wheel / 全局安装的能力边界：

| 入口 | wheel 内可用 | 说明 |
| --- | --- | --- |
| `ifa`（CLI） | ✅ | 含 `analyze / screen / portfolio / search / info / backtest / tools / tool / skill / config / validate` |
| `ifa-mcp` | ✅（需 `mcp` 依赖） | `uvx --from <wheel> --with mcp ifa-mcp` |
| `ifa-web` | ❌ | Streamlit 界面在仓库根的 `web/app.py`，wheel 不含 → 直接提示「需要仓库检出」并退出 1 |
| REST API | ❌ | 同上，`api/main.py` 需要仓库检出后 `uvicorn api.main:app` |

## 接入客户端

### Claude Desktop

`claude_desktop_config.json`：

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

### OpenCode

`opencode.json`：

```jsonc
{
  "mcp": {
    "ifa": {
      "type": "local",
      "command": ["ifa-mcp"],
      "enabled": true
    }
  }
}
```

## 工具（8 个数据 / 估值工具，均不依赖 LLM Key）

| 工具 | 说明 |
| --- | --- |
| `search_funds` | 按关键词 / 代码搜索公募基金 |
| `get_fund_info` | 基金基本信息（类型 / 规模 / 经理 / 费率） |
| `get_index_valuation_metrics` | 指数结构化估值指标（PE / PB / ROE / 股息率 / ERP，返回 dict） |
| `get_index_valuation_report` | 指数综合估值报告（含历史百分位） |
| `get_valuation_signal` | 估值信号（买入 / 持有 / 卖出） |
| `screen_index_funds` | 按分类 + 跟踪方式筛选指数基金 |
| `get_index_constituents` | 指数成份股 |
| `get_north_flow` | 北向资金流向（市场情绪） |

数据全部来自 [AkShare](https://akshare.akfamily.xyz/)（东方财富 / 雪球 / 中证指数公司 / 中国债券信息网）。

## 示例

```
查一下沪深300 的 PE 和 ERP
```
```
筛选大盘被动指数基金，前 10 只
```

## 设计

- 直接复用 IFA 数据层（`run_data_tool` / `fetch_valuation_metrics`），不经过 HTTP
- stdio 传输，无单独服务进程
- 阻塞调用用 `asyncio.to_thread` 包装

## License

MIT（见 [LICENSE](LICENSE)）
