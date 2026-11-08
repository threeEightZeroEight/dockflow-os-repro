"""EDF+Aging 老化阈值（aging_threshold）参数扫描与调参曲线（P1-B）。

用途：为 PPT 说明 EDF+Aging 的阈值选择依据——遍历 aging_threshold 参数，
多随机种子批量运行仿真，自动输出指标 CSV（平均等待时间、任务逾期率等），
并绘制「阈值 → 指标」调参曲线。

场景来源：默认 `generate_competition_scenario(level, seed)`（low/medium/high），
同一 seed 的冻结场景对所有阈值共享，保证单变量对照。

确定性：相同 (thresholds, seeds, level) 输入产出完全相同的运行结果；
绘图输出 PNG（matplotlib Agg 后端，延迟导入）。
"""
from __future__ import annotations

import csv

from ..competition import generate_competition_scenario
from ..engine import run_simulation
from ..metrics import export_results_csv

# 默认扫描阈值（仿真分钟）
DEFAULT_THRESHOLDS = (5.0, 10.0, 15.0, 20.0, 30.0)
# 汇总曲线的指标（均值口径，None 跳过）
SWEEP_METRICS = ("avg_waiting_time", "p95_waiting_time",
                 "outbound_deadline_miss_rate", "throughput")


def run_aging_threshold_sweep(
    thresholds: list[float],
    seeds: list[int],
    level: str = "low",
    algorithms: tuple[str, ...] = ("edf_aging",),
) -> dict:
    """扫描 aging_threshold × 多种子批量运行 edf_aging。

    返回 {"level", "seeds", "thresholds", "algorithms", "runs", "summary"}；
    summary[threshold][algorithm] = {metric: 跨种子均值}。
    """
    if (not isinstance(thresholds, list) or not thresholds
            or any(isinstance(t, bool) or not isinstance(t, (int, float))
                   or not t > 0 for t in thresholds)):
        raise ValueError("thresholds must be a nonempty list of positive numbers")
    if (not isinstance(seeds, list) or not seeds
            or any(type(s) is not int for s in seeds)):
        raise ValueError("seeds must be a nonempty list of integers")
    algorithms = tuple(algorithms)
    if not algorithms or any(a not in ("edf", "edf_aging") for a in algorithms):
        raise ValueError("algorithms must be a nonempty subset of ('edf', 'edf_aging')")
    thresholds = [float(t) for t in thresholds]
    seeds = list(seeds)

    runs: list[dict] = []
    for seed in seeds:
        scene = generate_competition_scenario(level, seed)  # 同 seed 冻结共享
        for threshold in thresholds:
            for algorithm in algorithms:
                result = run_simulation(scene, algorithm, {
                    "aging_threshold": threshold,
                    "random_seed": seed,
                })
                runs.append({
                    "level": level,
                    "seed": seed,
                    "threshold": threshold,
                    "algorithm": algorithm,
                    "result": result,
                })

    summary: dict[float, dict[str, dict]] = {}
    for threshold in thresholds:
        by_algorithm: dict[str, dict] = {}
        for algorithm in algorithms:
            rows = [run for run in runs
                    if run["threshold"] == threshold
                    and run["algorithm"] == algorithm]
            stats: dict[str, float | None] = {}
            for metric in SWEEP_METRICS:
                values = [run["result"]["metrics"].get(metric) for run in rows]
                numbers = [float(v) for v in values if isinstance(v, (int, float))]
                stats[metric] = (sum(numbers) / len(numbers)) if numbers else None
            stats["run_count"] = len(rows)
            by_algorithm[algorithm] = stats
        summary[threshold] = by_algorithm

    return {
        "level": level,
        "seeds": seeds,
        "thresholds": thresholds,
        "algorithms": list(algorithms),
        "runs": runs,
        "summary": summary,
    }


def export_aging_sweep_csv(sweep: dict, path: str) -> str:
    """将扫描的全部运行导出为逐次指标 CSV（复用 metrics 导出器）。"""
    return export_results_csv([run["result"] for run in sweep["runs"]], path)


