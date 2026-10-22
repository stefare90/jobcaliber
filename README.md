# jobcaliber

Personal job-offer ranker: it searches the boards every day, scores each offer against
**your** criteria with a model that runs on your machine, and shows you only what deserves your
attention — without re-showing yesterday's same 50.

## What it does

```
search boards  →  score every offer  →  decide  →  show it  →  you say yes/no
                                                                    │
                                          the feedback calibrates the criteria ──┘
```

- **Searches** LinkedIn and Indeed for the titles and locations you configure.
- **Scores** each new offer with one question per criterion (a local decision model by default,
  any OpenAI-compatible engine as an alternative).
- **Decides** with hard gates plus per-criterion thresholds: `drop`, `review` or `pass`.
- **Remembers** everything: the same offer is never scored twice with the same configuration,
  never re-notified, and the history stays attributable to the rules that produced it.
- **Shows** the results in a local web app, where you mark each offer good or bad. Those
  verdicts are the raw material for calibration.

It is **not**: an auto-applier, a CV/cover-letter tailor, a multi-user service, or a crawler
that hammers the boards.

## Status

First release in progress. The scoring pipeline and the storage already run end-to-end from
the command line; the web app and the worker are next.

| Area | State |
|---|---|
| Typed config (Pydantic v2) with fail-fast validation | ✅ |
| Fetch: Title × location queries, per-board caps, polite pacing | ✅ |
| Scoring: one question per criterion, rubric projected per engine | ✅ |
| Evaluation: gates → thresholds → `pass`/`review`/`drop` | ✅ |
| SQLite storage, idempotent evaluations, schema guard + migrations | ✅ |
| CLI: `run`, `status`, `jobs`, `db` | ✅ |
| Worker: schedule + queue (`runs` as the queue) | ✅ `jobcaliber-worker` |
| Web UI: offer table, detail, Sì/No feedback, run request | ✅ `jobcaliber-web` |
| Telegram notification with a link to the web UI | ⛔ after the web app |
| Calibration on your own verdicts | ⛔ needs a few weeks of verdicts |

## How it works

1. **Fetch** (`pipeline/fetch/`) — JobSpy queries the boards for
   `search.titles × (on_site_locations + remote_locations)`, paginating up to
   `board_max_results[board]` and stopping early when a page brings no new offer. Captchas are
   never stored, `NaN` becomes `None`, and no gate or score is applied here.
2. **Dedup** — `external_id` (the board URL) is unique. The same offer seen again only refreshes
   `last_seen_at`.
3. **Scoring** (`pipeline/scoring/`) — each configured criterion carries its own question. The
   rubric is **projected** at runtime into the engine's format: a `/v1/systemone` payload for
   decision models, a chat prompt for LLM engines. One configuration, two formats, no drift.
4. **Evaluation** (`pipeline/evaluation/`) — gates first (location, contract type, exclusions),
   then per-criterion thresholds, then the confidence:
   - an explicit negative answer can `drop`;
   - a **missing** answer never drops: it becomes neutral, lowers the confidence and forces
     `review`;
   - everything above `apply_threshold` is `pass`.
5. **Storage** (`infrastructure/database/`) — SQLite with WAL. Every judgement is a row in
   `evaluations`, unique per `(job, config version, engine)`: re-running the same configuration
   is a no-op, changing it re-scores everything.
6. **Delivery** — the web app reads the database (⛔ next); Telegram will only send a link.

## The scoring model

`config.yaml` has three blocks:

```yaml
search:                      # the only bound part: it drives the boards
  titles: ["Software Engineer", "Embedded Software Engineer"]
  on_site_locations: ["Sardinia, Italy"]
  remote_locations: ["Italy"]
  exclude: ["reserved for protected categories (law 68/99)"]

criteria:                    # free keys, each with its own question
  core_skills: {min_threshold: 0.5, apply_threshold: 0.67, question: {...}}
  location:    {gate: {accept: ["accepted"]}, question: {...}}
```

- **Scored criteria** (`min_threshold` / `apply_threshold`): the answer is a 0-1 score.
  Below `min_threshold` → `drop`; below `apply_threshold` → `review`; otherwise → `pass`.
