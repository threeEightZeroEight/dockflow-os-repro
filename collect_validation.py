#!/usr/bin/env python3
"""独立验证：选择集定 λ/γ，报告集评估；逐实例不劣比例、失败案例、γ 敏感性。

选择集：seeds 200-209；报告集：seeds 300-319（与既往 42-61 完全独立）。
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "vendor" / "dockflow"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent / "research"))

import simulation.engine as engine_module  # noqa: E402
from simulation import run_simulation  # noqa: E402
from simulation.competition import generate_competition_scenario, make_docks  # noqa: E402
from simulation.generator import generate_scenario  # noqa: E402
import qedf  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "data" / "research"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SELECT_SEEDS = list(range(200, 220))
REPORT_SEEDS = list(range(300, 320))
LAMBDAS = [0.25, 0.5, 0.75, 1.0]
GAMMAS = [0.5, 1.0, 1.5, 2.0, 3.0]


def install_variant(engine, discount: float, gate: float) -> None:
    original = engine._make_scheduler

    def factory(algorithm: str):
        if algorithm == "aqedf_v":
            return qedf.AdaptiveQueueEDF(discount, gate)
        return original(algorithm)

    engine._make_scheduler = factory
    engine.ALGORITHMS = frozenset((*engine.ALGORITHMS, "aqedf_v"))


def scenario(level: str, seed: int) -> dict:
    return generate_competition_scenario(level, seed)


def big(total: int, seed: int) -> dict:
    return generate_scenario({
        "scenario_preset": "normal", "random_seed": seed,
        "inbound_count": total // 2, "outbound_count": total // 2,
        "dependency_ratio": 0.5, "arrival_horizon": 120.0,
        "docks": make_docks(5),
    })


def main() -> None:
    # ---------- 选择阶段：仅使用 SELECT_SEEDS ----------
    print("[选择集] seeds 200-209，扫描 λ × γ")
    edf_medium = statistics.mean(
        run_simulation(scenario("medium", s), "edf")["metrics"]["outbound_deadline_miss_rate"]
        for s in SELECT_SEEDS
    )
    edf_high = statistics.mean(
        run_simulation(scenario("high", s), "edf")["metrics"]["outbound_deadline_miss_rate"]
        for s in SELECT_SEEDS
    )
    best = None
    selection_rows = []
    for discount in LAMBDAS:
        for gate in GAMMAS:
            install_variant(engine_module, discount, gate)
            med = statistics.mean(
                run_simulation(scenario("medium", s), "aqedf_v")["metrics"]["outbound_deadline_miss_rate"]
                for s in SELECT_SEEDS
            )
            high = statistics.mean(
                run_simulation(scenario("high", s), "aqedf_v")["metrics"]["outbound_deadline_miss_rate"]
                for s in SELECT_SEEDS
            )
            selection_rows.append({"lambda": discount, "gamma": gate,
                                   "select_medium_miss": round(med, 4),
                                   "select_high_miss": round(high, 4)})
            # 选择准则：medium 不劣于 EDF（+0.005 容差）前提下，最小化 high 逾期率
            if med <= edf_medium + 0.005 and (best is None or high < best[2]):
                best = (discount, gate, high)
    print(f"  选择集 EDF: medium={edf_medium:.3f}, high={edf_high:.3f}")
    for row in selection_rows:
        mark = "  <== 选中" if (row["lambda"], row["gamma"]) == (best[0], best[1]) else ""
        print(f"  λ={row['lambda']:.2f} γ={row['gamma']:.1f}  medium={row['select_medium_miss']:.3f}  high={row['select_high_miss']:.3f}{mark}")
    with (OUT_DIR / "validation_selection.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(selection_rows[0].keys()))
        writer.writeheader()
        writer.writerows(selection_rows)

    discount, gate = best[0], best[1]
    print(f"\n[报告集] 使用固定 λ={discount}, γ={gate}，在 seeds 300-319 上评估")

    # ---------- 报告阶段：仅使用 REPORT_SEEDS ----------
    install_variant(engine_module, discount, gate)
    rows = []
    per_instance = []
    cases = [("medium", lambda s: scenario("medium", s)),
             ("high", lambda s: scenario("high", s)),
             ("n120", lambda s: big(120, s)),
             ("n160", lambda s: big(160, s))]
    for label, build in cases:
        seeds = REPORT_SEEDS if label in ("medium", "high") else REPORT_SEEDS[:10]
        for seed in seeds:
            edf_m = run_simulation(build(seed), "edf")["metrics"]
            aq_m = run_simulation(build(seed), "aqedf_v")["metrics"]
            rows.append({"scenario": label, "seed": seed,
                         "edf_miss": edf_m["outbound_deadline_miss_rate"],
                         "aqedf_miss": aq_m["outbound_deadline_miss_rate"],
                         "edf_wait": edf_m["avg_waiting_time"],
                         "aqedf_wait": aq_m["avg_waiting_time"]})
            per_instance.append({
                "scenario": label, "seed": seed,
                "miss_delta": aq_m["outbound_deadline_miss_rate"] - edf_m["outbound_deadline_miss_rate"],
                "wait_delta": aq_m["avg_waiting_time"] - edf_m["avg_waiting_time"],
            })
    with (OUT_DIR / "validation_report.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # 逐实例不劣比例（容差 0.01，即 1 个百分点）
    summary = {}
    for label, _ in cases:
        subset = [p for p in per_instance if p["scenario"] == label]
        non_inferior = sum(1 for p in subset if p["miss_delta"] <= 0.01)
        failures = [
            {"seed": p["seed"], "miss_delta": round(p["miss_delta"], 4),
             "wait_delta": round(p["wait_delta"], 4)}
            for p in subset if p["miss_delta"] > 0.01
        ]
        summary[label] = {
            "instances": len(subset),
            "non_inferior": non_inferior,
            "ratio": round(non_inferior / len(subset), 3),
            "mean_miss_delta": round(statistics.mean(p["miss_delta"] for p in subset), 4),
            "worst_miss_delta": round(max(p["miss_delta"] for p in subset), 4),
            "failures": failures,
        }
    (OUT_DIR / "validation_summary.json").write_text(
        json.dumps({"selected": {"lambda": discount, "gamma": gate},
                    "selection_set": SELECT_SEEDS,
                    "report_set": REPORT_SEEDS,
                    "by_scenario": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps({"selected": {"lambda": discount, "gamma": gate},
                      "by_scenario": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()