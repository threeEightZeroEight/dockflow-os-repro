"""Reproducible real-scheduler parameter scans, no database or plotting.

A result contains full Scenario+SimulationResult records so the backend can
persist immutable evidence, plus metric series suitable for ECharts.

（原 simulation/experiments.py，转为 experiments 包后保持 API 不变，
经由 simulation/experiments/__init__.py 重新导出供旧调用方使用。）
"""
from __future__ import annotations

import math
from collections import defaultdict

from ..competition import (
    ALGORITHMS, SCAN_PARAMETERS, COMPETITION_DEFAULTS,
    _tier, controlled_scenario, experiment_baseline,
)
from ..engine import run_simulation, validate_settings
from ..models import ScenarioValidationError
from .scoring import SCORE_WEIGHTS, score_experiment_runs

CORE_METRICS = (
    "avg_waiting_time",
    "p95_waiting_time",
    "outbound_deadline_miss_rate",
    "throughput",
    "dock_utilization",
)
EXTRA_METRICS = ("uncompleted_count",)
METRIC_UNITS = {
    "avg_waiting_time": "minute",
    "p95_waiting_time": "minute",
    "outbound_deadline_miss_rate": "ratio",
    "throughput": "truck_per_minute",
    "dock_utilization": "ratio",
    "uncompleted_count": "truck",
    "dock_score": "score",
}


def validate_experiment_config(config: dict) -> dict:
    """Return a normalized, JSON-safe copy; reject ambiguous input up front."""
    if not isinstance(config, dict):
        raise ScenarioValidationError("ExperimentConfig must be a JSON object")
    keys = {"competition_level", "vary_parameter", "parameter_values",
            "seeds", "algorithms", "settings", "base_config"}
    unexpected = set(config) - keys
    if unexpected:
        raise ScenarioValidationError(f"Unknown ExperimentConfig field(s): {sorted(unexpected)}")
    level = config.get("competition_level")
    _tier(level)
    parameter = config.get("vary_parameter")
    if parameter not in SCAN_PARAMETERS:
        raise ScenarioValidationError(f"vary_parameter must be one of {SCAN_PARAMETERS}")
    values = config.get("parameter_values")
    if not isinstance(values, list) or not 2 <= len(values) <= 12:
        raise ScenarioValidationError("parameter_values must contain 2–12 ordered points")
    normalized_values: list[int | float] = []
    previous: float | None = None
    for value in values:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ScenarioValidationError("parameter_values must be finite numbers, not bool")
        if parameter == "dock_count":
            if type(value) is not int or not 1 <= value <= 30:
                raise ScenarioValidationError("dock_count sweep points must be integers in [1,30]")
            clean: int | float = value
        elif parameter == "arrival_density":
            if value <= 0:
                raise ScenarioValidationError("arrival_density must be positive")
            clean = float(value)
            if not math.isfinite((sum(COMPETITION_DEFAULTS[level][k] for k in ("inbound_count","outbound_count"))) / clean):
                raise ScenarioValidationError("arrival_density implies an infinite arrival horizon")
        else:
            if not 0 <= value <= 1:
                raise ScenarioValidationError("dependency_ratio must be in [0,1]")
            clean = float(value)
        if previous is not None and clean <= previous:
            raise ScenarioValidationError("parameter_values must be strictly increasing and unique")
        previous = float(clean)
        normalized_values.append(clean)

    # Optional fixed base scenario. Presets are initial values, not additional
    # factors being silently changed during a one-variable scan.
    raw_base = config.get("base_config")
    base_config = None
    if raw_base is not None:
        allowed_base = {
            "inbound_count", "outbound_count", "dock_count", "arrival_horizon",
            "dependency_ratio", "scenario_preset",
        }
        if not isinstance(raw_base, dict) or set(raw_base) - allowed_base:
            raise ScenarioValidationError(
                f"base_config supports only {sorted(allowed_base)}")
        base_config = dict(COMPETITION_DEFAULTS[level])
        base_config.update(raw_base)
        inbound, outbound, dock_count = (
            base_config["inbound_count"], base_config["outbound_count"],
            base_config["dock_count"],
        )
        if (type(inbound) is not int or type(outbound) is not int
                or not 0 <= inbound <= 100 or not 0 <= outbound <= 100
                or inbound + outbound < 1 or inbound + outbound > 150):
            raise ScenarioValidationError(
                "base_config inbound/outbound must be integers [0,100] "
                "with a total of 1–150 trucks")
        if type(dock_count) is not int or not 1 <= dock_count <= 30:
            raise ScenarioValidationError("base_config dock_count must be integer in [1,30]")
        horizon, ratio = base_config["arrival_horizon"], base_config["dependency_ratio"]
        if (type(horizon) not in (int, float) or not math.isfinite(horizon) or horizon <= 0):
            raise ScenarioValidationError("base_config arrival_horizon must be positive and finite")
        if (type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0 <= ratio <= 1
                or (inbound == 0 and ratio != 0)):
            raise ScenarioValidationError("base_config dependency_ratio must be in [0,1], "
                                          "or 0 when there are no inbound trucks")
        if base_config["scenario_preset"] not in ("normal", "rush", "heavy"):
            raise ScenarioValidationError("base_config scenario_preset must be normal/rush/heavy")
        base_config["arrival_horizon"] = float(horizon)
        base_config["dependency_ratio"] = float(ratio)
        if parameter == "arrival_density" and not math.isfinite(
                (inbound + outbound) / normalized_values[0]):
            raise ScenarioValidationError("Arrival density implies infinite arrival horizon")

    seeds = config.get("seeds")
    if (not isinstance(seeds, list) or not 1 <= len(seeds) <= 20
            or any(type(seed) is not int for seed in seeds) or len(set(seeds)) != len(seeds)):
        raise ScenarioValidationError("seeds must be 1–20 distinct integers")

    # The single canonical AlgorithmType enum defines the seven allowed IDs.
    algorithms = config.get("algorithms", list(ALGORITHMS))
    if (not isinstance(algorithms, list) or not 1 <= len(algorithms) <= len(ALGORITHMS)
            or any(type(a) is not str or a not in ALGORITHMS for a in algorithms)
            or len(set(algorithms)) != len(algorithms)):
        raise ScenarioValidationError(
            "algorithms must be a nonempty unique subset of supported algorithms")

    settings = config.get("settings", {})
    allowed_settings_keys = {"aging_threshold", "simulation_mode", "long_wait_threshold"}
    if not isinstance(settings, dict) or set(settings) - allowed_settings_keys:
        raise ScenarioValidationError(
            f"settings supports only {sorted(allowed_settings_keys)}")
    try:
        normalized_settings = validate_settings(settings)
    except ValueError as exc:
        raise ScenarioValidationError(str(exc)) from exc

    return {
        "competition_level": level,
        **({"base_config": base_config} if base_config is not None else {}),
        "vary_parameter": parameter,
        "parameter_values": normalized_values,
        "seeds": list(seeds),
        "algorithms": list(algorithms),
        "settings": normalized_settings,
    }


