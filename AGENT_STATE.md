# AGENT_STATE.md — current snapshot

> Internal handoff for the agent working on this repo. For users and for a fresh
> install, start from [`README.md`](README.md) and [`docs/INSTALL.md`](docs/INSTALL.md).
> This file is the "where we are right now"; `AGENT_PLAN.md` is the log, `AGENTS.md` the rules.

Last updated: 2026-10-25 · tests: **261 passing** · branch `main` @ `44c3e8b`, pushed, both
machines at the same commit.

## What jobcaliber is

A personal, local job-offer ranker. Every morning it queries LinkedIn + Indeed for the configured
titles/locations, scores every new offer against the user's own criteria with a **pluggable**
engine (default `rizzo`, a local 4B decision model on the model host), decides
`pass`/`review`/`drop`, stores everything in SQLite, shows it in a local web app where the user
marks the offer (`applied`/`planned`/`skipped`), and sends a Telegram digest. It never re-scores
the same offer with the same config+engine and never re-notifies.

## Architecture (layers, enforced by `tests/test_layers.py`)

```
src/jobcaliber/
├── core/            domain.py · formatting.py (UTC → local)
│                    config/ (search, criteria, ai, settings, app) — no I/O
├── pipeline/
│   ├── fetch/       models.py (Query, FetchStats) · queries.py · parsing.py · fetcher.py
│   ├── scoring/     scorer/ (base.py ABC + system_one.py + llm.py)
│   │                projection/ (systemone.py, llm.py — rubrics from `criteria`)
│   └── evaluation/  evaluator.py (gates → thresholds → decision → confidence)
├── infrastructure/  database/ (store.py, schema.sql, schema_version.py, migrations/, migrate.py)
│                    ai/ (client/base.py ABC + system_one/llm, prompts.py)
│                    model_host.py · notify/telegram.py · config_loader.py · env.py
├── application/     runner.py (run_once) · worker.py (poll, claim, retry, hot reload)
│                    schedule.py (is_due) · clients.py (transports → services)
├── entrypoints/     cli.py (`jobcaliber`) · worker.py (`jobcaliber-worker`)
│                    web/ (routes.py, filters.py — HTTP-free, readmodels.py, templates/, static/)
└── bootstrap.py     build_context() → AppContext(root, config, raw_yaml, store, engine, tz)
```

Direction: `entrypoints` → `application` → `pipeline`/`infrastructure` → `core`. Only entrypoints
may import everything.

## Invariants (do not break without a decision)

1. **A missing answer never drops**: it forces `review` and is exempt from thresholds. `missing`
   in a criterion names the level an absent answer gets (unless `missing: null`).
2. **Gates drop only on an explicit negative**: `gate: true` (answer must be `yes`),
   `gate: {accept: [...]}`, `gate: {min_score: x}`.
3. **Re-scoring key** = `UNIQUE(job_id, config_v, engine)`: same profile+engine is a no-op; a new
   profile or engine re-scores everything. `score_total` is the plain mean, ordering only; every
   drop names its rule (`dropped_by`). No weights, no penalties.
4. **Config split by cost**: `config/profile.yaml` (search + evaluation + criteria) keys the
   evaluations (`config_versions` over the profile text + `RUBRIC_VERSION` in code);
   `config/settings.yaml` (db_path, scraping, schedule, notifications, ai) never re-scores. A key
   in both files is an error. Templates: `config/*.example.yaml`.
5. **The engine is probed before the fetch** (`AIClient.probe()`, TCP connect): a dead engine fails
   in ~40 ms, not after a 25-minute fetch, and is **not retried**.
6. **Schema changes are manual**: a process creates an empty DB, never alters one (`SchemaMismatch`);
   `jobcaliber db migrate` backs up and applies one transaction per step. `migrations/` is
   append-only; `SCHEMA_VERSION` is asserted at import. Live schema **v4**.
7. **The web is read-mostly**: it may write only the application marks and `runs(status='requested')`
   — asserted by a test on the allowed `Store` methods.
8. **No criterion name, threshold or heuristic hardcoded** anywhere; web columns and filters come
   from `config.criteria`.
9. **English only** in the repo (code, docs, UI, commit messages); chat may be Italian.
10. **Nothing is implemented before the user agrees** (`AGENTS.md` §0); commits/pushes need approval.

