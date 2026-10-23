# AGENTS.md — jobcaliber project rules & architecture guidelines

Binding for every contributor (human or agent).

## 0. Two-phase workflow & versioning approval

**Non-negotiable: nothing is implemented before the user agrees.** Every change — a feature, a
refactor, a one-line fix, a config tweak, a dependency — is proposed in chat first (scope, files,
approach, acceptance criteria, how it will be tested) and implemented **only** after an explicit
"ok". Writing code, editing files or running mutating commands before that agreement is a rule
violation, even when the change looks trivial or obviously right. If something new comes up while
implementing, stop and return to the proposal instead of deciding alone.

Every development step runs in two mandatory phases, in this order:

1. **Planning (with the user).** Before writing or changing code, the agent
   proposes a plan: scope, files, approach, acceptance criteria, and how it will
   be tested. The plan is written in chat and agreed with the user. No code is
   written before explicit approval.
2. **Development (only after approval).** The agent implements exactly the
   approved plan, runs the tests, and reports real results. If the plan turns out
   to be wrong, the agent stops and returns to phase 1; it does not silently
   expand scope.

A development step ends in the **versioning phase**: commit and push happen
**only if the user approves**. This is enforced by the `git-guard` extension in
`.pi/extensions/`:

- every git write (commit, push, add, switch, tag, stash, pull, ...) shows a
  **Conferma / Rifiuta** menu to the user;
- on **Rifiuta** the extension asks the user for a **reason** and hands it back
  to the agent, which must address it and must not retry the identical command;
- destructive git operations (reset, clean, rebase, restore, `push --force`, ...)
  are always blocked;
- commit messages must follow conventional commits: `<type>(<scope>): <subject>`.

Because the extension is a project extension, the project must be trusted by Pi
for it to load. After editing the extension, run `/reload`.

## 1. Language: English-only
Everything in this project is written in English: code, identifiers, comments,
docstrings, docs, commit messages, reports, config keys. Chat with the user may be
in Italian; repo content never is.

## 2. Comments: minimal, integration-only
- No comment per line or per function. No boilerplate docstrings repeating signatures.
- Comments are allowed only when explaining non-obvious integration details, external API quirks,
  or spec invariants.
- Self-explanatory names over comments.

## 3. Tested before done
Nothing is marked complete without proof of testing:
- Run `uv sync --frozen` and `uv run pytest`.
- All logic has unit tests under `tests/`.
- Spikes must run end-to-end and report real numbers.
- Never fake test results.

## 4. Architecture Guidelines & Core Invariants

### A. Strongly Typed Domain Models
- Never pass raw, unstructured dictionaries across module boundaries.
- Domain entities (`JobPosting`, `ScoringResult`, `EvaluationResult`, `FetchStats`, `Query`)
  live in `src/jobcaliber/models.py` as typed dataclasses.
- Configuration is typed too: `AppConfig` (`search`, `criteria`, `penalties`, `notifications`,
  `scraping`, `schedule`, `ai`) plus `Criterion`/`Question`/`GateAccept`/`GateMinScore` live in
  `src/jobcaliber/config.py` as Pydantic v2 models, loaded by `load_config()`. No module
  takes a config `dict`.
- `criteria` is free-keyed but strictly shaped: `weight > 0` (weighted) xor `gate`, and every
  criterion carries its own question. Adding a criterion is data, never code; adding a *kind*
  of gate is code. No criterion name is hardcoded in the pipeline.

### B. Pure Pipeline Architecture
The source tree is layered (`core/` -> `pipeline/` -> `infrastructure/` -> `application/` ->
`entrypoints/`, wired by `bootstrap.py`), and inside `pipeline/` there is one folder per step
(`fetch/`, `scoring/`, `evaluation/`), with `core/` free of I/O — reading `profile.yaml`/`settings.yaml`
and `.env` lives in `infrastructure/config_loader.py` and `infrastructure/env.py`.
Shared **pure** helpers that every layer needs are the one exception allowed in `core/`
(e.g. `core/formatting.py`: UTC->local timestamps for the web, the CLI and the notifier),
because a helper placed in `entrypoints/` cannot be imported by anything else:
1. **Ingestion (`pipeline/fetch/`)**: query boards and return raw, normalized `JobPosting` objects.
   - No gates, no hard drops, no scoring inside fetch.
   - Paginates cleanly, respects rate limits, never stores captchas, normalizes `NaN -> None`.
