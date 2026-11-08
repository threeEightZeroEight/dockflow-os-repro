#!/usr/bin/env python3
"""自适应 QEDF 正式实验：三种负载、依赖扫描、120/160 辆规模。"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "vendor" / "dockflow"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent / "research"))

import simulation.engine as engine_module  # noqa: E402
from simulation import run_simulation  # noqa: E402
from simulation.competition import generate_competition_scenario, make_docks  # noqa: E402
from simulation.generator import generate_scenario  # noqa: E402
import qedf  # noqa: E402

qedf.install(engine_module)

OUT_DIR = Path(__file__).resolve().parent / "data" / "research"
ALGORITHMS = ["edf", "qedf", "aqedf"]
METRICS = [
    "avg_waiting_time", "p95_waiting_time", "max_waiting_time",
    "outbound_deadline_miss_rate", "throughput", "dock_utilization",
]


def flat(metrics: dict) -> dict:
    row = {m: metrics.get(m) for m in METRICS}
    cost = metrics.get("decision_cost") or {}
    row["decision_avg_ms"] = cost.get("avg_ms")
    return row


def write_csv(name: str, rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  -> {path.relative_to(REPO_ROOT)} ({len(rows)} 行)")


def main() -> None:
    seeds = list(range(42, 62))
    started = time.time()
    rows: list[dict] = []

    print("[rq_adaptive] low/medium/high × 20 种子")
    for level in ("low", "medium", "high"):
        for seed in seeds:
            scenario = generate_competition_scenario(level, seed)
            for algorithm in ALGORITHMS:
                row = {"experiment": "rq_adaptive", "scenario": level,
                       "seed": seed, "algorithm": algorithm}
                row.update(flat(run_simulation(scenario, algorithm)["metrics"]))
                rows.append(row)

    print("[rq_adaptive_dependency] 依赖扫描 × 20 种子")
    for ratio in (0.0, 0.2, 0.4, 0.6, 0.8):
        for seed in seeds:
            scenario = generate_scenario({
                "scenario_preset": "normal", "random_seed": seed,
                "inbound_count": 30, "outbound_count": 30,
                "dependency_ratio": ratio, "arrival_horizon": 90.0,
                "docks": make_docks(5),
            })
            for algorithm in ALGORITHMS:
                row = {"experiment": "rq_adaptive_dependency",
                       "scenario": f"dep{ratio}", "seed": seed,
                       "algorithm": algorithm}
                row.update(flat(run_simulation(scenario, algorithm)["metrics"]))
                rows.append(row)

    print("[rq_adaptive_large] 120/160 辆 × 10 种子")
    for total in (120, 160):
        for seed in seeds[:10]:
            scenario = generate_scenario({
                "scenario_preset": "normal", "random_seed": seed,
                "inbound_count": total // 2, "outbound_count": total // 2,
                "dependency_ratio": 0.5, "arrival_horizon": 120.0,
                "docks": make_docks(5),
            })
            for algorithm in ALGORITHMS:
                row = {"experiment": "rq_adaptive_large",
                       "scenario": f"n{total}", "seed": seed,
                       "algorithm": algorithm}
                row.update(flat(run_simulation(scenario, algorithm)["metrics"]))
                rows.append(row)

    write_csv("rq_adaptive.csv", rows)
    print(f"\n完成，耗时 {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()