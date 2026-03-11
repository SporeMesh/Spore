"""Periodic peer reconciliation for missed gossip and stale connections."""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

RESYNC_INTERVAL_SEC = 120


class PeerSyncLoop:
    """Keep peer state fresh by periodically re-running sync and peer exchange."""

    def __init__(self, interval_sec: int = RESYNC_INTERVAL_SEC):
        self.interval_sec = max(30, interval_sec)
        self._task: asyncio.Task | None = None

    def start(self, node) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(node))

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self, node) -> None:
        while True:
            try:
                await asyncio.sleep(self.interval_sec)
                await self._sync_known_peers(node)
                await self._sync_connected_peers(node)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Periodic peer sync failed")

    async def _sync_known_peers(self, node) -> None:
        targets = list(dict.fromkeys(node.config.peer + node._load_known_peer()))
        for peer_addr in targets:
            host, _, port_str = peer_addr.partition(":")
            if not port_str or node._should_skip_peer(peer_addr):
                continue
            connected = await node.gossip.connect_to_peer(host, int(port_str))
            if connected:
                node._save_peer(peer_addr)
            else:
                node._drop_peer(peer_addr)

    async def _sync_connected_peers(self, node) -> None:
        for peer_addr in list(node.gossip.peers):
            try:
                await node.gossip.request_pex(peer_addr)
                await node.gossip.request_sync(
                    peer_addr,
                    since_timestamp=node.graph.latest_timestamp(),
                )
                await node.gossip.request_control_sync(
                    peer_addr,
                    since_timestamp=node.control.latest_timestamp(),
                )
                await node.gossip.request_task_sync(
                    peer_addr,
                    since_timestamp=node.task.latest_timestamp(),
                )
            except Exception:
                log.warning("Dropping unhealthy peer %s", peer_addr)
                node.gossip._remove_peer(peer_addr)
                node._drop_peer(peer_addr)
