"""Read-only explanations of actual baseline scheduling decisions.

Slack is time remaining after the earliest service completion (IN) or
physical departure (OUT), in simulation minutes. An unselected compatible
vehicle is described by the actual policy, never an invented urgency win.
"""
from __future__ import annotations

from .base import is_dock_compatible

REJECT_INCOMPATIBLE = "月台类型或白名单不兼容"
REJECT_DEPENDENCY = "货物依赖条件尚未满足"
REJECT_LOW_PRIORITY = "本轮调度规则选择了其他候选"
_POLICY_REASONS = {
    "fcfs": "其他候选更早进入就绪队列",
    "spt": "其他候选的装卸时间更短或平局顺序更早",
    "edf": "其他候选的调度截止时间更早或平局顺序更早",
    "edf_aging": "其他候选在老化分层及截止时间排序中优先",
    "dependency_aware": "其他候选的依赖、资源适配与等待综合得分更高",
    "joint_da": "本轮联合匹配方案选择了其他候选",
    "rh_da": "预测总逾期及等待更优的候选方案选择了其他车辆",
}


class DecisionSnapshotGenerator:
    """Build explanation rows; these observations never drive allocation."""

    def __init__(self, snapshots: list[dict], selected_id: str | None,
                 dock: dict, now: float, settings: dict) -> None:
        self.snapshots = snapshots
        self.selected_id = selected_id
        self.dock = dock
        self.now = now
        self.settings = settings

    def generate(self) -> list[dict]:
        available = self.settings.get("available_docks") or [self.dock]
        reason = _POLICY_REASONS.get(self.settings.get("algorithm"), REJECT_LOW_PRIORITY)
        records = []
        for truck in self.snapshots:
            compatible = is_dock_compatible(truck, self.dock)
            ready = truck.get("status", "READY") == "READY"
            selected = compatible and ready and truck["truck_id"] == self.selected_id
            if not compatible:
                rejected = REJECT_INCOMPATIBLE
            elif not ready:
                rejected = REJECT_DEPENDENCY
            else:
                rejected = "" if selected else reason
            ready_since = truck.get("ready_since")
            records.append({
                "truck_id": truck["truck_id"], "direction": truck.get("direction"),
                "compatible": compatible,
                "compatible_dock_ids": [d["dock_id"] for d in available if is_dock_compatible(truck, d)],
                "unlock_impact": int(truck.get("immediate_unlock_count", 0)),
                "slack_time": self._compute_slack(truck),
                "waiting_time": max(0., self.now - ready_since) if ready_since is not None else 0.,
                "selected": selected, "reject_reason": rejected,
            })
        return records

    def _compute_slack(self, truck: dict) -> float | None:
        world = self.settings.get("planning_snapshot") or self.settings
        approach = float(world.get("approach_duration", 0.))
        duration = float(truck.get("service_duration", 0.))
        if truck.get("direction") == "OUT":
            deadline = truck.get("departure_deadline", truck.get("dispatch_deadline"))
            completion = self.now + approach + duration + float(world.get("exit_duration", 0.))
        else:
            deadline = truck.get("dispatch_deadline")
            completion = self.now + approach + duration
        return float(deadline) - completion if deadline is not None else None
