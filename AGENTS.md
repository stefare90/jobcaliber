# AGENTS.md — project rules

Binding for every contributor, human or agent. **If a rule here conflicts with a request, the
rule wins until it is changed in a reviewed edit of this file.**

Read first, in this order:

| File | What it gives you |
|---|---|
| `README.md` | what the product is, quick start, the shape of the output |
| [`docs/INSTALL.md`](docs/INSTALL.md) | step-by-step server install, with a check after each step |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | backups, migrations, upgrades, failure matrix |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | layers, data model, invariants, extension points |
| [`config/README.md`](config/README.md) | every configuration key, and what fails fast |
| `AGENT_PLAN.md` | the chronological log of what was done and what is next |
| `AGENT_STATE.md` | the current snapshot: where the project stands right now |

---

## 0. Two-phase workflow, and versioning approval

**Nothing is implemented before the user agrees.** Every change — a feature, a refactor, a
one-line fix, a config tweak, a dependency — is proposed in chat first (scope, files, approach,
acceptance criteria, how it will be tested) and implemented **only** after an explicit "ok".
Writing code, editing files or running mutating commands before that agreement is a rule
violation, even when the change looks trivial. If something new comes up while implementing, stop
and return to the proposal instead of deciding alone.

A development step ends in the **versioning phase**: commit and push happen **only if the user
approves**. This is enforced by the `git-guard` extension in `.pi/extensions/`:

- every git write (commit, push, add, switch, tag, stash, pull, …) shows a **Conferma / Rifiuta**
  menu; on **Rifiuta** the extension asks for a reason and hands it back, and the reason must be
  addressed — never retry the identical command;
- destructive git operations (reset, clean, rebase, restore, `push --force`, …) are always blocked;
- commit messages follow conventional commits: `<type>(<scope>): <subject>`, lowercase, ≤72 chars.

Commits are verified before they are proposed: the suite must be green in the tree that will be
committed, not only in the working tree.

## 1. Language

Everything in the repository is **English**: code, identifiers, comments, docstrings, docs, commit
messages, reports, config keys, UI strings. Chat with the user may be in Italian; repo content
never is.

## 2. Comments

Minimal. No per-line or per-function comments, no docstrings that repeat the signature.

Allowed only when they explain something the code cannot: a non-obvious integration detail, an
external API quirk, a spec invariant, or a trap that was paid for once. Self-explanatory names
beat comments.

## 3. Tested before done

Nothing is marked complete without proof:

- `uv sync --frozen && uv run pytest -q` must pass;
- every piece of logic has a test under `tests/`, with the layering tests green;
- a spike (anything under `spikes/`) must run end to end and report real numbers;
- never fake or "reasonably infer" a test result — paste what actually ran.

Behaviour that cannot be covered by a unit test (a run against the boards, a Telegram delivery) is
verified by hand and the observed numbers go into `AGENT_PLAN.md`.

## 4. Architecture, and the invariants

The map is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The short version, which must stay
true after any change:

### A. Typed models everywhere
- Domain entities live in `core/domain.py` (`JobPosting`, `ScoringResult`, `EvaluationResult`,
  `GateDecision`); fetch models in `pipeline/fetch/models.py` (`Query`, `FetchStats`); storage rows
  in `infrastructure/database/store.py` (`JobRow`, `ApplicationRow`, `Filter`).
- Configuration is typed: `AppConfig` plus `Search`/`Evaluation`/`Criterion`/`Question`/gate
  models in `core/config/`, Pydantic v2, loaded by `infrastructure/config_loader.py`.
- **No raw dicts across module boundaries.** A dataclass stays with the module that defines its
  contract and moves to `core/` only when it is domain vocabulary *and* named by a lower layer.

### B. Pure pipeline
`core/` → `pipeline/` → `infrastructure/` → `application/` → `entrypoints/`, wired by
`bootstrap.py`. `core/` has no I/O and no frameworks. No layer imports `entrypoints`.
`infrastructure/` never imports upwards. Inside `pipeline/`, one folder per step, and each step
owns exactly one question:

1. **fetch** — boards → normalized `JobPosting`s. No gates, no scores, no storage decisions.
2. **scoring** — one question per configured criterion, projected into the engine's wire format.
3. **evaluation** — gates → thresholds → confidence. Pure, no I/O.

Shared **pure** helpers that every layer needs are the only thing allowed in `core/` beyond
domain vocabulary (`core/formatting.py`: UTC → local timestamps), because a helper in
`entrypoints/` cannot be imported by anything else.

