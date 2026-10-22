"""127.0.0.1-only endpoint the browser extension reports the active tab to.

Only the tracker extension's origin is accepted (its ID is fixed by the key in extension/manifest.json),
so web pages cannot feed the agent fake activity.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from tracker_agent.core import BROWSERS, Tab

EXTENSION_ID = "odcdjagpgncdkaadeilapklolefhpeoc"
ALLOWED_ORIGINS = {f"chrome-extension://{EXTENSION_ID}"}
MAX_BODY = 16 * 1024
MAX_CONTEXT = 2048


class TabStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._tabs: dict[str, Tab] = {}

    def set(self, browser: str, tab: Tab | None) -> None:
        with self._lock:
            if tab is None:
                self._tabs.pop(browser, None)
            else:
                self._tabs[browser] = tab

    def snapshot(self) -> dict[str, Tab]:
        with self._lock:
            return dict(self._tabs)


def make_handler(tabs: TabStore, status: Callable[[], dict], page_rules: Callable[[], dict]):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep URLs out of any console/log
            pass

        def _origin_ok(self) -> bool:
            return self.headers.get("Origin") in ALLOWED_ORIGINS

        def _send(self, code: int, body: dict | None = None):
            data = b"" if code == 204 else json.dumps(body or {}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            if self._origin_ok():
                self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self._send(204 if self._origin_ok() else 403)

        def do_GET(self):
            if not self._origin_ok():
                return self._send(403, {"error": "origin"})
            if self.path == "/status":
                return self._send(200, status())
            if self.path == "/config":
                return self._send(200, page_rules())
            self._send(404)

        def do_POST(self):
            if not self._origin_ok():
                return self._send(403, {"error": "origin"})
            if self.path != "/tab":
                return self._send(404)
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n > MAX_BODY:
                    return self._send(413)
                body = json.loads(self.rfile.read(n))
                browser = str(body["browser"]).lower()
            except (ValueError, KeyError, TypeError):
                return self._send(400)
            if browser not in BROWSERS:
                return self._send(400, {"error": "browser"})
            url, title, context = body.get("url"), body.get("title"), body.get("context")
            if not isinstance(context, dict) or len(json.dumps(context)) > MAX_CONTEXT:
                context = None
            if body.get("incognito") or not isinstance(url, str):
                tabs.set(browser, None)  # nothing recorded beyond the window itself
            else:
                tabs.set(browser, Tab(url=url[:4000], title=str(title or "")[:2000], context=context))
            self._send(200, status())

    return Handler


DEFAULT_RULES = {"page_reading": True, "allow": [], "skip": []}


def start(port: int, tabs: TabStore, status: Callable[[], dict],
          page_rules: Callable[[], dict] = lambda: DEFAULT_RULES) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(tabs, status, page_rules))
    threading.Thread(target=server.serve_forever, name="local-server", daemon=True).start()
    return server
