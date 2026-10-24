# IFA 项目优化任务清单

> 基于 TradingAgents / FinRobot 等优秀开源项目对比分析，按优先级排列。

## 第一轮：基础建设 ✅ 已完成

### P0 — 健壮性加固（防崩溃） ✅ 已完成

- [x] **`run()` 方法加顶层异常保护**
- [x] **`invoke_llm_safely` 全局统一使用**
- [x] **`_log_state` 安全字典访问**
- [x] **`executor.py` 缓存操作异常隔离**
- [x] **`route_to_vendor` fallback 链修复**

### P1 — 数据质量与可靠性 ✅ 已完成

- [x] **数据清洗管道 `clean_dataframe`**
- [x] **消息清理机制 `Msg Clear` 节点**
- [x] **Agent 状态访问安全化**
- [x] **Prompt 长度限制 `truncate_report`**

### P2 — 核心功能增强 ✅ 已完成

- [x] **回测集成**
  - 新增模块：`src/ifa/backtest/engine.py`
  - 功能：买入-持有策略回测，计算年化收益、最大回撤、Sharpe、月度收益
  - 支持 ETF/指数/公募基金的历史数据回测
  - `BacktestResult` 数据类 + `format_backtest_report()` Markdown 报告

- [x] **基础测试覆盖**
  - 41 个测试覆盖 8 个模块：数据清洗、回测引擎、状态初始化、条件边、反思、安全访问、工具注册表、资产类型
  - 文件：`tests/test_core.py`

- [x] **反思系统增强**
  - 新增 `reflect_all()` 方法：按模式条件性反思
  - deep_simple 跳过全部反思，portfolio 额外反思 risk_debate
  - 缺少辩论状态时自动跳过对应 Agent

### P3 — 生产化扩展 ✅ 已完成

- [x] **可观测性集成**
  - 新增模块：`src/ifa/observability/tracer.py`
  - `RequestTracer` + `TraceSpan` 轻量级 per-request 追踪
  - 集成到 `AdvisorGraph.run()`，每次运行自动记录执行时间
  - 追踪日志保存到 `results/traces/{request_id}.json`
  - 无外部依赖，后续可切换到 Langfuse/OTel

- [x] **多数据源 fallback 架构**（供应商实现待补）
  - `route_to_vendor()` 对每个供应商独立 try/except，失败自动尝试下一个；接口层已就绪
  - 配置级供应商选择：`data_vendors` / `tool_vendors` 字典
  - ⚠️ **更正**：原文「`_KNOWN_DATA_VENDORS` 新增 tushare 供应商」不成立——`tushare` 只是被
    加进可配置名单，`VENDOR_METHODS` 中**没有任何 tushare 实现**，配置它会被静默回退到
    akshare（无日志、无提示）。现已从名单移除：宁可让 `validate_config` 明确报错，
    也不要保留「配置了却不生效」的选项。新增供应商需要同时补实现，不只是加个名字

- [x] **Web 界面可视化增强**
  - 新增 `web/views/charts.py`：Plotly 图表组件（净值曲线、月度收益柱状图、指标卡片）
  - 分析页面集成回测功能：可选回测参数 → 净值曲线 + 月度收益 + 详细报告
  - `analysis.py` 新增回测参数面板（时长、金额）

---

## 第二轮：代码质量与优化 ✅ 已完成

### S1 — 安全与稳定性 ✅ 已完成

- [x] **`no_proxy()` 线程安全改造**
  - 文件：`src/ifa/dataflows/a_share_common.py`
  - 问题：直接 monkey-patch `requests.Session.__init__`，API 并发时存在竞态条件
  - 方案：改为 context manager 或 per-session 代理设置，避免修改全局类

- [x] **API 任务存储添加过期清理**
  - 文件：`api/main.py:42`
  - 问题：`_tasks: dict[str, dict] = {}` 无限增长
  - 方案：添加 TTL 过期或 LRU 淘汰机制（如 `cachetools.TTLCache`）

- [x] **API CORS 限制为特定域名**
  - 文件：`api/main.py:19-25`
  - 问题：`allow_origins=["*"]` 允许所有来源
  - 方案：通过环境变量 `IFA_CORS_ORIGINS` 配置允许的域名列表

### S2 — 消除重复代码 ✅ 已完成

- [x] **统一 `_safe_plain_code` / `_safe_display_symbol` 等符号处理函数**
  - 重复 5 处：`a_share_index_fund.py`、`a_share_public_fund.py`、`a_share_common.py`、`constituent_tools.py`、`stockstats_utils.py`
  - 方案：统一到 `a_share_common.py`，其他文件改为 import