### C. Decisions
- **A missing answer never drops.** It forces `review` and is exempt from thresholds.
- Gates drop only on an **explicit negative** answer.
- `score_total` is the plain mean of the scored answers, used only for ordering. There are no
  weights and no penalties: every drop names its rule (`dropped_by`).
- Ties between `pass`/`review`/`drop` are decided by the config, never by a hardcoded number.

### D. Engines and the wire
- `httpx` only. No agentic frameworks (`langchain`, `llamaindex`, `crewai`).
- `AIClient` (`infrastructure/ai/client/base.py`) is an ABC: implementations provide
  `build_request()` and `extract()`, while the base owns `_post()`, auth headers, retry/backoff,
  the registry and `create()`. Public methods stay per transport (`system_one()`, `complete()`).
- The registry is keyed by the **wire api** (`systemone`, `openai`), never by product. A product is
  configuration: `base_url`, `model`, headers, key.
- `Scorer` (`pipeline/scoring/scorer/base.py`) is an ABC keyed by engine **kind**
  (`decision`, `llm`). The rubric is projected from `criteria` at runtime
  (`pipeline/scoring/projection/`): one configuration, two formats, no drift, no rubric files.
- Provider quirks that only affect the transport (a routing header, a versioned base path) live in
  `ai.engines.<name>.headers` / `base_url`, never in client code.
- The engine is **probed before the fetch**; an unreachable engine fails in milliseconds and is
  **not retried**.

### E. Configuration discipline
- Two gitignored files under `config/`: `profile.yaml` (what to search, evaluation rules,
  criteria) and `settings.yaml` (scraping, schedule, notifications, ai, paths).
  **The split is the versioning rule**: evaluations are keyed by the profile content plus
  `RUBRIC_VERSION` from the code, so the settings never re-score.
- Templates: `config/profile.example.yaml`, `config/settings.example.yaml`. Every key is documented
  in [`config/README.md`](config/README.md).
- No hardcoded parameters, thresholds or heuristics in source code.
- Secrets never enter `config/*.yaml`: engines declare `api_key_env`, the notifier `token_env`, and
  `load_config()` loads the gitignored `<repo>/.env` (`chmod 600`) first. A real environment
  variable always wins (`os.environ.setdefault`).
- Fail fast: invalid keys, unknown enums, malformed criteria and unresolved placeholders stop at
  load/startup with a message naming the key and the expected shape. Never degrade silently.

### F. Storage
- A process may **create** a database, never alter one. A schema mismatch raises `SchemaMismatch`
  naming the remedy; `jobcaliber db migrate` is manual, takes a backup and uses one transaction
  per step.
- `migrations/` is append-only: one immutable module per version, `SCHEMA_VERSION` is the single
  source of truth and is asserted at import.
- Facts belong to the things they describe: an application mark is keyed on the **job**, not on an
  evaluation (a re-score must not orphan it).

### G. Web
- Read-mostly, no JavaScript, server-rendered HTML. A test asserts that the web only calls an
  allowlist of `Store` methods, and that only the application marks and the run requests write.
- `entrypoints/web/filters.py` is the query-string model and stays free of FastAPI (a test asserts
  it). Columns and filter fields come from `config.criteria`: never a hardcoded list.
- The UI is in English and must be usable by someone who has never seen the project.

### H. Extension points (interface + registry)
Only for families of interchangeable implementations chosen at runtime from configuration — all
four must hold: two or more implementations share a contract, the choice comes from config, callers
must not branch on the concrete type, the implementation is replaceable.

An ABC (not a bare Protocol) owns the registry, `register(key)` and `create(...)`. Each
implementation lives in its own file under the family's folder, self-registers with
`@Base.register(...)`, and the folder's `__init__` imports it so registration runs. Callers only
ever call `Base.create(...)` and the interface. Fail fast on an unknown key, listing known ones.

Do **not** use it for single-implementation services (`Evaluator`, `Fetcher`) or for data models.

## 5. Development workflow: workshop here, production there

Two machines, two roles. **Code is written and tested in the workshop; production only pulls.**

| | workshop (`stefare-PC`) | production (`stefare-optiplex3050`) |
|---|---|---|
| role | edits, tests, spikes, the model | web, worker, the **only** database |
| Python | 3.14.8 | 3.14.4 (its own `uv`) |
| DB | `data/dev.db`, throwaway | `data/jobs.db`, the history |

- **Code travels only through git.** Never `scp` sources: two checkouts with different content are
  a silent drift nobody notices until a run behaves differently.
