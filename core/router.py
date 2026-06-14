"""极简 HTTP 路由（基于 http.server）。

特性：
- 装饰器 @router.route("/path", methods=("GET","POST"))
- 路径参数 /<name> 自动注入
- 自动解析 query string / urlencoded form / JSON body
- 响应类型支持 str (HTML) / dict (JSON) / tuple (status, body)
"""
from __future__ import annotations

import json
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

from core.config import STATIC_DIR


class Route:
    def __init__(self, pattern: str, methods: tuple, handler: Callable) -> None:
        self.pattern = pattern
        self.methods = tuple(m.upper() for m in methods)
        self.handler = handler
        self.regex, self.param_names = self._compile(pattern)

    @staticmethod
    def _compile(pattern: str):
        names = []
        def repl(m):
            names.append(m.group(1))
            return r"(?P<%s>[^/]+)" % m.group(1)
        regex = re.sub(r"<(\w+)>", repl, pattern)
        return re.compile("^" + regex + "$"), names


class Router:
    def __init__(self) -> None:
        self.routes: list[Route] = []

    def route(self, pattern: str, methods=("GET",)):
        def deco(fn):
            self.routes.append(Route(pattern, methods, fn))
            return fn
        return deco

    def match(self, path: str, method: str):
        for r in self.routes:
            if method not in r.methods:
                continue
            m = r.regex.match(path)
            if m:
                return r, m.groupdict()
        return None, None


router = Router()


class Request:
    def __init__(self, method: str, path: str, query: dict, headers: dict,
                 body: bytes, form: dict, json_body):
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.body = body
        self.form = form
        self.json = json_body

    def get(self, key: str, default=None):
        if key in self.form:
            return self.form[key]
        if key in self.query:
            return self.query[key]
        if isinstance(self.json, dict):
            return self.json.get(key, default)
        return default


def _parse_qs_flat(qs: str) -> dict:
    return {k: (v[0] if len(v) == 1 else v) for k, v in parse_qs(qs, keep_blank_values=True).items()}


class Handler(BaseHTTPRequestHandler):
    server_version = "InvestMgmt/1.0"

    def log_message(self, fmt, *args):  # 静默 access log，只在错误时打印
        if str(args[1] if len(args) > 1 else "")[:1] in ("4", "5"):
            super().log_message(fmt, *args)

    def _serve_static(self, path: str) -> bool:
        if not path.startswith("/static/"):
            return False
        rel = path[len("/static/"):]
        fp = (STATIC_DIR / rel).resolve()
        try:
            fp.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(403); return True
        if not fp.is_file():
            self.send_error(404); return True
        ext = fp.suffix.lower()
        ctype = {
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".ico": "image/x-icon",
        }.get(ext, "application/octet-stream")
        data = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return True

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if self._serve_static(path):
            return
        query = _parse_qs_flat(parsed.query)
        body = b""
        form: dict = {}
        json_body = None
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                body = self.rfile.read(length)
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if ctype == "application/x-www-form-urlencoded":
                form = _parse_qs_flat(body.decode("utf-8"))
            elif ctype == "application/json":
                try:
                    json_body = json.loads(body.decode("utf-8"))
                except Exception:
                    json_body = None

        route, kwargs = router.match(path, method)
        if not route:
            self.send_error(404, f"No route: {method} {path}")
            return
        req = Request(method, path, query, dict(self.headers), body, form, json_body)
        try:
            resp = route.handler(req, **(kwargs or {}))
            self._write_response(resp)
        except Exception:
            tb = traceback.format_exc()
            self._write_response((500, f"<pre>{tb}</pre>"))

    def _write_response(self, resp) -> None:
        status = 200
        body: bytes
        ctype = "text/html; charset=utf-8"
        headers: dict = {}

        if isinstance(resp, tuple):
            if len(resp) == 2:
                status, payload = resp
            elif len(resp) == 3:
                status, payload, headers = resp
            else:
                raise ValueError("tuple response must be (status, body[, headers])")
        else:
            payload = resp

        if isinstance(payload, dict) or isinstance(payload, list):
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        elif isinstance(payload, bytes):
            body = payload
        else:
            body = str(payload).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", headers.get("Content-Type", ctype))
        self.send_header("Content-Length", str(len(body)))
        for k, v in headers.items():
            if k.lower() == "content-type":
                continue
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")
    def do_PUT(self): self._handle("PUT")
    def do_DELETE(self): self._handle("DELETE")


def run_server(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"[投资管理系统] 已启动 -> http://{host}:{port}")
    print("[提示] 按 Ctrl+C 退出")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[投资管理系统] 已停止")
    finally:
        server.server_close()


def redirect(url: str, status: int = 302):
    return (status, b"", {"Location": url, "Content-Type": "text/plain; charset=utf-8"})
