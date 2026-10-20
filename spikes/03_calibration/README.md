# Spike 03 — calibration

**Question:** do the configured criteria actually separate offers you would apply to from the
ones you would not?

Without labels there is nothing to calibrate: every change of a weight or a question would be
an impression. This spike builds a small labelled set and measures the scoring against it.

## Run

```bash
# 1. deterministic stratified sample from the frozen pool (seed fixed)
uv run python spikes/03_calibration/sample.py --per-stratum 6

# 2. score the sample with one engine
uv run python spikes/02_engine_benchmark/engine_benchmark.py --engine rizzo --limit 61 \
  --input spikes/03_calibration/output/sample.json

# 3. measure against labels.yaml
uv run python spikes/03_calibration/calibrate.py rizzo
```

## Input

- `labels.yaml` — committed. One entry per sampled posting: `external_id`, `title`,
  `company`, `query`, `board`, `verdict` (`apply` | `maybe` | `no`), `reason`.
  The first pass is machine-proposed and **the user approves or corrects it**; the labels are
  the ground truth, so an unreviewed label is worth little.

## Output (gitignored)

- `output/sample.json` / `output/sample.tsv` — the sampled postings.
- `output/calibration-<engine>.md` — per-criterion separation, missing rates, gate drops by
  verdict, precision/recall per notify threshold.

## What the metrics mean

- **AUC apply vs no** — probability that an `apply` outranks a `no` on that criterion.
  0.5 = the criterion is noise; below 0.5 = it points the wrong way.
- **missing rate** — how often the model says "not stated". A high rate dilutes the weight and
  applies a confidence penalty; if a criterion is missing half the time, its question is wrong,
  not the model.
- **dropped apply** — the expensive error. A gate that drops an `apply` must be reworded or
  demoted to `shadow`.
- **precision per threshold** — of the postings above the threshold, how many are `apply`.

## Findings of the first pass (61 sampled, rizzo)

| # | Finding | Evidence |
|---|---|---|
| 1 | No `apply` in the sample | 0 apply / 15 maybe / 46 no |
| 2 | `core_skills` is missing 59% of the time | 36/61, mean 0.48 for both maybe and no |
| 3 | `salary_stated` gate is very aggressive | dropped 14 `no` + 1 `maybe` of 61 (23%) |
| 4 | Nothing scores above 60 | max observed 60, so any notify threshold ≥ 65 notifies nothing |

Diagnosis: (2) is a broken question, not a broken model — level 0 "Not stated" invites the
model to answer "unsure"; job ads nearly always state the stack. (3) has no measured benefit
and one demonstrated cost. (1) means the pool itself is thin for these criteria, which is a
profile question before it is a scoring question.
