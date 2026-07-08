# IFA — AI 驱动的中国指数基金分析工具

基于 LangGraph 多 Agent 辩论架构，对中国 A 股指数基金做深度分析、筛选对比和组合配置。

> **智识诚实声明**：本工具输出的评级（BUY/HOLD/SELL）与置信度由统计模型（多 Agent 辩论）生成，**不构成任何投资建议**，其历史预测准确率未经独立验证。报告中的客观数据（估值百分位、PE/PB、费率、规模、持仓）来自公开数据源，可独立核查；模型的判断部分仅供参考与学习。

---

## 功能一览

| 能力 | 说明 | 是否调 LLM |
|------|------|:---:|
| **单基金深度分析** | 业绩/持仓/风险/估值/成分股十余维度，含看涨 vs 看跌研究员多轮辩论 | ✅ |
| **基金筛选对比** | 自然语言或结构化条件筛选指数基金，含辩论裁决 | ✅ |
| **组合配置建议** | 按风险偏好（保守/稳健/积极/成长）推荐组合，含三方风险辩论 | ✅ |
| **指数估值分析** | PE/PB/ROE/股息率/盈利收益率 + 历史百分位 + 估值判断 | ❌ |
| **三种估值信号** | 盈利收益率法 / 博格公式（PE）/ 博格公式（PB），自动按指数类型选择 | ❌ |
| **快速查询** | 基金搜索、基本信息、配置查看 | ❌ |
| **买入持有回测** | 年化收益、最大回撤、Sharpe、波动率、月度收益、净值曲线 | ❌ |
| **评级 vs 实际收益验证** | 跑历史分析，对比评级与事后收益，输出命中率/Wilson CI/混淆矩阵/双基准对比 | ✅ |

---

## 安装

需要 **Python ≥ 3.10**。

```bash
git clone <repo-url>
cd index-fund-advisor

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 基础安装（CLI / Web / API）
pip install -e ".[dev]"

# 如需接入 MCP 客户端（Claude Desktop 等）
pip install -e ".[mcp]"

# 如需锁定到经 CI 验证的依赖版本（推荐生产/协作时使用）
pip install -r requirements.lock && pip install -e . --no-deps
```

`-e` 是 editable install，会同时把 `ifa`、`ifa-web`、`ifa-mcp` 三个入口脚本注册到 PATH。
`requirements.lock` 由 `pip-compile` 生成（`pip-compile pyproject.toml --extra dev --extra mcp --no-emit-index-url -o requirements.lock`），精确钉死全部传递依赖。CI 按锁文件安装以保证可复现。

---

## 配置

### 1. LLM API Key

复制模板并填写：

```bash
cp .env.example .env
```

`.env` 支持的 Key（按所用提供方填写其一即可）：

```ini
OPENAI_API_KEY=sk-...
AZURE_OPENAI_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
ZHIPUAI_API_KEY=...        # 默认提供方，必填
```

> **默认配置使用智谱 GLM，需要 `ZHIPUAI_API_KEY`。** 切换提供方见下文「配置项」。

### 2. 可选环境变量

| 变量 | 用途 | 默认 |
|------|------|------|
| `IFA_API_KEY` | API 服务鉴权（**留空 = 不启用认证，所有路由开放**） | 空 |
| `IFA_CORS_ORIGINS` | API CORS 允许来源 | `*` |
| `IFA_TASK_TTL` | API 异步任务保留时长（秒） | `3600` |
| `IFA_TASK_MAX_SIZE` | API 任务存储上限 | `1000` |
| `IFA_RESULTS_DIR` | 分析报告输出目录 | `<项目根>/results` |
| `IFA_LOCAL_DATA_DIR` | 本地数据/缓存根目录 | `<项目根>/local_data` |

