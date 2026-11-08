#!/usr/bin/env python3
"""汇总实验数据：多种子均值、最小值、最大值、标准差，输出 JSON + Markdown 表。"""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

ALGORITHMS = ["fcfs", "spt", "edf", "edf_aging", "dependency_aware", "joint_da", "rh_da"]
METRICS = [
    "avg_waiting_time", "p95_waiting_time", "max_waiting_time",
    "outbound_deadline_miss_rate", "throughput", "dock_utilization",
    "long_wait_task_ratio", "decision_avg_ms", "decision_max_ms",
    "uncompleted_count",
]


def load(name: str) -> list[dict]:
    with (DATA_DIR / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _num(value: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def aggregate(rows: list[dict], group_keys: tuple[str, ...]) -> dict:
    buckets: dict[tuple, list[dict]] = {}
    for row in rows:
        key = tuple(row[k] for k in group_keys)
        buckets.setdefault(key, []).append(row)
    result: dict = {}
    for key, group in buckets.items():
        node: dict = {}
        for metric in METRICS:
            values = [v for v in (_num(r.get(metric)) for r in group) if v is not None]
            if not values:
                node[metric] = None
                continue
            node[metric] = {
                "mean": round(statistics.mean(values), 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
                "n": len(values),
            }
        cursor = result
        for part in key[:-1]:
            cursor = cursor.setdefault(str(part), {})
        cursor[str(key[-1])] = node
    return result


def waiting_distribution() -> dict:
    rows = load("e6_waiting_distribution.csv")
    out: dict = {}
    for algorithm in sorted({r["algorithm"] for r in rows}):
        subset = [r for r in rows if r["algorithm"] == algorithm]
        waits = sorted(
            (float(r["waiting_time"]) for r in subset
             if r["waiting_time"] not in ("", None)),
            reverse=True,
        )
        completed = sum(1 for r in subset if r["status"] == "DEPARTED")
        out[algorithm] = {
            "vehicles": len(subset),
            "completed": completed,
            "max_waiting": round(waits[0], 4) if waits else None,
            "top5": [round(v, 4) for v in waits[:5]],
            "median": round(statistics.median(waits), 4) if waits else None,
        }
    return out


def markdown_table(e1: dict) -> str:
    header = ("| 算法 | 平均等待 | P95 | 最大等待 | 逾期率 | 吞吐量 | 利用率 | "
              "长等待占比 | 调度耗时ms |")
    lines = [header, "|---|---|---|---|---|---|---|---|---|"]
    for algorithm in ALGORITHMS:
        node = e1.get(algorithm)
        if not node:
            continue
        def cell(metric: str) -> str:
            item = node.get(metric)
            if not item:
                return "—"
            return f"{item['mean']:.3f} ({item['min']:.2f}–{item['max']:.2f})"
        lines.append(
            f"| {algorithm} | {cell('avg_waiting_time')} | {cell('p95_waiting_time')} | "
            f"{cell('max_waiting_time')} | {cell('outbound_deadline_miss_rate')} | "
            f"{cell('throughput')} | {cell('dock_utilization')} | "
            f"{cell('long_wait_task_ratio')} | {cell('decision_avg_ms')} |"
        )
    return "\n".join(lines)


def main() -> None:
    e1 = aggregate(load("e1_algorithm_baseline.csv"), ("algorithm",))
    e2 = aggregate(load("e2_dependency_sweep.csv"), ("parameter_value", "algorithm"))
    e3 = aggregate(load("e3_dock_sweep.csv"), ("parameter_value", "algorithm"))
    e4 = aggregate(load("e4_aging_sweep.csv"), ("aging_threshold", "algorithm"))
    e6 = waiting_distribution()

    seeds = sorted({r["seed"] for r in load("e1_algorithm_baseline.csv")})
    payload = {
        "meta": {
            "seeds": seeds,
            "baseline_scenario": "medium: 30 IN / 30 OUT / 5 docks / dependency 0.5",
            "metric_note": "每个单元格为多种子 mean (min–max)",
        },
        "e1_algorithm_baseline": e1,
        "e2_dependency_sweep": e2,
        "e3_dock_sweep": e3,
        "e4_aging_sweep": e4,
        "e6_waiting_distribution": e6,
    }
    out = DATA_DIR / "summary.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# 实验数据汇总（多种子）", "", f"- 种子：{seeds}",
          "- 基线场景：medium（30 入站 / 30 出站 / 5 月台 / 依赖 0.5）",
          "- 单元格格式：均值 (最小值–最大值)", "",
          "## E1 七算法基线", "", markdown_table(e1), ""]
    (DATA_DIR / "summary.md").write_text("\n".join(md), encoding="utf-8")

    print("已生成 summary.json / summary.md")
    print(markdown_table(e1))


if __name__ == "__main__":
    main()