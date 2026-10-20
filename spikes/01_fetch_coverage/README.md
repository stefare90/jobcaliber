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

Takes 20-40 min: 8 queries × 2 boards, sequential, 2s pause between boards, paginated
`page_size` per request up to `board_max_results[board]`, stopping early when a page brings
no new posting.

## Input

- `input/queries.json` — gitignored, written at the start of every run: the exact query matrix,
  boards, `page_size`, `board_max_results`, `country`, `hours_old`, `job_type`. This is what the
  report refers to, so a run is reproducible without guessing the config.

## Output

- `output/raw/q<idx>_<board>.json` — raw postings as returned by the board, captchas never
  stored, `NaN` already normalised to `null`.
- `output/report.md` — per-query and per-board coverage tables, errors, queries below the
  5-row reporting bar, captcha rows skipped. No pass/fail verdict: the numbers are the output.
- `output/report-long.md` — earlier long-form report kept for reference.
- `../02_engine_benchmark/input/postings.jsonl` — frozen deduplicated set (by
  `external_id`), the single input of spike 02.

## Reporting bar

`5` usable rows per query is reported as a diagnostic, not as a verdict: below it a query
cannot sustain a daily pipeline. It never turns the run into a pass/fail.

## Last run

2026-10-19, after raising `board_max_results` to linkedin 300 / indeed 500: 1593 usable rows
over 8 queries, **924 unique postings**, no board errors, no captcha. Only `q2` *Embedded
Software Engineer @ Sardinia* sits under the bar with 3 rows; city-scoped embedded roles are
genuinely scarce, not a fetch bug.

| query | location | remote | seen | new |
|---|---|---|---|---|
| q1 Software Engineer | Sardinia, Italy | no | 27 | 27 |
| q2 Embedded Software Engineer | Sardinia, Italy | no | 3 | 0 |
| q3 Software Developer | Sardinia, Italy | no | 24 | 6 |
| q4 Backend Developer | Sardinia, Italy | no | 20 | 1 |
| q5 Software Engineer | Italy | yes | 371 | 281 |
| q6 Embedded Software Engineer | Italy | yes | 301 | 211 |
| q7 Software Developer | Italy | yes | 518 | 255 |
| q8 Backend Developer | Italy | yes | 331 | 143 |

LinkedIn hit its 300 ceiling on q5-q7; Indeed peaked at 218 (q7), well under its 500 ceiling.
1595 rows collapse to 924 unique postings: the same ad is returned by several queries.
