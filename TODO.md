# IFA 项目优化任务清单

> 基于 TradingAgents / FinRobot 等优秀开源项目对比分析，按优先级排列。

## P0 — 健壮性加固（防崩溃）

- [ ] **`run()` 方法加顶层异常保护**
  - 文件：`src/ifa/graph/advisor_graph.py`
  - 问题：`graph.invoke()` 任何异常直接崩溃，`_log_state` 不执行，状态丢失
  - 方案：try/except 包裹，异常时仍保存已完成的日志，返回错误信息而非抛异常
  - 同时修复第 165 行的残留死代码（空 StateGraph 创建后立即被覆盖）

- [ ] **`invoke_llm_safely` 全局统一使用**
  - 文件：`src/ifa/graph/reflection.py`、`src/ifa/graph/signal_processing.py`
  - 问题：`Reflector._reflect_on_component()` 和 `SignalProcessor` 直接调用 `llm.invoke()`，无重试无降级
  - 方案：所有 LLM 调用统一走 `invoke_llm_safely()`

- [ ] **`_log_state` 安全字典访问**
  - 文件：`src/ifa/graph/advisor_graph.py`
  - 问题：硬编码 `["fund_debate_state"]["bull_history"]`，`deep_simple` 模式 KeyError
  - 方案：改用 `.get()` 链式访问 + 空值兜底

- [ ] **`executor.py` 缓存操作异常隔离**
  - 文件：`src/ifa/data_tools/executor.py`
  - 问题：缓存读写失败（磁盘满/权限）阻塞正常工具执行
  - 方案：`_try_read_cache` / `_store_result` / `_save_snapshot_if_needed` 加 try/except，失败时降级为直接执行

- [ ] **`route_to_vendor` fallback 链修复**
  - 文件：`src/ifa/dataflows/interface.py`
  - 问题：构建了 fallback_vendors 但调用无 try/except，第一个供应商失败直接抛异常
  - 方案：加 try/except 包裹 `impl_func()` 调用，失败时 continue 到下一个供应商

## P1 — 数据质量与可靠性

- [ ] **数据清洗管道 `_clean_dataframe`**
  - 文件：新增 `src/ifa/dataflows/data_cleaning.py`
  - 内容：统一处理 datetime 解析 → 缺失值 dropna → 数值类型强制转换 → ffill/bfill
  - 集成点：在 `a_share.py` 的 `_format_table()` 和所有返回 DataFrame 的函数中调用

- [ ] **消息清理机制 `Msg Clear` 节点**
  - 文件：`src/ifa/graph/advisor_graph.py`、`src/ifa/agents/utils.py`
  - 问题：Agent 长对话中 messages 列表不断膨胀，可能触发 token 上限
  - 方案：参照 TradingAgents 的 `create_msg_delete()`，在关键节点后清理历史消息

- [ ] **Agent 状态访问安全化**
  - 文件：`src/ifa/agents/researchers/bull_researcher.py`、`bear_researcher.py`、`src/ifa/agents/managers/research_manager.py`
  - 问题：`state["fund_debate_state"]` 硬编码索引，缺少 `.get()` 保护
  - 方案：统一用 `.get()` 并提供合理的默认空值

- [ ] **Prompt 长度限制**
  - 文件：所有 Agent（researchers、managers、risk_mgmt）
  - 问题：分析报告直接拼入 prompt，超长时可能超出上下文窗口
  - 方案：添加 `_truncate_report(report, max_chars=3000)` 工具函数，截断过长的输入

## P2 — 核心功能增强

- [ ] **回测集成**
  - 新增模块：`src/ifa/backtest/`
  - 功能：基于历史数据验证分析策略的实际收益表现
  - 参照 FinRobot 的 BackTraderUtils，支持自定义策略和评估指标（Sharpe/MaxDrawdown/Returns）
  - 集成到 LangGraph 工作流中，作为可选的分析验证环节

- [ ] **基础测试覆盖**
  - 目录：`tests/`
  - 组件级：数据工具执行、状态初始化、条件边逻辑、信号处理
  - 集成级：图构建不报错、各模式端到端（mock LLM）
  - 工具：pytest + pytest-mock

- [ ] **反思系统增强**
  - 文件：`src/ifa/graph/reflection.py`
  - 问题：`reflect_portfolio_manager` 假设 `risk_debate_state` 存在，非 portfolio 模式 KeyError
  - 方案：根据 mode 条件性调用，缺少辩论状态时跳过对应反思

## P3 — 生产化扩展

- [ ] **可观测性集成（Langfuse / OpenTelemetry）**
  - 功能：per-request tracing，追踪每个 Agent 的 LLM 调用和工具使用
  - 用于：性能分析、成本追踪、质量评估

- [ ] **多数据源扩展**
  - 新增供应商：Tushare、东方财富、Wind（如有授权）
  - 依托已有的 `VENDOR_METHODS` 框架扩展
  - 配置级供应商选择 + 自动降级

- [ ] **Web 界面可视化增强**
  - 文件：`web/views/`
  - 图表：收益曲线、风险散点图、组合配置饼图
  - 历史：分析结果对比、回测报告展示
