#!/usr/bin/env python3
"""研究增强图：QEDF 效果与依赖—压力边界。输出 figures/fig13、fig14。"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
DATA = HERE / "data" / "research"

plt.rcParams.update({
    "font.sans-serif": ["Hiragino Sans GB", "Arial Unicode MS", "STHeiti"],
    "axes.unicode_minus": False,
    "figure.dpi": 150,
    "savefig.dpi": 220,
    "axes.grid": True,
    "grid.alpha": 0.25,
})

ORDER = ["edf", "qedf", "spt", "dependency_aware", "joint_da", "rh_da"]
LABELS = {"edf": "EDF", "qedf": "QEDF（无门控）", "aqedf": "AQEDF（本文）", "spt": "SPT",
          "dependency_aware": "DA", "joint_da": "JointDA", "rh_da": "RH-DA"}
COLORS = {"edf": "#8E82A6", "qedf": "#B49A80", "aqedf": "#B06A60",
          "spt": "#6E8FA8", "dependency_aware": "#B49A80", "joint_da": "#B08088",
          "rh_da": "#7E9A85"}


def load(name: str) -> list[dict]:
    with (DATA / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def mean_ci(values: list[float]) -> tuple[float, float]:
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    half = stats.t.ppf(0.975, n - 1) * np.std(values, ddof=1) / np.sqrt(n)
    return mean, half


def fig13() -> Path:
    qedf_rows = load("rq_qedf.csv")
    large_rows = load("rq_large_scale.csv")
    panels = [
        ("medium", qedf_rows, "中负载（30/30，5 月台）"),
        ("high", qedf_rows, "高负载（50/50，3 月台）"),
        ("n120", large_rows, "大规模（120 辆，5 月台）"),
        ("n160", large_rows, "大规模（160 辆，5 月台）"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for ax, (scenario, rows, title) in zip(axes.flat, panels):
        means, errs = [], []
        for algorithm in ORDER:
            values = [float(r["outbound_deadline_miss_rate"]) for r in rows
                      if r["scenario"] == scenario and r["algorithm"] == algorithm]
            mean, half = mean_ci(values)
            means.append(mean)
            errs.append(half)
        bars = ax.bar(range(len(ORDER)), means, yerr=errs, capsize=3,
                      color=[COLORS[a] for a in ORDER], edgecolor="white", linewidth=0.6)
        bars[ORDER.index("qedf")].set_edgecolor("#B06A60")
        bars[ORDER.index("qedf")].set_linewidth(2.0)
        ax.set_xticks(range(len(ORDER)))
        ax.set_xticklabels([LABELS[a] for a in ORDER], rotation=20, fontsize=8.5)
        ax.set_ylabel("出站逾期率")
        ax.set_title(title, fontsize=10)
        for bar, value in zip(bars, means):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f"{value:.3f}", ha="center", va="bottom", fontsize=7)
    fig.suptitle("无门控 QEDF：中等负载过度修正，高排队压力下有效",
                 fontsize=12)
    fig.tight_layout()
    path = FIG / "fig13_qedf.png"
    fig.savefig(path)
    plt.close(fig)
    print("生成", path.relative_to(HERE.parents[1]))
    return path


def fig14() -> Path:
    rows = load("rq_dependency.csv")
    ratios = ["0.0", "0.2", "0.4", "0.6", "0.8"]
    fig, ax = plt.subplots(figsize=(7.5, 5))
    for algorithm in ("edf", "qedf", "aqedf"):
        xs, means, lows, highs = [], [], [], []
        for ratio in ratios:
            values = [float(r["outbound_deadline_miss_rate"]) for r in rows
                      if r["scenario"] == f"dep{ratio}" and r["algorithm"] == algorithm]
            mean, half = mean_ci(values)
            xs.append(float(ratio))
            means.append(mean)
            lows.append(mean - half)
            highs.append(mean + half)
        ax.plot(xs, means, marker="o", color=COLORS[algorithm], label=LABELS[algorithm])
        ax.fill_between(xs, lows, highs, color=COLORS[algorithm], alpha=0.12)
    ax.set_xlabel("依赖比例")
    ax.set_ylabel("出站逾期率")
    ax.set_title("固定规模（30/30，5 月台）下 QEDF 并无收益：\n"
                 "修正需要足够的排队压力，而非单纯依赖比例")
    ax.legend(fontsize=9)
    fig.tight_layout()
    path = FIG / "fig16_qedf_dependency.png"
    fig.savefig(path)
    plt.close(fig)
    print("生成", path.relative_to(HERE.parents[1]))
    return path


def main() -> None:
    fig13()
    fig14()


if __name__ == "__main__":
    main()