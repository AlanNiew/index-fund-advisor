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
ifa backtest 510300                      # 买入-持有回测（不经过 LLM）
ifa tools                                # 列出全部数据工具与参数（36 个，由注册表生成）
ifa tool get_index_valuation -p index_name=沪深300   # 直接调用一个数据工具
ifa skill                                # 把内置 skill 安装到用户级目录（任意项目可用）
python scripts/daily_analysis.py --email  # 批量分析 + 邮件报告（HTML 摘要正文 + .md 附件；cron 定时用；--mode deep_simple 跳过辩论）

# Web 界面
ifa-web    # 启动 Streamlit（内部通过 subprocess 调用 streamlit run web/app.py）

# API 服务（注意：无注册的 ifa-api 脚本，需直接调用 uvicorn）
uvicorn api.main:app --host 0.0.0.0 --port 8000

# 代码质量
ruff check .          # lint
ruff format .         # 格式化
mypy src              # 类型检查
pytest                # 全部测试（909 个，覆盖 38 个模块）
pytest tests/test_core.py::TestBacktestEngine::test_max_drawdown   # 运行单个测试
pytest -x             # 遇到第一个失败即停止
```

> 依赖锁：CI 用 `pip install -r requirements.lock && pip install -e . --no-deps` 安装（不是 `pip install -e ".[dev]"`）。CI 跑在 `ubuntu-latest` 而开发机是 Windows，所以锁文件里 Windows-only 的包必须带平台标记（`pywin32==312 ; sys_platform == "win32"`），否则安装步骤在每个矩阵项上都失败 —— `tests/test_lock_hygiene.py` 会守住这条与 CI 矩阵/`requires-python` 的一致性。反向同样成立：`akshare` 的 V8 包装器按平台分流（`mini-racer` 仅非 Linux，`akracer`/`py-mini-racer` 仅 Linux，三者都往同一个 `py_mini_racer/` 目录写文件），锁文件必须带上相同的 `platform_system` 标记，否则 Linux CI 会在锁之外自行补装、破坏可复现性。另有三条一致性由测试守住：① pyproject 里声明的每个依赖都必须在锁文件里被标注 `# via index-fund-advisor (pyproject.toml)`（新增依赖却忘了重新生成锁文件会立刻失败）；② extra 的版本上限不能排除锁里已钉死的版本 —— `mcp>=1.0,<2` 正是因此存在（mcp 2.x 移除了 `mcp.server.fastmcp`，本 server 用 1.x API）；③ `src/ifa` 直接导入的任何第三方模块都必须**直接声明**，不能靠别的包顺带装上（`python-dotenv` 曾经只由 streamlit → pydantic-settings 带入，wheel 装进干净环境后 `ifa --help` 直接 `ModuleNotFoundError: No module named 'dotenv'`）。见 `tests/test_lock_hygiene.py` 与 `tests/test_dependency_declarations.py`。

## 架构

### 四种分析模式的工作流（LangGraph）

所有模式由 `AdvisorGraph`（`src/ifa/graph/advisor_graph.py`）编排，共享统一的 `IFAdvisorState` 状态：

1. **deep**（含辩论）— `Fund Analyst → Index Analyst? → Bull/Bear 辩论循环 → Research Manager → Report Generator`
   - Index Analyst 仅在资产类型为 ETF/指数基金时执行（条件边 `should_skip_index_analyst`）
   - Bull/Bear 研究员进行对抗辩论（默认 1 轮，`max_debate_rounds`），Research Manager 裁决
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
  - `analysts/` — fund_analyst（19 个数据工具）、index_analyst（11 个工具）、fund_screener（5 个工具）
  - `researchers/` — bull_researcher（看涨研究员）、bear_researcher（看跌研究员），带记忆的对抗辩论
  - `managers/` — portfolio_advisor、research_manager（研究经理裁决）、portfolio_manager（最终决策）、report_generator（整合辩论裁决生成报告）
  - `risk_mgmt/` — aggressive_debator（积极）、conservative_debator（保守）、neutral_debator（中立），三方风险辩论
  - `tools/` — 四类数据工具：`public_fund_tools`（20）、`macro_tools`（8）、`etf_index_tools`（5）、`constituent_tools`（3）
  - `memory.py` — 基于 BM25 的金融情景记忆模块，中英混合分词（中文按字/英文按词），FIFO 淘汰（默认上限 1000 条），支持 JSON 落盘 + 启动载入
  - `prompts/` — Agent prompt 模板，分离自 Agent 实现代码
