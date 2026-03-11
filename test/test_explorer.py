"""Tests for explorer node-centric APIs."""

from __future__ import annotations

from test.conftest import make_record

from fastapi.testclient import TestClient

from spore.explorer import create_app
from spore.node import NodeConfig, SporeNode
from spore.profile import NodeProfile
from spore.record import Status


def _close_node(node: SporeNode):
    node.graph.close()
    node.profile.close()
    node.control.close()
    node.reputation.close()


def test_nodes_endpoint_returns_rich_node_summaries(tmp_path, keypair, second_keypair):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    sk_a, node_id_a = keypair

    keep_a = make_record(
        keypair,
        val_bpb=0.91,
        status=Status.KEEP,
        description="alpha keep",
        gpu_model="RTX_4090",
    )
    discard_a = make_record(
        keypair,
        parent=keep_a.id,
        depth=1,
        val_bpb=0.97,
        status=Status.DISCARD,
        description="alpha discard",
        gpu_model="RTX_4090",
    )
    keep_b = make_record(
        second_keypair,
        val_bpb=0.89,
        status=Status.KEEP,
        description="beta keep",
        gpu_model="CPU",
    )

    profile_a = NodeProfile(
        node_id=node_id_a,
        display_name="Alpha Node",
        bio="Independent trainer",
        website="https://alpha.example",
        avatar_url="https://alpha.example/avatar.png",
    )
    profile_a.sign(sk_a)

    try:
        node._on_remote_experiment(keep_a)
        node._on_remote_experiment(discard_a)
        node._on_remote_experiment(keep_b)
        node.graph.mark_verified(keep_a.id, True)
        node.update_local_profile(
            display_name="Verifier Node",
            bio="Verifier only",
            avatar_url="https://verifier.example/avatar.png",
        )
        node.reputation.verification_performed(node.node_id)
        node._on_remote_profile(profile_a)

        client = TestClient(create_app(node))
        response = client.get("/api/nodes", params={"sort": "published"})
        assert response.status_code == 200

        payload = response.json()
        by_id = {entry["node_id"]: entry for entry in payload}

        alpha = by_id[node_id_a]
        assert alpha["display_name"] == "Alpha Node"
        assert alpha["avatar_url"] == "https://alpha.example/avatar.png"
        assert alpha["activity"] == "researcher"
        assert alpha["experiment_count"] == 2
        assert alpha["keep_count"] == 1
        assert alpha["discard_count"] == 1
        assert alpha["verified_count"] == 1
        assert alpha["best_experiment"]["id"] == keep_a.id
        assert alpha["latest_experiment"]["id"] == discard_a.id

        verifier = by_id[node.node_id]
        assert verifier["display_name"] == "Verifier Node"
        assert verifier["has_profile"] is True
        assert verifier["activity"] == "verifier"
        assert verifier["experiment_count"] == 0
    finally:
        _close_node(node)


