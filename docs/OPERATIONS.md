# Operating jobcaliber

The day-2 runbook: what to look at, what to back up, how to change things safely, and what to do
when something is wrong.

- [Daily and weekly](#daily-and-weekly)
- [Where things are](#where-things-are)
- [Inspecting the database](#inspecting-the-database)
- [Backup and restore](#backup-and-restore)
- [Changing the rules](#changing-the-rules)
- [Engines](#engines)
- [Retention](#retention)
- [Upgrading](#upgrading)
- [Troubleshooting](#troubleshooting)

---

## Daily and weekly

Nothing is required: the worker owns the schedule. These are the commands worth knowing.

```bash
# what happened
uv run jobcaliber status                     # last run + how many offers are notifiable
systemctl --user status jobcaliber-worker    # is the process alive?
journalctl --user -u jobcaliber-worker -n 50 --no-pager

# force a run now (the web button does the same thing)
uv run jobcaliber run                        # full pass, in the foreground
uv run jobcaliber run --limit 5 --max-queries 1 --dry-run   # smoke test, writes nothing

# the database
uv run jobcaliber db version                 # schema in use vs expected
uv run jobcaliber db check                   # live schema == schema.sql?
```

A healthy log is quiet: the worker writes a line per tick **only when something happens** (a run
starts, the config is reloaded, a request is queued). The web app shows the same history in
`/runs`.

Weekly, worth a glance:

- `/runs`: any `failed` row carries the error message.
- `data/jobs.db` size: growth is normal (the descriptions are the bulk).
- `uv run jobcaliber db backup` — see below.

## Where things are

| Path | What |
|---|---|
| `config/profile.yaml` | what you look for and how you judge it — **changing it re-scores** |
| `config/settings.yaml` | scraping, schedule, notifications, engines, `db_path` |
| `.env` | secrets (`TELEGRAM_BOT_TOKEN`, engine API keys), mode `600` |
| `data/jobs.db` | the database (WAL: `-wal` and `-shm` sit next to it) |
| `data/jobs.db.bak-vN` | the automatic pre-migration backup |
| `output/` | fetch/benchmark artefacts from `spikes/`, disposable |

Logs: `journalctl --user -u jobcaliber-{web,worker,rizzo}` for the units; the terminal for a
process you started by hand.

## Inspecting the database

Read-only queries, handy for answering "why is this offer not here?".

```bash
sqlite3 data/jobs.db "SELECT id,status,trigger,started_at,duration_ms,error FROM runs ORDER BY id DESC LIMIT 5;"
sqlite3 data/jobs.db "SELECT decision, COUNT(*) FROM evaluations WHERE config_v=(SELECT MAX(v) FROM config_versions) GROUP BY decision;"
sqlite3 data/jobs.db "SELECT state, COUNT(*) FROM applications GROUP BY state;"
sqlite3 data/jobs.db "SELECT title, score_total, dropped_by FROM jobs j JOIN evaluations e ON e.job_id=j.id
                      WHERE e.decision='review' ORDER BY e.score_total DESC LIMIT 10;"
sqlite3 data/jobs.db "SELECT COUNT(*) FROM evaluations WHERE config_v=3;"   # progress of a run
```

`SELECT * FROM runs` is also the queue: a row with `status='requested'` is waiting for the worker,
`running` means it is being executed now.

## Backup and restore

The database is one file, but it runs in **WAL mode**: copying only `data/jobs.db` while a process
is writing can silently lose the tail of the journal. Use the built-in command, which uses
SQLite's backup API and is safe on a live database.

```bash
uv run jobcaliber db backup                      # → data/jobs.db.bak
uv run jobcaliber db backup --to /backup/jobs-2026-10-24.db
```

Restore:

```bash
systemctl --user stop jobcaliber-worker jobcaliber-web   # nothing may hold the file
cp /backup/jobs-2026-10-24.db data/jobs.db
rm -f data/jobs.db-wal data/jobs.db-shm                  # never mix WAL files with another db
systemctl --user start jobcaliber-web jobcaliber-worker
uv run jobcaliber db check
```

A cheap weekly cron entry is enough:

```cron
0 4 * * * cd /home/you/jobcaliber && .venv/bin/jobcaliber db backup --to /backup/jobs-$(date +\%F).db
```

(`schedule.backup_time` exists in the config but is **not implemented yet**: no code reads it.)

## Changing the rules

- **`config/profile.yaml`** (titles, locations, criteria, thresholds, `min_confidence`): every
  change creates a new profile version and the next run re-scores **every** posting of that
  profile. On ~1 000 postings that is ~2 hours on an iGPU. The old evaluations stay in the
  database, attributable to the version that produced them.
- **`config/settings.yaml`** (schedule, scraping, notifications, engines, paths): free. The worker
  reloads it on the next tick (it watches both files' mtime), no restart needed.
- The web and the CLI always render the **latest** evaluation of a posting; `/runs` shows which
  run and which profile version produced it.

### The profile is per machine

`config/profile.yaml` and `config/settings.yaml` are gitignored: they never travel with the code.
When the workshop and the controller are two different machines, **editing the rules in the
workshop does not change what the controller scores** — it keeps running the copy it has. After a
change, copy the profile over and check that the two are identical before trusting the next run:

```bash
# in the workshop
sha256sum config/profile.yaml
cat config/profile.yaml | ssh controller 'cat > ~/Projects/jobcaliber/config/profile.yaml'
ssh controller 'sha256sum ~/Projects/jobcaliber/config/profile.yaml'   # same digest
```

The next run on the controller records a new profile version and re-scores everything, exactly as if
the edit had been made there. `settings.yaml` is **not** copied: it is per machine by design (engine
address, database path, schedule, notification links).

To experiment without paying the full re-score, use a bounded run first:

```bash
uv run jobcaliber run --limit 20 --max-queries 1     # 20 offers instead of all of them
```

## Engines

The scorer is `ai.roles.scorer` in `config/settings.yaml`. Every engine declared in `ai.engines` can
also be benchmarked without touching production:

```bash
uv run python spikes/02_engine_benchmark/engine_benchmark.py --engine <name> --limit 20
uv run python spikes/03_calibration/calibrate.py <name>       # against the 61 labelled offers
```

Measured on a Ryzen 5 8600G with the Radeon 760M iGPU (Vulkan), per offer:

| Engine | Latency | Notes |
|---|---|---|
| `rizzo` (4B, Q4_K_M) | ~6 s | default; best discrimination per second |
| `jev` (cloud, free tier) | ~0.3 s | strictest; free tier throttles in bursts |
| `qwen3:8b` via Ollama | ~20 s | generation, self-reported confidence |
| `qwen3.5:9b` / `granite4.2:8b` via Ollama | ~20–27 s | slower than the decision engines, no better on the reviews |

Two rules of thumb: a **decision** engine (one forward pass, probabilities read from logits) is
much cheaper than a generative one, and the numbers scale with memory bandwidth — on a machine
without an iGPU, divide by 3–5.

If the engine is down, the run fails in ~40 ms (before the fetch) and is **not** retried: a
stopped service does not fix itself, and three retries would waste three fetches. Start the engine
and press *Run now*.

## The model host

When the engine lives on another machine (see `docs/INSTALL.md`), the run's log tells you what the
controller did and why:

| line | meaning |
|---|---|
| `model host: waking 10.10.0.2` | the machine was off and a magic packet was sent |
| `model host: machine already on, starting the engine` | the machine was up, the engine was not |
| `model host: engine ready after about Ns` | the engine answers; the run continues |
| `model host: stopping the engine (the machine stays on)` | the controller started it, so it stops it — the machine was already on |
| `model host: powering the machine off` | the controller woke the machine, so it powers it off |

- **The engine unit on the host arms a 3 hour `poweroff` watchdog** (`ExecStartPost`). It exists so a
  machine started for an unattended run cannot stay on forever, and it dies with the shutdown.
  To keep the machine on by hand: `sudo systemctl stop rizzo-idle-watchdog.timer`.
- **Leave the host as you found it** is enforced: if the machine was already on when the run
  started, nothing is powered off at the end (a failure in either command never fails the run).
- **Neither machine may sleep while it is needed.** The engine unit holds
  `systemd-inhibit --what=idle:sleep` for as long as the engine runs, so a desktop idle daemon
  (`hypridle`, PowerDevil) cannot suspend the host in the middle of a run — the lock disappears
  with the engine. The **controller** must never suspend at all (it is the one that sends the
  06:00 packet): on KDE, *Power Management → Energy Saving → Suspend session = Do nothing* (AC and
  battery), and `~/.config/powerdevilrc` must contain `[AC][SuspendAndShutdown] AutoSuspendAction=0`.
- If you start the engine **by hand** (not through the unit), hold the same lock yourself:
  `systemd-inhibit --what=idle:sleep --who=rizzo --why=dev uv run rizzo serve …`.

## Retention

Nothing is deleted automatically. Deleting rows is rarely the right move:

- a posting that is still online comes back on the next fetch and is then scored as new;
- `DELETE FROM jobs` cascades into `applications`, i.e. it deletes the record of where you applied.

If the database grows too much, prune the **bulk**, not the history:

```bash
uv run jobcaliber db backup
sqlite3 data/jobs.db "UPDATE jobs SET description = NULL
                      WHERE first_seen_at < datetime('now','-60 days')
                        AND id NOT IN (SELECT job_id FROM applications);"
sqlite3 data/jobs.db "VACUUM;"
```

The descriptions are ~4 KB each (~4 MB per 1 000 postings); everything else is small.

## Upgrading

```bash
cd ~/jobcaliber
git pull
uv sync --frozen
uv run jobcaliber db check               # names the command to run when the schema moved
uv run jobcaliber db migrate --dry-run
uv run jobcaliber db migrate             # backup + one transaction per step
systemctl --user restart jobcaliber-web jobcaliber-worker
```

A schema change is never applied by a process: `Store` creates an empty database but refuses to
alter an existing one, so a forgotten migration stops with a message instead of corrupting data.

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| the worker does nothing | `jobcaliber status`, then `SELECT * FROM runs ORDER BY id DESC LIMIT 5` | nothing is due: the next `scrape_times` slot will fire; a run can be queued from `/runs` |
| a run fails in milliseconds with `EngineUnreachable` | `curl <engine base_url>` | start the engine (`sudo systemctl start rizzo` on the model host) |
| `SchemaMismatch` on start | `jobcaliber db version` vs the version in the message | `jobcaliber db migrate` |
| `no profile file found in …/config` | `ls config/` | copy the two examples (step 3 of the install) |
| `schedule.timezone 'Europe/Roma' is not an IANA zone name` | the message lists valid examples | fix the value (`Europe/Rome`, `UTC`, …) |
| `criterion 'x': set a gate or at least one threshold` | `config/profile.yaml` | every criterion needs thresholds or a gate |
| no `pass` for days | `/jobs?decisions=review` | expected with strict thresholds: read the reviews, then lower `apply_threshold` |
| Telegram silent although there are new offers | `applications` table, `notified_at` | marked or already notified offers are not re-sent; check `enabled`, `chat_id`, the token in `.env` |
| Telegram error at startup | `notifications.telegram.enabled` without `chat_id`, or the token variable empty | fix one of the two; the message says which |
| the page is stale | the build stamp in the footer | hard-reload; responses carry `Cache-Control: no-store` |
| `model host did not answer within Ns` | `ping <address>`, then `ssh -i ~/.ssh/host-start host` by hand | the machine did not wake (BIOS ErP/`Resume By PCI-E`), or the engine unit failed: `journalctl -u rizzo` on the host |
| the host stays on after a run that woke it | `/runs` error column, `journalctl --user -u jobcaliber-worker` | `poweroff_command` failed (sudoers rule missing?) — it is best effort, so the run is still `ok` |
| a run is `running` after a crash | `jobcaliber status` | the next tick marks it `failed` (`process died`) and the offer stays pending |

When in doubt, the two commands that answer most questions:

```bash
uv run jobcaliber status
sqlite3 data/jobs.db "SELECT id,status,error,duration_ms FROM runs ORDER BY id DESC LIMIT 3;"
```
