#!/usr/bin/env python3
"""重建未由主采集脚本直接生成的派生数据：真实切片、统一规模表、公平性指标。"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "vendor" / "dockflow"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "research"))

import simulation.engine as engine_module  # noqa: E402
from simulation import run_simulation  # noqa: E402
from simulation.competition import generate_competition_scenario, make_docks  # noqa: E402
from simulation.generator import generate_scenario  # noqa: E402
import qedf  # noqa: E402

qedf.install(engine_module)

DATA = REPO_ROOT / "data"
RESEARCH = DATA / "research"
SLICES = REPO_ROOT / "research" / "slices"
ALGORITHMS8 = ["fcfs", "spt", "edf", "edf_aging",
               "dependency_aware", "joint_da", "rh_da", "aqedf"]
ALGORITHMS4 = ["fcfs", "spt", "edf", "aqedf"]
SLICE_ORDER = ["early", "middle", "late"]


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print("  ->", path.relative_to(REPO_ROOT), len(rows), "行")


def real_slices() -> None:
    print("[real_slices] 3 个切片 x 8 算法")
    rows = []
    for name in SLICE_ORDER:
        scene = json.loads((SLICES / f"slice_{name}.json").read_text(encoding="utf-8"))
        for algorithm in ALGORITHMS8:
            metrics = run_simulation(scene, algorithm)["metrics"]
            rows.append({
                "slice": name, "algorithm": algorithm,
                "avg_waiting_time": metrics["avg_waiting_time"],
                "p95_waiting_time": metrics["p95_waiting_time"],
                "max_waiting_time": metrics["max_waiting_time"],
                "outbound_deadline_miss_rate": metrics["outbound_deadline_miss_rate"],
                "throughput": metrics["throughput"],
                "dock_utilization": metrics["dock_utilization"],
            })
    write_csv(RESEARCH / "real_slices.csv", rows)


def scale_unified() -> None:
    print("[scale_unified] 重建 20-80 规模并合并 120/160")
    rows = []
    for total in (20, 40, 60, 80):
        for seed in range(42, 52):
            scene = big(total, seed)
            for algorithm in ALGORITHMS4:
                metrics = run_simulation(scene, algorithm)["metrics"]
                rows.append({
                    "total": total, "seed": seed, "algorithm": algorithm,
                    "avg_waiting_time": metrics["avg_waiting_time"],
                    "throughput": metrics["throughput"],
                    "outbound_deadline_miss_rate": metrics["outbound_deadline_miss_rate"],
                })
    with (RESEARCH / "rq_large_scale.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["algorithm"] not in ("fcfs", "spt", "edf"):
                continue
            rows.append({
                "total": int(row["scenario"].lstrip("n")), "seed": int(row["seed"]),
                "algorithm": row["algorithm"],
                "avg_waiting_time": float(row["avg_waiting_time"]),
                "throughput": float(row["throughput"]),
                "outbound_deadline_miss_rate": float(row["outbound_deadline_miss_rate"]),
            })
    with (RESEARCH / "rq_adaptive.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["scenario"] not in ("n120", "n160") or row["algorithm"] != "aqedf":
                continue
            rows.append({
                "total": int(row["scenario"].lstrip("n")), "seed": int(row["seed"]),
                "algorithm": "aqedf",
                "avg_waiting_time": float(row["avg_waiting_time"]),
                "throughput": float(row["throughput"]),
                "outbound_deadline_miss_rate": float(row["outbound_deadline_miss_rate"]),
            })
    rows.sort(key=lambda r: (r["total"], r["seed"], ALGORITHMS4.index(r["algorithm"])))
    write_csv(RESEARCH / "scale_unified.csv", rows)


def big(total: int, seed: int) -> dict:
    return generate_scenario({
        "scenario_preset": "normal", "random_seed": seed,
        "inbound_count": total // 2, "outbound_count": total // 2,
        "dependency_ratio": 0.5, "arrival_horizon": 120.0,
        "docks": make_docks(5),
    })


def validation_fairness() -> None:
    print("[validation_fairness] 重放确认集 60 个实例")
    rows = []
    with (RESEARCH / "validation_report.csv").open(encoding="utf-8") as fh:
        for item in csv.DictReader(fh):
            label, seed = item["scenario"], int(item["seed"])
            scene = (generate_competition_scenario(label, seed)
                     if label in ("medium", "high") else big(int(label.lstrip("n")), seed))
            for algorithm in ("edf", "aqedf"):
                metrics = run_simulation(scene, algorithm)["metrics"]
                cost = metrics.get("decision_cost") or {}
                rows.append({
                    "scenario": label, "seed": seed, "algorithm": algorithm,
                    "miss": metrics["outbound_deadline_miss_rate"],
                    "avg_wait": metrics["avg_waiting_time"],
                    "p95_wait": metrics["p95_waiting_time"],
                    "max_wait": metrics["max_waiting_time"],
                    "long_wait_ratio": metrics["long_wait_task_ratio"],
                    "decision_ms": cost.get("avg_ms"),
                })
    write_csv(RESEARCH / "validation_fairness.csv", rows)


def main() -> None:
    real_slices()
    scale_unified()
    validation_fairness()


if __name__ == "__main__":
    main()