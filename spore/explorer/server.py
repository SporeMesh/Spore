"""Spore Explorer — FastAPI server with REST + WebSocket for the research graph."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..node import SporeNode
from ..profile import NodeProfile
from ..record import ExperimentRecord, Status

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self._active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self._active:
            self._active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self._active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._active)


def _record_to_dict(r: ExperimentRecord) -> dict:
    status = r.status.value if isinstance(r.status, Status) else r.status
    return {
        "id": r.id,
        "parent": r.parent,
        "depth": r.depth,
        "code_cid": r.code_cid,
        "diff": r.diff,
        "dataset_cid": r.dataset_cid,
        "prepare_cid": r.prepare_cid,
        "time_budget": r.time_budget,
        "val_bpb": r.val_bpb,
        "peak_vram_mb": r.peak_vram_mb,
        "num_steps": r.num_steps,
        "num_params": r.num_params,
        "status": status,
        "description": r.description,
        "hypothesis": r.hypothesis,
        "agent_model": r.agent_model,
        "gpu_model": r.gpu_model,
        "cuda_version": r.cuda_version,
        "torch_version": r.torch_version,
        "node_id": r.node_id,
        "timestamp": r.timestamp,
        "signature": r.signature,
        "version": r.version,
    }


def _profile_to_dict(profile: NodeProfile | None) -> dict | None:
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


def _record_with_profile(node: SporeNode, record: ExperimentRecord) -> dict:
    data = _record_to_dict(record)
    profile = node.get_profile(record.node_id)
    if profile:
        data["node_display_name"] = profile.display_name
    return data


def create_app(node: SporeNode) -> FastAPI:
    app = FastAPI(title="Spore Explorer", version="0.1.0")
    ws_manager = ConnectionManager()

    def on_new_experiment(record: ExperimentRecord):
        data = {"event": "experiment", "data": _record_to_dict(record)}
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(ws_manager.broadcast(data), loop=loop)
        except RuntimeError:
            pass

    node.add_listener(on_new_experiment)

    # --- Static ---

    @app.get("/", response_class=HTMLResponse)
    async def index():
        html_path = STATIC_DIR / "index.html"
        return HTMLResponse(html_path.read_text())

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # --- REST API ---

    @app.get("/api/stat")
    async def stat():
        total = node.graph.count()
        frontier = node.graph.frontier()
        best_bpb = frontier[0].val_bpb if frontier else None
        return {
            "experiment_count": total,
            "frontier_size": len(frontier),
            "best_val_bpb": best_bpb,
            "peer_count": len(node.gossip.peers),
            "node_id": node.node_id,
            "ws_client": ws_manager.count,
        }

    @app.get("/api/graph")
    async def graph():
        records = node.graph.all_records()
        frontier = node.graph.frontier()
        frontier_id = {r.id for r in frontier}

        nodes = []
        edges = []
        for r in records:
            nodes.append(_record_with_profile(node, r))
            if r.parent:
                edges.append({"source": r.parent, "target": r.id})

        return {
            "node": nodes,
            "edge": edges,
            "frontier_id": list(frontier_id),
        }

    @app.get("/api/frontier")
    async def frontier(gpu: str | None = None):
        results = node.graph.frontier(gpu_class=gpu)
        return [_record_with_profile(node, r) for r in results]

    @app.get("/api/experiment/{cid}")
    async def experiment(cid: str):
        record = node.graph.get(cid)
        if not record:
            return {"error": "not found"}
        return _record_with_profile(node, record)

    @app.get("/api/experiment/{cid}/ancestor")
    async def ancestor(cid: str):
        chain = node.graph.ancestors(cid)
        return [_record_with_profile(node, r) for r in chain]

    @app.get("/api/experiment/{cid}/children")
    async def children(cid: str):
        kids = node.graph.children(cid)
        return [_record_with_profile(node, r) for r in kids]

    @app.get("/api/recent")
    async def recent(limit: int = 50):
        records = node.graph.recent(limit=limit)
        return [_record_with_profile(node, r) for r in records]

    @app.get("/api/node/{node_id}/experiment")
    async def node_experiment(node_id: str):
        records = node.graph.by_node(node_id)
        return [_record_with_profile(node, r) for r in records]

    @app.get("/api/node/{node_id}/reputation")
    async def node_reputation(node_id: str):
        return node.reputation.get_stats(node_id)

    @app.get("/api/node/{node_id}/profile")
    async def node_profile(node_id: str):
        return _profile_to_dict(node.get_profile(node_id)) or {"error": "not found"}

    @app.get("/api/search")
    async def search(q: str = ""):
        """Search experiments by CID prefix, description, or node ID."""
        if not q or len(q) < 2:
            return []
        q_lower = q.lower()
        results = []
        for r in node.graph.all_records():
            if (
                (r.id and r.id.startswith(q))
                or q_lower in r.description.lower()
                or (r.node_id and r.node_id.startswith(q))
                or q_lower in (r.gpu_model or "").lower()
                or q_lower
                in (
                    (
                        node.get_profile(r.node_id) or NodeProfile(node_id=r.node_id)
                    ).display_name.lower()
                )
            ):
                results.append(_record_with_profile(node, r))
            if len(results) >= 20:
                break
        return results

    @app.get("/api/leaderboard")
    async def leaderboard():
        rows = node.reputation.leaderboard(limit=50)
        for row in rows:
            profile = node.get_profile(row["node_id"])
            if profile:
                row["display_name"] = profile.display_name
        return rows

    @app.get("/api/artifact/{cid}")
    async def artifact(cid: str):
        """Get stored code artifact by CID."""
        data = node.store.get(cid)
        if data is None:
            data = await node.fetch_code(cid)
        if data is None:
            return {"error": "not found"}
        return {"cid": cid, "content": data.decode("utf-8", errors="replace")}

    # --- WebSocket ---

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws_manager.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)

    return app
