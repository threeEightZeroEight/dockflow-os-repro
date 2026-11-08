"""DockFlow scheduler package (contract.md v1.3 section 4.2).

Exports the ``Scheduler`` protocol, the ``create_scheduler`` factory, the
``AlgorithmType`` enum and all concrete scheduler classes. The factory
accepts either a plain string (``"fcfs"`` …) or an :class:`AlgorithmType`
enum member; an unknown identifier raises ``ValueError``.

Concrete implementations are imported lazily inside ``create_scheduler`` so
that adding a new algorithm does not create import cycles and partial states
(empty implementations) are never exposed.
"""
from __future__ import annotations

from .base import (
    AlgorithmType,
    Scheduler,
    SchedulerSelectResult,
    SchedulerStats,
    dispatch_deadline_or_inf,
    filter_compatible,
    is_dock_compatible,
)

__all__ = [
    "AlgorithmType",
    "Scheduler",
    "SchedulerSelectResult",
    "SchedulerStats",
    "create_scheduler",
    "dispatch_deadline_or_inf",
    "filter_compatible",
    "is_dock_compatible",
]


def create_scheduler(algorithm: str | AlgorithmType) -> Scheduler:
    """Return the scheduler instance for ``algorithm``.

    Accepts either a plain string (legacy, e.g. ``"fcfs"``) or an
    :class:`AlgorithmType` enum member (recommended). An unknown identifier
    raises ``ValueError`` so that the simulation layer surfaces interface
    mismatches explicitly rather than silently falling back.
    """
    # Normalise enum → string so the rest of the factory is unchanged.
    if isinstance(algorithm, AlgorithmType):
        algorithm = algorithm.value

    if algorithm == "fcfs":
        from .fcfs import FcfsScheduler
        return FcfsScheduler()
    if algorithm == "spt":
        from .spt import SptScheduler
        return SptScheduler()
    if algorithm == "edf":
        from .edf import EdfScheduler
        return EdfScheduler()
    if algorithm == "edf_aging":
        from .edf_aging import EdfAgingScheduler
        return EdfAgingScheduler()
    if algorithm == "dependency_aware":
        from .dependency_aware import DependencyAwareScheduler
        return DependencyAwareScheduler()
    if algorithm == "joint_da":
        from .joint_da import JointDAScheduler
        return JointDAScheduler()
    if algorithm == "rh_da":
        from .rh_da import RollingHorizonDAScheduler
        return RollingHorizonDAScheduler()
    raise ValueError(f"Unknown scheduling algorithm: {algorithm!r}")
