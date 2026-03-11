"""Gossip protocol — broadcast experiment records between peers.

MVP uses raw TCP. Each message is a length-prefixed JSON payload.
Wire format: 4-byte big-endian length + UTF-8 JSON body.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Callable

from .control import SignedControlEvent
from .profile import NodeProfile
from .record import ExperimentRecord
from .task import TaskManifest
from .wire import MessageType, encode_message, read_message

log = logging.getLogger(__name__)


class GossipServer:
    """TCP server that accepts peer connections and gossips experiment records."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 7470,
        on_experiment: Callable[[ExperimentRecord], None] | None = None,
        on_task: Callable[[TaskManifest], None] | None = None,
        on_sync_request: Callable[[int], list[ExperimentRecord]] | None = None,
        on_control_sync_request: Callable[[int], list[SignedControlEvent]]
        | None = None,
        on_task_sync_request: Callable[[int], list[TaskManifest]] | None = None,
        on_new_peer: Callable[[str], None] | None = None,
        on_control_event: Callable[[SignedControlEvent], None] | None = None,
        on_challenge: Callable[[dict], None] | None = None,
        on_challenge_response: Callable[[dict], None] | None = None,
        on_dispute: Callable[[dict], None] | None = None,
        on_verification: Callable[[dict], None] | None = None,
        on_profile: Callable[[NodeProfile], None] | None = None,
        on_code_request: Callable[[str], bytes | None] | None = None,
    ):
        self.host = host
        self.port = port
        self.on_experiment = on_experiment
        self.on_task = on_task
        self.on_sync_request = on_sync_request
        self.on_control_sync_request = on_control_sync_request
        self.on_task_sync_request = on_task_sync_request
        self.on_new_peer = on_new_peer
        self.on_control_event = on_control_event
        self.on_challenge = on_challenge
        self.on_challenge_response = on_challenge_response
        self.on_dispute = on_dispute
        self.on_verification = on_verification
        self.on_profile = on_profile
        self.on_code_request = on_code_request
        self._experiment_accepts_addr = False
        if self.on_experiment is not None:
            self._experiment_accepts_addr = (
                len(inspect.signature(self.on_experiment).parameters) > 1
            )
        self.peers: dict[str, tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}
        self._advertised_peers: set[str] = set()
        self.seen_cid: set[str] = set()
        self.seen_task: set[str] = set()
        self.seen_event: set[str] = set()
        self._server: asyncio.Server | None = None
        self._tasks: list[asyncio.Task] = []
        self._pending_code: dict[str, asyncio.Future] = {}
        self._pending_sync: dict[tuple[str, str], asyncio.Future] = {}

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        log.info("Gossip server listening on %s:%d", self.host, self.port)

    async def stop(self):
        # Cancel all listen tasks
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for _, (_, writer) in self.peers.items():
            writer.close()
        self.peers.clear()

    async def connect_to_peer(self, host: str, port: int) -> bool:
        """Connect to a remote peer."""
        addr = f"{host}:{port}"
        if addr in self.peers:
            return True
        try:
            reader, writer = await asyncio.open_connection(host, port)
            self.peers[addr] = (reader, writer)
            self._advertised_peers.add(addr)
            task = asyncio.create_task(self._listen(addr, reader))
            self._tasks.append(task)
            log.info("Connected to peer %s", addr)
            return True
        except Exception as e:
            log.warning("Failed to connect to %s: %s", addr, e)
            return False

    async def broadcast_experiment(self, record: ExperimentRecord):
        """Broadcast an experiment record to all connected peers."""
        if record.id in self.seen_cid:
            return
        self.seen_cid.add(record.id)

        msg = encode_message(
            MessageType.EXPERIMENT,
            json.loads(record.to_json()),
        )
        disconnected = []
        for addr, (_, writer) in self.peers.items():
            try:
                writer.write(msg)
                await writer.drain()
            except Exception as e:
                log.warning("Failed to send to %s: %s", addr, e)
                disconnected.append(addr)

        for addr in disconnected:
            self._remove_peer(addr)

    async def broadcast_task(self, manifest: TaskManifest):
        """Broadcast a task manifest to all connected peers."""
        if manifest.task_id in self.seen_task:
            return
        self.seen_task.add(manifest.task_id)
        msg = encode_message(MessageType.TASK, manifest.to_dict())
        disconnected = []
        for addr, (_, writer) in self.peers.items():
            try:
                writer.write(msg)
                await writer.drain()
            except Exception as exc:
                log.warning("Failed to send task to %s: %s", addr, exc)
                disconnected.append(addr)
        for addr in disconnected:
            self._remove_peer(addr)

    async def broadcast_challenge(self, payload: dict):
        """Broadcast a challenge to all peers."""
        await self._broadcast(MessageType.CHALLENGE, payload)

    async def broadcast_challenge_response(self, payload: dict):
        """Broadcast a challenge response to all peers."""
        await self._broadcast(MessageType.CHALLENGE_RESPONSE, payload)

    async def broadcast_dispute(self, payload: dict):
        """Broadcast a resolved dispute to all peers."""
        await self._broadcast(MessageType.DISPUTE, payload)

    async def broadcast_verification(self, payload: dict):
        """Broadcast a successful verification event to all peers."""
        await self._broadcast(MessageType.VERIFICATION, payload)

    async def broadcast_profile(self, profile: NodeProfile):
        """Broadcast a signed node profile to all connected peers."""
        await self._broadcast(MessageType.PROFILE, profile.to_dict())

    async def _broadcast(self, msg_type: str, payload: dict):
        """Broadcast a message to all connected peers."""
        self._mark_seen_event(msg_type, payload)
        msg = encode_message(msg_type, payload)
        for addr, (_, writer) in self.peers.items():
            try:
                writer.write(msg)
                await writer.drain()
            except Exception:
                pass

    async def request_pex(self, addr: str):
        """Ask a peer for its peer list."""
        if addr not in self.peers:
            return
        _, writer = self.peers[addr]
        msg = encode_message(MessageType.PEX_REQUEST, {})
        writer.write(msg)
        await writer.drain()

    async def request_sync(
        self, addr: str, since_timestamp: int = 0, timeout: float = 30.0
    ) -> dict | None:
        """Request all experiments from a peer since a given timestamp."""
        if addr not in self.peers:
            return None
        fut: asyncio.Future[dict | None] = asyncio.get_running_loop().create_future()
        self._pending_sync[(addr, MessageType.SYNC_RESPONSE)] = fut
        _, writer = self.peers[addr]
        msg = encode_message(
            MessageType.SYNC_REQUEST,
            {"since": since_timestamp},
        )
        writer.write(msg)
        await writer.drain()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_sync.pop((addr, MessageType.SYNC_RESPONSE), None)
            return None

    async def request_control_sync(
        self, addr: str, since_timestamp: int = 0, timeout: float = 30.0
    ) -> dict | None:
        """Request all signed control events from a peer since a given timestamp."""
        if addr not in self.peers:
            return None
        fut: asyncio.Future[dict | None] = asyncio.get_running_loop().create_future()
        self._pending_sync[(addr, MessageType.CONTROL_SYNC_RESPONSE)] = fut
        _, writer = self.peers[addr]
        msg = encode_message(
            MessageType.CONTROL_SYNC_REQUEST,
            {"since": since_timestamp},
        )
        writer.write(msg)
        await writer.drain()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_sync.pop((addr, MessageType.CONTROL_SYNC_RESPONSE), None)
            return None

    async def request_task_sync(
        self, addr: str, since_timestamp: int = 0, timeout: float = 30.0
    ) -> dict | None:
        """Request all task manifests from a peer since a given timestamp."""
        if addr not in self.peers:
            return None
        fut: asyncio.Future[dict | None] = asyncio.get_running_loop().create_future()
        self._pending_sync[(addr, MessageType.TASK_SYNC_RESPONSE)] = fut
        _, writer = self.peers[addr]
        msg = encode_message(
            MessageType.TASK_SYNC_REQUEST,
            {"since": since_timestamp},
        )
        writer.write(msg)
        await writer.drain()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_sync.pop((addr, MessageType.TASK_SYNC_RESPONSE), None)
            return None

    async def request_code(
        self, addr: str, code_cid: str, timeout: float = 30.0
    ) -> bytes | None:
        """Request code from a peer by code_cid. Returns code bytes or None."""
        if addr not in self.peers:
            return None
        fut: asyncio.Future[bytes | None] = asyncio.get_running_loop().create_future()
        self._pending_code[code_cid] = fut
        _, writer = self.peers[addr]
        msg = encode_message(MessageType.CODE_REQUEST, {"code_cid": code_cid})
        writer.write(msg)
        await writer.drain()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_code.pop(code_cid, None)
            return None

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        peername = writer.get_extra_info("peername")
        addr = f"{peername[0]}:{peername[1]}" if peername else "unknown"
        self.peers[addr] = (reader, writer)
        log.info("Peer connected: %s", addr)
        task = asyncio.create_task(self._listen(addr, reader))
        self._tasks.append(task)

    async def _listen(self, addr: str, reader: asyncio.StreamReader):
        try:
            while True:
                msg = await read_message(reader)
                if msg is None:
                    break
                await self._handle_message(addr, msg)
        except asyncio.CancelledError:
            return
        except (asyncio.IncompleteReadError, ConnectionError):
            log.info("Peer disconnected: %s", addr)
        finally:
            self._remove_peer(addr)

    async def _handle_message(self, addr: str, msg: dict):
        msg_type = msg.get("type")
        payload = msg.get("payload", {})

        if msg_type == MessageType.EXPERIMENT:
            record = ExperimentRecord.from_json(payload)
            if record.id in self.seen_cid:
                return  # already seen (dedup)

            if not record.verify_cid():
                log.warning("Invalid CID from %s, dropping", addr)
                return

            if not record.verify_signature():
                log.warning("Invalid signature from %s, dropping", addr)
                return

            self.seen_cid.add(record.id)
            if self.on_experiment:
                if self._experiment_accepts_addr:
                    self.on_experiment(record, addr)
                else:
                    self.on_experiment(record)

            # Re-gossip to other peers (fan-out)
            await self._regossip(record, exclude=addr)

        elif msg_type == MessageType.TASK:
            manifest = TaskManifest.from_json(payload)
            if manifest.task_id in self.seen_task:
                return
            if not manifest.verify_id():
                log.warning("Invalid task id from %s, dropping", addr)
                return
            if not manifest.verify_signature():
                log.warning("Invalid task signature from %s, dropping", addr)
                return
            self.seen_task.add(manifest.task_id)
            if self.on_task:
                self.on_task(manifest)
            await self._regossip_task(manifest, exclude=addr)

        elif msg_type == MessageType.SYNC_REQUEST:
            since = payload.get("since", 0)
            if self.on_sync_request and addr in self.peers:
                records = self.on_sync_request(since)
                _, writer = self.peers[addr]
                for record in records:
                    exp_msg = encode_message(
                        MessageType.EXPERIMENT,
                        json.loads(record.to_json()),
                    )
                    writer.write(exp_msg)
                    await writer.drain()
                writer.write(
                    encode_message(
                        MessageType.SYNC_RESPONSE,
                        {"since": since, "count": len(records)},
                    )
                )
                await writer.drain()
                log.info("Sync response: sent %d records to %s", len(records), addr)

        elif msg_type == MessageType.CONTROL_SYNC_REQUEST:
            since = payload.get("since", 0)
            if self.on_control_sync_request and addr in self.peers:
                events = self.on_control_sync_request(since)
                _, writer = self.peers[addr]
                for event in events:
                    control_msg = encode_message(event.type, event.to_dict())
                    writer.write(control_msg)
                    await writer.drain()
                writer.write(
                    encode_message(
                        MessageType.CONTROL_SYNC_RESPONSE,
                        {"since": since, "count": len(events)},
                    )
                )
                await writer.drain()
                log.info(
                    "Control sync response: sent %d events to %s", len(events), addr
                )

        elif msg_type == MessageType.TASK_SYNC_REQUEST:
            since = payload.get("since", 0)
            if self.on_task_sync_request and addr in self.peers:
                tasks = self.on_task_sync_request(since)
                _, writer = self.peers[addr]
                for manifest in tasks:
                    writer.write(encode_message(MessageType.TASK, manifest.to_dict()))
                    await writer.drain()
                writer.write(
                    encode_message(
                        MessageType.TASK_SYNC_RESPONSE,
                        {"since": since, "count": len(tasks)},
                    )
                )
                await writer.drain()
                log.info("Task sync response: sent %d tasks to %s", len(tasks), addr)

        elif msg_type == MessageType.SYNC_RESPONSE:
            fut = self._pending_sync.pop((addr, MessageType.SYNC_RESPONSE), None)
            if fut and not fut.done():
                fut.set_result(dict(payload))

        elif msg_type == MessageType.CONTROL_SYNC_RESPONSE:
            fut = self._pending_sync.pop(
                (addr, MessageType.CONTROL_SYNC_RESPONSE), None
            )
            if fut and not fut.done():
                fut.set_result(dict(payload))

        elif msg_type == MessageType.TASK_SYNC_RESPONSE:
            fut = self._pending_sync.pop((addr, MessageType.TASK_SYNC_RESPONSE), None)
            if fut and not fut.done():
                fut.set_result(dict(payload))

        elif msg_type == MessageType.PEX_REQUEST:
            peer_list = [a for a in sorted(self._advertised_peers) if a != addr]
            if addr in self.peers:
                _, writer = self.peers[addr]
                pex_msg = encode_message(MessageType.PEX_RESPONSE, {"peer": peer_list})
                writer.write(pex_msg)
                await writer.drain()
                log.info("PEX: sent %d peers to %s", len(peer_list), addr)

        elif msg_type == MessageType.PEX_RESPONSE:
            new_peer = payload.get("peer", [])
            for peer_addr in new_peer:
                if peer_addr not in self.peers:
                    parts = peer_addr.split(":")
                    if len(parts) == 2:
                        connected = await self.connect_to_peer(parts[0], int(parts[1]))
                        if connected and self.on_new_peer:
                            self.on_new_peer(peer_addr)
            log.info("PEX: received %d peers from %s", len(new_peer), addr)

        elif msg_type == MessageType.CHALLENGE:
            event = self._parse_control_event(addr, msg_type, payload)
            if event is None or not self._mark_seen_event(msg_type, event.payload):
                return
            if self.on_control_event:
                self.on_control_event(event)
            if self.on_challenge:
                self.on_challenge(event.payload)
            await self._regossip_control(msg_type, event.to_dict(), exclude=addr)

        elif msg_type == MessageType.CHALLENGE_RESPONSE:
            event = self._parse_control_event(addr, msg_type, payload)
            if event is None or not self._mark_seen_event(msg_type, event.payload):
                return
            if self.on_control_event:
                self.on_control_event(event)
            if self.on_challenge_response:
                self.on_challenge_response(event.payload)
            await self._regossip_control(msg_type, event.to_dict(), exclude=addr)

        elif msg_type == MessageType.DISPUTE:
            event = self._parse_control_event(addr, msg_type, payload)
            if event is None or not self._mark_seen_event(msg_type, event.payload):
                return
            if self.on_control_event:
                self.on_control_event(event)
            if self.on_dispute:
                self.on_dispute(event.payload)
            await self._regossip_control(msg_type, event.to_dict(), exclude=addr)

        elif msg_type == MessageType.VERIFICATION:
            event = self._parse_control_event(addr, msg_type, payload)
            if event is None or not self._mark_seen_event(msg_type, event.payload):
                return
            if self.on_control_event:
                self.on_control_event(event)
            if self.on_verification:
                self.on_verification(event.payload)
            await self._regossip_control(msg_type, event.to_dict(), exclude=addr)

        elif msg_type == MessageType.PROFILE:
            if not self._mark_seen_event(msg_type, payload):
                return
            profile = NodeProfile.from_json(payload)
            if not profile.verify_id():
                log.warning("Invalid profile id from %s, dropping", addr)
                return
            if not profile.verify_signature():
                log.warning("Invalid profile signature from %s, dropping", addr)
                return
            if self.on_profile:
                self.on_profile(profile)
            await self._regossip_control(msg_type, payload, exclude=addr)

        elif msg_type == MessageType.CODE_REQUEST:
            code_cid = payload.get("code_cid", "")
            if self.on_code_request and addr in self.peers:
                code_bytes = self.on_code_request(code_cid)
                if code_bytes is not None:
                    import base64

                    _, writer = self.peers[addr]
                    resp = encode_message(
                        MessageType.CODE_RESPONSE,
                        {
                            "code_cid": code_cid,
                            "code": base64.b64encode(code_bytes).decode("ascii"),
                        },
                    )
                    writer.write(resp)
                    await writer.drain()
                    log.info("Sent code %s to %s", code_cid[:8], addr)

        elif msg_type == MessageType.CODE_RESPONSE:
            import base64

            code_cid = payload.get("code_cid", "")
            code_b64 = payload.get("code", "")
            fut = self._pending_code.pop(code_cid, None)
            if fut and not fut.done():
                fut.set_result(base64.b64decode(code_b64))
            log.info("Received code %s", code_cid[:8])

        elif msg_type == MessageType.PING:
            if addr in self.peers:
                _, writer = self.peers[addr]
                writer.write(encode_message(MessageType.PONG, {}))
                await writer.drain()

    async def _regossip(self, record: ExperimentRecord, exclude: str):
        """Forward an experiment to all peers except the source."""
        msg = encode_message(
            MessageType.EXPERIMENT,
            json.loads(record.to_json()),
        )
        await self._send_to_others(msg, exclude)

    async def _regossip_task(self, manifest: TaskManifest, exclude: str):
        """Forward a task manifest to all peers except the source."""
        msg = encode_message(MessageType.TASK, manifest.to_dict())
        await self._send_to_others(msg, exclude)

    async def _send_to_others(self, msg: bytes, exclude: str):
        for addr, (_, writer) in self.peers.items():
            if addr == exclude:
                continue
            try:
                writer.write(msg)
                await writer.drain()
            except Exception:
                pass

    async def _regossip_control(self, msg_type: str, payload: dict, exclude: str):
        """Forward a control-plane event to all peers except the source."""
        msg = encode_message(msg_type, payload)
        for addr, (_, writer) in self.peers.items():
            if addr == exclude:
                continue
            try:
                writer.write(msg)
                await writer.drain()
            except Exception:
                pass

    def _mark_seen_event(self, msg_type: str, payload: dict) -> bool:
        """Return True once per unique control event."""
        event_id = payload.get("event_id")
        key = (
            f"{msg_type}:{event_id}"
            if event_id
            else f"{msg_type}:{json.dumps(payload, sort_keys=True, separators=(',', ':'))}"
        )
        if key in self.seen_event:
            return False
        self.seen_event.add(key)
        return True

    def _parse_control_event(
        self, addr: str, msg_type: str, payload: dict
    ) -> SignedControlEvent | None:
        """Parse and verify a signed control event."""
        try:
            event = SignedControlEvent.from_json(payload)
        except Exception:
            log.warning("Invalid %s payload from %s, dropping", msg_type, addr)
            return None

        if event.type != msg_type:
            log.warning("Mismatched control event type from %s, dropping", addr)
            return None
        if not event.verify_id():
            log.warning("Invalid %s id from %s, dropping", msg_type, addr)
            return None
        if not event.verify_signature():
            log.warning("Invalid %s signature from %s, dropping", msg_type, addr)
            return None
        if not self._control_actor_matches_signer(msg_type, event):
            log.warning(
                "Actor/signature mismatch for %s from %s, dropping", msg_type, addr
            )
            return None
        return event

    def _control_actor_matches_signer(
        self, msg_type: str, event: SignedControlEvent
    ) -> bool:
        """Require the signer to match the actor identity for control events."""
        actor_field = {
            MessageType.CHALLENGE: "challenger_id",
            MessageType.CHALLENGE_RESPONSE: "verifier_id",
            MessageType.DISPUTE: "challenger_id",
            MessageType.VERIFICATION: "verifier_id",
        }.get(msg_type)
        if actor_field is None:
            return True
        return event.payload.get(actor_field, "") == event.node_id

    def _remove_peer(self, addr: str):
        if addr in self.peers:
            _, writer = self.peers[addr]
            try:
                writer.close()
            except Exception:
                pass
            del self.peers[addr]
