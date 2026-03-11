"""Spore node orchestration."""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import tomllib
from nacl.encoding import HexEncoder
from nacl.signing import SigningKey

from .artifact_sync import ArtifactSync
from .challenge import ChallengeCoordinator
from .control import SignedControlEvent
from .control_store import ControlStore
from .gossip import GossipServer
from .gpu import normalize_gpu_model
from .graph import ResearchGraph
from .peer_sync import PeerSyncLoop
from .profile import NodeProfile, NodeProfileStore
from .record import ExperimentRecord, generate_keypair
from .store import ArtifactStore
from .task import TaskManifest
from .task_store import TaskStore
from .training_runtime import TrainingRuntime
from .verify import ReputationStore, Verifier

log = logging.getLogger(__name__)

SPORE_DIR = Path("~/.spore").expanduser()
DEFAULT_PORT = 7470
BOOTSTRAP_PEER = ["peer.sporemesh.com:7470"]
KNOWN_PEER_FILE = "known_peer"


@dataclass
class NodeConfig:
    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    peer: list[str] = field(default_factory=list)
    task_id: str = ""
    auto_update: bool = True
    update_interval_sec: int = 21600
    update_manifest_url: str = (
        "https://raw.githubusercontent.com/SporeMesh/Spore/main/release-manifest.json"
    )
    data_dir: str = str(SPORE_DIR)
    enable_cache: bool = False

    @classmethod
    def load(cls, path: str | Path | None = None) -> NodeConfig:
        path = Path(path or (SPORE_DIR / "config.toml"))
        if not path.exists():
            return cls()
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
        return cls(
            host=data.get("host", "0.0.0.0"),
            port=data.get("port", DEFAULT_PORT),
            peer=data.get("peer", []),
            task_id=data.get("task_id", ""),
            auto_update=data.get("auto_update", True),
            update_interval_sec=data.get("update_interval_sec", 21600),
            update_manifest_url=data.get(
                "update_manifest_url",
                "https://raw.githubusercontent.com/SporeMesh/Spore/main/release-manifest.json",
            ),
            data_dir=data.get("data_dir", str(SPORE_DIR)),
            enable_cache=data.get("enable_cache", False),
        )

    def save(self, path: str | Path | None = None):
        target = Path(path or (Path(self.data_dir) / "config.toml"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "\n".join(
                [
                    f'host = "{self.host}"',
                    f"port = {self.port}",
                    f"peer = {self.peer!r}",
                    f'task_id = "{self.task_id}"',
                    f"auto_update = {str(self.auto_update).lower()}",
                    f"update_interval_sec = {self.update_interval_sec}",
                    f'update_manifest_url = "{self.update_manifest_url}"',
                    f'data_dir = "{self.data_dir}"',
                    f"enable_cache = {str(self.enable_cache).lower()}",
                ]
            )
            + "\n"
        )


class SporeNode:
    def __init__(self, config: NodeConfig | None = None):
        self.config = config or NodeConfig.load()
        self.data_dir = Path(self.config.data_dir).expanduser()
        for name in ("db", "artifact", "identity"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)

        self.signing_key, self.node_id = self._load_identity()
        self.graph = ResearchGraph(self.data_dir / "db" / "graph.sqlite")
        self.store = ArtifactStore(self.data_dir / "artifact")
        self.profile = NodeProfileStore(self.data_dir / "db" / "profile.sqlite")
        self.control = ControlStore(self.data_dir / "db" / "control.sqlite")
        self.task = TaskStore(self.data_dir / "db" / "task.sqlite")
        self.reputation = ReputationStore(self.data_dir / "db" / "reputation.sqlite")
        self.training = TrainingRuntime()
        self.artifact = ArtifactSync()
        self.peer_sync = PeerSyncLoop()
        self.workspace: Path | None = None

        self._backfill_tasks()
        self.reputation.backfill_published(self.graph.all_records())
        self.active_task_id = self.config.task_id or self._auto_select_task()

        self.verifier = Verifier(self.reputation)
        self.challenger = ChallengeCoordinator(
            self.verifier,
            self.node_id,
            gpu_model=self._detect_gpu(),
        )
        self.challenger.set_node(self)

        self.gossip = GossipServer(
            host=self.config.host,
            port=self.config.port,
            on_experiment=self._on_remote_experiment,
            on_task=self._on_remote_task,
            on_sync_request=self._on_sync_request,
            on_control_sync_request=self._on_control_sync_request,
            on_task_sync_request=self._on_task_sync_request,
            on_new_peer=self._save_peer,
            on_control_event=self._on_remote_control_event,
            on_challenge=self.challenger.on_challenge,
            on_challenge_response=self.challenger.on_challenge_response,
            on_dispute=self.challenger.on_dispute,
            on_verification=self.challenger.on_verification,
            on_profile=self._on_remote_profile,
            on_code_request=self._on_code_request,
        )
        self._listeners: list[Callable[[ExperimentRecord], None]] = []

    def add_listener(self, callback: Callable[[ExperimentRecord], None]):
        self._listeners.append(callback)

    def get_profile(self, node_id: str) -> NodeProfile | None:
        return self.profile.get(node_id)

    def get_task(self, task_id: str) -> dict | None:
        return self.task.get(task_id)

    def all_tasks(self) -> list[dict]:
        return self.task.all()

    def set_active_task(self, task_id: str):
        self.active_task_id = task_id
        self.config.task_id = task_id
        self.config.save(self.data_dir / "config.toml")

    def create_task(
        self,
        *,
        name: str,
        description: str,
        task_type: str,
        artifact_type: str,
        metric: str,
        goal: str,
        base_code_cid: str,
        prepare_cid: str,
        dataset_cid: str,
        time_budget: int,
    ) -> TaskManifest:
        manifest = TaskManifest(
            name=name,
            description=description,
            task_type=task_type,
            artifact_type=artifact_type,
            metric=metric,
            goal=goal,
            base_code_cid=base_code_cid,
            prepare_cid=prepare_cid,
            dataset_cid=dataset_cid,
            time_budget=time_budget,
            created_by=self.node_id,
        )
        manifest.sign(self.signing_key)
        self.task.upsert_manifest(manifest)
        self.set_active_task(manifest.task_id)
        return manifest

    async def publish_task(self, manifest: TaskManifest):
        self.task.upsert_manifest(manifest)
        await self.gossip.broadcast_task(manifest)

    async def publish_experiment(
        self, record: ExperimentRecord, code: str | None = None
    ):
        record.node_id = self.node_id
        record.task_id = self._normalize_task_id(record, local_publish=True)
        record.version = max(record.version, 2) if record.task_id else record.version
        record.sign(self.signing_key)
        if not self._accept_lineage(record, local_publish=True):
            raise ValueError("task lineage rejected")
        self.graph.insert(record)
        self._register_task_for_record(record)
        self.reputation.record_published(record.node_id, record)
        if code:
            self.store.put(code.encode("utf-8"))
        await self.gossip.broadcast_experiment(record)
        log.info(
            "Published experiment %s task=%s val_bpb=%.6f %s",
            record.id[:8],
            record.task_id[:8],
            record.val_bpb,
            record.status.value,
        )
        self._notify_listeners(record)

    async def publish_profile(self, profile: NodeProfile | None = None):
        profile = profile or self.profile.get(self.node_id)
        if profile is None:
            return
        self.profile.upsert(profile)
        await self.gossip.broadcast_profile(profile)

    def update_local_profile(
        self,
        *,
        display_name: str,
        bio: str = "",
        website: str = "",
        avatar_url: str = "",
        donation_address: str = "",
    ) -> NodeProfile:
        profile = NodeProfile(
            node_id=self.node_id,
            display_name=display_name.strip(),
            bio=bio.strip(),
            website=website.strip(),
            avatar_url=avatar_url.strip(),
            donation_address=donation_address.strip(),
        )
        profile.sign(self.signing_key)
        self.profile.upsert(profile)
        return profile

    def make_control_event(self, msg_type: str, payload: dict) -> dict:
        event = SignedControlEvent(
            type=msg_type, payload=dict(payload), node_id=self.node_id
        )
        event.sign(self.signing_key)
        self.control.store(event)
        return event.to_dict()

    async def fetch_code(self, code_cid: str) -> bytes | None:
        return await self.artifact.fetch(self, code_cid)

    async def start(self, *, skip_peer: bool = False):
        await self.gossip.start()
        if not skip_peer:
            known_peers = self._load_known_peer()
            peers = list(
                dict.fromkeys(
                    self.config.peer
                    + known_peers
                    + (BOOTSTRAP_PEER if not (self.config.peer or known_peers) else [])
                )
            )
            for peer_addr in peers:
                host, _, port_str = peer_addr.partition(":")
                if not port_str or self._should_skip_peer(peer_addr):
                    continue
                if await self.gossip.connect_to_peer(host, int(port_str)):
                    self._save_peer(peer_addr)
                    await self.gossip.request_pex(peer_addr)
                    await self.gossip.request_sync(peer_addr)
                    await self.gossip.request_control_sync(
                        peer_addr, since_timestamp=self.control.latest_timestamp()
                    )
                    await self.gossip.request_task_sync(
                        peer_addr, since_timestamp=self.task.latest_timestamp()
                    )
                else:
                    self._drop_peer(peer_addr)
            self.peer_sync.start(self)
        for manifest in self.task.manifests():
            await self.gossip.broadcast_task(manifest)
        if self.profile.get(self.node_id) is not None:
            await self.publish_profile()
        self.active_task_id = self.config.task_id or self._auto_select_task()

    async def stop(self):
        await self.peer_sync.stop()
        await self.gossip.stop()
        self.graph.close()
        self.profile.close()
        self.control.close()
        self.task.close()
        self.reputation.close()

    async def run(self):
        await self.start()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    def _on_remote_experiment(
        self, record: ExperimentRecord, source_addr: str | None = None
    ):
        record.task_id = self._normalize_task_id(record)
        if not self._accept_lineage(record):
            log.warning("Rejected experiment %s: invalid task lineage", record.id[:8])
            return
        inserted = self.graph.insert(record)
        if not inserted:
            return
        self._register_task_for_record(record)
        self.reputation.record_published(record.node_id, record)
        if source_addr and self.store.get(record.code_cid) is None:
            self.artifact.prefetch(self, record.code_cid, preferred_peer=source_addr)
        if self.workspace:
            self.challenger.on_experiment_received(record)
        self._notify_listeners(record)

    def _on_sync_request(self, since_timestamp: int) -> list[ExperimentRecord]:
        return [
            record
            for record in self.graph.all_records()
            if record.timestamp >= since_timestamp
        ]

    def _on_control_sync_request(
        self, since_timestamp: int
    ) -> list[SignedControlEvent]:
        return self.control.list_since(since_timestamp)

    def _on_remote_control_event(self, event: SignedControlEvent):
        self.control.store(event)

    def _on_remote_profile(self, profile: NodeProfile):
        self.profile.upsert(profile)

    def _on_remote_task(self, manifest: TaskManifest):
        self.task.upsert_manifest(manifest)
        if not self.active_task_id:
            self.active_task_id = manifest.task_id

    def _on_task_sync_request(self, since_timestamp: int) -> list[TaskManifest]:
        return self.task.list_since(since_timestamp)

    def _on_code_request(self, code_cid: str) -> bytes | None:
        return self.store.get(code_cid)

    def _normalize_task_id(
        self, record: ExperimentRecord, *, local_publish: bool = False
    ) -> str:
        if record.task_id:
            return record.task_id
        if record.parent:
            parent = self.graph.get(record.parent)
            if parent is not None and parent.task_id:
                return parent.task_id
        if record.parent is None:
            if local_publish:
                return self.active_task_id or record.id
            return record.id
        return self.active_task_id if local_publish else ""

    def _accept_lineage(
        self, record: ExperimentRecord, *, local_publish: bool = False
    ) -> bool:
        if not record.task_id:
            return False
        if record.parent:
            parent = self.graph.get(record.parent)
            return parent is None or parent.task_id == record.task_id
        roots = self.graph.root_ids_by_task(record.task_id)
        if roots:
            return record.id in roots
        existing = self.graph.by_task(record.task_id)
        return not existing if local_publish else len(existing) == 0

    def _register_task_for_record(self, record: ExperimentRecord):
        if record.parent is None and record.task_id:
            self.task.ensure_legacy_task(record.task_id, record)

    def _backfill_tasks(self):
        task_by_record = self.graph.backfill_task_ids()
        for record in self.graph.all_records():
            record.task_id = task_by_record.get(record.id, record.task_id)
            if record.parent is None and record.task_id:
                self.task.ensure_legacy_task(record.task_id, record)

    def _auto_select_task(self) -> str:
        task_ids = self.graph.all_task_ids()
        if not task_ids:
            return ""
        scored = []
        for task_id in task_ids:
            recent = self.graph.recent_by_task(task_id, limit=25)
            latest = max((record.timestamp for record in recent), default=0)
            keep_count = sum(
                1
                for record in recent
                if (
                    record.status.value
                    if hasattr(record.status, "value")
                    else record.status
                )
                == "keep"
            )
            scored.append((len(recent), keep_count, latest, task_id))
        scored.sort(reverse=True)
        return scored[0][3]

    def _notify_listeners(self, record: ExperimentRecord):
        for callback in self._listeners:
            try:
                callback(record)
            except Exception:
                log.exception("Listener callback failed")

    def _load_known_peer(self) -> list[str]:
        path = self.data_dir / KNOWN_PEER_FILE
        if not path.exists():
            return []
        return [
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and line.strip() not in BOOTSTRAP_PEER
        ]

    def _save_peer(self, addr: str):
        if addr in BOOTSTRAP_PEER:
            return
        path = self.data_dir / KNOWN_PEER_FILE
        existing = set(self._load_known_peer())
        if addr not in existing:
            with open(path, "a") as handle:
                handle.write(addr + "\n")

    def _drop_peer(self, addr: str):
        path = self.data_dir / KNOWN_PEER_FILE
        if path.exists():
            peers = [peer for peer in self._load_known_peer() if peer != addr]
            path.write_text("\n".join(peers) + ("\n" if peers else ""))
        if addr in self.config.peer:
            self.config.peer = [peer for peer in self.config.peer if peer != addr]
            self.config.save(self.data_dir / "config.toml")

    def _should_skip_peer(self, peer_addr: str) -> bool:
        host, _, port_str = peer_addr.partition(":")
        if not port_str:
            return True
        try:
            port = int(port_str)
        except ValueError:
            return True
        if port != self.config.port:
            return False
        if host in {"127.0.0.1", "localhost", self.config.host}:
            return True
        local_hosts = {"127.0.0.1", "localhost", self.config.host}
        try:
            local_hosts.update(
                info[4][0]
                for info in socket.getaddrinfo(socket.gethostname(), None)
                if info[4]
            )
        except socket.gaierror:
            pass
        try:
            target_hosts = {
                info[4][0]
                for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                if info[4]
            }
        except socket.gaierror:
            return False
        return bool(target_hosts & local_hosts)

    @staticmethod
    def _detect_gpu() -> str:
        try:
            import torch

            if torch.cuda.is_available():
                return normalize_gpu_model(torch.cuda.get_device_name(0))
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "APPLE_MPS"
        except ImportError:
            pass
        return "CPU"

    def _load_identity(self) -> tuple[SigningKey, str]:
        key_path = self.data_dir / "identity" / "private_key"
        if key_path.exists():
            key = SigningKey(bytes.fromhex(key_path.read_text().strip()))
            node_id = key.verify_key.encode(encoder=HexEncoder).decode("ascii")
            return key, node_id
        key, node_id = generate_keypair()
        key_path.write_text(key.encode(encoder=HexEncoder).decode("ascii"))
        (self.data_dir / "identity" / "node_id").write_text(node_id)
        return key, node_id
