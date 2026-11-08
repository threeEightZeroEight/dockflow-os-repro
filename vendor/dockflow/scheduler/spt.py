"""SPT (Shortest Processing Time) scheduler — contract.md v1.3 section 4.3.

Algorithm: among dock-compatible READY candidates, select the truck with the
smallest sort key ``(service_duration, ready_since, truck_id)``. This
favours short jobs and can reduce average waiting, at the cost of potential
long-task starvation; it is not a global guarantee under dock/dependency constraints.

Key constraints:
- Non-preemptive: only READY trucks are candidates.
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


class SptScheduler:
    """SPT short-job-first scheduler."""

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
            key=lambda t: (t["service_duration"], t["ready_since"], t["truck_id"]),
        )
        result = SchedulerSelectResult(winner, "selected_by_spt")
        self.last_result = result
        self.last_stats = SchedulerStats(
            total_ready_candidates=len(ready_trucks),
            compatible_candidates=len(compatible),
            select_cost_ms=(perf_counter() - _t0) * 1000,
            reason="selected_by_spt",
        )
        return result