- **`config/` and `.env` never travel.** They are per machine: the controller's `settings.yaml`
  points the engine at the model host (`base_url: http://10.10.0.2:8017` plus the `model_host`
  block); the workshop's points at `127.0.0.1` and has no `model_host` (it would wake itself).
- **The production database exists only on the controller.** A workshop run writes to
  `data/dev.db`; `data/jobs.pre-cutover.db` is a fixture (1100 real postings) for calibration and
  benchmarks, not a second source of truth.
- **`profile.yaml` is per machine and gitignored**: editing the rules in the workshop does not reach
  the controller. After changing them, copy the file and compare the digests before trusting the
  next run:
  `cat config/profile.yaml | ssh controller 'cat > ~/Projects/jobcaliber/config/profile.yaml'`, then
  `sha256sum` on both sides. The controller then records a new profile version and re-scores.
  `settings.yaml` is never copied: it is per machine by design.
- Deploy = `git -C ~/Projects/jobcaliber pull --ff-only && uv sync --frozen && uv run pytest -q`
  on the controller, then `systemctl --user restart jobcaliber-web` (and the worker when enabled).
  The suite must be green on **both** machines: the Python patch versions differ, which is exactly
  the kind of drift worth catching.
- The cold path (wake a powered-off model host) can only be tested from the controller, with a
  detached script: powering off the workshop kills the agent's own session.

## 6. Working agreements

- Keep the repo root tidy: personal state lives in `data/`, configuration in `config/`, docs in
  `docs/`, deployment in `deploy/`.
- A commit does one thing and says what it did; the body explains *why* when it is not obvious.
- Record decisions, traps and measurements in `AGENT_PLAN.md` — the next agent starts from there.
- When a plan turns out to be wrong mid-implementation, stop and return to the proposal.

## Lessons learned

- 2026-10-14: `python-jobspy==1.1.82` needs `pandas<3`; its country parameter is `country_indeed`,
  and `NaN` from JobSpy must become `None`.
- 2026-10-14: multi-page LinkedIn pagination works with `offset` stepping by page size.
- 2026-10-15: local decision engines compared on 20 real postings. `laya` (322M) was flat (all 20
  `review`, scores 69–76) — rejected, but note its *AUC* was never measured, only its verdicts.
  `rizzo-flow` discriminates best and runs on the AMD 760M via Vulkan (~4.6× its own CPU path).
- 2026-10-15: `gpt-oss:20b` is a MoE (~3.6B active), so "20B vs 4B" is not a speed intuition;
  generative engines vary with output length, decision engines are single-pass and stable.
- 2026-10-15: Jev is reachable free through the opencode Zen gateway
  (`POST https://opencode.ai/inference/v1/systemone`, model `jev-1.13-free`); it is fast (0.39 s)
  and stricter. Its free tier returns 429 in bursts, so the retry policy then costs ~30 s/call —
  keep it as a reference engine, not the production scorer.
- 2026-10-22: SQLite writes UTC; comparing those timestamps with a local clock made the worker
  start a run at every poll. `is_due()` parses the stored value as UTC and builds the slot in the
  configured zone.
- 2026-10-22: the engine must be probed **before** the fetch: an engine that is down used to cost a
  full 28-minute fetch before failing on the first offer.
- 2026-10-22: YAML 1.1 reads bare `yes`/`no` as booleans — quote option keys and verdict labels.
- 2026-10-23: `penalties` (confidence discounts for a missing answer) were dead code: a penalty is
  applied only when an answer is missing, and a missing answer returns `review` *before* the
  confidence is read. Removed.
- 2026-10-23: renaming an SQLite table rewrites every foreign key that points at it; rebuild with
  create-new → copy → drop → rename, and run `PRAGMA foreign_key_check` at the end.
- 2026-10-23: copying `jobs.db` alone can silently lose the last writes (WAL). Use
  `jobcaliber db backup`, which goes through SQLite's backup API.
- 2026-10-24: a systemd `ExecStartPost` that fails **kills the main process**, and `systemd-run`
  inside a system service is denied without a polkit session ("requires interactive
  authentication"). A watchdog in `ExecStartPost` needs the `+` prefix (run as root) and `-`
  (non-fatal), or it turns a safety net into an outage.
- 2026-10-23: Ollama reasoning models (qwen3.5, granite 4.2) spend the whole answer budget on
  "thinking" unless the request carries `reasoning_effort: "none"`; without it every call timed out
  at 120 s.
