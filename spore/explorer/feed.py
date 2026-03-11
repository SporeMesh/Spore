"""Derived feed and momentum helpers for explorer APIs."""

from __future__ import annotations

import time
from collections import defaultdict

from ..node import SporeNode
from ..record import ExperimentRecord, Status
from .state import (
    collect_explorer_state,
    record_with_profile,
)

DEFAULT_PULSE_WINDOW_SECONDS = 6 * 60 * 60


def _status_value(record: ExperimentRecord) -> str:
    return record.status.value if isinstance(record.status, Status) else record.status


def _display_name(node: SporeNode, node_id: str, profiles_by_id: dict) -> str:
    profile = profiles_by_id.get(node_id)
    return profile.display_name if profile and profile.display_name else node_id[:8]


def _task_name(task_by_id: dict[str, dict], task_id: str) -> str:
    task = task_by_id.get(task_id)
    return task["name"] if task else task_id[:8]


def build_feed_event(
    node: SporeNode,
    record: ExperimentRecord,
    *,
    frontier_ids: set[str],
    verified_ids: set[str],
    profiles_by_id: dict,
    task_by_id: dict[str, dict],
) -> dict:
    data = record_with_profile(
        node,
        record,
        frontier_ids=frontier_ids,
        verified_ids=verified_ids,
        profiles_by_id=profiles_by_id,
    )
    parent = node.graph.get(record.parent) if record.parent else None
    delta = None if parent is None else record.val_bpb - parent.val_bpb
    status = _status_value(record)
    actor = _display_name(node, record.node_id, profiles_by_id)
    task_name = _task_name(task_by_id, record.task_id)
    if status == Status.CRASH.value:
        kind = "crash"
        headline = f"{actor} hit a crash on {task_name}"
        summary = record.description or "Experiment crashed before completion."
    elif status == Status.DISCARD.value:
        kind = "discard"
        headline = f"{actor} tested an idea on {task_name}"
        summary = record.description or "Result was worse than its parent."
    else:
        kind = "frontier_keep" if record.id in frontier_ids else "keep"
        if kind == "frontier_keep":
            headline = f"{actor} moved the frontier on {task_name}"
        else:
            headline = f"{actor} found a keep on {task_name}"
        summary = record.description or "Result improved enough to keep."
    if delta is None:
        impact = "baseline"
    elif delta < 0:
        impact = f"improved by {abs(delta):.6f}"
    elif delta > 0:
        impact = f"worse by {delta:.6f}"
    else:
        impact = "matched parent"
    return {
        "kind": kind,
        "headline": headline,
        "summary": summary,
        "impact": impact,
        "delta_bpb": delta,
        "before_val_bpb": parent.val_bpb if parent else None,
        "after_val_bpb": record.val_bpb,
        "task_id": record.task_id,
        "task_name": task_name,
        "node_id": record.node_id,
        "node_display_name": actor,
        "timestamp": record.timestamp,
        "verified": record.id in verified_ids,
        "share_path": f"/?experiment={record.id}",
        "task_path": f"/?task={record.task_id}",
        "node_path": f"/?node={record.node_id}",
        "record": data,
    }


def recent_feed(
    node: SporeNode,
    *,
    task_id: str = "",
    node_id: str = "",
    limit: int = 50,
    keep_only: bool = False,
) -> list[dict]:
    explorer = collect_explorer_state(node, task_id)
    tasks = {task["task_id"]: task for task in node.all_tasks()}
    records = explorer["records"]
    if node_id:
        records = [record for record in records if record.node_id == node_id]
    if keep_only:
        records = [
            record for record in records if _status_value(record) == Status.KEEP.value
        ]
    records = sorted(
        records,
        key=lambda record: (record.timestamp, record.depth, record.id),
        reverse=True,
    )[: max(1, min(limit, 200))]
    return [
        build_feed_event(
            node,
            record,
            frontier_ids=explorer["frontier_ids"],
            verified_ids=explorer["verified_ids"],
            profiles_by_id=explorer["profiles_by_id"],
            task_by_id=tasks,
        )
        for record in records
    ]


