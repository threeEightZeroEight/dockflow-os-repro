#!/usr/bin/env python3
"""自适应 QEDF 图（fig15）。"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

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

S = json.loads((DATA / "stats_adaptive.json").read_text(encoding="utf-8"))
SCENARIOS = ["low", "medium", "high", "n120", "n160"]
LABELS = {"low": "低负载\n15/15·8台", "medium": "中负载\n30/30·5台",
          "high": "高负载\n50/50·3台", "n120": "120 辆", "n160": "160 辆"}
COLORS = {"edf": "#8769ad", "qedf": "#c97c5a", "aqedf": "#c0392b"}
NAMES = {"edf": "EDF", "qedf": "QEDF（无门控）", "aqedf": "AQEDF（自适应）"}


def main() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # (a) 五个场景的逾期率
    ax = axes[0]
    width = 0.26
    positions = np.arange(len(SCENARIOS))
    for index, algorithm in enumerate(("edf", "qedf", "aqedf")):
        means, errs = [], []
        for scenario in SCENARIOS:
            cell = S["by_scenario"][scenario][algorithm]["outbound_deadline_miss_rate"]
            means.append(cell["mean"])
            errs.append((cell["ci95"][1] - cell["ci95"][0]) / 2)
        ax.bar(positions + (index - 1) * width, means, width, yerr=errs, capsize=2,
               color=COLORS[algorithm], label=NAMES[algorithm], edgecolor="white")
    ax.set_xticks(positions)
    ax.set_xticklabels([LABELS[s] for s in SCENARIOS], fontsize=8.5)
    ax.set_ylabel("出站逾期率")
    ax.set_title("(a) 各负载逾期率：高负载与大规模改善，中负载统计等价", fontsize=10)
    ax.legend(fontsize=8)

    # (b) 固定规模依赖扫描
    ax = axes[1]
    ratios = [0.0, 0.2, 0.4, 0.6, 0.8]
    for algorithm in ("edf", "qedf", "aqedf"):
        ys = [S["dependency"][f"dep{r}"][algorithm]["mean"] for r in ratios]
        style = "--" if algorithm == "edf" else "-"
        ax.plot(ratios, ys, marker="o", linestyle=style, color=COLORS[algorithm],
                label=NAMES[algorithm])
    ax.set_xlabel("依赖比例")
    ax.set_ylabel("出站逾期率")
    ax.set_title("(b) 固定小规模：门控正确退化，AQEDF 贴近 EDF", fontsize=10)
    ax.legend(fontsize=8)

    fig.suptitle("图 14 自适应队列感知 EDF（AQEDF）：按排队压力启用修正，实现高压力下稳定改善",
                 fontsize=12)
    fig.tight_layout()
    path = FIG / "fig14_aqedf.png"
    fig.savefig(path)
    plt.close(fig)
    print("生成", path.relative_to(HERE.parents[1]))


if __name__ == "__main__":
    main()