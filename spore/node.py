"""Spore node — ties together graph, storage, gossip, and the experiment loop.

A node:
1. Maintains a local research graph (SQLite DAG)
2. Runs a gossip server to exchange experiments with peers
3. Optionally runs an experiment loop (wrapper around autoresearch)
4. Stores artifacts in content-addressed storage
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import tomllib
from nacl.encoding import HexEncoder
from nacl.signing import SigningKey

from .challenge import ChallengeCoordinator
from .gossip import GossipServer
from .graph import ResearchGraph
from .record import ExperimentRecord, generate_keypair
from .store import ArtifactStore
from .verify import ReputationStore, Verifier

log = logging.getLogger(__name__)

SPORE_DIR = Path("~/.spore").expanduser()
DEFAULT_PORT = 7470
BOOTSTRAP_PEER = ["188.36.196.221:42208"]
KNOWN_PEER_FILE = "known_peer"


@dataclass
class NodeConfig:
    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    peer: list[str] = field(default_factory=list)  # ["host:port", ...]
    data_dir: str = str(SPORE_DIR)

    @classmethod
    def load(cls, path: str | Path | None = None) -> NodeConfig:
        if path is None:
            path = SPORE_DIR / "config.toml"
        path = Path(path)
        if not path.exists():
            return cls()
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return cls(
            host=data.get("host", "0.0.0.0"),
            port=data.get("port", DEFAULT_PORT),
            peer=data.get("peer", []),
            data_dir=data.get("data_dir", str(SPORE_DIR)),
        )

    def save(self, path: str | Path | None = None):
        if path is None:
            path = Path(self.data_dir) / "config.toml"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f'host = "{self.host}"',
            f"port = {self.port}",
            f'data_dir = "{self.data_dir}"',
            f"peer = {self.peer!r}",
        ]
        path.write_text("\n".join(lines) + "\n")


class SporeNode:
    def __init__(self, config: NodeConfig | None = None):
        self.config = config or NodeConfig.load()
        self.data_dir = Path(self.config.data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "db").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "artifact").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "identity").mkdir(parents=True, exist_ok=True)

        # Load or generate identity
        self.signing_key, self.node_id = self._load_identity()

        # Core components
        self.graph = ResearchGraph(self.data_dir / "db" / "graph.sqlite")
        self.store = ArtifactStore(self.data_dir / "artifact")
        self.reputation = ReputationStore(self.data_dir / "db" / "reputation.sqlite")
        self.reputation.backfill_published(self.graph.all_records())
        # Verification
        self.verifier = Verifier(self.reputation)
        self.challenger = ChallengeCoordinator(
            self.verifier,
            self.node_id,
            gpu_model=self._detect_gpu(),
        )
        self.challenger.set_node(self)
        self.workspace: Path | None = None  # Set by experiment loop if training

        self.gossip = GossipServer(
            host=self.config.host,
            port=self.config.port,
            on_experiment=self._on_remote_experiment,
            on_sync_request=self._on_sync_request,
            on_new_peer=self._save_peer,
            on_challenge=self.challenger.on_challenge,
            on_challenge_response=self.challenger.on_challenge_response,
            on_dispute=self.challenger.on_dispute,
            on_code_request=self._on_code_request,
        )
        self._listener: list[Callable[[ExperimentRecord], None]] = []

    def add_listener(self, callback: Callable[[ExperimentRecord], None]):
        """Register a callback for new experiment events."""
        self._listener.append(callback)

    @staticmethod
    def _detect_gpu() -> str:
        """Detect GPU model for verification matching."""
        try:
            import torch

            if torch.cuda.is_available():
                return torch.cuda.get_device_name(0).replace(" ", "_")
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "Apple_MPS"
        except ImportError:
            pass
        return "CPU"

    def _load_identity(self) -> tuple[SigningKey, str]:
        """Load existing keypair or generate a new one."""
        key_path = self.data_dir / "identity" / "private_key"
        if key_path.exists():
            sk_hex = key_path.read_text().strip()
            sk = SigningKey(bytes.fromhex(sk_hex))
            pk_hex = sk.verify_key.encode(encoder=HexEncoder).decode("ascii")
            return sk, pk_hex

        sk, pk_hex = generate_keypair()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(sk.encode(encoder=HexEncoder).decode("ascii"))
        # Store public key separately for easy access
        (self.data_dir / "identity" / "node_id").write_text(pk_hex)
        return sk, pk_hex

    def _on_remote_experiment(self, record: ExperimentRecord):
        """Called when a remote experiment arrives via gossip."""
        inserted = self.graph.insert(record)
        if inserted:
            self.reputation.record_published(record.node_id, record)
            log.info(
                "Received experiment %s (val_bpb=%.6f, %s) from %s",
                record.id[:8],
                record.val_bpb,
                record.status.value,
                record.node_id[:8],
            )
            # Spot-check if we have a workspace
            if self.workspace:
                self.challenger.on_experiment_received(record)

            for cb in self._listener:
                try:
                    cb(record)
                except Exception:
                    log.exception("Listener callback failed")

    def _on_sync_request(self, since_timestamp: int) -> list[ExperimentRecord]:
        """Called when a peer requests sync. Returns records after timestamp."""
        all_records = self.graph.all_records()
        return [r for r in all_records if r.timestamp >= since_timestamp]

    async def publish_experiment(
        self, record: ExperimentRecord, code: str | None = None
    ):
        """Sign, store, and broadcast an experiment."""
        record.node_id = self.node_id
        record.sign(self.signing_key)
        self.graph.insert(record)
        self.reputation.record_published(record.node_id, record)
        # Store full code snapshot for verification
        if code:
            self.store.put(code.encode("utf-8"))
        await self.gossip.broadcast_experiment(record)
        log.info(
            "Published experiment %s (val_bpb=%.6f, %s)",
            record.id[:8],
            record.val_bpb,
            record.status.value,
        )
        for cb in self._listener:
            try:
                cb(record)
            except Exception:
                log.exception("Listener callback failed")

    def _on_code_request(self, code_cid: str) -> bytes | None:
        """Called when a peer requests code by CID."""
        return self.store.get(code_cid)

    async def fetch_code(self, code_cid: str) -> bytes | None:
        """Try to fetch code by CID from any connected peer."""
        import hashlib

        for addr in list(self.gossip.peers.keys()):
            code_bytes = await self.gossip.request_code(addr, code_cid, timeout=15.0)
            if code_bytes is not None:
                actual_cid = hashlib.sha256(code_bytes).hexdigest()
                if actual_cid == code_cid:
                    self.store.put(code_bytes)
                    return code_bytes
                log.warning(
                    "Code CID mismatch from %s: expected %s, got %s",
                    addr,
                    code_cid[:8],
                    actual_cid[:8],
                )
        return None

    async def start(self, *, skip_peer: bool = False):
        """Start the gossip server and connect to peers."""
        (self.data_dir / "db").mkdir(parents=True, exist_ok=True)
        await self.gossip.start()

        if skip_peer:
            return

        # Build peer list: configured + persisted + bootstrap (deduplicated)
        all_peer = list(
            dict.fromkeys(
                self.config.peer
                + self._load_known_peer()
                + (BOOTSTRAP_PEER if not self.config.peer else [])
            )
        )

        for peer_addr in all_peer:
            parts = peer_addr.split(":")
            if len(parts) == 2:
                host, port = parts[0], int(parts[1])
                connected = await self.gossip.connect_to_peer(host, port)
                if connected:
                    self._save_peer(peer_addr)
                    await self.gossip.request_sync(peer_addr)
                    await self.gossip.request_pex(peer_addr)

    async def stop(self):
        await self.gossip.stop()
        self.graph.close()
        self.reputation.close()

    def _load_known_peer(self) -> list[str]:
        """Load previously-seen peers from disk."""
        path = self.data_dir / KNOWN_PEER_FILE
        if not path.exists():
            return []
        return [l.strip() for l in path.read_text().splitlines() if l.strip()]

    def _save_peer(self, addr: str):
        """Append a peer to the known peers file (dedup)."""
        path = self.data_dir / KNOWN_PEER_FILE
        existing = set(self._load_known_peer())
        if addr not in existing:
            with open(path, "a") as f:
                f.write(addr + "\n")

    async def run(self):
        """Run the node (start + wait forever)."""
        await self.start()
        try:
            await asyncio.Event().wait()  # Run until cancelled
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
