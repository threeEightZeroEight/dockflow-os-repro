"""EDF (Earliest Deadline First) scheduler — contract.md v1.3 section 4.3.

Algorithm: among dock-compatible READY candidates, select the truck with the
smallest sort key ``(dispatch_deadline_or_inf, ready_since, truck_id)``.
``dispatch_deadline`` is a derived ordering value computed by the simulation;
when it is ``null`` (cannot be derived for an IN truck with no downstream
deadline) it is treated as positive infinity so the task sorts as least urgent.

Business goal: reduce outbound deadline miss rate by serving the most urgent
(releaseable) trucks first.

Key constraints:
- Non-preemptive; only READY candidates.
- Dock compatibility filtered first.
- ``None`` deadline → ``float("inf")``; never compare ``None`` directly.
- Read-only snapshots; no mutation.
"""
from __future__ import annotations

from .base import (
    Scheduler,
    SchedulerSelectResult,
    SchedulerStats,
    dispatch_deadline_or_inf,
    filter_compatible,
)
from time import perf_counter


class EdfScheduler:
    """EDF earliest-deadline-first scheduler."""

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
            key=lambda t: (
                dispatch_deadline_or_inf(t),
                t["ready_since"],
                t["truck_id"],
            ),
        )
        result = SchedulerSelectResult(winner, "selected_by_edf")
        self.last_result = result
        self.last_stats = SchedulerStats(
            total_ready_candidates=len(ready_trucks),
            compatible_candidates=len(compatible),
            select_cost_ms=(perf_counter() - _t0) * 1000,
            reason="selected_by_edf",
        )
        return result