## Two machines (code via git, config/`.env` per machine, DB only on the controller)

| | workshop = model host (`stefare-PC`) | production = controller (`stefare-optiplex3050`) |
|---|---|---|
| role | edits, tests, spikes, the engine | web :8000, worker, the **only** DB |
| address | `10.10.0.2` (cable) · `192.168.1.28` (Wi-Fi) | `10.10.0.1` (cable) · `192.168.1.240` (Wi-Fi, static) |
| python | 3.14.8 | 3.14.4 |
| data | `data/dev.db` (throwaway) + `data/jobs.pre-cutover.db` (fixture) | `data/jobs.db` |

- Direct cable between the machines, **no gateway** on it (internet stays on Wi-Fi).
- The controller wakes the host (WoL `magic`, **29 s from S5**), starts/stops `rizzo` and powers
  the machine off through three forced-command SSH keys (`host-start`, `host-stop`,
  `host-poweroff` = `~/.ssh/host-*`), sudoers-limited to `systemctl start|stop rizzo` and
  `poweroff`. Rule: **leave the host as you found it**.
- `rizzo.service` (system unit on the host, from `deploy/rizzo.service.example`, **not enabled**):
  `SuccessExitStatus=143`, `ExecStartPre` disarm, `ExecStartPost` arms a 3 h `poweroff` watchdog,
  `ExecStopPost` disarms it (the timer lives exactly as long as the engine).
- **The host must not suspend during a run** (~30 min, nobody at the keyboard): the unit does *not*
  use `systemd-inhibit` (a system service has no logind session → polkit denies → the engine never
  starts). The guard is in `~/.config/hypr/hypridle.conf`:
  `on-timeout = systemctl is-active --quiet rizzo || systemctl suspend`.
- Deploy: `git pull --ff-only && uv sync --frozen && uv run pytest -q` on the controller, then
  `systemctl --user restart jobcaliber-web` (and the worker when enabled). Green on **both** machines.

## Commands

```bash
uv sync --frozen && uv run pytest -q                 # 261 tests
uv run jobcaliber run [--limit N --max-queries M --dry-run --engine NAME]
uv run jobcaliber status | jobs --decision review
uv run jobcaliber db version | check | backup [--to PATH] | migrate [--dry-run]
uv run jobcaliber-worker [--poll S] [--once]
uv run uvicorn jobcaliber.entrypoints.web:create_app --factory --host 0.0.0.0 --port 8000
```

Engines (`ai.engines`, keyed by wire api `systemone`/`openai`, not by product): `rizzo`
(`127.0.0.1:8017`, production scorer), `onejev` (:8018, rejected: fast but blind), `jev`
(opencode gateway, free tier throttles), `qwen3_llm`/`qwen35_llm`/`granite_llm` (Ollama,
`reasoning_effort: none` required), `opencode_llm` (deepseek via `/inference/go/v1` + session
header). `ai.roles.scorer` picks the default.

## Current data (production DB, gitignored)

- **1139 jobs · ~2167 evaluations · 5 applications · run 13 ok · `config_v 3` · schema v4**.
- Criteria: `core_skills`, `tools`, `role_fit` (min .5 / apply .67), `pay` (apply .75),
  `location` (choice gate `accept: [accepted]`), `applicable` (choice gate), `contract_ok`
  (bool gate).
- Schedule **06:00** in `Europe/Rome` (one run a day), 8 queries × 2 boards ≈ 1609 rows in 25–35 min,
  scoring ~6.6 s/offer on the iGPU. Run 13: 38 new, 31 drop / 7 review / 0 pass, 33 min.
- **165 `review` in the notification backlog** (left by user choice; the next digest lists them).

## Web (verified in a browser)

- `/jobs` — one filter field per column (all AND, groups: score & decision · job · criteria ·
  status & dates), "show columns" sub-box, Apply/Reset, sortable headers, pagination; criteria
  columns and filters generated from config. Logic in `entrypoints/web/filters.py` (no HTTP, no
  FastAPI — a test asserts it).
- `/jobs/<id>` — decision, score/confidence, `dropped by`, answers vs thresholds, ad link, markdown
  description (raw HTML escaped), three mark buttons + undo, back-link restoring filters/sort/page.
