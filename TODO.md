# IFA 项目优化任务清单

> 基于 TradingAgents / FinRobot 等优秀开源项目对比分析，按优先级排列。

## P0 — 健壮性加固（防崩溃） ✅ 已完成

- [x] **`run()` 方法加顶层异常保护**
- [x] **`invoke_llm_safely` 全局统一使用**
- [x] **`_log_state` 安全字典访问**
- [x] **`executor.py` 缓存操作异常隔离**
- [x] **`route_to_vendor` fallback 链修复**

## P1 — 数据质量与可靠性 ✅ 已完成

- [x] **数据清洗管道 `clean_dataframe`**
- [x] **消息清理机制 `Msg Clear` 节点**
- [x] **Agent 状态访问安全化**
- [x] **Prompt 长度限制 `truncate_report`**

## P2 — 核心功能增强 ✅ 已完成

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

## P3 — 生产化扩展 ✅ 已完成

- [x] **可观测性集成**
  - 新增模块：`src/ifa/observability/tracer.py`
  - `RequestTracer` + `TraceSpan` 轻量级 per-request 追踪
  - 集成到 `AdvisorGraph.run()`，每次运行自动记录执行时间
  - 追踪日志保存到 `results/traces/{request_id}.json`
  - 无外部依赖，后续可切换到 Langfuse/OTel

- [x] **多数据源扩展**
  - `_KNOWN_DATA_VENDORS` 新增 tushare 供应商
  - 已有 `VENDOR_METHODS` + `route_to_vendor` fallback 架构支持即插即用
  - 配置级供应商选择：`data_vendors` 字典

- [x] **Web 界面可视化增强**
  - 新增 `web/views/charts.py`：Plotly 图表组件（净值曲线、月度收益柱状图、指标卡片）
  - 分析页面集成回测功能：可选回测参数 → 净值曲线 + 月度收益 + 详细报告
  - `analysis.py` 新增回测参数面板（时长、金额）
