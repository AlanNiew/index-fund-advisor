# IFA — AI 驱动的中国指数基金分析工具

基于 LangGraph 多 Agent 辩论架构，对中国 A 股指数基金做深度分析、筛选对比和组合配置。

> **智识诚实声明**：本工具输出的评级（STRONG_BUY/BUY/HOLD/UNDERWEIGHT/SELL）与置信度由统计模型（多 Agent 辩论）生成，**不构成任何投资建议**，其历史预测准确率未经独立验证。报告中的客观数据（估值百分位、PE/PB、费率、规模、持仓）来自公开数据源，可独立核查；模型的判断部分仅供参考与学习。

---

## 功能一览

| 能力 | 说明 | 是否调 LLM |
|------|------|:---:|
| **单基金深度分析** | 业绩/持仓/风险/估值/成分股十余维度，含看涨 vs 看跌研究员多轮辩论 | ✅ |
| **基金筛选对比** | 自然语言或结构化条件筛选指数基金，含辩论裁决 | ✅ |
| **组合配置建议** | 按风险偏好（保守/稳健/积极/成长）推荐组合，含三方风险辩论 | ✅ |
| **指数估值分析** | PE/PB/ROE/股息率（指数自身口径）/盈利收益率 + 历史百分位 + 估值判断；无估值数据的指数会显式标注 | ❌ |
| **三种估值信号** | 盈利收益率法 / 博格公式（PE）/ 博格公式（PB），自动按指数类型选择 | ❌ |
| **快速查询** | 基金搜索、基本信息、配置查看 | ❌ |
| **买入持有回测** | 价格口径与投资者口径双收益、真实无风险利率、费用拖累、最大回撤、Sharpe、波动率、月度收益、净值曲线 | ❌ |
| **评级 vs 实际收益验证** | 跑历史分析，对比评级与事后收益，输出命中率/Wilson CI/混淆矩阵/双基准对比 | ✅ |

---

## 安装

需要 **Python ≥ 3.12**（`requirements.lock` 钉死的 numpy/pandas 版本不带 3.10/3.11 的 wheel）。

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

### 全局安装（推荐：不克隆仓库也能用）

```bash
# 从 Git 仓库安装：--from 写仓库地址，最后一个参数必须是包名 index-fund-advisor
uv tool install --from git+https://github.com/AlanNiew/index-fund-advisor.git index-fund-advisor
# 或从 GitHub Release 下载的 wheel 安装（本项目不发 PyPI）
uv tool install --from ./index_fund_advisor-0.1.0-py3-none-any.whl index-fund-advisor
ifa skill            # 把内置 skill 安装到用户级目录（所有项目可见）
```

`uv tool install` 会创建隔离环境并把 `ifa` 放到 PATH，因此**任意工作目录**都能直接调用 ——
不需要 `cd` 到仓库、也不需要激活 venv。API Key 放用户级 `.env` 即可
（Windows `%APPDATA%\ifa\.env`，其他平台 `~/.config/ifa/.env`）：CLI 会**同时**读取工作目录
向上找到的 `.env` 与用户级 `.env`，先加载者生效（`override=False`）。

**wheel / 全局安装的能力边界**：`ifa`（CLI）与 `ifa-mcp`（需 `[mcp]` 额外依赖）可用；`ifa-web`（Streamlit）
与 REST API 需要仓库检出 —— wheel 里没有 `web/`、`api/`，`ifa-web` 会直接提示「需要仓库检出」并以退出码 1 结束。
发行方式见 [`.github/workflows/release.yml`](.github/workflows/release.yml)：推送 `v*` tag 构建 wheel + sdist
并在冒烟测试后挂到 GitHub Release，**不发布到 PyPI**。

---

## 配置

### 1. LLM API Key

复制模板并填写：

```bash
cp .env.example .env
```

`.env` 支持的 Key（按所用提供方填写其一即可）：

```ini
OPENCODE_API_KEY=...          # 默认提供方（OpenCode Go），必填
OPENAI_API_KEY=sk-...
AZURE_OPENAI_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
ZHIPUAI_API_KEY=...
DEEPSEEK_API_KEY=...
```

> **默认配置使用 OpenCode Go（`opencode`），需要 `OPENCODE_API_KEY`。** 该端点为订阅制，`ifa` 发请求时会自动附带自定义 `User-Agent` 与进程级 `x-opencode-session` 会话头（服务端据此优化路由与提示缓存；可用 `OPENCODE_SESSION_ID` 覆盖会话 ID）。切换提供方见下文「配置项」。

