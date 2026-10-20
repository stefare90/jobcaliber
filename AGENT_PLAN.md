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
