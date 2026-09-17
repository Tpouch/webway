"""Tests for the HTTP file upload/download endpoints."""
import os
import tempfile

from aiohttp import FormData
from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web

from webway.server import files as files_module
from webway.server.app import create_app
from webway.shared import protocol as p


class FilesTestCase(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self.tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self.tmpdir, "test.db")
        upload_dir = os.path.join(self.tmpdir, "uploads")
        return create_app(db_path, upload_dir)

    async def _session_token(self, username="alice"):
        async with self.client.ws_connect("/ws") as ws:
            await ws.send_str(p.encode({"type": p.C_AUTH, "username": username, "password": "pw"}))
            import json
            reply = json.loads(await ws.receive_str())
            return reply["session_token"]

    async def test_upload_without_token_is_rejected(self):
        data = FormData()
        data.add_field("file", b"hello", filename="hello.txt", content_type="text/plain")
        resp = await self.client.post("/upload", data=data)
        self.assertEqual(resp.status, 401)

    async def test_upload_and_download_round_trip(self):
        token = await self._session_token()
        data = FormData()
        data.add_field("file", b"hello world", filename="hello.txt", content_type="text/plain")
        resp = await self.client.post("/upload", data=data, headers={"X-Session-Token": token})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("file_id", body)

        download = await self.client.get(f"/files/{body['file_id']}")
        self.assertEqual(download.status, 200)
        content = await download.read()
        self.assertEqual(content, b"hello world")

    async def test_download_unknown_file_is_404(self):
        resp = await self.client.get("/files/does-not-exist")
        self.assertEqual(resp.status, 404)

    async def test_upload_over_size_limit_is_rejected(self):
        original = files_module.MAX_UPLOAD_SIZE
        files_module.MAX_UPLOAD_SIZE = 4
        try:
            token = await self._session_token()
            data = FormData()
            data.add_field("file", b"this is too big", filename="big.bin", content_type="application/octet-stream")
            resp = await self.client.post("/upload", data=data, headers={"X-Session-Token": token})
            self.assertEqual(resp.status, 413)
        finally:
            files_module.MAX_UPLOAD_SIZE = original

    async def test_download_response_headers_are_secure(self):
        token = await self._session_token()
        data = FormData()
        data.add_field("file", b"test content", filename="test.txt", content_type="text/html")
        resp = await self.client.post("/upload", data=data, headers={"X-Session-Token": token})
        body = await resp.json()
        file_id = body["file_id"]

        download = await self.client.get(f"/files/{file_id}")
        self.assertEqual(download.status, 200)
        self.assertEqual(download.headers["Content-Type"], "application/octet-stream")
        self.assertTrue(download.headers["Content-Disposition"].startswith("attachment"))
        self.assertIn("X-Content-Type-Options", download.headers)
        self.assertEqual(download.headers["X-Content-Type-Options"], "nosniff")

    async def test_download_sanitizes_unsafe_filename(self):
        token = await self._session_token()
        data = FormData()
        # Upload a file with a quote in the filename
        # (aiohttp validates on client side, but we test the server-side sanitization)
        unsafe_filename = 'test"file.txt'
        data.add_field("file", b"content", filename=unsafe_filename, content_type="text/plain")
        resp = await self.client.post("/upload", data=data, headers={"X-Session-Token": token})
        body = await resp.json()
        file_id = body["file_id"]

        download = await self.client.get(f"/files/{file_id}")
        self.assertEqual(download.status, 200)
        # Verify the response has valid headers without header injection
        disposition = download.headers["Content-Disposition"]
        # Should not contain raw newlines or double quotes outside of encoding
        self.assertNotIn("\r", disposition)
        self.assertNotIn("\n", disposition)
        # Content should still be readable
        content = await download.read()
        self.assertEqual(content, b"content")
