# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

IFA (Index Fund Advisor) 是一个 AI 驱动的中国指数基金分析工具，借鉴 TradingAgents 框架的多智能体辩论架构，提供深度分析、基金筛选和组合配置四种分析模式。核心基于 LangGraph 编排多 Agent 工作流，数据源为 AkShare。

## 常用命令

```bash
# 安装（开发模式，含测试工具）
pip install -e ".[dev]"

# CLI 入口
ifa analyze 510300 --date 2024-01-15    # 单只基金深度分析（含辩论）
ifa screen --query "大盘低波动" --top 10 # 基金筛选（含辩论）
ifa portfolio --risk moderate            # 组合配置建议（含风险辩论）
ifa search 沪深300                       # 快速搜索（不经过 LLM）
ifa info 510300                          # 基金基本信息（不经过 LLM）
ifa config                               # 查看当前配置

# Web 界面
ifa-web    # 启动 Streamlit（内部通过 subprocess 调用 streamlit run web/app.py）

# API 服务（注意：无注册的 ifa-api 脚本，需直接调用 uvicorn）
uvicorn api.main:app --host 0.0.0.0 --port 8000

# 代码质量
ruff check .          # lint
ruff format .         # 格式化
mypy src              # 类型检查
pytest                # 全部测试（148 个，覆盖 8 个模块）
pytest tests/test_core.py::TestBacktestEngine::test_max_drawdown   # 运行单个测试
pytest -x             # 遇到第一个失败即停止
```

## 架构

### 四种分析模式的工作流（LangGraph）

所有模式由 `AdvisorGraph`（`src/ifa/graph/advisor_graph.py`）编排，共享统一的 `IFAdvisorState` 状态：

1. **deep**（含辩论）— `Fund Analyst → Index Analyst? → Bull/Bear 辩论循环 → Research Manager → Report Generator`
   - Index Analyst 仅在资产类型为 ETF/指数基金时执行（条件边 `should_skip_index_analyst`）
   - Bull/Bear 研究员进行多轮对抗辩论（默认 2 轮），Research Manager 裁决
2. **deep_simple**（无辩论）— `Fund Analyst → Index Analyst? → Report Generator`
   - 向后兼容模式，通过 `enable_debate: false` 或指定 `deep_simple` 启用
3. **screen**（含辩论）— `Fund Screener → Fund Analyst → Bull/Bear 辩论循环 → Research Manager → Report Generator`
4. **portfolio**（含风险辩论）— `Portfolio Advisor(R1) → Fund Screener → Fund Analyst → Portfolio Advisor(R2) → 积极/保守/中立 风险辩论 → Portfolio Manager → Report Generator`

每种模式使用两个 LLM：`quick_llm`（工具调用/辩论）和 `deep_llm`（报告生成/关键决策裁决）。

### 共享初始化（`src/ifa/common.py`）

CLI / Web / API 三个接口层共用四个函数：

- `build_advisor()` — 根据配置创建 `AdvisorGraph`（含 LLM 客户端初始化）
- `build_state()` — 通过 `Propagator` 构建初始状态字典
- `save_report()` — 将最终报告保存为 Markdown
- `get_provider_kwargs()` — 将配置转为 LLM 提供方专属参数（如 Google thinking、OpenAI reasoning_effort、Anthropic effort）

### 分层结构

- **Agent 层** (`src/ifa/agents/`) — LangGraph ReAct Agent，每个 Agent 拥有独立的 ToolNode
  - `analysts/` — fund_analyst（18 个数据工具）、index_analyst（11 个工具）、fund_screener（7 个工具）
  - `researchers/` — bull_researcher（看涨研究员）、bear_researcher（看跌研究员），带记忆的对抗辩论
  - `managers/` — portfolio_advisor、research_manager（研究经理裁决）、portfolio_manager（最终决策）、report_generator（整合辩论裁决生成报告）
  - `risk_mgmt/` — aggressive_debator（积极）、conservative_debator（保守）、neutral_debator（中立），三方风险辩论
  - `tools/` — 四类数据工具：`public_fund_tools`（20）、`macro_tools`（8）、`etf_index_tools`（5）、`constituent_tools`（3）
  - `memory.py` — 基于 BM25 的金融情景记忆模块，中英混合分词（中文按字/英文按词），FIFO 淘汰（默认上限 100 条）
  - `prompts/` — Agent prompt 模板，分离自 Agent 实现代码
