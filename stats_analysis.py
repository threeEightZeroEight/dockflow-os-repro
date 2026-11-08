#!/usr/bin/env python3
"""统计检验：均值/95% CI、配对 t 检验、Wilcoxon 符号秩、Cohen's d。"""
from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path

from scipy import stats

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "extended"

ALGORITHMS = ["fcfs", "spt", "edf", "edf_aging", "dependency_aware", "joint_da", "rh_da"]
METRICS = [
    "avg_waiting_time", "p95_waiting_time", "max_waiting_time",
    "outbound_deadline_miss_rate", "throughput", "dock_utilization",
    "long_wait_task_ratio", "decision_avg_ms",
]


def load(name: str) -> list[dict]:
    with (DATA / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def num(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def ci95(values: list[float]) -> tuple[float, float]:
    n = len(values)
    mean = statistics.mean(values)
    if n < 2:
        return (mean, mean)
    half = stats.t.ppf(0.975, n - 1) * statistics.stdev(values) / math.sqrt(n)
    return (mean - half, mean + half)


def describe(values: list[float]) -> dict:
    lo, hi = ci95(values)
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 4),
        "std": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
        "ci95": [round(lo, 4), round(hi, 4)],
    }


def group(rows: list[dict], key_fields: tuple[str, ...], metric: str) -> dict:
    buckets: dict[tuple, list[float]] = {}
    for row in rows:
        value = num(row.get(metric))
        if value is None:
            continue
        buckets.setdefault(tuple(row[k] for k in key_fields), []).append(value)
    result: dict = {}
    for key, values in buckets.items():
        cursor = result
        for part in key[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[key[-1]] = describe(values)
    return result


def paired(rows: list[dict], scenario: str, metric: str, a: str, b: str) -> dict | None:
    by_seed: dict[str, dict[str, float]] = {}
    for row in rows:
        if row["scenario"] != scenario:
            continue
        if row["algorithm"] not in (a, b):
            continue
        value = num(row.get(metric))
        if value is None:
            continue
        by_seed.setdefault(row["seed"], {})[row["algorithm"]] = value
    pairs = [(v[a], v[b]) for v in by_seed.values() if a in v and b in v]
    if len(pairs) < 5:
        return None
    diffs = [x - y for x, y in pairs]
    mean_diff = statistics.mean(diffs)
    std_diff = statistics.stdev(diffs)
    lo, hi = ci95(diffs)
    t_stat, t_p = stats.ttest_rel([x for x, _ in pairs], [y for _, y in pairs])
    try:
        w_stat, w_p = stats.wilcoxon([x for x, _ in pairs], [y for _, y in pairs])
    except ValueError:
        w_stat, w_p = float("nan"), 1.0
    cohens_d = mean_diff / std_diff if std_diff else 0.0
    return {
        "scenario": scenario, "metric": metric, "a": a, "b": b,
        "n_pairs": len(pairs),
        "mean_diff": round(mean_diff, 4),
        "ci95_diff": [round(lo, 4), round(hi, 4)],
        "t_stat": round(float(t_stat), 3),
        "t_p": float(f"{t_p:.3g}"),
        "wilcoxon_p": float(f"{w_p:.3g}"),
        "cohens_d": round(cohens_d, 3),
    }


def main() -> None:
    ea = load("ea_multi_scenario.csv")
    eb = load("eb_mendeley.csv")
    ec = load("ec_scale.csv")
    ed = load("ed_dependency.csv")
    ee = load("ee_docks.csv")
    ef = load("ef_aging.csv")
    eg = load("eg_ablation.csv")

    summary = {
        "ea_multi_scenario": {
            level: {
                algorithm: {metric: describe([
                    v for r in ea
                    if r["scenario"] == level and r["algorithm"] == algorithm
                    for v in [num(r.get(metric))] if v is not None
                ]) for metric in METRICS}
                for algorithm in ALGORITHMS
            }
            for level in ("low", "medium", "high")
        },
        "eb_mendeley": {
            algorithm: {metric: describe([
                v for r in eb if r["algorithm"] == algorithm
                for v in [num(r.get(metric))] if v is not None
            ]) for metric in METRICS}
            for algorithm in ALGORITHMS
        },
        "ec_scale": group(ec, ("scenario", "algorithm"), "avg_waiting_time"),
        "ed_dependency": group(ed, ("scenario", "algorithm"), "outbound_deadline_miss_rate"),
        "ee_docks": group(ee, ("scenario", "algorithm"), "avg_waiting_time"),
        "ef_aging": group(ef, ("scenario", "algorithm"), "long_wait_task_ratio"),
        "eg_ablation": group(eg, ("variant", "algorithm"), "outbound_deadline_miss_rate"),
    }

    comparisons = [
        ("medium", "avg_waiting_time", "spt", "fcfs"),
        ("medium", "max_waiting_time", "spt", "fcfs"),
        ("medium", "outbound_deadline_miss_rate", "edf", "fcfs"),
        ("medium", "p95_waiting_time", "edf", "fcfs"),
        ("medium", "long_wait_task_ratio", "edf_aging", "edf"),
        ("medium", "outbound_deadline_miss_rate", "dependency_aware", "edf"),
        ("medium", "avg_waiting_time", "joint_da", "fcfs"),
        ("medium", "outbound_deadline_miss_rate", "joint_da", "fcfs"),
        ("medium", "outbound_deadline_miss_rate", "rh_da", "edf"),
        ("medium", "avg_waiting_time", "rh_da", "edf"),
        ("medium", "decision_avg_ms", "rh_da", "edf"),
    ]
    summary["paired_tests"] = [
        result for result in (
            paired(ea, *item) for item in comparisons
        ) if result is not None
    ]

    (DATA / "stats_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = ["# 统计检验摘要（20 种子，均值 [95% CI]）", ""]
    lines.append("## 多场景主结果（medium）")
    lines.append("")
    lines.append("| 算法 | 平均等待 | P95 | 最大等待 | 逾期率 | 吞吐量 | 利用率 |")
    lines.append("|---|---|---|---|---|---|---|")
    for algorithm in ALGORITHMS:
        cells = []
        for metric in ("avg_waiting_time", "p95_waiting_time", "max_waiting_time",
                       "outbound_deadline_miss_rate", "throughput", "dock_utilization"):
            item = summary["ea_multi_scenario"]["medium"][algorithm][metric]
            cells.append(f"{item['mean']:.3f} [{item['ci95'][0]:.3f},{item['ci95'][1]:.3f}]")
        lines.append(f"| {algorithm} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## 配对检验（medium，20 对）")
    lines.append("")
    lines.append("| 指标 | A vs B | 均值差 [95% CI] | t 检验 p | Wilcoxon p | Cohen's d |")
    lines.append("|---|---|---|---|---|---|")
    for item in summary["paired_tests"]:
        lines.append(
            f"| {item['metric']} | {item['a']} vs {item['b']} | "
            f"{item['mean_diff']:.4f} [{item['ci95_diff'][0]:.4f},{item['ci95_diff'][1]:.4f}] | "
            f"{item['t_p']} | {item['wilcoxon_p']} | {item['cohens_d']:.3f} |"
        )
    (DATA / "stats.md").write_text("\n".join(lines), encoding="utf-8")

    print("已生成 stats_summary.json / stats.md")
    print("\n".join(lines[lines.index("## 配对检验（medium，20 对）"):]))


if __name__ == "__main__":
    main()