### 3. 配置项（`src/ifa/default_config.py`）

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `llm_provider` | `zhipu` | LLM 提供方，可选：`openai` / `azure` / `anthropic` / `google` / `ollama` / `openrouter` / `qwen` / `zhipu` / `xai` |
| `deep_think_llm` | `glm-5.2` | 深度推理（报告生成、关键裁决） |
| `quick_think_llm` | `glm-5.2` | 快速调用（工具调用、辩论）。**不要用最便宜的 turbo 档**——结构化输出在弱模型上不可靠，会污染整条分析管道 |
| `backend_url` | `https://open.bigmodel.cn/api/coding/paas/v4` | API 基础地址 |
| `enable_debate` | `True` | 是否启用辩论（关闭后退化为 `deep_simple`） |
| `max_debate_rounds` | `2` | 基金辩论轮数 |
| `max_risk_discuss_rounds` | `2` | 风险辩论轮数 |
| `internal_language` | `English` | Agent 内部推理语言（保持英文以确保推理质量） |
| `final_output_language` | `Chinese` | 最终报告语言 |
| `max_recur_limit` | `150` | LangGraph 递归上限 |
| `timeout` | `180` | 单次分析超时（秒） |

**切换提供方示例**：编辑 `src/ifa/default_config.py` 或运行 `ifa config` 后手动写入 `src/ifa/last_config.py`：

```python
LAST_CONFIG = {
    'llm_provider': 'anthropic',
    'deep_think_llm': 'claude-sonnet-4-5',
    'quick_think_llm': 'claude-sonnet-4-5',
}
```

---

## 使用方式

IFA 提供 **四种入口**：CLI、Web、REST API、MCP Server。

### ① CLI 命令行

```bash
# —— 经 LLM 的深度分析 ——

# 单基金深度分析（含 Bull/Bear 辩论）
ifa analyze 510300 --date 2024-01-15
ifa analyze 159919                      # 默认分析当天

# 基金筛选（含辩论裁决）
ifa screen --query "规模大于10亿的沪深300被动指数基金" --top 10
ifa screen --category 沪深指数 --method 被动指数型
ifa screen -c 中证指数 -m 增强指数型 -n 5

# 组合配置建议（含三方风险辩论）
ifa portfolio --risk moderate --amount 100000
ifa portfolio -r conservative           # 金额可选，默认 0

# —— 纯数据查询（不调 LLM，秒级返回）——

ifa search 沪深300                       # 关键词模糊匹配基金列表
ifa search "300" --limit 5
ifa info 510300                         # 单只基金基本信息
ifa config                              # 查看当前运行时配置
```

**CLI 命令完整参考**：

| 命令 | 参数 | 选项 | 说明 |
|------|------|------|------|
| `analyze <code>` | 基金代码 | `--date / -d`（默认今天）、`--debug` | 深度分析 |
| `screen` | — | `--category / -c`（默认`全部`）、`--method / -m`（默认`全部`）、`--query / -q`、`--top / -n`（默认`10`）、`--debug` | 筛选对比 |
| `portfolio` | — | `--risk / -r`（默认`moderate`）、`--amount / -a`（默认`0`）、`--debug` | 组合配置 |
| `search <kw>` | 关键词 | `--limit / -n`（默认`20`） | 模糊搜索 |
| `info <code>` | 基金代码 | — | 基本信息查询 |
| `config [k] [v]` | — | — | 查看/说明配置（写入需手动编辑 `last_config.py`） |

> `risk` 取值：`conservative`（保守）/ `moderate`（稳健）/ `aggressive`（积极）/ `growth`（成长）。

### ② Web 界面

```bash
ifa-web
```

浏览器打开 `http://localhost:8501`，提供五个页面：

| 页面 | 功能 | 关键输入 |
|------|------|---------|
| **首页** | 项目介绍 | — |
| **基金分析** | 深度分析 + 可选回测 | 基金代码、分析日期、回测开关（3/6/12/24 月）、初始金额 |
| **筛选对比** | 结构化或自然语言筛选 | 指数类别、跟踪方式、返回数量（5–30）/ 查询文本 |
| **组合配置** | 按风险偏好生成方案 | 风险偏好、投资金额 |
| **历史记录** | 浏览过往报告（默认 `results/` 下 Markdown，按时间倒序，前 50 份） | — |

含 Plotly 交互图表（净值曲线、月度收益柱状图、回测指标卡）。`AdvisorGraph` 经 `@st.cache_resource` 缓存复用。

