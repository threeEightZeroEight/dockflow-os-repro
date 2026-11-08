"""Reproducible baseline comparisons of dock capacity, dependencies and deadlines.

Every seed freezes one Scenario shared by all seven online schedulers. Results
retain real event records; wall-clock decision_cost is excluded from summary
means. No forklift, buffer or dock-failure model is simulated.
"""
from __future__ import annotations

import random

from ..competition import ALGORITHMS as COMPARISON_ALGORITHMS, make_docks
from ..engine import run_simulation
from ..generator import generate_scenario
from ..models import validate_scenario
from ..metrics import export_results_csv

# 汇总统计的指标（decision_cost 为真实墙钟耗时，不参与跨种子汇总）
SUMMARY_METRICS = (
    "avg_waiting_time", "p95_waiting_time", "max_waiting_time",
    "outbound_deadline_miss_rate", "throughput", "dock_utilization",
    "completed_count", "uncompleted_count", "long_wait_task_ratio",
)


# ---------------------------------------------------------------------------
# 场景生成器（全部确定性：random.Random(固定命名种子)）
# ---------------------------------------------------------------------------

def _docks(count: int) -> list[dict]:
    """与 competition.make_docks 同源的确定性月台布局。"""
    return make_docks(count)


def generate_dependency_concentration(seed: int, scale: str) -> dict:
    """场景 1【依赖集中】：少量入站车阻塞大量出站车。

    少数 IN 车（前 2 辆）被大量 OUT 车共同依赖，形成单点解锁瓶颈；
    对比 DA 与 JointDA 在出站车阻塞时长上的差异。
    """
    params = {
        "small": {"inbound_count": 4, "outbound_count": 12, "dock_count": 4,
                  "arrival_horizon": 40.0},
        "large": {"inbound_count": 10, "outbound_count": 40, "dock_count": 6,
                  "arrival_horizon": 90.0},
    }[scale]
    scene = generate_scenario({
        **params, "dependency_ratio": 0.0, "docks": _docks(params["dock_count"]),
        "random_seed": seed, "scenario_id": f"exp-dep-concentration-{scale}-seed{seed}",
    })
    # 全部 OUT 车依赖前 2 辆 IN 车（依赖集中）
    inbound_ids = sorted(t["truck_id"] for t in scene["trucks"]
                         if t["direction"] == "IN")
    hub_ids = inbound_ids[:2]
    rng = random.Random(f"dep-concentration-{seed}")
    for truck in scene["trucks"]:
        if truck["direction"] == "OUT":
            truck["depends_on"] = sorted(
                rng.sample(hub_ids, rng.randint(1, len(hub_ids))))
    validate_scenario(scene)
    return scene


def generate_deadline_pressure(seed: int, scale: str) -> dict:
    """场景 2【时限紧张】：出站任务截止时间差异大（紧/松交替）。

    一半 OUT 车截止时间极紧（卸完即走），另一半非常宽松；
    验证算法在「优先解锁下游」与「优先赶截止时间」之间的取舍。
    """
    params = {
        "small": {"inbound_count": 6, "outbound_count": 10, "dock_count": 3,
                  "arrival_horizon": 40.0, "dependency_ratio": 0.4},
        "large": {"inbound_count": 20, "outbound_count": 30, "dock_count": 4,
                  "arrival_horizon": 90.0, "dependency_ratio": 0.4},
    }[scale]
    scene = generate_scenario({
        **params, "docks": _docks(params["dock_count"]),
        "random_seed": seed, "scenario_id": f"exp-deadline-pressure-{scale}-seed{seed}",
    })
    approach = scene["approach_duration"]
    exit_duration = scene["exit_duration"]
    rng = random.Random(f"deadline-pressure-{seed}")
    outbound = sorted((t for t in scene["trucks"] if t["direction"] == "OUT"),
                      key=lambda t: t["truck_id"])
    for index, truck in enumerate(outbound):
        service = truck["service_duration"]
        earliest = truck["arrival_time"] + service + approach + exit_duration
        if index % 2 == 0:
            # 紧时限：最早可完成时刻 + 极小冗余
            truck["departure_deadline"] = round(earliest + rng.uniform(0.5, 3.0), 3)
        else:
            # 松时限：宽裕冗余
            truck["departure_deadline"] = round(earliest + rng.uniform(30.0, 60.0), 3)
    validate_scenario(scene)
    return scene