- `/runs` — queue + history, auto-refresh while a request is pending. `/applications` + `.csv`.
- `/run` enqueues (`runs.status='requested'`); the web never runs the pipeline. Light/dark automatic.

## Notifications

Telegram digest per run with every new **pass and review** not marked applied/skipped; header counts
pass/review; each line labels the decision and links `/jobs?decisions=pass,review&run=<id>`; 10 then
"…and N more"; HTML escaped; 4096-char cap; `notified_at` for idempotency; a delivery failure never
fails the run. Bot `@jobcaliber_bot`, chat id in settings, token in `.env` (600, both machines).

## Traps learned (do not re-discover)

- **Time**: the DB is UTC; `schedule.timezone` (IANA, required) defines `scrape_times` and rendered
  dates; `AppContext.tz` resolved once; `core/formatting.local_time` is the only formatter. Comparing
  a stored UTC timestamp with `datetime.now()` made the worker run on every poll.
- **`pgrep -f <pattern>` matches its own shell**: a `pgrep -f "rizzo serve"` guard in hypridle would
  always match, so the machine would never suspend (same class of bug as `pkill -f` killing the
  session). Use `systemctl is-active --quiet rizzo`.
- **`systemd-inhibit`/`systemd-run` in a system service have no polkit session**: `Access denied …
  requires interactive authentication`. Inside a unit prefix with `+` (run as root); a failing
  `ExecStartPost` **kills the main process** (hence `-` for non-fatal).
- **`systemctl stop` exits 143**: `SuccessExitStatus=143` or the unit looks `failed` after a clean stop.
- **Watchdog must die with the engine**: an `ExecStartPost` timer that is never disarmed powers the
  machine off at +3 h, e.g. at 09:00 while the user works (`ExecStopPost` fixes it).
- **hypridle only suspends on compositor idle**: the waybar `idle_inhibitor` button is the Wayland
  idle-inhibit protocol (needs a client in the session), cannot be driven from the controller.
- **Copying `jobs.db` alone loses writes (WAL)**: use `jobcaliber db backup`. A v4 migration on a
  plain copy found 0 rows for exactly this reason.
- **YAML 1.1**: bare `yes`/`no` are booleans — quote option keys and verdict labels.
- **HTML hrefs in tests are escaped** (`&amp;`) — `html.unescape` before following them.
- **System One wire rejects extra fields** (`missing_level`/`missing_choice` stay in config).
- **SQLite cannot alter a `CHECK`**: create new → copy → drop old → rename; renaming rewrites
  other tables' FKs, so `PRAGMA foreign_key_check` at the end.
- **Ollama reasoning models** spend the answer budget thinking unless `reasoning_effort: "none"`.
- **Avahi cannot alias its own machine** (`Local name collision`), and `firewalld` blocks mDNS 5353.
- **OneJev 0.8B rejected**: 1.31 s/offer but 74% missing on `core_skills` and two criteria inverted.

## Open work / next steps

1. **First fully unattended run** (06:00, worker enabled): wake → fetch → score → digest → poweroff.
   Confirm from `/runs`, `journalctl --user -u jobcaliber-worker`, and `systemd-inhibit --list`.
2. **Backlog**: the 165 `review` postings will appear in the next digest; decide whether to re-score
   them (`--engine`, profile unchanged) or mark them in bulk.
3. **Calibration on real verdicts**: extend `spikes/03_calibration/calibrate.py` to read labels from
   the ledger (`applied`/`planned` vs `skipped`) and tune thresholds (`pay` 0.75 blocks 5/7 reviews;
   `tools`/`contract_ok` AUC ≈ 0.51/0.52 — near noise).
4. **Nightly backup** on the controller (`schedule.backup_time` is still dead config; the ledger is
   not reconstructible).
5. **Config editor**: profile versioned in the DB, YAML import/export, diff between `config_v`.
6. Small: highlight the failing criterion on the detail page ("why is this review?").

## Open questions for the user

- Bulk handling of the `review` backlog: re-score, or mark in bulk?
- Calibration: how many verdicts before tuning thresholds (suggest ≥ 30)?
- Dark mode: keep automatic, or add a manual toggle (needs a preference + JS)?
