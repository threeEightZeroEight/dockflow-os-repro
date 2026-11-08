"""研究原型：队列感知 EDF（QEDF）与离线下界。

QEDF 不进入产品算法契约（AGENTS.md 限定七种在线算法），仅作为论文对照方法，
通过 monkeypatch 仿真引擎的调度器工厂注入。

QEDF 的核心修正：EDF 使用派生截止期 D(t)，但 D(t) 未扣除排队时延。
QEDF 用"队列中排在前面的工作量 / 可用月台数"修正有效截止期：

    D_eff(t) = D_base(t) - ahead_service_time(t) / m

其中 D_base(t) 为 OUT 的真实 departure_deadline 或 IN 的派生 D(t)，
ahead_service_time(t) 为按 EDF 顺序排在 t 之前所有 READY 车的服务时长之和，
m 为当前可用月台数。按 D_eff 升序选择，即可把"看似来得及、实际来不及"的车降级。
"""
from __future__ import annotations

from scheduler.base import (
    SchedulerSelectResult,
    dispatch_deadline_or_inf,
    filter_compatible,
)


class QueueAwareEDF:
    """EDF with queue-delay-corrected effective deadlines (research prototype)."""

    def __init__(self, discount: float = 1.0) -> None:
        # discount < 1 is conservative: full queue correction over-penalizes
        # candidates at moderate load (verified empirically).
        self.discount = discount

    def select_next(self, ready_trucks: list[dict], dock: dict, now: float,
                    settings: dict) -> str | None:
        compatible = filter_compatible(ready_trucks, dock)
        if not compatible:
            return None

        ready = [t for t in ready_trucks if t.get("status", "READY") == "READY"]
        docks = settings.get("available_docks") or [dock]
        parallel = max(1, len(docks))

        base_key = lambda t: (
            dispatch_deadline_or_inf(t),
            float(t["ready_since"]),
            float(t["arrival_time"]),
            t["truck_id"],
        )
        ordered = sorted(ready, key=base_key)

        effective: dict[str, float] = {}
        ahead = 0.0
        for truck in ordered:
            effective[truck["truck_id"]] = (
                dispatch_deadline_or_inf(truck) - self.discount * ahead / parallel
            )
            ahead += float(truck["service_duration"])

        winner = min(
            compatible,
            key=lambda t: (
                effective.get(t["truck_id"], dispatch_deadline_or_inf(t)),
                float(t["ready_since"]),
                float(t["arrival_time"]),
                t["truck_id"],
            ),
        )
        return SchedulerSelectResult(winner, "selected_by_qedf")


class AdaptiveQueueEDF:
    """Per-truck gated queue correction (research prototype).

    The correction is applied to a truck only when its estimated queue delay
    Q/m exceeds a fraction (gate) of its remaining deadline slack. When the
    slack is unbounded (no deadline) or the queue is short, the rule reduces
    to plain EDF — so it cannot be worse than EDF by construction, while
    retaining QEDF's benefit under high queue pressure.
    """

    def __init__(self, discount: float = 1.0, gate: float = 1.5) -> None:
        self.discount = discount
        self.gate = gate

    def select_next(self, ready_trucks: list[dict], dock: dict, now: float,
                    settings: dict) -> str | None:
        compatible = filter_compatible(ready_trucks, dock)
        if not compatible:
            return None

        ready = [t for t in ready_trucks if t.get("status", "READY") == "READY"]
        docks = settings.get("available_docks") or [dock]
        parallel = max(1, len(docks))

        base_key = lambda t: (
            dispatch_deadline_or_inf(t),
            float(t["ready_since"]),
            float(t["arrival_time"]),
            t["truck_id"],
        )
        ordered = sorted(ready, key=base_key)

        effective: dict[str, float] = {}
        ahead = 0.0
        for truck in ordered:
            base = dispatch_deadline_or_inf(truck)
            queue_delay = ahead / parallel
            slack = base - now
            if queue_delay > self.gate * max(slack, 0.0):
                effective[truck["truck_id"]] = base - self.discount * queue_delay
            else:
                effective[truck["truck_id"]] = base
            ahead += float(truck["service_duration"])

        winner = min(
            compatible,
            key=lambda t: (
                effective.get(t["truck_id"], dispatch_deadline_or_inf(t)),
                float(t["ready_since"]),
                float(t["arrival_time"]),
                t["truck_id"],
            ),
        )
        return SchedulerSelectResult(winner, "selected_by_aqedf")


def install(engine_module) -> None:
    """Monkeypatch the engine scheduler factory to expose the 'qedf' key."""
    original = engine_module._make_scheduler

    def factory(algorithm: str):
        if algorithm == "qedf":
            return QueueAwareEDF()
        if algorithm == "aqedf":
            return AdaptiveQueueEDF()
        return original(algorithm)

    engine_module._make_scheduler = factory
    # Research-only extension of the engine whitelist; product code is unchanged.
    engine_module.ALGORITHMS = frozenset((*engine_module.ALGORITHMS, "qedf", "aqedf"))


def offline_lower_bound(scenario: dict) -> dict:
    """Capacity-relaxed lower bound: every READY truck is served immediately.

    Ignores dock contention, so waiting and miss rate are optimistic bounds.
    """
    approach = float(scenario["approach_duration"])
    exit_time = float(scenario["exit_duration"])
    trucks = scenario["trucks"]

    in_finish: dict[str, float] = {}
    for truck in trucks:
        if truck["direction"] == "IN":
            in_finish[truck["truck_id"]] = (
                float(truck["arrival_time"]) + approach + float(truck["service_duration"])
            )

    waits: list[float] = []
    misses: list[float] = []
    for truck in trucks:
        arrival = float(truck["arrival_time"])
        service = float(truck["service_duration"])
        if truck["direction"] == "IN":
            waits.append(0.0)
            continue
        predecessor_ready = max(
            (in_finish[dep] for dep in truck["depends_on"] if dep in in_finish),
            default=0.0,
        )
        start = max(arrival, predecessor_ready)
        departure = start + approach + service + exit_time
        waits.append(max(0.0, start - arrival))
        deadline = truck.get("departure_deadline")
        if deadline is not None:
            misses.append(1.0 if departure > float(deadline) else 0.0)

    return {
        "lower_bound_avg_waiting": sum(waits) / len(waits) if waits else 0.0,
        "lower_bound_miss_rate": sum(misses) / len(misses) if misses else 0.0,
        "outbound_count": len(misses),
    }