### 2. 可选环境变量

| 变量 | 用途 | 默认 |
|------|------|------|
| `IFA_API_KEY` | API 服务鉴权（**留空 = 不启用认证，所有路由开放**） | 空 |
| `IFA_CORS_ORIGINS` | API CORS 允许来源 | `*` |
| `IFA_TASK_TTL` | API 异步任务保留时长（秒） | `3600` |
| `IFA_TASK_MAX_SIZE` | API 任务存储上限 | `1000` |
| `IFA_RESULTS_DIR` | 分析报告输出目录 | `<项目根>/results` |
| `IFA_LOCAL_DATA_DIR` | 本地数据/缓存根目录 | `<项目根>/local_data` |
| `IFA_LLM_PROVIDER` | 覆盖 `llm_provider`（**优先级最高，不改任何文件即可换模型**） | 空 |
| `IFA_DEEP_LLM` / `IFA_QUICK_LLM` | 覆盖深度/快速模型 | 空 |
| `IFA_BACKEND_URL` | 覆盖 `backend_url`（`custom` 提供方必填） | 空 |
| `IFA_CUSTOM_API_KEY` | `llm_provider=custom` 时的 API Key | 空 |
| `IFA_CONFIG_DIR` | 用户配置文件与用户级 `.env` 所在目录 | Windows `%APPDATA%\ifa`；否则 `~/.config/ifa` |
| `IFA_DATA_SOURCE_TIMEOUT` | 数据源请求（AkShare 内部 `requests`）默认超时秒数 | `30` |
| `IFA_TIMEOUT` / `IFA_DEEP_TIMEOUT` | 覆盖 quick / deep 档 LLM 调用超时（秒） | `120` / `180` |
| `IFA_LLM_MAX_RETRIES` | 覆盖 LLM 重试次数 | `2` |
| `IFA_SMTP_HOST` / `IFA_SMTP_PORT` | 每日邮件报告的 SMTP 服务器与端口（端口留空时按 `IFA_SMTP_USE_SSL` 推导 465 / 587） | 空 / 自动 |
| `IFA_SMTP_USER` / `IFA_SMTP_PASSWORD` | SMTP 登录用户名与密码（QQ / 163 等用**授权码**，不是登录密码；密码建议只走环境变量，不落进 `config.json`） | 空 |
| `IFA_SMTP_SENDER` | 发件人地址（留空复用 `IFA_SMTP_USER`） | 空 |
| `IFA_EMAIL_TO` | 收件人，逗号 / 分号 / 空白分隔 | 空 |
| `IFA_SMTP_USE_SSL` | `true` = SMTPS(465)；`false` = STARTTLS(587) | `true` |
| `IFA_SMTP_TIMEOUT` | SMTP 连接 / 发送超时（秒） | `30` |