2. **Scoring (`pipeline/scoring/`)**: query the System One model via the typed HTTP client
   (`infrastructure/ai/`, `/v1/systemone`) with questions projected from `criteria`.
   - `Scorer` is a common abstract base class (`pipeline/scoring/scorer/base.py`) holding the registry,
     `Scorer.create()`, and the shared normalization helpers. Implementations live in
     separate files (`system_one.py`, `llm.py`) and self-register by engine kind via
     `@Scorer.register(kind)`. Callers never branch on kind; new scorers (e.g. a
     deterministic one) are a new file + registration, no caller changes.
   - Evaluates one question per configured criterion; the rubric is projected from
     `criteria` into the engine's format (`pipeline/scoring/projection/`), so the System One JSON and
     the LLM markdown can never drift apart. No rubric files on disk for scoring.
   - Agnostic to language and profession: zero hardcoded regex/keywords for cities, salaries, or roles.
3. **Evaluation (`pipeline/evaluation/`)**: applies config rules onto `ScoringResult`.
   - Gates first (an explicit negative answer drops; a *missing* answer never drops), then the
     weighted 0-100 over `weight > 0` criteria, then review routing.
   - Calculates combined confidence with the per-criterion `penalties` for missing answers.
4. **Storage & Delivery**: SQLite persistence + Telegram notifications (idempotent, never re-notify).

### C. System One Model Integration (rizzo-flow / Jev / laya)
- Use standard `httpx` for wire protocol. Zero heavy agentic frameworks (`langchain`, `llamaindex`, `crewai`).
- Wire format is strictly `/v1/systemone` using atomic `Choice`, `Score`, and `Noul` primitives.
- `AIClient` (`infrastructure/ai/client/base.py`) is an ABC with a real contract: each transport implements
  `build_request()` (path + payload) and `extract()` (response -> domain value), while the
  base owns `_post()` (POST + auth headers + `raise_for_status`), the registry and `create()`.
  Public methods stay per-transport: `SystemOneClient.system_one()`, `LLMClient.complete()`.
  Do not give every transport a `complete()`: System One does not generate text.
- The registry is keyed by the **wire api** (`systemone`, `openai`), not by product.
  rizzo, Jev and laya are all `decision`/`systemone`; Ollama (via `/v1`), OpenRouter and
  OpenAI are all `llm`/`openai`. Products differ only by config (`base_url`, `model`, key).
- Engines are declared in `ai.engines` with `kind` (`decision` | `llm`) and `api`
  (`systemone` | `openai`); `ai.roles` maps pipeline roles (`scorer`,
  `query_expander`) to an engine name. A role accepts the kinds it can
  implement (`scorer`: decision or llm; `query_expander`: llm).
  `AIClients` (`application/clients.py`) builds the transports once at startup and exposes
  the role services (`scorer(criteria)`, `explainer()`, `query_expander()`); services
  receive a resolved client, not a config.
- Provider quirks that only affect the transport (a required routing header, a versioned
  base path) live in `ai.engines.<name>.headers` / `base_url`, never in client code.
- Default local engine: **rizzo-flow** (Spark-4B + LoRA, llama.cpp, Apache-2.0) served on
  `http://127.0.0.1:8017`; the same wire format works for Cloud **Jev** unchanged.
- Questions and LLM prompts live in `prompts/<kind>/<name>.<ext>`; `ai.custom_prompts`
  overrides any default. No prompt text is hardcoded in Python.

### D. Configuration Discipline
- Personal configuration lives in two gitignored files: `profile.yaml` (search inputs, evaluation
  rules, criteria — **any change re-scores**) and `settings.yaml` (scraping, schedule,
  notifications, ai, paths — **never re-scores**). Templates: `profile.example.yaml`,
  `settings.example.yaml`. The split *is* the versioning rule: evaluations are keyed by the
  profile content (+ `RUBRIC_VERSION` from the code), never by the settings.
- No hardcoded parameters, thresholds, or heuristics in source code.
- Secret values never enter `profile.yaml`/`settings.yaml`: engines declare `api_key_env` and
  `load_config()` loads the gitignored `<repo>/.env` (`chmod 600`) into the process
  environment first. A real environment variable always wins over the file
  (`os.environ.setdefault`), so systemd `EnvironmentFile` and CI secrets still work.