### ③ REST API

```bash
# 启动（无注册脚本，直接 uvicorn）
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

**鉴权**：设置 `IFA_API_KEY` 环境变量后，所有请求需带请求头 `X-API-Key: <你的key>`。**留空 = 完全开放，请谨慎。**

**端点**（统一前缀 `/api/v1`）：

| Method | Path | 说明 | 是否调 LLM |
|--------|------|------|:---:|
| `POST` | `/analyze/deep` | 深度分析（异步任务） | ✅ |
| `POST` | `/analyze/screen` | 筛选对比（异步任务） | ✅ |
| `POST` | `/analyze/portfolio` | 组合配置（异步任务） | ✅ |
| `GET` | `/tasks/{task_id}` | 查询任务状态/结果 | — |
| `GET` | `/tasks` | 列出所有任务 | — |
| `GET` | `/funds/search?q=&limit=` | 模糊搜索 | ❌ |
| `GET` | `/funds/{code}/basic` | 基金基本信息 | ❌ |
| `GET` | `/indexes/categories` | 指数类别与跟踪方式枚举 | ❌ |

**示例**：

```bash
# 提交深度分析（异步）
curl -X POST http://localhost:8000/api/v1/analyze/deep \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $IFA_API_KEY" \
  -d '{"fund_code": "510300", "analysis_date": "2024-01-15"}'
# → {"task_id": "...", "status": "pending", "mode": "deep", ...}

# 轮询结果
curl http://localhost:8000/api/v1/tasks/{task_id} -H "X-API-Key: $IFA_API_KEY"

# 同步快速查询
curl "http://localhost:8000/api/v1/funds/search?q=沪深300&limit=5" -H "X-API-Key: $IFA_API_KEY"
```

异步任务在内存中存储（TTL `IFA_TASK_TTL`=3600s，上限 `IFA_TASK_MAX_SIZE`=1000），每 60 秒清理过期项。

### ④ MCP Server（接入 Claude 等）

把 IFA 的数据/估值/分析能力暴露给 MCP 客户端，让 AI 在对话里直接查基金、看估值、跑分析。采用 stdio 传输，无需单独起服务。

```bash
pip install -e ".[mcp]"
```

**Claude Desktop** 配置文件加入：

> macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
> Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ifa": { "command": "ifa-mcp" }
  }
}
```

**Claude Code** 直接命令行添加：

```bash
claude mcp add ifa -- ifa-mcp
```

**暴露的 9 个工具**：

| 工具 | 说明 | 需 LLM Key |
|------|------|:---:|
| `search_funds(query, limit)` | 关键词/代码搜索公募基金 | ❌ |
| `get_fund_info(code)` | 基金基本信息 | ❌ |
| `get_index_valuation_metrics(index_name)` | 结构化估值指标（PE/PB/ROE/股息率/盈利收益率/ERP） | ❌ |
| `get_index_valuation_report(index_name)` | 综合估值报告（含历史百分位） | ❌ |
| `get_valuation_signal(index_name)` | 估值信号（买入/持有/卖出） | ❌ |
| `screen_index_funds(index_category, tracking_method)` | 按分类 + 跟踪方式筛选 | ❌ |
| `get_index_constituents(index_name)` | 指数成份股 | ❌ |
| `get_north_flow(symbol)` | 北向资金流向（市场情绪） | ❌ |
| `analyze_fund(code, analysis_date, mode)` | AI 深度分析（`deep_simple` 快速 30–60s / `deep` 含辩论 1–3 分钟） | ✅ |

> 数据/估值工具走 AkShare 公开数据，无需 Key；`analyze_fund` 需在 `.env` 配置有效的 LLM API Key。完整说明见 [`MCP.md`](MCP.md)。

---

## 分析模式与架构

### 四种分析模式（LangGraph 编排）

所有模式由 `AdvisorGraph`（`src/ifa/graph/advisor_graph.py`）编排，共享统一状态 `IFAdvisorState`。每种模式用两个 LLM：`quick_llm`（工具调用/辩论）和 `deep_llm`（报告生成/裁决）。

