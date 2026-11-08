"""Synthetic competition tiers and controlled scenario transformations.

All input here is GENERATED, never relabelled as source research data.
Sweep generation holds the base truck population fixed per seed, then
modifies one independent experimental dimension at a time.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random

from scheduler.base import AlgorithmType

from .generator import generate_scenario
from .models import ScenarioValidationError, validate_scenario


COMPETITION_DEFAULTS = {
    "low": {"inbound_count": 15, "outbound_count": 15, "dock_count": 8,
            "arrival_horizon": 120.0, "dependency_ratio": 0.2, "scenario_preset": "normal"},
    "medium": {"inbound_count": 30, "outbound_count": 30, "dock_count": 5,
               "arrival_horizon": 90.0, "dependency_ratio": 0.5, "scenario_preset": "normal"},
    "high": {"inbound_count": 50, "outbound_count": 50, "dock_count": 3,
             "arrival_horizon": 60.0, "dependency_ratio": 0.8, "scenario_preset": "normal"},
}
SCAN_PARAMETERS = ("dock_count", "arrival_density", "dependency_ratio")
ALGORITHMS = tuple(algorithm.value for algorithm in AlgorithmType)


def make_docks(dock_count: int) -> list[dict]:
    """Deterministic compatible dock set: one FLEX or IN+OUT+FLEX remainder."""
    if type(dock_count) is not int or not 1 <= dock_count <= 30:
        raise ScenarioValidationError("dock_count must be an integer in [1,30]")
    if dock_count == 1:
        modes = ["FLEX"]
    else:
        modes = ["IN", "OUT", *(["FLEX"] * (dock_count - 2))]
    return [{"dock_id": f"D{i + 1:02d}", "mode": mode, "slot_index": i}
            for i, mode in enumerate(modes)]


def _tier(level: str) -> dict:
    if not isinstance(level, str) or level not in COMPETITION_DEFAULTS:
        raise ScenarioValidationError("competition_level must be low/medium/high")
    return dict(COMPETITION_DEFAULTS[level])


def generate_competition_scenario(level: str, seed: int = 42) -> dict:
    """Generate a complete, stable low/medium/high sample for normal runs."""
    if type(seed) is not int:
        raise ScenarioValidationError("seed must be an integer")
    params = _tier(level)
    docks = make_docks(params.pop("dock_count"))
    scene = generate_scenario({
        **params, "random_seed": seed, "docks": docks,
        "scenario_id": f"competition-{level}-seed{seed}",
    })
    return scene


def _dependency_plan(base: dict, seed: int) -> tuple[list[str], dict[str, list[str]]]:
    """Stable nested group of OUT IDs with pre-picked, unchanged IN predecessors."""
    inbound_ids = sorted(t["truck_id"] for t in base["trucks"] if t["direction"] == "IN")
    outbound_ids = sorted(t["truck_id"] for t in base["trucks"] if t["direction"] == "OUT")
    rng = random.Random(f"DockFlow-controlled-dependencies-{seed}")
    rng.shuffle(outbound_ids)
    assigned: dict[str, list[str]] = {}
    for oid in outbound_ids:
        if inbound_ids:
            assigned[oid] = sorted(rng.sample(inbound_ids, rng.randint(1, min(3, len(inbound_ids)))))
        else:
            assigned[oid] = []
    return outbound_ids, assigned


def controlled_scenario(
    base: dict, level: str, parameter: str, value: int | float, seed: int,
    base_config: dict | None = None,
) -> dict:
    """Derive one frozen Scenario, preserving unrelated truck attributes."""
    if parameter not in SCAN_PARAMETERS:
        raise ScenarioValidationError(f"Unsupported sweep parameter: {parameter}")
    params = _tier(level)
    if base_config is not None:
        params.update(base_config)
    scene = copy.deepcopy(base)
    if parameter == "dock_count":
        scene["docks"] = make_docks(value)
        ratio = params["dependency_ratio"]
    elif parameter == "arrival_density":
        total = len(scene["trucks"])
        horizon = total / float(value)
        if not math.isfinite(horizon) or horizon <= 0:
            raise ScenarioValidationError("Arrival horizon derived from density is invalid")
        original_horizon = base["arrival_horizon"]
        factor = horizon / original_horizon
        for truck in scene["trucks"]:
            truck["arrival_time"] = truck["arrival_time"] * factor
        scene["arrival_horizon"] = horizon
        # Fixed absolute due dates isolate arrival timing; they may become harder
        # or easier to meet, which is an actual consequence of this experiment.
        ratio = params["dependency_ratio"]
    else:
        ratio = float(value)

    outbound_order, assignments = _dependency_plan(base, seed)
    active = set(outbound_order[:round(len(outbound_order) * ratio)])
    for truck in scene["trucks"]:
        if truck["direction"] == "OUT":
            truck["depends_on"] = assignments[truck["truck_id"]] if truck["truck_id"] in active else []
    suffix = ""
    if base_config is not None:
        # Include the exact generated schedule inputs, not only the baseline:
        # arrival_density may change a base arrival window depending on other
        # sweep points, so the same x/seed can still represent different data.
        fingerprint = json.dumps(
            {k: v for k, v in scene.items() if k != "scenario_id"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        suffix = "-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
    scene["scenario_id"] = f"exp-{level}-{parameter}-{value}-seed{seed}{suffix}"
    validate_scenario(scene)
    return scene


def experiment_baseline(level: str, seed: int, parameter: str,
                        values: list[int | float], base_config: dict | None = None) -> dict:
    """One common base for the entire x-series of a seed."""
    params = _tier(level)
    if base_config is not None:
        params.update(base_config)
    params["dependency_ratio"] = 0.0
    params["docks"] = make_docks(params.pop("dock_count"))
    if parameter == "arrival_density":
        # Start at the longest horizon so later compression never introduces
        # artificially impossible 'arrived after deadline' tasks.
        params["arrival_horizon"] = max(
            params["arrival_horizon"], len_total(params) / min(values)
        )
    params["random_seed"] = seed
    params["scenario_id"] = f"exp-baseline-{level}-seed{seed}"
    return generate_scenario(params)


def len_total(params: dict) -> int:
    return params["inbound_count"] + params["outbound_count"]
