"""Tests for gossip protocol — message encoding, server communication."""

from __future__ import annotations

import asyncio
import json
from test.conftest import make_record

import pytest

from spore.control import SignedControlEvent
from spore.gossip import GossipServer
from spore.record import generate_keypair
from spore.wire import MessageType, encode_message, read_message


class TestMessageEncoding:
    def test_encode_decode_roundtrip(self):
        payload = {"key": "value", "number": 42}
        encoded = encode_message("test_type", payload)

        async def _decode():
            reader = asyncio.StreamReader()
            reader.feed_data(encoded)
            return await read_message(reader)

        msg = asyncio.run(_decode())
        assert msg["type"] == "test_type"
        assert msg["payload"]["key"] == "value"
        assert msg["payload"]["number"] == 42

    def test_encode_experiment_record(self, keypair):
        record = make_record(keypair)
        payload = json.loads(record.to_json())
        encoded = encode_message(MessageType.EXPERIMENT, payload)
        assert len(encoded) > 0

    def test_encode_sync_request(self):
        encoded = encode_message(MessageType.SYNC_REQUEST, {"since": 1000})
        assert len(encoded) > 0


class TestGossipServer:
    @pytest.fixture
    def event_loop_policy(self):
        return asyncio.DefaultEventLoopPolicy()

    @pytest.mark.asyncio
    async def test_server_starts_and_stops(self):
        server = GossipServer(host="127.0.0.1", port=0)
        await server.start()
        assert server._server is not None
        await server.stop()

    @pytest.mark.asyncio
    async def test_peer_connection(self):
        server = GossipServer(
            host="127.0.0.1",
            port=17470,
            on_experiment=lambda record: None,
        )
        await server.start()

        client = GossipServer(host="127.0.0.1", port=17471)
        await client.start()

        connected = await client.connect_to_peer("127.0.0.1", 17470)
        assert connected
        await asyncio.sleep(0.1)

        await server.stop()
        await client.stop()

    @pytest.mark.asyncio
    async def test_broadcast_and_receive(self, keypair):
        received = []

        server = GossipServer(
            host="127.0.0.1",
            port=17472,
            on_experiment=lambda record: received.append(record),
        )
        await server.start()

        client = GossipServer(host="127.0.0.1", port=17473)
        await client.start()
        await client.connect_to_peer("127.0.0.1", 17472)
        await asyncio.sleep(0.1)

        record = make_record(keypair, val_bpb=0.95, description="test broadcast")
        await client.broadcast_experiment(record)
        await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0].val_bpb == 0.95
        assert received[0].description == "test broadcast"

        await server.stop()
        await client.stop()

    @pytest.mark.asyncio
    async def test_on_experiment_callback_can_receive_source_addr(self, keypair):
        received = []

        server = GossipServer(host="127.0.0.1", port=17474)
        client = GossipServer(
            host="127.0.0.1",
            port=17475,
            on_experiment=lambda record, addr: received.append((record, addr)),
        )
        await server.start()
        await client.start()
        await client.connect_to_peer("127.0.0.1", 17474)
        await asyncio.sleep(0.1)

        record = make_record(keypair, description="with-source")
        await server.broadcast_experiment(record)
        await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0][0].id == record.id
        assert received[0][1]

        await server.stop()
        await client.stop()

    @pytest.mark.asyncio
    async def test_dedup_prevents_rebroadcast(self, keypair):
        received = []

        server = GossipServer(
            host="127.0.0.1",
            port=17476,
            on_experiment=lambda record: received.append(record),
        )
        await server.start()

        client = GossipServer(host="127.0.0.1", port=17477)
        await client.start()
        await client.connect_to_peer("127.0.0.1", 17476)
        await asyncio.sleep(0.1)

        record = make_record(keypair, description="dedup test")
        await client.broadcast_experiment(record)
        await client.broadcast_experiment(record)
        await asyncio.sleep(0.2)

        assert len(received) == 1

        await server.stop()
        await client.stop()

    @pytest.mark.asyncio
    async def test_invalid_signature_dropped(self, keypair):
        received = []

        server = GossipServer(
            host="127.0.0.1",
            port=17478,
            on_experiment=lambda record: received.append(record),
        )
        await server.start()

        client = GossipServer(host="127.0.0.1", port=17479)
        await client.start()
        await client.connect_to_peer("127.0.0.1", 17478)
        await asyncio.sleep(0.1)

        record = make_record(keypair, description="tampered")
        record.description = "changed after signing"

        msg = encode_message(MessageType.EXPERIMENT, json.loads(record.to_json()))
        for _, (_, writer) in client.peers.items():
            writer.write(msg)
            await writer.drain()

        await asyncio.sleep(0.2)

        assert len(received) == 0

        await server.stop()
        await client.stop()

    @pytest.mark.asyncio
    async def test_sync_request_handler(self, keypair):
        received = []
        sync_records = [
            make_record(keypair, val_bpb=0.95, description="sync exp 1"),
            make_record(keypair, val_bpb=0.90, description="sync exp 2"),
        ]

        server = GossipServer(
            host="127.0.0.1",
            port=17480,
            on_experiment=lambda record: None,
            on_sync_request=lambda since: sync_records,
        )
        await server.start()

        client = GossipServer(
            host="127.0.0.1",
            port=17481,
            on_experiment=lambda record: received.append(record),
        )
        await client.start()
        await client.connect_to_peer("127.0.0.1", 17480)
        await asyncio.sleep(0.1)

        response = await client.request_sync("127.0.0.1:17480", since_timestamp=0)

        assert len(received) == 2
        assert response == {"since": 0, "count": 2}

        await server.stop()
        await client.stop()

    @pytest.mark.asyncio
    async def test_control_sync_request_handler(self, keypair):
        received = []
        sk, node_id = keypair
        events = []

        for index in range(2):
            event = SignedControlEvent(
                type=MessageType.VERIFICATION,
                payload={
                    "event_id": f"verification:{index}",
                    "experiment_id": f"exp-{index}",
                    "verified_node_id": "publisher",
                    "verifier_id": node_id,
                    "is_frontier": False,
                },
                node_id=node_id,
                timestamp=100 + index,
            )
            event.sign(sk)
            events.append(event)

        server = GossipServer(
            host="127.0.0.1",
            port=17482,
            on_control_sync_request=lambda since: [
                event for event in events if event.timestamp > since
            ],
        )
        await server.start()

        client = GossipServer(
            host="127.0.0.1",
            port=17483,
            on_verification=lambda payload: received.append(payload["event_id"]),
        )
        await client.start()
        await client.connect_to_peer("127.0.0.1", 17482)
        await asyncio.sleep(0.1)

        response = await client.request_control_sync(
            "127.0.0.1:17482", since_timestamp=100
        )

        assert received == ["verification:1"]
        assert response == {"since": 100, "count": 1}

        await server.stop()
        await client.stop()

    @pytest.mark.asyncio
    async def test_signed_control_event_is_received(self, keypair):
        received = []
        sk, node_id = keypair

        server = GossipServer(
            host="127.0.0.1",
            port=17482,
            on_challenge=lambda payload: received.append(payload),
        )
        await server.start()

        client = GossipServer(host="127.0.0.1", port=17483)
        await client.start()
        await client.connect_to_peer("127.0.0.1", 17482)
        await asyncio.sleep(0.1)

        event = SignedControlEvent(
            type=MessageType.CHALLENGE,
            payload={
                "event_id": "challenge:exp:node",
                "experiment_id": "exp",
                "challenger_id": node_id,
                "challenger_gpu": "RTX_3060",
            },
            node_id=node_id,
        )
        event.sign(sk)

        msg = encode_message(MessageType.CHALLENGE, event.to_dict())
        for _, (_, writer) in client.peers.items():
            writer.write(msg)
            await writer.drain()

        await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0]["challenger_id"] == node_id

        await server.stop()
        await client.stop()

    @pytest.mark.asyncio
    async def test_signed_control_event_with_actor_mismatch_is_dropped(self):
        received = []
        sk, node_id = generate_keypair()
        _, other_node_id = generate_keypair()

        server = GossipServer(
            host="127.0.0.1",
            port=17484,
            on_challenge=lambda payload: received.append(payload),
        )
        await server.start()

        client = GossipServer(host="127.0.0.1", port=17485)
        await client.start()
        await client.connect_to_peer("127.0.0.1", 17484)
        await asyncio.sleep(0.1)

        event = SignedControlEvent(
            type=MessageType.CHALLENGE,
            payload={
                "event_id": "challenge:exp:other",
                "experiment_id": "exp",
                "challenger_id": other_node_id,
                "challenger_gpu": "RTX_3060",
            },
            node_id=node_id,
        )
        event.sign(sk)

        msg = encode_message(MessageType.CHALLENGE, event.to_dict())
        for _, (_, writer) in client.peers.items():
            writer.write(msg)
            await writer.drain()

        await asyncio.sleep(0.2)

        assert received == []

        await server.stop()
        await client.stop()

    @pytest.mark.asyncio
    async def test_pex_does_not_advertise_inbound_ephemeral_ports(self):
        server_b = GossipServer(host="127.0.0.1", port=17486)
        server_a = GossipServer(host="127.0.0.1", port=17487)
        server_c = GossipServer(host="127.0.0.1", port=17488)
        await server_b.start()
        await server_a.start()
        await server_c.start()

        await server_a.connect_to_peer("127.0.0.1", 17486)
        await server_c.connect_to_peer("127.0.0.1", 17487)
        await asyncio.sleep(0.1)

        await server_c.request_pex("127.0.0.1:17487")
        await asyncio.sleep(0.2)

        assert "127.0.0.1:17486" in server_c.peers
        assert all(
            addr in {"127.0.0.1:17486", "127.0.0.1:17487"} for addr in server_c.peers
        )

        await server_c.stop()
        await server_a.stop()
        await server_b.stop()