def _metric_series(config: dict, runs: list[dict]) -> dict:
    """Aggregate arithmetic mean/min/max across non-null independent seeds."""
    run_lookup: dict[tuple[int | float, str], list[dict]] = defaultdict(list)
    for row in runs:
        run_lookup[(row["parameter_value"], row["algorithm"])].append(row)

    series = {}
    for name in (*CORE_METRICS, *EXTRA_METRICS, "dock_score"):
        curves = []
        for algorithm in config["algorithms"]:
            points = []
            for value in config["parameter_values"]:
                observed = [
                    item.get("evaluation", {}).get("dock_score")
                    if name == "dock_score" else item["result"]["metrics"].get(name)
                    for item in run_lookup[(value, algorithm)]
                ]
                observed = [v for v in observed if v is not None]
                points.append({
                    "x": value,
                    "mean": sum(observed) / len(observed) if observed else None,
                    "min": min(observed) if observed else None,
                    "max": max(observed) if observed else None,
                    "sample_count": len(observed),
                })
            curves.append({"algorithm": algorithm, "points": points})
        series[name] = {"unit": METRIC_UNITS[name], "curves": curves}
        if name == "dock_score":
            series[name].update({
                "relative": True,
                "score_version": 1,
                "weights": SCORE_WEIGHTS.copy(),
                "note": "同场景同种子的候选算法相对评分；改变算法集合会改变得分，不可跨实验比较",
            })
    return series


def run_experiment(config: dict) -> dict:
    """Run every algorithm on the same frozen point/seed Scenario.

    No mocking, no persistence, no plotting; the caller owns storage.
    Returned full run records may be large; the backend should deduplicate
    stored scenarios per (parameter_value, seed).
    """
    normalized = validate_experiment_config(config)
    level = normalized["competition_level"]
    parameter = normalized["vary_parameter"]
    values = normalized["parameter_values"]
    runs = []
    base_config = normalized.get("base_config")
    for seed in normalized["seeds"]:
        base = experiment_baseline(level, seed, parameter, values, base_config)
        for value in values:
            scene = controlled_scenario(base, level, parameter, value, seed, base_config)
            for algorithm in normalized["algorithms"]:
                result = run_simulation(scene, algorithm, normalized["settings"])
                runs.append({
                    "parameter_value": value,
                    "seed": seed,
                    "algorithm": algorithm,
                    "scenario": scene,
                    "result": result,
                })

    score_experiment_runs(runs)
    return {
        "config": normalized,
        "runs": runs,
        "series": _metric_series(normalized, runs),
    }
