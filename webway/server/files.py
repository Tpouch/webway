"""HTTP handlers for file upload and download."""
from __future__ import annotations

import os
import re
import uuid
from urllib.parse import quote

from aiohttp import web

from webway.server.appkeys import DB_KEY, SESSIONS_KEY, UPLOAD_DIR_KEY

MAX_UPLOAD_SIZE = 15 * 1024 * 1024


async def handle_upload(request: web.Request) -> web.Response:
    token = request.headers.get("X-Session-Token")
    sessions = request.app[SESSIONS_KEY]
    user_id = sessions.resolve(token) if token else None
    if user_id is None:
        return web.json_response({"reason": "not_authenticated"}, status=401)

    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return web.json_response({"reason": "missing_file_field"}, status=400)

    filename = field.filename or "upload.bin"
    mime = field.headers.get("Content-Type", "application/octet-stream")

    upload_dir = request.app[UPLOAD_DIR_KEY]
    disk_path = os.path.join(upload_dir, uuid.uuid4().hex)

    size = 0
    with open(disk_path, "wb") as fh:
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                fh.close()
                os.remove(disk_path)
                return web.json_response({"reason": "file_too_large"}, status=413)
            fh.write(chunk)

    db = request.app[DB_KEY]
    file_id = await db.create_file(user_id, filename, mime, size, disk_path)
    return web.json_response({"file_id": file_id, "url": f"/files/{file_id}"})


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r'[\r\n\x00-\x1f"]', "", name).strip()
    return cleaned or "download"


async def handle_download(request: web.Request) -> web.StreamResponse:
    file_id = request.match_info["file_id"]
    db = request.app[DB_KEY]
    row = await db.get_file(file_id)
    if row is None:
        return web.json_response({"reason": "no_such_file"}, status=404)
    safe_name = _safe_filename(row["filename"])
    encoded_name = quote(safe_name, safe="")
    return web.FileResponse(
        path=row["path"],
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Disposition": (
                f'attachment; filename="{safe_name}"; filename*=UTF-8\'\'{encoded_name}'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
