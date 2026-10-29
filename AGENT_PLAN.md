> Internal chronological log (agent handoff). User-facing docs: `README.md`, `docs/INSTALL.md`,
> `docs/OPERATIONS.md`, `docs/ARCHITECTURE.md`, `config/README.md`.

> Current snapshot: see `AGENT_STATE.md` (kept short and always up to date). This file is the
> chronological log.

# AGENT_PLAN.md — agent-only build plan

Not user docs. The user reads `README.md`; the agent works from here.
Single source of truth for what is done and what remains, in execution order.
Spec references: idea pack `HANDOFF.md`, `piano-w1.md`, `requisiti.md`, `schema.sql`,
`config.example.yaml` v4, `jev-questions.md`.

## DONE

- [x] Repo init (2026-10-14) — `uv` project `jobcaliber`, `pyproject.toml`
  (`python-jobspy==1.1.82`, `pandas>=2.1,<3`, `httpx`, `pyyaml`, `beautifulsoup4`),
  `requires-python >=3.11`, layout `src/jobcaliber spikes tests data`,
  `schema.sql` + `config.example.yaml` + `jev-questions.md` copied from idea pack,
  `.gitignore` (incl. `config.yaml`), `README.md`, `AGENTS.md`.
- [x] S1 spike (2026-10-14) — now `spikes/01_fetch_coverage/fetch_coverage.py` +
  `output/report.md` + `output/raw/q<idx>_<board>.json`.
  Queries from `profile.target_roles x preferred_locations`,
  `country_indeed=italy, hours_old=24, results_wanted=15/board`, sequential, no login,
  no scorer, NaN→None, captcha rows dropped before save.
  Result: linkedin 34 usable (q1=15, q2=4, q3=15), indeed 0, google 0
  (`initial cursor not found`), no captcha stored → verdict FAIL (bar ≥5/query,
  missed by 1 row on q2). No LinkedIn hard block → no full pivot.
- [x] Docs split (2026-10-14) — `README.md` holds product/install/usage only;
  this file holds done/todo. `AGENTS.md` holds binding rules + lessons.
- [x] Config aligned to user (2026-10-14) — personal `config.yaml` (gitignored) mirrors
  the real search: regional titles, the user's seniority and contract preference, a home
  region plus Remote-IT. Spike loads `config.yaml` when present (else the example), cyclic
  role×location pairing, geo map to the board's `Region, Country` string.
  `config.example.yaml` keeps generic defaults.
- [x] S1 re-run with user params (2026-10-14) — q1/q3 @Sardinia 24h: 0 rows on all
  boards (not the fulltime filter, not the geo string — verified both). q2 @Remote:
  15 LinkedIn rows, pertinent titles, worldwide locations, zero Italy.
  Diagnosis: 24h window too tight for the Sardinia market (unfiltered: 7 genuine
  Sardinia rows incl. one posted yesterday, missed by the 24h filter). Consequence:
  Region-scoped queries need hours_old 72+ or no limit + dedup; remote needs a
  location post-filter.
- [x] Our location filter + wide window (2026-10-14) — `location_bucket`
  (sardinia/remote/unknown kept, elsewhere dropped, both lists in report),
  `HOURS_OLD=None` restored and `RESULTS_WANTED=50` in spike, `hours_old: null`,
  `results_wanted: 50` in `config.yaml`. Volume run: 70 usable (q1 7, q2 50 capped,
  q3 13), 24 kept / 46 dropped worldwide. Open: fetch keywords too narrow vs user's
  LinkedIn (role-only gives 16 vs 7 for a city-scoped query) → proposal: role-only
  fetch + skill matching in scorer.
- [x] Titles instead of target_roles (2026-10-14, config v5) — `profile.titles` holds bare
  roles, seniority is query-free. 93 usable (q1 24 incl. first 4 Indeed rows, q2 50 capped, q3 19),
  45 kept / 48 dropped, PASS. Next: title gate (Indeed civile/SUAPE are kept today).
- [x] Remote fixed + manual variants (2026-10-14) — remote queries fetch Italy-wide
  with `is_remote` + description-based bucket (no-remote guard). `extra_searches`:
  Firmware q4 = 0 rows, Backend q5 = 133 rows. 279 usable, 118 kept (44 sardinia,
  65 remote, 9 unknown) / 161 dropped. Verdict FAIL only because q4 is empty;
  coverage goal met. Open: replace q4 variant, title gate, LLM variants in W2.
- [x] Pagination (2026-10-14) — 100/page up to 300 cap per query/board, verified
  working. Pools fluctuate between runs; this snapshot: 233 usable. Open: Glassdoor
  board test, ATS sources (W1).
- [x] Full title×location matrix (2026-10-14, user catch) — cyclic pairing was a
  shortcut; `per_role_location: true` means every combination. 8 queries,
  561 usable. New finds: q2 Software@Italy Indeed 66 rows, q6 Python@Italy 117.
  FAIL only from q7 (Firmware Sardinia).
- [x] First class `Fetcher` (2026-10-14) — `src/jobcaliber/fetch.py` (queries from
  profile, paginated per-board fetch, NaN→None, captcha never stored, dedup,
  board errors recorded). `tests/test_fetch.py`: 9 passed. Verified against real
  `config.yaml` (5 queries). Spike still runs standalone; port to class next.
- [x] GEO_FETCH out of the class (2026-10-14, user catch) — user geo mapping lives
  in `query_builder.location_aliases` (empty in example, personal values in
  `config.yaml`); class defaults to identity. 10 passed, same 5 queries.
- [x] Remote vocabulary + full pagination (2026-10-14) — 673 usable (q2+q5 both
  hit the 300 cap; q4 still empty → FAIL verdict on bar only). Buckets: 43 sardinia,
  219 remote, 81 hybrid, 12 unknown, 318 elsewhere. Nothing stuck: capped runs take
  minutes of page fetching.
- [x] Full descriptions in S1 report (2026-10-14) — spike fetches LinkedIn
  descriptions (`linkedin_fetch_description` on LinkedIn board only) into raw JSON;
  `spikes/01_fetch_coverage/output/report.md` stays compact (one `query/board: title — company | url` line
  per job) to limit growth. Superseded same-day: full-text section removed per user.
- [x] Evaluator & Job Parameters Config (2026-10-14) — `config.yaml` / `config.example.yaml`
  migrated to `job_parameters` schema with configurable mode (`hard_gate`, `hybrid`, `weighted`).
  Implemented `src/jobcaliber/evaluator.py` (location matching with remote/hybrid detection,
  salary extraction & cutoff, garbage titles filtering, confidence penalty).
  Added unit tests in `tests/test_evaluator.py`: 17 passed.
- [x] Spikes directory reorganization (2026-10-15) — organized spikes into step-based subdirectories:
  `spikes/01_fetch_coverage/` (scraping harness, raw outputs, reports) and the engine benchmark scripts,
  reports, and `utils/` for embedder/servers). Updated paths and docs. Test suite 15/15 green.
- [x] CLM Cleanup & Pivot (2026-10-15) — benchmarked CLM unquantized on CPU (~25s per full job posting, impractical).
  Cleaned all temporary CLM environments, HF cache, and utility servers.
- [x] Local System One engine selection (2026-10-15) — compared ollama (gpt-oss:20b),
  laya (322M), rizzo-flow (Spark-4B+LoRA) on the same 20 postings via
  `spikes/02_engine_benchmark/engine_benchmark.py`. laya flat (20/20 REVIEW), ollama conservative (0 PASS),
  rizzo best discrimination (5 PASS) and Jev-native on Vulkan iGPU. **Chosen: rizzo-flow.**
  `config.yaml`/`config.example.yaml` point `ai_engine` at `http://127.0.0.1:8017`.
  Removed `.laya-env`, laya HF cache (freed ~17GB orphan blobs), laya report.
  Ollama kept as explainer/fallback. Suite 15/15 green.
