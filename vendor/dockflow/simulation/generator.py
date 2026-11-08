"""Seeded demonstration-scenario generator conforming to contract v1.3.

This only constructs immutable input data. No task state, scheduling choice,
or events are precomputed. Shared docks and generated deadlines are synthetic.
"""
from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from .models import ScenarioValidationError, validate_scenario


def generate_scenario(config: dict) -> dict:
    """Return a deterministic complete Scenario for normal/rush/heavy."""
    if not isinstance(config, dict):
        raise ScenarioValidationError("GenerateScenarioConfig must be an object")
    preset = config.get("scenario_preset", "normal")
    if preset not in ("normal", "rush", "heavy"):
        raise ScenarioValidationError("Generated preset must be normal/rush/heavy")
    seed = config.get("random_seed", 42)
    if type(seed) is not int:
        raise ScenarioValidationError("random_seed must be an integer")
    inbound = config.get("inbound_count", 20)
    outbound = config.get("outbound_count", 15)
    if type(inbound) is not int or type(outbound) is not int or inbound < 0 or outbound < 0 or inbound + outbound == 0:
        raise ScenarioValidationError("Vehicle counts must be nonnegative integers with nonzero sum")
    dependency_ratio = config.get("dependency_ratio", 0.7)
    if (isinstance(dependency_ratio, bool) or not isinstance(dependency_ratio, (int,float))
            or not 0 <= dependency_ratio <= 1):
        raise ScenarioValidationError("dependency_ratio must be between 0 and 1")
    if inbound == 0 and dependency_ratio != 0:
        raise ScenarioValidationError("dependency_ratio must be 0 with zero inbound trucks")
    horizon = config.get("arrival_horizon", 60.0)
    approach = config.get("approach_duration", 0.5)
    exit_duration = config.get("exit_duration", 0.5)
    import math
    for name, value in (("arrival_horizon",horizon),("approach_duration",approach),("exit_duration",exit_duration)):
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or value < 0 or (name=="arrival_horizon" and value==0):
            raise ScenarioValidationError(f"Invalid {name}")
    docks = config.get("docks")
    if docks is None:
        docks = [
            {"dock_id":"IN01", "mode":"IN", "slot_index":0},
            {"dock_id":"FLEX01", "mode":"FLEX", "slot_index":1},
            {"dock_id":"OUT01", "mode":"OUT", "slot_index":2},
        ]
    rng = random.Random(seed)
    def arrival() -> float:
        if preset == "rush" and rng.random() < 0.60:
            return rng.uniform(horizon / 3.0, 2.0 * horizon / 3.0)
        return rng.uniform(0.0, horizon * (1 - 1e-9))

    trucks = []
    for index in range(1, inbound + 1):
        service = rng.uniform(12.0, 24.0) if preset == "heavy" else rng.uniform(3.0, 9.0)
        trucks.append({
            "truck_id": f"I{index:03}", "direction": "IN",
            "arrival_time": arrival(), "service_duration": service,
            "departure_deadline": None, "depends_on": [],
            "allowed_dock_ids": None,
        })
    dep_count = int(round(outbound * dependency_ratio))
    selected_out = set(rng.sample(range(1, outbound + 1), dep_count))
    input_ids = [t["truck_id"] for t in trucks]
    for index in range(1, outbound + 1):
        service = rng.uniform(12.0, 24.0) if preset == "heavy" else rng.uniform(3.0, 9.0)
        arrive = arrival()
        dependencies = sorted(rng.sample(input_ids, rng.randint(1, min(3, inbound)))) if index in selected_out else []
        deadline = max(
            arrive + service + approach + exit_duration,
            max((t["arrival_time"] + t["service_duration"] + approach
                 for t in trucks if t["truck_id"] in dependencies), default=0.0)
            + service + approach + exit_duration,
        ) + rng.uniform(1.0, 20.0)
        trucks.append({
            "truck_id": f"O{index:03}", "direction": "OUT",
            "arrival_time": arrive, "service_duration": service,
            "departure_deadline": deadline, "depends_on": dependencies,
            "allowed_dock_ids": None,
        })
    max_time = config.get("max_simulation_time")
    if max_time is None:
        max_time = max(
            horizon, max((t["departure_deadline"] or 0) for t in trucks)
        ) + sum(t["service_duration"] + approach + exit_duration for t in trucks) + 1.0
    # The default scenario_id must uniquely reflect every content-determining
    # input. The backend dedups scenarios by (scenario_id, content hash) and
    # rejects same-ID/different-content, so params that change the payload
    # (dependency_ratio, horizon, durations, docks, max_simulation_time) must
    # be folded into the ID, otherwise two configs collide on one ID -> 422.
    id_basis = {
        "preset": preset, "seed": seed, "inbound": inbound, "outbound": outbound,
        "dependency_ratio": float(dependency_ratio), "arrival_horizon": float(horizon),
        "approach_duration": float(approach), "exit_duration": float(exit_duration),
        "docks": docks, "max_simulation_time": config.get("max_simulation_time"),
    }
    id_suffix = hashlib.sha256(
        json.dumps(id_basis, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:8]
    default_id = f"generated-{preset}-seed{seed}-i{inbound}-o{outbound}-{id_suffix}"
    scenario = {
        "schema_version": "1.2",
        "scenario_id": config.get("scenario_id", default_id),
        "scenario_source": "generated",
        "scenario_preset": preset,
        "random_seed": seed,
        "time_unit": "minute",
        "arrival_horizon": float(horizon),
        "max_simulation_time": float(max_time),
        "approach_duration": float(approach),
        "exit_duration": float(exit_duration),
        "docks": docks,
        "trucks": trucks,
    }
    validate_scenario(scenario)
    return scenario
