#!/usr/bin/env python3
"""从原始 JSON 重算关键数值，并与 expected_metrics.json 比对。"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESEARCH = ROOT / "data" / "research"


def mean(rows: list[dict], key: str) -> float:
    return statistics.mean(row[key] for row in rows)


def approx(actual: float, expected: float, tol: float = 0.01) -> bool:
    return abs(actual - expected) <= tol


def main() -> int:
    expected = json.loads((ROOT / "data" / "expected_metrics.json").read_text(encoding="utf-8"))
    failures: list[str] = []

    cpsat = json.loads((RESEARCH / "cpsat_offline.json").read_text(encoding="utf-8"))
    table10 = expected["table10"]
    actual = {
        "offline": mean([row["offline"] for row in cpsat], "objective_minutes"),
        "edf": mean([row["online"] for row in cpsat], "edf"),
        "aqedf": mean([row["online"] for row in cpsat], "aqedf"),
        "rh_da": mean([row["online"] for row in cpsat], "rh_da"),
        "spt": mean([row["online"] for row in cpsat], "spt"),
    }
    for key, value in table10["cpsat"].items():
        if not approx(actual[key], value, table10.get("tolerance", 0.01)):
            failures.append(f"CP-SAT {key}: {actual[key]:.3f} != {value}")

    for name, key in (("offline_bruteforce.json", "bruteforce6"),
                      ("offline_bruteforce_8.json", "bruteforce8")):
        rows = json.loads((RESEARCH / name).read_text(encoding="utf-8"))
        values = {
            "offline": mean(rows, "offline_optimum"),
            "edf": mean([row["online"] for row in rows], "edf"),
            "aqedf": mean([row["online"] for row in rows], "aqedf"),
            "rh_da": mean([row["online"] for row in rows], "rh_da"),
            "spt": mean([row["online"] for row in rows], "spt"),
        }
        for metric, value in table10[key].items():
            if not approx(values[metric], value, table10.get("tolerance", 0.01)):
                failures.append(f"{key} {metric}: {values[metric]:.3f} != {value}")

    validation = json.loads((RESEARCH / "validation_summary.json").read_text(encoding="utf-8"))
    by_scenario = validation["by_scenario"]
    total = sum(item["non_inferior"] for item in by_scenario.values())
    total_instances = sum(item["instances"] for item in by_scenario.values())
    checks = {
        "medium_non_inferior": by_scenario["medium"]["non_inferior"],
        "high_non_inferior": by_scenario["high"]["non_inferior"],
        "n120_non_inferior": by_scenario["n120"]["non_inferior"],
        "n160_non_inferior": by_scenario["n160"]["non_inferior"],
        "total_non_inferior": total,
        "total_instances": total_instances,
    }
    for key, value in expected["validation"].items():
        if checks.get(key) != value:
            failures.append(f"validation {key}: {checks.get(key)} != {value}")

    selected = validation["selected"]
    if (selected["lambda"], selected["gamma"]) != tuple(expected["selected"]):
        failures.append(f"selected: {selected} != {expected['selected']}")

    required = ["figures/fig04_multi_scenario.png",
                "figures/fig10_mendeley.png", "figures/fig15_validation.png"]
    for rel in required:
        if not (ROOT / rel).exists():
            failures.append(f"missing artifact: {rel}")

    if failures:
        print("校验失败：")
        for item in failures:
            print("  -", item)
        return 1
    print("校验通过：表 10、确认集不劣计数、选择集参数与关键产物一致。")
    print("  CP-SAT 均值:", {k: round(v, 3) for k, v in actual.items()})
    print("  确认集不劣:", checks)
    return 0


if __name__ == "__main__":
    sys.exit(main())