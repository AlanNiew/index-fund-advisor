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
ifa config
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
- **`src/ifa/data_tools/`** — declarative `_TOOL_SPECS` registry + `CachedDataToolExecutor` (SHA1-keyed cache + snapshots, disk-failure → degrade to direct execution).
- **`src/ifa/dataflows/`** — AkShare wrappers (retry, asset-type auto-detect) + `clean_dataframe`/`truncate_report`.
- **`src/ifa/llm_clients/`** — `create_llm_client` factory; `OpenAIClient` covers openai/azure/ollama/openrouter/xai/qwen/zhipu/deepseek/opencode; Anthropic + Google have dedicated clients. `opencode` talks to the OpenCode Go gateway (`https://opencode.ai/inference/go/v1`) and auto-attaches a custom `User-Agent` plus a process-scoped `x-opencode-session` header (override the session via `OPENCODE_SESSION_ID`).
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
- **Ruff**: `target-version py310`, `line-length 120`, ignore `E501 / F403 / F405 / E402`; `isort.known-first-party = ["ifa","api","web"]`.

## Gotchas

- **`ifa <6位数字>` auto-routes to `analyze`** via `_FundCodeGroup` in `src/ifa/cli/main.py` — so `ifa 510300` works with no subcommand, but a typo'd subcommand (e.g. `ifa analyz`) still errors normally.
- **Default LLM provider is OpenCode Go** (`opencode`) → a valid `OPENCODE_API_KEY` in `.env` is required out of the box; requests go to `https://opencode.ai/inference/go/v1`. Other providers (openai/azure/anthropic/google/ollama/openrouter/qwen/xai/zhipu/deepseek) selectable in `src/ifa/default_config.py`.
- **`quick_think_llm` must not be the cheapest tier** — weak models produce unreliable structured output that pollutes the whole pipeline.
- **`IFA_API_KEY` empty = API auth disabled, all routes open.** Set it before exposing the API.
- **Rating validator supports ETF/index funds only** — public funds hit `get_fund_history_nav`'s `tail(120)` truncation. Enforced by design.
- **`ifa validate --update-memory` defaults OFF** — survivorship-bias guard; only enable deliberately. It is the *only* writer of agent memory; normal `analyze` runs only read.
- **Agent memory persists to `<memory_dir>/<name>.json`** (`DEFAULT_CONFIG` → `local_data/memory`). Without `memory_dir` in the config, `FinancialSituationMemory` is in-memory only — that's why unit tests pass a bare config and stay side-effect free.
- **CI** (`.github/workflows/ci.yml`) runs **ruff + mypy + pytest on a Python 3.10–3.13 matrix**. mypy is a hard gate (`mypy src` must be clean); run it locally before pushing.
- **Generated outputs** `results/`, `test_results/`, `local_data/`, `release/src/`, `release/dist/`, `.claude/` are gitignored.

## Read before changing sensitive areas

- [`CLAUDE.md`](CLAUDE.md) — canonical architecture, robustness patterns, state model, debate mechanics.
- [`README.md`](README.md) — usage, four modes, API/MCP surface, config table.
- [`MCP.md`](MCP.md) — the 9 MCP tools and transport details.
- [`TODO.md`](TODO.md) — roadmap status (P0–P3 reported complete).
