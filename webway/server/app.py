"""aiohttp application wiring for the webway server."""
from __future__ import annotations

import argparse
import logging
import os
import secrets

import bcrypt
from aiohttp import web

from webway.server.appkeys import CHANNELS_KEY, DB_KEY, SESSIONS_KEY, UPLOAD_DIR_KEY
from webway.server.auth import SessionStore
from webway.server.channels import ChannelRegistry
from webway.server.db import Database
from webway.server.files import handle_download, handle_upload
from webway.server.ws_protocol import websocket_handler

DEFAULT_PORT = 5555
DEFAULT_DB_PATH = "webway.db"
UPLOAD_DIR = "uploads"
SYSTEM_USERNAME = "system"
DEFAULT_CHANNEL_NAME = "general"


def create_app(db_path: str = DEFAULT_DB_PATH, upload_dir: str = UPLOAD_DIR) -> web.Application:
    app = web.Application(client_max_size=20 * 1024 * 1024)
    app[DB_KEY] = Database(db_path)
    app[SESSIONS_KEY] = SessionStore()
    app[CHANNELS_KEY] = ChannelRegistry()
    app[UPLOAD_DIR_KEY] = upload_dir
    os.makedirs(upload_dir, exist_ok=True)

    app.router.add_get("/ws", websocket_handler)
    app.router.add_post("/upload", handle_upload)
    app.router.add_get("/files/{file_id}", handle_download)

    app.on_startup.append(_seed_default_channel)
    app.on_cleanup.append(_on_cleanup)
    return app


async def _seed_default_channel(app: web.Application) -> None:
    """Create a #general channel on a brand-new install so there's somewhere to land."""
    db = app[DB_KEY]
    if await db.list_channels():
        return
    system_user = await db.get_user_by_username(SYSTEM_USERNAME)
    if system_user is None:
        random_hash = bcrypt.hashpw(secrets.token_hex(32).encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        user_id = await db.create_user(SYSTEM_USERNAME, random_hash)
    else:
        user_id = system_user["id"]
    await db.create_channel(DEFAULT_CHANNEL_NAME, "General discussion", user_id)


async def _on_cleanup(app: web.Application) -> None:
    app[DB_KEY].close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("port", nargs="?", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--uploads", default=UPLOAD_DIR)
    args = parser.parse_args()

    app = create_app(args.db, args.uploads)
    web.run_app(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
