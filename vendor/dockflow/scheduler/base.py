"""Scheduler protocol and shared helpers (contract.md v1.3 section 4.2).

Key constraints (from contract.md, enforced by every concrete scheduler):
- Non-preemptive: only READY trucks are passed in; the scheduler never
  interrupts a running装卸 task.
- Read-only snapshots: ``select_next`` must NOT mutate ``ready_trucks``,
  ``dock`` or ``settings``. The simulation deep-copies snapshots before
  calling and verifies they are unchanged afterwards.
- Dock compatibility is the scheduler's contract responsibility: an IN truck
  can only use IN/FLEX docks; an OUT truck only OUT/FLEX docks; the optional
  ``allowed_dock_ids`` whitelist is honored when present.
- Deterministic ordering and tie-breaking rules are fixed by contract.md
  section 4.3; each policy has one documented ranking rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import perf_counter
from typing import Protocol


class AlgorithmType(str, Enum):
    """Type-safe algorithm identifiers (contract.md section 2).

    Mixing in ``str`` keeps full backward compatibility: an enum member
    compares equal to its string value, so existing callers that pass
    plain strings (e.g. the simulation layer) continue to work unchanged.

    Usage (recommended)::

        from scheduler import AlgorithmType, create_scheduler
        sched = create_scheduler(AlgorithmType.FCFS)

    Legacy (still supported)::

        sched = create_scheduler("fcfs")
    """

    FCFS = "fcfs"
    SPT = "spt"
    EDF = "edf"
    EDF_AGING = "edf_aging"
    DEPENDENCY_AWARE = "dependency_aware"
    JOINT_DA = "joint_da"
    RH_DA = "rh_da"


@dataclass
class SchedulerStats:
    """Read-only performance statistics collected during ``select_next``.

    These statistics are purely observational — they never influence the
    scheduling decision.  Each concrete scheduler stores the latest stats
    in ``self.last_stats`` after every successful ``select_next`` call.
    """

    total_ready_candidates: int
    compatible_candidates: int
    select_cost_ms: float
    reason: str = ""


class SchedulerSelectResult(str):
    """Structured ``select_next`` result — a ``str`` subclass for full
    backward compatibility with the simulation engine.

    The string value is the ``truck_id``, so ``isinstance(result, str)`` is
    ``True`` and the engine can use the result exactly like a plain string
    (dict-key lookups, equality comparisons, etc.).

    Additional attributes for new code:
    - ``task``: the full truck dict snapshot (or ``None``).
    - ``reason``: why this task was selected / why no task (e.g.
      ``"selected_by_fcfs"``, ``"no_ready_task"``).

    Dict-style access ``result["field"]`` forwards to the task snapshot.
    """

    task: dict | None
    reason: str

    def __new__(
        cls, task: dict | None, reason: str
    ) -> "SchedulerSelectResult":
        truck_id = task["truck_id"] if task is not None else ""
        instance = super().__new__(cls, truck_id)
        instance.task = task
        instance.reason = reason
        return instance

    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, str):
            if self.task is not None:
                return self.task[key]
            raise KeyError(key)
        return super().__getitem__(key)

    def __bool__(self) -> bool:  # type: ignore[override]
        return self.task is not None


class Scheduler(Protocol):
    """Unified scheduling protocol (contract.md 4.2).

    ``select_next`` receives read-only READY-truck snapshots from the
    simulation layer and returns the selected ``truck_id`` string, or
    ``None`` when no candidate is compatible with the given dock.

    Implementations MAY expose a ``last_stats: SchedulerStats | None``
    attribute for performance observability; the return type of
    ``select_next`` remains ``str | None`` for full backward compatibility.
    """

    def select_next(
        self,
        ready_trucks: list[dict],
        dock: dict,
        now: float,
        settings: dict,
    ) -> str | None:
        """Return the chosen truck_id, or None; never mutate inputs."""
        ...


def is_dock_compatible(truck: dict, dock: dict) -> bool:
    """Return True when ``truck`` may be served on ``dock``.

    Rules (contract.md section 3.1, 4.2):
    - IN trucks use IN/FLEX docks; OUT trucks use OUT/FLEX docks.
    - When ``allowed_dock_ids`` is non-null, the dock id must be in it.
    """
    allowed = truck.get("allowed_dock_ids")
    return dock["mode"] in (truck["direction"], "FLEX") and (
        allowed is None or dock["dock_id"] in allowed
    )


def filter_compatible(ready_trucks: list[dict], dock: dict) -> list[dict]:
    """Return the subset of ``ready_trucks`` compatible with ``dock``.

    Does not mutate the input list; returns a new list of references to the
    original (still read-only) truck dicts.
    """
    return [t for t in ready_trucks
            if t.get("status", "READY") == "READY" and is_dock_compatible(t, dock)]


def dispatch_deadline_or_inf(truck: dict) -> float:
    """Return the truck's dispatch_deadline, treating None as +infinity.

    contract.md 4.3: ``dispatch_deadline`` is a derived ordering value; when
    it is null (cannot be computed) the task sorts as least urgent. Using
    ``float("inf")`` keeps tuple comparisons stable without special cases.
    """
    deadline = truck.get("dispatch_deadline")
    if deadline is None:
        return float("inf")
    return float(deadline)
