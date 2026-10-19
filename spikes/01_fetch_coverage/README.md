# Spike 01 — fetch coverage

**Question:** with the queries generated from `profile.titles × preferred_locations`, how
many *usable* offers does each query × board pair actually return, and where do caps or
empty boards bite?

Fetch only: no scoring, no gates, no hardcoded title/location heuristics. Whatever the
model should judge is left to spike 02.

## Run

```bash
uv run python spikes/01_fetch_coverage/fetch_coverage.py              # fetch + report + export
uv run python spikes/01_fetch_coverage/fetch_coverage.py --export-only  # rebuild only the benchmark set
```

Takes ~10 min: 7 queries × 2 boards, sequential, 2s pause between boards, paginated
`page_size` per request up to `page_cap` rows per board/query.

## Input

- `input/queries.json` — gitignored, written at the start of every run: the exact query matrix,
  boards, `page_size`, `page_cap`, `country`, `hours_old`, `job_type`. This is what the
  report refers to, so a run is reproducible without guessing the config.

## Output

- `output/raw/q<idx>_<board>.json` — raw postings as returned by the board, captchas never
  stored, `NaN` already normalised to `null`.
- `output/report.md` — per-query and per-board coverage table, errors, pass bar, verdict.
- `output/report-long.md` — earlier long-form report kept for reference.
- `../02_engine_benchmark/input/postings.jsonl` — frozen deduplicated set (by
  `external_id`), the single input of spike 02.

## Pass bar

`>= 5` usable rows per query (a query with 0-3 rows cannot sustain a daily pipeline) and no
captcha stored.

## Verdict

Last run (2026-10-19): **FAIL** — 632 usable rows over 7 queries, 518 unique postings, no
board errors and no captcha, but `q3` *Embedded Software Engineer @ Sardinia* returned only
3 rows. City-scoped embedded roles are genuinely scarce, not a fetch bug; the remaining
criteria are met. See `output/report.md`.