- **图编排层** (`src/ifa/graph/`) — 模块化图编排（借鉴 TradingAgents）
  - `advisor_graph.py` — 主编排类 `AdvisorGraph`，负责图构建、运行、日志、反思
  - `conditional_logic.py` — 条件边控制（工具循环 + 辩论循环 + 风险辩论循环）
  - `propagation.py` — 状态初始化 (`Propagator`) 和图传播参数
  - `reflection.py` — 决策反思模块 (`Reflector`)，基于实际收益更新记忆
  - `signal_processing.py` — 信号处理 (`SignalProcessor`)。`parse_decision_signals()` 先做**确定性正则解析**（管理层裁决/最终报告里机器可读的 `Rating: X` / `Confidence: Y` 行，零 LLM 调用），解析不到才回退到 LLM 抽取；两条路径都经 `_normalize_rating()` / `_normalize_confidence()` 校验 + 模糊匹配，非法值 fallback 到 `HOLD` / `Medium`。合法评级固定 5 级：`STRONG_BUY / BUY / HOLD / UNDERWEIGHT / SELL`（`REDEEM` 之类的词不在词表内）
- **数据工具层** (`src/ifa/data_tools/`) — 声明式注册表模式
  - `builtin.py` 定义 `_TOOL_SPECS` 列表（36 个工具的 name/handler/description 三元组），`create_default_data_tool_registry()` 一次性注册
  - `search_funds`（`search_funds_tool`）在**完整**基金列表上过滤：CLI / REST / MCP 的搜索必须走它，`get_fund_list()` 只返回前 30 行，**不能**用于搜索
  - `executor.py` 的 `CachedDataToolExecutor` 提供缓存（SHA1 键含参数哈希 + `storage.CACHE_SCHEMA_VERSION`）和快照；改动任何数据工具的输出契约都要递增该版本号，否则旧载荷会永久遮蔽新实现
  - 所有工具通过 `route_to_vendor()` 路由到具体数据源
- **数据流层** (`src/ifa/dataflows/`) — AkShare API 封装，含重试逻辑和资产类型自动检测
  - `data_cleaning.py` — 统一清洗管道（`clean_dataframe`: datetime 解析 → 类型转换 → ffill/bfill）和报告截断（`truncate_report`）
  - **数据源能力边界（易踩）**：ETF 基本信息（`get_fund_basic_info` / `get_etf_fund_info`）必须走东财场内行情表 `fund_etf_fund_daily_em` —— 蛋卷 `fund_individual_basic_info_xq` 只有场外基金库，对 510300 直接 `KeyError: 'data'`；`fund_etf_fund_info_em` 是上游坏接口（14/13 列长度不匹配，默认日期区间下要跑约 2 分钟才失败）。中证成分股（`get_index_constituents*`）按**指数代码**寻址，ETF 代码（510300）与深证指数代码（399006）在该站点返回 404（响应体是 JPEG，pandas 只报 "Excel file format cannot be determined"），故取数失败时抛带可操作说明的 `ValueError`，原始异常留在 `__cause__`
