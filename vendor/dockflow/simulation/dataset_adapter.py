"""Deterministic, auditable dual-flow scenario construction for DockFlow.

All vehicle arrivals, destination codes, pallet deadlines and outbound truck
deadlines are original research input. Assignment, truck capacity, handling
speed and work durations are explicit MODEL ASSUMPTIONS, not source columns.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .mendeley_reader import DatasetFormatError, read_instance, workbook_sha256

DEFAULT_WORKBOOK = Path("data/raw/mendeley_crossdock/DoorSet_2/LL_21-30.xlsx")
DEFAULT_OUTPUT = Path("data/processed/scenario_21.json")


def _number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise DatasetFormatError(f"{field}: not a number: {value}") from exc
    if not math.isfinite(number) or number < 0:
        raise DatasetFormatError(f"{field}: must be finite and nonnegative")
    return number


def _integer(value: Any, field: str) -> int:
    number = _number(value, field)
    if not number.is_integer():
        raise DatasetFormatError(f"{field}: expected an integer")
    return int(number)


def _nonempty_unique(rows: list[dict], field: str) -> dict[int, dict]:
    output: dict[int, dict] = {}
    for row in rows:
        index = _integer(row[field], field)
        if index < 1 or index in output:
            raise DatasetFormatError(f"Duplicate or invalid {field}: {index}")
        output[index] = row
    return output


def build_scenario(
    records: dict[str, list[dict[str, str]]], *, instance_id: int,
    door_set: int = 2, arrival_window: float = 480.0,
    outbound_capacity: int = 40, pallets_per_minute: float = 2.0,
    setup_minutes: float = 2.0, approach_minutes: float = 0.5,
    exit_minutes: float = 0.5,
) -> tuple[dict, dict]:
    """Convert one complete instance into a consistent bounded Scenario.

    Only matching pallets are assigned to outbound vehicles; unmatched pallets
    remain associated with inbound vehicles with outbound_truck_id = null.
    Outbound arrivals without assigned pallets are excluded, never disguised
    as loaded shipments. Metadata accounts for all dropped/unmatched records.
    """
    if door_set not in (1, 2, 3, 4, 5):
        raise ValueError("door_set must be 1..5")
    if _number(arrival_window, "arrival_window") == 0:
        raise ValueError("arrival_window must be positive")
    if _integer(outbound_capacity, "outbound_capacity") < 1:
        raise ValueError("outbound_capacity must be positive")
    if _number(pallets_per_minute, "pallets_per_minute") == 0:
        raise ValueError("pallets_per_minute must be positive")
    for label, value in (("setup_minutes", setup_minutes),
                         ("approach_minutes", approach_minutes),
                         ("exit_minutes", exit_minutes)):
        _number(value, label)
    if not isinstance(instance_id, int) or instance_id < 1:
        raise ValueError("instance_id must be positive")
    counts = {1: 2, 2: 5, 3: 10, 4: 15, 5: 20}
    n_docks = counts[door_set]
    ins: dict[int, dict] = {}
    outs: dict[int, dict] = {}
    all_in = _nonempty_unique(records["inboundTrucks"], "Truck ID")
    all_out = _nonempty_unique(records["outboundTrucks"], "Truck ID")
    pallets_raw = _nonempty_unique(records["pallets"], "Pallet ID")
    for index, row in all_in.items():
        arrive = _number(row["Truck arrival time (min)"], "inbound.arrival")
        if arrive < arrival_window:
            ins[index] = {"arrival_time": arrive, "pallet_ids": []}
    for index, row in all_out.items():
        arrive = _number(row["Arrival time (min)"], "outbound.arrival")
        due = _number(row["Due date (min)"], "outbound.deadline")
        destination = _integer(row["Destination"], "outbound.destination")
        if destination not in (1, 2, 3):
            raise DatasetFormatError(f"Invalid outbound destination: {destination}")
        if arrive < arrival_window:
            outs[index] = {
                "arrival_time": arrive, "deadline": due,
                "destination": destination, "pallet_ids": [],
            }
    # Validate every source pallet FK; selected pallets are those carried by
    # an inbound vehicle arriving in the window (no arbitrary row slicing).
    selected: dict[int, dict] = {}
    for index, row in pallets_raw.items():
        source = _integer(row["TruckId"], "pallet.TruckId")
        if source not in all_in:
            raise DatasetFormatError(f"Pallet {index}: unknown inbound truck {source}")
        due = _number(row["Due date (min)"], "pallet.due_date")
        destination = _integer(row["Destination"], "pallet.destination")
        if destination not in (1, 2, 3):
            raise DatasetFormatError(f"Pallet {index}: invalid destination {destination}")
        category = str(row["Type"]).strip()
        if category not in ("A", "B", "C"):
            raise DatasetFormatError(f"Pallet {index}: invalid type {category}")
        if source in ins:
            selected[index] = {
                "pallet_id": f"P{index}", "inbound_truck_id": f"I{source}",
                "outbound_truck_id": None, "destination": destination,
                "due_date": due, "type": category,
            }
            ins[source]["pallet_ids"].append(f"P{index}")
    # Use the full selected inbound load for service time, INCLUDING pallets
    # which cannot be matched to an outbound truck in this bounded window.
    in_service = {
        i: float(setup_minutes + len(row["pallet_ids"]) / pallets_per_minute)
        for i, row in ins.items()
    }
    available_by_dest: dict[int, list[int]] = defaultdict(list)
    for i, row in outs.items():
        if row["deadline"] >= row["arrival_time"]:
            available_by_dest[row["destination"]].append(i)
    for candidates in available_by_dest.values():
        candidates.sort(key=lambda i: (outs[i]["deadline"], outs[i]["arrival_time"], i))
    not_matched = Counter()
    for pid, pallet in sorted(selected.items(), key=lambda item: (
        item[1]["due_date"], ins[int(item[1]["inbound_truck_id"][1:])]["arrival_time"], item[0]
    )):
        source = int(pallet["inbound_truck_id"][1:])
        # Inbound unload cannot even theoretically finish before this time.
        earliest_supply = ins[source]["arrival_time"] + approach_minutes + in_service[source]
        choices = [
            out_id for out_id in available_by_dest[pallet["destination"]]
            if outs[out_id]["deadline"] <= pallet["due_date"]
            and outs[out_id]["deadline"] >= earliest_supply
        ]
        if not choices:
            not_matched["no_compatible_departure"] += 1
            continue
        candidates = [i for i in choices if len(outs[i]["pallet_ids"]) < outbound_capacity]
        if not candidates:
            not_matched["all_compatible_trucks_at_capacity"] += 1
            continue
        # Prefer to supply empty outbound trucks, then earlier deadlines.
        chosen = min(candidates, key=lambda i: (
            len(outs[i]["pallet_ids"]) != 0, outs[i]["deadline"],
            len(outs[i]["pallet_ids"]), i,
        ))
        outs[chosen]["pallet_ids"].append(pallet["pallet_id"])
        pallet["outbound_truck_id"] = f"O{chosen}"
    filled_out = {i: row for i, row in outs.items() if row["pallet_ids"]}
    trucks: list[dict] = []
    for i, row in sorted(ins.items(), key=lambda x: x[0]):
        trucks.append({
            "truck_id": f"I{i}", "direction": "IN",
            "arrival_time": row["arrival_time"],
            "service_duration": in_service[i],
            "departure_deadline": None, "depends_on": [],
            "allowed_dock_ids": None, "pallet_ids": sorted(row["pallet_ids"], key=lambda s: int(s[1:])),
        })
    for i, row in sorted(filled_out.items(), key=lambda x: x[0]):
        pallet_ids = sorted(row["pallet_ids"], key=lambda s: int(s[1:]))
        sources = sorted({
            selected[int(pid[1:])]["inbound_truck_id"]
            for pid in pallet_ids
        }, key=lambda s: int(s[1:]))
        trucks.append({
            "truck_id": f"O{i}", "direction": "OUT",
            "arrival_time": row["arrival_time"],
            "service_duration": float(setup_minutes + len(pallet_ids) / pallets_per_minute),
            "departure_deadline": row["deadline"], "destination": row["destination"],
            "depends_on": sources, "allowed_dock_ids": None, "pallet_ids": pallet_ids,
        })
    docks = [
        {"dock_id": f"IN{j:02}", "mode": "IN", "slot_index": j - 1}
        for j in range(1, n_docks + 1)
    ] + [
        {"dock_id": f"OUT{j:02}", "mode": "OUT", "slot_index": n_docks + j - 1}
        for j in range(1, n_docks + 1)
    ]
    service_budget = sum(t["service_duration"] + approach_minutes + exit_minutes for t in trucks)
    max_time = float(max([arrival_window] + [row["deadline"] for row in filled_out.values()])
                     + service_budget + 1.0)
    scenario = {
        "schema_version": "1.2",
        "scenario_id": f"mendeley-ds{door_set}-inst{instance_id}-w{int(arrival_window)}-c{outbound_capacity}",
        "scenario_source": "mendeley_ch5",
        "scenario_preset": "benchmark",
        "instance_id": instance_id, "door_set": door_set,
        "random_seed": None, "time_unit": "minute",
        "arrival_horizon": float(arrival_window),
        "max_simulation_time": max_time,
        "approach_duration": float(approach_minutes), "exit_duration": float(exit_minutes),
        "docks": docks, "trucks": trucks,
        "pallets": [selected[i] for i in sorted(selected)],
        "model_assumptions": {
            "outbound_capacity_pallets": outbound_capacity,
            "handling_rate_pallets_per_minute": float(pallets_per_minute),
            "service_setup_minutes": float(setup_minutes),
            "assignment_policy": "same_destination_earliest_feasible_deadline_spread_to_empty",
            "input_vehicle_cutoff_rule": "arrival_time < arrival_horizon",
            "unmatched_pallets_policy": "retain_inbound_inventory_not_outbound_assigned",
        },
    }
    metadata = {
        "scenario_id": scenario["scenario_id"],
        "source": "Mendeley Dataset_ch5 / PhD research synthetic benchmark",
        "source_record_type": "research_benchmark_not_company_operational_log",
        "instance_id": instance_id, "door_set": door_set,
        "arrival_window_minutes": float(arrival_window),
        "original_instance_counts": {
            "inbound_trucks": len(all_in), "outbound_trucks": len(all_out),
            "pallets": len(pallets_raw),
        },
        "selected_window_counts": {
            "inbound_trucks": len(ins), "outbound_truck_candidates": len(outs),
            "inbound_pallets": len(selected),
        },
        "exported_counts": {
            "inbound_trucks": len(ins), "outbound_trucks": len(filled_out),
            "assigned_pallets": sum(bool(p["outbound_truck_id"]) for p in selected.values()),
            "unassigned_pallets": sum(not p["outbound_truck_id"] for p in selected.values()),
            "excluded_empty_outbound_trucks": len(outs) - len(filled_out),
        },
        "unmatched_reasons": dict(not_matched),
        "model_assumptions": scenario["model_assumptions"],
        "selection_note": "Source is unchanged; all assumed mappings are explicit and reproducible.",
    }
    validate_scenario(scenario)
    return scenario, metadata


def validate_scenario(scenario: dict) -> None:
    """Reject orphan pallets, invalid dependencies and capacity violations."""
    trucks = scenario["trucks"]
    pallets = scenario["pallets"]
    ids = [t["truck_id"] for t in trucks]
    if len(ids) != len(set(ids)):
        raise DatasetFormatError("Duplicate scenario truck IDs")
    by_id = {t["truck_id"]: t for t in trucks}
    by_pallet = {p["pallet_id"]: p for p in pallets}
    if len(by_pallet) != len(pallets):
        raise DatasetFormatError("Duplicate pallet IDs")
    outbound_pallets = set()
    for truck in trucks:
        for pid in truck["pallet_ids"]:
            if pid not in by_pallet:
                raise DatasetFormatError(f"Missing pallet {pid}")
            pallet = by_pallet[pid]
            foreign = pallet["inbound_truck_id"] if truck["direction"] == "IN" else pallet["outbound_truck_id"]
            if foreign != truck["truck_id"]:
                raise DatasetFormatError(f"Invalid assignment for pallet {pid}")
            if truck["direction"] == "OUT":
                if pid in outbound_pallets:
                    raise DatasetFormatError(f"Duplicate outbound assignment {pid}")
                outbound_pallets.add(pid)
                if pallet["destination"] != truck["destination"]:
                    raise DatasetFormatError(f"Wrong destination {pid}")
                if pallet["due_date"] < truck["departure_deadline"]:
                    raise DatasetFormatError(f"Pallet {pid} cannot satisfy chosen departure deadline")
        if truck["direction"] == "OUT":
            if not truck["pallet_ids"]:
                raise DatasetFormatError("Empty outgoing truck")
            actual = {by_pallet[pid]["inbound_truck_id"] for pid in truck["pallet_ids"]}
            if set(truck["depends_on"]) != actual or not actual <= by_id.keys():
                raise DatasetFormatError("Outbound dependencies disagree with pallets")
            if len(truck["pallet_ids"]) > scenario["model_assumptions"]["outbound_capacity_pallets"]:
                raise DatasetFormatError("Outbound capacity exceeded")
        elif truck["depends_on"]:
            raise DatasetFormatError("Inbound truck cannot have dependencies")
    for pallet in pallets:
        if pallet["inbound_truck_id"] not in by_id:
            raise DatasetFormatError("Pallet source not selected")
        if pallet["outbound_truck_id"] is not None and pallet["pallet_id"] not in outbound_pallets:
            raise DatasetFormatError("Pallet assigned to nonexistent outbound truck")


def export_scenario(
    workbook: str | Path = DEFAULT_WORKBOOK, *, instance_id: int = 21,
    door_set: int = 2, arrival_window: float = 480.0, outbound_capacity: int = 40,
    pallets_per_minute: float = 2.0, setup_minutes: float = 2.0,
    output: str | Path = DEFAULT_OUTPUT,
) -> tuple[dict, dict]:
    raw = read_instance(workbook, instance_id)
    scenario, metadata = build_scenario(
        raw, instance_id=instance_id, door_set=door_set,
        arrival_window=arrival_window, outbound_capacity=outbound_capacity,
        pallets_per_minute=pallets_per_minute, setup_minutes=setup_minutes,
    )
    workbook = Path(workbook)
    metadata["source_workbook"] = workbook.as_posix()
    metadata["source_sha256"] = workbook_sha256(workbook)
    scenario["source_info"] = {
        "dataset": "Mendeley Dataset_ch5",
        "source_workbook": workbook.as_posix(),
        "source_sha256": metadata["source_sha256"],
        "instance_id": instance_id,
        "research_benchmark": True,
    }
    dest = Path(output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = dest.with_name(dest.stem + "_metadata.json")
    for path, data in ((dest, scenario), (metadata_path, metadata)):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return scenario, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--instance", type=int, default=21)
    parser.add_argument("--door-set", type=int, default=2)
    parser.add_argument("--arrival-window", type=float, default=480.0)
    parser.add_argument("--capacity", type=int, default=40)
    parser.add_argument("--pallets-per-minute", type=float, default=2.0)
    parser.add_argument("--setup-minutes", type=float, default=2.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    options = parser.parse_args()
    scenario, metadata = export_scenario(
        options.input, instance_id=options.instance, door_set=options.door_set,
        arrival_window=options.arrival_window, outbound_capacity=options.capacity,
        pallets_per_minute=options.pallets_per_minute,
        setup_minutes=options.setup_minutes, output=options.output,
    )
    print(json.dumps({
        "scenario_id": scenario["scenario_id"], "output": str(options.output),
        "counts": metadata["exported_counts"],
        "unmatched_reasons": metadata["unmatched_reasons"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
