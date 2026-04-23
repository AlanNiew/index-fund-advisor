# IFA - AI 驱动的指数基金分析工具

基于 LangGraph 多 Agent 架构，对中国 A 股指数基金进行深度分析、筛选对比和组合配置建议。

## 功能

- **单只基金深度分析** — 输入基金代码，从业绩、持仓、风险等十余个维度生成分析报告
- **基金筛选对比** — 通过自然语言或结构化条件筛选指数基金，多维度对比
- **组合配置建议** — 基于风险偏好（保守/稳健/积极/成长），推荐指数基金组合方案
- **指数估值分析** — PE/PB/盈利率/股息率四大指标 + 近 10 年历史百分位 + 估值判断
- **三种估值信号** — 盈利收益率法、博格公式（PE）、博格公式（PB），自动根据指数类型选择适用方法，生成买入/卖出/持有信号

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

2. 编辑 `.env`，根据使用的 LLM 提供方填入对应的 Key：

```
OPENAI_API_KEY=sk-...
AZURE_OPENAI_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
```

3. 配置文件位于 `src/ifa/default_config.py`，默认使用 Azure OpenAI。修改 `last_config.py` 或编辑默认配置可切换提供方和模型：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `llm_provider` | LLM 提供方 | `azure` |
| `deep_think_llm` | 深度推理模型 | `gpt-5.4` |
| `quick_think_llm` | 快速调用模型 | `gpt-5.4-mini` |
| `backend_url` | API 基础地址 | `YOUR_AZURE_API_URL` |

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

浏览器访问 `http://localhost:8501`，提供深度分析、筛选对比和组合配置三个页面。

### REST API

```bash
ifa-api
```

服务启动在 `http://localhost:8000`，异步任务模式：

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

Agent 可使用 33 个数据工具，覆盖以下维度：

| 类别 | 数量 | 工具示例 |
|------|------|---------|
| **ETF / 指数 / 场外基金** | 5 | ETF 行情、指数行情、成分股、基金净值 |
| **公募基金** | 20 | 基金列表、持仓、风险分析、业绩、费率、盈利概率等 |
| **宏观经济** | 1 | CPI/PPI/PMI/GDP/LPR/SHIBOR/货币供应量（7 种指标） |
| **市场情绪** | 3 | 北向资金、大盘资金流向、融资融券 |
| **行业估值** | 2 | 板块资金流向排名、市场 PE/PB 估值 |
| **指数估值分析** | 1 | 综合估值报告（PE/PB/盈利率/股息率 + 历史百分位） |
| **估值信号** | 1 | 三种方法（盈利收益率/博格PE/博格PB）投资信号 |

数据全部来自 AkShare（底层：东方财富、雪球、中证指数公司、中国债券信息网）。

## 架构

```
                          ┌─────────────────────────────────────┐
                          │        AdvisorGraph (LangGraph)      │
                          │                                     │
  deep 模式:  Fund Analyst ─→ Index Analyst? ─→ Report Generator│
  screen 模式: Fund Screener ─→ Fund Analyst ─→ Report Generator│
  portfolio:  Advisor(R1) ─→ Screener ─→ Analyst ─→ Advisor(R2)│
                                                                    → Report Generator
                          └──────────┬──────────┬─────────────────┘
                                     │          │
                          ┌──────────▼──┐  ┌────▼──────────────┐
                          │ Agent 层     │  │ LLM 客户端层       │
                          │ fund_analyst │  │ OpenAI/Azure/     │
                          │ index_analyst│  │ Anthropic/Google  │
                          │ fund_screener│  └───────────────────┘
                          │ portfolio_   │
                          │   advisor    │
                          │ report_gen   │
                          └──────┬───────┘
                                 │
                          ┌──────▼───────────┐
                          │ 数据工具层（缓存） │
                          └──────┬───────────┘
                                 │
                          ┌──────▼───────────┐
                          │ 数据流层 (AkShare) │
                          └──────────────────┘
```

每种模式使用两个 LLM：`quick_llm` 负责工具调用和分析，`deep_llm` 负责报告生成和深度推理。

## 开发

```bash
# 代码检查
ruff check .
ruff format .

# 类型检查
mypy src

# 测试
pytest
```

## 技术栈

- **LLM 框架**: LangChain Core + LangGraph
- **数据源**: AkShare（中国 A 股市场数据）
- **CLI**: Typer + Rich
- **Web**: Streamlit
- **API**: FastAPI + Uvicorn
- **Python**: >= 3.10