#### `deep` — 单基金深度分析（含辩论，默认）

```
START → Fund Analyst → [ETF/指数基金?] → Index Analyst →
        Bull ↔ Bear 辩论（2 轮） → Research Manager 裁决 →
        Report Generator → END
```

- Index Analyst 仅当标的为 ETF/指数基金时执行（条件边 `should_skip_index_analyst`）
- Bull/Bear 交替发言，终止条件 `count >= 2 × max_debate_rounds`
- Research Manager 裁决结果传递给 Report Generator

#### `deep_simple` — 单基金快速分析（无辩论）

```
START → Fund Analyst → [ETF/指数基金?] → Index Analyst →
        Report Generator → END
```

通过 `enable_debate: false` 或指定 `deep_simple` 启用。

#### `screen` — 基金筛选对比（含辩论）

```
START → Fund Screener → Fund Analyst →
        Bull ↔ Bear 辩论 → Research Manager →
        Report Generator → END
```

#### `portfolio` — 组合配置建议（含三方风险辩论）

```
START → Portfolio Advisor (R1) → Fund Screener → Fund Analyst →
        Portfolio Advisor (R2) →
        Aggressive ↔ Conservative ↔ Neutral 风险辩论（2 轮） →
        Portfolio Manager 裁决 → Report Generator → END
```

### 整体架构

```
                          ┌──────────────────────────────────────────┐
                          │        AdvisorGraph (LangGraph)          │
                          │                                          │
  deep:       Fund Analyst ─→ Index Analyst? ─→ Bull/Bear 辩论      │
                                                            ↓        │
                                              Research Manager 裁决   │
                                                            ↓        │
                                              Report Generator       │
                          │                                          │
  screen:     Fund Screener ─→ Fund Analyst ─→ Bull/Bear 辩论        │
                                               ↓                     │
                                    Research Manager → Report Gen    │
                          │                                          │
  portfolio:  Advisor(R1) → Screener → Analyst → Advisor(R2)         │
                                               ↓                     │
                              Aggressive/Conservative/Neutral 辩论   │
                                               ↓                     │
                              Portfolio Manager → Report Generator   │
                          └──────────┬──────────┬────────────────────┘
                                     │          │
                          ┌──────────▼──┐  ┌────▼──────────────┐
                          │ Agent 层     │  │ LLM 客户端层       │
                          │ (记忆/工具)  │  │ OpenAI/Azure/     │
                          │              │  │ Anthropic/Google  │
                          └──────┬───────┘  └───────────────────┘
                                 │
                          ┌──────▼───────────┐
                          │ 数据工具层（缓存） │
                          └──────┬───────────┘
                                 │
                          ┌──────▼───────────┐
                          │ 数据流层 (AkShare) │
                          └──────────────────┘
```

### 数据工具

Agent 可使用 **36 个数据工具**（`src/ifa/agents/tools/`），全部来自 AkShare（底层：东方财富、雪球、中证指数公司、中国债券信息网）：

| 类别 | 数量 | 文件 | 代表工具 |
|------|:---:|------|---------|
| 公募基金 | 20 | `public_fund_tools.py` | 基金列表、持仓、风险分析、业绩、费率、盈利概率、资产配置 |
| 宏观经济 | 8 | `macro_tools.py` | CPI/PPI/PMI/GDP/LPR/SHIBOR、北向资金、融资融券、估值信号 |
| ETF / 指数 | 5 | `etf_index_tools.py` | ETF 行情、指数行情、基金净值、成份股 |
| 成分股 | 3 | `constituent_tools.py` | 成份股概览、行业分布、成份股表现 |

### 记忆与反思

- 每个 Agent 可携带 `FinancialSituationMemory`（`src/ifa/agents/memory.py`），基于 BM25 检索历史相似情景，中英混合分词（中文按字、英文按词）。
- 条目上限默认 **1000 条**（`_DEFAULT_MAX_SITUATIONS`），FIFO 淘汰。可在配置中通过 `max_situations` 调整。
- `Reflector`（`src/ifa/graph/reflection.py`）在决策后基于实际收益/亏损反思并更新各 Agent 记忆。

