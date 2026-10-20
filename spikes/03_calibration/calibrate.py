"""Spike 03 — calibrate: measure an engine's scoring against the labelled set.

Reads labels.yaml plus one output/results-<engine>.json from spike 02 and reports, for the
postings that have both a label and a measurement:
  - per-criterion separation (mean per verdict + AUC-like rank statistic)
  - missing rate per criterion
  - gate drop counts by verdict (a dropped `apply` is the expensive error)
  - precision/recall at candidate notify thresholds

No LLM is involved: every number is computed from stored answers.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LABELS_PATH = HERE / "labels.yaml"
RESULTS_DIR = ROOT / "spikes" / "02_engine_benchmark" / "output"

POSITIVE = "apply"
SOFT = "maybe"
VERDICTS = (POSITIVE, SOFT, "no")


def load_labels(path: Path = LABELS_PATH) -> dict[str, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {row["external_id"]: row for row in data.get("labels", [])}


def load_results(engine: str, path: Path | None = None) -> dict[str, dict]:
    path = path or RESULTS_DIR / f"results-{engine}.json"
    if not path.exists():
        raise SystemExit(f"missing {path}; run spikes/02_engine_benchmark/engine_benchmark.py")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {row["external_id"]: row for row in data["postings"]}


def auc(values_pos: list[float], values_neg: list[float]) -> float | None:
    """Probability that a positive outranks a negative (0.5 = no separation)."""
    if not values_pos or not values_neg:
        return None
    wins = 0.0
    for a in values_pos:
        for b in values_neg:
            wins += 1.0 if a > b else (0.5 if a == b else 0.0)
    return wins / (len(values_pos) * len(values_neg))


def report(engine: str, labels: dict[str, dict], results: dict[str, dict]) -> str:
    paired = [(labels[eid], results[eid]) for eid in labels if eid in results]
    missing = [eid for eid in labels if eid not in results]
    if not paired:
        raise SystemExit("no labelled posting has a measurement; score the labelled set first")

    counts = Counter(row["verdict"] for row, _ in paired)
    lines = [
        f"# Calibration report — {engine}",
        "",
        f"- labelled: {len(labels)} · measured: {len(paired)} · not measured: {len(missing)}",
        "- verdicts: " + " · ".join(f"{v} {counts.get(v, 0)}" for v in VERDICTS),
        "",
        "## Criteria separation",
        "",
        "| criterion | apply mean | maybe mean | no mean | AUC apply vs no | missing rate |",
        "|---|---|---|---|---|---|",
    ]

    criteria = sorted({key for _, result in paired for key in result["answers"]})
    for key in criteria:
        per_verdict: dict[str, list[float]] = defaultdict(list)
        missing_count = 0
        for row, result in paired:
            value = result["answers"].get(key)
            if key in result.get("missing", []):
                missing_count += 1
            if isinstance(value, (int, float)):
                per_verdict[row["verdict"]].append(float(value))

        def mean_of(verdict: str) -> str:
            values = per_verdict.get(verdict) or []
            return f"{sum(values) / len(values):.2f}" if values else "-"

        separation = auc(per_verdict.get(POSITIVE, []), per_verdict.get("no", []))
        if per_verdict:
            lines.append(
                f"| {key} | {mean_of(POSITIVE)} | {mean_of(SOFT)} | {mean_of('no')} | "
                f"{'-' if separation is None else f'{separation:.2f}'} | "
                f"{missing_count}/{len(paired)} |"
            )
        else:
            options: dict[str, Counter] = defaultdict(Counter)
            for row, result in paired:
                value = result["answers"].get(key)
                if isinstance(value, str):
                    options[row["verdict"]][value] += 1
            def top(verdict: str) -> str:
                counter = options.get(verdict)
                if not counter:
                    return "-"
                option, count = counter.most_common(1)[0]
                return f"{option} ({count})"
            lines.append(
                f"| {key} (choice) | {top(POSITIVE)} | {top(SOFT)} | {top('no')} | - | "
                f"{missing_count}/{len(paired)} |"
            )

    lines += ["", "## Gates", "", "| gate | dropped no | dropped maybe | dropped apply |", "|---|---|---|---|"]
    gates: dict[str, Counter] = defaultdict(Counter)
    for row, result in paired:
        if result.get("dropped_by"):
            gates[result["dropped_by"]][row["verdict"]] += 1
    if not gates:
        lines.append("| (none dropped) | 0 | 0 | 0 |")
    for gate, counter in sorted(gates.items()):
        lines.append(
            f"| {gate} | {counter.get('no', 0)} | {counter.get(SOFT, 0)} | {counter.get(POSITIVE, 0)} |"
        )

    lines += ["", "## Thresholds", "", "| notify threshold | passing | of which apply | of which maybe | precision |", "|---|---|---|---|---|"]
    scores = sorted({round(result["score"]) for _, result in paired})
    for threshold in range(50, 100, 5):
        passing = [(row, result) for row, result in paired if result["score"] >= threshold]
        hits = Counter(row["verdict"] for row, _ in passing)
        precision = hits.get(POSITIVE, 0) / len(passing) if passing else 0.0
        lines.append(
            f"| {threshold} | {len(passing)} | {hits.get(POSITIVE, 0)} | {hits.get(SOFT, 0)} | {precision:.2f} |"
        )
    if scores:
        lines += ["", f"- observed scores: {scores[0]}-{scores[-1]}"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", help="engine name, e.g. rizzo")
    args = parser.parse_args()
    text = report(args.engine, load_labels(), load_results(args.engine))
    out = HERE / "output" / f"calibration-{args.engine}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
