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
uv run python spikes/02_engine_benchmark/engine_benchmark.py --engine local_llm --limit 20   # qwen3:8b

# cross-engine report from every measured run (no re-scoring); optional engine subset
uv run python spikes/02_engine_benchmark/compare_benchmark.py
uv run python spikes/02_engine_benchmark/compare_benchmark.py rizzo jev
```

`--engine` accepts any key of `ai.engines`, so new engines are benchmarked with zero code
changes. `--limit` caps the set size; default 20.

## Input

- `input/postings.jsonl` — gitignored frozen set produced by spike 01 (`924` postings, one
  JSON object per line, deduplicated by `external_id`). Never re-derived at run time: every
  engine and every run sees the same offers. Regenerate with
  `fetch_coverage.py` (or `--export-only`, no network needed).

## Output

- `output/report-<engine>.md` — pass/review/drop counts, latency (mean/min/max), full
  leaderboard, per-posting sub-scores and reasons.
- `output/results-<engine>.json` — machine-readable run: engine/model/options, `dataset_sha`,
  `limit`, total time, failures, and one entry per posting (decision, score, confidence,
  sub-scores, location bucket, latency). This is what `compare_benchmark.py` reads.
- `output/comparison.md` — written by `compare_benchmark.py`: decision mix per engine,
  mean score and `stdev` (discrimination), latency, per-posting decisions and a pairwise
  agreement matrix.

## compare_benchmark.py

Standalone on purpose: the runner measures, the comparator reports. Re-render the
comparison without re-scoring, and compare as soon as one more engine has been measured.
It reads every `results-*.json` (or the engines you name) and refuses two things: mixing
runs with a different `dataset_sha`/`limit`, and reporting results that no longer match the
current `input/postings.jsonl`. When the dataset changes, it says which engines must be
re-run instead of silently showing stale numbers.

## Verdict

20 postings, same set, `dataset_sha 518e3d8eb2ee6062`:

| engine | model | PASS | REVIEW | DROP | mean | stdev | latency |
|---|---|---|---|---|---|---|---|
| `rizzo` | rizzo-latest | 4 | 7 | 9 | 47.6 | **25.1** | 4.19s |
| `jev` | jev-1.13-free | 0 | 1 | 19 | 23.0 | 16.7 | **0.40s** |
| `opencode_llm` | deepseek-v4.1-flash | 0 | 0 | 20 | 10.2 | 15.0 | 5.92s |
| `local_llm` | qwen3:8b | 0 | 7 | 13 | 10.9 | 12.8 | 11.72s |

- **`rizzo` is the only engine that discriminates** on this sample: 4 PASS, 7 REVIEW, and
  the widest score spread.
- **`jev` and `deepseek` are strict** (19-20 DROP out of 20) and score differently: near-zero
  recall on this sample. `jev` flipped one posting between two identical runs (0 -> 1
  REVIEW), so its decisions are not perfectly deterministic even at temperature 0.
- **`qwen3:8b` is flat**: most postings land on `core=0, tools=0, contract=0, pay=0.5`
  → a constant 7.5, plus implausible location buckets (`Roma` → `primary`). Usable as a
  fast local fallback, not as a scorer.
- `gemma4:26b` cannot run on this machine (`radv/amdgpu: Not enough memory`,
  `ErrorDeviceLost`), so it was excluded from the comparison.

**Caveat:** the 20 postings are the first 20 by `external_id`, i.e. an alphabetical slice
of URLs, not a representative sample — mostly noise. Useful for latency and wire checks,
not yet for calibration. The per-posting table links every ad, so a decision can be checked
against the original text. Numbers in `output/comparison.md`.
