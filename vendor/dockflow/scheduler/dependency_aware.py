"""DA: dependency benefit, resource fit, observed traffic and linear aging.

One policy, using only arrived-truck and current resource snapshots.  Higher
score wins; exact ties use (ready_since, arrival_time, truck_id)::

    100 * immediate_unlock_count + 5 * dependent_blocked_count
    + 20 * resource_fit + 10 * traffic_pressure * is_inbound
    + 2 * max(0, now - ready_since)

resource_fit = (1 + min(1, compatible_candidates / free_docks)) /
               candidate_free_compatible_docks.
traffic_pressure = min(1, observed_arrivals_in_last_60_minutes / (60 * 0.5)).

Resource fit rewards scarce compatible capacity, even without dependencies.
The bounded traffic signal is historical demand, not knowledge of future
arrivals.  Unbounded linear waiting protects all READY trucks.  The scheduler
always selects when a compatible candidate exists and never changes inputs.
"""
from __future__ import annotations

import math
from time import perf_counter

from .base import SchedulerSelectResult, SchedulerStats, filter_compatible, is_dock_compatible


def _finite_number(value, name: str, *, minimum: float | None = None,
                   strict: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if minimum is not None and (result < minimum or (strict and result == minimum)):
        qualifier = "greater than" if strict else "at least"
        raise ValueError(f"{name} must be {qualifier} {minimum}")
    return result


def _settings_number(settings: dict, name: str, default: float, *, positive: bool = False) -> float:
    return _finite_number(settings.get(name, default), name, minimum=0, strict=positive)


def _ready_wait(truck: dict, now: float) -> float:
    since = _finite_number(truck["ready_since"], f"ready_since for {truck.get('truck_id')!r}")
    return max(0.0, now - since)


def _validate_counts(truck: dict) -> None:
    """Ensure immediate_unlock_count / dependent_blocked_count are valid.

    Raises ValueError on missing, negative, non-integer, boolean or
    inconsistent values.  The contract forbids silently defaulting to 0 to
    avoid masking simulation/scheduler interface bugs.
    """
    for field in ("immediate_unlock_count", "dependent_blocked_count"):
        if field not in truck:
            raise ValueError(
                f"DA scheduler requires '{field}' in truck snapshot "
                f"{truck.get('truck_id')!r}; field is missing"
            )
        value = truck[field]
        # bool is a subclass of int but must be rejected per contract.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"{field} for {truck.get('truck_id')!r} must be an int, "
                f"got {type(value).__name__}"
            )
        if value < 0:
            raise ValueError(
                f"{field} for {truck.get('truck_id')!r} must be non-negative"
            )
    if truck["immediate_unlock_count"] > truck["dependent_blocked_count"]:
        raise ValueError(
            f"immediate_unlock_count ({truck['immediate_unlock_count']}) "
            f"cannot exceed dependent_blocked_count "
            f"({truck['dependent_blocked_count']}) for "
            f"{truck.get('truck_id')!r}"
        )
    # OUT trucks never carry dependency benefit; non-zero counts signal a bug.
    if truck.get("direction") == "OUT" and (
        truck["immediate_unlock_count"] != 0 or truck["dependent_blocked_count"] != 0
    ):
        raise ValueError(
            f"OUT truck {truck.get('truck_id')!r} must have zero counts, "
            f"got ({truck['immediate_unlock_count']}, "
            f"{truck['dependent_blocked_count']})"
        )


