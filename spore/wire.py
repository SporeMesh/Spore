"""Wire-level message helpers for the gossip transport."""

from __future__ import annotations

import asyncio
import json
import struct

HEADER_SIZE = 4  # 4-byte big-endian uint32 length prefix
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB


class MessageType:
    EXPERIMENT = "experiment"
    SYNC_REQUEST = "sync_request"
    SYNC_RESPONSE = "sync_response"
    PING = "ping"
    PONG = "pong"
    PEX_REQUEST = "pex_request"
    PEX_RESPONSE = "pex_response"
    CHALLENGE = "challenge"
    CHALLENGE_RESPONSE = "challenge_response"
    DISPUTE = "dispute"
    VERIFICATION = "verification"
    CODE_REQUEST = "code_request"
    CODE_RESPONSE = "code_response"


def encode_message(msg_type: str, payload: dict) -> bytes:
    """Encode a message as length-prefixed JSON."""
    envelope = {"type": msg_type, "payload": payload}
    body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    return struct.pack(">I", len(body)) + body


async def read_message(reader: asyncio.StreamReader) -> dict | None:
    """Read a length-prefixed JSON message from a stream."""
    header = await reader.readexactly(HEADER_SIZE)
    length = struct.unpack(">I", header)[0]
    if length > MAX_MESSAGE_SIZE:
        return None
    body = await reader.readexactly(length)
    return json.loads(body.decode("utf-8"))
