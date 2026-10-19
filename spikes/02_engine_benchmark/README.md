# Spike 02 — engine benchmark

**Question:** given the same offers, which System One engine separates good matches from
noise best, and at what latency?

Scores every posting of the frozen input with one engine declared in `config.ai.engines`,
then applies the real `Evaluator` (same thresholds, weights and gates as production).

## Run

```bash
# rizzo-flow (local, needs the server up)
cd ~/rizzo-flow && uv run rizzo serve --port 8017 --device auto --quant q4_k_m &
uv run python spikes/02_engine_benchmark/engine_benchmark.py --engine rizzo --limit 20

# jev (opencode System One, free)
uv run python spikes/02_engine_benchmark/engine_benchmark.py --engine jev --limit 20

# deepseek (opencode-go, OpenAI wire)
uv run python spikes/02_engine_benchmark/engine_benchmark.py --engine opencode_llm --limit 20
```

`--engine` accepts any key of `ai.engines`, so new engines are benchmarked with zero code
changes. `--limit` caps the set size; default 20.

## Input

- `input/postings.jsonl` — gitignored frozen set produced by spike 01 (`518` postings, one
  JSON object per line, deduplicated by `external_id`). Never re-derived at run time: every
  engine and every run sees the same offers. Regenerate with
  `fetch_coverage.py` (or `--export-only`, no network needed).

## Output

- `output/report-<engine>.md` — pass/review/drop counts, latency (mean/min/max), full
  leaderboard, per-posting sub-scores and reasons.
- `output/comparison.md` — cross-engine verdict kept by hand from the comparison round.

## Verdict

`jev` is the reference (fast, strict); `rizzo-flow` is the local default (better
discrimination on the earlier sample, ~4.6× faster on the Radeon 760M via Vulkan than on
CPU); laya was rejected (flat scores, 20/20 REVIEW). Numbers and caveats in
`output/comparison.md`.