- **图编排层** (`src/ifa/graph/`) — 模块化图编排（借鉴 TradingAgents）
  - `advisor_graph.py` — 主编排类 `AdvisorGraph`，负责图构建、运行、日志、反思
  - `conditional_logic.py` — 条件边控制（工具循环 + 辩论循环 + 风险辩论循环）
  - `propagation.py` — 状态初始化 (`Propagator`) 和图传播参数
  - `reflection.py` — 决策反思模块 (`Reflector`)，基于实际收益更新记忆
  - `signal_processing.py` — 信号处理 (`SignalProcessor`)，提取标准化评级（含合法性校验和模糊匹配 fallback）
- **数据工具层** (`src/ifa/data_tools/`) — 声明式注册表模式
  - `builtin.py` 定义 `_TOOL_SPECS` 列表（25 个工具的 name/handler/description 三元组），`create_default_data_tool_registry()` 一次性注册
  - `executor.py` 的 `CachedDataToolExecutor` 提供缓存（SHA1 键含参数哈希）和快照
  - 所有工具通过 `route_to_vendor()` 路由到具体数据源
- **数据流层** (`src/ifa/dataflows/`) — AkShare API 封装，含重试逻辑和资产类型自动检测
  - `data_cleaning.py` — 统一清洗管道（`clean_dataframe`: datetime 解析 → 类型转换 → ffill/bfill）和报告截断（`truncate_report`）
- **LLM 客户端层** (`src/ifa/llm_clients/`) — 工厂模式（`create_llm_client`），`OpenAIClient` 统一兼容 OpenAI 协议的多个提供方（openai/azure/ollama/openrouter/xai/qwen/zhipu/deepseek），另有 Anthropic/Google 独立客户端
- **接口层** — `src/ifa/cli/`（Typer，作为 `ifa` 包子模块）、`web/`（Streamlit 多页应用，含 Plotly 图表）、`api/`（FastAPI 异步任务 + API Key 认证）
- **回测引擎** (`src/ifa/backtest/`) — 买入-持有策略回测，`run_backtest()` 输出年化收益、最大回撤、Sharpe、月度收益、净值曲线
- **可观测性** (`src/ifa/observability/`) — 轻量级 per-request tracing，`RequestTracer` 自动追踪 `AdvisorGraph.run()` 执行，日志保存到 `results/traces/`
- **组合模型** (`src/ifa/portfolio/`) — `RiskProfile` 数据模型（4 种风险偏好）+ 资产配置策略描述

### 状态模型

定义在 `src/ifa/agents/types.py`：

- **`IFAdvisorState(MessagesState)`** — 主状态，包含输入（fund_codes、analysis_date、mode、risk_profile）、分析结果（fund_analysis_report、index_analysis_report、portfolio_advice）、辩论状态（fund_debate_state、risk_debate_state）、最终输出（final_report、final_rating、final_confidence）
- **`FundDebateState`** — 基金研究辩论状态（bull_history、bear_history、history、current_response、count、judge_decision）
- **`RiskDebateState`** — 风险辩论状态（aggressive/conservative/neutral 三方 history 和 current_response、latest_speaker、count、judge_decision）

### 辩论机制

- **基金辩论**（deep/screen 模式）：Bull/Bear 交替发言，默认 2 轮（`max_debate_rounds`），终止条件 `count >= 2 * max_debate_rounds`，Research Manager 裁决
- **风险辩论**（portfolio 模式）：Aggressive → Conservative → Neutral 轮流发言，默认 2 轮（`max_risk_discuss_rounds`），终止条件 `count >= 3 * max_risk_discuss_rounds`，Portfolio Manager 裁决
- 裁决结果通过 `_extract_debate_judgment()` 传递给 Report Generator

### 记忆与反思系统