### 3. 配置项（`src/ifa/default_config.py`）

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `llm_provider` | `opencode` | LLM 提供方，可选：`opencode` / `openai` / `azure` / `anthropic` / `google` / `ollama` / `openrouter` / `qwen` / `zhipu` / `xai` / `deepseek` / **`custom`（任意 OpenAI 兼容端点）** |
| `deep_think_llm` | `deepseek-v4.1-flash` | 深度推理（报告生成、关键裁决）。两档统一用 V4.1 Flash，不再使用 V4 Pro |
| `quick_think_llm` | `deepseek-v4.1-flash` | 快速调用（工具调用、辩论）。**不要用最便宜的 turbo 档**——结构化输出在弱模型上不可靠，会污染整条分析管道 |
| `backend_url` | `https://opencode.ai/inference/go/v1` | API 基础地址。显式设置的值**优先于**内置端点；`custom` 提供方必须提供。切换提供方后残留的别家内置端点会被自动重置（各提供方默认地址见 [src/ifa/providers.py](<src/ifa/providers.py>)） |
| `custom_api_key` | `None` | 仅 `custom` 使用；通常直接用 `IFA_CUSTOM_API_KEY` |
| `enable_debate` | `True` | 是否启用辩论（关闭后退化为 `deep_simple`） |
| `max_debate_rounds` | `1` | 基金辩论轮数（2 轮会让运行时间显著变长：实测 30.4 分钟的 deep 运行里辩论段独占 86%） |
| `max_risk_discuss_rounds` | `2` | 风险辩论轮数 |
| `internal_language` | `English` | Agent 内部推理语言（保持英文以确保推理质量） |
| `final_output_language` | `Chinese` | 最终报告语言 |
| `max_recur_limit` | `150` | LangGraph 递归上限 |
| `timeout` | `120` | quick 档（工具调用、分析师、辩论）的 LLM 调用超时（秒） |
| `deep_timeout` | `180` | deep 档（报告生成、关键裁决）的 LLM 调用超时（秒）。deep 档产出最终报告，单独放宽 |
| `llm_max_retries` | `2` | LLM 调用重试次数（总尝试 = 重试次数 + 1）。实测挂死请求要读到超时才返回，重试是最大的时间黑洞 |
| `smtp_host` | `None` | SMTP 服务器。与 `smtp_recipients` / `smtp_sender` **缺一不可**：只配了一部分时抛 `EmailConfigError` 并列出缺项，**绝不静默跳过发信** |
| `smtp_port` | `None` | 留空按 `smtp_use_ssl` 推导（465 / 587） |
| `smtp_user` / `smtp_password` | `None` | SMTP 登录凭据；给了用户名却没给密码会报缺 `smtp_password`（QQ / 163 用授权码） |
| `smtp_sender` | `None` | 发件人地址，留空复用 `smtp_user` |
| `smtp_recipients` | `None` | 收件人列表（逗号 / 分号 / 空白分隔） |
| `smtp_use_ssl` | `True` | `True` = SMTPS(465)；`False` = STARTTLS(587) |
| `smtp_timeout` | `30` | SMTP 连接 / 发送超时（秒） |

**切换提供方**（三种方式，优先级由低到高）：

```bash
# ① 写用户配置文件（真正落盘，跨目录/跨机器有效）
ifa config llm_provider deepseek
ifa config deep_think_llm deepseek-reasoner
ifa config quick_think_llm deepseek-chat
ifa config llm_provider           # 查看单项生效值
ifa config --unset llm_provider   # 删除该项
ifa config                        # 查看全部配置 + 配置文件路径

# ② 环境变量（优先级最高，适合容器/CI，不改任何文件）
IFA_LLM_PROVIDER=deepseek IFA_DEEP_LLM=deepseek-reasoner ifa analyze 510300

# ③ 接入任意 OpenAI 兼容端点（自建网关、公司内网、one-api 等）
ifa config llm_provider custom
ifa config backend_url https://your-gateway/v1
ifa config deep_think_llm your-model
export IFA_CUSTOM_API_KEY=sk-...
```

配置文件位置：Windows `%APPDATA%\ifa\config.json`，Linux/macOS `~/.config/ifa/config.json`（可用 `IFA_CONFIG_DIR` 覆盖）。
路径键（如 `memory_dir`）由项目位置现场推导，不会写入该文件；旧版写在包目录里的 `src/ifa/last_config.py` 仍会被只读兼容。

---

## 使用方式

IFA 提供 **四种入口**：CLI、Web、REST API、MCP Server。

### ① CLI 命令行

```bash
# —— 经 LLM 的深度分析 ——

# 单基金深度分析（含 Bull/Bear 辩论）
ifa analyze 510300 --date 2024-01-15
ifa analyze 159919                      # 默认分析当天
ifa analyze 510300 --mode deep_simple   # 跳过辩论，快得多

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
ifa backtest 510300                     # 买入-持有回测（默认近 3 年、初始 10 万；默认计入申赎费）
ifa tools                               # 列出全部数据工具与参数（39 个）
ifa tool get_fund_achievement -p symbol=000834   # 直接调用一个数据工具
ifa skill                               # 安装内置 skill 到用户级目录
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
| `config [k] [v]` | — | `--unset` | 查看/设置配置（落盘到用户配置文件） |
| `tools` | — | `--json`、`--markdown` | 列出全部数据工具及参数（由注册表生成，不手写） |
| `tool <name>` | 工具名 | `--param / -p`（可重复）、`--json`、`--no-cache` | 直接调用一个数据工具，失败时非零退出码 |
| `skill` | — | `--print`、`--force`、`--dir` | 把内置 skill 安装到用户级目录 |
| `backtest <code>` | 基金代码 | `--start`、`--end`（默认近 3 年）、`--amount / -a`（默认 10 万）、`--no-fees`（只看价格口径） | 买入-持有回测 |

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
        Bull ↔ Bear 辩论（1 轮） → Research Manager 裁决 →
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


> **权重硬约束由代码校验**：`Portfolio Advisor` 之后会解析资产类别/单基金权重，校验合计 100%、单基金 ≤ 风险偏好上限、债券 ≥ 下限、海外/QDII ≤ 上限。违规时在建议末尾追加 `## WEIGHT CHECK（代码校验，非 LLM 自述）`（违规项 + 按约束重排后的权重 + 告警），CLI / Web / API 三处都会看到；约束不可行时明确写「无法满足」而不是硬凑一组数字。

