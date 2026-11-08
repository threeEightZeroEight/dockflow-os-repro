#!/usr/bin/env python3
"""小规模 CP-SAT 离线最优（总逾期最小）与在线策略对比。

CP-SAT 使用全信息，只用于给出离线参照，不作为在线算法。
"""
from __future__ import annotations

import json
import math
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
from ortools.sat.python import cp_model  # noqa: E402

qedf.install(engine_module)

SCALE = 10  # 0.1 minute resolution


def compatible(truck, dock):
    allowed = truck.get("allowed_dock_ids")
    return dock["mode"] in (truck["direction"], "FLEX") and (
        allowed is None or dock["dock_id"] in allowed
    )


def solve_offline(scene: dict, time_limit: float = 20.0) -> dict:
    a = int(round(scene["approach_duration"] * SCALE))
    e = int(round(scene["exit_duration"] * SCALE))
    horizon = int(round(scene["max_simulation_time"] * SCALE))
    trucks = scene["trucks"]
    by_id = {t["truck_id"]: t for t in trucks}

    model = cp_model.CpModel()
    start = {t["truck_id"]: model.NewIntVar(0, horizon, f"s_{t['truck_id']}") for t in trucks}
    occupancy = int(round(max(t["service_duration"] for t in trucks) * SCALE)) + a + e

    intervals = {d["dock_id"]: [] for d in scene["docks"]}
    for truck in trucks:
        tid = truck["truck_id"]
        options = [d for d in scene["docks"] if compatible(truck, d)]
        presence = []
        for dock in options:
            p = model.NewBoolVar(f"p_{tid}_{dock['dock_id']}")
            presence.append(p)
            intervals[dock["dock_id"]].append(
                model.NewOptionalIntervalVar(
                    start[tid], occupancy, model.NewIntVar(0, horizon, f"e_{tid}_{dock['dock_id']}"),
                    p, f"iv_{tid}_{dock['dock_id']}",
                )
            )
        model.AddExactlyOne(presence)
        model.Add(start[tid] >= int(math.floor(truck["arrival_time"] * SCALE)))

    for dock_id, ivs in intervals.items():
        model.AddNoOverlap(ivs)

    for truck in trucks:
        if truck["direction"] != "OUT":
            continue
        for dep in truck["depends_on"]:
            pred = by_id[dep]
            finish = model.NewIntVar(0, horizon, f"f_{dep}_{truck['truck_id']}")
            model.Add(finish == start[dep] + a + int(round(pred["service_duration"] * SCALE)))
            model.Add(start[truck["truck_id"]] >= finish)

    tardiness = []
    for truck in trucks:
        if truck["direction"] != "OUT":
            continue
        deadline = int(round(truck["departure_deadline"] * SCALE))
        departure = model.NewIntVar(0, horizon * 2, f"d_{truck['truck_id']}")
        model.Add(departure == start[truck["truck_id"]] + a
                  + int(round(truck["service_duration"] * SCALE)) + e)
        late = model.NewIntVar(0, horizon * 2, f"l_{truck['truck_id']}")
        model.Add(late >= departure - deadline)
        tardiness.append(late)
    model.Minimize(sum(tardiness))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": name, "objective_minutes": None, "bound": None}
    objective = solver.ObjectiveValue() / SCALE
    bound = solver.BestObjectiveBound() / SCALE
    return {"status": name, "objective_minutes": round(objective, 3),
            "bound": round(bound, 3)}


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


def main() -> None:
    rows = []
    for seed in (300, 301, 302, 303, 304):
        scene = generate_scenario({
            "scenario_preset": "normal", "random_seed": seed,
            "inbound_count": 10, "outbound_count": 10,
            "dependency_ratio": 0.5, "arrival_horizon": 60.0,
            "docks": make_docks(4),
        })
        offline = solve_offline(scene)
        online = {}
        for algorithm in ("edf", "aqedf", "spt", "rh_da"):
            online[algorithm] = total_tardiness(run_simulation(scene, algorithm))
        rows.append({"seed": seed, "offline": offline, "online": online})
        print(f"seed {seed}: offline={offline} | " +
              " ".join(f"{k}={v:.1f}" for k, v in online.items()))

    out = Path(__file__).resolve().parent / "data" / "research" / "cpsat_offline.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已保存", out)


if __name__ == "__main__":
    main()