- **Gates** (`gate`): the answer must be one of the accepted options. A gate drops only on an
  explicit negative answer.
- **`missing`**: each question declares which level or option means "cannot tell". Missing
  answers are exempt from thresholds, cost a confidence penalty and force `review`.
- **No weights**: the 0-100 score is the simple mean of the scored criteria, used only to order
  the list. The decision comes from the thresholds, so every drop has a name
  (`dropped_by`: `location`, `core_skills`, …).

Adding a criterion is **data, not code**: a new key with its question. The rubric for both
engine families is generated from it, so there is no prompt file to keep in sync.

## Architecture

```
src/jobcaliber/
├── core/                 # models only: no I/O, no frameworks
│   ├── domain.py         #   JobPosting, ScoringResult, EvaluationResult, GateDecision
│   └── config/           #   search.py · criteria.py · ai.py · settings.py · app.py
├── pipeline/             # one folder per step
│   ├── fetch/            #   models.py · queries.py · parsing.py · fetcher.py
│   ├── scoring/          #   scorer/ (systemone, llm) · projection/ (criteria → prompt)
│   └── evaluation/       #   evaluator.py (gates, thresholds, confidence)
├── infrastructure/       # how to talk to the world
│   ├── database/         #   store.py · schema.py · migrations/
│   ├── ai/               #   transports (systemone, openai), prompt rendering
│   ├── config_loader.py  #   reads config.yaml
│   └── env.py            #   reads .env
├── application/          # what happens, in which order
│   ├── runner.py         #   one run: fetch → score → evaluate → save
│   ├── worker.py         #   schedule + claim queued runs
│   ├── schedule.py       #   "is a slot due?" (pure functions)
│   └── clients.py        #   transports → services, from config
├── entrypoints/          # one module per process
│   ├── cli.py            #   jobcaliber        → run | status | jobs | db
│   ├── worker.py         #   jobcaliber-worker → the worker loop
│   └── web/              #   uvicorn …web:create_app: table, detail, feedback
└── bootstrap.py          # composition root
```

The layering is enforced by tests (`tests/test_layers.py`): `core` has no I/O, no framework
imports and does not read files; no layer imports `entrypoints`; infrastructure never depends
upwards. The web and
the worker will be thin: they will not import the pipeline, only the database and the runner.

**Process types.** One deployable package, two long-lived processes:

| Process | Role | Talks to |
|---|---|---|
| `jobcaliber-web` (next) | shows offers, records your Sì/No, requests a run | the database |
| `jobcaliber-worker` | owns the schedule, claims run requests, executes them | the database, the boards, the model |

They never call each other: **the database is the contract**. `runs` doubles as the queue —
the web inserts a `requested` row, the worker claims it atomically.

## Installation

```bash
# 1. uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 2. dependencies (frozen = reproducible)
git clone https://github.com/stefare90/jobcaliber && cd jobcaliber
uv sync --frozen

# 3. personal config + secrets (both gitignored)
cp config.example.yaml config.yaml
cp .env.example .env && chmod 600 .env     # API keys, if your engine needs one

# 4. sanity checks
uv run pytest -q
uv run jobcaliber db version               # "new database (will be created at v2 on first use)"
```

### Scoring engine

The default is a **local** System One model (`rizzo-flow`, Apache-2.0, llama.cpp + Vulkan on the
iGPU), which keeps your CV, criteria and postings on your machine:

```bash
cd ~/rizzo-flow && uv run rizzo serve --port 8017 --device auto --quant q4_k_m
```

Any OpenAI-compatible endpoint can replace it by changing `ai.engines` / `ai.roles` in the
config — the code does not change.

## Usage

```bash
# one pass: fetch, score the pending offers, evaluate, persist
uv run jobcaliber run
uv run jobcaliber run --limit 5 --max-queries 1     # quick check, ~40s
uv run jobcaliber run --dry-run                     # nothing is written
uv run jobcaliber run --engine jev                  # score with another configured engine

# the worker (systemd keeps it alive): schedule + queued requests, one run at a time
uv run jobcaliber-worker                            # loop
uv run jobcaliber-worker --once --limit 5 --max-queries 1   # one bounded tick

# what happened / what is stored
uv run jobcaliber status                            # last run + notifiable offers
uv run jobcaliber jobs --decision review --limit 10

# web app (local, read-mostly: it writes feedback and run requests only)
uv run uvicorn jobcaliber.entrypoints.web:create_app --factory --port 8765

# database
uv run jobcaliber db version                        # schema version in use
uv run jobcaliber db check                          # does the file match schema.sql?
uv run jobcaliber db migrate [--dry-run]            # apply pending migrations (manual on purpose)
uv run jobcaliber db backup --to data/jobs.db.bak
```

