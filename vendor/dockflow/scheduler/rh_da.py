"""RH-DA: compare bounded event forecasts, execute one current batch, replan.

All times are simulation minutes. Only arrived tasks from the read-only
planning_snapshot are visible. A forecast advances a private copy through
service completion, dock release and dependency unlock events. It never
changes the engine and never imports the real simulation to predict future
arrivals. H bounds event time, not the number of candidates.

The objective is lexicographic: minimum predicted total OUT tardiness,
then total waiting (start minus arrival), then a stable assignment signature.
Unfinished jobs at the horizon receive an optimistic terminal completion
estimate, so they cannot simply disappear from the objective. Search is
bounded (default eight first-batch plans, four proposals per dock); it is
an online heuristic, not a proof of a globally optimal schedule.
"""
from __future__ import annotations

import copy
import heapq
import json
import logging
import math
from time import perf_counter

from .base import SchedulerSelectResult, SchedulerStats, filter_compatible, is_dock_compatible

logger = logging.getLogger(__name__)
_POLICIES = ("edf", "dependency", "spt")


def _positive_number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return float(value)


def _budget(value, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [1, {maximum}]")
    return value


def _dock_key(d: dict) -> tuple:
    return (d.get("slot_index", 0), d["dock_id"])


def _deadline(t: dict) -> float:
    value = t.get("departure_deadline") if t["direction"] == "OUT" else t.get("dispatch_deadline")
    return float(value) if value is not None else float("inf")


def _dependency_counts(tid: str, pending: dict[str, dict], finished: set[str]) -> tuple[int, int]:
    immediate = blocked = 0
    for out in pending.values():
        if out["direction"] != "OUT":
            continue
        remaining = set(out.get("depends_on", ())) - finished
        if tid in remaining:
            blocked += 1
            immediate += remaining == {tid}
    return immediate, blocked


def _policy_key(t: dict, policy: str, pending: dict[str, dict], finished: set[str]) -> tuple:
    ready = t.get("ready_since")
    ready = float(ready) if ready is not None else float(t.get("arrival_time", 0.))
    tie = (ready, float(t.get("arrival_time", 0.)), t["truck_id"])
    if policy == "edf":
        return (_deadline(t), *tie)
    if policy == "dependency":
        immediate, blocked = _dependency_counts(t["truck_id"], pending, finished)
        return (-immediate, -blocked, *tie)
    if policy == "spt":
        return (float(t["service_duration"]), *tie)
    return tie


def forecast_schedule(snapshot: dict, initial_assignments: dict[str, str], horizon: float,
                      policy: str = "edf") -> dict:
    """Forecast known work for H minutes; terminal values are estimates.

    projected_departures includes terminal estimates beyond H, whereas
    completed_within_horizon counts only real release events in the copy.
    A missing not-yet-arrived dependency stays unresolved throughout the
    forecast; its terminal bound uses H as the earliest possible unlock.
    """
    horizon = _positive_number(horizon, "horizon_window")
    if policy not in _POLICIES:
        raise ValueError(f"Unknown forecast policy: {policy}")
    now = float(snapshot["now"])
    end = now + horizon
    approach = float(snapshot.get("approach_duration", 0.))
    exit_time = float(snapshot.get("exit_duration", 0.))
    trucks = {
        t["truck_id"]: copy.deepcopy(t) for t in snapshot["trucks"]
        if t.get("arrival_time", now) <= now and t.get("status", "READY") not in ("PENDING", "DEPARTED")
    }
    docks = {d["dock_id"]: dict(d) for d in snapshot["docks"]}
    finished = set(snapshot.get("finished_inbound_ids", ()))
    pending = {tid: t for tid, t in trucks.items() if t.get("status", "READY") in ("READY", "BLOCKED")}
    # occupancy is separate from available_at: zero-length jobs remain owned
    # until their FINISH/RELEASE events are settled at the same clock tick.
    occupied: set[str] = set()
    events: list[tuple[float, int, str, str]] = []
    scheduled: dict[str, tuple[float, float, float]] = {}
    departed: dict[str, float] = {}
    max_simulated_time = now
    for tid, t in trucks.items():
        if tid in pending:
            continue
        did = t.get("dock_id")
        if did not in docks:
            continue
        assigned = t.get("assigned_time")
        assigned = float(assigned) if assigned is not None else now - approach
        finish = t.get("service_finish_time")
        finish = float(finish) if finish is not None else assigned + approach + float(t["service_duration"])
        release = t.get("dock_released_time")
        release = float(release) if release is not None else finish + exit_time
        scheduled[tid] = (finish, release, assigned + approach)
        occupied.add(did)
        docks[did]["available_at"] = release
        if t["direction"] == "IN" and (finish < now or t.get("status") == "EXITING"):
            finished.add(tid)
        elif finish >= now:
            heapq.heappush(events, (finish, 0, tid, did))
        heapq.heappush(events, (max(now, release), 1, tid, did))
    for did, d in docks.items():
        if d.get("status", "FREE") != "FREE" and did not in occupied:
            # A complete engine snapshot carries the owner above. For a
            # standalone partial snapshot, still respect busy resource time.
            occupied.add(did)
            heapq.heappush(events, (max(now, float(d.get("available_at", end))), 1, "", did))

    def refresh_ready(at: float) -> None:
        for t in pending.values():
            if t.get("status") == "BLOCKED" and set(t.get("depends_on", ())) <= finished:
                t["status"] = "READY"
                t["ready_since"] = at

    def assign(tid: str, did: str, at: float) -> None:
        t = pending.pop(tid)
        finish = at + approach + float(t["service_duration"])
        release = finish + exit_time
        scheduled[tid] = (finish, release, at + approach)
        occupied.add(did)
        docks[did]["available_at"] = release
        heapq.heappush(events, (finish, 0, tid, did))
        heapq.heappush(events, (release, 1, tid, did))

    refresh_ready(now)
    for did, tid in sorted(initial_assignments.items(), key=lambda item: _dock_key(docks[item[0]])):
        t = pending.get(tid)
        if (did not in occupied and t is not None and t.get("status", "READY") == "READY"
                and is_dock_compatible(t, docks[did])):
            assign(tid, did, now)
        else:
            raise ValueError(f"Infeasible forecast assignment {did} <- {tid}")

    at = now
    while True:
        # Settle every finish/release before any further allocation at at.
        while events and events[0][0] <= at:
            when, kind, tid, did = heapq.heappop(events)
            max_simulated_time = max(max_simulated_time, when)
            if kind == 0 and trucks[tid]["direction"] == "IN":
                finished.add(tid)
            elif kind == 1:
                occupied.discard(did)
                if tid:
                    departed[tid] = when
            refresh_ready(when)
        for dk in sorted(docks.values(), key=_dock_key):
            did = dk["dock_id"]
            if did in occupied:
                continue
            candidates = [t for t in pending.values()
                          if t.get("status", "READY") == "READY" and is_dock_compatible(t, dk)]
            if candidates:
                winner = min(candidates, key=lambda t: _policy_key(t, policy, pending, finished))
                assign(winner["truck_id"], did, at)
        if events and events[0][0] <= at:
            continue  # zero-duration service/exit: settle before another batch
        if not events or events[0][0] > end:
            break
        at = events[0][0]

    # Account for all known unfinished jobs, not just those completing by H.
    projections = dict(departed)
    projected_starts = {tid: times[2] for tid, times in scheduled.items()}
    in_finishes = {tid: times[0] for tid, times in scheduled.items() if trucks[tid]["direction"] == "IN"}

    def earliest_dock(t: dict) -> float:
        possible = [max(end, float(d.get("available_at", end))) for d in docks.values()
                    if is_dock_compatible(t, d)]
        return min(possible, default=end)

    for tid, (finish, release, start) in scheduled.items():
        projections[tid] = release
    for tid, t in pending.items():
        if t["direction"] == "IN":
            assigned = earliest_dock(t)
            in_finishes[tid] = assigned + approach + float(t["service_duration"])
            projections[tid] = in_finishes[tid] + exit_time
            projected_starts[tid] = assigned + approach
    unresolved = 0
    for tid, t in pending.items():
        if t["direction"] != "OUT":
            continue
        remaining = set(t.get("depends_on", ())) - finished
        unknown = remaining - in_finishes.keys()
        unresolved += bool(unknown)
        dependency_time = max([end, *(in_finishes.get(dep, end) for dep in remaining)])
        assigned = max(earliest_dock(t), dependency_time)
        projected_starts[tid] = assigned + approach
        projections[tid] = assigned + approach + float(t["service_duration"]) + exit_time
    tardiness = sum(max(0., projections[tid] - float(t["departure_deadline"]))
                    for tid, t in trucks.items()
                    if t["direction"] == "OUT" and t.get("departure_deadline") is not None)
    waiting = sum(max(0., projected_starts[tid] - float(t.get("arrival_time", now))) for tid, t in trucks.items())
    return {
        "predicted_total_tardiness": tardiness,
        "predicted_total_waiting": waiting,
        "projected_departures": dict(sorted(projections.items())),
        "completed_within_horizon": len(departed),
        "terminal_estimate_count": len(trucks) - len(departed),
        "unresolved_dependency_count": unresolved,
        "max_simulated_time": max_simulated_time,
    }


def _maximum_plan(trucks: list[dict], docks: list[dict]) -> dict[str, str]:
    """A maximum-cardinality compatible plan, without a candidate cutoff."""
    owners: dict[str, str] = {}  # truck -> dock
    dock_by_id = {d["dock_id"]: d for d in docks}
    ordered = sorted(trucks, key=lambda t: (sum(is_dock_compatible(t, d) for d in docks), t["truck_id"]))

    def augment(did: str, seen: set[str]) -> bool:
        for t in ordered:
            tid = t["truck_id"]
            if tid in seen or not is_dock_compatible(t, dock_by_id[did]):
                continue
            seen.add(tid)
            old = owners.get(tid)
            if old is None or augment(old, seen):
                owners[tid] = did
                return True
        return False

    for dk in sorted(docks, key=_dock_key):
        augment(dk["dock_id"], set())
    plan = {did: tid for tid, did in owners.items()}
    # Engine visits slots in order and requires work conservation. Compact
    # an assignment from a later slot into an earlier compatible empty slot.
    truck_by_id = {t["truck_id"]: t for t in trucks}
    ordered_docks = sorted(docks, key=_dock_key)
    for index, dk in enumerate(ordered_docks):
        if dk["dock_id"] in plan:
            continue
        for later in ordered_docks[index + 1:]:
            tid = plan.get(later["dock_id"])
            if tid is not None and is_dock_compatible(truck_by_id[tid], dk):
                plan[dk["dock_id"]] = plan.pop(later["dock_id"])
                break
    return plan


def _candidate_plans(trucks: list[dict], docks: list[dict], snapshot: dict,
                     beam_width: int, per_dock: int) -> list[dict[str, str]]:
    """Bounded diverse proposals, plus an untruncated feasible matching."""
    pending = {t["truck_id"]: t for t in snapshot["trucks"]}
    finished = set(snapshot.get("finished_inbound_ids", ()))
    maximum = _maximum_plan(trucks, docks)
    beam: list[dict[str, str]] = [{}]
    for dk in sorted(docks, key=_dock_key):
        groups = []
        for plan in beam:
            expanded = []
            unused = [t for t in trucks if t["truck_id"] not in plan.values() and is_dock_compatible(t, dk)]
            proposals: list[str] = []
            if unused:
                # Scarce resources, EDF, dependency benefit, SPT and FCFS
                # contribute distinct proposals rather than one scalar rank.
                scarce = min(unused, key=lambda t: (sum(is_dock_compatible(t, d) for d in docks), t["truck_id"]))
                proposals.append(scarce["truck_id"])
                for policy in (*_POLICIES, "fcfs"):
                    winner = min(unused, key=lambda t: _policy_key(t, policy, pending, finished))["truck_id"]
                    if winner not in proposals:
                        proposals.append(winner)
                for t in sorted(unused, key=lambda t: _policy_key(t, "edf", pending, finished)):
                    if t["truck_id"] not in proposals:
                        proposals.append(t["truck_id"])
                for tid in proposals[:per_dock]:
                    expanded.append({**plan, dk["dock_id"]: tid})
            else:
                expanded.append(dict(plan))
            groups.append(expanded)
        # Interleave parents before truncation: otherwise four choices on
        # a late dock can erase all alternative choices on an early dock.
        expanded = [group[index] for index in range(max(map(len, groups), default=0))
                    for group in groups if index < len(group)]
        unique = {tuple(sorted(p.items())): p for p in expanded}
        beam = list(unique.values())[:beam_width]
    unique = {tuple(sorted(p.items())): p for p in [maximum, *beam]}
    plans = [p for p in unique.values() if len(p) == len(maximum)]
    return plans[:beam_width]


class RollingHorizonDAScheduler:
    """One policy in the sole baseline world; no DA downgrade path."""

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._cache_key = None
        self.last_stats = None
        self.last_result = None
        self.last_plan_summary: dict | None = None

    def select_next(self, ready_trucks: list[dict], dock: dict, now: float, settings: dict) -> str | None:
        started = perf_counter()
        compatible = filter_compatible(ready_trucks, dock)
        if not compatible:
            self.last_result = SchedulerSelectResult(None, "no_ready_task")
            self.last_stats = SchedulerStats(len(ready_trucks), 0, (perf_counter() - started) * 1000, "no_ready_task")
            return None
        horizon = _positive_number(settings.get("horizon_window", 30.), "horizon_window")
        beam = _budget(settings.get("rh_beam_width", 8), "rh_beam_width", 64)
        per_dock = _budget(settings.get("rh_candidates_per_dock", 4), "rh_candidates_per_dock", 16)
        source = settings.get("planning_snapshot")
        if source is None:
            # Standalone callers can forecast READY work only. Engine callers
            # always provide BLOCKED/in-progress tasks as well.
            source = {
                "now": now, "approach_duration": settings.get("approach_duration", 0.),
                "exit_duration": settings.get("exit_duration", 0.),
                "trucks": [{**t, "status": "READY", "depends_on": t.get("depends_on", []),
                            "departure_deadline": t.get("departure_deadline", t.get("dispatch_deadline"))
                            if t["direction"] == "OUT" else None} for t in ready_trucks
                           if t.get("status", "READY") == "READY"],
                "docks": [dict(d) for d in (settings.get("available_docks") or [dock])],
                "finished_inbound_ids": [],
            }
        snapshot = copy.deepcopy(source)
        snapshot["trucks"] = [t for t in snapshot["trucks"]
                              if t.get("arrival_time", now) <= now and t.get("status", "READY") not in ("PENDING", "DEPARTED")]
        if "decision_id" in snapshot:
            token = (now, snapshot["decision_id"], horizon, beam, per_dock)
        else:
            token = (now, json.dumps(snapshot, sort_keys=True), horizon, beam, per_dock)
        winner_id = self._cache.get(dock["dock_id"])
        valid_ids = {t["truck_id"] for t in compatible}
        if self._cache_key != token or winner_id not in valid_ids:
            docks = [d for d in snapshot["docks"] if d.get("status", "FREE") == "FREE"]
            # A standalone single-dock invocation must remain usable even if
            # a caller's optional batch list omitted its current dock.
            if dock["dock_id"] not in {d["dock_id"] for d in docks}:
                docks.append(dict(dock))
                snapshot["docks"].append(dict(dock))
            ready = [t for t in snapshot["trucks"] if t.get("status", "READY") == "READY"
                     and t["truck_id"] in {x["truck_id"] for x in ready_trucks}]
            plans = _candidate_plans(ready, docks, snapshot, beam, per_dock)
            best = None
            evaluations = []
            for plan in plans:
                for policy in _POLICIES:
                    forecast = forecast_schedule(snapshot, plan, horizon, policy)
                    signature = tuple(sorted(plan.items()))
                    key = (forecast["predicted_total_tardiness"], forecast["predicted_total_waiting"], signature, policy)
                    evaluations.append({"assignments": dict(plan), "continuation": policy,
                                        "predicted_total_tardiness": forecast["predicted_total_tardiness"]})
                    if best is None or key < best[0]:
                        best = (key, plan, policy, forecast)
            if best is None:
                raise ValueError("planning_snapshot has no current compatible READY assignment")
            _, plan, policy, forecast = best
            self._cache = dict(plan)
            self._cache_key = token
            winner_id = self._cache.get(dock["dock_id"])
            self.last_plan_summary = {
                "horizon_minutes": horizon, "horizon_end": now + horizon,
                "evaluated_plan_count": len(plans), "rollout_count": len(evaluations),
                "selected_continuation": policy, **forecast, "comparisons": evaluations,
            }
            if settings.get("scheduler_debug_log", False):
                logger.info("[RH-DA] now=%.3f H=%.1f plans=%d rollouts=%d predicted_tardiness=%.3f",
                            now, horizon, len(plans), len(evaluations), forecast["predicted_total_tardiness"])
        if winner_id not in valid_ids:
            # This indicates a caller supplied an inconsistent batch snapshot.
            raise ValueError("RH-DA batch plan does not contain a feasible current assignment")
        winner = next(t for t in compatible if t["truck_id"] == winner_id)
        self.last_result = SchedulerSelectResult(winner, "selected_by_rh_da_forecast")
        self.last_stats = SchedulerStats(len(ready_trucks), len(compatible), (perf_counter() - started) * 1000,
                                         "selected_by_rh_da_forecast")
        return self.last_result
