#!/usr/bin/env python3
"""DockFlow 操作系统实验报告 · 数据采集脚本（选题一 + 选题二融合）

用法：
    python docs/os-report/collect_experiments.py --quick
    python docs/os-report/collect_experiments.py --seeds 42,43,44

输出：docs/os-report/data/*.csv 与 *.json
全部调用真实仿真（simulation 层），不使用任何 Mock / 预置结果。
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "vendor" / "dockflow"))
sys.path.insert(0, str(REPO_ROOT))

from simulation import run_experiment, run_simulation  # noqa: E402
from simulation.competition import (  # noqa: E402
    ALGORITHMS,
    generate_competition_scenario,
)
from simulation.models import ScenarioValidationError, validate_scenario  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent / "data"

METRIC_FIELDS = [
    "truck_count", "completed_count", "uncompleted_count",
    "avg_waiting_time", "p95_waiting_time", "max_waiting_time",
    "outbound_deadline_miss_rate", "throughput", "dock_utilization",
    "long_wait_task_ratio",
]


def _flat_metrics(metrics: dict) -> dict:
    row = {field: metrics.get(field) for field in METRIC_FIELDS}
    by_dir = metrics.get("by_direction") or {}
    for direction in ("IN", "OUT"):
        sub = by_dir.get(direction) or {}
        row[f"{direction}_avg_waiting"] = sub.get("avg_waiting_time")
        row[f"{direction}_p95_waiting"] = sub.get("p95_waiting_time")
        row[f"{direction}_max_waiting"] = sub.get("max_waiting_time")
        row[f"{direction}_miss_rate"] = sub.get("outbound_deadline_miss_rate")
    cost = metrics.get("decision_cost") or {}
    row["decision_count"] = cost.get("count")
    row["decision_avg_ms"] = cost.get("avg_ms")
    row["decision_max_ms"] = cost.get("max_ms")
    return row


def write_csv(name: str, rows: list[dict]) -> Path:
    path = DATA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    print(f"  -> {path.relative_to(REPO_ROOT)} ({len(rows)} 行)")
    return path


def write_json(name: str, payload: dict) -> Path:
    path = DATA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> {path.relative_to(REPO_ROOT)}")
    return path


def e1_algorithm_baseline(seeds: list[int]) -> None:
    """固定 medium 场景（30 IN / 30 OUT / 5 月台 / 依赖 0.5），七算法对照。"""
    print("[E1] 七算法基线对照")
    rows = []
    for seed in seeds:
        scenario = generate_competition_scenario("medium", seed)
        for algorithm in ALGORITHMS:
            result = run_simulation(scenario, algorithm)
            row = {
                "experiment": "e1_algorithm_baseline",
                "seed": seed,
                "algorithm": algorithm,
                "inbound": 30,
                "outbound": 30,
                "dock_count": len(scenario["docks"]),
                "dependency_ratio": 0.5,
            }
            row.update(_flat_metrics(result["metrics"]))
            rows.append(row)
    write_csv("e1_algorithm_baseline.csv", rows)


def _sweep(experiment: str, vary: str, values: list, seeds: list[int],
           filename: str) -> None:
    print(f"[{experiment}] {vary} 扫描 values={values} seeds={seeds}")
    config = {
        "competition_level": "medium",
        "vary_parameter": vary,
        "parameter_values": values,
        "seeds": seeds,
        "algorithms": list(ALGORITHMS),
    }
    started = time.time()
    outcome = run_experiment(config)
    rows = []
    for run in outcome["runs"]:
        row = {
            "experiment": experiment,
            "seed": run["seed"],
            "algorithm": run["algorithm"],
            "parameter_value": run["parameter_value"],
        }
        row.update(_flat_metrics(run["result"]["metrics"]))
        rows.append(row)
    write_csv(filename, rows)
    write_json(filename.replace(".csv", "_series.json"),
               {"config": outcome["config"], "series": outcome["series"]})
    print(f"  (耗时 {time.time() - started:.1f}s)")


def e2_dependency_sweep(seeds: list[int], values: list) -> None:
    _sweep("e2_dependency_sweep", "dependency_ratio", values, seeds,
           "e2_dependency_sweep.csv")


def e3_dock_sweep(seeds: list[int], values: list) -> None:
    _sweep("e3_dock_sweep", "dock_count", values, seeds, "e3_dock_sweep.csv")


def e4_aging_sweep(seeds: list[int], thresholds: list) -> None:
    """EDF vs EDF+Aging 在不同老化阈值下的饥饿与效率。"""
    print(f"[E4] aging_threshold 扫描 thresholds={thresholds}")
    rows = []
    for seed in seeds:
        scenario = generate_competition_scenario("medium", seed)
        for threshold in thresholds:
            for algorithm in ("edf", "edf_aging"):
                result = run_simulation(
                    scenario, algorithm, {"aging_threshold": float(threshold)}
                )
                row = {
                    "experiment": "e4_aging_sweep",
                    "seed": seed,
                    "algorithm": algorithm,
                    "aging_threshold": threshold,
                }
                row.update(_flat_metrics(result["metrics"]))
                rows.append(row)
    write_csv("e4_aging_sweep.csv", rows)


def e5_deadlock_prevention() -> None:
    """验证死锁预防：非法依赖边在输入校验阶段被静态拒绝。"""
    print("[E5] 死锁预防（非法依赖输入校验）")
    base = generate_competition_scenario("medium", 42)
    inbound = next(t for t in base["trucks"] if t["direction"] == "IN")
    outbound = next(t for t in base["trucks"] if t["direction"] == "OUT")

    cases: list[tuple[str, dict]] = []

    reverse_edge = copy.deepcopy(base)
    target_in = next(
        t for t in reverse_edge["trucks"]
        if t["truck_id"] == inbound["truck_id"]
    )
    target_in["depends_on"] = [outbound["truck_id"]]
    cases.append(("IN_depends_on_OUT_reverse_edge", reverse_edge))

    self_loop = copy.deepcopy(base)
    target_out = next(
        t for t in self_loop["trucks"]
        if t["truck_id"] == outbound["truck_id"]
    )
    target_out["depends_on"] = [outbound["truck_id"]]
    cases.append(("OUT_depends_on_itself", self_loop))

    missing = copy.deepcopy(base)
    target_out = next(
        t for t in missing["trucks"]
        if t["truck_id"] == outbound["truck_id"]
    )
    target_out["depends_on"] = ["I999"]
    cases.append(("depends_on_missing_truck", missing))

    duplicate = copy.deepcopy(base)
    target_out = next(
        t for t in duplicate["trucks"]
        if t["truck_id"] == outbound["truck_id"]
    )
    target_out["depends_on"] = [inbound["truck_id"], inbound["truck_id"]]
    cases.append(("duplicate_dependency", duplicate))

    unreachable = copy.deepcopy(base)
    target_in_dock = next(
        t for t in unreachable["trucks"]
        if t["truck_id"] == inbound["truck_id"]
    )
    target_in_dock["allowed_dock_ids"] = ["D02"]
    cases.append(("no_compatible_dock", unreachable))

    rows = []
    for name, scenario in cases:
        try:
            validate_scenario(scenario)
            accepted, message = True, ""
        except ScenarioValidationError as exc:
            accepted, message = False, str(exc)
        rows.append({
            "case": name,
            "accepted": accepted,
            "expected": False,
            "message": message,
        })
        status = "误接受" if accepted else "已拒绝"
        print(f"  - {name}: {status} | {message}")

    write_csv("e5_deadlock_prevention.csv", rows)


def e6_waiting_distribution(seeds: list[int], algorithms: list[str]) -> None:
    """每辆车的等待分布，用于分析饥饿（长尾）与完成率。"""
    print(f"[E6] 等待分布（algorithm={algorithms}）")
    rows = []
    for seed in seeds:
        scenario = generate_competition_scenario("medium", seed)
        for algorithm in algorithms:
            result = run_simulation(scenario, algorithm)
            for truck in result["trucks"]:
                rows.append({
                    "experiment": "e6_waiting_distribution",
                    "seed": seed,
                    "algorithm": algorithm,
                    "truck_id": truck["truck_id"],
                    "direction": truck["direction"],
                    "status": truck["status"],
                    "waiting_time": truck["waiting_time"],
                    "ready_waiting_time": truck["ready_waiting_time"],
                    "deadline_missed": truck["deadline_missed"],
                })
    write_csv("e6_waiting_distribution.csv", rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="DockFlow OS 实验数据采集")
    parser.add_argument("--seeds", default="42", help="逗号分隔的随机种子")
    parser.add_argument("--quick", action="store_true", help="快速模式（用于脚本自检）")
    parser.add_argument("--only", default="", help="只跑指定实验，如 e1,e2")
    args = parser.parse_args()

    seeds = [int(item) for item in args.seeds.split(",") if item.strip()]
    if not seeds:
        parser.error("至少需要一个随机种子")

    dependency_values = [0.0, 0.4, 0.8] if args.quick else [0.0, 0.2, 0.4, 0.6, 0.8]
    dock_values = [3, 5, 8] if args.quick else [2, 3, 4, 6, 8]
    aging_values = [2, 12, 30] if args.quick else [2, 6, 12, 20, 30]

    selected = {item.strip() for item in args.only.split(",") if item.strip()}
    run_all = not selected

    started = time.time()
    if run_all or "e1" in selected:
        e1_algorithm_baseline(seeds)
    if run_all or "e2" in selected:
        e2_dependency_sweep(seeds, dependency_values)
    if run_all or "e3" in selected:
        e3_dock_sweep(seeds, dock_values)
    if run_all or "e4" in selected:
        e4_aging_sweep(seeds, aging_values)
    if run_all or "e5" in selected:
        e5_deadlock_prevention()
    if run_all or "e6" in selected:
        e6_waiting_distribution(seeds, ["fcfs", "spt", "edf_aging", "joint_da"])

    print(f"\n全部完成，总耗时 {time.time() - started:.1f}s")
    print(f"数据目录：{DATA_DIR.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()