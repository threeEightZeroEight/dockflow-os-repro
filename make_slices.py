#!/usr/bin/env python3
"""从公开冻结实例派生 3 个时间窗切片（真实实例切片，非独立数据集）。"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "vendor" / "dockflow"))
sys.path.insert(0, str(REPO_ROOT))

from simulation.models import validate_scenario  # noqa: E402

SOURCE = REPO_ROOT / "vendor" / "dockflow" / "scenario_21.json"
OUT_DIR = Path(__file__).resolve().parent / "research" / "slices"

WINDOWS = [("early", 0.0, 160.0), ("middle", 160.0, 320.0), ("late", 320.0, 480.0)]


def slice_scenario(source: dict, name: str, start: float, end: float) -> dict:
    scene = copy.deepcopy(source)
    by_id = {t["truck_id"]: t for t in scene["trucks"]}

    inbound = [t for t in scene["trucks"]
               if t["direction"] == "IN" and start <= t["arrival_time"] < end]
    kept_in = {t["truck_id"] for t in inbound}
    outbound = []
    for truck in scene["trucks"]:
        if truck["direction"] != "OUT" or not (start <= truck["arrival_time"] < end):
            continue
        # Keep the outbound only if all predecessors are retained; otherwise
        # pull the missing predecessors in (deterministic, documented).
        missing = [d for d in truck["depends_on"] if d not in kept_in]
        for dep in missing:
            kept_in.add(dep)
            inbound.append(by_id[dep])
        outbound.append(truck)

    trucks = inbound + outbound
    trucks.sort(key=lambda t: t["truck_id"])
    kept_ids = {t["truck_id"] for t in trucks}

    if scene.get("pallets"):
        scene["pallets"] = [
            p for p in scene["pallets"]
            if p["inbound_truck_id"] in kept_ids
            and (p.get("outbound_truck_id") is None or p["outbound_truck_id"] in kept_ids)
        ]
    # Keep pallet manifests consistent with the retained pallets.
    manifest: dict[str, list[str]] = {}
    for p in scene.get("pallets", []):
        for key in ("inbound_truck_id", "outbound_truck_id"):
            tid = p.get(key)
            if tid:
                manifest.setdefault(tid, []).append(p["pallet_id"])
    for truck in trucks:
        if "pallet_ids" in truck:
            truck["pallet_ids"] = sorted(manifest.get(truck["truck_id"], []))

    scene["trucks"] = trucks
    max_arrival = max(t["arrival_time"] for t in trucks)
    horizon = max(float(end), max_arrival + 1.0)
    scene["arrival_horizon"] = horizon
    scene["max_simulation_time"] = horizon + sum(
        t["service_duration"] + scene["approach_duration"] + scene["exit_duration"]
        for t in trucks
    ) + 1.0
    basis = json.dumps({k: v for k, v in scene.items() if k != "scenario_id"},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]
    scene["scenario_id"] = f"mendeley-slice-{name}-{digest}"
    scene.setdefault("source_info", {})
    scene["source_info"]["derivation"] = {
        "kind": "time-window slice of the public frozen instance",
        "window_minutes": [start, end],
        "note": "derived instance, not an independent dataset",
    }
    validate_scenario(scene)
    return scene


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = []
    for name, start, end in WINDOWS:
        scene = slice_scenario(source, name, start, end)
        path = OUT_DIR / f"slice_{name}.json"
        path.write_text(json.dumps(scene, ensure_ascii=False), encoding="utf-8")
        inbound = sum(1 for t in scene["trucks"] if t["direction"] == "IN")
        outbound = len(scene["trucks"]) - inbound
        summary.append({"slice": name, "window": [start, end],
                        "inbound": inbound, "outbound": outbound,
                        "pallets": len(scene.get("pallets", [])),
                        "scenario_id": scene["scenario_id"]})
        print(f"  {name}: IN={inbound} OUT={outbound} pallets={len(scene.get('pallets', []))}")
    (OUT_DIR / "slices_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("切片实例已生成：", OUT_DIR.relative_to(REPO_ROOT))


if __name__ == "__main__":
    main()