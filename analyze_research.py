#!/usr/bin/env python3
"""研究实验统计：QEDF 配对检验、依赖扫描、下界 gap、大规模。"""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

from scipy import stats

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "research"


def load(name: str) -> list[dict]:
    with (DATA / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def num(value):
    return None if value in ("", None) else float(value)


def ci95(values: list[float]) -> tuple[float, float]:
    n = len(values)
    mean = statistics.mean(values)
    if n < 2:
        return mean, mean
    half = stats.t.ppf(0.975, n - 1) * statistics.stdev(values) / (n ** 0.5)
    return mean - half, mean + half


def describe(values: list[float]) -> dict:
    lo, hi = ci95(values)
    return {"n": len(values), "mean": round(statistics.mean(values), 4),
            "ci95": [round(lo, 4), round(hi, 4)]}


def paired(rows, scenario, a, b, metric):
    by_seed = {}
    for row in rows:
        if row["scenario"] != scenario or row["algorithm"] not in (a, b):
            continue
        value = num(row.get(metric))
        if value is not None:
            by_seed.setdefault(row["seed"], {})[row["algorithm"]] = value
    pairs = [(v[a], v[b]) for v in by_seed.values() if a in v and b in v]
    diffs = [x - y for x, y in pairs]
    mean_diff = statistics.mean(diffs)
    sd = statistics.stdev(diffs)
    lo, hi = ci95(diffs)
    if sd == 0:
        t_p = w_p = 1.0
        d = 0.0
    else:
        _, t_p = stats.ttest_rel([x for x, _ in pairs], [y for _, y in pairs])
        try:
            _, w_p = stats.wilcoxon([x for x, _ in pairs], [y for _, y in pairs])
        except ValueError:
            w_p = 1.0
        d = mean_diff / sd
    return {"scenario": scenario, "metric": metric, "a": a, "b": b,
            "n": len(pairs), "mean_diff": round(mean_diff, 4),
            "ci95_diff": [round(lo, 4), round(hi, 4)],
            "t_p": float(f"{t_p:.3g}"), "wilcoxon_p": float(f"{w_p:.3g}"),
            "cohens_d": round(d, 3)}


def group(rows, key_fields, metric):
    buckets = {}
    for row in rows:
        value = num(row.get(metric))
        if value is None:
            continue
        key = tuple(row[k] for k in key_fields)
        buckets.setdefault(key, []).append(value)
    out = {}
    for key, values in buckets.items():
        cursor = out
        for part in key[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[key[-1]] = describe(values)
    return out


def main() -> None:
    qedf_rows = load("rq_qedf.csv")
    dep_rows = load("rq_dependency.csv")
    bound_rows = load("rq_lower_bound.csv")
    large_rows = load("rq_large_scale.csv")

    summary = {
        "qedf": {level: {algorithm: {
            metric: describe([v for r in qedf_rows
                              if r["scenario"] == level and r["algorithm"] == algorithm
                              for v in [num(r.get(metric))] if v is not None])
            for metric in ("avg_waiting_time", "outbound_deadline_miss_rate",
                           "p95_waiting_time", "max_waiting_time")
        } for algorithm in ("edf", "qedf", "spt", "dependency_aware", "joint_da", "rh_da")}
            for level in ("low", "medium", "high")},
        "dependent_pairs": [
            paired(qedf_rows, level, "qedf", "edf", metric)
            for level in ("medium", "high")
            for metric in ("outbound_deadline_miss_rate", "avg_waiting_time")
        ],
        "dependency": group(dep_rows, ("scenario", "algorithm"),
                            "outbound_deadline_miss_rate"),
        "lower_bound": {row["scenario"]: {
            "avg_waiting": round(float(row["lower_bound_avg_waiting"]), 4),
            "miss_rate": round(float(row["lower_bound_miss_rate"]), 4),
        } for row in bound_rows if row["scenario"] != "benchmark"},
        "large_scale": group(large_rows, ("scenario", "algorithm"),
                             "avg_waiting_time"),
        "large_scale_miss": group(large_rows, ("scenario", "algorithm"),
                                  "outbound_deadline_miss_rate"),
    }

    # Gap to lower bound for medium/high.
    gaps = {}
    for level in ("medium", "high"):
        bound = summary["lower_bound"][level]
        gaps[level] = {}
        for algorithm in ("edf", "qedf", "spt", "dependency_aware", "joint_da", "rh_da"):
            item = summary["qedf"][level][algorithm]
            gaps[level][algorithm] = {
                "wait_ratio": round(item["avg_waiting_time"]["mean"]
                                    / max(bound["avg_waiting"], 1e-6), 3),
                "miss_abs_gap": round(item["outbound_deadline_miss_rate"]["mean"]
                                      - bound["miss_rate"], 4),
            }
    summary["gap_to_lower_bound"] = gaps

    (DATA / "stats_research.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# 研究增强实验统计", "", "## QEDF vs EDF（配对，20 种子）", "",
             "| 场景 | 指标 | 均值差 [95% CI] | t p | Wilcoxon p | Cohen's d |",
             "|---|---|---|---|---|---|"]
    for item in summary["dependent_pairs"]:
        lines.append(
            f"| {item['scenario']} | {item['metric']} | "
            f"{item['mean_diff']:+.4f} [{item['ci95_diff'][0]:+.4f}, {item['ci95_diff'][1]:+.4f}] | "
            f"{item['t_p']} | {item['wilcoxon_p']} | {item['cohens_d']:+.3f} |")
    lines += ["", "## 相对离线下界的差距（medium/high）", "",
              "| 场景 | 算法 | 等待/(下界) | 逾期率绝对差 |", "|---|---|---|---|"]
    for level in ("medium", "high"):
        for algorithm, values in summary["gap_to_lower_bound"][level].items():
            lines.append(f"| {level} | {algorithm} | {values['wait_ratio']:.2f}× | "
                         f"{values['miss_abs_gap']:+.3f} |")
    (DATA / "stats_research.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()