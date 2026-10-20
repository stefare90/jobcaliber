# jobcaliber

Personal job-offer ranker: every morning only the 2-3 offers above 70/100 for you
(skills, pay, location), without re-reading yesterday's same 50. Local, transparent,
tuned to your profile.

## Status

Early build. The scoring brain is done and measured; storage, delivery and scheduling
are next.

| Area | State |
|---|---|
| Typed config (Pydantic v2, schema v9) | ✅ validated at load, fail-fast |
| Fetch (JobSpy: LinkedIn + Indeed, paginated) | ✅ `ingestion/fetch.py`, 632 usable rows measured |
| AI transports (System One + OpenAI wire) | ✅ registry by wire api, config-driven engines |
| Scorer (5 atomic questions, prompt-driven) | ✅ `scoring/scorer/`, System One + LLM |
| Evaluator (gates, weights, confidence) | ✅ `scoring/evaluator.py` |
| Explainer / query expander | ✅ thin clients + prompts, not wired into a run yet |
| SQLite storage, Telegram, scheduler | ⛔ W1 (`app/`, `delivery/`, `schema.sql` ready) |
| Test suite | ✅ 53 tests, `uv run pytest` |

Spikes: `spikes/01_fetch_coverage` (do the queries reach enough offers?) and
`spikes/02_engine_benchmark` (which engine discriminates best?). Both run end-to-end and
report real numbers in their own README.

## Purpose

- **Does:** ingest 2-3 sources → aggressive dedup → hard gates (location/titles) →
  0-100 score + confidence → gate → 2-line reason only when >70 → Telegram + local
  history + yes/no feedback.
- **Does not:** auto-apply, CV/cover-letter tailoring, Gmail, multi-user, real LinkedIn
  login, hourly mass crawling, open ports.

## How it works (pipeline, fixed order)

1. **Fetch** (`ingestion/fetch.py`) — JobSpy boards (LinkedIn, Indeed), queries built from
   `profile.titles × query locations`, paginated with `page_size` up to
   `board_max_results[board]`, stopping early when a page adds no new posting; rate
   limited, captchas never stored, `NaN → None`. No gates, no scoring here. Max 2-4
   runs/day + jitter/backoff.
2. **Dedup** — normalized URL (strip `/apply|/application|/thanks`, tracking params,
   fragment) + normalized `company+title`, `UNIQUE(external_id)`. *(W1)*
3. **Hard gates** before scoring: location (remote ok / hybrid ≤`hybrid_max_km` / far
   onsite dropped / unknown→review), title/company kill lists. *(W1: `ingestion/gates.py`)*
4. **Score** (`scoring/`) — one call of 5 atomic questions to a System One model, answers
   normalised into `SystemOneResult`. Interchangeable engines (`decision` or `llm`), same
   questions, same independent evaluator.
5. **Evaluate** (`scoring/evaluator.py`) — config rules onto the scores: hard `DROP`,
   review routing, weighted 0-100, combined confidence with missing-data penalties.
6. **Gate:** `> notifica_soglia + confidence >= min` → notify, review band → web review,
   below → hidden. `notified` = idempotency, never re-notify. *(W1)*
7. **Explanation:** LLM text only for notified offers (2 lines), template fallback when
   the engine is down. *(W1 wiring)*

### Scoring 0-100

`total = 45*core + 20*tools + 15*pay + 20*contract` (location = hard gate, weight 0).

- `core ×45` — profile core-skills match (`profile.skills.core` with weights).
- `tools ×20` — tool coverage (`profile.skills.tools`).
- `pay ×15` — against `job_filters.pay` (`target_annual`, `min_annual`). Missing pay is
  **never a blind zero**: neutral level + flag + confidence penalty.
- `contract ×20` — contract/seniority vs preference.
- `location` — model-classified `LocationBucket` (`primary / remote / hybrid / elsewhere /
  unknown`), scored via config `bucket_scores`, `elsewhere` = hard drop, `unknown` =
  confidence penalty.

Weights, thresholds and penalties all live in `config.yaml`. The five questions live in
`prompts/scoring_systemone/default.json` — no question text is hardcoded in Python.

## AI engines

`ai.engines` declares any number of engines; `ai.roles` maps pipeline roles
(`scorer`, `explainer`, `query_expander`) to one of them.