def export_aging_sweep_summary_csv(sweep: dict, path: str) -> str:
    """导出「阈值 × 算法 → 指标均值」汇总 CSV（调参曲线数据源）。"""
    fieldnames = ["aging_threshold", "algorithm", *SWEEP_METRICS, "run_count"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for threshold, by_algorithm in sweep["summary"].items():
            for algorithm, stats in by_algorithm.items():
                row = {"aging_threshold": threshold, "algorithm": algorithm}
                row.update({k: stats.get(k) for k in fieldnames
                            if k not in row})
                writer.writerow(row)
    return path


def plot_aging_sweep(sweep: dict, path: str, title: str | None = None) -> str:
    """绘制调参曲线：上图为平均等待时间、下图为出站逾期率，横轴为阈值。

    每个算法一条曲线；多随机种子已按均值聚合。返回 PNG 路径。
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # 无显示环境下渲染
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("plotting requires matplotlib: pip install matplotlib") from exc

    fig, (ax_wait, ax_miss) = plt.subplots(2, 1, figsize=(7.0, 8.0),
                                           sharex=True)
    for algorithm in sweep["algorithms"]:
        xs: list[float] = []
        waits: list[float] = []
        misses: list[float] = []
        for threshold in sweep["thresholds"]:
            stats = sweep["summary"][threshold][algorithm]
            if stats.get("avg_waiting_time") is not None:
                xs.append(threshold)
                waits.append(stats["avg_waiting_time"])
                misses.append(stats.get("outbound_deadline_miss_rate") or 0.0)
        if xs:
            ax_wait.plot(xs, waits, marker="o", label=algorithm)
            ax_miss.plot(xs, misses, marker="o", label=algorithm)

    ax_wait.set_ylabel("avg waiting time (min)")
    ax_wait.set_title(title or (f"EDF+Aging aging_threshold sweep "
                                f"({sweep['level']}, seeds={sweep['seeds']})"))
    ax_wait.grid(True, alpha=0.3)
    ax_wait.legend()
    ax_miss.set_xlabel("aging_threshold")
    ax_miss.set_ylabel("outbound deadline miss rate")
    ax_miss.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="python -m simulation.experiments.aging_sweep",
        description="EDF+Aging aging_threshold 参数扫描与调参曲线绘制",
    )
    parser.add_argument("--level", default="low",
                        choices=["low", "medium", "high"],
                        help="竞争场景档位（默认 low）")
    parser.add_argument("--thresholds", nargs="*", type=float,
                        default=list(DEFAULT_THRESHOLDS),
                        help="aging_threshold 扫描列表")
    parser.add_argument("--seeds", nargs="*", type=int, default=[1, 2, 3],
                        help="随机种子列表（默认 1 2 3）")
    parser.add_argument("--out", default="build/aging_sweep",
                        help="输出目录")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sweep = run_aging_threshold_sweep(
        args.thresholds, args.seeds, level=args.level)
    csv_path = export_aging_sweep_csv(sweep, str(out_dir / "aging-sweep-runs.csv"))
    summary_path = export_aging_sweep_summary_csv(
        sweep, str(out_dir / "aging-sweep-summary.csv"))
    png_path = plot_aging_sweep(sweep, str(out_dir / "aging-sweep-curve.png"))
    print(f"[done] level={args.level} thresholds={args.thresholds} "
          f"seeds={args.seeds}: {len(sweep['runs'])} runs")
    for threshold, by_algorithm in sweep["summary"].items():
        for algorithm, stats in by_algorithm.items():
            print(f"    threshold={threshold:<6} {algorithm:<10} "
                  f"avg_wait={_fmt(stats['avg_waiting_time'])} "
                  f"miss_rate={_fmt(stats['outbound_deadline_miss_rate'])}")
    print(f"[done] runs csv -> {csv_path}")
    print(f"[done] summary csv -> {summary_path}")
    print(f"[done] curve png -> {png_path}")
    return 0


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
