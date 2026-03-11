"""ExperimentRecord — the atomic unit of the Spore protocol.

Every experiment produces an immutable, content-addressed record containing
the code diff, results, hardware info, and cryptographic signature.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum

from nacl.encoding import HexEncoder
from nacl.signing import SigningKey, VerifyKey


class Status(str, Enum):
    KEEP = "keep"
    DISCARD = "discard"
    CRASH = "crash"


@dataclass
class ExperimentRecord:
    # Lineage
    parent: str | None  # Parent experiment CID (None for genesis)
    depth: int  # Distance from genesis (0 = baseline)

    # The experiment
    code_cid: str  # SHA-256 of full train.py snapshot
    diff: str  # Unified diff from parent's train.py

    # Configuration
    dataset_cid: str  # Hash of dataset used
    prepare_cid: str  # Hash of prepare.py
    time_budget: int  # Training time in seconds

    # Results
    val_bpb: float  # Validation bits per byte. Lower = better.
    peak_vram_mb: float  # Peak GPU memory in MB
    num_steps: int  # Training steps completed
    num_params: int  # Model parameter count
    status: Status  # keep / discard / crash

    # Provenance
    description: str  # What was tried
    hypothesis: str  # Why the agent thought this would work
    agent_model: str  # Which LLM proposed this

    # Hardware
    gpu_model: str  # e.g. "RTX_4090", "H100-SXM5-80GB"
    cuda_version: str
    torch_version: str

    # Node identity
    node_id: str  # Ed25519 public key (hex)
    task_id: str = ""  # Task namespace (signed for v2+ records)
    timestamp: int = field(default_factory=lambda: int(time.time()))

    # Computed after creation
    signature: str = ""  # Ed25519 signature (hex)
    id: str = ""  # CID = SHA-256 of canonical payload

    # Protocol
    version: int = 1

    def canonical_payload(self) -> dict:
        """Return the dict used for CID computation and signing.

        Excludes `id` and `signature` (they depend on the payload).
        """
        d = asdict(self)
        d.pop("id")
        d.pop("signature")
        if self.version < 2:
            d.pop("task_id", None)
        if isinstance(d.get("status"), Status):
            d["status"] = d["status"].value
        return d

    def canonical_bytes(self) -> bytes:
        """Deterministic JSON bytes for hashing and signing."""
        return json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")

    def compute_cid(self) -> str:
        """SHA-256 of canonical JSON payload."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def sign(self, signing_key: SigningKey) -> None:
        """Sign the record and compute CID."""
        self.signature = signing_key.sign(
            self.canonical_bytes(), encoder=HexEncoder
        ).signature.decode("ascii")
        self.id = self.compute_cid()

    def verify_signature(self) -> bool:
        """Verify the record's signature against node_id."""
        try:
            verify_key = VerifyKey(bytes.fromhex(self.node_id))
            verify_key.verify(
                self.canonical_bytes(),
                bytes.fromhex(self.signature),
            )
            return True
        except Exception:
            return False

    def verify_cid(self) -> bool:
        """Verify the CID matches the payload."""
        return self.id == self.compute_cid()

    def to_json(self) -> str:
        d = asdict(self)
        if isinstance(d.get("status"), Status):
            d["status"] = d["status"].value
        return json.dumps(d, sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, data: str | dict) -> ExperimentRecord:
        if isinstance(data, str):
            d = json.loads(data)
        else:
            d = dict(data)
        if "status" in d:
            d["status"] = Status(d["status"])
        return cls(**d)


def generate_keypair() -> tuple[SigningKey, str]:
    """Generate a new Ed25519 keypair. Returns (signing_key, public_key_hex)."""
    sk = SigningKey.generate()
    pk_hex = sk.verify_key.encode(encoder=HexEncoder).decode("ascii")
    return sk, pk_hex


def compute_file_cid(path: str) -> str:
    """Compute SHA-256 CID of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
