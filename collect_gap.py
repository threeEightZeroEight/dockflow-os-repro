#!/usr/bin/env python3
"""补强实验：负载×依赖网格、全部车辆等待口径、DA 消融配对检验。"""
from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "vendor" / "dockflow"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent / "research"))

import simulation.engine as engine_module  # noqa: E402
from simulation import run_simulation  # noqa: E402
from simulation.competition import make_docks  # noqa: E402
from simulation.generator import generate_scenario  # noqa: E402
import qedf  # noqa: E402

qedf.install(engine_module)

OUT = Path(__file__).resolve().parent / "data" / "research"
OUT.mkdir(parents=True, exist_ok=True)
SEEDS = list(range(42, 62))
ALGORITHMS = ["edf", "spt", "aqedf", "dependency_aware", "joint_da", "rh_da"]


def scenario(total: int, dependency: float, seed: int) -> dict:
    return generate_scenario({
        "scenario_preset": "normal", "random_seed": seed,
        "inbound_count": total // 2, "outbound_count": total // 2,
        "dependency_ratio": dependency, "arrival_horizon": 120.0,
        "docks": make_docks(5),
    })


def main() -> None:
    # 1) 负载 × 依赖 网格（固定 5 月台）
    rows = []
    print("[grid] 3 规模 × 3 依赖 × 20 种子 × 6 算法")
    for total in (30, 60, 90):
        for dependency in (0.2, 0.5, 0.8):
            for seed in SEEDS:
                scene = scenario(total, dependency, seed)
                for algorithm in ALGORITHMS:
                    m = run_simulation(scene, algorithm)["metrics"]
                    rows.append({
                        "experiment": "grid", "total": total,
                        "dependency": dependency, "seed": seed,
                        "algorithm": algorithm,
                        "avg_waiting_time": m["avg_waiting_time"],
                        "outbound_deadline_miss_rate": m["outbound_deadline_miss_rate"],
                        "throughput": m["throughput"],
                    })
    with (OUT / "grid_load_dependency.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("  -> grid_load_dependency.csv", len(rows))

    # 2) 全部车辆等待（含未完成车）
    rows = []
    print("[all-wait] medium/high × 20 种子 × EDF/AQEDF")
    for level_total, dependency in ((60, 0.5), (100, 0.8)):
        for seed in SEEDS:
            scene = scenario(level_total, dependency, seed)
            for algorithm in ("edf", "aqedf"):
                trucks = run_simulation(scene, algorithm)["trucks"]
                waits = [float(t["waiting_time"]) for t in trucks]
                completed = [t for t in trucks if t["status"] == "DEPARTED"]
                rows.append({
                    "level": f"n{level_total}_d{dependency}",
                    "seed": seed, "algorithm": algorithm,
                    "all_vehicle_avg_wait": round(statistics.mean(waits), 4),
                    "completed_avg_wait": round(
                        statistics.mean(float(t["waiting_time"]) for t in completed), 4
                    ) if completed else None,
                    "completed": len(completed), "total": len(trucks),
                })
    with (OUT / "all_vehicle_wait.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("  -> all_vehicle_wait.csv", len(rows))

    # 3) DA 消融配对检验（full vs 各变体，20 种子）
    ablation = list(csv.DictReader(
        (OUT / "eg_ablation.csv").open(encoding="utf-8")
    ))
    from scipy import stats
    print("\n[ablation] full vs 变体（配对 t / Wilcoxon / Cohen's d）")
    for variant in ("no_unlock(I=0)", "no_blocked(B=0)", "no_resource(R=0)",
                    "no_traffic(P=0)", "no_wait(W=0)"):
        full = {r["seed"]: float(r["outbound_deadline_miss_rate"])
                for r in ablation if r["variant"] == "full"}
        other = {r["seed"]: float(r["outbound_deadline_miss_rate"])
                 for r in ablation if r["variant"] == variant}
        pairs = [(other[s], full[s]) for s in full if s in other]
        diffs = [x - y for x, y in pairs]
        mean = statistics.mean(diffs); sd = statistics.stdev(diffs)
        _, p = stats.ttest_rel([x for x, _ in pairs], [y for _, y in pairs])
        try:
            _, wp = stats.wilcoxon([x for x, _ in pairs], [y for _, y in pairs])
        except ValueError:
            wp = 1.0
        print(f"  {variant:18s} diff={mean:+.4f} p={p:.4g} wil={wp:.4g} d={mean/sd if sd else 0:+.3f}")


if __name__ == "__main__":
    main()