- Fail fast: config values whose keys mirror a domain enum (e.g. `location.bucket_scores`
  vs `LocationBucket`) and prompt criteria are validated at load/startup, never silently
  degraded (`validate_systemone_questions`, `AIClients.from_config`).

### E. Extension points (interface + registry)
Only for **families of interchangeable implementations selected at runtime from config**:
all four must hold — (1) two or more implementations share a contract, (2) the choice
comes from config/data, (3) callers must not branch on the concrete type, (4) the
implementation is replaceable.

Reference implementations: `Scorer` (`pipeline/scoring/scorer/base.py`) and
`AIClient` (`infrastructure/ai/client/base.py`).
The policy for each family:
- an **ABC** (not a bare Protocol) is the common interface; it owns the shared
  `_registry`, `register(key)` and `create(...)`, plus any shared helpers (`static`) and
  shared plumbing (e.g. `AIClient._post`). An ABC with no abstract member is not allowed:
  if there is nothing to implement, the family does not need an interface.
- each implementation lives in its **own file** under a dedicated folder of the family
  (`ai/client/`, `pipeline/scoring/scorer/`) that also holds the family's `base.py` (the ABC);
  implementations subclass the ABC and self-register with `@Base.register("key")`, and
  the folder's `__init__` imports them so registration runs.
- callers only ever call `Base.create(...)` and the interface methods; they never see
  the concrete class or the dispatch. A new implementation is a new file + registration.
- fail fast on an unknown key with a clear error listing known keys.

Do **not** use this for single-implementation services (`Evaluator`, `Fetcher`) or for
data models (`JobPosting`, config classes). Extract a generic registry helper only when
a second family actually needs it (YAGNI).

Checklist for a new implementation (e.g. a deterministic scorer):
1. new file in the family package, subclass the ABC, `@ABC.register("<key>")`;
2. import it in the package `__init__` so registration runs;
3. if the key is an engine/config kind, add it to the config validation (`KIND_APIS`);
4. tests: `isinstance(x, ABC)`, `ABC.create` dispatch, unknown-key error, and the
   implementation's own behaviour.

## Lessons learned
- 2026-10-14: `python-jobspy==1.1.82` requires `pandas<3` (`>=2.1,<3`).
- 2026-10-14: JobSpy's country parameter is `country_indeed`, not `country`.
- 2026-10-14: `NaN` values from JobSpy must be normalized to `None`.
- 2026-10-14: Multi-page pagination on LinkedIn works with `offset` stepping by page size.
- 2026-10-14: CLM (Contrastive Language Models) is too slow on CPU unquantized (~25s/posting for full text vs ~2s for quantised Ollama). Removed CLM local dependencies and cleaned disk cache.
- 2026-10-15: local System One engines compared on 20 real postings. `laya`
  (322M multilingual) is fast and Jev-compatible but flat: all 20 postings scored
  69-76 REVIEW, no separation (a civil engineer scored 0.81 on "requires
  C++/Python"). Rejected. `rizzo-flow` (Spark-4B + LoRA, Jev wire protocol,
  llama.cpp) discriminates best (5 PASS vs 0/0 for ollama/laya) and runs on the
  AMD Radeon 760M via Vulkan (~4.6x faster than its own CPU path). Chosen as the
  local System One engine.
- 2026-10-15: `gpt-oss:20b` is a MoE (~3.6B active params), not a dense 20B, so
  "20B vs 4B" is not a valid speed intuition. Generative engines also vary with
  output/reasoning length; decision engines (rizzo) are single-pass and stable.
- 2026-10-15: real Jev is reachable free through the **opencode Zen gateway**:
  `POST https://opencode.ai/inference/v1/systemone`, `Authorization: Bearer <opencode key>`,
  model `jev-1.13-free`. It is NOT in the `opencode-go` provider model list (that is
  pi's; Jev lives in `/inference/v1`, go models in `/inference/go/v1`). Fastest and
  most consistent engine (0.39s) but stricter calibration (0 PASS vs rizzo 5 PASS).
  `scorer.py` reads the key from `api_key_env` (`OPENCODE_API_KEY`).
- 2026-10-15: decision — keep both engines: **rizzo** local/Vulkan as default and
  **jev** (opencode, free) as reference; compare during W2 calibration.
