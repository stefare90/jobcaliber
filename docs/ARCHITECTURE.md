# Architecture

What the code is made of, why the layers exist, and which invariants a change must not break.
Binding rules for contributors are in [`AGENTS.md`](../AGENTS.md); this file is the map.

---

## Layers

```
core/            domain vocabulary and typed configuration — no I/O, no frameworks
   ↑
pipeline/        one folder per step: fetch/ · scoring/ · evaluation/
   ↑
infrastructure/  the outside world: SQLite, HTTP transports, config files, notifications
   ↑
application/     what happens and in which order: runner, worker, schedule, clients
   ↑
entrypoints/     one module per process: cli, worker, web
                 + bootstrap.py (the composition root, the only place that wires everything)
```

Enforced by `tests/test_layers.py`:

- `core` imports no frameworks, no `sqlite3`, no `httpx`, no file reads;
- no layer imports `entrypoints`;
- `infrastructure` never imports `pipeline`, `application` or `entrypoints`.

The one exception allowed in `core` is a **pure helper every layer needs** — today
`core/formatting.py` (UTC → local timestamps), because a helper placed in `entrypoints` cannot be
imported by anything else.

## The pipeline

| Step | Folder | Contract |
|---|---|---|
| Fetch | `pipeline/fetch/` | boards → normalized `JobPosting`s. No gates, no scores, no storage decisions |
| Score | `pipeline/scoring/` | one `ScoringResult` per posting: answers, missing set, confidence |
| Evaluate | `pipeline/evaluation/` | `ScoringResult` → `EvaluationResult` (decision, score, dropped_by) |
| Store | `infrastructure/database/` | one `Store` for everything: jobs, evaluations, runs, applications |
| Compose | `application/runner.py` | `run_once()`: fetch → score → evaluate → persist → notify |

`run_once` takes its collaborators as arguments (`fetcher`, `scorer`, `notifier`) and the tests
pass fakes: nothing in the suite touches the network.

## Decisions, in order

```
gates           explicit negative answer → DROP (a missing answer never drops)
min_threshold   answered, below the floor → DROP
missing         any answer missing → REVIEW
apply_threshold below the band → REVIEW
confidence      below evaluation.systemone_min_confidence → REVIEW
scored_criteria all above the band, nothing missing → PASS
```

`score_total` is the simple mean of the scored answers, used only to order the list. There are no
weights: every drop carries the name of the rule that produced it (`dropped_by`).

## Data model (schema v4)

| Table | Holds | Key |
|---|---|---|
| `jobs` | one row per posting | `external_id` (the board URL) is unique |
| `evaluations` | one judgement | unique per `(job_id, config_v, engine)` |
| `evaluation_answers` | one row per criterion per evaluation | indexable, so the web can filter on answers |
| `applications` | what you did about a posting | `job_id`, `state ∈ applied/planned/skipped` |
| `runs` | the run history **and the queue** | `status ∈ requested/running/ok/failed` |
| `config_versions` | the profile content of every version | `sha` of the profile text |

Two invariants follow from the keys:

- **Re-scoring is content-addressed.** The profile *content* (plus `RUBRIC_VERSION`, bumped when
  the projection changes shape) is the version. Same content → same version → nothing re-scores;
  schedule, notifications or scraping changes never touch it.
- **A mark belongs to the posting.** `applications` is keyed on `jobs.id`, so it survives
  re-scoring; `feedback` (the previous design) was keyed on `evaluations.id` and would have been
  orphaned by the next re-score.

Schema changes are a **manual** step: a process may create an empty database but never alter an
existing one. `Store` raises `SchemaMismatch` naming the remedy; `migrations/` holds one immutable
module per version, and `jobcaliber db migrate` applies them with a backup and one transaction per
step.

## Extension points

Only for families of interchangeable implementations chosen from configuration — an ABC with
`_registry`, `register(key)` and `create(...)`, implementations in their own files, self-registered
on import:

| Family | Base | Kinds |
|---|---|---|
| `AIClient` | `infrastructure/ai/client/base.py` | wire protocols: `systemone`, `openai` |
| `Scorer` | `pipeline/scoring/scorer/base.py` | engine kinds: `decision`, `llm` |

Adding a *product* (a model behind an existing wire) is configuration: `ai.engines.<name>` with
`kind`, `api`, `base_url`, `model` and optionally `api_key_env`, `headers`, `options`, `retry`.
Adding a *protocol* is a new file plus `@AIClient.register("<api>", "<kind>")`.

The rubric is never stored: `pipeline/scoring/projection/` turns `criteria` into the engine's
format at runtime, so the same config drives a System One payload and an LLM prompt.

## Processes

| Process | Entry point | Talks to |
|---|---|---|
| `jobcaliber` | `entrypoints/cli.py` | the pipeline, the database |
| `jobcaliber-worker` | `entrypoints/worker.py` | the database (queue + schedule), the boards, the engine |
| web | `entrypoints/web/routes.py` | the database only |

The web never runs the pipeline: it inserts a `requested` row into `runs`; the worker claims it
atomically. That is the whole contract between the two.

The worker is a single-threaded loop: reload the config if its mtime changed, recover stale runs,
claim a request or check the schedule, run it, requeue on a retryable failure.

## Time

The database stores **UTC** (`datetime('now')`). `schedule.timezone` (an IANA name, required)
defines the wall clock of `scrape_times` and of everything rendered for a human.
`core/formatting.local_time` is the only formatter: the web filter and the CLI use it, and a
delivery (Telegram) uses it too. No code calls a bare `astimezone()`.

`is_due()` compares UTC instants: it parses the stored timestamp as UTC and builds the slot in the
configured zone. Comparing a UTC timestamp with a local clock is what once made the worker start a
run at every poll.

## The web layer

```
entrypoints/web/
├── routes.py      create_app + the route handlers (wiring, templates, static, middleware)
├── filters.py     the query string → Column/Row/Filter; pure, no FastAPI
├── readmodels.py  query → the data a template needs (table rows, detail, markdown)
└── templates/ static/
```

`filters.py` is deliberately HTTP-free (there is a test for it): it describes which columns can be
filtered, what widget each needs, and the `Filter` objects the store consumes. The table columns
come from `config.criteria`, never from a hardcoded list: adding a criterion to the profile adds a
column and a filter field.

The web is read-mostly. A test asserts that it only calls an allowlist of `Store` methods, and only
two of them write: `save_application`/`clear_application` and `request_run`.
