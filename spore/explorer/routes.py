"""REST routes for the explorer."""

from __future__ import annotations

from fastapi import FastAPI

from ..node import SporeNode
from ..profile import NodeProfile
from .feed import hot_tasks, recent_feed
from .state import (
    all_task_summaries,
    collect_explorer_state,
    profile_to_dict,
    record_matches_filters,
    record_with_profile,
    task_summary,
)


def register_routes(app: FastAPI, node: SporeNode, *, ws_client_count: callable):
    @app.get("/api/feed")
    async def feed(task_id: str = "", limit: int = 50):
        return recent_feed(node, task_id=task_id, limit=limit)

    @app.get("/api/keeps/recent")
    async def recent_keeps(task_id: str = "", limit: int = 25):
        return recent_feed(node, task_id=task_id, limit=limit, keep_only=True)

    @app.get("/api/tasks/hot")
    async def hot_task_list(limit: int = 10):
        return hot_tasks(node, limit=limit)

    @app.get("/api/stat")
    async def stat(task_id: str = ""):
        explorer = collect_explorer_state(node, task_id)
        tasks = all_task_summaries(node)
        best_bpb = explorer["frontier"][0].val_bpb if explorer["frontier"] else None
        return {
            "task_id": explorer["task_id"],
            "task_count": len(tasks),
            "active_task_id": node.active_task_id,
            "experiment_count": len(explorer["records"]),
            "frontier_size": len(explorer["frontier"]),
            "best_val_bpb": best_bpb,
            "peer_count": len(node.gossip.peers),
            "node_id": node.node_id,
            "ws_client": ws_client_count(),
            "node_count": len(explorer["summaries"]),
            "profile_count": len(explorer["profiles_by_id"]),
            "verified_experiment_count": len(explorer["verified_ids"]),
            "frontier_node_count": len(
                {
                    summary["node_id"]
                    for summary in explorer["summaries"]
                    if summary["frontier_count"] > 0
                }
            ),
        }

    @app.get("/api/tasks")
    async def tasks():
        return all_task_summaries(node)

    @app.get("/api/task/{task_id}")
    async def task_detail(task_id: str):
        task = node.get_task(task_id)
        if task is None:
            return {"error": "not found"}
        explorer = collect_explorer_state(node, task_id)
        data = task_summary(node, task)
        data["frontier"] = [
            record_with_profile(
                node,
                record,
                frontier_ids=explorer["frontier_ids"],
                verified_ids=explorer["verified_ids"],
                profiles_by_id=explorer["profiles_by_id"],
            )
            for record in explorer["frontier"]
        ]
        data["recent"] = [
            record_with_profile(
                node,
                record,
                frontier_ids=explorer["frontier_ids"],
                verified_ids=explorer["verified_ids"],
                profiles_by_id=explorer["profiles_by_id"],
            )
            for record in node.graph.recent_by_task(task_id, limit=20)
        ]
        return data

    @app.get("/api/task/{task_id}/feed")
    async def task_feed(task_id: str, limit: int = 50):
        if node.get_task(task_id) is None:
            return {"error": "not found"}
        return recent_feed(node, task_id=task_id, limit=limit)

    @app.get("/api/graph")
    async def graph(task_id: str = ""):
        explorer = collect_explorer_state(node, task_id)
        nodes = [
            record_with_profile(
                node,
                record,
                frontier_ids=explorer["frontier_ids"],
                verified_ids=explorer["verified_ids"],
                profiles_by_id=explorer["profiles_by_id"],
            )
            for record in explorer["records"]
        ]
        edges = [
            {"source": record.parent, "target": record.id}
            for record in explorer["records"]
            if record.parent
        ]
        return {
            "task_id": explorer["task_id"],
            "node": nodes,
            "edge": edges,
            "frontier_id": list(explorer["frontier_ids"]),
        }

    @app.get("/api/frontier")
    async def frontier(task_id: str = "", gpu: str | None = None):
        target_task = task_id or node.active_task_id
        results = (
            node.graph.frontier_by_task(target_task, gpu_class=gpu)
            if target_task
            else node.graph.frontier(gpu_class=gpu)
        )
        frontier_ids = {record.id for record in results}
        verified_ids = node.graph.verified_ids()
        profiles_by_id = {profile.node_id: profile for profile in node.profile.all()}
        return [
            record_with_profile(
                node,
                record,
                frontier_ids=frontier_ids,
                verified_ids=verified_ids,
                profiles_by_id=profiles_by_id,
            )
            for record in results
        ]

    @app.get("/api/experiment/{cid}")
    async def experiment(cid: str):
        record = node.graph.get(cid)
        if not record:
            return {"error": "not found"}
        return record_with_profile(
            node,
            record,
            frontier_ids={r.id for r in node.graph.frontier_by_task(record.task_id)},
            verified_ids=node.graph.verified_ids(),
        )

    @app.get("/api/experiment/{cid}/ancestor")
    async def ancestor(cid: str):
        chain = node.graph.ancestors(cid)
        if not chain:
            return []
        task_id = chain[0].task_id
        frontier_ids = {record.id for record in node.graph.frontier_by_task(task_id)}
        verified_ids = node.graph.verified_ids()
        profiles_by_id = {profile.node_id: profile for profile in node.profile.all()}
        return [
            record_with_profile(
                node,
                record,
                frontier_ids=frontier_ids,
                verified_ids=verified_ids,
                profiles_by_id=profiles_by_id,
            )
            for record in chain
        ]

    @app.get("/api/experiment/{cid}/children")
    async def children(cid: str):
        record = node.graph.get(cid)
        kids = node.graph.children(cid)
        frontier_ids = (
            {item.id for item in node.graph.frontier_by_task(record.task_id)}
            if record
            else set()
        )
        verified_ids = node.graph.verified_ids()
        profiles_by_id = {profile.node_id: profile for profile in node.profile.all()}
        return [
            record_with_profile(
                node,
                child,
                frontier_ids=frontier_ids,
                verified_ids=verified_ids,
                profiles_by_id=profiles_by_id,
            )
            for child in kids
        ]

    @app.get("/api/recent")
    async def recent(limit: int = 50, task_id: str = ""):
        explorer = collect_explorer_state(node, task_id)
        records = (
            node.graph.recent_by_task(explorer["task_id"], limit=limit)
            if explorer["task_id"]
            else node.graph.recent(limit=limit)
        )
        return [
            record_with_profile(
                node,
                record,
                frontier_ids=explorer["frontier_ids"],
                verified_ids=explorer["verified_ids"],
                profiles_by_id=explorer["profiles_by_id"],
            )
            for record in records
        ]

    @app.get("/api/nodes")
    async def nodes(
        task_id: str = "",
        activity: str = "all",
        status: str = "all",
        has_profile: bool | None = None,
        sort: str = "recent",
        limit: int = 100,
    ):
        explorer = collect_explorer_state(node, task_id)
        summaries = []
        for summary in explorer["summaries"]:
            if activity not in {"", "all"} and summary["activity"] != activity:
                continue
            if status == "keep" and summary["keep_count"] == 0:
                continue
            if status == "discard" and summary["discard_count"] == 0:
                continue
            if status == "crash" and summary["crash_count"] == 0:
                continue
            if has_profile is not None and summary["has_profile"] != has_profile:
                continue
            summaries.append(summary)

        if sort == "published":
            summaries.sort(
                key=lambda item: (
                    item["experiment_count"],
                    item["keep_count"],
                    item["last_seen"] or 0,
                ),
                reverse=True,
            )
        elif sort == "frontier":
            summaries.sort(
                key=lambda item: (
                    item["frontier_count"],
                    -(item["best_val_bpb"] or float("inf")),
                    item["last_seen"] or 0,
                ),
                reverse=True,
            )
        else:
            summaries.sort(
                key=lambda item: (item["last_seen"] or 0, item["experiment_count"]),
                reverse=True,
            )
        return summaries[: max(1, min(limit, 500))]

    @app.get("/api/nodes/search")
    async def node_search(
        q: str = "",
        task_id: str = "",
        activity: str = "all",
        status: str = "all",
        limit: int = 20,
    ):
        if not q or len(q) < 2:
            return []
        q_lower = q.lower()
        results = []
        for summary in await nodes(
            task_id=task_id,
            activity=activity,
            status=status,
            has_profile=None,
            sort="recent",
            limit=max(1, min(limit * 5, 500)),
        ):
            if (
                q_lower in summary["node_id"].lower()
                or q_lower in summary["display_name"].lower()
                or q_lower in summary["bio"].lower()
                or q_lower in summary["website"].lower()
                or any(q_lower in gpu.lower() for gpu in summary["gpu_models"])
            ):
                results.append(summary)
            if len(results) >= limit:
                break
        return results

    @app.get("/api/node/{node_id}")
    async def node_detail(
        node_id: str,
        task_id: str = "",
        status: str = "all",
        gpu: str | None = None,
        verified_only: bool = False,
        frontier_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ):
        explorer = collect_explorer_state(node, task_id)
        summary = explorer["summaries_by_id"].get(node_id)
        if summary is None:
            return {"error": "not found"}
        records = [
            record
            for record in explorer["records_by_node"].get(node_id, [])
            if record_matches_filters(
                record,
                status=status,
                gpu=gpu,
                verified_only=verified_only,
                frontier_only=frontier_only,
                verified_ids=explorer["verified_ids"],
                frontier_ids=explorer["frontier_ids"],
            )
        ]
        paged = records[offset : offset + max(1, min(limit, 500))]
        return {
            "node": summary,
            "experiments": [
                record_with_profile(
                    node,
                    record,
                    frontier_ids=explorer["frontier_ids"],
                    verified_ids=explorer["verified_ids"],
                    profiles_by_id=explorer["profiles_by_id"],
                )
                for record in paged
            ],
            "total_experiments": len(records),
            "filters": {
                "task_id": explorer["task_id"],
                "status": status,
                "gpu": gpu,
                "verified_only": verified_only,
                "frontier_only": frontier_only,
                "limit": limit,
                "offset": offset,
            },
        }

    @app.get("/api/node/{node_id}/experiment")
    async def node_experiment(
        node_id: str,
        task_id: str = "",
        status: str = "all",
        gpu: str | None = None,
        verified_only: bool = False,
        frontier_only: bool = False,
    ):
        explorer = collect_explorer_state(node, task_id)
        records = [
            record
            for record in explorer["records_by_node"].get(node_id, [])
            if record_matches_filters(
                record,
                status=status,
                gpu=gpu,
                verified_only=verified_only,
                frontier_only=frontier_only,
                verified_ids=explorer["verified_ids"],
                frontier_ids=explorer["frontier_ids"],
            )
        ]
        return [
            record_with_profile(
                node,
                record,
                frontier_ids=explorer["frontier_ids"],
                verified_ids=explorer["verified_ids"],
                profiles_by_id=explorer["profiles_by_id"],
            )
            for record in records
        ]

    @app.get("/api/node/{node_id}/profile")
    async def node_profile(node_id: str):
        return profile_to_dict(node.get_profile(node_id)) or {"error": "not found"}

    @app.get("/api/node/{node_id}/activity")
    async def node_activity(node_id: str, task_id: str = "", limit: int = 50):
        return recent_feed(node, task_id=task_id, node_id=node_id, limit=limit)

    @app.get("/api/search")
    async def search(q: str = "", task_id: str = ""):
        if not q or len(q) < 2:
            return []
        q_lower = q.lower()
        explorer = collect_explorer_state(node, task_id)
        results = []
        for record in explorer["records"]:
            profile = explorer["profiles_by_id"].get(record.node_id) or NodeProfile(
                node_id=record.node_id
            )
            if (
                record.id.startswith(q)
                or q_lower in record.description.lower()
                or record.node_id.startswith(q)
                or q_lower in (record.gpu_model or "").lower()
                or q_lower in profile.display_name.lower()
            ):
                results.append(
                    record_with_profile(
                        node,
                        record,
                        frontier_ids=explorer["frontier_ids"],
                        verified_ids=explorer["verified_ids"],
                        profiles_by_id=explorer["profiles_by_id"],
                    )
                )
            if len(results) >= 20:
                break
        return results

    @app.get("/api/artifact/{cid}")
    async def artifact(cid: str):
        data = node.store.get(cid)
        if data is None:
            data = await node.fetch_code(cid)
        if data is None:
            return {"error": "not found"}
        return {"cid": cid, "content": data.decode("utf-8", errors="replace")}