- 每个 Agent 可携带 `FinancialSituationMemory` 实例，基于 BM25 检索历史相似情景
- `_tokenize()` 使用中英混合分词：中文按字拆分（每个汉字独立 token），英文/数字按词拆分
- `add_situations()` 带 FIFO 淘汰机制（默认上限 100 条，可配置 `max_situations`）
- `Reflector` 在决策后根据实际收益/亏损反思并更新各 Agent 的记忆（`reflect_and_remember()`）
- `Reflector.reflect_all()` 按模式条件性反思：deep_simple 跳过，portfolio 额外反思 risk_debate

### 日志系统

- 每次运行自动保存结构化 JSON 日志到 `results/{fund_codes}/ifa_logs/state_log_{date}_{mode}.json`
- 日志包含完整的分析报告、辩论历史、裁决结果

### 配置系统

- `src/ifa/default_config.py` — 默认配置 + `build_runtime_config()` 运行时配置构建
- CLI 通过 `save_last_config()` 持久化到 `src/ifa/last_config.py`
- 环境变量 `.env` 存放 API Key（参考 `.env.example`，支持 OPENAI/AZURE/ANTHROPIC/GOOGLE/ZHIPUAI/DEEPSEEK）
- `IFA_LOCAL_DATA_DIR` 可覆盖本地数据目录
- 辩论相关配置：`enable_debate`（开关）、`max_debate_rounds`（研究辩论轮数，默认 2）、`max_risk_discuss_rounds`（风险辩论轮数，默认 2）

### 健壮性模式

项目已建立的错误处理约定，修改代码时应遵循：

- **LLM 调用统一走 `invoke_llm_safely()` / `invoke_chain_safely()`** — 定义在 `src/ifa/agents/utils.py`，带指数退避重试。所有 Agent 和图模块中的 LLM 调用都必须使用它，禁止裸调用 `llm.invoke()`
- **`run()` 顶层异常保护** — `AdvisorGraph.run()` 用 try/except 包裹 `graph.invoke()`，失败时仍保存日志并返回含 `error` 字段的状态
- **缓存操作异常隔离** — `CachedDataToolExecutor` 的缓存读写和快照保存均有 try/except，磁盘故障时降级为直接执行
- **vendor fallback 链** — `route_to_vendor()` 对每个供应商用 try/except，失败时自动尝试下一个
- **安全字典访问** — 所有 Agent 节点使用 `.get()` + `isinstance` 检查访问嵌套状态；`_safe_get_nested()` 用于日志；`Reflector._safe_get_debate()` 用于反思
- **Prompt 长度限制** — Agent 中输入的分析报告通过 `truncate_report(report, max_chars=3000)` 截断，防止 token 溢出
- **信号处理校验** — `SignalProcessor._normalize_rating()` / `_normalize_confidence()` 对 LLM 输出做合法性校验 + 模糊匹配，非法值 fallback 到 `HOLD` / `Medium`
- **Analyst 报告 fallback** — 当 Agent 有 tool_calls 但同时返回文本内容时，使用文本内容作为报告

### 关键约定

- 包布局：`pyproject.toml` 的 `packages.find` 配置 `where=["src"]`、`include=["ifa*"]`，`src/ifa` 是唯一主包（CLI 入口在 `ifa.cli` 子包内）；`api/`、`web/` 位于项目顶层，由 CLI 入口模块运行时注入 sys.path
- 入口点：`ifa`（`ifa.cli.main:app`）和 `ifa-web`（`ifa.cli.web_entry:main`）注册在 `[project.scripts]`；API 服务无注册脚本，需直接用 `uvicorn api.main:app` 启动
- 内部语言为英文（辩论 Agent 始终用英文以确保推理质量），最终输出由配置决定（默认中文）
- Ruff 规则：忽略 E501（行长度）、F403/F405（星号导入）、E402（模块级导入顺序）
- `isort.known-first-party`：`["ifa", "api", "cli", "web"]`
- 测试：225 个测试覆盖 14 个模块（含 `test_core.py` 41、`test_macro_data.py` 19、`test_advisor_graph.py`、`test_api_and_thread_safety.py` 等）
- 优化路线图见 `TODO.md`：P0-P3 全部完成
