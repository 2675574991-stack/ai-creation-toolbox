"""本地 HTTP 服务：静态页面 + JSON API + 媒体流。"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import socket
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import paths
from .api import Api, ApiError
from .project import ProjectError

MIME = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".ico": "image/x-icon",
    ".woff2": "font/woff2", ".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
    ".mov": "video/quicktime", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac",
    ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".txt": "text/plain; charset=utf-8",
    ".pdf": "application/pdf",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AssetNest/" + paths.VERSION
    api: Api = None  # type: ignore

    def log_message(self, fmt, *args):
        pass

    # ---------- 输出 ----------
    def _send(self, status, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _json(self, obj, status: int = 200):
        self._send(status, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _err(self, msg: str, status: int = 400):
        self._json({"error": msg}, status)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            raw = self.rfile.read(n)
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    # ---------- 路由 ----------
    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PATCH(self):
        self._route("POST")

    def do_DELETE(self):
        self._route("POST")

    def _route(self, method: str):
        u = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(u.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query, keep_blank_values=True).items()}
        try:
            if path == "/api/thumb":
                return self._media(self.api.thumb_path(q), "image/webp", max_age=86400)
            if path == "/api/file":
                return self._file(q)
            if path == "/api/import":
                return self._import(q)
            if path.startswith("/api/"):
                return self._api(method, path, q)
            return self._static(path)
        except (ProjectError, ApiError) as e:
            self._err(str(e), getattr(e, "status", 400))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            traceback.print_exc()
            self._err("服务器内部错误：" + str(traceback.format_exc(limit=1)).strip().splitlines()[-1], 500)

    def _api(self, method: str, path: str, q: dict):
        a = self.api
        body = self._body() if method in ("POST", "PATCH", "DELETE") else {}
        if path == "/api/ping":
            return self._json({"ok": True, "version": paths.VERSION})
        if path == "/api/rev":
            return self._json({"rev": a.rev})
        if path == "/api/bootstrap":
            return self._json(a.bootstrap())
        if path == "/api/project" and method == "POST":
            return self._json(a.open_project(body.get("path", "")))
        if path == "/api/project/demo" and method == "POST":
            return self._json(a.demo())
        if path == "/api/pick-folder":
            return self._json(a.pick_folder(body.get("title") or "选择项目文件夹"))
        if path == "/api/tree":
            return self._json(a.tree())
        if path == "/api/files":
            return self._json(a.files(q))
        if path == "/api/fs":
            return self._json(a.fs_list(q))
        if path == "/api/meta":
            if method == "GET":
                return self._json(a.item_meta(q))
            return self._json(a.save_meta(body))
        if path == "/api/tags":
            return self._json(a.tags())
        if path == "/api/poster" and method == "POST":
            return self._json(a.poster(body))
        if path == "/api/peaks":
            if method == "GET":
                return self._json(a.peaks({}, q))
            return self._json(a.peaks(body, {}))
        if path == "/api/mkdir" and method == "POST":
            return self._json(a.mkdir(body))
        if path == "/api/move" and method == "POST":
            return self._json(a.move(body))
        if path == "/api/move/undo" and method == "POST":
            return self._json(a.move_undo(body))
        if path == "/api/rename" and method == "POST":
            return self._json(a.rename(body))
        if path == "/api/delete" and method == "POST":
            return self._json(a.delete(body))
        if path == "/api/reveal" and method == "POST":
            return self._json(a.reveal(body))
        if path == "/api/copy" and method == "POST":
            return self._json(a.copy_text(body))
        if path == "/api/export":
            kind = "json" if q.get("format") == "json" else "csv"
            data, ctype, filename = a.export(q, kind)
            return self._send(200, data, ctype, {
                "Content-Disposition": "attachment; filename*=UTF-8''"
                                       + urllib.parse.quote(filename), "Cache-Control": "no-store"})
        if path == "/api/settings" and method == "POST":
            return self._json(a.settings(body))
        if path == "/api/quit" and method == "POST":
            a.quit_event.set()
            return self._json({"ok": True})
        raise ApiError("未知接口 " + path, 404)

    def _import(self, q: dict):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except Exception:
            length = 0
        rel = self.headers.get("X-File-Rel") or "import.bin"
        folder = q.get("folder") or ""
        item = self.api.import_stream(self.rfile, length, folder, rel)
        self._json({"item": item, "rev": self.api.rev})

    def _media(self, file_path: str, ctype: str, max_age: int = 0):
        if not file_path or not os.path.isfile(file_path):
            raise ApiError("文件不存在", 404)
        with open(file_path, "rb") as f:
            data = f.read()
        self._send(200, data, ctype, {"Cache-Control": f"public, max-age={max_age}"})

    def _static(self, path: str):
        root = os.path.realpath(paths.web_dir())
        rel = path.lstrip("/") or "index.html"
        full = os.path.realpath(os.path.join(root, rel))
        if not (full == root or full.startswith(root + os.sep)) or not os.path.isfile(full):
            if not os.path.splitext(rel)[1]:
                full = os.path.join(root, "index.html")
                if not os.path.isfile(full):
                    return self._send(404, b"UI not found", "text/plain; charset=utf-8")
            else:
                return self._send(404, b"404", "text/plain; charset=utf-8")
        with open(full, "rb") as f:
            data = f.read()
        ctype = MIME.get(os.path.splitext(full)[1].lower()) or \
            mimetypes.guess_type(full)[0] or "application/octet-stream"
        self._send(200, data, ctype, {"Cache-Control": "no-cache"})

    def _file(self, q: dict):
        p = self.api._require_project()
        path = p.safe(q.get("p") or "")
        if not os.path.isfile(path):
            raise ApiError("文件不存在", 404)
        size = os.path.getsize(path)
        ext = os.path.splitext(path)[1].lower()
        ctype = MIME.get(ext) or "application/octet-stream"
        extra = {}
        if q.get("download") == "1":
            extra["Content-Disposition"] = "attachment; filename*=UTF-8''" + \
                urllib.parse.quote(os.path.basename(path))
        rng = self.headers.get("Range")
        start, end, partial = 0, size - 1, False
        if rng:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
                if start <= end:
                    partial = True
        length = max(0, end - start + 1)
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "private, max-age=3600")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(262144, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


def free_port(start: int = 47821) -> int:
    for port in range(start, start + 200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(api: Api, port: int = 0) -> ThreadingHTTPServer:
    Handler.api = api
    port = port or free_port()

    class Server(ThreadingHTTPServer):
        allow_reuse_address = False
        daemon_threads = True

    httpd = Server(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True, name="assetnest-http").start()
    return httpd