def hot_tasks(node: SporeNode, *, limit: int = 10) -> list[dict]:
    ranked = []
    for task in node.all_tasks():
        recent = node.graph.recent_by_task(task["task_id"], limit=25)
        keep_count = sum(
            1 for record in recent if _status_value(record) == Status.KEEP.value
        )
        crash_count = sum(
            1 for record in recent if _status_value(record) == Status.CRASH.value
        )
        participant_ids = {record.node_id for record in recent}
        frontier = node.graph.frontier_by_task(task["task_id"])
        ranked.append(
            {
                "task_id": task["task_id"],
                "name": task["name"],
                "description": task.get("description", ""),
                "task_type": task["task_type"],
                "metric": task.get("metric", ""),
                "goal": task.get("goal", ""),
                "participant_count": len(participant_ids),
                "frontier_size": len(frontier),
                "recent_experiment_count": len(recent),
                "recent_keep_count": keep_count,
                "recent_crash_count": crash_count,
                "recent_compute_seconds": sum(
                    record.time_budget or 0 for record in recent
                ),
                "latest_activity": max(
                    (record.timestamp for record in recent), default=0
                ),
                "best_val_bpb": (frontier[0].val_bpb if frontier else None),
            }
        )
    ranked.sort(
        key=lambda item: (
            item["recent_experiment_count"],
            item["recent_keep_count"],
            item["latest_activity"],
            item["task_id"],
        ),
        reverse=True,
    )
    return ranked[: max(1, min(limit, 50))]


def network_pulse(
    node: SporeNode,
    *,
    task_id: str = "",
    window_seconds: int = DEFAULT_PULSE_WINDOW_SECONDS,
    limit: int = 5,
) -> dict:
    explorer = collect_explorer_state(node, task_id)
    cutoff = int(time.time()) - max(60, window_seconds)
    tasks = {task["task_id"]: task for task in node.all_tasks()}
    recent_records = [
        record
        for record in sorted(
            explorer["records"],
            key=lambda item: (item.timestamp, item.depth, item.id),
            reverse=True,
        )
        if record.timestamp >= cutoff
    ]
    keep_count = sum(1 for record in recent_records if _status_value(record) == "keep")
    discard_count = sum(
        1 for record in recent_records if _status_value(record) == "discard"
    )
    crash_count = sum(
        1 for record in recent_records if _status_value(record) == "crash"
    )
    frontier_move_count = sum(
        1 for record in recent_records if record.id in explorer["frontier_ids"]
    )
    node_recent: dict[str, dict] = defaultdict(
        lambda: {
            "node_id": "",
            "experiment_count": 0,
            "keep_count": 0,
            "frontier_count": 0,
            "last_seen": 0,
        }
    )
    for record in recent_records:
        bucket = node_recent[record.node_id]
        bucket["node_id"] = record.node_id
        bucket["experiment_count"] += 1
        bucket["last_seen"] = max(bucket["last_seen"], record.timestamp)
        if _status_value(record) == "keep":
            bucket["keep_count"] += 1
        if record.id in explorer["frontier_ids"]:
            bucket["frontier_count"] += 1

    active_nodes = []
    for summary in explorer["summaries"]:
        recent = node_recent.get(summary["node_id"])
        if not recent:
            continue
        active_nodes.append(
            {
                "node_id": summary["node_id"],
                "display_name": summary["display_name"],
                "avatar_url": summary["avatar_url"],
                "bio": summary["bio"],
                "activity": summary["activity"],
                "has_profile": summary["has_profile"],
                "profile": summary["profile"],
                "experiment_count_recent": recent["experiment_count"],
                "keep_count_recent": recent["keep_count"],
                "frontier_count_recent": recent["frontier_count"],
                "last_seen": recent["last_seen"],
            }
        )
    active_nodes.sort(
        key=lambda item: (
            item["frontier_count_recent"],
            item["keep_count_recent"],
            item["experiment_count_recent"],
            item["last_seen"],
            item["node_id"],
        ),
        reverse=True,
    )

    hot = hot_tasks(node, limit=max(1, min(limit, 10)))
    if task_id:
        hot = [item for item in hot if item["task_id"] == task_id]
    recent_events = [
        build_feed_event(
            node,
            record,
            frontier_ids=explorer["frontier_ids"],
            verified_ids=explorer["verified_ids"],
            profiles_by_id=explorer["profiles_by_id"],
            task_by_id=tasks,
        )
        for record in recent_records[: max(1, min(limit * 2, 12))]
    ]
    best = explorer["frontier"][0].val_bpb if explorer["frontier"] else None
    return {
        "task_id": explorer["task_id"],
        "window_seconds": window_seconds,
        "experiment_count_recent": len(recent_records),
        "compute_seconds_recent": sum(
            record.time_budget or 0 for record in recent_records
        ),
        "keep_count_recent": keep_count,
        "discard_count_recent": discard_count,
        "crash_count_recent": crash_count,
        "frontier_move_count_recent": frontier_move_count,
        "active_node_count_recent": len(node_recent),
        "active_task_count_recent": len(
            {record.task_id for record in recent_records if record.task_id}
        ),
        "keep_rate_recent": (keep_count / len(recent_records))
        if recent_records
        else 0.0,
        "best_val_bpb": best,
        "hot_tasks": hot,
        "active_nodes": active_nodes[: max(1, min(limit, 10))],
        "stories": recent_events,
    }
