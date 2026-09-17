"""Typed keys for aiohttp Application-level state, shared across server modules."""
from __future__ import annotations

from aiohttp import web

from webway.server.auth import SessionStore
from webway.server.channels import ChannelRegistry
from webway.server.db import Database

DB_KEY: web.AppKey[Database] = web.AppKey("db", Database)
SESSIONS_KEY: web.AppKey[SessionStore] = web.AppKey("sessions", SessionStore)
CHANNELS_KEY: web.AppKey[ChannelRegistry] = web.AppKey("channels", ChannelRegistry)
UPLOAD_DIR_KEY: web.AppKey[str] = web.AppKey("upload_dir", str)