> **组合风险由代码计算**：R2 之后若解析出 ≥2 只基金权重，会用与回测同一取价层拉取真实历史序列（共同交易日对齐），算出年化波动率、相关系数矩阵、分散化比率与每只基金的风险贡献（`w_i(Σw)_i/(w'Σw)`），以 `## PORTFOLIO ANALYTICS（代码计算，非 LLM 自述）` 追加到建议末尾。样本不足或取数失败只剔除该基金并注明，绝不猜测、绝不中断分析。
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

Agent 可使用 **39 个数据工具**（`src/ifa/agents/tools/`），全部来自 AkShare（底层：东方财富、雪球、中证指数公司、中国债券信息网）：

| 类别 | 数量 | 文件 | 代表工具 |
|------|:---:|------|---------|
| 公募基金 | 20 | `public_fund_tools.py` | 基金列表、持仓、风险分析、业绩、费率、盈利概率、资产配置 |
| 宏观经济 | 8 | `macro_tools.py` | CPI/PPI/PMI/GDP/LPR/SHIBOR、北向资金、融资融券、估值信号 |
| ETF / 指数 | 8 | `etf_index_tools.py` | ETF 行情、指数行情、基金净值、成份股、**ETF 折溢价率**、**跟踪误差**、**人民币汇率** |
| 成分股 | 3 | `constituent_tools.py` | 成份股概览、行业分布、成份股表现 |

此外，CLI `ifa search` / REST `GET /funds/search` / MCP `search_funds` 共用数据工具 `search_funds`：它在**完整**基金列表（约 2.8 万只）上按代码/简称/类型/拼音过滤后再分页，不依赖 `get_fund_list()` 的前 30 行。取数失败时 CLI 以非零退出码结束、REST 返回 502，不会伪装成「查无结果」。

CLI 侧对应 `ifa tools`（列出全部工具与参数）与 `ifa tool <名字> -p key=value`（直接调用，失败非零退出码）：
不写 Python、不激活 venv 就能取到同一批数据。内置 skill `src/ifa/skills/fund.md` 里的工具表
由 `ifa tools --markdown` 生成，`tests/test_skill_doc.py` 会校验它与注册表一致（历史上工具数
漂移过五次：25 → 33 → 35 → 36 → 39）。

### 记忆与反思

- 每个 Agent 可携带 `FinancialSituationMemory`（`src/ifa/agents/memory.py`），基于 BM25 检索历史相似情景，中英混合分词（中文按字、英文按词）。
- 条目上限默认 **1000 条**（`_DEFAULT_MAX_SITUATIONS`），FIFO 淘汰。可在配置中通过 `max_situations` 调整。
- `Reflector`（`src/ifa/graph/reflection.py`）在决策后基于实际收益/亏损反思并更新各 Agent 记忆。
- **记忆会落盘**：写入 `local_data/memory/<name>.json`（由配置项 `memory_dir` 决定），下次启动自动载入，
  因此 `ifa validate --update-memory` 积累的经验能在之后的 `ifa analyze` 中真正被检索到。
  未配置 `memory_dir` 时仅存在于内存。

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

**取价口径**：ETF 用**前复权收盘价**（分红已还原）；公募基金优先取**累计净值走势**（分红再投已计入，且不再截断历史 —— 旧实现取单位净值并 `tail(120)`，会把分红记成亏损、把三年回测压成半年）；但**发生过份额折算的基金**（如 161725）累计净值会一步跳变、不再可比，此时自动改用它自己的**前复权价**（再退单位净值并显式标注），口径会写进报告；指数用价格指数（**不含分红**）。

