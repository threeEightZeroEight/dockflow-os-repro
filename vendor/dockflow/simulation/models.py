"""Contract v1.3 scenario validation for generated and Mendeley dual-flow inputs.

This module only checks input integrity. Runtime states and scheduling decisions
belong to the event engine and the separate scheduler team, respectively.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any


class ScenarioValidationError(ValueError):
    """A scenario violates the shared DockFlow input contract."""


def _fail(message: str) -> None:
    raise ScenarioValidationError(message)


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        _fail(f"{field} must be {'positive' if positive else 'nonnegative'} and finite")
    return number


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{field} must be a nonempty string ID")
    return value


def validate_scenario(scenario: dict) -> None:
    """Raise ScenarioValidationError if a v1.2 dual-flow scenario is invalid."""
    if not isinstance(scenario, dict):
        _fail("Scenario must be a JSON object")
    if scenario.get("schema_version") != "1.2":
        _fail("Scenario schema_version must be 1.2")
    _id(scenario.get("scenario_id"), "scenario_id")
    source = scenario.get("scenario_source", "generated")
    if source not in ("generated", "mendeley_ch5"):
        _fail("Unsupported scenario_source in dual-flow simulator")
    if scenario.get("scenario_preset") not in ("normal", "rush", "heavy", "benchmark"):
        _fail("Invalid scenario_preset")
    horizon = _number(scenario.get("arrival_horizon"), "arrival_horizon", positive=True)
    cap = _number(scenario.get("max_simulation_time"), "max_simulation_time", positive=True)
    if cap <= horizon:
        _fail("max_simulation_time must be after arrival_horizon")
    _number(scenario.get("approach_duration"), "approach_duration")
    _number(scenario.get("exit_duration"), "exit_duration")
    docks = scenario.get("docks")
    trucks = scenario.get("trucks")
    if not isinstance(docks, list) or not docks:
        _fail("Scenario must have nonempty docks")
    if not isinstance(trucks, list) or not trucks:
        _fail("Scenario must have nonempty trucks")
    dock_by_id: dict[str, dict] = {}
    slots: set[int] = set()
    for dock in docks:
        if not isinstance(dock, dict):
            _fail("Every dock must be an object")
        did = _id(dock.get("dock_id"), "dock_id")
        if did in dock_by_id:
            _fail(f"Duplicate dock_id {did}")
        if dock.get("mode") not in ("IN", "OUT", "FLEX"):
            _fail(f"Invalid dock mode for {did}")
        slot = dock.get("slot_index")
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0 or slot in slots:
            _fail(f"Invalid/duplicate slot_index for {did}")
        slots.add(slot)
        dock_by_id[did] = dock

    truck_by_id: dict[str, dict] = {}
    for truck in trucks:
        if not isinstance(truck, dict):
            _fail("Every truck must be an object")
        tid = _id(truck.get("truck_id"), "truck_id")
        if tid in truck_by_id:
            _fail(f"Duplicate truck_id {tid}")
        if truck.get("direction") not in ("IN", "OUT"):
            _fail(f"Invalid truck direction for {tid}")
        arrival = _number(truck.get("arrival_time"), f"{tid}.arrival_time")
        if arrival >= horizon:
            _fail(f"{tid} arrives outside arrival_horizon")
        _number(truck.get("service_duration"), f"{tid}.service_duration")
        deadline = truck.get("departure_deadline")
        if truck["direction"] == "OUT":
            if deadline is None:
                _fail(f"OUT {tid} requires a departure_deadline")
            _number(deadline, f"{tid}.departure_deadline")
        elif deadline is not None:
            _fail(f"IN {tid} must have departure_deadline=null")
        dependencies = truck.get("depends_on")
        if not isinstance(dependencies, list) or len(set(map(str, dependencies))) != len(dependencies):
            _fail(f"{tid} depends_on must be a list with unique IDs")
        for dependency in dependencies:
            _id(dependency, f"{tid}.depends_on")
        if truck["direction"] == "IN" and dependencies:
            _fail(f"IN {tid} cannot have dependencies")
        allowed = truck.get("allowed_dock_ids")
        if allowed is not None:
            if not isinstance(allowed, list) or any(not isinstance(d, str) for d in allowed):
                _fail(f"{tid} allowed_dock_ids must be null or an ID list")
            if len(set(allowed)) != len(allowed):
                _fail(f"Duplicate allowed_dock_ids for {tid}")
            if not set(allowed) <= dock_by_id.keys():
                _fail(f"{tid} allowed_dock_ids refers to unknown docks")
        if not any(
            dock["mode"] in (truck["direction"], "FLEX")
            and (allowed is None or dock["dock_id"] in allowed)
            for dock in docks
        ):
            _fail(f"{tid} has no compatible dock")
        if "pallet_ids" in truck:
            ids = truck["pallet_ids"]
            if not isinstance(ids, list) or len(set(ids)) != len(ids):
                _fail(f"{tid}.pallet_ids must be unique IDs")
            for pid in ids:
                _id(pid, f"{tid}.pallet_ids")
        truck_by_id[tid] = truck

    for truck in trucks:
        for dep in truck["depends_on"]:
            if dep not in truck_by_id or truck_by_id[dep]["direction"] != "IN":
                _fail(f"{truck['truck_id']} depends on non-IN or missing truck {dep}")

    if source == "mendeley_ch5":
        pallets = scenario.get("pallets")
        if not isinstance(pallets, list):
            _fail("Mendeley scenario must contain pallets")
        pallet_by_id = {}
        for pallet in pallets:
            if not isinstance(pallet, dict):
                _fail("Invalid pallet")
            pid = _id(pallet.get("pallet_id"), "pallet_id")
            if pid in pallet_by_id:
                _fail(f"Duplicate pallet {pid}")
            origin = _id(pallet.get("inbound_truck_id"), f"{pid}.inbound_truck_id")
            dest = pallet.get("outbound_truck_id")
            if dest is not None:
                _id(dest, f"{pid}.outbound_truck_id")
            if origin not in truck_by_id or truck_by_id[origin]["direction"] != "IN":
                _fail(f"Invalid origin for {pid}")
            if dest is not None and (
                dest not in truck_by_id or truck_by_id[dest]["direction"] != "OUT"
            ):
                _fail(f"Invalid destination truck for {pid}")
            _number(pallet.get("due_date"), f"{pid}.due_date")
            if pallet.get("destination") not in (1, 2, 3) or isinstance(pallet.get("destination"), bool):
                _fail(f"Invalid destination for {pid}")
            if pallet.get("type") not in ("A", "B", "C"):
                _fail(f"Invalid type for {pid}")
            pallet_by_id[pid] = pallet
        for truck in trucks:
            tid = truck["truck_id"]
            if "pallet_ids" not in truck:
                _fail(f"Mendeley truck {tid} must have pallet_ids")
            actual = {
                pallet["pallet_id"] for pallet in pallets
                if pallet["inbound_truck_id" if truck["direction"] == "IN" else "outbound_truck_id"] == tid
            }
            if set(truck["pallet_ids"]) != actual:
                _fail(f"Pallet manifest inconsistent for {tid}")
            if truck["direction"] == "OUT":
                origins = {pallet_by_id[pid]["inbound_truck_id"] for pid in truck["pallet_ids"]}
                if set(truck["depends_on"]) != origins:
                    _fail(f"OUT {tid} has incorrect depends_on")
                if any(pallet_by_id[pid]["destination"] != truck.get("destination")
                       for pid in truck["pallet_ids"]):
                    _fail(f"OUT {tid} has mismatched pallet destination")
