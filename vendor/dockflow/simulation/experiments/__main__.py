"""命令行入口：python -m simulation.experiments [options]

批量运行两组 baseline 标准对比实验（7 算法 × 多随机种子），导出指标 CSV。
默认输出目录 build/experiments/（git 忽略，不入库）。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .comparison import (
    COMPARISON_ALGORITHMS,
    COMPARISON_SCENARIOS,
    export_comparison_csv,
    run_comparison_experiment,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m simulation.experiments",
        description="DockFlow baseline 标准对比实验批量运行器",
    )
    parser.add_argument(
        "--scenario", nargs="*", default=sorted(COMPARISON_SCENARIOS),
        choices=sorted(COMPARISON_SCENARIOS),
        help="要运行的场景名（默认全部 2 组）",
    )
    parser.add_argument(
        "--seeds", nargs="*", type=int, default=[1, 2, 3],
        help="随机种子列表（默认 1 2 3）",
    )
    parser.add_argument(
        "--scale", default="large", choices=["small", "large"],
        help="small=前端可视化演示规模；large=定量统计规模（默认）",
    )
    parser.add_argument(
        "--algorithms", nargs="*", default=list(COMPARISON_ALGORITHMS),
        help=f"算法子集（默认全部 7 种：{' '.join(COMPARISON_ALGORITHMS)}）",
    )
    parser.add_argument(
        "--out", default="build/experiments", help="CSV 输出目录",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_rows_path = out_dir / f"comparison-{args.scale}-all.csv"

    combined_rows: list[dict] = []
    for name in args.scenario:
        experiment = run_comparison_experiment(
            name, seeds=args.seeds, algorithms=args.algorithms, scale=args.scale,
        )
        csv_path = out_dir / f"comparison-{name}-{args.scale}.csv"
        export_comparison_csv(experiment, str(csv_path))
        combined_rows.extend(run["result"] for run in experiment["runs"])
        print(f"[done] {name} ({args.scale}): {len(experiment['runs'])} runs "
              f"-> {csv_path}")
        for algorithm, stats in experiment["summary"].items():
            avg_wait = stats["avg_waiting_time"]
            miss = stats["outbound_deadline_miss_rate"]
            print(f"    {algorithm:<16} avg_wait={_fmt(avg_wait)} "
                  f"miss_rate={_fmt(miss)}")

    from ..metrics import export_results_csv
    export_results_csv(combined_rows, str(all_rows_path))
    print(f"[done] combined {len(combined_rows)} runs -> {all_rows_path}")
    return 0


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