- [x] Two-phase workflow rule + git-guard extension (2026-10-15) — added AGENTS.md
  section 0: planning with the user -> approval -> development -> versioning with
  approval before commit/push. Added `.pi/extensions/git-guard.ts` (adapted from
  musicare_workspace): Conferma/Rifiuta menu on every git write, commit dialog
  with message+files, conventional-commit validation, destructive ops blocked,
  and on Rifiuta it asks the user for a reason and returns it to the agent.
  Added jobcaliber to `~/.pi/agent/trust.json` so the project extension loads.
  Verified the extension loads via jiti (default export is a function).
- [x] Jev via opencode gateway (2026-10-15) — real `jev-1.13-free` reachable at
  `https://opencode.ai/inference/v1/systemone` with the opencode key (found in
  `/inference/v1`, not the go provider). Added engine `jev` to the benchmark script and
  `api_key_env` support to `scorer.py`. Result: 0.39s mean, free, discriminates
  but stricter (0 PASS). `output/report-jev.md` + `output/comparison.md` updated.
  Decision: keep **rizzo (default, local)** + **jev (reference)**; calibrate both
  in W2. Suite 17/17 green.
- [x] Typed configuration models (2026-10-15) — new `src/jobcaliber/config.py`
  (Pydantic v2): `AppConfig`, `Profile`, `Skills`, `LocationPrefs`, `JobFilters`,
  `FilterParam`/`PayFilter`/`LocationFilter`, `Notifications`/`TelegramNotifications`,
  `Scraping`/`ExtraSearch`, `Schedule`, `AIEngine` (+ `resolve_api_key`), and
  `load_config()`. Refactored `Fetcher(scraping)` + `build_queries(profile)`,
  `SystemOneScorer(ai_engine)` with `Profile`, `Evaluator(AppConfig)`; spikes updated.
  No config `dict` crosses a module boundary now. Added `tests/test_config.py`.
  Suite 22/22 green; jev spike re-run end-to-end with typed config.
- [x] AI package + prompt files (2026-10-15, config v9) — `AIEngine(kind, api, base_url,
  model, api_key_env)` (no literal `api_key` in YAML); `AIConfig(prompts_dir, engines,
  roles, custom_prompts)` with validation (kind/api coherence, role->engine kind). New
  `src/jobcaliber/ai/`: `clients.py` (`SystemOneClient`, `LLMClient`), `prompts.py`
  (`PromptStore`, `{{placeholder}}` render), `registry.py` (`AIClients.from_config`,
  `system_one(role)`/`llm(role)`/`by_name`). `SystemOneScorer(client, profile, prompts)`
  builds questions from `prompts/scoring_systemone/default.json`; added `explainer.py`
  and `query_expander.py`. Rewrote `config.yaml`/`config.example.yaml` to `ai:` schema.
  Tests: 32/32 green. Jev spike re-run OK (0.50s mean).
- [x] Source tree reorganization (2026-10-15) — `src/jobcaliber/` split by pipeline stage:
  `ingestion/` (fetch, query_expander), `scoring/` (scorer, evaluator), `delivery/`
  (explainer), plus placeholders `app/` (W1 CLI/scheduler/web); `ai/`, `config.py`,
  `models.py` unchanged at root. `tests/` mirrored (`ai/`, `ingestion/`, `scoring/`).
  Pure move: imports updated in spikes/tests, 32/32 green, both spikes run.
- [x] LLM scorer + role/kind decoupling (2026-10-15) — `ROLE_KINDS` values are now
  sets: `scorer` accepts `system_one` **or** `llm` (spec: `jev | free-llm | local`);
  `explainer`/`query_expander` require `llm`. Added `LLMScorer` (+ `build_scorer`
  dispatch and shared result builder) and `prompts/scoring_llm/default.md`.
  `AIClients` now exposes role services: `scorer(profile)`, `explainer()`,
  `query_expander()`. Spike S2 uses `build_scorer` for any engine. Tests 35/35 green.
- [x] Prompt/level cleanups (2026-10-15) — LLM `system` prompts moved into YAML front
  matter of `prompts/<kind>/*.md` (`PromptStore.load_llm`); no hardcoded SYSTEM strings
  in Python. `scoring_systemone` scales are derived from each question's `criteria`
  (no `SCORE_LEVELS`); pay "not stated" level inferred from criteria text. Location
  `bucket_scores` and `confidence_penalties` moved to `job_filters` in config (no
  `LOCATION_SCORES`/magic numbers in `evaluator.py`). Kind renamed `systemone_questions`
  -> `scoring_systemone`. Tests 38/38 green.
- [x] Fail-fast validation (2026-10-15) — `LocationFilter` rejects `bucket_scores`
  keys that do not equal `LocationBucket` values; `validate_systemone_questions()`
  (called in `SystemOneScorer.__init__` and by `AIClients.from_config` for the scorer
  role) enforces required score questions, `location` criteria == enum values, and a
  'not stated' pay level. A tampered prompt now fails at startup, not mid-run. Tests
  44/44 green.
- [x] Dead code/config removal (2026-10-15) — `Evaluator.evaluate(s1)` no longer takes
  an unused `posting`; removed `exclude_garbage_titles` / `exclude_body_keywords` from
  the config models and both YAMLs (declared but enforced nowhere). Pre-scorer omission
  gates are deferred to a W1 `ingestion/gates.py` with config-driven lists. 44/44 green.
- [x] Scorer interface + registry (2026-10-15) — replaced `build_scorer`/isinstance with
  `scoring/base.py`: `Scorer` protocol, `SCORER_REGISTRY` + `@register_scorer(kind)`, and
  `make_scorer(client, profile, prompts)` that resolves from `engine.kind`. Split scorers
  into `scoring/system_one.py` and `scoring/llm.py` (each self-registers); shared helpers
  in `base.py`. `AIClients.scorer(profile)` (role) and `AIClients.scorer_for(name, profile)`
  (benchmarks) hide the choice. Spike S2 uses `scorer_for`. Tests 44/44 green.
- [x] Registry into Scorer (2026-10-15) — `Scorer` is now an ABC carrying
  `_registry`, `register(kind)`, `create(client, profile, prompts)` and the shared
  helpers (`question_values`, `build_state`, `clamp`, `build_result`, `parse_json_object`,
  `missing_level`). `system_one.py`/`llm.py` subclass it and self-register; the module
  level `SCORER_REGISTRY`/`register_scorer`/`make_scorer` are gone. Tests 45/45 green.
- [x] AI transports aligned + extension-point rule (2026-10-15) — `ai/clients.py` now
  has `AIClient` ABC with `_registry`, `register(kind)`, `create(engine, http)` and shared
  `headers()`; `SystemOneClient`/`LLMClient` self-register by kind and the `if kind`
  builder is gone (`AIClients` uses `AIClient.create`). Added AGENTS.md section E
  ("Extension points"): when to use the interface+registry policy, the checklist for a
  new implementation, and when NOT to use it. Tests 46/46 green.
- [x] Family folders (2026-10-15) — transports split like scorers: `ai/base.py`
  (`AIClient` + registry) and `ai/clients/{system_one,llm}.py` (self-registering);
  scorers moved to `scoring/scorers/{system_one,llm}.py` with `ai/base.py`-style
  `scoring/base.py`. Each family's `__init__` imports its implementations to trigger
  registration. Imports updated; tests 46/46 green; spike smoke OK.
- [x] Family folder naming (2026-10-15) — `ai/base.py` + `ai/clients/` -> `ai/client/`
  (base.py + system_one.py + llm.py); `scoring/base.py` + `scoring/scorers/` ->
  `scoring/scorer/` (base.py + system_one.py + llm.py). One unambiguous path per family:
  `jobcaliber.ai.client` and `jobcaliber.scoring.scorer`. Tests 46/46 green.
