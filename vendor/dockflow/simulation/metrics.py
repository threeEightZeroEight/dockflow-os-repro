"""Metrics derived from baseline runtime facts and observed decision timings.

Wall-clock decision_cost is observational and excluded from reproducibility
comparisons; waiting and completion metrics use simulation time only.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] * (upper - position) + values[upper] * (position - lower)


def _metrics(rows: list[dict], end: float) -> dict:
    completed = [t for t in rows if t["status"] == "DEPARTED"]
    waits = [float(t["waiting_time"]) for t in completed]
    outs = [t for t in rows if t["direction"] == "OUT"]
    return {
        "truck_count": len(rows),
        "completed_count": len(completed),
        "uncompleted_count": len(rows) - len(completed),
        "avg_waiting_time": sum(waits) / len(waits) if waits else None,
        "p95_waiting_time": _percentile(waits, 0.95),
        "max_waiting_time": max(waits) if waits else None,
        "outbound_deadline_miss_rate": (
            sum(bool(t["deadline_missed"]) for t in outs) / len(outs) if outs else None
        ),
        "throughput": len(completed) / end if end else 0.0,
    }


def _decision_metrics(
    truck_rows: list[dict], end: float, settings: dict,
    decision_costs_ms: list[float] | None,
) -> dict:
    """Include accrued ready waits for work still queued at the cutoff."""
    threshold = settings.get("long_wait_threshold", 15.0)
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or threshold < 0):
        raise ValueError("long_wait_threshold must be a nonnegative finite number")
    waits = [
        (row["assigned_time"] if row["assigned_time"] is not None else end)
        - row["ready_since"]
        for row in truck_rows if row["ready_since"] is not None
    ]
    costs = decision_costs_ms or []
    return {
        "long_wait_task_ratio": (sum(wait > threshold for wait in waits) / len(truck_rows)
                                 if truck_rows else None),
        "decision_cost": {
            "count": len(costs),
            "avg_ms": sum(costs) / len(costs) if costs else None,
            "max_ms": max(costs) if costs else None,
        },
    }


def flatten_metrics(metrics: dict, prefix: str = "") -> dict[str, Any]:
    """将嵌套指标字典扁平化为「a.b.c」键的一层字典（CSV 导出用）。"""
    flat: dict[str, Any] = {}
    for key, value in metrics.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten_metrics(value, name + "."))
        else:
            flat[name] = value
    return flat


def export_results_csv(results: list[dict], path: str) -> str:
    """将多个仿真结果（单场景 × 单算法 × 单种子）的全部指标导出为 CSV。

    每行一个结果：scenario_id / algorithm / simulation_mode / 种子等上下文
    + 全部指标（扁平化）；缺失值写为空字符串。
    返回写入的文件路径。
    """
    rows: list[dict] = []
    for result in results:
        settings = result.get("settings", {})
        row: dict[str, Any] = {
            "scenario_id": result.get("scenario_id"),
            "algorithm": result.get("algorithm"),
            "simulation_mode": str(settings.get("simulation_mode", "baseline")),
            "random_seed": settings.get("random_seed"),
            "simulation_end_time": result.get("simulation_end_time"),
        }
        row.update(flatten_metrics(result.get("metrics", {})))
        rows.append(row)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    def _cell(value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, bool):
            return int(value)
        return value

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames,
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _cell(row.get(key)) for key in fieldnames})
    return path


def build_result(
    scenario: dict, algorithm: str, settings: dict,
    end: float, runtime_trucks: dict[str, dict],
    runtime_docks: dict[str, dict], events: list[dict],
    *,
    decision_costs_ms: list[float] | None = None,
) -> dict:
    """Return full contract SimulationResult without rounding raw timestamps."""
    truck_rows = []
    for spec in scenario["trucks"]:
        truck = runtime_trucks[spec["truck_id"]]
        depart = truck["departure_time"]
        deadline = spec["departure_deadline"]
        missed = (
            (depart > deadline if depart is not None else end > deadline)
            if spec["direction"] == "OUT" else None
        )
        assigned, ready, started = (truck[k] for k in ("assigned_time", "ready_since", "start_time"))
        row = {
            "truck_id": spec["truck_id"],
            "direction": spec["direction"],
            "status": truck["status"],
            "arrival_time": spec["arrival_time"],
            "service_duration": spec["service_duration"],
            "departure_deadline": deadline,
            "depends_on": list(spec["depends_on"]),
            "allowed_dock_ids": spec.get("allowed_dock_ids"),
            "ready_since": ready,
            "assigned_time": assigned,
            "start_time": started,
            "finish_time": truck["finish_time"],
            "departure_time": depart,
            "waiting_time": (started - spec["arrival_time"]) if started is not None else None,
            "ready_waiting_time": (assigned - ready) if assigned is not None and ready is not None else None,
            "blocked_duration": (ready - spec["arrival_time"]) if ready is not None else None,
            "dock_id": truck["dock_id"],
            "deadline_missed": missed,
        }
        if "pallet_ids" in spec:
            row["pallet_ids"] = list(spec["pallet_ids"])
        truck_rows.append(row)

    dock_rows = []
    for spec in scenario["docks"]:
        dock = runtime_docks[spec["dock_id"]]
        occupied = dock["busy_time"]
        if dock["assigned_time"] is not None:
            occupied += max(0.0, end - dock["assigned_time"])
        dock_rows.append({
            "dock_id": spec["dock_id"], "mode": spec["mode"],
            "slot_index": spec["slot_index"], "status": dock["status"],
            "truck_id": dock["truck_id"],
            "busy_time": occupied, "utilization": occupied / end if end else 0.0,
        })

    metrics = _metrics(truck_rows, end)
    metrics["dock_utilization"] = (
        sum(dock["busy_time"] for dock in dock_rows) / (len(dock_rows) * end)
        if end else 0.0
    )
    metrics["by_direction"] = {
        direction: _metrics([r for r in truck_rows if r["direction"] == direction], end)
        for direction in ("IN", "OUT")
    }
    if "pallets" in scenario:
        metrics["pallet_count"] = len(scenario["pallets"])
        metrics["assigned_pallet_count"] = sum(
            p["outbound_truck_id"] is not None for p in scenario["pallets"]
        )
        metrics["unassigned_pallet_count"] = (
            metrics["pallet_count"] - metrics["assigned_pallet_count"]
        )

    metrics.update(_decision_metrics(truck_rows, end, settings, decision_costs_ms))

    return {
        "schema_version": scenario["schema_version"],
        "scenario_id": scenario["scenario_id"],
        "algorithm": algorithm,
        "settings": dict(settings),
        "simulation_end_time": end,
        "metrics": metrics,
        "trucks": truck_rows,
        "docks": dock_rows,
        "events": events,
    }