输出**两套收益**：价格口径（`total_return_pct`，与指数基准同口径，便于算超额）与投资者口径（`net_*`，扣申购费/赎回费/券商佣金），差额即**费用拖累** `fee_impact_pct`。管理费/托管费**已含在净值里，不重复扣除**，只作说明。无风险利率取中债 10 年期国债收益率（取不到才退 2%），取数来源在报告里标注。另有最大回撤、年化波动率、交易天数、月度收益、净值曲线（采样到最多 120 点）。数据不足 2 条直接返回带 `error` 的空结果；`--no-fees` 可只看价格口径。

### 评级 vs 实际收益 回测验证

**用数字回答「AI 多 Agent 辩论生成的评级，在历史上是否有预测力」**。跑历史分析 → 取事后实际收益 → 统计**绝对命中率与超额命中率**、Wilson 置信区间、多视界对比、评级分档、rank IC、置信度校准与混淆矩阵。源码：`src/ifa/backtest/rating_validator.py`（取数与编排）、`rating_stats.py`（纯统计层）、`benchmarks.py`（逐基金基准解析）。

> **智识诚实声明**：本验证**不证明**评级「有效」或「无效」，仅描述其在给定样本上的历史表现。样本量 < 30 时统计结论无显著性。过往表现不代表未来结果。

> **口径提醒**：① 绝对命中率主要反映 beta（大盘涨它就高），可证伪的是**超额命中率**；② 多视界（默认 20/60/120 交易日）与多指标属多重比较，**只有主视界 `--hold-days` 可当确认性结论**；③ 基准逐基金解析，回退到沪深300 的记录其「超额」不代表跑赢自己的跟踪指数。

#### CLI 用法

```bash
# 对一批 ETF 在指定日期跑分析，持有 60 交易日后看收益
ifa validate --codes 510300,159919,510500 --dates 2024-01-15,2024-04-15 --hold-days 60

# 自动生成过去 6 个月每月一个分析日期
ifa validate --codes 510300,159919 --months-back 6 --hold-days 60

# 指定统计视界（交易日）；默认 20,60,120，且必含 --hold-days
ifa validate --codes 510300,159919 --months-back 6 --horizons 20,60,120

# 显式开启记忆更新（注意幸存者偏差风险，默认关闭）
ifa validate --codes 510300 --months-back 3 --update-memory
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--codes` | 必填 | 逗号分隔 ETF/指数基金代码 |
| `--dates` | — | 逗号分隔分析日期，与 `--months-back` 二选一 |
| `--months-back` | — | 自动生成过去 N 个月每月一个日期 |
| `--hold-days` | `60` | **主视界**：评级后持有多少交易日看收益（唯一可当确认性结论的视界） |
| `--horizons` | `20,60,120` | 逗号分隔的统计视界（交易日），自动排序去重并保证含 `--hold-days` |
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
| **超额命中率** | 看涨中「跑赢自己的基准」的比例 | 这才是选基能力；与绝对命中率对照可看出 beta 占比 |
| **Alpha vs 同期基准** | 命中率 − 同期基准上涨比例 | 正值=评级选股跑赢被动持有该基准 |
| **多视界对比** | 20/60/120 交易日各自的命中率、超额、IC | 各视界独立取数；只有主视界可当确认性结论 |
| **rank IC** | 评级分数（+2…−2）与超额的 Spearman 相关 | ≥8 条样本才算；越接近 1 说明评级梯度越有效 |
| **评级分档** | 5 档各自的平均/中位超额、超额>0 比例 | 看梯度是否单调；HOLD 档超额应接近 0 |
| **置信度校准** | High/Medium/Low 的命中率与平均绝对超额 | 区分度 = High − Low，为正才说明置信度有信息量 |
| **混淆矩阵** | 5 档评级 × {涨/跌} | 看 BUY/SELL 的分布是否均衡（全是 HOLD=无信息量） |

#### 设计约束（芒格视角评审结论）

1. **小样本必须标注 CI**——不标 CI 的命中率是欺骗（噪声不是信号）
2. **默认不接回反思系统**——防止「用随机性强化随机性」的反馈污染（`--update-memory` 需用户显式开启）
3. **必须有基准对比**——全是 HOLD 的策略也能高命中率，必须对比随机基准与**该基金自己的**基准；回退到沪深300 的记录必须写明原因并计数
4. **多视界不许互相冒充**——每个视界各自取数，扁平字段只在主视界可作回退（60 日收益不得填进 120 日）；公募基金同样可验证（累计净值、无截断）