- [x] Registry keyed by wire api (2026-10-15) — `AIClient.register(api, kind)` and
  `AIClient.create` now key on `engine.api` (`systemone`, `openai`), not on `kind`.
  Dropped the native Ollama `/api/generate` branch: Ollama is used through its
  OpenAI-compatible `/v1`, so `LLMClient` has a single wire. `KIND_APIS` narrowed to
  `{system_one: {systemone}, llm: {openai}}`; configs updated (`local_llm` -> `openai`,
  `http://localhost:11434/v1`). Verified live: Ollama `/v1` returns text; jev spike OK.
  Tests 46/46 green.
- [x] Kind renamed `system_one` -> `decision` (2026-10-15) — the kind now names the engine
  class (a decision model vs a generative LLM) and no longer collides with the wire api
  `systemone`. `KIND_APIS = {decision: {systemone}, llm: {openai}}`,
  `ROLE_KINDS[scorer] = {decision, llm}`; registries keyed by api stay unchanged
  (`{'openai': LLMClient, 'systemone': SystemOneClient}`). Configs and docs updated;
  tests 46/46 green.
- [x] `.env` secrets support (2026-10-15) — `src/jobcaliber/env.py` (`parse_env`,
  `load_env_file`, `load_env`) is called by `load_config()` before validating `AppConfig`.
  Keys come from the gitignored `<repo>/.env` (`chmod 600`, template `.env.example`);
  `os.environ.setdefault` keeps real env vars authoritative, and malformed lines raise
  `EnvFileError` at load. Plaintext key scrubbed from `~/.zsh_history`, pi session logs
  and the VS Code workspace state. Tests 51/51 green.
- [x] opencode-go LLM engine working (2026-10-15) — the failure was never the key: pi
  uses provider `opencode-go` on `/inference/go/v1` with the paid `deepseek-v4.1-flash`,
  while `/inference/v1` serves only the in-app free tier (`403 FreeTierError`) and the
  pay-per-use balance is empty (`402`). Added `AIEngine.headers` (merged by
  `AIClient.headers()`, config-driven, no hardcode); `opencode_llm` now points at
  `https://opencode.ai/inference/go/v1`, model `deepseek-v4.1-flash`, header
  `x-opencode-session: jobcaliber` (required by that endpoint, value free-form).
  Live reply `'OK'` in 1.68s; tests 53/53 green.
- [x] Config schema v8 & clean job_filters (2026-10-14) — consolidated config into 6 clear
  sections: `profile`, `job_filters` (rules, weights, excludes), `notifications` (thresholds, delivery),
  `scraping` (replaces fetch_defaults), `schedule`, and `ai_engine`.
  Updated `fetch.py`, `evaluator.py`, the fetch spike, and test suite. All 16 tests green.

## NEXT (in order, one at a time)

### S2 — location/pay extraction probe (before W1)

Goal: decide whether gates can rely on extracted sede/RAL or must fall back.
- Build an extract spike: run location + pay parsing over the raw fetch output
  LinkedIn rows (34 usable) + 10 hand-picked edge cases.
- Acceptance: ≥80% correct location bucket (remote/hybrid_ok/onsite_far/unknown),
  ≥70% correct pay band (good/mid/below/missing).
- Kill: below bar → board filters only + pay neutral + review queue (HANDOFF §5).
  Record verdict in the engine benchmark report.

### W1 — ingest + dedup + DB + Telegram stub (4-5d, fake score, no real scorer)

Binding acceptance from `piano-w1.md`. Stop at first red, report the pivot.

- [ ] T1 Skeleton (0.5d): `pyproject` add `fastapi, httpx, apscheduler,
  python-telegram-bot, pydantic`, `app/` layout (config, db, models, norm, dedup,
  gates, location_it, salary_it_stub, fetch_jobspy, scheduler, notify_telegram,
  web_stub), `install.sh`, logging + `HEALTHZ`.
  OK: `uv sync --frozen && uv run python -m app --check` green on PC and Pi.
- [ ] T2 DB (0.5d): apply `schema.sql` WAL, DAO `jobs/runs/feedback/config_versions`,
  norm helpers (lower/strip/punct).
  OK: `pytest tests/test_dedup_norm.py` green + `UNIQUE(external_id)` blocks re-insert.
- [ ] T3 Query builder (0.5d): `target_roles x preferred_locations` →
  JobSpy params via `keywords_template` + top-2 skills; read-only preview (web + CLI).
  OK: changing one role regenerates queries; no hand-written keywords in code.
- [ ] T4 Fetch (1d): JobSpy `country_indeed=italy, hours_old=24, results_wanted=30`,
  boards indeed+google (+linkedin light), per-board seen/new/error, 7d raw cache,
  NaN→None, bot-wall never stored.
  OK: dry run stores ≥5 real rows OR a readable board error in `runs.errors`
  (no crash, no captcha saved).
- [ ] T5 Dedup+gates (1d): URL norm + company+title hash; garbage + locale `it`;
  `body_exclude`; location hard gate (remote ok / hybrid≤40km / far drop / unknown→review).
  OK: golden 15 URLs (Indeed `jk` variants, tracking, case) dedup to ≤10 ids;
  10 sample postings gate as expected.
- [ ] T6 Telegram (0.5d): polling, chat whitelist, 20:00 digest + immediate stub
  (fake score 0 until W2), `/stato`, `/cerca` 1/h single-flight, Yes/No buttons
  storing `feedback` verdict.
  OK: digest arrives with counts; second identical run notifies 0; `/stato` shows last run.
- [ ] T7 Scheduler+runs (0.5d): APScheduler scrape 08/13/19 + digest + backup 03:00;
  every run writes a `runs` row (config_v, found/new/scored=0/notified/duration/errors/
  summary); missing digest = alarm; systemd `Restart=always`.
  OK: 3 consecutive ticks logged; kill -9 → auto-restart.
- [ ] T8 Tests+demo (0.5d): pytest (norm, dedup identity, gates, builder, idempotency)
  + demo script over 2 searches.
  OK: suite green; demo shows DB rows + digest + 0 duplicates on rerun.

NOT in W1: real scorer (Jev/free-llm), explainer text, `/calibra`, full web (stub
`/stato` only), Playwright, Postgres/Docker default, Gmail/tailoring/autofill,
multi-user, preview iframe.

### W2 — selection (Jev + formula + gate + golden 20)

- Atomic 5-question scorer via thin `scorer.py` wrapper (engine `jev|free-llm|local`),
  formula `45*core+20*tools+15*pay+20*contract` in code, confidence gate, golden-20
  calibration. Kill: precision@70 <60% or flat scores → deterministic formula +
  LLM extractor only.

### W3 — web + loop

- 5-tab local web (results/searches/weights/notifications/system), yes/no feedback,
  scheduler + backup wiring.

### W4 — calibration

- 30 labeled postings, filter/pay/location tightening, cost/run metrics, Tailscale opt-in.

## NEVER

Personal LinkedIn login, hourly mass crawling, auto-apply, pushing personal config,
committing `config.yaml`.
- [x] Spikes restructured (2026-10-19) — `spikes/s1,s2` -> `spikes/01_fetch_coverage` and
  `spikes/02_engine_benchmark`, each with `input/` (committed) and `output/` (gitignored,
  `spikes/*/output/`). Scripts renamed to `fetch_coverage.py` / `engine_benchmark.py`.
  Spike 01 is now fetch-only: the fabricated `SystemOneResult` plus the `"sard" in location`
  / `"smart working" in description` heuristics were removed (AGENTS §B forbids them), and
  it exports the frozen `02/input/postings.jsonl` (518 postings) instead. Real run:
  632 usable rows across 7 queries, 0 errors, 0 captcha, `q3` embedded@Sardinia = 3 rows ->
  honest FAIL. `output/raw/` is wiped at the start of each run so stale query files cannot
  leak into the frozen set (that bug made the first export count 764 rows from 8 queries). Spike 02 reads only `input/postings.jsonl` (jev 8 postings, 0.47s mean).
  Index + per-spike READMEs added; tests 53/53 green.