A full run costs one call per new offer (~5 s each with the local model) plus the fetch
(~20-30 min for all queries, dominated by board pagination). Re-runs only score what is new.

## Configuration

- `search` — titles, on-site locations, remote locations, and an `exclude` list shown to the
  `applicable` criterion (protected-category postings and similar). Location strings are sent
  to the boards **verbatim**: write them the way the board spells them (`Sardinia, Italy`).
- `criteria` — free-keyed; each one has `question` (`score` or `choice`, with `levels`/`options`
  and the `missing` marker) and either thresholds or a `gate`. Text may use
  `{{search.titles}}`, `{{search.on_site_locations}}`, `{{search.remote_locations}}`,
  `{{search.exclude}}`; an unresolved placeholder fails at startup.
- `penalties` — confidence multiplier per criterion when the answer is missing.
- `notifications.telegram` — thresholds, quiet hours (used from the Telegram milestone).
- `scraping` — boards, country, hours window, page size, per-board caps, job type.
- `ai` — engines (`kind`, `api`, `base_url`, `model`, optional `api_key_env`, `headers`,
  `options`, `throttle_s`, `retry`) and the `scorer` role.

**Secrets** never enter the config: engines name an environment variable (`api_key_env`) and
`load_config()` first loads the gitignored `<repo>/.env`. A real environment variable always
wins over the file.

## Database

SQLite in WAL, one file (`data/jobs.db`, gitignored). A **process may create the database but
never alter it**: if the schema version does not match, it refuses to start and tells you what
to run. Migrations are a deliberate, manual step:

```bash
uv run jobcaliber db migrate --dry-run   # what would change
uv run jobcaliber db migrate             # backup + apply, one transaction per step
```

`migrations/` holds one immutable, numbered module per schema change; `SCHEMA_VERSION` is the
single source of truth and is checked at import.

## Calibration

The thresholds are still provisional. On a stratified sample of 61 offers, labelled by hand:

| Finding | Effect |
|---|---|
| The location question was asking "which arrangement" instead of "is it acceptable" | a Turin on-site role was accepted; rewritten, the gate now drops 7 `no` and 0 good offers |
| "Not mentioned" treated as neutral for core skills diluted the strongest criterion | as the lowest level it lifts the rank separation from AUC 0.62 to 0.72 |
| A model-judged salary gate dropped no-salary offers | removed: `pay` missing already forces `review` |
| The exclusion criterion answered "keep" for protected-category postings | asking the fact ("does it contain any exclusion?") with the abbreviations in the data fixed it: 5/5 |
| No offer in the sample earned your "I would apply" | thresholds cannot be set until the web app collects real verdicts |

Consequently, the first release will run in **learning mode**: it shows `pass` **and** `review`,
and your Sì/No becomes the labels that calibrate the thresholds.

## Development

```bash
uv run pytest -q                      # 172 tests, layering included
uv run python spikes/01_fetch_coverage/fetch_coverage.py     # do the queries reach enough offers?
uv run python spikes/02_engine_benchmark/engine_benchmark.py --engine rizzo --limit 20
uv run python spikes/03_calibration/calibrate.py rizzo       # measure against labels.yaml
```

`spikes/` are throwaway experiments that must run end-to-end and report real numbers; each one
has a README with its input/output convention. `AGENTS.md` holds the binding project rules and
the lessons learned; `AGENT_PLAN.md` is the agent's build log.

## Privacy

Postings, criteria and verdicts stay on your machine. Outside calls go only to the engine you
configure. No captcha is stored, no LinkedIn login, no open ports: the web app will listen on
localhost. `config.yaml`, `.env` and `data/` are gitignored and never pushed.

## License

To be chosen (MIT proposed).
