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
pytest                # 全部测试（555 个，覆盖 16 个模块）
pytest tests/test_core.py::TestBacktestEngine::test_max_drawdown   # 运行单个测试
pytest -x             # 遇到第一个失败即停止
```

> 依赖锁：CI 用 `pip install -r requirements.lock && pip install -e . --no-deps` 安装（不是 `pip install -e ".[dev]"`）。CI 跑在 `ubuntu-latest` 而开发机是 Windows，所以锁文件里 Windows-only 的包必须带平台标记（`pywin32==312 ; sys_platform == "win32"`），否则安装步骤在每个矩阵项上都失败 —— `tests/test_lock_hygiene.py` 会守住这条与 CI 矩阵/`requires-python` 的一致性。反向同样成立：`akshare` 的 V8 包装器按平台分流（`mini-racer` 仅非 Linux，`akracer`/`py-mini-racer` 仅 Linux，三者都往同一个 `py_mini_racer/` 目录写文件），锁文件必须带上相同的 `platform_system` 标记，否则 Linux CI 会在锁之外自行补装、破坏可复现性。

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
  - `signal_processing.py` — 信号处理 (`SignalProcessor`)，提取标准化评级（含合法性校验和模糊匹配 fallback）
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
- 环境变量覆盖表 `_ENV_OVERRIDES`：`IFA_LLM_PROVIDER` / `IFA_DEEP_LLM` / `IFA_QUICK_LLM` / `IFA_BACKEND_URL` / `IFA_CUSTOM_API_KEY` / `IFA_ANALYSIS_MODE` / `IFA_AZURE_API_VERSION` / `IFA_TIMEOUT` / `IFA_ENABLE_DEBATE`（空白值视为未设置；整型/布尔键经 `_coerce_config_value` 转换，非法值抛 `ValueError`）
- `backend_url` 归一化：残留的**别家**内置端点（历史漂移：provider=deepseek 却指向智谱）会被重置为所选提供方默认端点，用户自定义地址保留；`custom` 且地址为空时 `validate_config` 报错
- 环境变量 `.env` 存放 API Key（参考 `.env.example`，支持 OPENCODE/OPENAI/AZURE/ANTHROPIC/GOOGLE/ZHIPUAI/DEEPSEEK/QWEN/XAI/OPENROUTER）
- `IFA_LOCAL_DATA_DIR` 可覆盖本地数据目录
- 记忆落盘目录：`memory_dir`（默认 `local_data/memory`，随 `IFA_LOCAL_DATA_DIR` 变化；属于 `_PATH_KEYS`，不会被写入用户配置文件）
- 辩论相关配置：`enable_debate`（开关）、`max_debate_rounds`（研究辩论轮数，默认 2）、`max_risk_discuss_rounds`（风险辩论轮数，默认 2）

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
- `isort.known-first-party`：`["ifa", "api", "web"]`
- 测试：555 个测试覆盖 16 个模块（数据层 `test_public_fund_data.py` / `test_index_fund_data.py` / `test_macro_data.py`、图与状态 `test_core.py` / `test_advisor_graph.py`、接口 `test_api_and_thread_safety.py` 等）
- 优化路线图见 `TODO.md`：P0-P3 全部完成
