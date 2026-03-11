"""Signed task manifests and task helpers."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field

from nacl.encoding import HexEncoder
from nacl.signing import SigningKey, VerifyKey


@dataclass
class TaskManifest:
    name: str
    description: str
    task_type: str
    artifact_type: str
    metric: str
    goal: str
    base_code_cid: str
    prepare_cid: str
    dataset_cid: str
    time_budget: int
    created_by: str
    timestamp: int = field(default_factory=lambda: int(time.time()))
    signature: str = ""
    task_id: str = ""
    version: int = 1

    def canonical_payload(self) -> dict:
        data = asdict(self)
        data.pop("signature")
        data.pop("task_id")
        return data

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")

    def compute_task_id(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def sign(self, signing_key: SigningKey) -> None:
        self.signature = signing_key.sign(
            self.canonical_bytes(), encoder=HexEncoder
        ).signature.decode("ascii")
        self.task_id = self.compute_task_id()

    def verify_id(self) -> bool:
        return self.task_id == self.compute_task_id()

    def verify_signature(self) -> bool:
        try:
            verify_key = VerifyKey(bytes.fromhex(self.created_by))
            verify_key.verify(self.canonical_bytes(), bytes.fromhex(self.signature))
            return True
        except Exception:
            return False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: str | dict) -> TaskManifest:
        if isinstance(data, str):
            data = json.loads(data)
        return cls(**dict(data))


def legacy_task_name(root_id: str) -> str:
    return f"legacy-{root_id[:8]}"
