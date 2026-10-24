# `config/` — the two files that define the system

| File | Answers | A change… |
|---|---|---|
| `profile.yaml` | *what am I looking for, and how do I judge it* | **re-scores every posting** (new version, old evaluations kept) |
| `settings.yaml` | *how does the system run* | is free: the worker reloads it on the next tick |

Both are gitignored. Start from the examples:

```bash
cp config/profile.example.yaml config/profile.yaml
cp config/settings.example.yaml config/settings.yaml
```

A key may live in only one of the two files: declaring it in both is an error, because a silent
precedence between "what to score" and "how to run" is exactly the kind of bug that is invisible
until it costs a re-score.

---

## `profile.yaml`

### `search`

| Key | Meaning |
|---|---|
| `titles` | the job titles to search for. One query per title per location |
| `on_site_locations` | board-ready location strings for on-site/hybrid offers (`"Sardinia, Italy"`) |
| `remote_locations` | board-ready strings for remote searches (`"Italy"`) |
| `exclude` | phrases that mean "not for me"; shown to the criterion that uses `{{search.exclude}}` |
| `job_type` | `fulltime`, `parttime`, … or `null` |

Location strings are sent to the boards **verbatim**: write them the way the board spells them, not
the way you spell them.

### `evaluation`

| Key | Meaning |
|---|---|
| `systemone_min_confidence` | 0–1. The confidence the engine reports per answer; below it a posting is never `pass` (it stays `review`) |

### `criteria`

Free keys, each one criterion:

```yaml
criteria:
  core_skills:
    min_threshold: 0.5          # below → drop
    apply_threshold: 0.67       # below → review, above → pass
    question:
      type: "score"
      instructions: "…"
      levels: ["no overlap", "…", "…", "core of the role"]
      missing: 0                # which level means "cannot tell" (or null)
  location:
    gate: {accept: ["accepted"]}   # or gate: true, or gate: {min_score: 0.8}
    question:
      type: "choice"
      instructions: "…"
      options: {accepted: "…", rejected: "…", unknown: "…"}
      missing: "unknown"
```

Rules the loader enforces (fail fast, with the criterion name in the message):

- every criterion has **either** thresholds **or** a gate, never both and never neither;
- a `score` question has at least two `levels`; a `choice` question has non-empty `options`;
- `missing` is a valid level index, a valid option key, or `null`;
- `0 ≤ min_threshold ≤ apply_threshold ≤ 1`;
- a boolean gate uses exactly the options `yes`, `no`, `missing`;
- `gate.accept` ⊆ the question's options, and `missing` is not accepted;
- `{{search.*}}` placeholders resolve (an unknown one fails at startup).

Text may interpolate `{{search.titles}}`, `{{search.on_site_locations}}`,
`{{search.remote_locations}}`, `{{search.exclude}}`.

**Adding a criterion is data, not code.** The rubric for both engine families is generated from
these entries; there is no prompt file to keep in sync. A new criterion also becomes a column and a
filter field in the web table on the next start.

---

## `settings.yaml`

### `scraping`

| Key | Meaning |
|---|---|
| `boards` | `["linkedin", "indeed"]` |
| `page_size` | results per board page (the pagination step) |
| `board_max_results` | hard cap per board: `{linkedin: 300, indeed: 500}`; unknown boards fail at startup |
| `board_country` | which Indeed site to query (`italy` → `it.indeed.com`); LinkedIn ignores it |

### `schedule`

| Key | Meaning |
|---|---|
| `timezone` | **required**, IANA (`Europe/Rome`, `UTC`, …). Interpret `scrape_times` and render dates |
| `scrape_times` | `["08:00", "13:00", "19:00"]`, wall clock in `timezone` |
| `max_attempts` | retries for a retryable failure (an unreachable engine is not retryable) |
| `backup_time` | reserved; no code reads it yet (backups are manual, see `docs/OPERATIONS.md`) |

### `notifications`

| Key | Meaning |
|---|---|
| `base_url` | where the links inside a message point (the web app as your phone sees it) |
| `telegram.enabled` | turns the digest on. `true` without `chat_id` fails at startup |
| `telegram.chat_id` | your chat with the bot (see `docs/INSTALL.md`, step 5) |
| `telegram.token_env` | the environment variable holding the bot token (`TELEGRAM_BOT_TOKEN`) |
| `telegram.max_offers` | how many offers the message lists before "…and N more" |

### `ai`

```yaml
ai:
  prompts_dir: "prompts"
  engines:
    rizzo: {kind: "decision", api: "systemone", base_url: "http://127.0.0.1:8017", model: "rizzo-latest"}
    jev:
      kind: "decision", api: "systemone", base_url: "https://opencode.ai/inference", model: "jev-1.13-free"
      api_key_env: "OPENCODE_API_KEY", throttle_s: 0.5,
      retry: {max_attempts: 5, base_delay_s: 2.0, max_delay_s: 30.0}
    local_llm:
      kind: "llm", api: "openai", base_url: "http://localhost:11434/v1", model: "qwen3:8b",
      options: {reasoning_effort: "none"}
  roles: {scorer: "rizzo"}
```

- `kind` is `decision` (System One: probabilities read from logits, no generation) or `llm`
  (OpenAI-compatible chat completion).
- `api` is the wire protocol: `systemone` or `openai`. A product is only `base_url`, `model`,
  headers and a key.
- `api_key_env` names the environment variable; the key itself lives in `.env`.
- `options` is merged into the request payload (only for `llm` engines) — e.g. Ollama's
  `reasoning_effort: "none"` to stop a reasoning model from spending the whole answer on thinking.
- `retry` applies to transient failures only (429/5xx); `throttle_s` paces the calls.
- `roles.scorer` must name one of the engines and must accept the role's kind.

### `db_path`

`./data/jobs.db` by default. A relative path is resolved against the project root.

---

## Environment (`.env`)

Only secrets and per-machine identifiers. `load_config()` loads `<repo>/.env` (mode `600`) first and
never overrides a real environment variable, so systemd `EnvironmentFile` and CI secrets still win.

```dotenv
TELEGRAM_BOT_TOKEN=123456789:AAH…
OPENCODE_API_KEY=…          # only if you use the jev / opencode engines
```

---

## Failing fast: what you will see

| Message | Cause |
|---|---|
| `no profile file found in …/config` | neither `profile.yaml` nor `profile.example.yaml` exist |
| `schedule.timezone 'Europe/Roma' is not an IANA zone name` | typo in the timezone |
| `criterion 'pay': set a gate or at least one threshold` | a criterion with neither |
| `criterion 'x': 'missing' must be one of the options` | a `missing` value that is not an option |
| `unresolved placeholder '{{search.foo}}'` | a placeholder that does not exist |
| `['scraping'] declared in both profile and settings` | the same key in both files |
| `notifications.telegram.enabled requires chat_id` | Telegram on without a chat id |
| `notifications.telegram.enabled but $TELEGRAM_BOT_TOKEN is empty` | Telegram on, no token in the env |
| `unknown engine 'x'; known: [...]` | `roles.scorer` names an engine that does not exist |
