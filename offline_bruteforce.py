#!/usr/bin/env python3
"""小规模精确离线基准：在依赖可行的车辆顺序空间中穷举，求最小总逾期。

规模：6 辆（3 IN / 3 OUT）、2 个兼容月台；穷举顺序数可控。
与在线策略（EDF/AQEDF/SPT/RH-DA）在同一实例上比较总逾期。
"""
from __future__ import annotations

import itertools
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "vendor" / "dockflow"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent / "research"))

import simulation.engine as engine_module  # noqa: E402
from simulation import run_simulation  # noqa: E402
from simulation.competition import make_docks  # noqa: E402
from simulation.generator import generate_scenario  # noqa: E402
import qedf  # noqa: E402

qedf.install(engine_module)


def compatible(truck, dock):
    allowed = truck.get("allowed_dock_ids")
    return dock["mode"] in (truck["direction"], "FLEX") and (
        allowed is None or dock["dock_id"] in allowed
    )


def evaluate(order: list[dict], scene: dict) -> float:
    approach = scene["approach_duration"]
    exit_time = scene["exit_duration"]
    dock_free = {d["dock_id"]: 0.0 for d in scene["docks"]}
    finish_in: dict[str, float] = {}
    total = 0.0
    for truck in order:
        tid = truck["truck_id"]
        if truck["direction"] == "OUT":
            ready = max([truck["arrival_time"]]
                        + [finish_in[d] for d in truck["depends_on"] if d in finish_in])
        else:
            ready = truck["arrival_time"]
        options = [d["dock_id"] for d in scene["docks"] if compatible(truck, d)]
        if not options:
            return float("inf")
        dock_id = min(options, key=lambda d: dock_free[d])
        start = max(ready, dock_free[dock_id])
        finish = start + approach + truck["service_duration"]
        dock_free[dock_id] = finish + exit_time
        if truck["direction"] == "IN":
            finish_in[tid] = finish
        else:
            departure = finish + exit_time
            total += max(0.0, departure - truck["departure_deadline"])
    return total


def feasible(order: list[dict]) -> bool:
    seen: set[str] = set()
    for truck in order:
        if truck["direction"] == "OUT":
            if any(dep not in seen for dep in truck["depends_on"]):
                return False
        seen.add(truck["truck_id"])
    return True


def offline_optimum(scene: dict) -> float:
    best = float("inf")
    count = 0
    for order in itertools.permutations(scene["trucks"]):
        if not feasible(order):
            continue
        count += 1
        best = min(best, evaluate(order, scene))
    return round(best, 3), count


def total_tardiness(result: dict) -> float:
    total = 0.0
    for truck in result["trucks"]:
        if truck["direction"] != "OUT" or truck["departure_time"] is None:
            continue
        deadline = truck.get("departure_deadline")
        if deadline is None:
            continue
        total += max(0.0, float(truck["departure_time"]) - float(deadline))
    return round(total, 3)


def run_scale(inbound: int, outbound: int, out_name: str) -> list[dict]:
    rows = []
    for seed in (300, 301, 302, 303, 304):
        scene = generate_scenario({
            "scenario_preset": "normal", "random_seed": seed,
            "inbound_count": inbound, "outbound_count": outbound,
            "dependency_ratio": 1.0, "arrival_horizon": 30.0,
            "docks": make_docks(2),
        })
        optimum, count = offline_optimum(scene)
        online = {a: total_tardiness(run_simulation(scene, a))
                  for a in ("edf", "aqedf", "spt", "rh_da")}
        rows.append({"seed": seed, "feasible_orders": count,
                     "offline_optimum": optimum, "online": online})
        print(f"{inbound}/{outbound} seed {seed}: orders={count} optimum={optimum:.2f} | " +
              " ".join(f"{k}={v:.2f}" for k, v in online.items()))

    out = Path(__file__).resolve().parent / "data" / "research" / out_name
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{inbound}/{outbound} 平均总逾期：")
    for algorithm in ("edf", "aqedf", "spt", "rh_da"):
        print(f"  {algorithm:8s} {statistics.mean(r['online'][algorithm] for r in rows):.3f}")
    print(f"  离线最优   {statistics.mean(r['offline_optimum'] for r in rows):.3f}")
    return rows


def main() -> None:
    run_scale(3, 3, "offline_bruteforce.json")
    run_scale(4, 4, "offline_bruteforce_8.json")

if __name__ == "__main__":
    main()