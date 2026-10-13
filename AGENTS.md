# AGENTS.md

Quick-start guide for AI coding agents working in this repo. **For full architecture detail, read [`CLAUDE.md`](CLAUDE.md) first** — this file is a fast-scanning complement, not a substitute.

## What this repo is

IFA (Index Fund Advisor) — AI-driven analyzer for Chinese A-share index funds. LangGraph orchestrates a multi-agent **debate** workflow (Bull/Bear for funds; Aggressive/Conservative/Neutral for risk). Data source is AkShare. Four analysis modes: `deep` (debate, default), `deep_simple` (no debate), `screen` (compare), `portfolio` (risk debate). Four entry points: CLI (`ifa`), Web (`ifa-web`), REST API, MCP server (`ifa-mcp`).

## Commands

```bash
# Install (editable; registers ifa / ifa-web / ifa-mcp scripts)
pip install -e ".[dev]"            # add ",[mcp]" if touching the MCP server
# For reproducible CI-matched deps: pip install -r requirements.lock && pip install -e . --no-deps

# Run
ifa analyze 510300 --date 2024-01-15
ifa 510300                         # shorthand — 6-digit codes auto-route to analyze
ifa screen --query "..." --top 10
ifa portfolio --risk moderate
ifa search 沪深300                  # no LLM
ifa info 510300                    # no LLM
ifa validate --codes 510300,159919 --months-back 12   # rating-vs-return backtest (LLM, slow)
ifa analyze 510300 --mode deep_simple  # skip the debate rounds (much faster)
ifa config                            # show effective config + config file path
ifa config llm_provider deepseek      # persist one key to the user config file
ifa config --unset llm_provider       # remove it
ifa-web                           # Streamlit (http://localhost:8501)
uvicorn api.main:app --port 8000   # API — no registered ifa-api script; call uvicorn directly

# Quality gates (these run in CI: .github/workflows/ci.yml)
ruff check .
ruff format .
mypy src
pytest                            # full suite
pytest -x                         # stop at first failure
pytest tests/test_core.py::TestBacktestEngine::test_max_drawdown   # single test
```

## Package layout — the big gotcha

- `src/ifa` is the **only** main package. `pyproject.toml` declares `packages.find: where=["src"], include=["ifa*"]`.
- `api/`, `web/`, `scripts/` live at the **project root**, outside the package. They import at runtime thanks to sys.path injection done by the CLI entry modules (works in editable/dev mode). Don't try to relocate them into `src/ifa` without reworking that.
- CLI lives **inside** the package as `ifa.cli` (entry: `ifa.cli.main:app`).
- `release/src/` and `release/dist/` are **generated** by `release/assemble.py` and gitignored — never hand-edit.

## Architecture boundaries (respect when editing)

