# IFA - AI 驱动的指数基金分析工具

基于 LangGraph 多 Agent 辩论架构，对中国 A 股指数基金进行深度分析、筛选对比和组合配置建议。

## 功能

- **单只基金深度分析** — 输入基金代码，从业绩、持仓、风险、估值等十余个维度生成分析报告，含看涨/看跌研究员多轮辩论
- **基金筛选对比** — 通过自然语言或结构化条件筛选指数基金，多维度对比，含辩论裁决
- **组合配置建议** — 基于风险偏好（保守/稳健/积极/成长），推荐指数基金组合方案，含积极/保守/中立三方风险辩论
- **指数估值分析** — PE/PB/盈利率/股息率四大指标 + 近 10 年历史百分位 + 估值判断
- **三种估值信号** — 盈利收益率法、博格公式（PE）、博格公式（PB），自动根据指数类型选择适用方法，生成买入/卖出/持有信号
- **多 Agent 辩论机制** — 看涨/看跌研究员对抗辩论（默认 2 轮）+ 三方风险辩论，由经理 Agent 裁决
- **BM25 记忆系统** — 中英混合分词的情景记忆，跨次分析积累经验
- **决策反思** — 基于实际收益/亏损回顾历史决策质量，更新 Agent 记忆

## 安装

```bash
# 克隆项目
git clone <repo-url>
cd index-fund-advisor

# 创建虚拟环境并安装依赖
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## 配置

1. 复制环境变量模板并填写 API Key：

```bash
cp .env.example .env
```

1. 编辑 `.env`，根据使用的 LLM 提供方填入对应的 Key：

```ini
OPENAI_API_KEY=sk-...
AZURE_OPENAI_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
ZHIPUAI_API_KEY=...
```

1. 配置文件位于 `src/ifa/default_config.py`，默认使用智谱 AI。修改 `last_config.py` 或编辑默认配置可切换提供方和模型：

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `llm_provider` | LLM 提供方 | `zhipu` |
| `deep_think_llm` | 深度推理模型 | `glm-5.2` |
| `quick_think_llm` | 快速调用模型 | `glm-5-turbo` |
| `backend_url` | API 基础地址 | `https://open.bigmodel.cn/api/coding/paas/v4` |
| `max_debate_rounds` | 基金辩论轮数 | `2` |
| `max_risk_discuss_rounds` | 风险辩论轮数 | `2` |

支持的全部提供方：`openai`、`azure`、`anthropic`、`google`、`ollama`、`openrouter`、`qwen`、`zhipu`、`xai`

## 使用

### CLI 命令行

```bash
# 单只基金深度分析
ifa analyze 510300 --date 2024-01-15

# 基金筛选
ifa screen --query "规模大于10亿的沪深300被动指数基金" --top 10
ifa screen --category 沪深指数 --method 被动指数型

# 组合配置建议
ifa portfolio --risk moderate --amount 100000

# 快速查询（不经过 LLM）
ifa search 沪深300
ifa info 510300

# 查看当前配置
ifa config
```

### Web 界面

```bash
ifa-web
```

浏览器访问 `http://localhost:8501`，提供深度分析、筛选对比和组合配置三个页面，含 Plotly 交互图表和回测可视化。

### REST API

```text
# 注意：无注册脚本，需直接用 uvicorn 启动
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

服务启动在 `http://localhost:8000`，支持 API Key 认证，异步任务模式：

```bash
# 提交深度分析
curl -X POST http://localhost:8000/api/v1/analyze/deep \
  -H "Content-Type: application/json" \
  -d '{"fund_code": "510300", "analysis_date": "2024-01-15"}'

# 查询任务状态
curl http://localhost:8000/api/v1/tasks/{task_id}
```

API 端点：

- `POST /api/v1/analyze/deep` — 深度分析
- `POST /api/v1/analyze/screen` — 筛选对比
- `POST /api/v1/analyze/portfolio` — 组合配置
- `GET /api/v1/tasks/{task_id}` — 查询任务状态
- `GET /api/v1/funds/search?q=关键词` — 快速搜索
- `GET /api/v1/funds/{code}/basic` — 基金基本信息

## 数据工具

Agent 可使用 36 个数据工具（`src/ifa/agents/tools/`），覆盖以下维度：

| 类别 | 数量 | 来源文件 | 工具示例 |
| --- | --- | --- | --- |
| **公募基金** | 20 | `public_fund_tools.py` | 基金列表、持仓、风险分析、业绩、费率、盈利概率等 |
| **宏观经济** | 8 | `macro_tools.py` | 宏观指标（CPI/PPI/PMI/GDP/LPR/SHIBOR/货币供应量）、北向资金、资金流向、融资融券、估值分析、估值信号 |
| **ETF / 指数** | 5 | `etf_index_tools.py` | ETF 行情、指数行情、基金净值 |
| **成分股** | 3 | `constituent_tools.py` | 成分股概览、行业分布、成分股表现 |

数据全部来自 AkShare（底层：东方财富、雪球、中证指数公司、中国债券信息网）。

## 架构

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

每种模式使用两个 LLM：`quick_llm` 负责工具调用和辩论，`deep_llm` 负责报告生成和关键裁决。Report Generator 会整合辩论裁决结果生成最终报告。

## 开发

```bash
# 代码检查
ruff check .
ruff format .

# 类型检查
mypy src

# 测试（148 个测试，覆盖 8 个模块）
pytest
pytest tests/test_core.py::TestBacktestEngine::test_max_drawdown   # 单个测试
pytest -x             # 遇到第一个失败即停止
```

## 技术栈

- **LLM 框架**: LangChain Core + LangGraph
- **数据源**: AkShare（中国 A 股市场数据）
- **CLI**: Typer + Rich
- **Web**: Streamlit + Plotly
- **API**: FastAPI + Uvicorn
- **Python**: >= 3.10