class DependencyAwareScheduler:
    """Single multifactor DA policy; numeric weights may be tuned in settings.

    da_immediate_weight=100, da_blocked_weight=5, da_resource_weight=20,
    da_traffic_weight=10 and da_wait_weight=2 must be finite and nonnegative.
    da_arrival_window=60 minutes and da_pressure_rate=0.5 trucks/minute must
    be finite and positive.  No switch changes the meaning of the algorithm.
    """

    last_stats: SchedulerStats | None = None
    last_result: SchedulerSelectResult | None = None

    def __init__(self) -> None:
        self._observed_arrivals: dict[str, float] = {}
        self._arrival_rate = 0.0

    def _observe(self, ready_trucks: list[dict], now: float, settings: dict,
                 window: float) -> None:
        # Planning snapshots include blocked and working trucks.  Standalone
        # callers can provide only READY snapshots; that is a partial history.
        observed = settings.get("planning_snapshot", {}).get("trucks", [])
        cutoff = now - window
        for truck in [*observed, *ready_trucks]:
            arrival = truck.get("arrival_time")
            if isinstance(arrival, (int, float)) and not isinstance(arrival, bool):
                if math.isfinite(arrival) and cutoff <= arrival <= now:
                    self._observed_arrivals[truck["truck_id"]] = float(arrival)
        self._observed_arrivals = {
            tid: arrival for tid, arrival in self._observed_arrivals.items()
            if cutoff <= arrival <= now
        }
        # A rolling window rate is idempotent across same-time dock calls and
        # incorporates a new arrival at the same now exactly once.
        self._arrival_rate = len(self._observed_arrivals) / window

    @staticmethod
    def _free_docks(dock: dict, now: float, settings: dict) -> list[dict]:
        planning_docks = settings.get("planning_snapshot", {}).get("docks")
        available = settings.get("available_docks")
        source = planning_docks if planning_docks is not None else (available or [dock])
        available_ids = None if available is None else {d["dock_id"] for d in available}
        by_id = {}
        for item in source:
            if available_ids is not None and item["dock_id"] not in available_ids:
                continue
            if item.get("status", "FREE") != "FREE":
                continue
            if float(item.get("available_at", now)) <= now:
                by_id[item["dock_id"]] = item
        # A select_next request is itself evidence that this dock is free.
        by_id[dock["dock_id"]] = dock
        return list(by_id.values())

    def select_next(self, ready_trucks: list[dict], dock: dict, now: float,
                    settings: dict) -> str | None:
        started = perf_counter()
        compatible = filter_compatible(ready_trucks, dock)
        if not compatible:
            self.last_result = SchedulerSelectResult(None, "no_ready_task")
            self.last_stats = SchedulerStats(len(ready_trucks), 0,
                                            (perf_counter() - started) * 1000, "no_ready_task")
            return None
        for truck in compatible:
            _validate_counts(truck)
        now = _finite_number(now, "now")
        wi = _settings_number(settings, "da_immediate_weight", 100)
        wb = _settings_number(settings, "da_blocked_weight", 5)
        wr = _settings_number(settings, "da_resource_weight", 20)
        wt = _settings_number(settings, "da_traffic_weight", 10)
        ww = _settings_number(settings, "da_wait_weight", 2)
        window = _settings_number(settings, "da_arrival_window", 60, positive=True)
        rate_scale = _settings_number(settings, "da_pressure_rate", 0.5, positive=True)
        self._observe(ready_trucks, now, settings, window)
        pressure = min(1.0, self._arrival_rate / rate_scale)
        free_docks = self._free_docks(dock, now, settings)
        competition = min(1.0, len(compatible) / len(free_docks))

        def score(truck: dict) -> float:
            options = sum(is_dock_compatible(truck, other) for other in free_docks)
            resource_fit = (1.0 + competition) / options
            return (wi * truck["immediate_unlock_count"]
                    + wb * truck["dependent_blocked_count"]
                    + wr * resource_fit
                    + wt * pressure * (truck["direction"] == "IN")
                    + ww * _ready_wait(truck, now))

        winner = min(compatible, key=lambda t: (-score(t), t["ready_since"],
                                               t["arrival_time"], t["truck_id"]))
        self.last_result = SchedulerSelectResult(winner, "selected_by_dependency_aware")
        self.last_stats = SchedulerStats(len(ready_trucks), len(compatible),
                                        (perf_counter() - started) * 1000,
                                        "selected_by_dependency_aware")
        return self.last_result