- [x] Project init (2026-10-19) — README rewritten as an accurate init document
  (Status matrix "done vs W1", AI engine table, real commands, secrets section, roadmap),
  stale references removed (`jev-questions.md`, config v8, Torino defaults). Repo scanned
  for secrets before the first commit: only the gitignored `.env` and a fake key in
  `tests/test_env.py`. `git init` must be run by the user: `git-guard` blocks every git
  write while the session dir is not yet a repo (`repoRoot` is null).
- [x] Pre-public scan (2026-10-19) — repo will be public. No credential, email, phone or
  absolute home path in any tracked file (the only `oc_sk_...` is a fake value in
  `tests/test_env.py`). Genericized the AGENT_PLAN notes that spelled out the user's real
  search (region, seniority, contract). Spike `input/` is now gitignored too (scraped
  posting text + personal query matrix), so the committed repo is 420K of code, prompts,
  config template, schema and docs.
- [x] Published (2026-10-19) — `git init` run by the user (the guard blocks git writes
  while the session dir is not a repo, and it caches `null` until `/reload`). Branch
  `master` -> `main`; root commit `20004b9` "chore: initial import of the jobcaliber
  pipeline skeleton" (54 files, 4704 insertions) pushed to
  https://github.com/stefare90/jobcaliber (public).
- [x] S2 state of the art (2026-10-19) — `AIEngine.options` (provider knobs merged into the
  LLM body, contract fields win, rejected for `decision` kind); `local_llm` switched from
  `gpt-oss:20b` (44.5s/posting) to `qwen3:8b` with `reasoning_effort: none` (8.9s; with
  thinking on it blew the 600s timeout without emitting JSON). `gemma4:26b` unusable on
  this machine (`radv/amdgpu: Not enough memory`). `engine_benchmark.py` now dumps
  `results-<engine>.json` (dataset_sha, limit, per-posting metrics); new standalone
  `compare_benchmark.py` renders `comparison.md` and refuses to mix different datasets.
  Same 20 postings, 4 engines: rizzo 4 PASS/7 REVIEW/DROP 9, stdev 25.1, 4.15s; jev 20 DROP,
  0.38s; deepseek 20 DROP, 7.64s; qwen3 13 DROP/7 REVIEW, flat 7.5, 11.67s. jev and deepseek
  agree on 100% of decisions. Sample is the first 20 by external_id (noise) -> latency and
  plumbing only, not calibration. Tests 55/55 green.
- [x] Fetch config v10 (2026-10-19) — `profile.location` now sends board-ready strings
  verbatim (`primary`, optional `remote_query`) and `normalize_fetch_location` is gone: no
  geo/language heuristic left in code. `remote_ok` dropped (remote acceptance is
  `bucket_scores.remote`); `extra_searches`/`ExtraSearch` dropped (Backend Developer is now
  a title); `scraping.page_cap` -> `board_max_results {linkedin: 300, indeed: 500}` with a
  fail-fast key check; pagination also stops when a page adds no new `external_id`.
  `Query.location_raw` removed (one `location` field). Real run (33 min): 1593 usable rows,
  924 unique postings, 0 errors, 0 captcha; only q2 (Embedded @ Sardinia, 3 rows) misses the
  pass bar. `compare_benchmark.py` now also refuses stale results (dataset_sha vs the current
  postings.jsonl). Tests 58/58 green.
- [x] Fetch report without a verdict (2026-10-19) — the spike no longer emits a
  PASS/FAIL/THIN verdict: a one-word gate added nothing for a single-operator tool and
  raised a false alarm (3-row scarce niche reported as a failure). The report now states
  facts only: usable rows per query, queries below the 5-row reporting bar with their
  counts, zero-row queries, captcha rows skipped, totals. `FetchStats.captcha_skipped` is
  measured instead of asserted; `output/stats.json` is persisted and `--report-only`
  re-renders the report from `output/raw/` without refetching. Tests 64/64 green.
- [ ] browser-use — **evaluated, not adopted, not scheduled** (user not interested). Facts
  recorded so the decision is not re-litigated: `browser-use 0.13.11` declares 37 core deps
  with hard pins that would fight ours (`httpx==0.28.1`, `pydantic==2.13.5`,
  `openai==2.26.0`), plus `posthog` telemetry and a Chromium/CDP runtime (`browser-harness`,
  `cdp-use`); it is also LLM-driven per call. Would have to live in a separate venv behind a
  subprocess boundary emitting the same posting JSON, opt-in for THIN queries only.
- [x] Transport retry (2026-10-19) — `AIEngine.retry` (`RetryPolicy`: max_attempts,
  base_delay_s, max_delay_s) and `AIEngine.throttle_s`. `AIClient._post` retries **only**
  429/5xx with exponential backoff + jitter, honouring `Retry-After`; 400/401/403 fail at
  once. `sleep_fn` is injectable so tests never sleep. jev config paced at 0.5s with 5
  attempts / 2s base / 30s cap. Tests 64/64 green. Not yet exercised against the real
  endpoint: the previous 924-posting jev run scored only 263 and then got 429 on every
  request from position 264 onwards.
- [x] Config v11 + generic scoring (2026-10-20) — `Profile`/`Skills`/`JobFilters`/
  `SystemOneResult`/`LocationBucket` removed. Config is now `search` (the only bound part) +
  free-keyed `criteria`, each carrying its own question, plus `penalties`. `weight > 0` xor
  `gate` (`true` / `{accept}` / `{min_score}`), 10 validators fail fast, `extra="forbid"`.
  Rubrics are **projected** from `criteria` (`scoring/projection/`) into the System One JSON
  and the LLM markdown, so the two formats cannot drift and no rubric file has to be
  regenerated when a value changes; the shipped default rubric files were deleted. The wire
  rejects extra fields, so `missing` markers stay in the config. Evaluator: gates first
  (missing never drops), then the weighted sum. Real end-to-end: rizzo 5/5 scored (3.83s
  mean, 1 REVIEW), qwen3 5/5 (14.03s mean). Tests 97/97 green.
  - Calibration finding #1: a model-judged numeric gate (`salary_stated`, "at least 38k")
    answered `no` on a posting with no salary (it read postal code `07026` as a figure) and
    dropped it. Sharpened the question text; after that, no-salary postings correctly answer
    `missing` and are not dropped. Still the weakest link: gates that parse numbers are
    probabilistic, `pay` missing already forces REVIEW, so this gate is a candidate for
    removal during calibration.
- [x] Spike 03 calibration harness (2026-10-20) — `sample.py` (deterministic stratified sample,
  seed 20261020, 6 per query/board -> 61 postings), `labels.yaml` (first pass machine-proposed:
  0 apply / 15 maybe / 46 no, to be approved by the user), `calibrate.py` (per-criterion means
  + AUC, missing rates, gate drops by verdict, precision per threshold). `engine_benchmark.py`
  gained `--input` so the calibration sample can be scored directly. rizzo scored all 61 in
  255s. First findings: `core_skills` missing in 36/61 (level 0 "Not stated" invites "unsure"),
  `salary_stated` dropped 15/61 with no measured benefit and one `maybe` lost, nothing scores
  above 60, and the pool produced no `apply`.
  - Trap recorded: YAML 1.1 reads bare `yes`/`no` as booleans — quote them in config options
    **and** in `labels.yaml` verdicts.
