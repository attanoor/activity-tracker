import json
import urllib.error
import urllib.request

import pytest

from tracker_agent.local_server import ALLOWED_ORIGINS, TabStore, start

ORIGIN = next(iter(ALLOWED_ORIGINS))


@pytest.fixture()
def server():
    tabs = TabStore()
    srv = start(0, tabs, lambda: {"mode": "tracking"})
    yield f"http://127.0.0.1:{srv.server_address[1]}", tabs
    srv.shutdown()


def post(base, body, origin=ORIGIN):
    req = urllib.request.Request(f"{base}/tab", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **({"Origin": origin} if origin else {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def test_extension_origin_sets_tab(server):
    base, tabs = server
    code, body = post(base, {"browser": "chrome.exe", "url": "https://github.com/", "title": "GitHub"})
    assert code == 200 and body == {"mode": "tracking"}
    assert tabs.snapshot()["chrome.exe"].url == "https://github.com/"


def test_other_origins_are_refused(server):
    base, tabs = server
    assert post(base, {"browser": "chrome.exe", "url": "https://evil/"}, origin="https://evil.example")[0] == 403
    assert post(base, {"browser": "chrome.exe", "url": "https://evil/"}, origin=None)[0] == 403
    assert post(base, {"browser": "chrome.exe", "url": "https://x/"},
                origin="chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")[0] == 403
    assert tabs.snapshot() == {}


def test_incognito_clears_tab_and_unknown_browser_rejected(server):
    base, tabs = server
    post(base, {"browser": "msedge.exe", "url": "https://a/", "title": "A"})
    post(base, {"browser": "msedge.exe", "url": "https://secret/", "title": "S", "incognito": True})
    assert "msedge.exe" not in tabs.snapshot()
    assert post(base, {"browser": "evil.exe", "url": "https://a/"})[0] == 400
