"""JointDA: maximum-cardinality matching, then maximum combined priority.

All READY candidates participate.  A batch plan lasts only for one dispatch
ID, is validated before use, and is recomputed at a new dispatch even if now
has not changed.  No old plan is locked and no physical-mode branch exists.

Priority = 100 * immediate_unlock_count + 5 * dependent_blocked_count
           + 20 * urgency + 2 * ready_waiting_minutes.
Urgency = 1 - slack / (30 + abs(slack)); absent deadline means zero urgency.
OUT slack uses actual departure_deadline minus now, approach, service and
exit. IN slack uses derived dispatch_deadline (unloading finish target)
minus now, approach and its own service. Exact ties use FCFS then truck ID.
"""
from __future__ import annotations

import math
from time import perf_counter

from .base import SchedulerSelectResult, SchedulerStats, filter_compatible, is_dock_compatible
from .dependency_aware import _finite_number, _ready_wait, _settings_number, _validate_counts

_INF = float("inf")
_is_compatible = is_dock_compatible


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Maximum feasible cardinality, then minimum cost, for any rectangle.

    Infinite edges are forbidden. Each row gets a dummy job. Finite costs
    are normalized to [-1, 1]; one dummy costs 2*m+1, greater than every
    possible change in real-edge cost across m rows. This proves cardinality
    precedes cost. Forbidden edges cost more than the all-dummy solution.
    Augmenting paths use a separate ``way`` predecessor array.
    """
    m = len(cost)
    if not m:
        return []
    n = len(cost[0])
    if any(len(row) != n for row in cost):
        raise ValueError("cost matrix must be rectangular")
    if not n:
        return [-1] * m
    if any(math.isnan(value) or value == -_INF for row in cost for value in row):
        raise ValueError("cost must contain finite numbers or positive infinity")
    magnitude = max([1.0, *(abs(value) for row in cost for value in row if math.isfinite(value))])
    unmatched = 2 * m + 1
    forbidden = unmatched * (m + 2)
    matrix = [[value / magnitude if math.isfinite(value) else forbidden for value in row]
              + [unmatched] * m for row in cost]
    width = n + m
    u, v = [0.0] * (m + 1), [0.0] * (width + 1)
    p, way = [0] * (width + 1), [0] * (width + 1)
    for worker in range(1, m + 1):
        p[0] = worker
        job = 0
        minimum = [_INF] * (width + 1)
        used = [False] * (width + 1)
        while True:
            used[job] = True
            row = p[job]
            delta, next_job = _INF, 0
            for candidate in range(1, width + 1):
                if used[candidate]:
                    continue
                reduced = matrix[row - 1][candidate - 1] - u[row] - v[candidate]
                if reduced < minimum[candidate]:
                    minimum[candidate] = reduced
                    way[candidate] = job
                if minimum[candidate] < delta:
                    delta, next_job = minimum[candidate], candidate
            for candidate in range(width + 1):
                if used[candidate]:
                    u[p[candidate]] += delta
                    v[candidate] -= delta
                else:
                    minimum[candidate] -= delta
            job = next_job
            if p[job] == 0:
                break
        while job:
            predecessor = way[job]
            p[job] = p[predecessor]
            job = predecessor
    result = [-1] * m
    for job in range(1, n + 1):
        if p[job] and math.isfinite(cost[p[job] - 1][job - 1]):
            result[p[job] - 1] = job - 1
    return result


def _split_components(
    trucks: list[dict], docks: list[dict]
) -> list[tuple[list[dict], list[dict]]]:
    """按兼容关系把 (truck × dock) 二分图分解为连通分量。

    使用 union-find：truck 与 dock 为节点，兼容关系为边。**数学性质**：
    不同分量之间无共享节点，全局最优匹配 = 各分量最优匹配的拼接，
    因此分量内独立求解 Hungarian 与全量求解结果严格等价（最优值不变），
    而 O(n³) 在小矩阵上实际开销显著降低。

    返回 [(comp_trucks, comp_docks), ...]，分量顺序确定性（按首节点 id）。
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # 固定合并方向保证确定性
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    for t in trucks:
        parent.setdefault("T:" + t["truck_id"], "T:" + t["truck_id"])
    for d in docks:
        parent.setdefault("D:" + d["dock_id"], "D:" + d["dock_id"])

    for t in trucks:
        for d in docks:
            if _is_compatible(t, d):
                union("T:" + t["truck_id"], "D:" + d["dock_id"])

    groups: dict[str, tuple[list[dict], list[dict]]] = {}
    for t in trucks:
        groups.setdefault(find("T:" + t["truck_id"]), ([], []))[0].append(t)
    for d in docks:
        groups.setdefault(find("D:" + d["dock_id"]), ([], []))[1].append(d)

    # 确定性排序：按分量代表根 id
    return [groups[root] for root in sorted(groups)]