> **诚实标注**：反思系统用市场短期收益强化 Agent 记忆，存在幸存者偏差风险——短期涨跌是噪声，把它编码成「经验」可能强化错误模式。这是已知的设计权衡。

### 回测引擎

`run_backtest()`（`src/ifa/backtest/engine.py`）采用 **买入持有** 策略，自动按资产类型分流取价（ETF/指数走行情，公募基金走历史净值）：

```python
from ifa.backtest import run_backtest, format_backtest_report

result = run_backtest(
    symbol="510300",
    start_date="2023-01-01",
    end_date="2024-01-01",
    initial_investment=100000.0,
)
print(format_backtest_report(result))
```

输出指标：总收益率、年化收益、最大回撤、Sharpe（无风险利率 2%）、年化波动率、交易天数、月度收益、净值曲线（采样到最多 120 点）。数据不足 2 条直接返回带 `error` 的空结果。

### 评级 vs 实际收益 回测验证

**用数字回答「AI 多 Agent 辩论生成的评级，在历史上是否有预测力」**。跑历史分析 → 取事后实际收益 → 统计命中率 / Wilson 置信区间 / 混淆矩阵 / 双基准对比。源码：`src/ifa/backtest/rating_validator.py`。

> **智识诚实声明**：本验证**不证明**评级「有效」或「无效」，仅描述其在给定样本上的历史表现。样本量 < 30 时统计结论无显著性。过往表现不代表未来结果。

#### CLI 用法

```bash
# 对一批 ETF 在指定日期跑分析，持有 60 交易日后看收益
ifa validate --codes 510300,159919,510500 --dates 2024-01-15,2024-04-15 --hold-days 60

# 自动生成过去 6 个月每月一个分析日期
ifa validate --codes 510300,159919 --months-back 6 --hold-days 60

# 显式开启记忆更新（注意幸存者偏差风险，默认关闭）
ifa validate --codes 510300 --months-back 3 --update-memory
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--codes` | 必填 | 逗号分隔 ETF/指数基金代码 |
| `--dates` | — | 逗号分隔分析日期，与 `--months-back` 二选一 |
| `--months-back` | — | 自动生成过去 N 个月每月一个日期 |
| `--hold-days` | `60` | 评级后持有多少交易日看收益 |
| `--update-memory` | `False` | **显式开关**：把结果喂回反思系统（默认关闭以防幸存者偏差反馈环） |
| `--output, -o` | `results/validation/` | 报告输出目录 |

#### 独立脚本（可 cron 调度）

```bash
python scripts/run_rating_validation.py                          # 默认 ETF × 过去 3 个月
python scripts/run_rating_validation.py --months-back 6 --hold-days 90
```

#### 输出指标解读

| 指标 | 含义 | 怎么读 |
|------|------|--------|
| **看涨命中率** | BUY/STRONG_BUY 中实际收益 > 0 的比例 | 单看这个没意义，必须结合 CI 和基准 |
| **95% 置信区间** | Wilson 二项分布 CI | 区间宽=样本不足；区间不含 50% 才有统计意义 |
| **Alpha vs 随机** | 命中率 − 50% | 正值=比抛硬币好，但需 CI 排除 50% |
| **Alpha vs 沪深300** | 命中率 − 同期大盘上涨比例 | 正值=评级选股跑赢被动持有大盘 |
| **混淆矩阵** | 5 档评级 × {涨/跌} | 看 BUY/SELL 的分布是否均衡（全是 HOLD=无信息量） |

#### 设计约束（芒格视角评审结论）

1. **小样本必须标注 CI**——不标 CI 的命中率是欺骗（噪声不是信号）
2. **默认不接回反思系统**——防止「用随机性强化随机性」的反馈污染（`--update-memory` 需用户显式开启）
3. **必须有基准对比**——全是 HOLD 的策略也能高命中率，必须对比随机基准和大盘
4. **仅支持 ETF/指数基金**——避开公募基金 `get_fund_history_nav` 的 `tail(120)` 截断问题

---

## 开发

