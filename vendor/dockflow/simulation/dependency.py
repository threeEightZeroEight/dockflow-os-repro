"""Runtime IN -> OUT dependency benefits, independent of scheduling policy.

A blocked OUT waiting for several inbound trucks is *affected* by all of
them, but only the last unfinished inbound can *immediately unlock* it.
"""
from __future__ import annotations

from collections import Counter
from typing import Mapping, Any


def dependency_scores(
    trucks: Mapping[str, Mapping[str, Any]],
    finished_in: set[str],
    now: float,
) -> dict[str, tuple[int, int]]:
    """Return (immediate_unlock_count, dependent_blocked_count) by truck ID.

    Only arrived, BLOCKED OUT trucks contribute. IN status PROCESSING or
    EXITING alone is insufficient: caller supplies IDs whose SERVICE_FINISHED
    event was actually processed. Does not mutate input.
    """
    immediate: Counter[str] = Counter()
    affected: Counter[str] = Counter()
    for out in trucks.values():
        if (out["direction"] != "OUT" or out["status"] != "BLOCKED"
                or out["arrival_time"] > now):
            continue
        remaining = set(out["depends_on"]) - finished_in
        for ident in remaining:
            affected[ident] += 1
        if len(remaining) == 1:
            immediate[next(iter(remaining))] += 1
    return {
        ident: (immediate[ident], affected[ident]) if truck["direction"] == "IN" else (0, 0)
        for ident, truck in trucks.items()
    }
