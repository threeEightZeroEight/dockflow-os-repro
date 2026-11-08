"""Deterministic non-preemptive, multi-dock discrete-event simulation.

Scheduler priority belongs exclusively to scheduler.create_scheduler(). The
simulation owns world state, dependencies, time, resource constraints, metrics
and the event log, and never modifies its input Scenario.
"""
from __future__ import annotations

import copy
import heapq
import math
from itertools import count
from time import perf_counter

from scheduler.base import AlgorithmType

from .dependency import dependency_scores
from .metrics import build_result
from .models import validate_scenario

ALGORITHMS = frozenset(("fcfs", "spt", "edf", "edf_aging", "dependency_aware", "joint_da", "rh_da"))
# Finish/unlock, dock release, docking, then arrival at equal timestamps.
_PRIORITY = {"FINISH": 0, "EXIT": 1, "DOCKED": 2, "ARRIVAL": 3}
_DEPENDENCY_ALGORITHMS = frozenset(("dependency_aware", "joint_da", "rh_da"))


def validate_settings(settings: dict | None) -> dict:
    """Resolve the single physical model and reject removed logistics options."""
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    if settings.get("simulation_mode", "baseline") != "baseline":
        raise ValueError("simulation_mode must be 'baseline'; enhanced is no longer supported")
    removed = sorted(str(key) for key in settings
                     if isinstance(key, str) and (key.startswith(("forklift_", "buffer_"))
                                                  or key == "dock_offline_schedule"))
    if removed:
        raise ValueError(f"Unsupported physical setting(s): {', '.join(removed)}")
    for name, default, positive in (("aging_threshold", 12.0, True),
                                     ("long_wait_threshold", 15.0, False)):
        value = settings.get(name, default)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or (value <= 0 if positive else value < 0)):
            domain = "positive" if positive else "nonnegative"
            raise ValueError(f"{name} must be a {domain} finite number")
    resolved = copy.deepcopy(settings)
    resolved.update(simulation_mode="baseline",
                    aging_threshold=float(settings.get("aging_threshold", 12.0)),
                    long_wait_threshold=float(settings.get("long_wait_threshold", 15.0)))
    return resolved


def _make_scheduler(algorithm: str):
    """Single integration point for the independent algorithm team."""
    try:
        from scheduler import create_scheduler
    except ImportError as exc:
        raise RuntimeError(
            "scheduler.create_scheduler is not installed; integrate the scheduler team first"
        ) from exc
    return create_scheduler(algorithm)


def _compatible(truck: dict, dock: dict) -> bool:
    allowed = truck["allowed_dock_ids"]
    return dock["mode"] in (truck["direction"], "FLEX") and (
        allowed is None or dock["dock_id"] in allowed
    )