- [x] Location gate fixed (2026-10-20) — the question accepted almost every posting outside the
  home area (Rome/Milan/Turin hybrid → `accepted`), so the gate was effectively off. Cause: the
  "accepted" option bundled proximity with arrangement ("on-site or hybrid in X, or fully remote
  within Italy") and the model matched "within Italy". Rewritten as a proximity judgement with
  the home area injected ("any on-site or hybrid work in a city outside X is NOT acceptable"),
  verified 8/8 on hand-checked postings (was 1/8). Result on the 61 labelled: location drops
  went 5 -> 26 (25 `no`, 1 `maybe` that was Rome + smart working, which the user's own hybrid
  rule says to reject), DROP/REVIEW 39/22 -> 48/13. Lesson: ask about the physical location, and
  never bundle two dimensions in one option.
- [x] Exclusion criterion made honest (2026-10-20) — the `keep` label said "Open to any candidate,
  a normal job", which asserts facts the model cannot know. Three factual rewordings ("contains
  nothing from the list", "no exclusion found", "applicable") all broke it (0/5 protected-category
  postings caught): with a neutral label the model defaults to keep. Fixed by inverting the
  question ("Does this posting contain any of these exclusions? yes/no/missing", gate accept
  ["no"]) -> 7/8, then 10/10 after adding the abbreviations that actually appear in titles
  ("cat. protette", "L.68/99", "art. 1 L.68") to `search.exclude`. Full run unchanged in shape
  (48 DROP / 13 REVIEW) with 5/5 protected postings dropped.
  - Lesson: with rizzo the answer labels must be factual AND the "interesting" case must be the
    affirmative one; a negative label makes the model pick the default.
- [x] M4 web read-mostly (2026-10-21) — `entrypoints/web/` (FastAPI + Jinja2, server-rendered):
  `/jobs` table with dynamic criterion columns, filters (decisions, source, text,
  criterion+op+value, missing, run scope), whitelisted sorting and pagination; `/jobs/{id}`
  detail with answers vs thresholds and the Sì/No buttons; `/runs` queue + history with
  auto-refresh while a request is pending; `POST /run` enqueues a `requested` row; `/healthz`.
  `Store` gained `count_jobs`, `job`, `latest_evaluation`, `answers_for`, `missing_for`,
  `feedback_for`, `criterion_columns`, `runs`, `pending_requests` and the new filter arguments.
  The write surface is enforced by a test: the web may call only an allowlist of Store methods
  (writes: `save_feedback`, `request_run`). Live check: 33 offers listed, detail/feedback/run
  200-303, feedback row and queued run verified in the DB. Tests 172/172 green.
- [x] Pagination bug root cause (2026-10-21) — from the browser: with every decision checked the
  list showed 216 offers, but "successivi" came back with 33. Cause: the hidden empty
  `<input name="decisions" value="">` (added to allow unchecking everything) made the form send
  `decisions=pass&decisions=review&decisions=drop&decisions=`; `QueryParams.get` keeps the last
  value, so the parse produced an empty list (no filter = all), while the pager link then omitted
  the parameter — and an absent parameter fell back to the learning default. The round-trip was
  not symmetric. Fix: no hidden input; **an absent `decisions` parameter means "no filter"**, so
  an empty selection survives pagination (test added). The learning default now comes only from
  the `/` redirect, and the header "Jobs" link points there.
- [x] Filters: repeated keys (2026-10-21) — the form sends one key per checkbox
  (`decisions=pass&decisions=review&decisions=drop`); `QueryParams.get()` returns only the last
  one, so the UI kept a single decision ("only drop checked, the others uncheckable"). Now the
  parser reads `getlist("decisions")` and splits each value on commas, so form style and pager
  style both work (test covers both). Verified live: 3 checkboxes → 216 offers with all three
  checked, both from a form submit and from a pager link. Tests 181/181 green.
- [x] Filter improvements (2026-10-21) — `"cannot tell" only` became **remove "cannot tell"**
  (`exclude_missing`, with or without a criterion); the value field adapts to the selected
  criterion (a `<select>` of its options for `choice`, operator + number for `score`), so
  `location` etc. are filtered without typing; the rigid `last|all` scope is replaced by a
  **Run** select listing recent runs with date, status and how many offers they added, and a
  sortable **Run** column shows the evaluation's run time. Store: `run_started_at` on `JobRow`
  (LEFT JOIN runs), `exclude_missing` in the WHERE builder, `run_started_at` as a sort key.
  Verified live: default 33, all 216, without "cannot tell" 69, location=rejected 136.
  Tests 185/185 green.
- [x] Filter widgets + template naming (2026-10-21) — filters are independent cards on one row
  (Run, Text, Board, Decision, Criterion) with the value field **always visible** (operator +
  text, datalist of the known options); a **Location** text filter on the posting's location
  (LIKE); every criterion column is sortable through `sort=crit:<name>` (LEFT JOIN on
  `evaluation_answers`, `NULLS LAST`); the `First seen` column was dropped and the `Verdict`
  column renamed **Feedback**. Templates renamed to `.html.j2` for editor support, with an
  explicit Jinja `Environment` because extension-based autoescaping would not cover `.j2` —
  a test now feeds a `<script>` title and requires it escaped.
  Verified live: 5 cards on one row, location Milan 59 / Cagliari 29, `crit:pay` asc/desc,
  `exclude_missing` 69. Tests 186/186 green.
- [x] Filter panel closed by default (2026-10-21) — `<details class="filters">` without `open`,
  so the table is what you see first and the chips in the summary still show the active filters.
  Tests 191/191 green.
- [x] Worker hot reload + config-driven filters (2026-10-21) — the worker re-reads the config
  when the file changes: `refresh()` stats `config_path` on every tick and rebuilds the context
  only when the mtime differs (`stat()` per poll, full parse only on change; the `Store` is
  reused). The web reads the criteria from `ctx.config.criteria` instead of
  `store.criterion_columns()`, so a criterion added today is filterable and selectable as a
  column before any run has produced answers for it. The Value field adapts to the selected
  criterion: a `<select>` of its own options for `choice`, a number input for `score`, always
  visible. Tests 195/195 green.
- [x] Compact columns picker (2026-10-21) — the Columns card lays its checkboxes out in a
  4-column grid (2 columns below 1200px), so eleven toggles take three rows instead of eleven.
- [x] Columns picker: three columns (2026-10-21) — the commit `4aa3fe3` message says four columns,
  but the user set the picker to **three** on purpose (eleven toggles in four rows): the CSS in
  that commit already carries `repeat(3, ...)`. Recorded here so the ledger matches the code.
  Note: `style.css` is now expanded/formatted by the editor, which is why the recent commits show
  large CSS diffs.