---

## 每日邮件报告（cron 定时）

`scripts/daily_analysis.py` 批量分析一组基金，并把**摘要正文（HTML + 纯文本两个版本）+ 完整报告的 `.md` 附件**发到邮箱。邮件是 `multipart/alternative`：HTML 版把摘要渲染成真表格、并把报告 Markdown 现场渲染成 HTML（邮件客户端不渲染 Markdown，这一步必须由发送方做）；纯文本版是等宽对齐的同一份摘要，给不认 HTML 的客户端兜底。它是按无人值守的定时任务写的：非交易日直接跳过、失败非零退出、配置缺项报错而不是静默不发。

```bash
python scripts/daily_analysis.py --email                                  # 分析前一交易日 + 发信（默认基金列表）
python scripts/daily_analysis.py --codes 510300,159919 --mode deep_simple --email
python scripts/daily_analysis.py --date 2026-10-13 --force --email        # 指定日期并强制跑（忽略交易日检查）
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--codes` | 脚本内 `DEFAULT_FUND_CODES` | 逗号分隔的基金代码（**部署前请改成自己的持仓**） |
| `--date` | **前一交易日** | 分析日期（`YYYY-MM-DD`）；不带该参数时自动取前一交易日 |
| `--mode` | `deep` | `deep`（含辩论）或 `deep_simple`（不辩论，快得多） |
| `--force` | 关 | 跳过交易日检查，非交易日也跑 |
| `--email` | 关 | 跑完把摘要正文（HTML + 纯文本：核心参数表 + 指数估值表 + 渲染后的报告全文）+ 完整报告 `.md` 附件发到配置的邮箱 |

- **退出码**：任一基金分析失败、或邮件发送失败 → `1`；否则 `0`（含「非交易日跳过」）。
- **非交易日**：不加 `--force` 时，**今天**不是交易日就直接跳过分析**且不发邮件**，退出码 `0`（休市不是故障）。
- **分析日期**：不带 `--date` 时分析**前一交易日** —— 早上跑批时当天还没收盘，能拿到的完整数据属于前一交易日（周一 → 上周五，长假后 → 节前最后一个交易日）。交易日历取不到时按失败上报（退出码 `1`），不会静默什么都不做。
- **配置**：`ifa config smtp_host smtp.qq.com` 等写进用户配置文件，或直接用上表的 `IFA_SMTP_*` / `IFA_EMAIL_TO` 环境变量（服务器上推荐环境变量，密码不落盘）。
- **发信行为**：同一份内容发两个版本（`multipart/alternative`）——`text/html` 版把摘要渲染成真表格，并把报告 Markdown 现场渲染成 HTML（自写的 `src/ifa/notify/markdown.py`，纯标准库：标题/表格/列表/粗体/分隔线，其余降级为段落；所有文本先转义，链接只放行 http/https/mailto）；`text/plain` 版是等宽对齐的同一份摘要，给不认 HTML 的客户端兜底。两版都含「核心参数」表（基金代码/基金名称/净值(日期)/日涨跌/评级/置信度/耗时/状态）+「指数估值」表（跟踪指数/数据日期/PE(TTM)/PB/ROE/股息率/ERP，只覆盖乐咕乐股支持的那 12 个指数，且股息率是「上证A股」全市场参考值而非指数自身值）+ 失败明细。HTML 正文超过 12 万字符时**显式省略报告全文**并写明「见 .md 附件」（绝不静默省略）；完整报告始终作为 `.md` 附件（含程序硬注入的【智识诚实声明】）。
- **日涨跌兜底**：ETF 的日涨跌优先取场内行情表的「增长率」；还没发布时回退东财日线（`fund_etf_hist_em`），仍失败再回退新浪日线（`fund_etf_hist_sina`，用最近两个交易日收盘价算涨跌幅）—— 东财 `push2his` 在部分网络下会持续 `RemoteDisconnected`，换源兜底好过让这一列长期空着。
- **服务器 cron**（工作日 08:00，分析前一交易日 —— 前一交易日的净值此时已公布）：

```cron
0 8 * * 1-5 cd /home/alan/index-fund-advisor && .venv/bin/python scripts/daily_analysis.py --email >> local_data/daily_analysis.log 2>&1
```