- [x] **统一 `_suppress_akshare_progress` / `_is_retryable_akshare_error`**
  - 重复 2 处：`a_share.py:46-155`、`stockstats_utils.py:49-100`
  - 方案：统一到 `a_share_common.py`

- [x] **统一 `_find_column` 函数**
  - 重复 2 处：`constituent_tools.py:189-194`、`backtest/engine.py:129-136`
  - 方案：提取到 `src/ifa/dataflows/utils.py` 公共模块

- [x] **合并 Bull/Bear Researcher 为参数化工厂函数**
  - 文件：`src/ifa/agents/researchers/bull_researcher.py`、`bear_researcher.py`
  - 问题：两个文件 71 行，结构几乎完全相同，仅 prompt 和历史字段名不同
  - 方案：创建 `create_researcher(role: str, prompt: str, history_key: str)` 工厂函数

- [x] **合并三个 Risk Debator 为参数化工厂函数**
  - 文件：`src/ifa/agents/risk_mgmt/aggressive_debator.py`、`conservative_debator.py`、`neutral_debator.py`
  - 问题：三个文件各 55 行，仅 prompt、历史字段名、speaker 标识不同
  - 方案：创建 `create_risk_debator(style: str, prompt: str, history_key: str)` 工厂函数

### S3 — 性能优化 ✅ 已完成

- [x] **BM25 索引延迟重建**
  - 文件：`src/ifa/agents/memory.py:64-82`
  - 问题：每次 `add_situations()` 都全量重建 BM25 索引
  - 方案：添加 dirty flag，在 `retrieve()` 时才触发重建（惰性更新）

- [x] **`get_constituent_performance` 并行获取股票数据**
  - 文件：`src/ifa/agents/tools/constituent_tools.py:170-186`
  - 问题：串行循环获取 10 只股票数据，每次都是独立网络请求
  - 方案：使用 `concurrent.futures.ThreadPoolExecutor` 并行获取

- [x] **`is_trade_date` 缓存 set 转换结果**
  - 文件：`src/ifa/dataflows/a_share_common.py:212-221`
  - 问题：每次调用都 `set(get_trade_calendar())` 重建集合
  - 方案：将 set 缓存为模块级变量或使用 `functools.cached_property`

- [x] **Web/API 层复用 LLM 客户端**
  - 文件：`web/views/analysis.py:38`、`src/ifa/common.py:43-70`
  - 问题：每次请求都 `build_advisor()` 重新创建 LLM 客户端
  - 方案：Web 层使用 `@st.cache_resource`；API 层在 app lifespan 中初始化

### S4 — 测试补充 ✅ 已完成

- [x] **Data Tools 层测试**
  - `src/ifa/data_tools/executor.py` — 缓存读写、TTL 过期、快照保存
  - `src/ifa/data_tools/storage.py` — `build_cache_key`、`load_cache`、`save_cache`

- [x] **Agent 节点集成测试（mock LLM）**
  - Fund Analyst / Index Analyst / Fund Screener
  - Bull/Bear Researcher
  - Report Generator / Portfolio Advisor
  - Risk Debators

- [x] **Portfolio 模型测试**
  - `src/ifa/portfolio/models.py` — RiskProfile 数据模型
  - `src/ifa/portfolio/strategies.py` — 资产配置策略

- [x] **Observability 测试**
  - `src/ifa/observability/tracer.py` — RequestTracer / TraceSpan

- [x] **条件边测试补全**
  - `should_continue_fund_analyst` 等工具循环条件（当前仅测试了辩论条件）

### S5 — 代码清理 ✅ 已完成

- [x] **删除未使用的 `stockstats_utils.py`**
  - 文件：`src/ifa/dataflows/stockstats_utils.py`
  - 问题：整个文件未被任何模块导入引用，属于遗留代码

- [x] **删除 `a_share_macro.py` 中的死代码**
  - 文件：`src/ifa/dataflows/a_share_macro.py:488-493`
  - 问题：`_calc_bogle_pe_signal` 中 `idx_col` 赋值后立即丢弃，且 `pe_series.index.name` 不会是列表

- [x] **`IFAdvisorState` 导入提升到模块级**
  - 文件：`src/ifa/graph/advisor_graph.py` 第 300、358、407、448 行
  - 问题：4 处函数级 `from ifa.agents.types import IFAdvisorState`
  - 方案：移到文件顶部统一导入

- [x] **`a_share_macro.py` 模块级导入规范化**
  - 文件：`src/ifa/dataflows/a_share_macro.py:399`
  - 问题：`from datetime import datetime  # noqa: E402` 插在模块中间
  - 方案：移到文件顶部

