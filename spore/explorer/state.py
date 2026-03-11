"""Explorer data shaping helpers."""

from __future__ import annotations

from collections import defaultdict

from ..node import SporeNode
from ..profile import NodeProfile
from ..record import ExperimentRecord, Status


def record_to_dict(record: ExperimentRecord) -> dict:
    status = record.status.value if isinstance(record.status, Status) else record.status
    return {
        "id": record.id,
        "parent": record.parent,
        "depth": record.depth,
        "task_id": record.task_id,
        "code_cid": record.code_cid,
        "diff": record.diff,
        "dataset_cid": record.dataset_cid,
        "prepare_cid": record.prepare_cid,
        "time_budget": record.time_budget,
        "val_bpb": record.val_bpb,
        "peak_vram_mb": record.peak_vram_mb,
        "num_steps": record.num_steps,
        "num_params": record.num_params,
        "status": status,
        "description": record.description,
        "hypothesis": record.hypothesis,
        "agent_model": record.agent_model,
        "gpu_model": record.gpu_model,
        "cuda_version": record.cuda_version,
        "torch_version": record.torch_version,
        "node_id": record.node_id,
        "timestamp": record.timestamp,
        "signature": record.signature,
        "version": record.version,
    }


def profile_to_dict(profile: NodeProfile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "id": profile.id,
        "node_id": profile.node_id,
        "display_name": profile.display_name,
        "bio": profile.bio,
        "website": profile.website,
        "avatar_url": profile.avatar_url,
        "donation_address": profile.donation_address,
        "timestamp": profile.timestamp,
        "schema_version": profile.schema_version,
    }


def classify_node_activity(reputation: dict) -> str:
    published = reputation.get("experiments_published", 0)
    verifier_work = (
        reputation.get("verifications_performed", 0)
        + reputation.get("disputes_won", 0)
        + reputation.get("disputes_lost", 0)
    )
    if published and verifier_work:
        return "hybrid"
    if published:
        return "researcher"
    if verifier_work:
        return "verifier"
    return "observer"


def record_matches_filters(
    record: ExperimentRecord,
    *,
    status: str = "all",
    gpu: str | None = None,
    verified_only: bool = False,
    frontier_only: bool = False,
    verified_ids: set[str] | None = None,
    frontier_ids: set[str] | None = None,
) -> bool:
    record_status = (
        record.status.value if isinstance(record.status, Status) else record.status
    )
    if status not in {"", "all"} and record_status != status:
        return False
    if gpu and record.gpu_model != gpu:
        return False
    if verified_only and (verified_ids is None or record.id not in verified_ids):
        return False
    if frontier_only and (frontier_ids is None or record.id not in frontier_ids):
        return False
    return True


def record_with_profile(
    node: SporeNode,
    record: ExperimentRecord,
    *,
    frontier_ids: set[str] | None = None,
    verified_ids: set[str] | None = None,
    profiles_by_id: dict[str, NodeProfile] | None = None,
) -> dict:
    data = record_to_dict(record)
    profile = profiles_by_id.get(record.node_id) if profiles_by_id is not None else None
    if profile is None:
        profile = node.get_profile(record.node_id)
    if profile:
        data["node_display_name"] = profile.display_name
        data["node_avatar_url"] = profile.avatar_url
    data["verified"] = (
        record.id in verified_ids
        if verified_ids is not None
        else node.graph.is_verified(record.id)
    )
    data["is_frontier"] = (
        record.id in frontier_ids
        if frontier_ids is not None
        else record.id in {item.id for item in node.graph.frontier()}
    )
    return data