> 每只基金串行分析（deep 模式实测峰值内存约 500 MB，辩论段占大头）。内存紧张的机器上建议用 `--mode deep_simple`，或套一层 `systemd-run --scope -p MemoryMax=`。

## 开发

```bash
# 代码检查
ruff check .
ruff format .

# 类型检查
mypy src

# 测试（969 个测试，覆盖 40 个模块）
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
- 评级/置信度优先从管理层输出的机器可读 `Rating:` / `Confidence:` 行**确定性解析**（零额外 LLM 调用），取不到才回退到 LLM 抽取；词表固定 5 级 `STRONG_BUY / BUY / HOLD / UNDERWEIGHT / SELL`
- `SignalProcessor` 对 LLM 输出做合法性校验 + 模糊匹配，非法值 fallback 到 `HOLD` / `Medium`
- 组合权重由 `src/ifa/portfolio/weights.py` 代码校验（合计 100% / 单基金上限 / 债券下限 / QDII 上限），违规时追加 `WEIGHT CHECK` 并告警
- 组合风险指标（相关性 / 波动率 / 风险贡献）由 `src/ifa/portfolio/analytics.py` 从真实历史序列计算，取数失败或样本不足只剔除并注明，不中断分析
- 估值数据缺失（乐咕乐股只覆盖 12 个指数）与股息率口径在报告、邮件与日志里显式标注，不静默留空
- 回测同时给出价格口径与投资者口径收益，标明取价口径与费用假设；管理费/托管费不重复扣除，取不到费率用保守默认值并写入 notes
- 评级验证以**超额命中率**为主、逐基金解析基准（回退须写明原因）；多视界各自取数，只有主视界可当确认性结论
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
| 邮件通知 | Python 标准库 `smtplib` + `email`（无第三方依赖） |
| Python | ≥ 3.12 |

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
│   │   ├── tools/            # 39 个数据工具（4 类）
│   │   ├── prompts/          # Agent prompt 模板
│   │   └── memory.py         # BM25 情景记忆
│   ├── graph/                # LangGraph 编排 + 反思 + 信号处理
│   ├── dataflows/            # AkShare 封装（含重试、资产类型检测）
│   ├── data_tools/           # 声明式工具注册表 + 缓存执行器
│   ├── llm_clients/          # 多提供方 LLM 客户端工厂
│   ├── backtest/             # 买入持有回测引擎（含费用建模）+ 评级验证（统计层 / 基准解析）
│   ├── observability/        # per-request tracing
│   ├── portfolio/            # 风险偏好模型 + 配置策略 + 组合数学分析
│   ├── notify/               # SMTP 邮件通知 + Markdown→HTML 渲染（纯标准库，摘要正文 + .md 附件）
│   ├── mcp/                  # FastMCP server（9 个工具）
│   ├── cli/                  # Typer CLI 入口（ifa / ifa-web）+ tools_cmd（tool/tools/skill）
│   ├── skills/               # 内置 skill（fund.md，工具表由 ifa tools --markdown 生成）
│   ├── env_loader.py         # 用户配置目录 + .env 加载（全局安装后仍能读到 Key）
│   └── default_config.py     # 默认配置 + 运行时构建
├── web/                      # Streamlit 多页应用
├── api/                      # FastAPI 异步任务 + 鉴权
├── tests/                    # 969 个测试（40 个模块）
├── scripts/                  # 每日分析脚本（含 --email 定时邮件报告）
├── release/                  # 轻量打包脚手架（assemble.py 带闭包自检，未发布到 PyPI）
├── pyproject.toml
└── README.md / CLAUDE.md / MCP.md
```

> **`release/` 说明**：该目录是「只含 MCP + 数据层」的轻量打包脚手架，`assemble.py` 从 `src/ifa` 动态拷贝子集。**本项目不发布到 PyPI**（正式发行走 GitHub Release，见上）；`assemble.py` 复制前会用 AST 自检「模块顶层 `ifa.*` 导入闭包」，漏文件立刻报错，`tests/test_release_package.py` 独立复算这条闭包。详见 [release/README.md](<release/README.md>)。**`release/src/` 和 `release/dist/` 是生成物，已在 `.gitignore` 中忽略，不要手动编辑。**

---

## 许可证

见 [`release/LICENSE`](release/LICENSE)。
