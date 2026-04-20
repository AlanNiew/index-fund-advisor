# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

IFA (Index Fund Advisor) 是一个 AI 驱动的中国指数基金分析工具，提供深度分析、基金筛选和组合配置三种分析模式。核心基于 LangGraph 编排多 Agent 工作流，数据源为 AkShare。

## 常用命令

```bash
# 安装（开发模式，含测试工具）
pip install -e ".[dev]"

# CLI 入口
ifa analyze 510300 --date 2024-01-15    # 单只基金深度分析
ifa screen --query "大盘低波动" --top 10 # 基金筛选
ifa portfolio --risk moderate            # 组合配置建议
ifa search 沪深300                       # 快速搜索（不经过 LLM）
ifa info 510300                          # 基金基本信息（不经过 LLM）
ifa config                               # 查看当前配置

# Web 界面
ifa-web    # 启动 Streamlit（streamlit run web/app.py）

# API 服务
ifa-api    # 启动 FastAPI（uvicorn api.main:app --host 0.0.0.0 --port 8000）

# 代码质量
ruff check .          # lint
ruff format .         # 格式化
mypy src              # 类型检查
pytest                # 测试（tests/ 目录，目前为空）
```

## 架构

### 三种分析模式的工作流（LangGraph）

所有模式由 `AdvisorGraph`（`src/ifa/graph/advisor_graph.py`）编排，共享统一的 `IFAdvisorState` 状态：

1. **deep** — `Fund Analyst → Index Analyst? → Report Generator`
   - Index Analyst 仅在资产类型为 ETF/指数基金时执行（条件边 `should_skip_index_analyst`）
2. **screen** — `Fund Screener → Fund Analyst → Report Generator`
3. **portfolio** — `Portfolio Advisor(R1) → Fund Screener → Fund Analyst → Portfolio Advisor(R2) → Report Generator`

每种模式使用两个 LLM：`quick_llm`（工具调用/分析）和 `deep_llm`（报告生成/深度推理）。

### 分层结构

- **Agent 层** (`src/ifa/agents/`) — LangGraph ReAct Agent，每个 Agent 拥有独立的 ToolNode
  - `analysts/` — fund_analyst（12 个数据工具）、index_analyst（4 个工具）、fund_screener（5 个工具）
  - `managers/` — portfolio_advisor、report_generator
  - `tools/` — 两类数据工具：`public_fund_tools`（公募基金）和 `etf_index_tools` / `constituent_tools`（ETF/指数）
- **数据工具层** (`src/ifa/data_tools/`) — 带缓存的工具执行引擎，`api.py` 的 `run_data_tool()` 是统一入口
- **数据流层** (`src/ifa/dataflows/`) — AkShare API 封装，含重试逻辑和资产类型自动检测
- **LLM 客户端层** (`src/ifa/llm_clients/`) — 工厂模式，支持 openai/azure/anthropic/google/ollama/openrouter/qwen/xai/zhipu
- **图编排层** (`src/ifa/graph/`) — LangGraph StateGraph 构建 + 条件边逻辑
- **接口层** — `cli/`（Typer）、`web/`（Streamlit）、`api/`（FastAPI 异步任务）

### 配置系统

- `src/ifa/default_config.py` — 默认配置 + 运行时配置构建
- CLI 通过 `save_last_config()` 持久化到 `src/ifa/last_config.py`
- 环境变量 `.env` 存放 API Key（参考 `.env.example`）
- `IFA_LOCAL_DATA_DIR` 可覆盖本地数据目录

### 关键约定

- 包布局：顶层有 `cli/`、`api/`、`web/`、`src/ifa/` 四个独立包，`setuptools` 通过 `[tool.setuptools.packages.find]` 将它们全部纳入
- 内部语言为英文，最终输出为中文
- Ruff 规则：忽略 E501（行长度）、F403/F405（星号导入）、E402（模块级导入顺序）
- `isort.known-first-party`：`["ifa", "api", "cli", "web"]`
