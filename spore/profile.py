"""Signed node profile metadata and local storage."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from nacl.encoding import HexEncoder
from nacl.signing import SigningKey, VerifyKey

SCHEMA = """
CREATE TABLE IF NOT EXISTS node_profile (
    node_id TEXT PRIMARY KEY,
    id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    bio TEXT NOT NULL,
    website TEXT NOT NULL,
    avatar_url TEXT NOT NULL,
    donation_address TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    signature TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_profile_timestamp ON node_profile(timestamp);
"""


@dataclass
class NodeProfile:
    node_id: str
    display_name: str = ""
    bio: str = ""
    website: str = ""
    avatar_url: str = ""
    donation_address: str = ""
    timestamp: int = field(default_factory=lambda: int(time.time()))
    signature: str = ""
    id: str = ""
    schema_version: int = 1

    def canonical_payload(self) -> dict:
        data = asdict(self)
        data.pop("id")
        data.pop("signature")
        return data

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")

    def compute_id(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def sign(self, signing_key: SigningKey) -> None:
        self.signature = signing_key.sign(
            self.canonical_bytes(), encoder=HexEncoder
        ).signature.decode("ascii")
        self.id = self.compute_id()

    def verify_signature(self) -> bool:
        try:
            verify_key = VerifyKey(bytes.fromhex(self.node_id))
            verify_key.verify(self.canonical_bytes(), bytes.fromhex(self.signature))
            return True
        except Exception:
            return False

    def verify_id(self) -> bool:
        return self.id == self.compute_id()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: str | dict) -> NodeProfile:
        if isinstance(data, str):
            data = json.loads(data)
        return cls(**dict(data))


class NodeProfileStore:
    """SQLite-backed storage for the latest profile per node."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    def upsert(self, profile: NodeProfile) -> bool:
        existing = self.get(profile.node_id)
        if existing and existing.timestamp > profile.timestamp:
            return False
        if existing and existing.id == profile.id:
            return False
        self.conn.execute(
            """
            INSERT INTO node_profile (
                node_id, id, display_name, bio, website, avatar_url,
                donation_address, timestamp, signature, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                id = excluded.id,
                display_name = excluded.display_name,
                bio = excluded.bio,
                website = excluded.website,
                avatar_url = excluded.avatar_url,
                donation_address = excluded.donation_address,
                timestamp = excluded.timestamp,
                signature = excluded.signature,
                schema_version = excluded.schema_version
            WHERE excluded.timestamp >= node_profile.timestamp
            """,
            (
                profile.node_id,
                profile.id,
                profile.display_name,
                profile.bio,
                profile.website,
                profile.avatar_url,
                profile.donation_address,
                profile.timestamp,
                profile.signature,
                profile.schema_version,
            ),
        )
        self.conn.commit()
        return True

    def get(self, node_id: str) -> NodeProfile | None:
        row = self.conn.execute(
            "SELECT * FROM node_profile WHERE node_id = ?", (node_id,)
        ).fetchone()
        if row is None:
            return None
        return NodeProfile(
            node_id=row["node_id"],
            display_name=row["display_name"],
            bio=row["bio"],
            website=row["website"],
            avatar_url=row["avatar_url"],
            donation_address=row["donation_address"],
            timestamp=row["timestamp"],
            signature=row["signature"],
            id=row["id"],
            schema_version=row["schema_version"],
        )

    def all(self) -> list[NodeProfile]:
        rows = self.conn.execute(
            "SELECT * FROM node_profile ORDER BY timestamp DESC"
        ).fetchall()
        return [
            NodeProfile(
                node_id=row["node_id"],
                display_name=row["display_name"],
                bio=row["bio"],
                website=row["website"],
                avatar_url=row["avatar_url"],
                donation_address=row["donation_address"],
                timestamp=row["timestamp"],
                signature=row["signature"],
                id=row["id"],
                schema_version=row["schema_version"],
            )
            for row in rows
        ]