- **`src/ifa/graph/`** — `AdvisorGraph` orchestrates all 4 modes over the shared `IFAdvisorState`. Conditional edges (`conditional_logic.py`) drive tool loops + fund/risk debate loops. `Propagator` builds initial state; `Reflector` updates agent memory post-decision; `SignalProcessor` normalizes LLM ratings.
- **`src/ifa/agents/`** — ReAct agents + ToolNodes, grouped under `analysts/`, `researchers/`, `managers/`, `risk_mgmt/`, with `tools/` (36 data tools), `prompts/` (separated from agent code), and BM25 `memory.py`.
- **`src/ifa/data_tools/`** — declarative `_TOOL_SPECS` registry (36 tools) + `CachedDataToolExecutor` (SHA1-keyed cache + snapshots, disk-failure → degrade to direct execution). The cache key includes `storage.CACHE_SCHEMA_VERSION` — bump it when a tool's output contract changes, or stale payloads keep shadowing the new implementation. Fund search must go through the `search_funds` tool: `get_fund_list()` returns only the first 30 rows.
- **`src/ifa/dataflows/`** — AkShare wrappers (retry, asset-type auto-detect) + `clean_dataframe`/`truncate_report`.
- **`src/ifa/llm_clients/`** — `create_llm_client` factory; `OpenAIClient` covers openai/azure/ollama/openrouter/xai/qwen/zhipu/deepseek/opencode/custom; Anthropic + Google have dedicated clients. The provider list is a single source of truth in `src/ifa/providers.py` (`PROVIDER_CONFIG`), which is dependency-free on purpose so `default_config` stays light. `custom` = any OpenAI-compatible endpoint; it **requires** an explicit `backend_url` and skips model validation. `opencode` talks to the OpenCode Go gateway (`https://opencode.ai/inference/go/v1`) and auto-attaches a custom `User-Agent` plus a process-scoped `x-opencode-session` header (override the session via `OPENCODE_SESSION_ID`).
- **`src/ifa/backtest/`** — buy-and-hold `run_backtest()` + `rating_validator.py` (rating-vs-actual-return validation).
- **`src/ifa/observability/`** — `RequestTracer` auto-traces `AdvisorGraph.run()` to `results/traces/`.
- **Shared init for CLI/Web/API** lives in `src/ifa/common.py`: `build_advisor()`, `build_state()`, `save_report()`, `get_provider_kwargs()`. All three interface layers must use these — don't re-init the graph ad hoc.

## Critical conventions (breaking these breaks things)

- **LLM calls go through `invoke_llm_safely()` / `invoke_chain_safely()`** (`src/ifa/agents/utils.py`, exponential-backoff retry). **Never raw `llm.invoke()`** in agents or graph code.
- **`AdvisorGraph.run()` keeps its top-level try/except** — on failure it still saves the log and returns a state with an `error` field. Preserve this.
- **Agent tools must fetch data through `run_data_tool()`** (`ifa.data_tools.api`), never by importing `akshare` directly or calling `route_to_vendor()` — otherwise the tool bypasses the cache/snapshot layer. The cache stores text/CSV, so a cached DataFrame loses leading zeros in numeric code columns; zero-pad on the consumer side (see `constituent_tools._normalize_stock_code`).
- **Agent report inputs are truncated** via `truncate_report(report, max_chars=3000)` to avoid token overflow.
- **`SignalProcessor` validates + fuzzy-matches LLM ratings/confidence**, falling back to `HOLD` / `Medium` on garbage. Don't bypass.
- **Honesty disclaimer is hard-injected by `report_generator.py`** — not left to the LLM to emit.
- **Ruff**: `target-version py312`, `line-length 120`, ignore `E501 / F403 / F405 / E402`; `isort.known-first-party = ["ifa","api","web"]`.

## Gotchas