### S6 — 架构改进 ✅ 已完成

- [x] **API 层模块化拆分**
  - 文件：`api/main.py`（232 行）
  - 问题：端点、请求模型、响应模型、后台任务全在一个文件
  - 方案：拆分到已有的 `api/routers/` + `api/models/` + `api/tasks/` 目录

- [x] **`build_runtime_config()` 使用深拷贝**
  - 文件：`src/ifa/default_config.py:118-130`
  - 问题：`DEFAULT_CONFIG.copy()` 是浅拷贝，嵌套 `data_vendors` 字典共享引用
  - 方案：使用 `copy.deepcopy()` 或 `msgspec` 结构化拷贝

- [x] **`save_last_config()` 原子写入**
  - 文件：`src/ifa/default_config.py:147-151`
  - 问题：直接 `write_text`，崩溃时可能损坏配置文件
  - 方案：先写入临时文件再 `os.replace()` 原子重命名

- [x] **Web 历史记录功能实现**
  - 文件：`web/app.py:60-61`
  - 问题：当前只有占位提示 `"历史记录功能开发中..."`
  - 方案：读取 `results/` 目录下的历史分析报告，提供列表和查看功能

- [ ] **`interface.py` 的 VENDOR_METHODS 自动注册**（实际未完成）
  - 文件：`src/ifa/dataflows/interface.py`
  - 问题：约 60 行导入 + 手动映射表，新增一个数据函数需手改 3 处
    （`interface.py` 的导入与映射、`data_tools/builtin.py` 的 spec、调用方）
  - 方案：使用装饰器或注册表模式自动收集
  - ⚠️ **更正**：此前标记为「已完成」，但该文件仍是全量手动映射；本次新增
    `get_stock_daily` / `get_index_constituents_raw` 仍需逐处手改，可直接证伪

### S7 — 生产化增强 ✅ 已完成

- [x] **Dockerfile 多阶段构建**
  - 文件：`Dockerfile`
  - 方案：多阶段构建、添加 `.dockerignore`、HEALTHCHECK、非 root 用户

- [x] **模型目录可配置化**
  - 文件：`src/ifa/llm_clients/model_catalog.py`
  - 问题：模型名称硬编码在源码中，更新需手动改代码
  - 方案：支持从配置文件或环境变量读取模型映射

- [x] **`dataflows/config.py` 全局状态线程安全**
  - 文件：`src/ifa/dataflows/config.py`
  - 问题：`_config` 是模块级全局变量，多线程下可能配置竞争
  - 方案：使用 `contextvars.ContextVar` 替代模块级变量

- [x] **`get_current_tracer()` 添加线程安全保护**
  - 文件：`src/ifa/observability/tracer.py:132-134`
  - 问题：`_current_tracer` 全局变量无锁保护
  - 方案：使用 `contextvars.ContextVar` 替代

---

## 第三轮：精炼打磨 ✅ 已完成

> 基于综合评估（评分 8.45/10），聚焦遗留的代码重复、线程安全缺口、弃用 API、测试盲区。

### R1 — 清理旧 Agent 文件（消除最大重复源） ✅ 已完成

- [x] **删除 `bull_researcher.py` 和 `bear_researcher.py`**
  - 文件：`src/ifa/agents/researchers/bull_researcher.py`、`bear_researcher.py`
  - 原因：功能已被 `researcher.py` 工厂完全替代，`advisor_graph.py` 已导入新工厂
  - 操作：`git rm` 两个文件，确认无其他引用

- [x] **删除三个旧 Debator 文件**
  - 文件：`src/ifa/agents/risk_mgmt/aggressive_debator.py`、`conservative_debator.py`、`neutral_debator.py`
  - 原因：功能已被 `debator.py` 工厂完全替代
  - 操作：`git rm` 三个文件，更新 `tests/test_agents_utils.py` 中 3 处旧导入路径改为 `from ifa.agents.risk_mgmt.debator import ...`

### R2 — 线程安全补全 ✅ 已完成

- [x] **`data_tools/api.py` 为 `_default_executor` 加锁**
  - 文件：`src/ifa/data_tools/api.py:8, 43-60`
  - 问题：`_default_executor` 全局可变状态无锁保护，并发时可能创建多个执行器实例
  - 方案：使用 `threading.Lock` 保护 `get_default_data_executor()` 的懒初始化

- [x] **`dataflows/config.py` 初始化改用 `deepcopy`**
  - 文件：`src/ifa/dataflows/config.py:11`
  - 问题：`DEFAULT_CONFIG.copy()` 浅拷贝，嵌套的 `data_vendors` 字典可被外部修改
  - 方案：改为 `copy.deepcopy(default_config.DEFAULT_CONFIG)`