- **LLM 客户端层** (`src/ifa/llm_clients/`) — 工厂模式（`create_llm_client`），`OpenAIClient` 统一兼容 OpenAI 协议的多个提供方（openai/azure/ollama/openrouter/xai/qwen/zhipu/deepseek/opencode/**custom**），另有 Anthropic/Google 独立客户端
  - 提供方清单是单一事实来源：`src/ifa/providers.py` 的 `PROVIDER_CONFIG`（base_url / api_key_env / 展示名）与 `OPENAI_COMPATIBLE_PROVIDERS`。该模块**零依赖**且位于包顶层，`default_config` 只能从它取提供方信息 —— 若放进 `llm_clients/` 会让 `ifa config` / `search` / `info` 连带拉起 langchain 全栈
  - `custom` 提供方 = 任意 OpenAI 兼容端点（自建网关/内网 one-api）：必须显式提供 `backend_url`（否则构造 LLM 时抛 `ValueError`），模型名不做目录校验，Key 取 `IFA_CUSTOM_API_KEY` 或配置项 `custom_api_key`
  - `opencode` 走 **OpenCode Go** 聚合端点（`https://opencode.ai/inference/go/v1`，订阅制）。该服务要求客户端自报身份并携带稳定会话 ID，故 opencode 提供方会额外注入 `default_headers`：自定义 `User-Agent` + 进程级 `x-opencode-session`（可用 `OPENCODE_SESSION_ID` 环境变量覆盖；一次 `ifa` 运行 = 一个会话）。缺失时服务端按通用 SDK 客户端处理且无法复用提示缓存。思考模式下该网关还要求把历史 assistant 消息的 `reasoning_content` 原样回传（langchain_openai 双向丢弃该字段，故 `NormalizedChatOpenAI` 只对 opencode 打开 `_preserve_reasoning_content`）。
- **通知层** (`src/ifa/notify/`) — SMTP 邮件通知（`email.py`，**只用标准库** `smtplib` + `email`）：配置缺项抛 `EmailConfigError` 并列出缺项，绝不静默跳过发信；正文是 `multipart/alternative` 双版本 —— `text/html` 版（摘要渲染成真表格 + 报告 Markdown 由 `markdown.py` 现场渲染成 HTML；超 12 万字符时显式省略全文并指向附件）+ `text/plain` 版（等宽对齐摘要，兜底不认 HTML 的客户端），完整报告作为 `.md` 附件。`markdown.py` 是自写的极简渲染器（标题/表格/列表/粗体/分隔线，**先转义再套标记**、链接只放行 http/https/mailto、未知构造降级为段落），不引第三方 `markdown` 依赖；当前唯一调用方是 `scripts/daily_analysis.py --email`
- **接口层** — `src/ifa/cli/`（Typer，作为 `ifa` 包子模块；`tools_cmd.py` 提供 `tools` / `tool` / `skill` 三个不经过 LLM 的命令）、`web/`（Streamlit 多页应用，含 Plotly 图表）、`api/`（FastAPI 异步任务 + API Key 认证）
- **内置 skill** (`src/ifa/skills/fund.md`) — 随包分发（`pyproject.toml` 的 `[tool.setuptools.package-data]`），`ifa skill` 装到 `~/.claude/skills/`。文件里的工具表由 `ifa tools --markdown` 在 BEGIN/END 标记之间生成，**不要手写**；`tests/test_skill_doc.py` 校验它覆盖全部工具且不含 `cd` / `python -c`
- **环境加载** (`src/ifa/env_loader.py`) — `user_config_dir()`（`IFA_CONFIG_DIR` → `%APPDATA%\ifa` → `~/.config/ifa`）与 `load_env_files()`（工作目录向上 6 层 + 用户级 `.env`，`override=False`）。四个入口都用它取代裸 `load_dotenv()`：否则全局安装后从任意目录启动会读不到 Key，报错却是 "Missing credentials"
- **回测引擎** (`src/ifa/backtest/`) — 买入-持有（**只支持一次性投资，不定投**）策略回测。`engine.py` 的 `run_backtest()` 输出价格口径与投资者口径两套收益、真实无风险利率（中债 10 年期国债，取不到才退 2%）、最大回撤、Sharpe、月度收益与净值曲线；`fees.py` 解析真实申赎费率并显式建模交易成本（管理费/托管费已含在净值里，**绝不重复扣**）；`rating_validator.py` 做评级 vs 实际收益验证，`rating_stats.py` 是纯统计层（多视界/超额/rank IC/分档/置信度校准），`benchmarks.py` 逐基金解析基准指数
- **可观测性** (`src/ifa/observability/`) — 轻量级 per-request tracing，`RequestTracer` 自动追踪 `AdvisorGraph.run()` 执行，日志保存到 `results/traces/`
- **组合模型** (`src/ifa/portfolio/`) — `RiskProfile` 数据模型（4 种风险偏好）+ 资产配置策略描述 + `weights.py`（权重的确定性解析与校验）

### 状态模型

定义在 `src/ifa/agents/types.py`：

- **`IFAdvisorState(MessagesState)`** — 主状态，包含输入（fund_codes、analysis_date、mode、risk_profile）、分析结果（fund_analysis_report、index_analysis_report、portfolio_advice）、辩论状态（fund_debate_state、risk_debate_state）、最终输出（final_report、final_rating、final_confidence）
- **`FundDebateState`** — 基金研究辩论状态（bull_history、bear_history、history、current_response、count、judge_decision）
- **`RiskDebateState`** — 风险辩论状态（aggressive/conservative/neutral 三方 history 和 current_response、latest_speaker、count、judge_decision）

### 辩论机制

- **基金辩论**（deep/screen 模式）：Bull/Bear 交替发言，默认 **1 轮**（`max_debate_rounds`；2 轮是 30.4 分钟实测里辩论段独占 86% 的主因），终止条件 `count >= 2 * max_debate_rounds`，Research Manager 裁决
- **风险辩论**（portfolio 模式）：Aggressive → Conservative → Neutral 轮流发言，默认 2 轮（`max_risk_discuss_rounds`），终止条件 `count >= 3 * max_risk_discuss_rounds`，Portfolio Manager 裁决
- 裁决结果通过 `_extract_debate_judgment()` 传递给 Report Generator

### 记忆与反思系统

- 每个 Agent 可携带 `FinancialSituationMemory` 实例，基于 BM25 检索历史相似情景
- `_tokenize()` 使用中英混合分词：中文按字拆分（每个汉字独立 token），英文/数字按词拆分
- `add_situations()` 带 FIFO 淘汰机制（默认上限 1000 条，可配置 `max_situations`）
- **落盘持久化**：配置提供 `memory_dir` 时记忆写入 `<memory_dir>/<name>.json`，实例化时自动载入。
  `DEFAULT_CONFIG` 默认指向 `local_data/memory`；不提供 `memory_dir` 则不落盘（单元测试因此保持无副作用）
  - 写盘走 `src/ifa/atomic_io.py` 的原子写；失败只告警，不阻塞分析
  - 载入对损坏 / 缺字段的文件降级为空记忆，绝不抛异常；`clear()` 默认同时删除落盘文件
  - **正常分析流程不会写入记忆**——只有 `ifa validate --update-memory` 会调用
    `reflect_and_remember()`。落盘保证的是这些经验能被之后的 `ifa analyze` 复用，
    而非"运行越久记忆越多"
- `Reflector` 在决策后根据实际收益/亏损反思并更新各 Agent 的记忆（`reflect_and_remember()`）
- `Reflector.reflect_all()` 按模式条件性反思：deep_simple 跳过，portfolio 额外反思 risk_debate

### 日志系统

- 每次运行自动保存结构化 JSON 日志到 `results/{fund_codes}/ifa_logs/state_log_{date}_{mode}.json`
- 日志包含完整的分析报告、辩论历史、裁决结果

### 配置系统

- `src/ifa/default_config.py` — 默认配置 + `build_runtime_config()` 运行时配置构建；提供方清单来自 `src/ifa/providers.py`
- 优先级：**环境变量 > 用户配置文件 > DEFAULT_CONFIG**（`build_runtime_config()` 依次 deepcopy → `load_last_config()` → `_env_overrides()` → 重算路径键 → 端点归一化 → `validate_config()`）
- `ifa config <key> <value>` 真正落盘：`set_user_config()` / `unset_user_config()` 原子写用户配置文件（`IFA_CONFIG_DIR` → Windows `%APPDATA%\ifa\config.json`，否则 `~/.config/ifa/config.json`）；`save_last_config()` 写同一文件。可配置项 = `CONFIGURABLE_KEYS`（DEFAULT_CONFIG 中非路径键、非字典键）；旧版 `src/ifa/last_config.py` 仅只读兼容
- 环境变量覆盖表 `_ENV_OVERRIDES`：`IFA_LLM_PROVIDER` / `IFA_DEEP_LLM` / `IFA_QUICK_LLM` / `IFA_BACKEND_URL` / `IFA_CUSTOM_API_KEY` / `IFA_ANALYSIS_MODE` / `IFA_AZURE_API_VERSION` / `IFA_TIMEOUT` / `IFA_DEEP_TIMEOUT` / `IFA_LLM_MAX_RETRIES` / `IFA_DATA_SOURCE_TIMEOUT` / `IFA_ENABLE_DEBATE` / `IFA_SMTP_HOST` / `IFA_SMTP_PORT` / `IFA_SMTP_USER` / `IFA_SMTP_PASSWORD` / `IFA_SMTP_SENDER` / `IFA_EMAIL_TO` / `IFA_SMTP_USE_SSL` / `IFA_SMTP_TIMEOUT`（空白值视为未设置；整型/布尔键经 `_coerce_config_value` 转换，非法值抛 `ValueError`）
- `backend_url` 归一化：残留的**别家**内置端点（历史漂移：provider=deepseek 却指向智谱）会被重置为所选提供方默认端点，用户自定义地址保留；`custom` 且地址为空时 `validate_config` 报错
- 环境变量 `.env` 存放 API Key（参考 `.env.example`，支持 OPENCODE/OPENAI/AZURE/ANTHROPIC/GOOGLE/ZHIPUAI/DEEPSEEK/QWEN/XAI/OPENROUTER）。加载走 `ifa.env_loader.load_env_files()`：**工作目录向上 6 层优先，其次用户级 `.env`**（`IFA_CONFIG_DIR` → `%APPDATA%\ifa\.env` / `~/.config/ifa/.env`），`override=False` 故先加载者生效 —— `uv tool install` 的全局 CLI 与 MCP server 因此在任意 CWD 都能拿到 Key
- 邮件通知配置：`smtp_host` / `smtp_port` / `smtp_user` / `smtp_password` / `smtp_sender` / `smtp_recipients` / `smtp_use_ssl` / `smtp_timeout`；`host` / `recipients` / `sender` 缺一不可，缺项抛 `EmailConfigError`（`smtp_port` / `smtp_use_ssl` / `smtp_timeout` 有默认值，不算「配过」的证据）。密码推荐只走 `IFA_SMTP_PASSWORD`，避免明文落进 `config.json`
- `IFA_LOCAL_DATA_DIR` 可覆盖本地数据目录
- 记忆落盘目录：`memory_dir`（默认 `local_data/memory`，随 `IFA_LOCAL_DATA_DIR` 变化；属于 `_PATH_KEYS`，不会被写入用户配置文件）
- 辩论相关配置：`enable_debate`（开关）、`max_debate_rounds`（研究辩论轮数，默认 1）、`max_risk_discuss_rounds`（风险辩论轮数，默认 2）
- 延迟预算：`timeout`（quick 档 LLM 超时，默认 120 秒）、`deep_timeout`（deep 档——报告生成/裁决——默认 180 秒）、`llm_max_retries`（重试次数，默认 2，即最多 3 次尝试）。依据：2026-10 实测 510300 的 deep 运行 wall 30.4 分钟、**98.5% 花在等 LLM**，其中多个请求拖到 180 秒超时后重试；但合法成功调用最长也到过 119 秒，所以不能一刀切收紧到 60–90 秒

### 发行（GitHub Release）

- `.github/workflows/release.yml`：推送 `v*` tag → 构建 wheel + sdist → 在干净 venv 里冒烟（`ifa --help`、`ifa tools --json`、随包 skill、`mcp` extra 落在 1.x、**MCP stdio initialize 握手**）→ 挂到 GitHub Release；`workflow_dispatch` 只上传 artifact。**不发 PyPI**。
- tag 必须等于 `pyproject.toml` 的 `version`（workflow 里强制校验）。
- `release/assemble.py` 是另一套「只含 MCP + 数据层」的轻量包脚手架：它用 AST 只取模块顶层 `ifa.*` 导入算闭包，复制前自检，漏文件立刻报错（历史上漏过 `env_loader` / `providers` / `atomic_io`，轻量包连 `import ifa.default_config` 都过不去）。`tests/test_release_package.py` 独立复算这条闭包，并真的组装一次、用「看不到仓库 src」的解释器 import 一遍。
- wheel 只含 `ifa` 包：`ifa` / `ifa-mcp` 可用，`ifa-web` 与 REST API 需要仓库检出（`ifa.cli.web_entry` 会给出可操作提示并以退出码 1 结束）。

### 健壮性模式

项目已建立的错误处理约定，修改代码时应遵循：

- **LLM 调用统一走 `invoke_llm_safely()` / `invoke_chain_safely()`** — 定义在 `src/ifa/agents/utils.py`，带指数退避重试。所有 Agent 和图模块中的 LLM 调用都必须使用它，禁止裸调用 `llm.invoke()`
- **`run()` 顶层异常保护** — `AdvisorGraph.run()` 用 try/except 包裹 `graph.invoke()`，失败时仍保存日志并返回含 `error` 字段的状态；**接口层必须把「没有最终报告」当失败上报**（CLI `_run_analysis` 抛 `typer.Exit(code=1)`、Web `st.error`），否则包装脚本/定时任务拿到退出码 0、无从发现故障
- **原子写统一走 `src/ifa/atomic_io.py`** — 报告 / 日志 / 追踪 / 记忆的落盘都经 `atomic_write*()`（tmp 文件 → `Path.replace`，失败清理 tmp 并降级为直写）。该模块独立于 `common.py`，使 `agents/memory.py` 这类叶子模块无需 import 组合根
- **Agent 工具取数统一走 `run_data_tool()`**（`ifa.data_tools.api`）— 不要直连 `akshare`，也不要直接调 `route_to_vendor()`，否则绕过缓存/快照层。历史上 `constituent_tools` 三个工具正是如此漏掉了缓存；其中 `get_constituent_performance` 还把个股行情路由到从未注册的 `get_stock_data`，导致对全部成分股恒定返回「数据获取失败」
- **缓存层以文本/CSV 落盘，不保留 dtype** — DataFrame 往返后纯数字列会丢前导零（`"000001" → 1`），消费方必须自行补零（见 `constituent_tools._normalize_stock_code`）
- **搜索必须走 `search_funds`，不要在 `get_fund_list()` 的文本上过滤** — 后者只返回 `head(30)`，历史上 CLI / REST / MCP 三处都在它上面 grep，导致干净环境里「沪深300」的 366 只基金一只都搜不到（且退出码为 0，看起来像「查无结果」）
- **数据源失败必须可识别** — `a_share.DATA_SOURCE_ERROR_MARKER`（"数据源访问失败："）用于区分「取数失败」与「查无结果」：CLI 打红字并 `typer.Exit(1)`，REST 返 502，MCP 返 `error` 字段
- **改动数据工具的输出契约时递增 `CACHE_SCHEMA_VERSION`** — 缓存无 TTL，旧载荷会一直命中并遮蔽新实现（`get_fund_list` 曾因此「有缓存机器正常、干净环境失效」）
- **数据源能力边界要变成可操作报错** — 上游把「不支持」表现为误导性报错时（如用 ETF 代码取中证成分股 → pandas "Excel file format cannot be determined"），不要原样透出：换成说明约束与正确用法的信息，同时把底层异常保留在 `__cause__` 与文本里（见 `_constituents_source_hint`）。反向要求同样成立——不要把网络抖动误诊成用法错误
- **`py_mini_racer` 构造必须串行化** — akshare 多个接口（估值 `stock_index_pe_lg`、交易日历 `tool_trade_date_hist_sina`、同花顺/巨潮系）在内部 new `MiniRacer()`。LangGraph 的 ToolNode 并行执行工具，两个线程同时构造会触发 V8 断言 `[FATAL:partition_address_space.cc(243)] Check failed: !IsConfigurablePoolInitialized().`，**直接 abort 整个进程**（退出码 0x80000003，try/except 无法捕获）。`src/ifa/dataflows/__init__.py` 在导入时安装 `_mini_racer_guard`：用 RLock 串行化构造，并遍历 `sys.modules` 替换所有已持有旧 `MiniRacer` 引用的模块属性。不要移除该 import，也不要自行构造 `MiniRacer`
- **数据源请求必须能超时退出** — AkShare 大量接口直接 `requests.get(url)` 不传 timeout（如 `index_stock_cons_csindex`），上游建连后不再返回字节时整条分析链会无限期挂住（实测 `oss-ch.csindex.com.cn` 挂死 14 分钟：进程存活、CPU≈0、日志停滞、try/except 永不触发）。`src/ifa/dataflows/__init__.py` 导入时安装 `_network_guard`：包装 `requests.sessions.Session.request`，只在调用方未传 timeout（或显式传 None）时补上 `IFA_DATA_SOURCE_TIMEOUT`（默认 30 秒）。**不要改回 `socket.setdefaulttimeout`** —— requests 会把 `timeout=None` 包成 `Timeout(connect=None, read=None)` 并显式 `sock.settimeout(None)`，把 socket 默认值覆盖掉（该实测结论已由 `tests/test_network_guard.py` 固化）。超时的请求仍被 `is_retryable_akshare_error` 视为可重试，单个工具最坏耗时约为 `retries × 超时`
- **思考模式的 `reasoning_content` 必须回传（只对 opencode 打开）** — OpenCode Go 在思考模式下会以 400 拒绝「历史 assistant 消息缺少 `reasoning_content`」的请求（原文 `The reasoning_content in the thinking mode must be passed back to the API`），而 `langchain_openai` 的 `_convert_message_to_dict` / `_convert_dict_to_message` 在两个方向上都丢弃该字段。`NormalizedChatOpenAI` 覆写 `_create_chat_result`（把响应里的 reasoning_content 存进 `additional_kwargs`）与 `_get_request_payload`（请求时按索引回填），开关由 `OpenAIClient.get_llm()` 仅在 `provider == "opencode"` 时打开。**不要全局打开**：DeepSeek 官方 API 的规则相反，回传会 400。该故障是**间歇性**的（是否进思考模式由上游按请求决定），不要用「复跑一次成功」判定已修好
- **超时与重试必须分档，且默认值要能被配置覆盖** — quick 档 120 秒 / deep 档 180 秒（`src/ifa/common.py` 的 `build_advisor()` 给 deep 客户端单独注入 `deep_timeout`），`llm_max_retries` 默认 2。所有默认值集中在 `src/ifa/default_config.py` 的 `DEFAULT_LLM_TIMEOUT` / `DEFAULT_DEEP_TIMEOUT` / `DEFAULT_LLM_MAX_RETRIES`，不要在各处硬编码；`invoke_llm_safely()` 的 `retries` 默认 `None` 表示「读配置」，显式传参仍然优先（`_resolve_retries()`）
- **辩论历史必须截断（保留最新发言）** — 每个辩手每轮都要重读整段 history，实测上下文涨到 41414 字符、辩论段独占运行时间的 86%。`truncate_debate_history()`（`src/ifa/agents/utils.py`，上限 `DEBATE_HISTORY_MAX_CHARS = 3000`）从**头部**丢弃并加「[... 较早的辩论发言已省略 ...]」，与 `truncate_report()`（保留头部）方向相反。只在**每轮重读历史**的节点（`researchers/researcher.py`、`risk_mgmt/debator.py`）调用；**state 里必须保留全文**，裁决（Research Manager）与最终报告需要完整记录。风险辩论节点的 `portfolio_advice` / `fund_analysis` 也走 `truncate_report()`（此前是全文直传）
- **缓存操作异常隔离** — `CachedDataToolExecutor` 的缓存读写和快照保存均有 try/except，磁盘故障时降级为直接执行
- **vendor fallback 链** — `route_to_vendor()` 对每个供应商用 try/except，失败时自动尝试下一个
- **安全字典访问** — 所有 Agent 节点使用 `.get()` + `isinstance` 检查访问嵌套状态；`_safe_get_nested()` 用于日志；`Reflector._safe_get_debate()` 用于反思
- **Prompt 长度限制** — Agent 中输入的分析报告通过 `truncate_report(report, max_chars=3000)` 截断，防止 token 溢出
- **信号处理优先确定性解析** — `AdvisorGraph.run()` 在图执行成功后调 `resolve_decision_signals()`：先取管理层裁决/最终报告里的 `Rating:` / `Confidence:` 行（正则，零 LLM 调用），只有取不到才让 `SignalProcessor.process_signal()` 再发一次 LLM 抽取。报告生成器的 prompt 被约束为 5 级词表（`STRONG_BUY / BUY / HOLD / UNDERWEIGHT / SELL`），不要引入 `REDEEM` 等词表外的词。`_normalize_rating()` / `_normalize_confidence()` 仍做合法性校验 + 模糊匹配，非法值 fallback 到 `HOLD` / `Medium`
- **组合权重必须由代码校验，不能只写在 prompt 里** — `validate_portfolio_weights()`（`src/ifa/portfolio/weights.py`）解析 `ASSET ALLOCATION` / `FUND SELECTIONS` 段的权重，校验合计 100%（±1%）、单基金 ≤ `max_single_fund_pct`、债券 ≥ `min_bond_pct`、海外/QDII ≤ `max_international_pct`；违规时算出**确定性重排结果**，把 `## WEIGHT CHECK（代码校验，非 LLM 自述）` 追加到 `portfolio_advice` 并 `logger.warning`。约束不可行（如基金数 × 单基金上限 < 100%）时显式写「无法满足」，不硬凑
  - 解析取舍：同一基金代码多次出现取**最大值**而非累加（真实报告常在明细表后用「宽基小计：510300（20%）…」复述一遍，累加会把合规组合算成 200%）；行内有 `+` 或「小计/合计」时跳过 `= 45%` 这种组内合计；支持 markdown 表格行（名字里的 `|` 会被剥掉）；「合计」行不会被当成一个 100% 的类别
- **估值数据缺失必须显式标注** — 乐咕乐股只覆盖 12 个指数，其余（中证白酒、纳斯达克100、标普500 等）PE/PB/ERP 全为空。`notify/email.py` 的 `_valuation_anchor_note()` 与 `daily_analysis.py` 的 `fetch_valuations()` 会在邮件正文、估值表与日志里标注「本次无估值锚」，避免「依据估值百分位给出评级」这种没有锚的宣称看不出来
- **股息率必须用指数自身口径** — `fetch_index_dividend_yield()` 走中证指数官方 `stock_zh_index_value_csindex`（列名被上游固定重命名为 `市盈率1/2`、`股息率1/2`，须先按日期取最新、忽略倒序与表头 NaN 行），`dividend_yield_source` 记录来源（如 `csindex:000300`）；未登记的指数返回 `available=False`，**绝不退回全市场 `stock_a_gxl_lg` 顶替**（历史上 5 只基金全显 2.73% 就是这么来的）。全市场值只作 `dividend_yield_reference` 参考
- **回测必须标明价格口径与费用假设** — ETF 走前复权价、公募基金优先取「累计净值走势」（分红再投已计入；单位净值会把分红记成亏损），且**不再截断历史**（旧实现 `tail(120)` 把三年回测压成半年）。价格口径（可与指数基准直接比较）与投资者口径（扣申购费/赎回费/券商佣金）同时给出，差额即费用拖累；管理费/托管费只作说明，**不从净值里再扣一次**。取不到费率时用保守默认值（申购 0.15% / 赎回 0.50% / 佣金 0.03% 单边）并写进 `notes`，绝不静默按 0 计；`ifa backtest --no-fees` 可回到纯价格口径
- **评级验证必须看超额、多视界、逐基金基准** — 绝对命中率主要反映 beta，可证伪的是**超额命中率**；每个视界（默认 20/60/120 交易日）各自取数，**只有主视界允许回退到扁平字段**（60 日收益绝不许冒充 120 日）；基准逐基金解析（显式 override > 基金名识别 > 回退沪深300 并写清原因），报告里列明回退条数；另给 rank IC、5 档分档平均超额、单调性、置信度分档校准。多视界/多指标属多重比较，**只有主视界可当确认性结论**（免责声明里写明）
- **Analyst 报告 fallback** — 当 Agent 有 tool_calls 但同时返回文本内容时，使用文本内容作为报告

### 关键约定

- 包布局：`pyproject.toml` 的 `packages.find` 配置 `where=["src"]`、`include=["ifa*"]`，`src/ifa` 是唯一主包（CLI 入口在 `ifa.cli` 子包内）；`api/`、`web/` 位于项目顶层，由 CLI 入口模块运行时注入 sys.path
- 入口点：`ifa`（`ifa.cli.main:app`）和 `ifa-web`（`ifa.cli.web_entry:main`）注册在 `[project.scripts]`；API 服务无注册脚本，需直接用 `uvicorn api.main:app` 启动
- 全局安装：`uv tool install --from git+https://github.com/AlanNiew/index-fund-advisor.git index-fund-advisor`（`--from` 写仓库地址，**最后一个参数必须是包名**，写成 `ifa` 会被 uv 拒绝）—— 不克隆仓库、不激活 venv，任意目录可用（Key 放用户级 `.env`），详见 README「全局安装」
- 数据工具的数量与参数是**生成的**：`ifa tools` / `ifa tools --markdown` 渲染 `_TOOL_SPECS`，skill 文档与 README 的数字都从它核对（历史上漂移过四次：25 → 33 → 35 → 36）
- 内部语言为英文（辩论 Agent 始终用英文以确保推理质量），最终输出由配置决定（默认中文）
- Ruff 规则：忽略 E501（行长度）、F403/F405（星号导入）、E402（模块级导入顺序）
- `isort.known-first-party`：`["ifa", "api", "web"]`
- 测试：909 个测试覆盖 38 个模块（数据层 `test_public_fund_data.py` / `test_index_fund_data.py` / `test_macro_data.py`、图与状态 `test_core.py` / `test_advisor_graph.py`、接口 `test_api_and_thread_safety.py`、回测与验证 `test_backtest_fees.py` / `test_rating_stats.py` / `test_benchmarks.py` / `test_rating_validator.py`、通知 `test_notify_email.py` / `test_markdown.py` 等）
- 优化路线图见 `TODO.md`：P0-P3 全部完成