- **`ifa <6位数字>` auto-routes to `analyze`** via `_FundCodeGroup` in `src/ifa/cli/main.py` — so `ifa 510300` works with no subcommand, but a typo'd subcommand (e.g. `ifa analyz`) still errors normally.
- **Default LLM provider is OpenCode Go** (`opencode`) → a valid `OPENCODE_API_KEY` in `.env` is required out of the box; requests go to `https://opencode.ai/inference/go/v1`. Other providers (openai/azure/anthropic/google/ollama/openrouter/qwen/xai/zhipu/deepseek/custom) selectable via `ifa config llm_provider <name>` or the `IFA_LLM_PROVIDER` env var (env wins).
- **Config precedence is env > user config file > DEFAULT_CONFIG.** `ifa config` persists to `%APPDATA%\ifa\config.json` (or `~/.config/ifa/config.json`, override with `IFA_CONFIG_DIR`); the legacy in-package `src/ifa/last_config.py` is read-only compatible. Path keys (`_PATH_KEYS`) are never persisted, and a stale `backend_url` pointing at another provider's built-in endpoint is reset automatically.
- **`quick_think_llm` must not be the cheapest tier** — weak models produce unreliable structured output that pollutes the whole pipeline.
- **`IFA_API_KEY` empty = API auth disabled, all routes open.** Set it before exposing the API.
- **`ifa analyze` exits non-zero when no report is produced** — `_run_analysis` raises `typer.Exit(code=1)` and prints the `error` field, so wrapper scripts and cron jobs can detect failure. Keep it that way.
- **Data-source ability limits are code-addressed, not ticker-addressed.** ETF basic info goes to East Money's intraday quote table (`fund_etf_fund_daily_em`), never the 蛋卷 out-of-exchange fund library; CSI constituent files are addressed by **index** code, so ETF codes (510300) and Shenzhen index codes (399006) 404 there. That failure now surfaces as an actionable `ValueError` (`_constituents_source_hint`) instead of pandas' "Excel file format cannot be determined".
- **`py_mini_racer` construction is serialized for you.** akshare's valuation / trade-calendar / THS interfaces build a `MiniRacer` internally, and LangGraph's ToolNode runs tools in parallel; two concurrent V8 isolate creations abort the whole process (`[FATAL:partition_address_space.cc(243)]`, exit 0x80000003 — not catchable by try/except). `src/ifa/dataflows/__init__.py` installs `_mini_racer_guard` (RLock around construction + rewrite of every module holding a stale reference). Don't remove that import and don't construct `MiniRacer` yourself.
- **Requests without a timeout fail fast for you.** akshare calls `requests.get(url)` with no timeout in several places (e.g. `index_stock_cons_csindex`); a server that accepts the connection and then goes silent hangs `ifa analyze` forever (14 minutes observed against `oss-ch.csindex.com.cn` — process alive, CPU ~0, log frozen, no exception ever raised). `src/ifa/dataflows/__init__.py` installs `_network_guard`, which wraps `requests.sessions.Session.request` and injects `IFA_DATA_SOURCE_TIMEOUT` (default 30 s) only when the caller passed no timeout. Do **not** "simplify" it back to `socket.setdefaulttimeout`: requests turns `timeout=None` into `Timeout(connect=None, read=None)` and calls `sock.settimeout(None)`, overriding the socket default (`tests/test_network_guard.py` pins that finding).
- **Rating validator supports ETF/index funds only** — public funds hit `get_fund_history_nav`'s `tail(120)` truncation. Enforced by design.
- **`ifa validate --update-memory` defaults OFF** — survivorship-bias guard; only enable deliberately. It is the *only* writer of agent memory; normal `analyze` runs only read.
- **Agent memory persists to `<memory_dir>/<name>.json`** (`DEFAULT_CONFIG` → `local_data/memory`). Without `memory_dir` in the config, `FinancialSituationMemory` is in-memory only — that's why unit tests pass a bare config and stay side-effect free.
- **CI** (`.github/workflows/ci.yml`) runs **ruff + mypy + pytest on a Python 3.12–3.13 matrix on `ubuntu-latest`**. mypy is a hard gate (`mypy src` must be clean); run it locally before pushing. Because CI is Linux while dev happens on Windows, any Windows-only pin in `requirements.lock` must carry a platform marker (`pywin32==312 ; sys_platform == "win32"`) — without it `pip install -r requirements.lock` fails on every matrix entry. `tests/test_lock_hygiene.py` guards both this and the matrix-vs-`requires-python` agreement. The reverse also holds: `akshare` splits its V8 wrapper by platform (`mini-racer` on non-Linux, `akracer`/`py-mini-racer` on Linux — all three ship the same `py_mini_racer/` directory), so those pins need matching `platform_system` markers or Linux silently installs packages outside the lock.
- **Generated outputs** `results/`, `test_results/`, `local_data/`, `release/src/`, `release/dist/`, `.claude/` are gitignored.

## Read before changing sensitive areas

- [`CLAUDE.md`](CLAUDE.md) — canonical architecture, robustness patterns, state model, debate mechanics.
- [`README.md`](README.md) — usage, four modes, API/MCP surface, config table.
- [`MCP.md`](MCP.md) — the 9 MCP tools and transport details.
- [`TODO.md`](TODO.md) — roadmap status (P0–P3 reported complete).