### R3 — 消除弃用 API ✅ 已完成

- [x] **替换 `datetime.utcnow()` 为 `datetime.now(UTC)`**
  - 文件：`src/ifa/data_tools/storage.py:165`
  - 问题：`datetime.utcnow()` 在 Python 3.12+ 已弃用
  - 方案：`from datetime import datetime, timezone` → `datetime.now(timezone.utc).isoformat()`

### R4 — API 层优化 ✅ 已完成

- [x] **`_execute_graph()` 移除重复 `load_dotenv()` 调用**
  - 文件：`api/routers/analysis.py:110-111`
  - 问题：每次执行都调用 `load_dotenv()`，在并发场景下是不必要的 I/O
  - 方案：在 `api/main.py` 启动时调用一次 `load_dotenv()`

- [x] **修复 `analysis.py` 中的函数内导入**
  - 文件：`api/routers/analysis.py:82, 90`
  - 问题：`HTTPException` 和 `all_tasks` 在函数内部导入
  - 方案：移至文件顶部

- [x] **`asyncio.create_task()` 添加引用跟踪**
  - 文件：`api/routers/analysis.py:38, 66, 77`
  - 问题：`asyncio.create_task()` 创建的后台任务无引用，GC 可能回收导致静默失败
  - 方案：使用 `weakref.WeakSet` 引用集合，GC 安全

### R5 — 测试补强 ✅ 已完成

- [x] **为 API 路由添加 `TestClient` 测试**
  - 文件：新建 `tests/test_api_and_thread_safety.py`（12 个测试）
  - 覆盖：CORS 头、任务列表、索引分类、deep/screen/portfolio 任务创建、API Key 认证（拒绝/允许）
  - Mock `_execute_graph` 避免真实 LLM 调用
  - 修复 API Key 认证中间件：改用 `JSONResponse` 替代 `raise HTTPException`

- [x] **为 `no_proxy()` 添加多线程测试**
  - 测试：环境变量隔离、代理键保存/恢复、嵌套上下文
  - 验证：多个线程同时进入 `no_proxy()` 上下文，各自的环境变量互不影响

### R6 — 代码规范收尾 ✅ 已完成

- [x] **`tracer.py` 的 `import contextvars` 移至文件顶部**
  - 文件：`src/ifa/observability/tracer.py`
  - 方案：移至顶部导入区域

- [x] **`web/views/history.py` 的导入规范化**
  - 文件：`web/views/history.py`
  - 方案：`from datetime import datetime` 移至顶部

- [x] **关键包 `__init__.py` 添加公共 API 导出**
  - 文件：`src/ifa/__init__.py`（build_advisor/build_state/save_report/AdvisorGraph）
  - 文件：`src/ifa/data_tools/__init__.py`（CachedDataToolExecutor/get_default_data_executor）
  - 文件：`src/ifa/llm_clients/__init__.py`（create_llm_client）

### R7 — `advisor_graph.py` 瘦身（跳过）

- [x] **已有充分抽象，无需进一步模板化**
  - 现有辅助方法（`_add_tool_agent`/`_add_tool_loop`/`_add_fund_debate`/`_add_risk_debate`/`_add_to_report`）已提取公共骨架
  - 四种模式拓扑差异大，进一步抽象会降低可读性
---

## 第四轮：判断质量（判断本身是否可靠） ✅ P-A / P-B 已完成

> 起因：2026-10-16 ~ 10-24 服务器连续 6 个交易日、5 只基金的真实日志复盘。
> 硬证据：25 个相邻日对里 **11 次评级翻转（44%）**，其中 017641 逐日交替 BUY/UNDERWEIGHT；
> 30 次评级的置信度 **29 次 Medium、1 次 High、从未 Low**。
> 这一轮不增加功能，只处理「分析跑得很稳、但结论本身不稳」这件事。

### P-A — 评级稳定化（去抖） ✅ 已完成

- [x] **新增 `src/ifa/decisions/` 决策层（纯函数 + 落盘历史，不调 LLM）**
  - `stability.py`：`decide(raw_rating, confidence, history, config, *, as_of_date)` — 与上次生效评级不同时要求**连续 `confirm_runs`（默认 2）次同向**才改口；未达门槛维持生效评级并记「待确认 N/M」；`SELL` 属硬红线跳过确认立即生效；无历史直接采用；非法评级原样透传
  - `history.py`：`RatingHistoryStore` — 每只基金一个 `{rating_history_dir}/{code}.json`，**同一交易日重复跑替换当天那条**（追加会让「连跑两次」冒充「连续两天同向」），`directory=None` 不落盘，读失败按无历史降级
  - 为什么不按「跨 2 档才允许改」：BUY 与 UNDERWEIGHT 在 5 级词表里本就相差 2 档，压不住逐日交替；也不用置信度做闸门 —— 实测无区分度（见 P-C）
