# jobcaliber

**A personal job-offer ranker that runs entirely on your machine.** It queries the boards every
day, scores each new offer against *your* criteria with a local model, and shows you only what
deserves attention — without showing you yesterday's same fifty.

```
boards  →  fetch  →  score each offer  →  gate + thresholds  →  pass / review / drop
                                                                    │
                                              you mark it applied / will apply / skipped
                                                                    │
                                          those marks become the labels for calibration
```

- **Searches** LinkedIn and Indeed for the job titles and locations you configure.
- **Scores** every new offer with one question per criterion. The default engine is a **local**
  decision model (no cloud, no API key, your data never leaves the machine).
- **Decides** with hard gates plus per-criterion thresholds, and remembers *which* rule dropped
  an offer.
- **Remembers** everything: an offer is never scored twice with the same rules, never notified
  twice, and every verdict stays attributable to the version of the rules that produced it.
- **Shows** it in a small local web app: filter by any column, open an offer, mark what you did.
- **Notifies** you on Telegram when a run finds offers worth your time.

It is **not** an auto-applier, a CV/cover-letter writer, a multi-user service, or a crawler that
hammers the boards.

---

## Contents

- [Requirements](#requirements)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Configuration](#configuration)
- [The web app](#the-web-app)
- [Engines](#engines)
- [Operating it](#operating-it)
- [Privacy](#privacy)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Requirements

| | |
|---|---|
| OS | Linux (tested on Arch + KDE/Hyprland), macOS, Windows |
| Python | 3.11 or newer (managed by [`uv`](https://docs.astral.sh/uv/)) |
| Disk | ~5 GB (the model + the llama.cpp runtime), plus the database |
| RAM | 8 GB free is enough for the default 4B model; 16 GB is comfortable |
| GPU | optional. The default engine runs on CPU, and ~4x faster on an AMD/NVIDIA iGPU via Vulkan |
| Network | the boards during a fetch; nothing during scoring |

A full run on a modern 8-core desktop with an iGPU takes **~30 min to fetch and ~6 s per new
offer to score**. A machine with a slow CPU and no GPU will take several times longer — see
[Engines](#engines) for the sizes and the trade-offs.

## Quick start

```bash
# 1. uv (Python toolchain, no root)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 2. the project
git clone https://github.com/stefare90/jobcaliber && cd jobcaliber
uv sync --frozen

# 3. your configuration (both files stay out of git)
cp config/profile.example.yaml config/profile.yaml
cp config/settings.example.yaml config/settings.yaml
cp .env.example .env && chmod 600 .env

# 4. a local decision engine (see "Engines"; any OpenAI-compatible API also works)
#    cd ~/rizzo-flow && uv run rizzo serve --port 8017 --device auto --quant q4_k_m

# 5. check it works
uv run pytest -q
uv run jobcaliber db version
uv run jobcaliber run --limit 5 --max-queries 1   # one small real pass, ~1 minute
```

Then open the web app:

```bash
uv run uvicorn jobcaliber.entrypoints.web:create_app --factory --port 8000
# → http://127.0.0.1:8000
```

Use any port you like, but the one you pick must match `notifications.base_url` and the systemd
unit. It is worth binding `0.0.0.0` (as the unit does) so your phone can reach it too.

For a server install with systemd units, firewall and Telegram, follow
[`docs/INSTALL.md`](docs/INSTALL.md). For the day-2 runbook (backups, migrations, upgrades,
what to do when something fails) see [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## How it works

1. **Fetch** (`pipeline/fetch/`) — the queries are
   `search.titles × (on_site_locations + remote_locations)`. Each board is paginated up to
   `scraping.board_max_results[board]`, and a page that brings no new offer stops the loop early.
   Captchas are never stored, `NaN` becomes `None`, and no gate or score is applied here.
2. **Dedup** — the board URL is the identity. Seeing the same offer again only refreshes
   `last_seen_at`.
3. **Score** (`pipeline/scoring/`) — every criterion carries its own question. The rubric is
   **projected at runtime** into the engine's wire format (a `/v1/systemone` payload for decision
   models, a chat prompt for LLM engines): one configuration, two formats, no drift.
4. **Evaluate** (`pipeline/evaluation/`) — gates first, then thresholds, then confidence:
   - a gate drops only on an **explicit negative** answer;
   - a **missing** answer never drops: it forces `review`;
   - below `min_threshold` → `drop`; below `apply_threshold` → `review`; otherwise → `pass`.
5. **Store** (`infrastructure/database/`) — SQLite in WAL. Each judgement is a row in
   `evaluations`, unique per `(job, profile version, engine)`: re-running unchanged rules is a
   no-op, changing the profile re-scores.
6. **Deliver** — the web app reads the database; Telegram sends one digest per run.

**Two processes, one contract.** The web app never runs the pipeline: it inserts a `requested`
row into `runs` and the worker claims it. The database is the only thing they share.

## Configuration

Two files, split by what a change **costs**:

> `config/profile.yaml` answers *what am I looking for and how do I judge it*.
> **Changing it re-scores every posting.**
>
> `config/settings.yaml` answers *how does the system run*.
> **Changing it never re-scores anything.**

```yaml
# config/profile.yaml
search:
  titles: ["Software Engineer", "Embedded Software Engineer", "Backend Developer"]
  on_site_locations: ["Sardinia, Italy"]     # sent to the boards verbatim
  remote_locations: ["Italy"]
  exclude: ["protected categories (law 68/99)", "internship, stage or apprenticeship"]
  job_type: "fulltime"
evaluation:
  systemone_min_confidence: 0.55             # below this a posting is never `pass`
criteria:                                    # free keys: adding one is data, not code
  core_skills: {min_threshold: 0.5, apply_threshold: 0.67, question: {...}}
  pay:         {apply_threshold: 0.75, question: {...}}
  location:    {gate: {accept: ["accepted"]}, question: {...}}
```

- **Scored criteria** (`min_threshold` / `apply_threshold`) take a 0–1 answer. There are **no
  weights**: the 0–100 score is the simple mean, used only to order the list. The decision comes
  from the thresholds, so every drop has a name (`dropped_by`).
- **Gates** (`gate: true`, `gate: {accept: [...]}`, `gate: {min_score: x}`) drop on an explicit
  negative answer, never on a missing one.
- **`missing`** declares, per question, which level or option means *cannot tell*.
- Text may interpolate `{{search.titles}}`, `{{search.on_site_locations}}`,
  `{{search.remote_locations}}`, `{{search.exclude}}`; an unresolved placeholder fails at startup.

Evaluations are keyed by the **content of `config/profile.yaml`**, plus a rubric version bumped in
code when the questions' projection changes. A page size, a scrape time or a Telegram token never
invalidate what the model already answered.

The full reference — every key of both files, with what it does and which values fail fast — is in
[`config/README.md`](config/README.md).

## The web app

| Page | What it does |
|---|---|
| `/jobs` | the table: score, decision, title/company, board, ad location, one column per criterion. Filter panel with **one field per column** (a criterion, score, title, company, board, ad location, decision, status, run, last seen), combined with AND; every header sorts; columns selectable. |
| `/jobs/<id>` | the offer: decision badge, score and confidence, *dropped by*, every answer next to its threshold, the original ad link, the description as markdown, and three marks: **Applied**, **Will apply**, **Not interested**. |
| `/applications` | everything you marked, filterable, with a CSV export. |
| `/runs` | the queue and the history: what ran, how long, what it found, and why it failed. |

The mark belongs to the **posting**, not to a single evaluation, so it survives re-scoring.
Offers you marked are never sent again by Telegram.

There is **no authentication** and no JavaScript. It is meant for localhost, or for your own
network with a firewall rule; a token can be added if you ever expose it further.

## Engines

The scorer is chosen in `config/settings.yaml` (`ai.engines` + `ai.roles.scorer`). Nothing in the
code depends on which one you pick.

| Engine | Kind | Where it runs | Notes |
|---|---|---|---|
| `rizzo` (default) | decision (`systemone`) | local, llama.cpp + Vulkan | 4B, ~6 s/offer on an iGPU; Apache-2.0. Install: [`docs/INSTALL.md`](docs/INSTALL.md#2-the-scoring-engine) |
| `jev` | decision (`systemone`) | opencode Zen, free tier | reference engine, fast (0.3 s), stricter; needs an API key |
| `local_llm` | llm (`openai`) | Ollama | e.g. `qwen3:8b`; ~20 s/offer, self-reported confidence |
| `opencode_llm` | llm (`openai`) | opencode Zen | a hosted model, same interface |

Adding an engine means adding a few lines under `ai.engines` (a *product* is only `base_url`,
`model`, headers and a key). A new *wire protocol* is one file: an `AIClient` subclass registered
with `@AIClient.register("<api>", "<kind>")`.

## Operating it

```bash
uv run jobcaliber status                 # last run + notifiable offers
uv run jobcaliber run --limit 5 --max-queries 1    # a bounded pass
uv run jobcaliber-worker                 # schedule + queued requests (systemd keeps it alive)
uv run jobcaliber db check               # does the database match the expected schema?
uv run jobcaliber db backup --to data/jobs.db.bak
uv run jobcaliber db migrate --dry-run   # migrations are manual, never automatic
```

- A full run costs one model call per new offer plus the fetch. Re-runs only score what is new.
- The worker checks the config file's mtime on every tick and reloads it: no restart to change a
  threshold.
- A dead engine costs ~40 ms, not a fetch: the run probes the engine **before** scraping.
- Logs: `journalctl --user -u jobcaliber-worker -f` for the unit, or the terminal you started it
  from.

Backups, restore, upgrades, retention and the failure matrix are in
[`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## Privacy

Postings, criteria and your marks stay in `data/jobs.db` on your machine. Outbound calls go only
to the boards (during a fetch) and to the engine you configured. No LinkedIn login, no captcha
storage, no telemetry. `config/profile.yaml`, `config/settings.yaml`, `.env` and `data/` are
gitignored.

## Development

```bash
uv run pytest -q          # the whole suite, layering rules included
uv run python spikes/02_engine_benchmark/engine_benchmark.py --engine rizzo --limit 20
uv run python spikes/03_calibration/calibrate.py rizzo
```

The layering (`core → pipeline → infrastructure → application → entrypoints`) is enforced by
`tests/test_layers.py`; the architecture and its invariants are written down in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). `AGENTS.md` holds the rules for contributors
(human or agent), and `spikes/` holds throwaway experiments that must report real numbers.

## Troubleshooting

| Symptom | Probably |
|---|---|
| the worker does nothing | nothing is due: `jobcaliber status`, then look at `runs` |
| a run fails in milliseconds | the engine is not listening: start it, check `curl <base_url>` |
| `SchemaMismatch` on start | the database is older/newer than the code: `jobcaliber db migrate` |
| no `pass` for days | expected with strict thresholds; read the `review` rows and tune `apply_threshold` |
| the page shows stale data | `Cache-Control: no-store` is on; check the build stamp in the footer |

The full matrix, with the exact commands, is in
[`docs/OPERATIONS.md#troubleshooting`](docs/OPERATIONS.md#troubleshooting).

## License

MIT — see [`LICENSE`](LICENSE).
