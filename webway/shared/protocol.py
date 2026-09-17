"""Wire protocol shared between the webway server and client.

Every WebSocket frame is a single JSON object with a "type" key.
"""
from __future__ import annotations

import json
from typing import Any

MAX_TEXT_LENGTH = 2000
MAX_USERNAME_LENGTH = 32
MAX_CHANNEL_NAME_LENGTH = 64

# Client -> server
C_AUTH = "auth"
C_CHANNEL_CREATE = "channel.create"
C_CHANNEL_JOIN = "channel.join"
C_CHANNEL_LIST = "channel.list"
C_MESSAGE_SEND = "message.send"
C_MESSAGE_ACTION = "message.action"
C_TYPING = "typing"
C_REACTION_ADD = "reaction.add"

# Server -> client
S_AUTH_OK = "auth.ok"
S_AUTH_ERROR = "auth.error"
S_CHANNEL_LIST = "channel.list"
S_CHANNEL_CREATED = "channel.created"
S_HISTORY = "history"
S_MESSAGE = "message"
S_TYPING = "typing"
S_REACTION = "reaction"
S_PRESENCE = "presence"
S_ERROR = "error"


class ProtocolError(ValueError):
    """Raised when an incoming frame fails validation."""


def encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def decode(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict) or "type" not in payload:
        raise ProtocolError("frame must be a JSON object with a 'type' key")
    return payload


def require_str(payload: dict[str, Any], key: str, max_length: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"'{key}' must be a non-empty string")
    value = value.strip()
    if len(value) > max_length:
        raise ProtocolError(f"'{key}' exceeds {max_length} characters")
    return value


def require_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolError(f"'{key}' must be an integer")
    return value
