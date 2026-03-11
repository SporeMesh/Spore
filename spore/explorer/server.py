"""Spore Explorer application."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..node import SporeNode
from ..record import ExperimentRecord
from .routes import register_routes
from .state import record_to_dict

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


def create_app(node: SporeNode, *, enable_cache: bool = False) -> FastAPI:
    app = FastAPI(title="Spore Explorer", version="0.2.0")
    ws_manager = ConnectionManager()

    def on_new_experiment(record: ExperimentRecord):
        payload = {"event": "experiment", "data": record_to_dict(record)}
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(ws_manager.broadcast(payload), loop=loop)
        except RuntimeError:
            pass

    node.add_listener(on_new_experiment)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse((STATIC_DIR / "index.html").read_text())

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    register_routes(
        app,
        node,
        ws_client_count=lambda: ws_manager.count,
        enable_cache=enable_cache,
    )

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws_manager.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)

    return app
