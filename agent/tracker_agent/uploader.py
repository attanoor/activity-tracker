import gzip
import json
import socket
import urllib.error
import urllib.request

from tracker_agent import __version__


class Unauthorized(Exception):
    """The server no longer accepts this device's token (revoked or deleted)."""


def _request(url: str, body: bytes, headers: dict, timeout: float = 20) -> dict:
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": f"ActivityTrackerAgent/{__version__}", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise Unauthorized() from e
        detail = e.read()[:300].decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e


def send_events(api: str, token: str, events: list[dict]) -> dict:
    body = gzip.compress(json.dumps({"events": events}).encode())
    return _request(f"{api}/ingest/events", body, {"Authorization": f"Bearer {token}", "Content-Encoding": "gzip"})


def page_rules(api: str, token: str) -> dict:
    """The extension's page-reading rules, set by the admin."""
    req = urllib.request.Request(f"{api}/ingest/agent-config", headers={
        "Authorization": f"Bearer {token}", "User-Agent": f"ActivityTrackerAgent/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise Unauthorized() from e
        raise RuntimeError(f"HTTP {e.code}") from e


def enrol(api: str, code: str) -> dict:
    """Returns {"device_id", "token"}; raises RuntimeError with the server's message on failure."""
    body = json.dumps({"code": code, "hostname": socket.gethostname()}).encode()
    try:
        return _request(f"{api}/devices/enrol", body, {})
    except RuntimeError as e:
        msg = str(e)
        try:
            msg = json.loads(msg.split(": ", 1)[1])["detail"]
        except (IndexError, ValueError, KeyError, TypeError):
            pass
        raise RuntimeError(msg) from e