def build_node_summary(
    node_id: str,
    records: list[ExperimentRecord],
    profile: NodeProfile | None,
    reputation: dict,
    *,
    frontier_ids: set[str],
    verified_ids: set[str],
    node_ref: SporeNode,
) -> dict:
    keep_count = 0
    discard_count = 0
    crash_count = 0
    frontier_count = 0
    verified_count = 0
    gpu_models: set[str] = set()
    agent_models: set[str] = set()
    best_record: ExperimentRecord | None = None
    latest_record: ExperimentRecord | None = None
    task_ids = {record.task_id for record in records if record.task_id}

    for record in records:
        status = (
            record.status.value if isinstance(record.status, Status) else record.status
        )
        if status == Status.KEEP.value:
            keep_count += 1
        elif status == Status.DISCARD.value:
            discard_count += 1
        elif status == Status.CRASH.value:
            crash_count += 1
        if record.id in frontier_ids:
            frontier_count += 1
        if record.id in verified_ids:
            verified_count += 1
        if record.gpu_model:
            gpu_models.add(record.gpu_model)
        if record.agent_model:
            agent_models.add(record.agent_model)
        if best_record is None or record.val_bpb < best_record.val_bpb:
            best_record = record
        if latest_record is None or (
            record.timestamp,
            record.depth,
            record.id,
        ) >= (
            latest_record.timestamp,
            latest_record.depth,
            latest_record.id,
        ):
            latest_record = record

    return {
        "node_id": node_id,
        "display_name": profile.display_name if profile else "",
        "avatar_url": profile.avatar_url if profile else "",
        "bio": profile.bio if profile else "",
        "website": profile.website if profile else "",
        "donation_address": profile.donation_address if profile else "",
        "has_profile": profile is not None,
        "profile": profile_to_dict(profile),
        "reputation": reputation,
        "activity": classify_node_activity(reputation),
        "experiment_count": len(records),
        "keep_count": keep_count,
        "discard_count": discard_count,
        "crash_count": crash_count,
        "frontier_count": frontier_count,
        "verified_count": verified_count,
        "task_count": len(task_ids),
        "first_seen": min((r.timestamp for r in records), default=None),
        "last_seen": max((r.timestamp for r in records), default=None),
        "gpu_models": sorted(gpu_models),
        "agent_models": sorted(agent_models),
        "best_val_bpb": best_record.val_bpb if best_record else None,
        "best_experiment": (
            record_with_profile(
                node_ref,
                best_record,
                frontier_ids=frontier_ids,
                verified_ids=verified_ids,
            )
            if best_record
            else None
        ),
        "latest_experiment": (
            record_with_profile(
                node_ref,
                latest_record,
                frontier_ids=frontier_ids,
                verified_ids=verified_ids,
            )
            if latest_record
            else None
        ),
    }


def resolve_task_id(node: SporeNode, requested_task_id: str = "") -> str:
    return requested_task_id or node.active_task_id or ""


def collect_explorer_state(node: SporeNode, requested_task_id: str = "") -> dict:
    task_id = resolve_task_id(node, requested_task_id)
    records = node.graph.by_task(task_id) if task_id else node.graph.all_records()
    frontier = (
        node.graph.frontier_by_task(task_id) if task_id else node.graph.frontier()
    )
    frontier_ids = {record.id for record in frontier}
    verified_ids = node.graph.verified_ids()
    profiles_by_id = {profile.node_id: profile for profile in node.profile.all()}
    reputation_by_id = {row["node_id"]: row for row in node.reputation.all_stats()}
    records_by_node: dict[str, list[ExperimentRecord]] = defaultdict(list)
    for record in records:
        records_by_node[record.node_id].append(record)

    all_node_ids = set(records_by_node) | set(profiles_by_id) | set(reputation_by_id)
    summaries = []
    for node_id in all_node_ids:
        reputation = reputation_by_id.get(node_id) or node.reputation.get_stats(node_id)
        summaries.append(
            build_node_summary(
                node_id,
                records_by_node.get(node_id, []),
                profiles_by_id.get(node_id),
                reputation,
                frontier_ids=frontier_ids,
                verified_ids=verified_ids,
                node_ref=node,
            )
        )

    return {
        "task_id": task_id,
        "records": records,
        "records_by_node": records_by_node,
        "frontier": frontier,
        "frontier_ids": frontier_ids,
        "verified_ids": verified_ids,
        "profiles_by_id": profiles_by_id,
        "summaries": summaries,
        "summaries_by_id": {summary["node_id"]: summary for summary in summaries},
    }


def task_summary(node: SporeNode, task_row: dict) -> dict:
    task_id = task_row["task_id"]
    records = node.graph.by_task(task_id)
    frontier = node.graph.frontier_by_task(task_id)
    participants = sorted({record.node_id for record in records})
    root_id = task_row.get("root_experiment_id") or next(
        iter(node.graph.root_ids_by_task(task_id)),
        "",
    )
    return {
        "task_id": task_id,
        "name": task_row["name"],
        "description": task_row["description"],
        "task_type": task_row["task_type"],
        "artifact_type": task_row["artifact_type"],
        "metric": task_row["metric"],
        "goal": task_row["goal"],
        "source": task_row["source"],
        "created_by": task_row["created_by"],
        "timestamp": task_row["timestamp"],
        "root_experiment_id": root_id,
        "experiment_count": len(records),
        "frontier_size": len(frontier),
        "best_val_bpb": frontier[0].val_bpb if frontier else None,
        "participant_count": len(participants),
        "participants": participants,
        "latest_activity": max((record.timestamp for record in records), default=0),
        "is_active": task_id == node.active_task_id,
    }


def all_task_summaries(node: SporeNode) -> list[dict]:
    tasks = [task_summary(node, row) for row in node.all_tasks()]
    tasks.sort(
        key=lambda item: (
            item["latest_activity"],
            item["experiment_count"],
            item["task_id"],
        ),
        reverse=True,
    )
    return tasks