- [x] **`AdvisorGraph` 集成**：`_apply_rating_stability()` 在信号解析之后执行；生效评级仍写 `final_rating`（报告/邮件/日志统一用它），原始评级写 `final_rating_raw`，判定细节写 `rating_stability`；`run(..., stabilize=False)` 可单次关闭
- [x] **配置与开关**：`rating_stability_enabled` / `rating_stability_confirm_runs` / `rating_stability_history_max_entries` / `rating_history_dir`；`IFA_RATING_STABILITY` / `IFA_RATING_CONFIRM_RUNS` 环境变量
- [x] **展示**：`daily_analysis.py` 汇总表与 `notify/email.py` 邮件新增「稳定性」列 + 独立小节（维持/待确认/确认变更/红线生效）
- [x] **测试**：`tests/test_rating_stability.py`

### P-B — 评级结算（基于已有日志，零重跑） ✅ 已完成

- [x] **新增 `src/ifa/backtest/settlement.py`**
  - `scan_rating_logs()` 扫 `results/logs/**/*.json`，取 `final_rating` / `final_rating_raw` / `rating_stability`
  - `settle_logged_ratings()` 按多视界（默认 20/60/120 交易日）算事后收益与超额，**生效 vs 原始两套口径 A/B 对照**
  - `ForwardReturnProvider` 前向收益按 `(基金, 日期, 视界)` 缓存，**只缓存已到期视界**；未到期计入 `immature_n` 而非当作 0 收益
  - **绝不调 LLM、绝不重跑分析** —— 重跑会把「当时的判断」污染成「现在的判断」
  - 报告首段声明「两套口径的差异只说明稳定化改变了什么，不证明变好或变坏」（智识诚实）
- [x] **新增 `scripts/settle_ratings.py`**：输出 `results/validation/settled_{date}.md|json`，支持 `--results-dir/--hold-days/--horizons/--since/--until/--modes/--cache-path|--no-cache/--json/--no-write`
- [x] **测试**：`tests/test_settlement.py`

### P-C — 置信度确定性化（未开始）

- [ ] **置信度改由代码从可复现证据推导，不再采信 LLM 自述**
  - 现状问题：30 次评级里 29 次 Medium、1 次 High、从未 Low —— 这个字段目前不携带任何信息，冒烟测试也无法用它识别「模型在瞎猜」
  - 方案：用确定性指标合成分数再映射到 `Low/Medium/High`：数据完整度（关键工具是否失败/降级）、估值锚是否存在（乐咕乐股只覆盖 12 个指数）、跟踪误差/折溢价是否越界、辩论分歧度（Bull/Bear 裁决差异）、稳定性历史一致度（连续同向次数）
  - 保留 LLM 自述为 `confidence_llm_raw` 供对照，**不删除原始信号**
  - 验收：同一份日志重算得到同一置信度（可复现）；置信度与事后超额有可见单调关系（分档校准不再是单桶）

### P-D — 交易纪律层（未开始）

- [ ] **把评级翻译成可执行的持仓动作，而不是让用户自己猜「BUY 是买多少」**
  - 输出：目标仓位区间、单只上限、调仓触发条件（偏离阈值 + 冷静期）、与现有持仓的差额动作
  - 只产生「建议动作 + 触发条件」，**不接券商、不下单**；跨境/债券/单只上限等约束复用 `portfolio/weights.py` 的确定性校验
  - 验收：给定评级序列与持仓，动作是确定的、可回放的；与稳定性闸门联动（待确认期间不许给出加仓动作）

### P-E — 邮件纳入新信号 + 性能（未开始）

- [ ] **邮件把稳定化与结算结论带出来**：稳定性小节已有；补「本周结算摘要」与「待确认中」提醒
- [ ] **压缩单次运行耗时**：deep 模式每只基金 2.5–4 分钟（5 只 12.5–21 分钟），实测 98.5% 时间在等 LLM
  - 已做：辩论轮数默认 1（2 轮时辩论段独占 86%）、辩论历史截断、信号确定性解析替代 LLM 抽取
  - 待评估：并发跑多只基金（注意 `py_mini_racer` 构造必须串行化）、`deep_simple` 兜底路径、数据工具缓存命中率
