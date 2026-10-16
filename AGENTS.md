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
ifa validate --codes 510300,159919 --months-back 12 --horizons 20,60,120   # rating-vs-return validation (LLM, slow)
ifa analyze 510300 --mode deep_simple  # skip the debate rounds (much faster)
ifa config                            # show effective config + config file path
ifa config llm_provider deepseek      # persist one key to the user config file
ifa config --unset llm_provider       # remove it
ifa backtest 510300                    # buy-and-hold backtest, no LLM
ifa tools                              # list all 36 data tools + params (generated)
ifa tool get_index_valuation -p index_name=沪深300   # call one data tool directly
ifa skill                              # install the bundled skill to ~/.claude/skills
python scripts/daily_analysis.py --email   # daily batch + summary email (HTML with the report rendered + plain-text fallback) + .md report attachment (cron); --mode deep_simple skips debate
# Global install, no clone needed: uv tool install --from git+https://github.com/AlanNiew/index-fund-advisor.git ifa
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
- `release/src/` and `release/dist/` are **generated** by `release/assemble.py` and gitignored — never hand-edit. `assemble.py` AST-checks the module-level `ifa.*` import closure before copying and fails loudly when a shared leaf module is missing; `tests/test_release_package.py` recomputes that closure and imports the assembled package in a subprocess.

## Architecture boundaries (respect when editing)

