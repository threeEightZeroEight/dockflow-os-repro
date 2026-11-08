#!/usr/bin/env python3
"""扩展实验：多场景、20 种子、规模扫描、DA 权重消融。

输出 docs/os-report/data/extended/*.csv
用法：python docs/os-report/collect_extended.py [--quick]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "vendor" / "dockflow"))
sys.path.insert(0, str(REPO_ROOT))

from simulation import run_simulation  # noqa: E402
from simulation.competition import (  # noqa: E402
    ALGORITHMS,
    generate_competition_scenario,
    make_docks,
)
from simulation.generator import generate_scenario  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "data" / "extended"

METRIC_FIELDS = [
    "truck_count", "completed_count", "uncompleted_count",
    "avg_waiting_time", "p95_waiting_time", "max_waiting_time",
    "outbound_deadline_miss_rate", "throughput", "dock_utilization",
    "long_wait_task_ratio",
]


def flat(metrics: dict) -> dict:
    row = {field: metrics.get(field) for field in METRIC_FIELDS}
    by_dir = metrics.get("by_direction") or {}
    for direction in ("IN", "OUT"):
        sub = by_dir.get(direction) or {}
        row[f"{direction}_avg_waiting"] = sub.get("avg_waiting_time")
    cost = metrics.get("decision_cost") or {}
    row["decision_avg_ms"] = cost.get("avg_ms")
    row["decision_max_ms"] = cost.get("max_ms")
    return row


def write_csv(name: str, rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  -> {path.relative_to(REPO_ROOT)} ({len(rows)} 行)")


def run_block(name: str, cases: list[tuple[str, int, dict]],
              algorithms: list[str], settings: dict | None = None,
              extra: dict | None = None) -> None:
    print(f"[{name}] {len(cases)} 场景 x {len(algorithms)} 算法")
    started = time.time()
    rows = []
    for label, seed, scenario in cases:
        for algorithm in algorithms:
            result = run_simulation(scenario, algorithm, settings)
            row = {"experiment": name, "scenario": label, "seed": seed,
                   "algorithm": algorithm}
            row.update(flat(result["metrics"]))
            if extra:
                row.update(extra)
            rows.append(row)
    write_csv(f"{name}.csv", rows)
    print(f"  (耗时 {time.time() - started:.1f}s)")


def medium(seed: int, *, dependency_ratio: float | None = None,
           dock_count: int = 5, total: int = 60) -> dict:
    config = {
        "scenario_preset": "normal",
        "random_seed": seed,
        "inbound_count": total // 2,
        "outbound_count": total // 2,
        "dependency_ratio": 0.5 if dependency_ratio is None else dependency_ratio,
        "arrival_horizon": 90.0,
        "docks": make_docks(dock_count),
    }
    return generate_scenario(config)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    seeds = list(range(42, 45)) if args.quick else list(range(42, 62))
    algorithms = list(ALGORITHMS)

    # EA: 三种竞争强度（low/medium/high）
    cases = []
    for level in ("low", "medium", "high"):
        for seed in seeds:
            cases.append((level, seed, generate_competition_scenario(level, seed)))
    run_block("ea_multi_scenario", cases, algorithms)

    # EB: Mendeley 冻结研究场景（确定性，无随机种子）
    mendeley = json.loads(
        (REPO_ROOT / "vendor" / "dockflow" / "scenario_21.json").read_text(encoding="utf-8")
    )
    run_block("eb_mendeley", [("mendeley-ch5", 0, mendeley)], algorithms)

    # EC: 规模扫描（车辆总数 20/40/60/80）
    scale_seeds = seeds[:10]
    cases = []
    for total in (20, 40, 60, 80):
        for seed in scale_seeds:
            cases.append((f"n{total}", seed, medium(seed, total=total)))
    run_block("ec_scale", cases, algorithms)

    # ED: 依赖比例扫描
    cases = []
    for ratio in (0.0, 0.2, 0.4, 0.6, 0.8):
        for seed in seeds:
            cases.append((f"dep{ratio}", seed, medium(seed, dependency_ratio=ratio)))
    run_block("ed_dependency", cases, algorithms)

    # EE: 月台数扫描
    cases = []
    for dock_count in (2, 3, 4, 6, 8):
        for seed in seeds:
            cases.append((f"docks{dock_count}", seed, medium(seed, dock_count=dock_count)))
    run_block("ee_docks", cases, algorithms)

    # EF: 老化阈值（仅 edf / edf_aging）
    cases = []
    for threshold in (2, 6, 12, 20, 30):
        for seed in seeds:
            cases.append((f"aging{threshold}", seed, medium(seed)))
    run_block("ef_aging", cases, ["edf", "edf_aging"])

    # EG: DA 权重消融（其余权重保持默认）
    base = medium(42)
    weight_sets = {
        "full": {},
        "no_unlock(I=0)": {"da_immediate_weight": 0},
        "no_blocked(B=0)": {"da_blocked_weight": 0},
        "no_resource(R=0)": {"da_resource_weight": 0},
        "no_traffic(P=0)": {"da_traffic_weight": 0},
        "no_wait(W=0)": {"da_wait_weight": 0},
    }
    print(f"[eg_ablation] {len(weight_sets)} 配置 x {len(seeds)} 种子")
    ablation_rows = []
    for label, overrides in weight_sets.items():
        for seed in seeds:
            scenario = medium(seed)
            result = run_simulation(scenario, "dependency_aware", overrides)
            row = {"experiment": "eg_ablation", "scenario": label, "seed": seed,
                   "algorithm": "dependency_aware", "variant": label}
            row.update(flat(result["metrics"]))
            ablation_rows.append(row)
    write_csv("eg_ablation.csv", ablation_rows)
    high_ablation(seeds)


def high_ablation(seeds: list[int]) -> None:
    weight_sets = {
        "full": {},
        "no_unlock(I=0)": {"da_immediate_weight": 0},
        "no_blocked(B=0)": {"da_blocked_weight": 0},
        "no_resource(R=0)": {"da_resource_weight": 0},
        "no_traffic(P=0)": {"da_traffic_weight": 0},
        "no_wait(W=0)": {"da_wait_weight": 0},
    }
    print(f"[eg_ablation_high] {len(weight_sets)} 配置 x {len(seeds)} 种子")
    rows = []
    for seed in seeds:
        scene = generate_competition_scenario("high", seed)
        for label, overrides in weight_sets.items():
            metrics = run_simulation(scene, "dependency_aware", overrides)["metrics"]
            rows.append({
                "scenario": label, "seed": seed,
                "outbound_deadline_miss_rate": metrics["outbound_deadline_miss_rate"],
                "avg_waiting_time": metrics["avg_waiting_time"],
                "max_waiting_time": metrics["max_waiting_time"],
                "throughput": metrics["throughput"],
                "long_wait_task_ratio": metrics["long_wait_task_ratio"],
            })
    write_csv("eg_ablation_high.csv", rows)


if __name__ == "__main__":
    main()