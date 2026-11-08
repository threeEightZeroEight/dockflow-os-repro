#!/usr/bin/env python3
"""AQEDF 统计：配对检验与场景汇总。"""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

from scipy import stats

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "research"


def load() -> list[dict]:
    with (DATA / "rq_adaptive.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def ci95(values):
    n = len(values)
    m = statistics.mean(values)
    if n < 2:
        return m, m
    h = stats.t.ppf(0.975, n - 1) * statistics.stdev(values) / (n ** 0.5)
    return m - h, m + h


def paired(rows, scenario, a, b, metric):
    by_seed = {}
    for row in rows:
        if row["scenario"] != scenario or row["algorithm"] not in (a, b):
            continue
        value = row[metric]
        if value not in ("", None):
            by_seed.setdefault(row["seed"], {})[row["algorithm"]] = float(value)
    pairs = [(v[a], v[b]) for v in by_seed.values() if a in v and b in v]
    diffs = [x - y for x, y in pairs]
    mean = statistics.mean(diffs)
    sd = statistics.stdev(diffs)
    lo, hi = ci95(diffs)
    if sd == 0:
        return {"scenario": scenario, "metric": metric, "a": a, "b": b,
                "n": len(pairs), "mean_diff": 0.0, "ci95_diff": [0.0, 0.0],
                "t_p": 1.0, "wilcoxon_p": 1.0, "cohens_d": 0.0}
    _, t_p = stats.ttest_rel([x for x, _ in pairs], [y for _, y in pairs])
    try:
        _, w_p = stats.wilcoxon([x for x, _ in pairs], [y for _, y in pairs])
    except ValueError:
        w_p = 1.0
    return {"scenario": scenario, "metric": metric, "a": a, "b": b,
            "n": len(pairs), "mean_diff": round(mean, 4),
            "ci95_diff": [round(lo, 4), round(hi, 4)],
            "t_p": float(f"{t_p:.3g}"), "wilcoxon_p": float(f"{w_p:.3g}"),
            "cohens_d": round(mean / sd, 3)}


def summary_cell(rows, scenario, algorithm, metric):
    values = [float(r[metric]) for r in rows
              if r["scenario"] == scenario and r["algorithm"] == algorithm
              and r[metric] not in ("", None)]
    lo, hi = ci95(values)
    return {"mean": round(statistics.mean(values), 4),
            "ci95": [round(lo, 4), round(hi, 4)], "n": len(values)}


def main() -> None:
    rows = load()
    scenarios = ["low", "medium", "high", "n120", "n160"]
    summary = {
        "by_scenario": {
            scenario: {
                algorithm: {
                    metric: summary_cell(rows, scenario, algorithm, metric)
                    for metric in ("avg_waiting_time", "outbound_deadline_miss_rate")
                }
                for algorithm in ("edf", "qedf", "aqedf")
            }
            for scenario in scenarios
        },
        "paired": [
            paired(rows, scenario, "aqedf", "edf", metric)
            for scenario in scenarios
            for metric in ("outbound_deadline_miss_rate", "avg_waiting_time")
        ],
        "dependency": {
            f"dep{ratio}": {
                algorithm: summary_cell(rows, f"dep{ratio}", algorithm,
                                        "outbound_deadline_miss_rate")
                for algorithm in ("edf", "qedf", "aqedf")
            } for ratio in (0.0, 0.2, 0.4, 0.6, 0.8)
        },
    }
    (DATA / "stats_adaptive.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# AQEDF 统计（自适应门控，gate=1.5, λ=0.5）", "",
             "## 各场景逾期率/等待（均值 [95% CI]）", "",
             "| 场景 | 算法 | 逾期率 | 平均等待 |", "|---|---|---|---|"]
    for scenario in scenarios:
        for algorithm in ("edf", "qedf", "aqedf"):
            miss = summary["by_scenario"][scenario][algorithm]["outbound_deadline_miss_rate"]
            wait = summary["by_scenario"][scenario][algorithm]["avg_waiting_time"]
            lines.append(f"| {scenario} | {algorithm} | {miss['mean']:.3f} "
                         f"[{miss['ci95'][0]:.3f}, {miss['ci95'][1]:.3f}] | "
                         f"{wait['mean']:.2f} [{wait['ci95'][0]:.2f}, {wait['ci95'][1]:.2f}] |")
    lines += ["", "## AQEDF − EDF 配对检验", "",
              "| 场景 | 指标 | 均值差 [95% CI] | t p | Wilcoxon p | Cohen's d |",
              "|---|---|---|---|---|---|"]
    for item in summary["paired"]:
        lines.append(f"| {item['scenario']} | {item['metric']} | "
                     f"{item['mean_diff']:+.4f} [{item['ci95_diff'][0]:+.4f}, {item['ci95_diff'][1]:+.4f}] | "
                     f"{item['t_p']} | {item['wilcoxon_p']} | {item['cohens_d']:+.3f} |")
    (DATA / "stats_adaptive.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()