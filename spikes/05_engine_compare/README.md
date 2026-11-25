# 05 — Candidate engine vs the production one

Answers one question before switching the default scorer: does another engine change the verdicts,
and is it worth the cost? It is read-only — the baseline answers come from the stored evaluations,
the candidate re-scores the same postings and nothing is written.

```bash
uv run python spikes/05_engine_compare/compare.py --limit 20            # rizzo vs opencode_llm
uv run python spikes/05_engine_compare/compare.py --ids 537,999,2108    # re-use a fixed sample
uv run python spikes/05_engine_compare/compare.py --candidate qwen3_llm --baseline rizzo
```

## 2026-11-03 — deepseek-v4.1-flash (opencode Go) vs rizzo, 20 random postings

Config: `base_url https://opencode.ai/inference/go/openai/v1`, model `deepseek-v4.1-flash`.

| measurement | value |
|---|---|
| decisions agree | **15/20 (75%)** |
| candidate stricter | 5/20 (3 by `location`, 2 by `core_skills`) |
| mean \|Δscore\| | 15.2 |
| latency | mean **19.0 s** · median 16.5 s · max 41.5 s |
| full run estimate (1600 postings) | **8.5 h** (rizzo: 6.6 s/offer ≈ 3 h) |

Per-criterion agreement is only meaningful for the choice criteria (the score criteria are compared
at a different granularity, so 0.67 vs 0.8 counts as disagreement and the percentages say nothing):
`location` 16/20, `applicable` 16/20, `contract_ok` 5/20.

## 2026-11-03 — same 15 postings, prompt rewritten (same engine)

Changes tried: criteria before the posting, numbered levels instead of a 0-1 float, exclusions as
a bullet list, a JSON validator with one corrective retry, "read the whole description" hint.

| measurement | old prompt | new prompt |
|---|---|---|
| decisions | 14 drop by `location`, 1 drop by `core_skills` | **identical** |
| latency | 16.1 s | 13.7 s |
| `applicable` answer | — | **flipped on 7/15** between the two runs |

The prompt rewrite moved nothing on the decisions, and the remaining problem is not the prompt: the
same model answers the binary `applicable` question inconsistently. That is model variance, and it
matters because an evaluation is stored once and never recomputed.

## Who is right on location?

Same 15 postings, rizzo's stored verdicts: 14 drop, **1 review** — a .NET job in Cologno Monzese
(Milan area) with **no remote mention**, which rizzo accepted (`location: accepted`). Under the
written rule (on-site only in Sardinia, or 100% remote) that is a false positive. The LLM dropped it.
On this sample the LLM is *more faithful to the written rule* than rizzo.

An earlier reading of "2 of 3 location errors" was too harsh: "giornate da remoto" and
"predominantly remote" are hybrid / not 100% remote, which the rule says to reject — the LLM followed
the rule. Only "supports up to 100% remote working" (Platform Engineer) was a genuine LLM error.

## Verdict

The disagreement is mostly **a spec question, not a model question**: what to do with hybrid and
flexible-remote offers outside Sardinia. Fix the rule first (state explicitly whether hybrid counts),
then re-measure. Prompt engineering is not the lever here; model variance and the 3x latency are.
Not switched: rizzo stays the production scorer.
