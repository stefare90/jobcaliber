# AGENT_STATE.md — current snapshot (read this first)

Dense handoff for a fresh context. History and decisions live in `AGENT_PLAN.md`; binding rules in
`AGENTS.md`; user-facing docs in `README.md`. This file is the "where we are right now".

Last updated: 2026-10-22 · tests: **201 passing** · branch `main`, pushed.

## What jobcaliber is

A personal, local job-offer ranker. Every morning it queries LinkedIn + Indeed for the configured
titles/locations, scores each new offer against the user's own criteria with a **local decision
model** (rizzo-flow on `127.0.0.1:8017`), decides `pass`/`review`/`drop`, stores everything in
SQLite, and shows it in a local web app where the user marks 👍/👎 (the feedback that will
calibrate the thresholds). Never re-scores the same offer with the same config, never re-notifies.

## Architecture (layers, enforced by `tests/test_layers.py`)

```
src/jobcaliber/
├── core/            domain.py (JobPosting, ScoringResult, EvaluationResult, GateDecision)
│                    config/ (search.py, criteria.py, ai.py, settings.py, app.py) — no I/O
├── pipeline/        one folder per step
│   ├── fetch/       models.py (Query, FetchStats) · queries.py · parsing.py · fetcher.py
│   ├── scoring/     scorer/ (base.py ABC + system_one.py + llm.py) · projection/ (systemone/llm)
│   └── evaluation/  evaluator.py (gates → thresholds → decision)
├── infrastructure/  database/ (store.py, schema.py, schema.sql, migrations/, migrations runner)
│                    ai/ (client/base.py ABC + system_one/llm + prompts.py) · config_loader.py · env.py
├── application/     runner.py (run_once) · worker.py (loop, claim, retry, hot reload)
│                    schedule.py (is_due) · clients.py (AIClients: transports → services)
├── entrypoints/     cli.py (`jobcaliber`) · worker.py (`jobcaliber-worker`)
│                    web/ (routes.py, readmodels.py, templates/*.html.j2, static/style.css)
└── bootstrap.py     build_context() → AppContext(root, config, raw_yaml, store, engine)
```

Dependency direction: `entrypoints` → `application` → `pipeline`/`infrastructure` → `core`.
Entry points are the only place allowed to import everything.

## Invariants (do not break without a decision)

1. **A missing answer never drops.** `missing` → neutral 0.5, confidence penalty, forced REVIEW.
2. **Gates drop only on an explicit negative answer** (`gate: true` → answer must be `yes`;
   `gate: {accept: […]}`; `gate: {min_score: x}`).
3. **Re-scoring key** = `UNIQUE(job_id, config_v, engine)`: same config+engine is a no-op, a new
   config or engine re-scores everything.
4. **A run probes the engine before fetching**: `AIClient.probe()` (TCP connect) is called
   before `_collect`, so a dead engine costs ~40 ms instead of a whole fetch (~28 min). That
   failure is **not retried** (`RunOutcome.retryable = False`): retrying cannot fix a stopped
   service, and the worker must not burn its 3 attempts on it.
5. **Config split by cost**: `profile.yaml` (search + evaluation + criteria) keys the evaluations
   (`config_versions(v, yaml, sha)` over the profile text + `RUBRIC_VERSION`); `config/settings.yaml`
   (scraping, schedule, notifications, ai, db_path) never re-scores. A key declared in both files
   is rejected. Same content → same version; new profile → new version.
6. **Schema changes are manual**: `Store` *creates* an empty DB, never alters an existing one;
   `jobcaliber db migrate` applies migrations (backup + one transaction per step). `db check`
   diffs the live schema against `schema.sql`.
7. **The web is read-mostly**: it may write only `feedback` (upsert) and `runs(status='requested')`
   — enforced by a test on the allowed `Store` methods.
8. **No criterion name, threshold or heuristic is hardcoded** anywhere (web, evaluator, fetch).
9. **English only** in the repo (code, docs, UI strings, commit messages). Chat may be Italian.
10. **Nothing is implemented before the user agrees** (`AGENTS.md` §0, absolute).

## Commands

```bash
uv sync --frozen && uv run pytest -q          # 201 tests
uv run jobcaliber run --limit 5 --max-queries 1   # one bounded pass
uv run jobcaliber run --dry-run                   # nothing written
uv run jobcaliber status | jobs --decision review
uv run jobcaliber db version | check | migrate --dry-run | migrate | backup
uv run jobcaliber-worker --poll 5                 # loop (systemd keeps it alive)
uv run jobcaliber-worker --once                   # one tick (queue check / post-deploy)
uv run uvicorn jobcaliber.entrypoints.web:create_app --factory --port 8765
```

Engines: `rizzo` (local, needs `cd ~/rizzo-flow && uv run rizzo serve --port 8017 --device auto
--quant q4_k_m`), `jev` (opencode System One, free tier, `OPENCODE_API_KEY` in `.env`),
`local_llm` (Ollama qwen3:8b), `opencode_llm` (deepseek via `/inference/go/v1` + `x-opencode-session`
header). Default `roles: {scorer: rizzo}`.

## Current data (dev DB `data/jobs.db`, gitignored)

- **Reset on 2026-10-23** (the pre-reset file is in `/tmp/jobs.db.before-reset-*.db`): the first
  clean run scored 26 postings (18 drop, 8 review) in 145 s with rizzo.
