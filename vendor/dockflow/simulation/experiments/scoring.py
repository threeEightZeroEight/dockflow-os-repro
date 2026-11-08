"""Relative DockScore for experiment-only scheduler comparison.

This is NOT a physical metric or a universal measure of algorithm quality.
Scores are relative to the SAME frozen scenario/seed and selected algorithms.
Never score runs with unfinished trucks or missing metrics. Keep raw results.
"""
from __future__ import annotations

import math
from collections import defaultdict

SCORE_WEIGHTS = {
    "avg_waiting_time": 0.25,
    "p95_waiting_time": 0.20,
    "outbound_deadline_miss_rate": 0.30,
    "throughput": 0.15,
    "dock_utilization": 0.10,
}
LOWER_IS_BETTER = frozenset((
    "avg_waiting_time", "p95_waiting_time", "outbound_deadline_miss_rate",
))
# Avoid a worst-in-one-dimension result collapsing every score to zero.
SCORE_FLOOR = 0.20
TIE_NEUTRAL = 0.50


def score_experiment_runs(runs: list[dict]) -> None:
    """Attach evaluation.dock_score to each run; never edit physical metrics.

    Normalization anchors are min/max of selected algorithms at a specific
    (parameter_value, seed). The score changes if the comparison cohort changes.
    A tied metric provides the same neutral 0.5 benefit to all competitors.
    """
    grouped: dict[tuple[int | float, int], list[dict]] = defaultdict(list)
    for row in runs:
        row["evaluation"] = {"dock_score": None}
        grouped[(row["parameter_value"], row["seed"])].append(row)

    for peers in grouped.values():
        valid = []
        for row in peers:
            metrics = row["result"]["metrics"]
            if metrics.get("uncompleted_count", 0) != 0:
                continue
            if all(type(metrics.get(k)) in (int, float) and math.isfinite(metrics[k])
                   for k in SCORE_WEIGHTS):
                valid.append(row)
        if len(valid) < 2:
            continue

        bounds = {
            k: (min(row["result"]["metrics"][k] for row in valid),
                max(row["result"]["metrics"][k] for row in valid))
            for k in SCORE_WEIGHTS
        }
        for row in valid:
            total = 0.0
            for metric, weight in SCORE_WEIGHTS.items():
                lo, hi = bounds[metric]
                value = row["result"]["metrics"][metric]
                if math.isclose(lo, hi, rel_tol=1e-9, abs_tol=1e-12):
                    normalized = TIE_NEUTRAL
                else:
                    normalized = (hi-value)/(hi-lo) if metric in LOWER_IS_BETTER else (value-lo)/(hi-lo)
                normalized = max(0.0, min(1.0, normalized))
                total += weight * math.log(SCORE_FLOOR + (1-SCORE_FLOOR)*normalized)
            row["evaluation"]["dock_score"] = round(100*math.exp(total), 3)
