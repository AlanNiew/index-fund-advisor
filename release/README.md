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
python assemble.py        # 从 ../src/ifa 拷贝 mcp/ + data_tools/ + dataflows/ 子集到 release/src/
python -m build           # 或 pip install .
```

`release/src/`、`release/dist/` 是生成物，已在 `.gitignore` 中忽略，不要手动编辑。

**已知限制（该脚手架尚未随主项目验证过，`release/src` / `release/dist` 从未生成）**：

- `assemble.py` 刻意排除 `ifa.common` / `ifa.graph` / `ifa.agents`，所以轻量包里的 `analyze_fund` 在**调用时会失败**；轻量包实际只有下表 8 个数据 / 估值工具可用。
- 它不通过 PyPI 分发，也没有 CI 覆盖；如需 MCP 功能，优先用上面的主项目方式。

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