- Criteria: `core_skills`, `tools`, `role_fit` (min .5 / apply .67), `pay` (apply .75),
  `location` (choice gate accept accepted/rejected/unknown), `applicable` (bool gate, `in_table:
  false`), `contract_ok` (bool gate).
- Thresholds: notify 70, review 60, min confidence 0.55. Schedule 08:00/13:00/19:00 in
  `Europe/Rome`, retries 3.
- Search: 4 titles × `Sardinia, Italy` (on-site) + `Italy` (remote).

## Web (implemented, verified in a browser)

- `/jobs` — table with **dynamic criterion columns** (default = criteria with `in_table: true`),
  collapsed filter panel with **cards** on 3 columns (Run, Text incl. "Ad location", Board,
  Decision, Criterion, Columns picker at 3 columns), chips summarising active filters, sortable
  headers incl. `sort=crit:<name>`, pagination.
- `/jobs/<id>` — decision badge, score/confidence, `dropped by`, answers vs thresholds, link to the
  ad, **markdown description** (markdown-it-py, `html=False` → raw HTML escaped), 👍/👎 feedback.
- `/runs` — queue + history, auto-refresh while a request is pending; `POST /run` enqueues.
- Light/dark via `prefers-color-scheme` (variable palette, `color-scheme: light dark`).
- The detail link carries the list query string, so "back" restores page, filters and columns.

## Traps learned (do not re-discover)

- **Time**: the DB is UTC (`datetime('now')`), `schedule.timezone` (IANA, required) defines the
  wall clock of `scrape_times` and of every rendered date; `AppContext.tz` is resolved once in
  `bootstrap`, `is_due` compares UTC instants, `core/formatting.local_time` is the only formatter
  (web filter + CLI, and the notifier later). Never call a bare `astimezone()`.
- **`penalties` were dead code**: a penalty only applies when an answer is missing, and a missing
  answer returns REVIEW *before* confidence is read — so a penalty could never change a decision.
  Removed. `missing` alone forces REVIEW.
- **SQLite `datetime('now')` is UTC, the schedule is local**: comparing them raw made every
  scheduled run look two hours old, so the worker started a new one on every poll. `is_due` now
  interprets the stored value as UTC and builds the slots in `schedule.timezone`.
- **YAML 1.1**: bare `yes`/`no` are booleans — quote option keys and label verdicts.
- **HTML hrefs in tests are escaped** (`&amp;`): `html.unescape` before following them.
- The System One wire **rejects extra fields** (`missing_level`/`missing_choice` stay in config).
- SQLite cannot alter a `CHECK`: table rebuild = create new → copy → drop old → rename, with
  `PRAGMA foreign_keys=OFF` around it (renaming the old table rewrites other tables' FKs).
- Ollama qwen3 emits `reasoning` and never returns JSON unless `reasoning_effort: "none"`.
- `localhost:8000` is taken by VS Code on this machine; use 8765.
- `firewalld` is **active** here; port must be opened for LAN access. Machine IP `192.168.1.28`
  (wlan0), hostname `stefare-PC`, Avahi active.
- A full first run on an empty DB is ~1.5-2h (fetch ~25 min + ~900 postings × 5 s).

## Notifications (implemented 2026-10-23)

`infrastructure/notify/telegram.py` (httpx, no framework): one digest per run with every new
`pass` posting, ad link + `/jobs?decisions=pass&run=<id>`; 10 offers then "…and N more"; HTML
escaped; 4096-char cap; `notified_at` for idempotency; a delivery error never fails the run.
Bot `@jobcaliber_bot`, chat id in gitignored `config/settings.yaml`, token in `.env`.

## Applications (implemented 2026-10-23)

`applications(job_id PK, state ∈ applied|planned|skipped, source, note, created_at, updated_at)`
replaces `feedback`: the mark belongs to the **posting**, not to the evaluation, so a re-score no
longer orphans it. Schema v4; the five old verdicts were migrated (`good → planned`,
`bad → skipped`, `source = feedback:<verdict>`, original timestamps kept). Web: three buttons on
the detail page, a `status` column + `state=` filter in the list, `/applications` and
`/applications.csv`. Telegram skips any posting that has a mark.

## Open work

- **Now**: application ledger (feedback becomes "applied / will apply / not interested", keyed on the
  job, with a `/applications` page and an export).
- Deferred: nightly backup, model calibration, live run counters, config editor + profile diff.
- At the server: three systemd units (incl. rizzo), engine choice for the i5.

## Next steps (agreed, not started)

1. ~~LAN access~~ **done**: the unit binds `0.0.0.0`, README has "Access from your phone"
   (mDNS `stefare-PC.local`, alias `jobcaliber.local` via `/etc/avahi/hosts`, Android caveat,
   Tailscale option, no-auth warning). Verified: `--host 0.0.0.0` answers on `192.168.1.28:8870`.
2. Install the systemd units (`loginctl enable-linger stefare`); port 8000 is free again.
3. Telegram notifier with a link to the page.
4. Calibration on real feedback (`spikes/03_calibration/calibrate.py`), then drop `review` from the
   learning-mode default.

## Open questions for the user

- Telegram: digest only, or instant alerts above threshold too?
- Calibration: how many verdicts before tuning thresholds (suggest ≥30)?
- Dark mode: keep automatic, or add a manual toggle (needs a preference + JS)?
