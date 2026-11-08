#!/usr/bin/env python3
"""研究增强实验：QEDF 对照、依赖扫描、离线下界、大规规模。

输出 docs/os-report/data/research/*.csv
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "vendor" / "dockflow"))
sys.path.insert(0, str(REPO_ROOT))

import simulation.engine as engine_module  # noqa: E402
from simulation import run_simulation  # noqa: E402
from simulation.competition import (  # noqa: E402
    ALGORITHMS,
    generate_competition_scenario,
    make_docks,
)
from simulation.generator import generate_scenario  # noqa: E402

RESEARCH = Path(__file__).resolve().parent / "research"
sys.path.insert(0, str(Path(__file__).resolve().parent / "research"))
import qedf  # noqa: E402

qedf.install(engine_module)

OUT_DIR = Path(__file__).resolve().parent / "data" / "research"
METRICS = [
    "avg_waiting_time", "p95_waiting_time", "max_waiting_time",
    "outbound_deadline_miss_rate", "throughput", "dock_utilization",
    "long_wait_task_ratio",
]
COMPARISON = ["edf", "qedf", "spt", "dependency_aware", "joint_da", "rh_da"]


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


def run_case(name: str, label: str, seed: int, scenario: dict,
             algorithms: list[str], rows: list[dict]) -> None:
    for algorithm in algorithms:
        result = run_simulation(scenario, algorithm)
        row = {"experiment": name, "scenario": label, "seed": seed,
               "algorithm": algorithm}
        row.update(flat(result["metrics"]))
        rows.append(row)


def main() -> None:
    seeds = list(range(42, 62))
    started = time.time()

    rows: list[dict] = []
    print("[rq_qedf] 三种负载 × 20 种子 × 6 算法")
    for level in ("low", "medium", "high"):
        for seed in seeds:
            run_case("rq_qedf", level, seed,
                     generate_competition_scenario(level, seed), COMPARISON, rows)
    write_csv("rq_qedf.csv", rows)

    rows = []
    print("[rq_dependency] 依赖扫描 × 20 种子 × EDF/QEDF")
    for ratio in (0.0, 0.2, 0.4, 0.6, 0.8):
        for seed in seeds:
            scenario = generate_scenario({
                "scenario_preset": "normal", "random_seed": seed,
                "inbound_count": 30, "outbound_count": 30,
                "dependency_ratio": ratio, "arrival_horizon": 90.0,
                "docks": make_docks(5),
            })
            run_case("rq_dependency", f"dep{ratio}", seed, scenario,
                     ["edf", "qedf"], rows)
    write_csv("rq_dependency.csv", rows)

    rows = []
    print("[rq_lower_bound] 离线下界（容量松弛）")
    for level in ("low", "medium", "high"):
        for seed in seeds:
            scenario = generate_competition_scenario(level, seed)
            bound = qedf.offline_lower_bound(scenario)
            rows.append({"experiment": "rq_lower_bound", "scenario": level,
                         "seed": seed, **bound})
    mendeley = json.loads(
        (REPO_ROOT / "vendor" / "dockflow" / "scenario_21.json").read_text(encoding="utf-8")
    )
    rows.append({"experiment": "rq_lower_bound", "scenario": "benchmark",
                 "seed": 0, **qedf.offline_lower_bound(mendeley)})
    write_csv("rq_lower_bound.csv", rows)

    rows = []
    print("[rq_large_scale] 120/160 辆 × 10 种子")
    for total in (120, 160):
        for seed in seeds[:10]:
            scenario = generate_scenario({
                "scenario_preset": "normal", "random_seed": seed,
                "inbound_count": total // 2, "outbound_count": total // 2,
                "dependency_ratio": 0.5, "arrival_horizon": 120.0,
                "docks": make_docks(5),
            })
            run_case("rq_large_scale", f"n{total}", seed, scenario,
                     [*ALGORITHMS, "qedf"], rows)
    write_csv("rq_large_scale.csv", rows)

    print(f"\n完成，总耗时 {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()