- **`src/ifa/graph/`** — `AdvisorGraph` orchestrates all 4 modes over the shared `IFAdvisorState`. Conditional edges (`conditional_logic.py`) drive tool loops + fund/risk debate loops. `Propagator` builds initial state; `Reflector` updates agent memory post-decision; `SignalProcessor` normalizes LLM ratings.
- **`src/ifa/agents/`** — ReAct agents + ToolNodes, grouped under `analysts/`, `researchers/`, `managers/`, `risk_mgmt/`, with `tools/` (36 data tools), `prompts/` (separated from agent code), and BM25 `memory.py`.
- **`src/ifa/data_tools/`** — declarative `_TOOL_SPECS` registry (36 tools) + `CachedDataToolExecutor` (SHA1-keyed cache + snapshots, disk-failure → degrade to direct execution). The cache key includes `storage.CACHE_SCHEMA_VERSION` — bump it when a tool's output contract changes, or stale payloads keep shadowing the new implementation. Fund search must go through the `search_funds` tool: `get_fund_list()` returns only the first 30 rows.
- **`src/ifa/dataflows/`** — AkShare wrappers (retry, asset-type auto-detect) + `clean_dataframe`/`truncate_report`.
- **`src/ifa/llm_clients/`** — `create_llm_client` factory; `OpenAIClient` covers openai/azure/ollama/openrouter/xai/qwen/zhipu/deepseek/opencode/custom; Anthropic + Google have dedicated clients. The provider list is a single source of truth in `src/ifa/providers.py` (`PROVIDER_CONFIG`), which is dependency-free on purpose so `default_config` stays light. `custom` = any OpenAI-compatible endpoint; it **requires** an explicit `backend_url` and skips model validation. `opencode` talks to the OpenCode Go gateway (`https://opencode.ai/inference/go/v1`) and auto-attaches a custom `User-Agent` plus a process-scoped `x-opencode-session` header (override the session via `OPENCODE_SESSION_ID`). In thinking mode that gateway also requires history assistant messages to carry their `reasoning_content` back — `NormalizedChatOpenAI` does this, but **only** for `opencode` (DeepSeek's own API rejects it).
- **`src/ifa/backtest/`** — buy-and-hold (lump sum only) `run_backtest()` in `engine.py`, which reports both price-basis and investor-basis returns; `fees.py` resolves real purchase/redemption fees and models transaction costs (operating fees are already inside NAV — never double-charged); `rating_validator.py` (orchestration) + `rating_stats.py` (pure stats: multi-horizon, excess-return, rank IC, rating buckets, confidence calibration) + `benchmarks.py` (per-fund benchmark resolution).
- **`src/ifa/portfolio/`** — `RiskProfile` risk profiles + `weights.py`: deterministic weight parsing/validation (sum 100%, single-fund cap, bond floor, QDII cap) with a `WEIGHT CHECK` appendix appended to `portfolio_advice` when the LLM's numbers violate the profile.
- **`src/ifa/observability/`** — `RequestTracer` auto-traces `AdvisorGraph.run()` to `results/traces/`.
- **Backtest numbers must state their price basis and fee assumptions** — ETFs use forward-adjusted prices; public funds prefer the cumulative-NAV series (unit NAV books dividends as losses) with no history truncation. Price-basis and investor-basis returns are both reported; operating fees are already inside NAV and are never deducted twice; missing fee data falls back to conservative defaults recorded in `notes`, never silently zero (`ifa backtest --no-fees` restores the price basis).
- **Rating validation measures excess, across horizons, against each fund's own benchmark** — the absolute hit rate is mostly beta. Every horizon fetches its own data and the flat fields are only a fallback for the primary horizon; benchmarks resolve per fund (explicit override > name detection > CSI300 fallback with a stated reason); rank IC, rating buckets, monotonicity and confidence calibration are reported. Multiple horizons/metrics are multiple comparisons — only the primary horizon is confirmatory.
- **Shared init for CLI/Web/API** lives in `src/ifa/common.py`: `build_advisor()`, `build_state()`, `save_report()`, `get_provider_kwargs()`. All three interface layers must use these — don't re-init the graph ad hoc.
- **`src/ifa/cli/tools_cmd.py`** — the `tools` / `tool` / `skill` commands. The skill's tool table is generated by `ifa tools --markdown` between BEGIN/END markers; never hand-edit it (`tests/test_skill_doc.py` guards coverage and the no-`cd`/no-`python -c` rules).
- **`src/ifa/env_loader.py`** — `user_config_dir()` + `load_env_files()` (cwd-upward `.env` first, then the user-level `.env`). All four entry points use it instead of bare `load_dotenv()`; a global install started from an arbitrary cwd would otherwise report "Missing credentials".
- **`src/ifa/skills/fund.md`** — bundled skill, shipped via `[tool.setuptools.package-data]`.

## Critical conventions (breaking these breaks things)

- **LLM calls go through `invoke_llm_safely()` / `invoke_chain_safely()`** (`src/ifa/agents/utils.py`, exponential-backoff retry). **Never raw `llm.invoke()`** in agents or graph code.
- **`AdvisorGraph.run()` keeps its top-level try/except** — on failure it still saves the log and returns a state with an `error` field. Preserve this.
- **Agent tools must fetch data through `run_data_tool()`** (`ifa.data_tools.api`), never by importing `akshare` directly or calling `route_to_vendor()` — otherwise the tool bypasses the cache/snapshot layer. The cache stores text/CSV, so a cached DataFrame loses leading zeros in numeric code columns; zero-pad on the consumer side (see `constituent_tools._normalize_stock_code`).
- **Agent report inputs are truncated** via `truncate_report(report, max_chars=3000)` to avoid token overflow. **Debate transcripts are truncated the other way round**: `truncate_debate_history()` (`src/ifa/agents/utils.py`, `DEBATE_HISTORY_MAX_CHARS = 3000`) drops the *head* and keeps the newest speech, because every debater re-reads the whole history each round. Call it only in per-round nodes (`researchers/researcher.py`, `risk_mgmt/debator.py`); the state keeps the full transcript for the Research Manager and the final report.
- **The latency budget is tiered and configurable** — quick calls time out at `timeout` (120 s), report-generation/judgment calls at `deep_timeout` (180 s, injected by `build_advisor()`), and `llm_max_retries` (2, so 3 attempts) bounds retries. Defaults live in `src/ifa/default_config.py` (`DEFAULT_LLM_TIMEOUT` / `DEFAULT_DEEP_TIMEOUT` / `DEFAULT_LLM_MAX_RETRIES`); `invoke_llm_safely(..., retries=None)` means "read the config". A measured 30.4-minute `deep` run spent 98.5% of its wall time waiting on LLMs, mostly on requests that hit the old 180 s timeout and retried — but legitimate calls have taken up to 119 s, so do not tighten this to 60–90 s blindly.
- **Ratings are parsed deterministically first** — `AdvisorGraph.resolve_decision_signals()` reads the machine-readable `Rating:` / `Confidence:` lines the managers are instructed to emit (zero extra LLM calls); only when those are absent does `SignalProcessor` fall back to LLM extraction + fuzzy matching, and finally to `HOLD` / `Medium`. The vocabulary is fixed at 5 levels — `STRONG_BUY / BUY / HOLD / UNDERWEIGHT / SELL`; never introduce `REDEEM` or other words. Don't bypass.
- **Portfolio weights are enforced in code, not just requested in the prompt** — `validate_portfolio_weights()` (`src/ifa/portfolio/weights.py`) checks the stated asset-class and per-fund weights against `max_single_fund_pct` / `min_bond_pct` / `max_international_pct`, then appends a `WEIGHT CHECK` block (issues + deterministically rebalanced weights) and logs a warning. Infeasible constraints are reported as such instead of silently fudged.
- **Missing valuation data and dividend yield are labelled, never implied** — indices outside 乐咕乐股's 12 (中证白酒 / 纳斯达克100 / 标普500 …) have no PE/PB/ERP and get a 「本次无估值锚」 note in the valuation table, CLI overview and email body. Dividend yield always uses the index's own 中证指数 value (`dividend_yield_source`), never the all-market fallback (which once made 5 different funds all show 2.73%).
- **Honesty disclaimer is hard-injected by `report_generator.py`** — not left to the LLM to emit.
- **Ruff**: `target-version py312`, `line-length 120`, ignore `E501 / F403 / F405 / E402`; `isort.known-first-party = ["ifa","api","web"]`.

## Gotchas

- **`ifa <6位数字>` auto-routes to `analyze`** via `_FundCodeGroup` in `src/ifa/cli/main.py` — so `ifa 510300` works with no subcommand, but a typo'd subcommand (e.g. `ifa analyz`) still errors normally.
- **Default LLM provider is OpenCode Go** (`opencode`) → a valid `OPENCODE_API_KEY` in `.env` is required out of the box; requests go to `https://opencode.ai/inference/go/v1`. Other providers (openai/azure/anthropic/google/ollama/openrouter/qwen/xai/zhipu/deepseek/custom) selectable via `ifa config llm_provider <name>` or the `IFA_LLM_PROVIDER` env var (env wins).
- **Thinking-mode `reasoning_content` round-trip** — the OpenCode Go gateway rejects (400) requests whose history assistant messages lack `reasoning_content`, while `langchain_openai` drops that field in both directions. `NormalizedChatOpenAI` preserves it (response → `additional_kwargs` → request payload) with a flag that `OpenAIClient.get_llm()` turns on **only** for `opencode`. The failure is intermittent (the upstream decides per request whether to think), so a single green re-run does not prove it fixed.
- **Config precedence is env > user config file > DEFAULT_CONFIG.** `ifa config` persists to `%APPDATA%\ifa\config.json` (or `~/.config/ifa/config.json`, override with `IFA_CONFIG_DIR`); the legacy in-package `src/ifa/last_config.py` is read-only compatible. Path keys (`_PATH_KEYS`) are never persisted, and a stale `backend_url` pointing at another provider's built-in endpoint is reset automatically.
- **Default debate is now 1 round** (`max_debate_rounds`); the risk debate still runs 2 (`max_risk_discuss_rounds`). Restore with `ifa config max_debate_rounds 2`.
- **`quick_think_llm` must not be the cheapest tier** — weak models produce unreliable structured output that pollutes the whole pipeline.
- **`IFA_API_KEY` empty = API auth disabled, all routes open.** Set it before exposing the API.
- **`ifa analyze` exits non-zero when no report is produced** — `_run_analysis` raises `typer.Exit(code=1)` and prints the `error` field, so wrapper scripts and cron jobs can detect failure. Keep it that way.
- **Data-source ability limits are code-addressed, not ticker-addressed.** ETF basic info goes to East Money's intraday quote table (`fund_etf_fund_daily_em`), never the 蛋卷 out-of-exchange fund library; CSI constituent files are addressed by **index** code, so ETF codes (510300) and Shenzhen index codes (399006) 404 there. That failure now surfaces as an actionable `ValueError` (`_constituents_source_hint`) instead of pandas' "Excel file format cannot be determined".
- **`py_mini_racer` construction is serialized for you.** akshare's valuation / trade-calendar / THS interfaces build a `MiniRacer` internally, and LangGraph's ToolNode runs tools in parallel; two concurrent V8 isolate creations abort the whole process (`[FATAL:partition_address_space.cc(243)]`, exit 0x80000003 — not catchable by try/except). `src/ifa/dataflows/__init__.py` installs `_mini_racer_guard` (RLock around construction + rewrite of every module holding a stale reference). Don't remove that import and don't construct `MiniRacer` yourself.
- **Requests without a timeout fail fast for you.** akshare calls `requests.get(url)` with no timeout in several places (e.g. `index_stock_cons_csindex`); a server that accepts the connection and then goes silent hangs `ifa analyze` forever (14 minutes observed against `oss-ch.csindex.com.cn` — process alive, CPU ~0, log frozen, no exception ever raised). `src/ifa/dataflows/__init__.py` installs `_network_guard`, which wraps `requests.sessions.Session.request` and injects `IFA_DATA_SOURCE_TIMEOUT` (default 30 s) only when the caller passed no timeout. Do **not** "simplify" it back to `socket.setdefaulttimeout`: requests turns `timeout=None` into `Timeout(connect=None, read=None)` and calls `sock.settimeout(None)`, overriding the socket default (`tests/test_network_guard.py` pins that finding).
- **Rating validation works for public funds too** — the old `get_fund_history_nav` `tail(120)` truncation is gone; `run_backtest()` prefers the cumulative-NAV series (no truncation), so 公募基金 records are validated like ETFs. Benchmarks resolve per fund; a CSI300 fallback is always labelled with its reason.
- **`ifa validate --update-memory` defaults OFF** — survivorship-bias guard; only enable deliberately. It is the *only* writer of agent memory; normal `analyze` runs only read.
- **Agent memory persists to `<memory_dir>/<name>.json`** (`DEFAULT_CONFIG` → `local_data/memory`). Without `memory_dir` in the config, `FinancialSituationMemory` is in-memory only — that's why unit tests pass a bare config and stay side-effect free.
- **The data-tool catalog is generated, not hand-written.** `ifa tools` / `ifa tools --markdown` render `_TOOL_SPECS`; the skill doc and README numbers are checked against it (the count drifted 25 → 33 → 35 → 36). If you add a tool, regenerate the BEGIN/END block.
- **Entry points load `.env` from the cwd *and* the user config dir** (`ifa.env_loader.load_env_files()`, `override=False`). This is what makes `uv tool install`-style global usage work from any directory.
- **CI** (`.github/workflows/ci.yml`) runs **ruff + mypy + pytest on a Python 3.12–3.13 matrix on `ubuntu-latest`**. mypy is a hard gate (`mypy src` must be clean); run it locally before pushing. Because CI is Linux while dev happens on Windows, any Windows-only pin in `requirements.lock` must carry a platform marker (`pywin32==312 ; sys_platform == "win32"`) — without it `pip install -r requirements.lock` fails on every matrix entry. `tests/test_lock_hygiene.py` guards both this and the matrix-vs-`requires-python` agreement. The reverse also holds: `akshare` splits its V8 wrapper by platform (`mini-racer` on non-Linux, `akracer`/`py-mini-racer` on Linux — all three ship the same `py_mini_racer/` directory), so those pins need matching `platform_system` markers or Linux silently installs packages outside the lock.
- **Releases are GitHub Releases, not PyPI** — `.github/workflows/release.yml` builds wheel + sdist on `v*` tags, smoke-tests them (CLI, bundled skill, `mcp` extra on 1.x, MCP stdio handshake) and attaches them to the Release. The tag must equal `pyproject.toml`'s version. The wheel ships only the `ifa` package: `ifa` and `ifa-mcp` work, `ifa-web` / the REST API need a checkout.
- **Direct imports must be declared dependencies** — `python-dotenv` used to arrive transitively (streamlit → pydantic-settings), so everything worked locally while the installed wheel died on `ifa --help` with `ModuleNotFoundError: No module named 'dotenv'`. `tests/test_dependency_declarations.py` now fails whenever a third-party module imported from `src/ifa` is missing from `pyproject.toml` (extras count; `OPTIONAL_IMPORTS` documents the exceptions).
- **The `mcp` extra is pinned `<2`** — mcp 2.x renamed `FastMCP` to `MCPServer` and removed `mcp.server.fastmcp`; `src/ifa/mcp/server.py` uses the v1 API. `tests/test_lock_hygiene.py` asserts the extra excludes 2.x and that every extra bound admits the locked version.
- **Generated outputs** `results/`, `test_results/`, `local_data/`, `release/src/`, `release/dist/`, `.claude/` are gitignored.

## Read before changing sensitive areas

- [`CLAUDE.md`](CLAUDE.md) — canonical architecture, robustness patterns, state model, debate mechanics.
- [`README.md`](README.md) — usage, four modes, API/MCP surface, config table.
- [`MCP.md`](MCP.md) — the 9 MCP tools and transport details.
- [`TODO.md`](TODO.md) — roadmap status (P0–P3 reported complete).
