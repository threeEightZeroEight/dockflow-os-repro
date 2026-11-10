#!/usr/bin/env python3
"""论文级图表（20 种子扩展实验 + Mendeley 基准）。输出 docs/os-report/figures/。"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
EXT = HERE / "data" / "extended"
FIG.mkdir(exist_ok=True)

plt.rcParams.update({
    "font.sans-serif": ["Hiragino Sans GB", "Arial Unicode MS", "STHeiti"],
    "axes.unicode_minus": False,
    "figure.dpi": 150,
    "savefig.dpi": 220,
    "axes.grid": True,
    "grid.alpha": 0.25,
})

ORDER = ["fcfs", "spt", "edf", "edf_aging", "dependency_aware", "joint_da", "rh_da"]
ORDER8 = ORDER + ["aqedf"]
LABELS = {
    "fcfs": "FCFS", "spt": "SPT", "edf": "EDF", "edf_aging": "EDF+Aging",
    "dependency_aware": "DA", "joint_da": "JointDA", "rh_da": "RH-DA",
    "aqedf": "AQEDF",
}
COLORS = {
    "fcfs": "#7A8796", "spt": "#6E8FA8", "edf": "#8E82A6", "edf_aging": "#6F9A94",
    "dependency_aware": "#B49A80", "joint_da": "#B08088", "rh_da": "#7E9A85",
    "aqedf": "#B06A60",
}
LEVELS = ["low", "medium", "high"]
LEVEL_LABELS = {
    "low": "低负载\n（15/15，8 月台，依赖 0.2）",
    "medium": "中负载\n（30/30，5 月台，依赖 0.5）",
    "high": "高负载\n（50/50，3 月台，依赖 0.8）",
}


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(EXT / name)


def mean_ci(series: pd.Series) -> tuple[float, float]:
    values = series.dropna().astype(float)
    n = len(values)
    mean = values.mean()
    if n < 2:
        return float(mean), 0.0
    half = stats.t.ppf(0.975, n - 1) * values.std(ddof=1) / np.sqrt(n)
    return float(mean), float(half)


def save(fig, name: str) -> Path:
    path = FIG / name
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print("生成", path.relative_to(REPO_ROOT))
    return path


def fig04_multi_scenario() -> Path:
    df = load("ea_multi_scenario.csv")
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for column, level in enumerate(LEVELS):
        sub = df[df["scenario"] == level]
        for row, (metric, title) in enumerate(
            (("avg_waiting_time", "平均等待时间（分钟）"),
             ("outbound_deadline_miss_rate", "出站逾期率"))
        ):
            ax = axes[row][column]
            means, errs = [], []
            for algorithm in ORDER8:
                mean, half = mean_ci(sub[sub["algorithm"] == algorithm][metric])
                means.append(mean)
                errs.append(half)
            bars = ax.bar(range(len(ORDER8)), means, yerr=errs, capsize=3,
                          color=[COLORS[a] for a in ORDER8], edgecolor="white", linewidth=0.6)
            ax.set_xticks(range(len(ORDER8)))
            ax.set_xticklabels([LABELS[a] for a in ORDER8], rotation=35, fontsize=8)
            ax.set_title(f"{LEVEL_LABELS[level]} — {title}", fontsize=9)
            for bar, value in zip(bars, means):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f"{value:.2f}", ha="center", va="bottom", fontsize=6.5)
    fig.suptitle("图 4 不同竞争强度下的策略表现（20 种子，八种策略，均值 ± 95% 置信区间）",
                 fontsize=12)
    return save(fig, "fig04_multi_scenario.png")


def fig05_waiting_distribution() -> Path:
    df = load("eh_waiting.csv")
    algorithms = ["fcfs", "spt", "edf_aging", "joint_da"]
    data = [df[df["algorithm"] == a]["waiting_time"].dropna().astype(float) for a in algorithms]
    fig, ax = plt.subplots(figsize=(8, 5))
    box = ax.boxplot(data, patch_artist=True, widths=0.5, showfliers=True)
    for patch, algorithm in zip(box["boxes"], algorithms):
        patch.set_facecolor(COLORS[algorithm])
        patch.set_alpha(0.65)
    ax.set_xticklabels([LABELS[a] for a in algorithms])
    ax.set_ylabel("单车等待时间（分钟）")
    ax.set_title("图 5 等待时间分布（中等负载，20 种子，4800 条车辆记录）")
    return save(fig, "fig05_waiting_distribution.png")


def _series(ax, df, scenario_prefix: str, metric: str, algorithms: list[str],
            xlabel: str, title: str, ylabel: str) -> None:
    df = df.copy()
    df["x"] = df["scenario"].str.replace(scenario_prefix, "", regex=False).astype(float)
    for algorithm in algorithms:
        sub = df[df["algorithm"] == algorithm]
        xs, means, errs = [], [], []
        for x in sorted(sub["x"].unique()):
            mean, half = mean_ci(sub[sub["x"] == x][metric])
            xs.append(x)
            means.append(mean)
            errs.append(half)
        ax.errorbar(xs, means, yerr=errs, marker="o", markersize=4, capsize=3,
                    color=COLORS[algorithm], label=LABELS[algorithm], linewidth=1.4)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(fontsize=8, ncol=2)


def fig06_sensitivity() -> Path:
    dependency = load("ed_dependency.csv")
    docks = load("ee_docks.csv")
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    _series(axes[0][0], dependency, "dep", "avg_waiting_time", ORDER,
            "依赖比例", "(a) 依赖比例与等待时间", "等待时间（分钟）")
    _series(axes[0][1], dependency, "dep", "outbound_deadline_miss_rate", ORDER,
            "依赖比例", "(b) 依赖比例与逾期率", "Miss rate")
    _series(axes[1][0], docks, "docks", "avg_waiting_time", ORDER,
            "月台数", "(c) 月台数与等待时间", "等待时间（分钟）")
    _series(axes[1][1], docks, "docks", "dock_utilization", ORDER,
            "月台数", "(d) 月台数与利用率", "月台利用率")
    fig.suptitle("图 6 依赖密度与资源供给敏感性（20 种子）",
                 fontsize=12)
    return save(fig, "fig06_sensitivity.png")


def fig07_aging() -> Path:
    df = load("ef_aging.csv")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for ax, metric, title, ylabel in (
        (axes[0], "long_wait_task_ratio", "(a) 老化阈值与长等待占比", "长等待任务占比"),
        (axes[1], "outbound_deadline_miss_rate", "(b) 老化阈值与逾期率", "Miss rate"),
    ):
        _series(ax, df, "aging", metric, ["edf", "edf_aging"],
                "老化阈值（分钟）", title, ylabel)
    fig.suptitle("图 7 老化机制的双刃剑效应（20 种子）", fontsize=12)
    return save(fig, "fig07_aging.png")


def fig08_ablation() -> Path:
    medium = load("eg_ablation.csv")
    high = load("eg_ablation_high.csv")
    variants = ["full", "no_unlock(I=0)", "no_blocked(B=0)", "no_resource(R=0)",
                "no_traffic(P=0)", "no_wait(W=0)"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8))
    for ax, df, scenario_col, title in (
        (axes[0], medium, "scenario", "(a) 中等负载：DA 权重消融"),
        (axes[1], high, "scenario", "(b) 高负载：DA 权重消融"),
    ):
        means, errs = [], []
        for variant in variants:
            mean, half = mean_ci(df[df[scenario_col] == variant]["outbound_deadline_miss_rate"])
            means.append(mean)
            errs.append(half)
        bars = ax.bar(range(len(variants)), means, yerr=errs, capsize=3,
                      color=["#6F7C89"] + ["#B49A80"] * (len(variants) - 1),
                      edgecolor="white")
        ax.set_xticks(range(len(variants)))
        ax.set_xticklabels(variants, rotation=30, fontsize=8)
        ax.set_ylabel("Miss rate")
        ax.set_title(title)
        for bar, value in zip(bars, means):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f"{value:.3f}", ha="center", va="bottom", fontsize=7)
    fig.suptitle("图 8 DA 组件消融：无单一权重项起决定作用（20 种子）",
                 fontsize=12)
    return save(fig, "fig08_ablation.png")


def fig09_scale() -> Path:
    df = pd.read_csv(Path(__file__).resolve().parent / "data" / "research" / "scale_unified.csv")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for ax, metric, ylabel, title in (
        (axes[0], "avg_waiting_time", "平均等待时间（分钟）", "(a) 车队规模与等待时间"),
        (axes[1], "throughput", "吞吐量（辆/分钟）", "(b) 车队规模与吞吐量"),
    ):
        for algorithm in ("fcfs", "spt", "edf", "aqedf"):
            sub = df[df["algorithm"] == algorithm]
            xs = sorted(sub["total"].unique())
            means, errs = [], []
            for x in xs:
                mean, half = mean_ci(sub[sub["total"] == x][metric])
                means.append(mean); errs.append(half)
            ax.errorbar(xs, means, yerr=errs, marker="o", capsize=3,
                        color=COLORS[algorithm], label=LABELS[algorithm], linewidth=1.4)
        ax.set_xlabel("车辆总数")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend(fontsize=8)
    fig.suptitle("图 9 规模扩展（20–160 辆，5 月台，依赖 0.5，10 种子）", fontsize=12)
    return save(fig, "fig09_scale.png")


def fig10_mendeley() -> Path:
    df = load("eb_mendeley.csv")
    metrics = [("avg_waiting_time", "平均等待（分钟）"),
               ("outbound_deadline_miss_rate", "Miss rate"),
               ("throughput", "吞吐量（辆/分钟）")]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    for ax, (metric, label) in zip(axes, metrics):
        values = [float(df[df["algorithm"] == a][metric].iloc[0]) for a in ORDER8]
        bars = ax.bar(range(len(ORDER8)), values, color=[COLORS[a] for a in ORDER8],
                      edgecolor="white")
        ax.set_xticks(range(len(ORDER8)))
        ax.set_xticklabels([LABELS[a] for a in ORDER8], rotation=35, fontsize=8)
        ax.set_ylabel(label)
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f"{value:.2f}", ha="center", va="bottom", fontsize=6.5)
    fig.suptitle("图 10 Mendeley 第 5 章冻结实例（53 入站 / 54 出站 / 10 月台 / 1378 托盘，八种策略）",
                 fontsize=12)
    return save(fig, "fig10_mendeley.png")


def fig11_quality_cost() -> Path:
    df = load("ea_multi_scenario.csv")
    df = df[df["scenario"] == "medium"]
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    for algorithm in ORDER:
        sub = df[df["algorithm"] == algorithm]
        x = float(sub["decision_avg_ms"].dropna().mean())
        y = float(sub["outbound_deadline_miss_rate"].dropna().mean())
        ax.scatter(x, y, s=150, color=COLORS[algorithm], edgecolor="white", zorder=3)
        ax.annotate(LABELS[algorithm], (x, y), textcoords="offset points",
                    xytext=(8, 6), fontsize=9)
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_xlabel("调度开销（毫秒/次，对数轴）")
    ax.set_ylabel("出站逾期率")
    ax.set_title("调度质量与开销（中等负载，20 种子）")
    return save(fig, "fig11_quality_cost.png")


def fig12_gantt() -> Path:
    from simulation import generate_scenario, run_simulation
    from simulation.competition import make_docks

    scenario = generate_scenario({
        "scenario_preset": "normal", "random_seed": 42,
        "inbound_count": 8, "outbound_count": 6, "dependency_ratio": 0.5,
        "arrival_horizon": 40.0, "max_simulation_time": 240.0,
        "docks": make_docks(3),
    })
    result = run_simulation(scenario, "joint_da")
    events = result["events"]
    docks = sorted({e["dock_id"] for e in events if e.get("dock_id")})
    y_base = {dock: index for index, dock in enumerate(docks)}
    direction = {t["truck_id"]: t["direction"] for t in scenario["trucks"]}
    assigned, started, finished = {}, {}, {}
    fig, ax = plt.subplots(figsize=(12, 4.5))
    for event in events:
        truck_id = event.get("truck_id")
        if not truck_id:
            continue
        if event["event_type"] == "DOCK_ASSIGNED":
            assigned[truck_id] = event["time"]
        elif event["event_type"] == "SERVICE_STARTED":
            started[truck_id] = event["time"]
        elif event["event_type"] == "SERVICE_FINISHED":
            finished[truck_id] = event["time"]
        elif event["event_type"] == "DOCK_RELEASED":
            start = assigned.get(truck_id)
            if start is None:
                continue
            y = y_base[event["dock_id"]]
            color = "#6F9A94" if direction[truck_id] == "IN" else "#B49A80"
            service_start = started.get(truck_id, start)
            service_end = finished.get(truck_id, event["time"])
            ax.barh(y, service_start - start, left=start, height=0.55, color=color, alpha=0.35)
            ax.barh(y, service_end - service_start, left=service_start, height=0.55,
                    color=color, alpha=0.95)
            ax.barh(y, event["time"] - service_end, left=service_end, height=0.55,
                    color=color, alpha=0.35)
            ax.text((start + event["time"]) / 2, y, truck_id, ha="center", va="center",
                    fontsize=6.5, color="white")
    ax.set_yticks(range(len(docks)))
    ax.set_yticklabels(docks)
    ax.set_xlabel("仿真时间（分钟）")
    ax.set_ylabel("月台")
    ax.set_title("示例调度甘特图（JointDA，小规模合成实例）：浅色为驶入/驶出，深色为装卸")
    return save(fig, "fig12_gantt.png")


def figA1_sequence() -> Path:
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")
    actors = ["仿真引擎", "调度算法", "事件日志", "存储"]
    xs = [1.3, 4.3, 7.0, 9.0]
    for x, name in zip(xs, actors):
        ax.add_patch(plt.Rectangle((x - 0.85, 9.0), 1.7, 0.6, facecolor="#EEF1F4",
                                   edgecolor="#6F7C89"))
        ax.text(x, 9.3, name, ha="center", va="center", fontsize=9, color="#5F6B78")
        ax.plot([x, x], [0.4, 9.0], linestyle="--", color="#A5AFB9", linewidth=0.9)
    activation = {0: (4.0, 8.7), 1: (6.8, 8.5), 2: (3.3, 4.2), 3: (2.6, 3.5)}
    for idx, (bottom, top) in activation.items():
        x = xs[idx]
        ax.add_patch(plt.Rectangle((x - 0.07, bottom), 0.14, top - bottom,
                                   facecolor="#DDE3E9", edgecolor="#A5AFB9",
                                   linewidth=0.5, zorder=1))
    messages = [
        (0, 1, "select_next(就绪快照, 月台, 当前时刻, 配置)", 8.4, "sync"),
        (1, 1, "评分 / 联合匹配 / 前瞻推演（只读）", 7.6, "self"),
        (1, 0, "返回 truck_id 或 None", 6.9, "return"),
        (0, 0, "DOCK_ASSIGNED; READY → APPROACHING", 6.2, "self"),
        (0, 0, "SERVICE_FINISHED：入站卸完解锁出站", 5.5, "self"),
        (0, 0, "DOCK_RELEASED：月台释放", 4.8, "self"),
        (0, 2, "追加事件（seq, time, type, data）", 4.1, "sync"),
        (2, 3, "持久化运行与事件", 3.4, "sync"),
        (3, 0, "分页读取并回放", 2.7, "return"),
    ]
    for src, dst, label, y, kind in messages:
        if src == dst:
            x = xs[src]
            ax.add_patch(plt.Rectangle((x - 0.09, y - 0.2), 0.18, 0.4,
                                       facecolor="#F4F6F8", edgecolor="#6F7C89", zorder=2))
            ax.text(x + 0.2, y, label, ha="left", va="center", fontsize=8, color="#5F6B78")
        else:
            direction = 1 if dst > src else -1
            dashed = kind == "return"
            ax.annotate("", xy=(xs[dst] - 0.05 * direction, y),
                        xytext=(xs[src] + 0.05 * direction, y),
                        arrowprops=dict(arrowstyle=("->" if dashed else "-|>"),
                                        color=("#7A8794" if dashed else "#5E6F80"),
                                        lw=1.2, linestyle=("--" if dashed else "-")))
            ax.text((xs[src] + xs[dst]) / 2, y + 0.12, label, ha="center",
                    va="bottom", fontsize=8, color="#5F6B78")
    ax.set_title("调度调用时序（非抢占、只读快照）")
    return save(fig, "figA1_sequence.png")


def main() -> None:
    for builder in (fig04_multi_scenario, fig05_waiting_distribution, fig06_sensitivity,
                    fig07_aging, fig08_ablation, fig09_scale, fig10_mendeley,
                    fig11_quality_cost, fig12_gantt, figA1_sequence):
        builder()


if __name__ == "__main__":
    main()