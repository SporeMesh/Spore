"""Derived feed and momentum helpers for explorer APIs."""

from __future__ import annotations

from ..node import SporeNode
from ..record import ExperimentRecord, Status
from .state import collect_explorer_state, record_with_profile


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
    status = record.status.value if isinstance(record.status, Status) else record.status
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
        "task_id": record.task_id,
        "task_name": task_name,
        "node_id": record.node_id,
        "node_display_name": actor,
        "timestamp": record.timestamp,
        "verified": record.id in verified_ids,
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
            record
            for record in records
            if (
                record.status.value
                if isinstance(record.status, Status)
                else record.status
            )
            == Status.KEEP.value
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
            1
            for record in recent
            if (
                record.status.value
                if isinstance(record.status, Status)
                else record.status
            )
            == Status.KEEP.value
        )
        ranked.append(
            {
                "task_id": task["task_id"],
                "name": task["name"],
                "task_type": task["task_type"],
                "recent_experiment_count": len(recent),
                "recent_keep_count": keep_count,
                "latest_activity": max(
                    (record.timestamp for record in recent), default=0
                ),
                "best_val_bpb": (
                    node.graph.best_by_task(task["task_id"]).val_bpb
                    if node.graph.best_by_task(task["task_id"])
                    else None
                ),
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