# ---------------------------------------------------------------------------
# JointDA 调度器主体
# ---------------------------------------------------------------------------


def _freeze(value):
    """Stable content key for standalone callers lacking a dispatch ID."""
    if isinstance(value, dict):
        return tuple((k, _freeze(v)) for k, v in sorted(value.items()))
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(v) for v in value)
    return value


class JointDAScheduler:
    """Joint matching on all available docks and candidates.

    Settings: joint_immediate_weight=100, joint_blocked_weight=5,
    joint_urgency_weight=20, joint_wait_weight=2 (finite nonnegative), and
    joint_slack_scale=30 minutes (finite positive). Tuning weights preserves
    one priority formula. Matching cardinality always takes precedence.
    """

    last_stats: SchedulerStats | None = None
    last_result: SchedulerSelectResult | None = None

    def __init__(self) -> None:
        self._cache: dict[str, str | None] = {}
        self._cache_key = None
        self._returned: dict[str, str] = {}

    @staticmethod
    def _parameters(settings: dict) -> tuple[float, float, float, float, float]:
        return (_settings_number(settings, "joint_immediate_weight", 100),
                _settings_number(settings, "joint_blocked_weight", 5),
                _settings_number(settings, "joint_urgency_weight", 20),
                _settings_number(settings, "joint_wait_weight", 2),
                _settings_number(settings, "joint_slack_scale", 30, positive=True))

    def _compute_truck_priority(self, truck: dict, now: float, settings: dict) -> float:
        _validate_counts(truck)
        wi, wb, wu, ww, scale = self._parameters(settings)
        planning = settings.get("planning_snapshot", {})
        approach = _finite_number(settings.get("approach_duration", planning.get("approach_duration", 0)),
                                  "approach_duration", minimum=0)
        exit_duration = _finite_number(settings.get("exit_duration", planning.get("exit_duration", 0)),
                                       "exit_duration", minimum=0)
        service = _finite_number(truck["service_duration"], "service_duration", minimum=0)
        deadline = (truck.get("departure_deadline") if truck["direction"] == "OUT"
                    else truck.get("dispatch_deadline"))
        urgency = 0.0
        if deadline is not None:
            deadline = _finite_number(deadline, "departure_deadline" if truck["direction"] == "OUT"
                                      else "dispatch_deadline")
            slack = deadline - now - approach - service
            if truck["direction"] == "OUT":
                slack -= exit_duration
            urgency = 1.0 - slack / (scale + abs(slack))
        return (wi * truck["immediate_unlock_count"] + wb * truck["dependent_blocked_count"]
                + wu * urgency + ww * _ready_wait(truck, now))

    def _compute_global_assignment(self, ready_trucks: list[dict], docks: list[dict],
                                   now: float, settings: dict) -> None:
        # Put the smaller resource set on the worker side: O(D^2 * (T+D)).
        # Sorting priorities before matching gives stable FCFS ties without
        # floating perturbations that could reverse a real priority difference.
        trucks = sorted(ready_trucks, key=lambda t: (-self._compute_truck_priority(t, now, settings),
                                                    t["ready_since"], t["arrival_time"], t["truck_id"]))
        priorities = {t["truck_id"]: self._compute_truck_priority(t, now, settings) for t in trucks}
        self._cache = {d["dock_id"]: None for d in docks}
        # Compatibility components are an exact decomposition, not a mode.
        for comp_trucks, comp_docks in _split_components(trucks, docks):
            if not comp_trucks or not comp_docks:
                continue
            cost = [[-priorities[t["truck_id"]] if is_dock_compatible(t, d) else _INF
                     for t in comp_trucks] for d in comp_docks]
            for i, j in enumerate(_hungarian(cost)):
                if j >= 0 and is_dock_compatible(comp_trucks[j], comp_docks[i]):
                    self._cache[comp_docks[i]["dock_id"]] = comp_trucks[j]["truck_id"]

    def select_next(self, ready_trucks: list[dict], dock: dict, now: float,
                    settings: dict) -> str | None:
        started = perf_counter()
        active = [t for t in ready_trucks if t.get("status", "READY") == "READY"]
        compatible = filter_compatible(active, dock)
        if not compatible:
            self.last_result = SchedulerSelectResult(None, "no_ready_task")
            self.last_stats = SchedulerStats(len(ready_trucks), 0,
                                            (perf_counter() - started) * 1000, "no_ready_task")
            return None
        now = _finite_number(now, "now")
        self._parameters(settings)
        for task in active:
            _validate_counts(task)
        available = settings.get("available_docks") or [dock]
        dock_by_id = {d["dock_id"]: d for d in available}
        dock_by_id[dock["dock_id"]] = dock
        docks = sorted(dock_by_id.values(), key=lambda d: (d.get("slot_index", 0), d["dock_id"]))
        decision_id = settings.get("planning_snapshot", {}).get("decision_id")
        if decision_id is not None:
            cache_key = (now, decision_id)
        else:
            cache_key = (now, _freeze(sorted(active, key=lambda t: t["truck_id"])),
                         _freeze(docks), _freeze(settings))
        if cache_key != self._cache_key:
            self._cache_key = cache_key
            self._returned = {}
            self._compute_global_assignment(active, docks, now, settings)
        selected = self._cache.get(dock["dock_id"])
        eligible = {t["truck_id"]: t for t in compatible}
        previously_returned = {tid for did, tid in self._returned.items() if did != dock["dock_id"]}
        if selected not in eligible or selected in previously_returned:
            # A stale candidate must never escape the cache. Replan remaining
            # resources within this batch, without reusing an already returned ID.
            remaining_docks = [d for d in docks if d["dock_id"] not in self._returned or d["dock_id"] == dock["dock_id"]]
            remaining_tasks = [t for t in active if t["truck_id"] not in previously_returned]
            self._compute_global_assignment(remaining_tasks, remaining_docks, now, settings)
            selected = self._cache.get(dock["dock_id"])
        if selected is None:
            # If this dock was unmatched, moving a compatible matched truck here
            # preserves cardinality and total priority (priority is dock-independent).
            candidates = [t for t in compatible if t["truck_id"] not in previously_returned]
            if not candidates:
                self.last_result = SchedulerSelectResult(None, "no_ready_task")
                self.last_stats = SchedulerStats(len(ready_trucks), 0,
                                                (perf_counter() - started) * 1000, "no_ready_task")
                return None
            selected = min(candidates, key=lambda t: (-self._compute_truck_priority(t, now, settings),
                                                      t["ready_since"], t["arrival_time"], t["truck_id"]))["truck_id"]
            for did, tid in self._cache.items():
                if tid == selected:
                    self._cache[did] = None
            self._cache[dock["dock_id"]] = selected
        self._returned[dock["dock_id"]] = selected
        self.last_result = SchedulerSelectResult(eligible[selected], "selected_by_jointda_batch")
        self.last_stats = SchedulerStats(len(ready_trucks), len(compatible),
                                        (perf_counter() - started) * 1000, "selected_by_jointda_batch")
        return self.last_result