| Engine | kind | api | Notes |
|---|---|---|---|
| `rizzo` | `decision` | `systemone` | local default: Spark-4B + LoRA on llama.cpp, Vulkan iGPU |
| `jev` | `decision` | `systemone` | cloud reference via opencode System One endpoint |
| `local_llm` | `llm` | `openai` | Ollama `qwen3:8b`, `reasoning_effort: none` |
| `opencode_llm` | `llm` | `openai` | `deepseek-v4.1-flash`, needs `x-opencode-session` header |

`kind` is the engine class (decision vs generative); `api` is the wire protocol. Products
differ **only** by config (`base_url`, `model`, `api_key_env`, `headers`, `options`), so
adding an engine is a config entry, never code. `options` carries provider knobs merged
into the request body (e.g. `reasoning_effort: none` for qwen3, `num_ctx`/`keep_alive` for
Ollama); the contract fields `model`/`messages`/`temperature` always win. A role only accepts the kinds it can implement,
validated at startup.

```bash
# local System One engine (kept outside this repo)
cd ~/rizzo-flow && uv run rizzo serve --port 8017 --device auto --quant q4_k_m
```

## Repo layout

```
jobcaliber/
├── AGENTS.md               # project rules (binding) + lessons learned
├── AGENT_PLAN.md           # agent-only build plan: done + todo (not user docs)
├── README.md               # this file
├── pyproject.toml          # uv deps (telegram/apscheduler come in W1)
├── uv.lock                 # pinned lockfile
├── schema.sql              # SQLite WAL: jobs/runs/feedback/config_versions (normative)
├── config.example.yaml     # generic template (copy to config.yaml, never commit it)
├── .env.example            # secret template (copy to .env, never commit it)
├── .pi/extensions/         # pi project extensions (git-guard: commit/push approval)
├── prompts/                # scoring_systemone/*.json, scoring_llm/*.md, explainer, query_expander
├── src/jobcaliber/         # package, split by pipeline stage:
│   ├── config.py           #   typed config (Pydantic) + load_config (+ .env loading)
│   ├── env.py              #   minimal .env parser, real environment wins
│   ├── models.py           #   domain entities (JobPosting, SystemOneResult, ...)
│   ├── ai/                 #   client/ (AIClient base + systemone, openai), prompts, registry
│   ├── ingestion/          #   fetch, query_expander (+ W1: dedup, gates)
│   ├── scoring/            #   scorer/ (Scorer base + system_one, llm), evaluator
│   ├── delivery/           #   explainer (+ W1: notify, storage)
│   └── app/                #   W1: CLI, scheduler, web
├── spikes/                 # experiments, one folder per question
│   ├── README.md           #   index + input/output convention
│   ├── 01_fetch_coverage/  #   do the queries reach enough offers?
│   └── 02_engine_benchmark/#   which engine discriminates best?
├── tests/                  # pytest (W1: dedup identity, gates, idempotency)
└── data/                   # DB + raw cache (gitignored, only .gitkeep in git)
```

DB tables (`schema.sql`): `jobs` (one row/offer, sub-scores
`s_core/s_tools/s_pay/s_contract/s_location`, `score_total`, `confidence`, `notified`,
`status new/review/hidden/saved`), `runs` (found/new/scored/notified, duration/errors),
`feedback` (explicit only: `verdict` + fixed `reason_category` + free `reason_text`),
`config_versions` (personal config history, never pushed).

## Dependencies

