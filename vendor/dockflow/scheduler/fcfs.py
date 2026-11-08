"""FCFS (First-Come-First-Served) scheduler — contract.md v1.3 section 4.3.

Algorithm: among dock-compatible READY candidates, select the truck with the
smallest sort key ``(ready_since, arrival_time, truck_id)``. This is the
baseline fairness strategy.

Key constraints:
- Non-preemptive: only READY trucks are candidates (BLOCKED trucks are never
  passed in by the simulation).
- Dock compatibility is filtered first (IN→IN/FLEX, OUT→OUT/FLEX, plus the
  optional ``allowed_dock_ids`` whitelist).
- Tie-breaking and ordering rules are fixed by contract.md; no custom weights.
- The input snapshots are read-only; this module never mutates them.
"""
from __future__ import annotations

from .base import (
    Scheduler,
    SchedulerSelectResult,
    SchedulerStats,
    filter_compatible,
)
from time import perf_counter


class FcfsScheduler:
    """FCFS baseline scheduler."""

    last_stats: SchedulerStats | None = None
    last_result: SchedulerSelectResult | None = None

    def select_next(
        self,
        ready_trucks: list[dict],
        dock: dict,
        now: float,
        settings: dict,
    ) -> str | None:
        _t0 = perf_counter()
        compatible = filter_compatible(ready_trucks, dock)
        if not compatible:
            self.last_result = SchedulerSelectResult(None, "no_ready_task")
            self.last_stats = SchedulerStats(
                total_ready_candidates=len(ready_trucks),
                compatible_candidates=0,
                select_cost_ms=(perf_counter() - _t0) * 1000,
                reason="no_ready_task",
            )
            return None
        winner = min(
            compatible,
            key=lambda t: (t["ready_since"], t["arrival_time"], t["truck_id"]),
        )
        result = SchedulerSelectResult(winner, "selected_by_fcfs")
        self.last_result = result
        self.last_stats = SchedulerStats(
            total_ready_candidates=len(ready_trucks),
            compatible_candidates=len(compatible),
            select_cost_ms=(perf_counter() - _t0) * 1000,
            reason="selected_by_fcfs",
        )
        return result
