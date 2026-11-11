import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qnh_master_export.bridge import OpenCLIBridge
from qnh_master_export.cli import main
from qnh_master_export.errors import ExportError, RetryableError


@pytest.fixture
def daemon():
    calls = []
    replies = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append((self.path, dict(self.headers), None))
            self.respond()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, dict(self.headers), body))
            self.respond()

        def respond(self):
            status, body = replies.pop(0)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls, replies
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_bind_then_query_on_pinned_page(daemon):
    url, calls, replies = daemon
    replies.extend(
        [
            (200, {"ok": True, "page": "demo-page"}),
            (200, {"ok": True, "data": {"host": "qnh.meituan.com", "path": "/home.html"}}),
            (
                200,
                {
                    "ok": True,
                    "data": {"status": 200, "payload": {"code": 0, "data": {"total": 0, "list": []}}},
                },
            ),
        ]
    )
    bridge = OpenCLIBridge(url, "demo-client")
    assert bridge.query_page(1) == {"total": 0, "list": []}
    assert [c[2]["action"] for c in calls] == ["bind-current", "exec", "exec"]
    assert len({c[2]["id"] for c in calls}) == 3
    assert all(c[2]["targetClientId"] == "demo-client" for c in calls)
    assert all(c[1].get("X-Opencli") == "1" for c in calls)
    assert calls[-1][2]["page"] == "demo-page"
    code = calls[-1][2]["code"]
    assert "window.fetch" in code and 'credentials:"include"' in code
    assert '"pageSize": 100' in code and "mtgsig" not in code


def test_single_client_upstream_fallback(daemon):
    url, _, replies = daemon
    replies.extend([(404, {}), (200, {"extensionConnected": True, "extensionVersion": "1.7.2"})])
    assert OpenCLIBridge(url).clients() == [{"clientId": None, "version": "1.7.2"}]


@pytest.mark.parametrize(
    "payload,error_type",
    [
        ({"status": 503}, RetryableError),
        ({"status": 429}, ExportError),
        ({"status": 200, "payload": {"code": 40100010}}, ExportError),
        ({"wrongHost": True}, ExportError),
        ({"requestFailed": True}, ExportError),
        ({"status": 200, "payload": {"code": 0, "data": []}}, ExportError),
    ],
)
def test_platform_failures_are_actionable(daemon, payload, error_type):
    url, _, replies = daemon
    replies.append((200, {"ok": True, "data": payload}))
    bridge = OpenCLIBridge(url)
    bridge.page = "demo-page"
    with pytest.raises(error_type):
        bridge.query_page(1)


def test_private_bridge_errors_not_echoed(daemon):
    url, _, replies = daemon
    replies.append((200, {"ok": False, "error": "Cookie: secret-demo-value"}))
    bridge = OpenCLIBridge(url)
    with pytest.raises(ExportError) as error:
        bridge.bind()
    assert "secret-demo-value" not in str(error.value)


@pytest.mark.parametrize("empty", [False, True])
def test_cli_pipeline_through_http_bridge(daemon, tmp_path, empty):
    url, calls, replies = daemon
    records = [] if empty else [{"tenantId": "demo-tenant", "spuId": "demo-spu", "spuName": "虚构商品"}]
    replies.extend(
        [
            (200, {"ok": True, "page": "demo-page"}),
            (200, {"ok": True, "data": {"host": "qnh.meituan.com", "path": "/home.html"}}),
            (
                200,
                {
                    "ok": True,
                    "data": {
                        "status": 200,
                        "payload": {"code": 0, "data": {"page": 1, "total": len(records), "list": records}},
                    },
                },
            ),
        ]
    )
    out = tmp_path / "export"
    result = main(["run", "--daemon", url, "--tenant", "demo-tenant", "--out", str(out)])
    assert result == (3 if empty else 0)
    assert len(calls) == 3
    assert (out / "master.xlsx").exists() is not empty
    if not empty:
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["status"] == "complete" and manifest["spu_collected"] == 1
        assert json.loads((out / "spus.jsonl").read_text(encoding="utf-8"))["spuId"] == "demo-spu"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.invalid",
        "http://example.invalid",
        "http://127.0.0.1:19825/path",
        "http://user:pass@localhost:19825",
        "http://localhost:19825?token=test",
        "http:///missing",
        "http://[bad",
        "http://localhost:99999",
    ],
)
def test_only_loopback_daemon_accepted(url):
    with pytest.raises(ExportError):
        OpenCLIBridge(url)