- **Runtime:** Python ≥3.11, [uv](https://docs.astral.sh/uv/), SQLite3 (WAL), systemd.
- **Python now:** `python-jobspy==1.1.82`, `pandas>=2.1,<3`, `httpx`, `pyyaml`,
  `beautifulsoup4`, `pydantic>=2`.
- **Python W1+** (not yet): `python-telegram-bot`, `apscheduler`.
- **Local System One engine:** [`rizzo-flow`](https://github.com/Rizzo-AI-Academy/rizzo-flow)
  (Apache-2.0) — open, local, Jev-compatible `POST /v1/systemone`. Kept outside this repo;
  the scorer reaches it over HTTP at `ai.engines.rizzo.base_url`.
- **Never at runtime:** LangChain/LlamaIndex/AutoGen/CrewAI, React/Postgres/Chromium.
  Only thin `httpx` clients.

## Installation

```bash
# 1. uv (if missing)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 2. deps (frozen = reproducible)
cd jobcaliber
uv sync --frozen

# 3. personal config + secrets (both gitignored)
cp config.example.yaml config.yaml     # edit: titles, skills, location, thresholds, engines
cp .env.example .env && chmod 600 .env # fill in the API keys you need

# 4. DB from schema
sqlite3 data/jobs.db < schema.sql

# 5. sanity checks
uv run pytest -q
uv run python spikes/01_fetch_coverage/fetch_coverage.py   # fetch + coverage report
```

systemd (W1): service with `Restart=always`, `EnvironmentFile=%h/.config/jobcaliber/env`,
daily `sqlite3 .backup` (7 days), rotated logs.

## Usage

```bash
# Spike 01: profile-driven fetch -> raw JSON, coverage report, frozen benchmark set
uv run python spikes/01_fetch_coverage/fetch_coverage.py

# Spike 02: benchmark an engine on that frozen set
uv run python spikes/02_engine_benchmark/engine_benchmark.py --engine jev --limit 20
uv run python spikes/02_engine_benchmark/engine_benchmark.py --engine rizzo --limit 20

# W1 (when ready):
uv run python -m app --check          # skeleton + healthcheck
uv run python -m app run              # fetch -> score -> evaluate -> notify
```

Queries are generated from the profile: `titles × locations`, where `locations` is
`[primary]` plus `[remote_query]` when that field is set. Location strings are passed to
the boards **verbatim** — write them the way the board spells them (`Sardinia, Italy`,
not `Sardegna`). No geo mapping or language heuristics live in the code.

## Configuration

Everything lives in `config.yaml` (copy of `config.example.yaml`, schema v10), validated by
Pydantic models in `src/jobcaliber/config.py`:

- `profile` — titles, seniority, contract type, skills (`core` levels + `tools`), location
  (`primary`, optional `remote_query`, `hybrid_max_km`).
- `job_filters` — per-dimension `mode` (`hard_gate` | `weighted` | `hybrid`) and `weight`
  for `core_skills`, `tools`, `contract`, `pay` (`target_annual`, `min_annual`,
  `hard_drop_tolerance`), `location` (`bucket_scores` used when weighted); plus
  `confidence_penalties` (`location_unknown`, `pay_missing`).
- `notifications.telegram` — `notify_threshold`, `review_threshold`, `min_confidence`,
  `quiet_hours`, `digest_time`.
- `scraping` — `boards`, `country`, `hours_old`, `page_size`,
  `board_max_results` (per-board ceiling, e.g. `{linkedin: 300, indeed: 500}`), `job_type`.
- `schedule` — `scrape_times`, `backup_time`.
- `ai` — `engines` (`kind`, `api`, `base_url`, `model`, optional `api_key_env`, `headers`,
  `options`, `throttle_s`, `retry`), `roles` (`scorer`, `explainer`, `query_expander`),
  `custom_prompts`.

Values whose keys mirror a domain enum (e.g. `location.bucket_scores` vs
`LocationBucket`) and prompt criteria are validated at load/startup, never silently
degraded.

### Secrets

API keys never enter `config.yaml`. Engines reference an environment variable via
`api_key_env`, and `load_config()` first loads `<repo>/.env` (gitignored, `chmod 600`):

```bash
cp .env.example .env && chmod 600 .env    # then fill in the keys
```

Real environment variables always win over `.env` (`os.environ.setdefault`), so a systemd
`EnvironmentFile`, CI secret or interactive `export` still overrides the file. Malformed
`.env` lines fail fast at load with file:line.

## Testing

```bash
uv sync --frozen && uv run pytest -q
```

53 tests cover typed config + validation, `.env` loading precedence, AI client registry and
wire formats, fetch/query building, scorer prompt parsing and level derivation, and the
evaluator gates/weights/confidence.

## Roadmap (W1)

`app/main.py` orchestrator (config → clients → fetch → score → evaluate → explain),
SQLite persistence, Telegram digest + alerts with idempotent `notified`, APScheduler,
`ingestion/gates.py` with config-driven lists, end-to-end demo with 0 duplicates on rerun.

## Privacy / security

Postings stay local; outside calls only to the scorer/LLM you configure. No captcha is ever
stored, `NaN → None`, LAN-only web with a single token and a `chat_id` whitelist, `600` on
secret files. Personal config and `.env` are gitignored and never pushed.

## License

To be chosen (MIT proposed).
