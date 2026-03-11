"""Artifact fetch coordination and code prefetching."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time

log = logging.getLogger(__name__)

FETCH_DEADLINE_SEC = 60.0


class ArtifactSync:
    """Coordinate code fetches so multiple consumers share the same request."""

    def __init__(self):
        self._inflight: dict[str, asyncio.Task] = {}

    async def fetch(self, node, code_cid: str, preferred_peer: str | None = None):
        """Fetch code by CID, sharing inflight work across callers."""
        cached = node.store.get(code_cid)
        if cached is not None:
            return cached

        task = self._inflight.get(code_cid)
        if task is None:
            task = asyncio.create_task(self._fetch_once(node, code_cid, preferred_peer))
            self._inflight[code_cid] = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._inflight.pop(code_cid, None)

    def prefetch(self, node, code_cid: str, preferred_peer: str | None = None):
        """Start a background code fetch if the artifact is not cached yet."""
        if node.store.get(code_cid) is not None or code_cid in self._inflight:
            return
        self._inflight[code_cid] = asyncio.create_task(
            self._fetch_once(node, code_cid, preferred_peer)
        )

    async def _fetch_once(self, node, code_cid: str, preferred_peer: str | None):
        attempted: set[str] = set()
        deadline = time.monotonic() + FETCH_DEADLINE_SEC

        while time.monotonic() < deadline:
            peers = list(node.gossip.peers.keys())
            if preferred_peer and preferred_peer in peers:
                peers.remove(preferred_peer)
                peers.insert(0, preferred_peer)
            pending = [addr for addr in peers if addr not in attempted]
            if not pending:
                await asyncio.sleep(0.5)
                continue

            for addr in pending:
                attempted.add(addr)
                try:
                    code_bytes = await node.gossip.request_code(
                        addr, code_cid, timeout=10.0
                    )
                except Exception as exc:
                    log.warning("Code fetch from %s failed: %s", addr, exc)
                    continue
                if code_bytes is None:
                    continue
                actual_cid = hashlib.sha256(code_bytes).hexdigest()
                if actual_cid != code_cid:
                    log.warning(
                        "Code CID mismatch from %s: expected %s, got %s",
                        addr,
                        code_cid[:8],
                        actual_cid[:8],
                    )
                    continue
                node.store.put(code_bytes)
                return code_bytes

        return None