def test_node_detail_and_experiment_filters_work(tmp_path, keypair, second_keypair):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    _, node_id_a = keypair

    keep_a = make_record(
        keypair,
        val_bpb=0.92,
        status=Status.KEEP,
        description="kept change",
    )
    discard_a = make_record(
        keypair,
        parent=keep_a.id,
        depth=1,
        val_bpb=1.01,
        status=Status.DISCARD,
        description="bad followup",
    )
    keep_b = make_record(
        second_keypair,
        val_bpb=0.88,
        status=Status.KEEP,
        description="other frontier",
    )

    try:
        node._on_remote_experiment(keep_a)
        node._on_remote_experiment(discard_a)
        node._on_remote_experiment(keep_b)
        node.graph.mark_verified(keep_a.id, True)

        client = TestClient(create_app(node))

        response = client.get(
            f"/api/node/{node_id_a}",
            params={"status": "keep", "verified_only": "true"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_experiments"] == 1
        assert payload["experiments"][0]["id"] == keep_a.id
        assert payload["experiments"][0]["verified"] is True
        assert payload["filters"]["status"] == "keep"
        assert payload["filters"]["verified_only"] is True

        response = client.get(
            f"/api/node/{node_id_a}/experiment",
            params={"status": "discard"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert [item["id"] for item in payload] == [discard_a.id]
        assert payload[0]["verified"] is False
    finally:
        _close_node(node)


def test_stat_and_node_search_include_richer_explorer_data(
    tmp_path, keypair, second_keypair
):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    sk_a, node_id_a = keypair

    keep_a = make_record(
        keypair,
        val_bpb=0.9,
        status=Status.KEEP,
        description="alpha on h100",
        gpu_model="H100",
    )
    keep_b = make_record(
        second_keypair,
        parent=keep_a.id,
        depth=1,
        val_bpb=0.87,
        status=Status.KEEP,
        description="beta on cpu",
        gpu_model="CPU",
    )
    profile_a = NodeProfile(
        node_id=node_id_a,
        display_name="Alpha Trainer",
        bio="H100 researcher",
    )
    profile_a.sign(sk_a)

    try:
        node._on_remote_experiment(keep_a)
        node._on_remote_experiment(keep_b)
        node.graph.mark_verified(keep_a.id, True)
        node._on_remote_profile(profile_a)

        client = TestClient(create_app(node))

        stat_response = client.get("/api/stat")
        assert stat_response.status_code == 200
        stat_payload = stat_response.json()
        assert stat_payload["node_count"] == 2
        assert stat_payload["profile_count"] == 1
        assert stat_payload["verified_experiment_count"] == 1
        assert stat_payload["frontier_node_count"] == 1

        search_response = client.get("/api/nodes/search", params={"q": "trainer"})
        assert search_response.status_code == 200
        search_payload = search_response.json()
        assert [item["node_id"] for item in search_payload] == [node_id_a]
    finally:
        _close_node(node)


def test_feed_and_hot_task_endpoints_return_derived_activity(
    tmp_path, keypair, second_keypair
):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    keep_a = make_record(
        keypair,
        val_bpb=0.91,
        status=Status.KEEP,
        description="improved optimizer",
    )
    discard_b = make_record(
        second_keypair,
        parent=keep_a.id,
        depth=1,
        val_bpb=1.05,
        status=Status.DISCARD,
        description="bad width increase",
    )

    try:
        node._on_remote_experiment(keep_a)
        node._on_remote_experiment(discard_b)
        client = TestClient(create_app(node))

        feed_response = client.get("/api/feed")
        assert feed_response.status_code == 200
        feed = feed_response.json()
        assert len(feed) == 2
        assert feed[0]["kind"] == "discard"
        assert feed[0]["record"]["id"] == discard_b.id
        assert feed[1]["kind"] in {"keep", "frontier_keep"}
        assert feed[1]["record"]["id"] == keep_a.id

        keeps_response = client.get("/api/keeps/recent")
        assert keeps_response.status_code == 200
        keeps = keeps_response.json()
        assert len(keeps) == 1
        assert keeps[0]["record"]["id"] == keep_a.id

        tasks_response = client.get("/api/tasks/hot")
        assert tasks_response.status_code == 200
        tasks = tasks_response.json()
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == keep_a.id
        assert tasks[0]["recent_experiment_count"] == 2
        assert tasks[0]["participant_count"] == 2

        pulse_response = client.get("/api/pulse", params={"limit": 4})
        assert pulse_response.status_code == 200
        pulse = pulse_response.json()
        assert pulse["experiment_count_recent"] == 2
        assert pulse["keep_count_recent"] == 1
        assert pulse["discard_count_recent"] == 1
        assert pulse["active_node_count_recent"] == 2
        assert pulse["active_task_count_recent"] == 1
        assert pulse["stories"][0]["record"]["id"] == discard_b.id
        assert pulse["hot_tasks"][0]["task_id"] == keep_a.id

        node_activity = client.get(f"/api/node/{keep_a.node_id}/activity")
        assert node_activity.status_code == 200
        activity = node_activity.json()
        assert len(activity) == 1
        assert activity[0]["record"]["id"] == keep_a.id

        task_feed = client.get(f"/api/task/{keep_a.id}/feed")
        assert task_feed.status_code == 200
        task_events = task_feed.json()
        assert len(task_events) == 2
        assert all(item["task_id"] == keep_a.id for item in task_events)
    finally:
        _close_node(node)
