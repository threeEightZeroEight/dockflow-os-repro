"""simulation.experiments 包：参数扫描（旧 API）+ baseline 标准对比实验（新 API）。

参数扫描 API（由 scans.py 实现）：
  - run_experiment / validate_experiment_config / _metric_series
  - CORE_METRICS / EXTRA_METRICS / METRIC_UNITS

四组标准对比实验 API：
  - COMPARISON_SCENARIOS / COMPARISON_ALGORITHMS
  - run_comparison_experiment(scenario_name, seeds, algorithms, scale)
  - export_comparison_csv(experiment, path)
  - 命令行入口：python -m simulation.experiments --help
"""
from .scans import (
    CORE_METRICS,
    EXTRA_METRICS,
    METRIC_UNITS,
    _metric_series,
    run_experiment,
    validate_experiment_config,
)
from .comparison import (
    COMPARISON_ALGORITHMS,
    COMPARISON_SCENARIOS,
    build_scenario,
    export_comparison_csv,
    run_comparison_experiment,
)

__all__ = [
    # 参数扫描 API
    "run_experiment", "validate_experiment_config", "_metric_series",
    "CORE_METRICS", "EXTRA_METRICS", "METRIC_UNITS",
    # 对比实验 API
    "COMPARISON_ALGORITHMS", "COMPARISON_SCENARIOS", "build_scenario",
    "run_comparison_experiment", "export_comparison_csv",
]