- [x] Markdown description (2026-10-22) — board descriptions use markdown (`**bold**`, `*`
  bullets, headings), so the detail page now renders them: `markdown-it-py` with `html=False`,
  which **escapes** any raw tag in the posting instead of executing it (the escaping moved from
  Jinja into the renderer, it is not dropped). `<pre>` became a styled
  `<div class="description">`; the blank-line normalisation still runs first. Verified on job
  201: 20 `<strong>`, 3 `<ul>`, zero raw `<script>`; a test feeds a `<script>` description and
  requires it escaped. Paragraph margins are `.2rem` (the user's tweak) so the 17 short
  paragraphs of a typical posting do not look like a column of gaps. Tests 196/196 green.
- [x] Dark mode (2026-10-22) — the stylesheet now has a full variable palette (`--surface`,
  `--thead`, `--chip-bg`, `--link`, `--error`, `--info`, `--shadow`, ...) with no hardcoded
  colours left, so a `@media (prefers-color-scheme: dark)` block redefines the palette and the
  whole UI follows the system setting. `color-scheme: light dark` makes native controls (selects,
  checkboxes, scrollbars) follow too. No toggle and no JavaScript: light stays the default when
  the system asks for light. Checked: 76 balanced rule blocks, every `var()` defined, page 200.
- [x] Detail link keeps the list state (2026-10-22) — the title link pointed at `/jobs/<id>` with no
  query string, so the detail page could not know which list you came from: "back" always landed
  on page 1 with default filters and default columns. `detail_url(filters, job_id)` appends the
  current query string (filters, columns, sort, limit **and** offset), so the header "Jobs" and
  the "‹ Jobs" back link restore the exact page. Note for tests: hrefs in the rendered HTML are
  HTML-escaped (`&amp;`), so they must be `html.unescape`-d before being followed. Verified live:
  list page 2 -> detail -> back returns to the same columns and offset. Tests 201/201 green.
- [x] LAN access (2026-10-22) — `deploy/jobcaliber-web.service` binds `--host 0.0.0.0` (with a
  comment about the missing authentication); README gained "Access from your phone": LAN bind,
  `firewalld` rich rule restricted to the local subnet, verification over the LAN IP,
  mDNS `<hostname>.local`, alias `jobcaliber.local` in `/etc/avahi/hosts`, the Android caveat,
  Tailscale as the authenticated alternative, and the warning that anyone on the network can
  write feedback and press *Run now*. Verified live: bound on `0.0.0.0:8870`, `/healthz` answers
  both on localhost and on `192.168.1.28`. Tests 201/201 green.
- [x] Worker loop + engine preflight (2026-10-23) — every run failed with `ConnectError` because
  rizzo was not running, and only *after* the full fetch (~28 min); on top of that the worker
  started a new scheduled run at every poll. Root cause of the loop: `runs.started_at` is written
  by SQLite in **UTC**, `is_due` compared it with a **local** `datetime.now()` (UTC+2), so every
  run looked older than the slot. Fixes: `is_due` interprets the stored timestamp as UTC;
  `AIClient.probe()` (TCP connect, shared by both transports) runs before `_collect`, raising
  `EngineUnreachable` which is marked non-retryable; `requeue` clears `finished_at`.
  Verified: engine down -> failed in **42 ms** (was 28 min); worker with `--poll 3` for 45 s ->
  **1** run (was ~15); with rizzo up, a clean run scored 26 postings in 145 s. DB reset.
- [x] Explicit timezone (2026-10-23) — the web printed stored UTC raw (`/runs` showed 08:56 while
  the clock said 10:56), and the CLI did the same, so fixing only the web would have created two
  truths. Instead of a bare `astimezone()` (which guessed the machine's zone) the zone is now
  declared: `schedule.timezone` (IANA, **required**), validated in `config_loader` with a clear
  message, resolved once in `AppContext.tz`. The DB keeps UTC; `scrape_times` are wall clock in
  that zone; `is_due` compares UTC instants; `core/formatting.local_time` is the single formatter
  used by the Jinja filter and the CLI. The formatter lives in `core/formatting.py`, not
  `entrypoints/`: a helper placed in the top layer cannot be imported by anything else, and the
  Telegram notifier (next milestone) would have re-implemented it — `AGENTS.md` now records this
  as the one exception allowed in `core/`. Tests cover summer/winter offsets, the two DST
  transitions, a nonexistent 02:30 slot, CLI/web agreement and the missing/invalid zone.
  Live: `/runs` and `jobcaliber status` both show 11:01 for the 09:01 UTC run; the worker, after
  the restart, created no run in 40 s with `--poll 5`. Tests 219.
- [x] Config split profile/settings + criteria cleanup (2026-10-23) — `profile.yaml` (search,
  `evaluation.systemone_min_confidence`, criteria) keys the evaluations; `settings.yaml`
  (scraping, schedule, notifications, ai, db_path) never re-scores; a key in both files is an
  error. Removed `in_table` (every criterion is a column; the picker still narrows), removed
  `penalties` (**dead code**: a penalty applies only when an answer is missing, and a missing
  answer returns REVIEW before confidence is read), removed `notify_threshold`,
  `review_threshold`, `quiet_hours`, `digest_time` (never read), removed `hours_old` (unused).
  `job_type` moved to `search` (it is a query filter); `scraping.country` -> `board_country`
  (which Indeed site, not a location). Telegram config is now `{enabled, chat_id}`. The version
  key also includes `RUBRIC_VERSION`, so changing the rubric projection in code invalidates
  stored answers. Tests 225. Next run creates `config_v 3` and re-scores the 1002 stored postings
  (~110 min) — the one-off price of the new key.
- [x] Telegram notifications (2026-10-23) — `infrastructure/notify/telegram.py` (httpx, no
  framework): at the end of a successful run, one HTML message with every new `pass` posting
  (title, company, score, ad link) plus a link to `/jobs?decisions=pass&run=<id>`; 10 offers then
  "…and N more"; titles escaped; hard cap at Telegram's 4096 chars; `notified_at` makes it
  idempotent; a delivery failure is logged and the run stays `ok` (the offer is retried next run);
  `enabled` without `chat_id`, or without the token in `.env`, fails at startup. Config:
  `notifications.base_url` + `notifications.telegram {enabled, chat_id, token_env, max_offers}`.
  Real delivery verified against `@jobcaliber_bot` (chat 657083271): 5 pass postings sent.
  Tests 235.
- [x] Config files moved under `config/` (2026-10-23) — `config/profile.yaml`,
  `config/settings.yaml` and their examples; `.env`, `data/` and `prompts/` stay where they are.
  Only `config_loader` changed (`CONFIG_DIR`, anchored `.gitignore` patterns), plus a test that a
  stray copy at the repository root is **not** picked up. Moving the files does not re-score:
  the version key is the profile *content*, not its path. Tests 236.
- [ ] Backlog decided on 2026-10-23 (ordering by value, not by effort):
  1. **DONE 2026-10-23 — application ledger**: feedback changes purpose from "model verdict" to "I applied / will
     apply / not interested". Keyed on `jobs.id`, not on `evaluations.id` (today a re-score orphans
     the mark, because `feedback.evaluation_id` points at the old evaluation). Migration v4
     (`applications(job_id PK, state, note, created_at, updated_at)`), three buttons on the detail
     page, a `status` column + filter in the list, a `/applications` page, and a CSV/JSON export of
     what was applied. Telegram skips postings already marked.
  2. **DEFERRED — nightly backup**: `schedule.backup_time` is dead config. The worker should run
     `db backup` once a day and keep N copies; the DB now holds 1022 postings and will hold the
     application ledger, which is not reconstructible.
  3. **DEFERRED — model calibration**: needs real verdicts (0 today). Then: decisions computed at
     read time (so thresholds are free to tune), `jobcaliber calibrate` reading the DB (recall@k,
     error attribution via `dropped_by`, confidence vs accuracy), per-criterion feedback. Rubric
     work goes on a frozen labelled subset (40 tune + 21 holdout), one change per iteration.
  4. **DEFERRED — live run counters** in `/runs` (declined for now: `finish_run` writes them at the
     end, so a running run shows 0).
  5. **DEFERRED — config editor** (`ConfigService`, profile in the DB with the YAML as import/export)
     together with a profile diff view between `config_v` versions. Last real feature, paired with 1.
  6. **AT THE SERVER — three systemd units**: `web`, `worker` and **`rizzo`** (today rizzo is started
     by hand; after a reboot the worker fails the preflight in 40 ms). `loginctl enable-linger`.
  7. **AT THE SERVER — engine choice on the i5-8th-gen/16 GB**: rizzo 4B at ~6.6 s/posting here means
     an estimated 20-40 s there (6-11 h per run); OneJev 0.8B is the candidate that would fit.
  8. **NOT NEEDED — `jobcaliber doctor`** (rejected: `status`, `db check` and the preflight cover it).
  9. **Candidates noticed while reviewing the model space**: duplicate ads across boards (same job on
     LinkedIn and Indeed = two rows to review, `external_id` is the URL), and ads that vanished from
     the boards (`last_seen_at` grows, nothing marks them closed).
- [x] Application ledger (2026-10-23) — schema v4: `applications(job_id PK, state, source, note,
  created_at, updated_at)` replaces `feedback`, which was keyed on `evaluations.id` and would have
  been orphaned by the next re-score. The five existing verdicts were migrated (`good -> planned`,
  `bad -> skipped`, provenance kept in `source`, original timestamps preserved) — a first attempt on
  a plain file copy found zero rows because the rows were still in the **WAL**; the real migration
  ran with the services stopped and an explicit backup. Web: three buttons (applied / will apply /
  not interested + undo) on the detail page, a `status` column with a `state=` filter, a
  `/applications` page and a CSV export. Telegram never re-sends a posting that carries a mark.
  Tests 240.
- [x] **Multi-row filters, one per column** (2026-10-23). Today the filter panel
  has a single "criterion + operator + value" triple, so only one criterion can be filtered at a
  time. Goal: **one row per criterion**, all of them combined with AND, so several can be filtered
  at once — and extend the same mechanism to every column (score, confidence, board, ad location,
  decision, **status**, and the optional salary/last-seen/run columns), each with the input type its
  type deserves: numeric comparison (`<`, `≤`, `=`, `≥`, `>`), free text (`LIKE`), or a list
  (select) for enumerations such as `status` and the `choice` criteria.
  Technical notes for the implementation:
  - the query string must carry repeated keys (`criterion=pay&op=ge&value=0.5&criterion=tools&...`),
    so `parse_filters` returns a **list** of filters, `jobs_url` serialises it, and the detail link
    keeps carrying the whole list (it already round-trips the query string);
  - `Store.jobs`/`count_jobs`/`_where` must accept a list of criterion filters and add one
    `EXISTS (SELECT 1 FROM evaluation_answers ...)` per filter (AND semantics), keeping the current
    special cases: `choice` criteria compare `option`, `score` criteria compare `value` with the
    chosen operator, `exclude_missing` still excludes rows where that criterion is missing;
  - the panel goes from one "Criterion" card to a table of rows, each with its own small form row
    (`+ add` / `× remove`), so the operator and input type follow the column's type;
  - `status` already has a `state=` filter: it becomes one of the typed columns instead of a
    separate card, and salary/last-seen/run become filterable too (last-seen/run as a date bound);
  - tests: two criteria at once (AND), a choice criterion by option, an unknown criterion ignored,
    the URL round-trip with two filters, and the empty-state message listing every active filter.
  Implemented as a generic `Filter(column, op, value, text, values)` in the store with
  `_condition()` mapping each column to SQL (`crit:<name>` goes through `evaluation_answers`, so
  several criteria combine with AND; `status` goes through `applications`), the panel as a table of
  `col/op/val/sel` rows (the always-present empty row is how a filter is added, no JS), operators and
  value controls driven by the column type, and `decisions`/`text`/`exclude_missing` kept as the
  always-visible controls. Tests 245.
- [x] Documentation pass for the server install (2026-10-24) — `docs/INSTALL.md` (step-by-step
  install with a check after each step, three systemd units, firewall, Telegram, final checklist,
  upgrade/uninstall), `docs/OPERATIONS.md` (daily commands, DB queries, backup/restore, changing the
  rules, engine benchmarks, retention, troubleshooting matrix), `docs/ARCHITECTURE.md` (layers,
  decisions order, data model, invariants, extension points, the web split),
  `config/README.md` (every key, and what fails fast), `deploy/README.md` + the missing
  `jobcaliber-rizzo.service`, a rewritten `README.md`, and an accurate `AGENTS.md` (the old one
  still described `weights`, `penalties`, `query_expander` and `src/jobcaliber/models.py`). Added
  `LICENSE` (MIT) and a fuller `.env.example`.
- [x] Sandbox benchmark: OneJev 1.6 0.8B vs the 61 labelled postings (2026-10-24). Setup: the
  docker profile builds torch+CUDA (their images are unpublished and the `gguf` target shares the
  base stage) → abandoned; instead `uv pip install /tmp/OneJev` in a venv plus the official
  `llama-b11856-bin-ubuntu-vulkan-x64` `llama-server`, then `qev serve --gguf
  mradermacher/OneJev1.6-0.8B-GGUF:Q8_0 --port 8018`; engine added as `ai.engines.onejev`.
  **Result**: 1.31 s/offer (rizzo: 5.2 s) — fast — but the aggregate AUC 0.774 is a trap: it is
  carried by the `location` gate (34 of the 52 `no` postings were dropped there). Per criterion
  (maybe-vs-no AUC · missing rate): core_skills 0.65 · 45/61 missing, tools 0.51 · 40/61,
  role_fit **0.35 inverted**, pay **0.44 inverted**. Rizzo on the same labels: core_skills 0.72 with
  0 missing, pay 0.63, tools 0.51. Verdict: **0.8B is not usable as the scorer** — 18 of 61 postings
  land in `review` merely because the model cannot tell, and the criteria that matter are at or
  below chance. Side finding: the wire returns `score` as a float expected level and
  `SystemOneScorer._parse` truncated it with `int()`; now `float()` (rounding only to detect
  `missing`).
- [ ] Cleanup candidate noticed during the docs pass: `ai.prompts_dir` / `ai.custom_prompts` and
  `PromptStore` look **dead** since the rubric became a projection — `prompts/` is empty and the
  scorers accept `prompts` without using it. Verify and remove (config key, loader wiring, the
  `prompts` argument of `Scorer.create`).
- [x] **`model_host`: power and service control for the machine that runs the engine** (2026-10-25).
  Validated end-to-end by hand on 2026-10-25 (see `spikes/04_model_host/README.md`): direct cable
  `10.10.0.1 ↔ 10.10.0.2`, engine reachable from the controller (200 in 21 ms), **wake from S5 in
  29 s** after enabling `Resume By PCI-E Device` + disabling ErP in the MSI B650M BIOS, ordered
  shutdown, watchdog in `ExecStartPost` (`+-` prefixes: root, non-fatal).
  Decision taken: the controller owns the *policy*, the host contains **no jobcaliber code** — only
  three elementary capabilities, each a forced `command=` in the controller key:
  `sudo systemctl start rizzo`, `sudo systemctl stop rizzo`, `sudo systemctl poweroff`
  (plus three `NOPASSWD` lines in `/etc/sudoers.d/rizzo-control`).
  Rule: **leave the host as you found it.**
  | found | do | at the end |
  |---|---|---|
  | host off | magic packet → wait for SSH up to `wait_s` → `start` | `poweroff` |
  | host on, engine off | `start` | `stop`, host stays on |
  | host on, engine on | nothing | nothing |
  Configuration per engine (`ai.engines.rizzo.model_host`): `wake_on_lan {mac, broadcast, wait_s}`,
  `start_command`, `stop_command`, `poweroff_command`. Code: `ModelHost` (Pydantic, in
  `core/config/ai.py`), `magic_packet()` + `ModelHostController` with `ensure_ready()` /
  `release()` (in `infrastructure/model_host.py`, takes a `probe` callable so it stays free of the
  scorer), wired in the runner **before** the fetch (a failed wake must not waste the fetch).
  Tests: payload, wake only when the host is down, start/stop/poweroff only when we caused them,
  timeout without fetch, a failing command never marking a good run as failed.
  Residual risk, accepted: if the user logs in during a 06:00 run (~2 h), the final poweroff hits
  the running session. Mitigations if it ever bites: start the run earlier, or add a fourth
  read-only command (`loginctl list-sessions --no-legend`) and skip the poweroff when a session
  is active.
  Implementation note: the first version probed only the **engine**, which cannot tell "host on,
  engine off" from "host off" — it would have powered off a machine someone was using. The fix is
  `model_host.address` (required whenever the controller may wake or power off) plus a TCP probe of
  the machine's ssh port, so the three rows of the table are distinguishable. Tests: 259.
- [ ] **Controller hardening (BIOS only).** On the mini-PC set *Restore AC Power Loss = Power On*
  so it comes back after a blackout. **Not** masking `sleep.target`/`suspend.target` (rejected as
  excessive): verified on 2026-10-25 that nothing suspends it today — no idle daemon, `logind`
  `IdleAction=ignore` by default, zero suspend events in the journal.
- [x] Split deployment, end to end (2026-10-25) — mini-PC (i5-8500, 4 cores) as the always-on
  **controller** (web, worker, database, fetch) and the Ryzen 5 8600G as the **model host** that
  only runs `rizzo`. Direct cable `10.10.0.1/24 ↔ 10.10.0.2/24` with **no gateway** on that link
  (internet stays on Wi-Fi on both), `firewalld` rules per source subnet, `rizzo.service` as a
  system unit started on demand. Wake-on-LAN needed two firmware options that are easy to miss:
  *Resume By PCI-E Device = Enabled* and **ErP = Disabled** — without them the NIC keeps the link
  but the machine never wakes. Measured: **wake from S5 in 29 s**, engine answering **4–12 s**
  after the host is up, engine latency over the cable **21 ms**, whole cold cycle (wake → fetch →
  score → poweroff) **72 s**.
  Traps paid for once:
  - a failing `ExecStartPost` **kills the main process** of a unit, and `systemd-run` inside a
    system service is denied without a polkit session (`requires interactive authentication`) — a
    watchdog needs `+-` prefixes (root, non-fatal) or it turns into an outage;
  - `systemctl stop` leaves a unit `failed` unless `SuccessExitStatus=143` is set;
  - one SSH key cannot offer several forced commands (`authorized_keys` applies `command=` per
    line and sshd uses the first match) → **one key per capability**;
  - `pkill -f <pattern>` matches the shell that runs it: it killed my own SSH session twice
    (exit 255 looked like a network fault). Use `pgrep -f 'x[y]z'` or kill by PID.
  Decision taken: the host contains **no jobcaliber code**, only `systemctl start|stop rizzo` and
  `poweroff`, each behind a forced-command key and a sudoers line; the controller owns the policy
  and leaves the host as it found it.
- [x] Cutover to the controller (2026-10-25) — `db backup` (WAL-safe) copied to the mini: 1101 jobs
  and 5 applications, `db check` green. The workshop keeps `data/dev.db` (throwaway) and
  `data/jobs.pre-cutover.db` (fixture), config and `.env` are per machine and never travel, and the
  workflow is written in `AGENTS.md` §5 ("workshop here, production there"): code through git, the
  suite green on both machines (Python 3.14.8 here, 3.14.4 there).
- [x] First unattended run + the two fixes it surfaced (2026-10-25). Run 13 (`schedule`, 33 min):
  1609 rows fetched, 38 new, 38 scored (31 drop, 7 review, 0 pass), engine stopped at the end, PC
  left on (it was already up). Two things came out of it:
  1. **the digest now carries `review` too** (only `drop` is excluded), each line labelled with its
     decision and the header counting pass/review: with a niche market the new offers are few, and a
     review is exactly the "worth a look" case;
  2. **the model host must not suspend while the engine runs**: this PC runs `hypridle` with
     `timeout = 300 → systemctl suspend`, so an unattended run would be frozen after 5 minutes. The
     engine unit now runs inside `systemd-inhibit --what=idle:sleep --who=rizzo-flow`, which holds
     the lock only while the engine is alive (`hypridle` has `ignore_systemd_inhibit = false`).
     Tests 261.
- [x] Keeping the model host awake during a run (2026-10-25) — `hypridle` on the model host suspends
  after 300 s idle, so an unattended run would be frozen mid-flight (and a timeout is retryable, so
  the worker would repeat the 30-minute fetch up to three times). `systemd-inhibit` inside the system
  unit was tried and is **not usable**: no logind session → polkit refuses the lock ("Access denied …
  requires interactive authentication") and the engine never starts. The working solution is the
  desktop's own decision point: `on-timeout = systemctl is-active --quiet rizzo || systemctl suspend`
  in `hypridle.conf` (hypridle runs listener commands through `/bin/sh -c`). A `pgrep -f "rizzo serve"`
  guard does **not** work: the shell running that line contains the pattern, so pgrep always
  matches — the same self-match trap that once killed an SSH session with `pkill`. The polkit rule is
  documented as the system-level alternative. The manual "idle inhibitor" button in waybar is the
  same idea but needs a Wayland client in the session, so it cannot be driven from the controller.
- [x] Watchdog lifespan (2026-10-25): the host unit armed the 3 hour `poweroff` watchdog on start
  but never disarmed it on stop, so a normal run (engine stopped after ~30 minutes) left a timer
  that powered the machine off at +3 h, possibly under the user. Added
  `ExecStopPost=-+/usr/bin/systemctl stop rizzo-idle-watchdog.timer`: the safety net now lives
  exactly as long as the engine.
- [x] Missing Telegram digests (2026-10-29): runs were ok and produced `review` offers, but no
  message arrived. The bot, token and chat were fine (`getMe`/`sendMessage` green). Cause: the
  worker process had been running since 2026-10-25 17:45, while the digest fix (pass **and** review)
  landed at 18:34 — 49 minutes later — and the unit was never restarted, so `_notify` still filtered
  `decision == "pass"` and returned silently (every run since produced 0 pass). Two lessons:
  **a deploy must restart the unit** (Python keeps the code it loaded) and **stdout must be
  unbuffered** (`Environment=PYTHONUNBUFFERED=1`) or the progress lines — including
  `telegram: not sent (<error>)` — never reach the journal. Both are now in `deploy/`, the upgrade
  section and the troubleshooting table.
- [x] Digest link across a backlog (2026-10-29): the message always linked `?decisions=pass,review&run=<id>`
  of the run that produced it, but a backlog digest lists offers from earlier runs, so the filter hid
  most of what the message showed. `JobRow` now carries `run_id` and the link includes `run=` only
  when every listed offer belongs to the same run. Also `SuccessExitStatus=143` on the worker and web
  units, so a clean `systemctl stop`/`restart` no longer reports the unit as failed.
- [x] Intermittent unreachable web on the controller (2026-10-29): the web itself never stopped
  (`NRestarts=0`, uptime 3d17h) — the **Wi-Fi** did. `iwlwifi` on `wlan0` associated with the
  2.4 GHz BSSID (`…:b4:23`, ch1, signal ~48) and roamed to the 5 GHz one (`…:b4:24`, signal 12)
  and back: **77 associations in 5 days**, hourly at :24–:27, plus flapping bursts of 3–4 minutes
  (02:12–02:15, 07:10–07:14), with `missed_beacons exceeds threshold` from the driver. Each roam is
  a few seconds off the LAN. Fix: `802-11-wireless.powersave 2` (disable) and a pinned
  `802-11-wireless.bssid` to the 2.4 GHz radio, applied 2026-10-29 11:4x. Baseline at the change:
  **38** `disconnect from AP` in the journal, 0 in the 30 minutes after. Verify after 24 h with
  `journalctl -k --since "24 hours ago" | grep -c "disconnect from AP"` (expect 0–2). If it is still
  high the steering is on the router side: separate SSIDs per band, or wire the machine. Note the
  cable path `http://10.10.0.1:8000` is immune to this and answered 200 in 27 ms.