```bash
# 代码检查
ruff check .
ruff format .

# 类型检查
mypy src

# 测试（225 个测试，覆盖 14 个模块）
pytest
pytest tests/test_core.py::TestBacktestEngine::test_max_drawdown   # 单个测试
pytest -x                                                          # 遇到第一个失败即停
```

**健壮性约定**（修改代码时遵循，详见 [`CLAUDE.md`](CLAUDE.md)）：

- LLM 调用统一走 `invoke_llm_safely()` / `invoke_chain_safely()`，禁止裸调用 `llm.invoke()`
- `AdvisorGraph.run()` 顶层 try/except 保护，失败仍落盘日志并返回含 `error` 字段的状态
- 缓存读写异常隔离，磁盘故障降级为直接执行
- vendor fallback 链：`route_to_vendor()` 逐个 try/except，失败自动尝试下一个
- Agent 报告经 `truncate_report(max_chars=3000)` 截断，防 token 溢出
- `SignalProcessor` 对 LLM 输出做合法性校验 + 模糊匹配，非法值 fallback 到 `HOLD` / `Medium`
- 每份报告顶部**程序硬注入智识诚实声明**（`report_generator.py`），不依赖 LLM 自觉输出

**Ruff 规则**：忽略 E501（行长）/ F403,F405（星号导入）/ E402（导入顺序）；`isort.known-first-party` = `["ifa","api","web"]`。

**包布局**：`packages.find` 配置 `where=["src"]`、`include=["ifa*"]`，`src/ifa` 是唯一主包（含 `ifa.cli` 子包）；`api/`、`web/` 位于项目顶层，通过 CLI 入口的 sys.path 注入在开发模式下可导入。

---

## 技术栈

| 层 | 技术 |
|----|------|
| LLM 框架 | LangChain Core + LangGraph |
| 数据源 | AkShare（中国 A 股市场数据） |
| CLI | Typer + Rich |
| Web | Streamlit + Plotly |
| API | FastAPI + Uvicorn |
| MCP | FastMCP（stdio） |
| Python | ≥ 3.10 |

---

## 项目结构

```
index-fund-advisor/
├── src/ifa/                  # 主包
│   ├── agents/               # LangGraph ReAct Agent + 工具 + 记忆
│   │   ├── analysts/         # fund / index / screener
│   │   ├── researchers/      # bull / bear（带记忆对抗辩论）
│   │   ├── managers/         # portfolio / research / report
│   │   ├── risk_mgmt/        # aggressive / conservative / neutral
│   │   ├── tools/            # 36 个数据工具（4 类）
│   │   ├── prompts/          # Agent prompt 模板
│   │   └── memory.py         # BM25 情景记忆
│   ├── graph/                # LangGraph 编排 + 反思 + 信号处理
│   ├── dataflows/            # AkShare 封装（含重试、资产类型检测）
│   ├── data_tools/           # 声明式工具注册表 + 缓存执行器
│   ├── llm_clients/          # 多提供方 LLM 客户端工厂
│   ├── backtest/             # 买入持有回测引擎 + 评级验证模块
│   ├── observability/        # per-request tracing
│   ├── portfolio/            # 风险偏好模型 + 配置策略
│   ├── mcp/                  # FastMCP server（9 个工具）
│   ├── cli/                  # Typer CLI 入口（ifa / ifa-web）
│   └── default_config.py     # 默认配置 + 运行时构建
├── web/                      # Streamlit 多页应用
├── api/                      # FastAPI 异步任务 + 鉴权
├── tests/                    # 225 个测试（14 个模块）
├── scripts/                  # 每日分析等脚本
├── release/                  # PyPI 轻量发行脚手架（assemble.py）
├── pyproject.toml
└── README.md / CLAUDE.md / MCP.md
```

> **`release/` 说明**：该目录是 PyPI 轻量发行的构建脚手架，`assemble.py` 从 `src/ifa` 动态拷贝 MCP + 数据层子集。**`release/src/` 和 `release/dist/` 是生成物，已在 `.gitignore` 中忽略，不要手动编辑。**

---

## 许可证

见 [`release/LICENSE`](release/LICENSE)。
