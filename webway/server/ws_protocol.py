"""Per-connection WebSocket message handling."""
from __future__ import annotations

import logging
import sqlite3
import time

from aiohttp import web

from webway.server.appkeys import CHANNELS_KEY, DB_KEY, SESSIONS_KEY
from webway.server.auth import AuthError, authenticate
from webway.shared import protocol as p

logger = logging.getLogger("webway.server.ws")

HISTORY_LIMIT = 50

# bcrypt raises ValueError rather than truncating past this many bytes.
MAX_PASSWORD_BYTES = 72


def _file_meta_dict(row) -> dict:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "mime": row["mime"],
        "size": row["size"],
        "url": f"/files/{row['id']}",
    }


async def _build_history_items(db, rows) -> list[dict]:
    items = []
    for row in rows:
        file_meta = await db.get_file(row["file_id"]) if row["file_id"] else None
        reaction_rows = await db.get_reactions(row["id"])
        items.append({
            "id": row["id"],
            "channel_id": row["channel_id"],
            "user_id": row["user_id"],
            "username": row["username"],
            "message_type": row["type"],
            "text": row["text"],
            "ts": row["ts"],
            "file": _file_meta_dict(file_meta) if file_meta else None,
            "reactions": [{"emoji": r["emoji"], "username": r["username"]} for r in reaction_rows],
        })
    return items


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    db = request.app[DB_KEY]
    sessions = request.app[SESSIONS_KEY]
    channels = request.app[CHANNELS_KEY]

    user_id: int | None = None
    username: str | None = None
    token: str | None = None

    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                payload = p.decode(msg.data)
            except p.ProtocolError as exc:
                logger.warning("dropped malformed frame: %s", exc)
                continue

            mtype = payload["type"]

            if mtype == p.C_AUTH:
                try:
                    uname = p.require_str(payload, "username", p.MAX_USERNAME_LENGTH)
                    password = payload.get("password")
                    if not isinstance(password, str) or not password:
                        raise p.ProtocolError("'password' must be a non-empty string")
                    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
                        raise p.ProtocolError("password too long")
                    user_id = await authenticate(db, uname, password)
                    username = uname
                    if token is not None:
                        sessions.revoke(token)
                    token = sessions.issue(user_id)
                    channels.register(ws, username)
                    await ws.send_str(p.encode({
                        "type": p.S_AUTH_OK, "user_id": user_id, "username": username,
                        "session_token": token,
                    }))
                    rows = await db.list_channels()
                    await ws.send_str(p.encode({
                        "type": p.S_CHANNEL_LIST,
                        "channels": [{"id": r["id"], "name": r["name"], "topic": r["topic"]} for r in rows],
                    }))
                except (p.ProtocolError, AuthError) as exc:
                    await ws.send_str(p.encode({"type": p.S_AUTH_ERROR, "reason": str(exc)}))
                except sqlite3.IntegrityError:
                    # Lost a first-use registration race: another connection just
                    # created this username, so our password is not the right one.
                    logger.warning("registration race for username %r", payload.get("username"))
                    await ws.send_str(p.encode({"type": p.S_AUTH_ERROR, "reason": "bad_credentials"}))
                except Exception:
                    logger.exception("unhandled error while authenticating")
                    await ws.send_str(p.encode({"type": p.S_ERROR, "reason": "internal_error"}))
                continue

            if user_id is None:
                await ws.send_str(p.encode({"type": p.S_ERROR, "reason": "not_authenticated"}))
                continue

            try:
                await _dispatch(mtype, payload, ws, db, channels, user_id, username)
            except p.ProtocolError as exc:
                await ws.send_str(p.encode({"type": p.S_ERROR, "reason": str(exc)}))
            except Exception:
                # One bad message must never tear down the connection, and must
                # never escape into the `async for` loop (which would skip the
                # cleanup below and leave a dead connection in the registry).
                logger.exception("unhandled error while handling %r", mtype)
                await ws.send_str(p.encode({"type": p.S_ERROR, "reason": "internal_error"}))
    finally:
        if username is not None:
            # Synchronous bookkeeping first: it must complete even if this task
            # is being cancelled and the awaits below never get to run.
            channels.unregister(ws)
            affected = channels.unsubscribe_all(ws)
            if token is not None:
                sessions.revoke(token)
            for channel_id in affected:
                await channels.broadcast(channel_id, {
                    "type": p.S_PRESENCE, "channel_id": channel_id,
                    "users": channels.members(channel_id),
                })

    return ws