# Standard baseline research scenarios; removed physical experiments deliberately
# retain no aliases, so archived names cannot silently acquire another meaning.
COMPARISON_SCENARIOS: dict[str, dict] = {
    "dependency_concentration": {
        "title": "依赖集中场景",
        "builder": generate_dependency_concentration,
        "settings": {"simulation_mode": "baseline"},
        "focus": "不同月台布局下的下游依赖解锁与出站等待",
    },
    "deadline_pressure": {
        "title": "时限紧张场景",
        "builder": generate_deadline_pressure,
        "settings": {"simulation_mode": "baseline"},
        "focus": "解锁下游任务数量与出站时限的取舍",
    },
}


def build_scenario(name: str, seed: int, scale: str) -> tuple[dict, dict]:
    """Build the named baseline scenario; extra settings remain empty."""
    if name not in COMPARISON_SCENARIOS:
        raise ValueError(f"Unknown comparison scenario: {name}")
    if scale not in ("small", "large"):
        raise ValueError("scale must be 'small' or 'large'")
    return COMPARISON_SCENARIOS[name]["builder"](seed, scale), {}


def scenario_settings(name: str, seed: int) -> dict:
    """场景固定 settings + 随机种子（写入结果 settings 供 CSV 上下文列）。"""
    return {**COMPARISON_SCENARIOS[name]["settings"], "random_seed": seed}


# ---------------------------------------------------------------------------
# 批量运行器
# ---------------------------------------------------------------------------

def run_comparison_experiment(
    scenario_name: str,
    seeds: list[int],
    algorithms: list[str] | tuple[str, ...] = COMPARISON_ALGORITHMS,
    scale: str = "large",
) -> dict:
    """单场景 × 多种子 × 多算法批量仿真。

    返回 {"scenario_name","scale","seeds","algorithms","runs","summary"}；
    runs 内每行含冻结场景与完整 SimulationResult；summary 为按算法求均值
    （None 值跳过，decision_cost 墙钟耗时除外不参与汇总）。
    """
    if scenario_name not in COMPARISON_SCENARIOS:
        raise ValueError(f"Unknown comparison scenario: {scenario_name}")
    if scale not in ("small", "large"):
        raise ValueError("scale must be 'small' or 'large'")
    if (not isinstance(seeds, list)
            or not seeds or any(type(seed) is not int for seed in seeds)):
        raise ValueError("seeds must be a nonempty list of integers")
    algorithms = list(algorithms)
    # Online comparisons use the same seven algorithms as the engine.
    from ..engine import ALGORITHMS as _REGISTERED_ALGORITHMS
    if (not algorithms
            or any(a not in _REGISTERED_ALGORITHMS for a in algorithms)
            or len(set(algorithms)) != len(algorithms)):
        raise ValueError(f"algorithms must be a unique subset of {sorted(_REGISTERED_ALGORITHMS)}")

    runs: list[dict] = []
    for seed in seeds:
        scene, extra_settings = build_scenario(scenario_name, seed, scale)
        settings = {**scenario_settings(scenario_name, seed), **extra_settings}
        for algorithm in algorithms:
            result = run_simulation(scene, algorithm, settings)
            runs.append({
                "scenario_name": scenario_name,
                "scale": scale,
                "seed": seed,
                "algorithm": algorithm,
                "scenario": scene,
                "result": result,
            })

    summary = _summarize(runs, algorithms)
    return {
        "scenario_name": scenario_name,
        "scale": scale,
        "seeds": list(seeds),
        "algorithms": algorithms,
        "runs": runs,
        "summary": summary,
    }


def _summarize(runs: list[dict], algorithms: list[str]) -> dict:
    """按算法对 SUMMARY_METRICS 求算术均值（None 跳过；无样本记 None）。"""
    summary: dict[str, dict] = {}
    for algorithm in algorithms:
        rows = [run for run in runs if run["algorithm"] == algorithm]
        stats: dict[str, float | int | None] = {}
        for metric in SUMMARY_METRICS:
            values: list[float] = []
            for run in rows:
                node = run["result"]["metrics"]
                value: object = node
                for part in metric.split("."):
                    if not isinstance(value, dict):
                        value = None
                        break
                    value = value.get(part)
                if isinstance(value, (int, float)) and value is not None:
                    values.append(float(value))
            stats[metric] = (sum(values) / len(values)) if values else None
        stats["run_count"] = len(rows)
        summary[algorithm] = stats
    return summary


def export_comparison_csv(experiment: dict, path: str) -> str:
    """将一个对比实验的全部 runs 导出为指标 CSV（复用 metrics 导出器）。"""
    return export_results_csv([run["result"] for run in experiment["runs"]], path)
