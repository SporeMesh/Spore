"""Integration tests — full node-to-node communication."""

import asyncio
from test.conftest import make_record

import pytest

from spore.gossip import GossipServer
from spore.graph import ResearchGraph
from spore.record import Status, generate_keypair


class TestTwoNodeGossip:
    """Test two nodes sharing experiments and converging on the same graph."""

    @pytest.mark.asyncio
    async def test_two_nodes_share_experiments(self):
        """Node A produces experiments, Node B receives them via gossip."""
        kp_a = generate_keypair()
        kp_b = generate_keypair()

        graph_a = ResearchGraph(":memory:")
        graph_b = ResearchGraph(":memory:")

        def on_exp_b(record):
            graph_b.insert(record)

        server_a = GossipServer(host="127.0.0.1", port=18470)
        server_b = GossipServer(host="127.0.0.1", port=18471, on_experiment=on_exp_b)

        await server_a.start()
        await server_b.start()
        await server_b.connect_to_peer("127.0.0.1", 18470)
        await asyncio.sleep(0.1)

        # Node A produces experiments
        genesis = make_record(kp_a, val_bpb=1.0, description="genesis")
        graph_a.insert(genesis)
        await server_a.broadcast_experiment(genesis)
        await asyncio.sleep(0.1)

        child = make_record(
            kp_a, parent=genesis.id, depth=1, val_bpb=0.95, description="improved LR"
        )
        graph_a.insert(child)
        await server_a.broadcast_experiment(child)
        await asyncio.sleep(0.1)

        # Verify both graphs have same experiments
        assert graph_a.count() == 2
        assert graph_b.count() == 2

        # Frontiers should match
        frontier_a = graph_a.frontier()
        frontier_b = graph_b.frontier()
        assert len(frontier_a) == 1
        assert len(frontier_b) == 1
        assert frontier_a[0].id == frontier_b[0].id
        assert frontier_a[0].val_bpb == 0.95

        await server_a.stop()
        await server_b.stop()
        graph_a.close()
        graph_b.close()

    @pytest.mark.asyncio
    async def test_bidirectional_sharing(self):
        """Both nodes produce experiments, both receive each other's."""
        kp_a = generate_keypair()
        kp_b = generate_keypair()

        graph_a = ResearchGraph(":memory:")
        graph_b = ResearchGraph(":memory:")

        def on_exp_a(record):
            graph_a.insert(record)

        def on_exp_b(record):
            graph_b.insert(record)

        server_a = GossipServer(host="127.0.0.1", port=18472, on_experiment=on_exp_a)
        server_b = GossipServer(host="127.0.0.1", port=18473, on_experiment=on_exp_b)

        await server_a.start()
        await server_b.start()
        await server_b.connect_to_peer("127.0.0.1", 18472)
        await asyncio.sleep(0.1)

        # Node A produces genesis
        genesis = make_record(kp_a, val_bpb=1.0, description="genesis from A")
        graph_a.insert(genesis)
        await server_a.broadcast_experiment(genesis)
        await asyncio.sleep(0.1)

        # Node B builds on genesis
        child_b = make_record(
            kp_b,
            parent=genesis.id,
            depth=1,
            val_bpb=0.93,
            description="improvement from B",
        )
        graph_b.insert(child_b)
        await server_b.broadcast_experiment(child_b)
        await asyncio.sleep(0.1)

        # Both graphs should have both experiments
        assert graph_a.count() == 2
        assert graph_b.count() == 2

        # Best experiment should be from Node B
        best_a = graph_a.best()
        best_b = graph_b.best()
        assert best_a.val_bpb == 0.93
        assert best_b.val_bpb == 0.93

        await server_a.stop()
        await server_b.stop()
        graph_a.close()
        graph_b.close()

    @pytest.mark.asyncio
    async def test_three_node_fan_out(self):
        """Node A sends to B, B re-gossips to C."""
        kp = generate_keypair()

        graph_c = ResearchGraph(":memory:")

        def on_exp_c(record):
            graph_c.insert(record)

        server_a = GossipServer(host="127.0.0.1", port=18474)
        server_b = GossipServer(
            host="127.0.0.1",
            port=18475,
            on_experiment=lambda r: None,  # B just forwards
        )
        server_c = GossipServer(host="127.0.0.1", port=18476, on_experiment=on_exp_c)

        await server_a.start()
        await server_b.start()
        await server_c.start()

        # B connects to A, C connects to B
        await server_b.connect_to_peer("127.0.0.1", 18474)
        await server_c.connect_to_peer("127.0.0.1", 18475)
        await asyncio.sleep(0.1)

        # A broadcasts
        record = make_record(kp, val_bpb=0.95, description="from A")
        await server_a.broadcast_experiment(record)
        await asyncio.sleep(0.3)

        # C should receive via B's re-gossip
        assert graph_c.count() == 1
        assert graph_c.get(record.id) is not None

        await server_a.stop()
        await server_b.stop()
        await server_c.stop()
        graph_c.close()

    @pytest.mark.asyncio
    async def test_control_message_fan_out(self):
        """Challenge/verification/dispute events should re-gossip beyond one hop."""
        seen_by_c: list[tuple[str, str]] = []

        server_a = GossipServer(host="127.0.0.1", port=18479)
        server_b = GossipServer(
            host="127.0.0.1",
            port=18480,
            on_challenge=lambda payload: None,
            on_challenge_response=lambda payload: None,
            on_dispute=lambda payload: None,
            on_verification=lambda payload: None,
        )
        server_c = GossipServer(
            host="127.0.0.1",
            port=18481,
            on_challenge=lambda payload: seen_by_c.append(
                ("challenge", payload["event_id"])
            ),
            on_challenge_response=lambda payload: seen_by_c.append(
                ("challenge_response", payload["event_id"])
            ),
            on_dispute=lambda payload: seen_by_c.append(
                ("dispute", payload["event_id"])
            ),
            on_verification=lambda payload: seen_by_c.append(
                ("verification", payload["event_id"])
            ),
        )

        await server_a.start()
        await server_b.start()
        await server_c.start()

        await server_b.connect_to_peer("127.0.0.1", 18479)
        await server_c.connect_to_peer("127.0.0.1", 18480)
        await asyncio.sleep(0.1)

        await server_a.broadcast_challenge(
            {"event_id": "challenge:test", "experiment_id": "exp", "challenger_id": "a"}
        )
        await server_a.broadcast_challenge_response(
            {
                "event_id": "challenge_response:test",
                "experiment_id": "exp",
                "challenger_id": "a",
                "verifier_id": "b",
                "verifier_bpb": 1.0,
                "verifier_gpu": "RTX_3060",
            }
        )
        await server_a.broadcast_verification(
            {
                "event_id": "verification:test",
                "experiment_id": "exp",
                "verified_node_id": "pub",
                "verifier_id": "b",
                "is_frontier": False,
            }
        )
        await server_a.broadcast_dispute(
            {
                "event_id": "dispute:test",
                "experiment_id": "exp",
                "challenger_id": "a",
                "original_node_id": "pub",
                "outcome": "upheld",
                "ground_truth_bpb": 1.0,
            }
        )
        await asyncio.sleep(0.3)

        assert ("challenge", "challenge:test") in seen_by_c
        assert ("challenge_response", "challenge_response:test") in seen_by_c
        assert ("verification", "verification:test") in seen_by_c
        assert ("dispute", "dispute:test") in seen_by_c

        await server_a.stop()
        await server_b.stop()
        await server_c.stop()


