"""Web GUI tests: hit the HTTP handler with real requests on a random port.

All requests go through helpers that validate scheme and host against a
pinned loopback allowlist before connecting (keeps static analysis calm and
documents the intent).
"""
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from bulk_renamer.webgui import Handler

ALLOWED_SCHEMES = ("http",)
ALLOWED_HOSTS = ("127.0.0.1",)


def _validated_url(srv, path: str) -> str:
    url = f"http://127.0.0.1:{srv.server_address[1]}{path}"
    parsed = urllib.parse.urlparse(url)
    assert parsed.scheme in ALLOWED_SCHEMES, f"non-http scheme: {parsed.scheme}"
    assert parsed.hostname in ALLOWED_HOSTS, f"non-loopback host: {parsed.hostname}"
    return url


def _get(srv, path):
    with urllib.request.urlopen(_validated_url(srv, path)) as r:
        return r.status, r.read()


def _post(srv, path, body):
    req = urllib.request.Request(
        _validated_url(srv, path),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


@pytest.fixture()
def server(tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, tmp_path
    srv.shutdown()


def test_index_served(server):
    srv, _ = server
    status, body = _get(srv, "/")
    assert status == 200
    assert b"bulk-renamer" in body


def test_files_listing(server):
    srv, root = server
    (root / "a.txt").write_text("x")
    (root / "b.log").write_text("x")
    status, data = _get(srv, f"/api/files?dir={root}&filter=*.txt")
    assert status == 200
    assert json.loads(data)["files"] == ["a.txt"]


def test_plan_endpoint(server):
    srv, root = server
    (root / "IMG_1.jpg").write_text("x")
    status, data = _post(srv, "/api/plan", {
        "dir": str(root),
        "rules": [{"kind": "replace", "find": "IMG", "replace_with": "pic"}],
    })
    assert status == 200
    assert data["changes"] == 1
    assert data["rows"][0]["target"] == "pic_1.jpg"


def test_plan_bad_rule_returns_error(server):
    srv, root = server
    status, data = _post(srv, "/api/plan", {
        "dir": str(root),
        "rules": [{"kind": "replace", "find": "", "replace_with": "x"}],
    })
    assert status == 400
    assert "error" in data


def test_apply_then_undo(server):
    srv, root = server
    (root / "old.txt").write_text("x")
    status, data = _post(srv, "/api/apply", {
        "dir": str(root),
        "rules": [{"kind": "prefix", "text": "new_"}],
    })
    assert status == 200
    assert data["applied"] == 1
    assert (root / "new_old.txt").exists()

    status, data = _post(srv, "/api/undo", {"dir": str(root)})
    assert status == 200
    assert data["undone"] == 1
    assert (root / "old.txt").exists()


def test_undo_without_journal(server):
    srv, root = server
    status, data = _post(srv, "/api/undo", {"dir": str(root)})
    assert status == 400
