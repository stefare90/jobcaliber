# Spikes

Throwaway experiments that must run end-to-end and report real numbers. Each spike is a
folder named `<order>_<what_it_answers>`; results live in its `output/` (gitignored).

| Spike | Question it answers | Depends on |
|---|---|---|
| [`01_fetch_coverage`](01_fetch_coverage/) | Do the profile-driven queries reach enough usable offers, and which board/cap limits us? | network + `config.yaml` |
| [`02_engine_benchmark`](02_engine_benchmark/) | Which System One engine discriminates offers best, and at what latency? | `01/input/postings.jsonl` |

## Layout convention

```
<NN>_<description>/
├── README.md          what it does, how to run it, verdict
├── <description>.py   the harness
├── input/             what the run consumes (generated, gitignored)
└── output/            everything the run produces (generated, gitignored)
```

Both `input/` and `output/` are generated and kept out of git: they hold scraped posting
text and personal query results. The scripts + READMEs are the versioned artefact. Spike 02
never re-reads spike 01's raw files: it consumes its own `input/postings.jsonl`, so every
engine is compared on the exact same set of offers.

## Run order

```bash
uv run python spikes/01_fetch_coverage/fetch_coverage.py   # ~10 min, rewrites both spikes' inputs
uv run python spikes/02_engine_benchmark/engine_benchmark.py --engine jev --limit 20
```