class TestFullWorkflow:
    """Test the complete workflow: create experiments, gossip, verify frontier."""

    @pytest.mark.asyncio
    async def test_research_graph_convergence(self):
        """Two nodes independently explore, share, and converge on the best."""
        kp_a = generate_keypair()
        kp_b = generate_keypair()

        graph_a = ResearchGraph(":memory:")
        graph_b = ResearchGraph(":memory:")

        def on_exp_a(record):
            graph_a.insert(record)

        def on_exp_b(record):
            graph_b.insert(record)

        server_a = GossipServer(host="127.0.0.1", port=18477, on_experiment=on_exp_a)
        server_b = GossipServer(host="127.0.0.1", port=18478, on_experiment=on_exp_b)

        await server_a.start()
        await server_b.start()
        await server_b.connect_to_peer("127.0.0.1", 18477)
        await asyncio.sleep(0.1)

        # Shared genesis
        genesis = make_record(kp_a, val_bpb=1.0, description="baseline")
        graph_a.insert(genesis)
        await server_a.broadcast_experiment(genesis)
        await asyncio.sleep(0.1)

        # Node A explores: LR change (keep)
        a1 = make_record(
            kp_a, parent=genesis.id, depth=1, val_bpb=0.95, description="A: double LR"
        )
        graph_a.insert(a1)
        await server_a.broadcast_experiment(a1)

        # Node B explores: architecture change (keep, better)
        b1 = make_record(
            kp_b, parent=genesis.id, depth=1, val_bpb=0.92, description="B: wider model"
        )
        graph_b.insert(b1)
        await server_b.broadcast_experiment(b1)

        # Node A explores: bad idea (discard)
        a2 = make_record(
            kp_a,
            parent=a1.id,
            depth=2,
            val_bpb=1.05,
            status=Status.DISCARD,
            description="A: remove attention",
        )
        graph_a.insert(a2)
        await server_a.broadcast_experiment(a2)

        await asyncio.sleep(0.3)

        # Both graphs should have all 4 experiments
        assert graph_a.count() == 4
        assert graph_b.count() == 4

        # Best should be B's wider model
        assert graph_a.best().val_bpb == 0.92
        assert graph_b.best().val_bpb == 0.92

        # Frontier should have 2 experiments (A's keep + B's keep)
        frontier_a = graph_a.frontier()
        assert len(frontier_a) == 2

        # ASCII tree should show the full graph
        tree = graph_a.ascii_tree()
        assert "baseline" in tree
        assert "double LR" in tree
        assert "wider model" in tree

        await server_a.stop()
        await server_b.stop()
        graph_a.close()
        graph_b.close()
