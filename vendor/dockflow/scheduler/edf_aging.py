"""EDF + Aging scheduler — contract.md v1.3 section 4.3.

Algorithm: in addition to the EDF ordering, a task whose READY waiting time
reaches ``aging_threshold`` is promoted to an urgent tier.  The sort key is:

- Aged task (``now - ready_since >= aging_threshold``):
  ``(0, ready_since, dispatch_deadline_or_inf, truck_id)``
- Normal task:
  ``(1, dispatch_deadline_or_inf, ready_since, truck_id)``

Aged tasks always sort before normal tasks (leading ``0`` vs ``1``).  Within
the aged tier, the task that became READY earliest (longest wait) and then
the earliest deadline wins.  Within the normal tier, pure EDF applies.

Important: Aging only raises scheduling priority; it does **not** modify the
truck's ``dispatch_deadline`` or any other field, and it is unrelated to CPU
MLFQ.  Blocked time is excluded because ``ready_since`` is set only when the
truck enters READY, not on arrival; the simulation guarantees this.

Key constraints:
- Non-preemptive; only READY candidates.
- Dock compatibility filtered first.
- ``aging_threshold`` is read from ``settings`` (the simulation validates and
  injects a positive finite float).  If it is missing the scheduler raises
  ``ValueError`` to surface the interface error rather than silently defaulting.
- Read-only snapshots; no mutation.
"""
from __future__ import annotations

import math

from .base import (
    Scheduler,
    SchedulerSelectResult,
    SchedulerStats,
    dispatch_deadline_or_inf,
    filter_compatible,
)
from time import perf_counter


class EdfAgingScheduler:
    """EDF with aging promotion for long-waiting READY tasks."""

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

        threshold = settings.get("aging_threshold")
        if threshold is None:
            raise ValueError("edf_aging requires settings['aging_threshold']")
        if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
                or not math.isfinite(threshold) or threshold <= 0):
            raise ValueError("aging_threshold must be a positive finite number")
        threshold = float(threshold)

        def sort_key(t: dict) -> tuple:
            deadline = dispatch_deadline_or_inf(t)
            if now - t["ready_since"] >= threshold:
                return (0, t["ready_since"], deadline, t["truck_id"])
            return (1, deadline, t["ready_since"], t["truck_id"])

        winner = min(compatible, key=sort_key)
        result = SchedulerSelectResult(winner, "selected_by_edf_aging")
        self.last_result = result
        self.last_stats = SchedulerStats(
            total_ready_candidates=len(ready_trucks),
            compatible_candidates=len(compatible),
            select_cost_ms=(perf_counter() - _t0) * 1000,
            reason="selected_by_edf_aging",
        )
        return result