async def _dispatch(mtype, payload, ws, db, channels, user_id: int, username: str) -> None:
    """Handle a single authenticated client frame."""
    if mtype == p.C_CHANNEL_LIST:
        rows = await db.list_channels()
        await ws.send_str(p.encode({
            "type": p.S_CHANNEL_LIST,
            "channels": [{"id": r["id"], "name": r["name"], "topic": r["topic"]} for r in rows],
        }))

    elif mtype == p.C_CHANNEL_CREATE:
        name = p.require_str(payload, "name", p.MAX_CHANNEL_NAME_LENGTH)
        topic = str(payload.get("topic", ""))[:200]
        channel_id = await db.create_channel(name, topic, user_id)
        await channels.broadcast_global({
            "type": p.S_CHANNEL_CREATED, "id": channel_id, "name": name, "topic": topic,
        })

    elif mtype == p.C_CHANNEL_JOIN:
        channel_id = p.require_int(payload, "channel_id")
        channel = await db.get_channel(channel_id)
        if channel is None:
            await ws.send_str(p.encode({"type": p.S_ERROR, "reason": "no_such_channel"}))
            return
        # A connection views one channel at a time: leave whatever it was in
        # before, or it lingers in the old channel's presence list forever and
        # keeps receiving its broadcasts.
        for old_id in channels.unsubscribe_all(ws):
            if old_id == channel_id:
                continue
            await channels.broadcast(old_id, {
                "type": p.S_PRESENCE, "channel_id": old_id, "users": channels.members(old_id),
            })
        channels.subscribe(channel_id, ws, username)
        history_rows = await db.get_history(channel_id, HISTORY_LIMIT)
        items = await _build_history_items(db, history_rows)
        await ws.send_str(p.encode({"type": p.S_HISTORY, "channel_id": channel_id, "items": items}))
        await channels.broadcast(channel_id, {
            "type": p.S_PRESENCE, "channel_id": channel_id, "users": channels.members(channel_id),
        })

    elif mtype in (p.C_MESSAGE_SEND, p.C_MESSAGE_ACTION):
        channel_id = p.require_int(payload, "channel_id")
        text = p.require_str(payload, "text", p.MAX_TEXT_LENGTH)
        file_id = payload.get("file_id")
        if file_id is not None and not isinstance(file_id, str):
            await ws.send_str(p.encode({"type": p.S_ERROR, "reason": "invalid_file_id"}))
            return
        if await db.get_channel(channel_id) is None:
            await ws.send_str(p.encode({"type": p.S_ERROR, "reason": "no_such_channel"}))
            return
        # Resolve the attachment before inserting: an unknown file_id would
        # otherwise trip the messages.file_id foreign key mid-insert.
        file_row = await db.get_file(file_id) if file_id else None
        if file_id and file_row is None:
            await ws.send_str(p.encode({"type": p.S_ERROR, "reason": "no_such_file"}))
            return
        msg_type = "action" if mtype == p.C_MESSAGE_ACTION else "msg"
        message_id = await db.create_message(channel_id, user_id, msg_type, text, file_id)
        await channels.broadcast(channel_id, {
            "type": p.S_MESSAGE, "id": message_id, "channel_id": channel_id,
            "user_id": user_id, "username": username, "message_type": msg_type, "text": text,
            "ts": time.time(), "file": _file_meta_dict(file_row) if file_row else None,
        })

    elif mtype == p.C_TYPING:
        channel_id = p.require_int(payload, "channel_id")
        state = bool(payload.get("state"))
        await channels.broadcast(channel_id, {
            "type": p.S_TYPING, "channel_id": channel_id, "username": username, "state": state,
        })

    elif mtype == p.C_REACTION_ADD:
        message_id = p.require_int(payload, "message_id")
        emoji = p.require_str(payload, "emoji", 8)
        message_row = await db.get_message(message_id)
        if message_row is None:
            await ws.send_str(p.encode({"type": p.S_ERROR, "reason": "no_such_message"}))
            return
        added = await db.add_reaction(message_id, user_id, emoji)
        if added:
            await channels.broadcast(message_row["channel_id"], {
                "type": p.S_REACTION, "message_id": message_id, "emoji": emoji, "username": username,
            })
