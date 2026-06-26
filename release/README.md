# index-fund-advisor (MCP server)

把中国 A 股**指数基金数据 / 估值**能力通过 [MCP（Model Context Protocol）](https://modelcontextprotocol.io) 暴露给 AI 客户端（Claude Desktop、Claude Code、OpenCode 等），让 AI 在对话里直接查基金、看估值、跑筛选。

> 这是 IFA 项目的**轻量发行版**（v0.1.x）：只含数据 / 估值工具（8 个），不依赖 langchain / langgraph，安装轻量。AI 深度分析（`analyze_fund`）能力将在后续版本加入。

## 安装

```bash
pip install index-fund-advisor
```

或用 `uvx` 直接运行（无需安装）：

```bash
uvx index-fund-advisor
```

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

## 工具（8 个，均不依赖 LLM Key）

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

MIT