def run_simulation(
    scenario: dict,
    algorithm: str,
    settings: dict | None = None,
) -> dict:
    """Execute and return a SimulationResult; does not mutate the Scenario.

    Injected schedulers in unit tests must obey the exact public interface:
    select_next(ready_trucks, dock, now, settings) -> truck_id | None.
    """
    validate_scenario(scenario)
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unknown scheduling algorithm: {algorithm}")
    resolved_settings = validate_settings(settings)
    scheduler = _make_scheduler(algorithm)
    if not callable(getattr(scheduler, "select_next", None)):
        raise TypeError("Scheduler must implement select_next")
    by_id = {item["truck_id"]: item for item in scenario["trucks"]}
    trucks = {
        key: {
            "truck_id": key,
            "direction": item["direction"],
            "depends_on": list(item["depends_on"]),
            "arrival_time": item["arrival_time"],
            "status": "PENDING",
            "ready_since": None, "assigned_time": None,
            "start_time": None, "finish_time": None,
            "departure_time": None, "dock_id": None,
        }
        for key, item in by_id.items()
    }
    docks = {
        item["dock_id"]: {
            "status": "FREE", "truck_id": None,
            "assigned_time": None, "busy_time": 0.0,
        }
        for item in scenario["docks"]
    }
    ordered_docks = sorted(scenario["docks"], key=lambda d:(d["slot_index"],d["dock_id"]))
    approach = scenario["approach_duration"]
    exit_time = scenario["exit_duration"]
    limit = scenario["max_simulation_time"]

    remaining: dict[str, set[str]] = {
        tid: set(item["depends_on"]) for tid,item in by_id.items()
        if item["direction"] == "OUT"
    }
    reverse: dict[str, list[str]] = {tid: [] for tid in trucks}
    for tid, pending in remaining.items():
        for dep in pending:
            reverse[dep].append(tid)
    for waiting in reverse.values():
        waiting.sort()
    finished_in: set[str] = set()
    seq = 0
    events: list[dict] = []
    heap: list[tuple[float, int, int, str, str, str | None]] = []
    orders = count()

    def schedule(when: float, kind: str, tid: str, did: str | None = None) -> None:
        heapq.heappush(heap, (when, _PRIORITY[kind], next(orders), kind, tid, did))

    def emit(now: float, event_type: str, tid: str | None, did: str | None,
             data: dict | None = None) -> None:
        nonlocal seq
        seq += 1
        events.append({
            "seq": seq, "time": now, "event_type": event_type,
            "truck_id": tid, "dock_id": did, "data": data or {},
        })

    def ready(now: float, tid: str) -> None:
        truck = trucks[tid]
        if truck["status"] not in ("PENDING", "BLOCKED"):
            raise RuntimeError(f"{tid} invalid transition to READY")
        truck["status"] = "READY"
        truck["ready_since"] = now
        emit(now, "TRUCK_READY", tid, None, {"ready_since": now})

    for spec in sorted(scenario["trucks"],key=lambda t:(t["arrival_time"],t["truck_id"])):
        schedule(spec["arrival_time"],"ARRIVAL",spec["truck_id"])

    def process(now: float, kind: str, tid: str, did: str | None) -> None:
        current = trucks[tid]
        if kind == "ARRIVAL":
            if current["status"] != "PENDING":
                raise RuntimeError(f"Duplicate arrival: {tid}")
            emit(now, "TRUCK_ARRIVED", tid, None)
            if current["direction"] == "OUT" and remaining[tid]:
                current["status"] = "BLOCKED"
                emit(now, "TRUCK_BLOCKED", tid, None,
                     {"waiting_for": sorted(remaining[tid])})
            else:
                ready(now, tid)
            return
        if did is None or docks[did]["truck_id"] != tid:
            raise RuntimeError(f"Invalid dock ownership: {tid}/{did}")
        dock = docks[did]
        if kind == "DOCKED":
            if current["status"] != "APPROACHING" or dock["status"] != "RESERVED":
                raise RuntimeError(f"Invalid dock approach completion: {tid}")
            emit(now, "TRUCK_DOCKED", tid, did)
            dock["status"] = "OCCUPIED"
            current["status"] = "PROCESSING"
            current["start_time"] = now
            emit(now, "SERVICE_STARTED", tid, did)
            schedule(now+by_id[tid]["service_duration"],"FINISH",tid,did)
        elif kind == "FINISH":
            if current["status"] != "PROCESSING" or dock["status"] != "OCCUPIED":
                raise RuntimeError(f"Invalid service finish: {tid}")
            current["finish_time"] = now
            current["status"] = "EXITING"
            dock["status"] = "RELEASING"
            data = {"pallet_ids": list(by_id[tid]["pallet_ids"])} if "pallet_ids" in by_id[tid] else {}
            emit(now, "SERVICE_FINISHED", tid, did, data)
            if current["direction"] == "IN":
                finished_in.add(tid)
                unlock_downstream(tid, now)
            schedule(now+exit_time,"EXIT",tid,did)
        elif kind == "EXIT":
            if current["status"] != "EXITING" or dock["status"] != "RELEASING":
                raise RuntimeError(f"Invalid departure: {tid}")
            dock["busy_time"] += now - dock["assigned_time"]
            dock["status"] = "FREE"
            dock["assigned_time"] = None
            dock["truck_id"] = None
            emit(now, "DOCK_RELEASED", tid, did)
            current["status"] = "DEPARTED"
            current["departure_time"] = now
            emit(now, "TRUCK_DEPARTED", tid, did)
        else:
            raise RuntimeError(f"Unexpected internal event {kind}")

    def unlock_downstream(tid: str, at: float) -> None:
        """Unload completion satisfies the inbound dependency immediately."""
        for output_id in reverse[tid]:
            remaining[output_id].remove(tid)
            other = trucks[output_id]
            if other["status"] == "BLOCKED" and not remaining[output_id]:
                ready(at, output_id)

    decision_costs_ms: list[float] = []
    decision_ids = count(1)

    def dispatch_deadline(tid: str) -> float | None:
        info = by_id[tid]
        if info["direction"] == "OUT":
            return info["departure_deadline"]
        candidates = (
            by_id[oid]["departure_deadline"] - by_id[oid]["service_duration"]
            - approach - exit_time
            for oid in reverse[tid]
            if by_id[oid]["departure_deadline"] is not None
            and trucks[oid]["status"] not in ("PENDING", "DEPARTED")
        )
        return min(candidates, default=None)

    def planning_snapshot(now: float, decision_id: int) -> dict:
        """Freeze all arrived world facts before this dispatch's first assignment."""
        rows = []
        for tid in sorted(trucks):
            runtime = trucks[tid]
            if runtime["status"] in ("PENDING", "DEPARTED"):
                continue
            spec = by_id[tid]
            assigned = runtime["assigned_time"]
            finish = (assigned + approach + spec["service_duration"]
                      if assigned is not None else None)
            row = {
                key: copy.deepcopy(spec[key])
                for key in ("truck_id", "direction", "arrival_time", "service_duration",
                            "departure_deadline", "depends_on", "allowed_dock_ids")
            }
            row.update(
                dispatch_deadline=dispatch_deadline(tid),
                status=runtime["status"], ready_since=runtime["ready_since"],
                dock_id=runtime["dock_id"], assigned_time=assigned,
                service_finish_time=finish,
                dock_released_time=(finish + exit_time if finish is not None else None),
            )
            rows.append(row)
        dock_rows = []
        for spec in ordered_docks:
            runtime = docks[spec["dock_id"]]
            available = now
            if runtime["status"] != "FREE":
                occupant = by_id[runtime["truck_id"]]
                available = runtime["assigned_time"] + approach + occupant["service_duration"] + exit_time
            dock_rows.append({**spec, "status": runtime["status"], "available_at": available})
        return {
            "decision_id": decision_id, "now": now,
            "approach_duration": approach, "exit_duration": exit_time,
            "docks": dock_rows, "trucks": rows,
            "finished_inbound_ids": sorted(finished_in),
        }

    def dispatch(now: float) -> bool:
        """Assign free docks using a single immutable world snapshot per round."""
        decision_id = next(decision_ids)
        did_any = False
        need_scores = algorithm in _DEPENDENCY_ALGORITHMS
        scores = dependency_scores(trucks, finished_in, now) if need_scores else {}
        # These facts intentionally remain unchanged across every dock call in
        # this round, even though the true state is assigned progressively.
        available_docks = [dict(spec) for spec in ordered_docks
                           if docks[spec["dock_id"]]["status"] == "FREE"]
        world = planning_snapshot(now, decision_id) if need_scores else None
        for dock_spec in ordered_docks:
            did = dock_spec["dock_id"]
            if docks[did]["status"] != "FREE":
                continue
            ready_ids = sorted(tid for tid, truck in trucks.items() if truck["status"] == "READY")
            if not ready_ids:
                break
            snapshots = []
            for tid in ready_ids:
                spec = by_id[tid]
                snapshot = {
                    "truck_id": tid, "direction": spec["direction"],
                    "status": "READY", "arrival_time": spec["arrival_time"],
                    "ready_since": trucks[tid]["ready_since"],
                    "service_duration": spec["service_duration"],
                    "departure_deadline": spec["departure_deadline"],
                    "dispatch_deadline": dispatch_deadline(tid),
                    "depends_on": list(spec["depends_on"]),
                    "allowed_dock_ids": copy.deepcopy(spec["allowed_dock_ids"]),
                }
                if need_scores:
                    snapshot.update(immediate_unlock_count=scores[tid][0],
                                    dependent_blocked_count=scores[tid][1])
                snapshots.append(snapshot)
            scheduler_settings = copy.deepcopy(resolved_settings)
            scheduler_settings["algorithm"] = algorithm
            if need_scores:
                scheduler_settings["available_docks"] = copy.deepcopy(available_docks)
                scheduler_settings["planning_snapshot"] = copy.deepcopy(world)
            dock_input = copy.deepcopy(dock_spec)
            originals = copy.deepcopy((snapshots, dock_input, scheduler_settings))
            decision_t0 = perf_counter()
            selected = scheduler.select_next(snapshots, dock_input, now, scheduler_settings)
            decision_costs_ms.append((perf_counter() - decision_t0) * 1000.0)
            for label, actual, original in zip(
                ("ready_trucks", "dock", "settings"),
                (snapshots, dock_input, scheduler_settings), originals,
            ):
                if actual != original:
                    raise RuntimeError(f"Scheduler illegally mutated {label}")
            compatible = [t for t in snapshots if _compatible(t, dock_spec)]
            if selected is None:
                if compatible:
                    raise RuntimeError(f"Scheduler returned None despite READY tasks for {did}")
                continue
            if not isinstance(selected, str) or selected not in ready_ids:
                raise RuntimeError(f"Scheduler returned invalid READY truck ID {selected!r}")
            # SchedulerSelectResult is a str subclass with extra constructor
            # arguments; store plain IDs in world state and planning snapshots.
            selected = str(selected)
            spec = by_id[selected]
            if not _compatible(spec, dock_spec):
                raise RuntimeError(f"Scheduler selected incompatible dock for {selected}")
            assigned = trucks[selected]
            assigned["status"] = "APPROACHING"
            assigned["assigned_time"] = now
            assigned["dock_id"] = did
            docks[did]["status"] = "RESERVED"
            docks[did]["truck_id"] = selected
            docks[did]["assigned_time"] = now
            decision = {"ready_since": assigned["ready_since"]}
            if need_scores:
                decision.update(immediate_unlock_count=scores[selected][0],
                                dependent_blocked_count=scores[selected][1])
            emit(now, "DOCK_ASSIGNED", selected, did, decision)
            if algorithm in ("joint_da", "rh_da"):
                from scheduler.decision_snapshot import DecisionSnapshotGenerator
                records = DecisionSnapshotGenerator(
                    snapshots=snapshots, selected_id=selected, dock=dict(dock_spec),
                    now=now, settings=scheduler_settings,
                ).generate()
                data = {"algorithm": algorithm, "mode": "baseline", "snapshot": records}
                forecast = getattr(scheduler, "last_plan_summary", None)
                if forecast is not None:
                    data["forecast"] = copy.deepcopy(forecast)
                emit(now, "DECISION_SNAPSHOT", selected, did, data)
            schedule(now + approach, "DOCKED", selected, did)
            did_any = True
        return did_any

    now = 0.0
    while heap:
        tick = heap[0][0]
        if tick > limit:
            now = limit
            break
        now = tick
        # Finish ALL same-time events before making each dispatch decision.
        while True:
            while heap and heap[0][0] == now:
                _, _, _, kind, tid, did = heapq.heappop(heap)
                process(now, kind, tid, did)
            dispatch(now)
            if not heap or heap[0][0] != now:
                break
            # Zero-duration approach, service or exit must finish at same time;
            # process it before dispatching any newly free dock again.
    if any(t["status"]!="DEPARTED" for t in trucks.values()) and not heap:
        if now < limit:
            raise RuntimeError("Simulation stalled with unfinished work; check scheduler and dependencies")
    return build_result(
        scenario, algorithm, resolved_settings, now, trucks, docks, events,
        decision_costs_ms=decision_costs_ms,
    )
