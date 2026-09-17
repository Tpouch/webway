"""aiohttp application wiring for the webway server."""
from __future__ import annotations

import argparse
import logging
import os

from aiohttp import web

from webway.server.appkeys import CHANNELS_KEY, DB_KEY, SESSIONS_KEY, UPLOAD_DIR_KEY
from webway.server.auth import SessionStore
from webway.server.channels import ChannelRegistry
from webway.server.db import Database
from webway.server.ws_protocol import websocket_handler

DEFAULT_PORT = 5555
DEFAULT_DB_PATH = "webway.db"
UPLOAD_DIR = "uploads"


def create_app(db_path: str = DEFAULT_DB_PATH, upload_dir: str = UPLOAD_DIR) -> web.Application:
    app = web.Application(client_max_size=20 * 1024 * 1024)
    app[DB_KEY] = Database(db_path)
    app[SESSIONS_KEY] = SessionStore()
    app[CHANNELS_KEY] = ChannelRegistry()
    app[UPLOAD_DIR_KEY] = upload_dir
    os.makedirs(upload_dir, exist_ok=True)

    app.router.add_get("/ws", websocket_handler)

    app.on_cleanup.append(_on_cleanup)
    return app


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
