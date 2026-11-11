"""Small independent client for OpenCLI's loopback HTTP browser bridge.

Uses the public bind-current/exec protocol, without a private adapter or cookie export.
The optional client selector also supports daemons that expose multiple clients.
"""

from __future__ import annotations

import ipaddress
import json
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .errors import ExportError, RetryableError

QNH_HOST = "qnh.meituan.com"
MASTER_PATH = "/qnh-gw3/api/product/tenant/page-query"


class OpenCLIBridge:
    def __init__(self, daemon="http://127.0.0.1:19825", client=None, timeout=30):
        try:
            parsed = urlsplit(daemon)
            loopback = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
            parsed.port  # Validate malformed/out-of-range ports before HTTP I/O.
        except (ValueError, TypeError):
            raise ExportError("--daemon 地址格式无效。") from None
        if (
            parsed.scheme != "http"
            or not loopback
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ExportError("--daemon 必须是无凭证的本机 HTTP 地址，例如 http://127.0.0.1:19825")
        self.daemon = daemon.rstrip("/")
        self.client = client
        self.timeout = timeout
        self.workspace = "qnh-master-" + uuid.uuid4().hex
        self.page = None
        self.opener = build_opener(ProxyHandler({}))

    def _http(self, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(
            self.daemon + path, data=body, headers={"X-OpenCLI": "1", "Content-Type": "application/json"}
        )
        try:
            with self.opener.open(req, timeout=self.timeout + 5) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise ExportError(f"OpenCLI HTTP {exc.code}；请检查 daemon 版本、扩展和 client。") from None
        except (OSError, URLError, ValueError):
            raise ExportError("OpenCLI 连接失败或超时；运行 opencli doctor，确认扩展在线后重试。") from None
        if not isinstance(result, dict):
            raise ExportError("OpenCLI 返回格式不兼容。")
        return result

    def clients(self):
        # /clients is an optional multi-profile extension; upstream single-client
        # daemons can still use the standard bind-current command without it.
        try:
            clients = self._http("/clients").get("clients", [])
            if not isinstance(clients, list) or any(not isinstance(c, dict) for c in clients):
                raise ExportError("OpenCLI clients 格式不兼容。")
            return clients
        except ExportError as exc:
            if "HTTP 404" not in str(exc):
                raise
            status = self._http("/status")
            if not status.get("extensionConnected"):
                return []
            return [{"clientId": None, "version": status.get("extensionVersion")}]

    def command(self, action, **params):
        payload = {
            "id": uuid.uuid4().hex,
            "action": action,
            "workspace": self.workspace,
            "timeout": self.timeout,
            **params,
        }
        if self.client:
            payload["targetClientId"] = self.client
        response = self._http("/command", payload)
        if not response.get("ok"):
            # Deliberately avoid raw bridge errors: some contain evaluated code,
            # request headers or response data. Keep diagnostics safe by default.
            raise ExportError(
                "浏览器命令失败；确认目标 client、已登录的牵牛花标签页及商品权限，"
                "关闭该页 DevTools；超时后请先确认原请求已结束。"
            )
        return response

    def bind(self):
        response = self.command("bind-current", matchDomain=QNH_HOST, matchPathPrefix="/home.html")
        self.page = response.get("page")
        if not self.page:
            raise ExportError("OpenCLI 未返回 page 标识；需要支持 bind-current 的 Browser Bridge。")
        result = self.command(
            "exec", page=self.page, code="({host:location.hostname,path:location.pathname})"
        ).get("data")
        if not isinstance(result, dict) or result.get("host") != QNH_HOST:
            raise ExportError("浏览器绑定域名不符；已停止。")
        return result

    def query_page(self, page, page_size=100):
        if not self.page:
            self.bind()
        body = {
            "labelInfoList": [],
            "storeFrontGroupCategoryList": [],
            "channelCategory": {"channelId": 100, "categoryProperty": {}},
            "page": page,
            "pageSize": page_size,
            "backendCategoryList": [],
        }
        # JSON literals are embedded in JS, never interpolated into a shell.
        # window.fetch retains the platform's own SDK behavior and browser cookies.
        code = """(async () => {
          if (location.hostname !== "qnh.meituan.com") return {wrongHost:true};
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), 20000);
          try {
            const r = await window.fetch(PATH, {
              method:"POST", credentials:"include", redirect:"error",
              headers:{"Content-Type":"application/json"},
              body:JSON.stringify(BODY), signal:controller.signal
            });
            let payload = null;
            try { payload = await r.json(); } catch {}
            return {status:r.status,payload};
          } catch { return {requestFailed:true}; }
          finally { clearTimeout(timer); }
        })()""".replace("PATH", json.dumps(MASTER_PATH)).replace("BODY", json.dumps(body))
        result = self.command("exec", page=self.page, code=code).get("data")
        if not isinstance(result, dict) or result.get("wrongHost"):
            raise ExportError("页面已切换或浏览器返回格式异常；已停止。")
        if result.get("requestFailed"):
            raise ExportError("页面请求失败或超时；请检查登录、网络和页面状态后续采。")
        status = result.get("status")
        if status in (500, 502, 503, 504):
            raise RetryableError(f"平台临时故障 HTTP {status}")
        if status != 200:
            raise ExportError(f"平台返回 HTTP {status}；请检查登录和访问权限后重试。")
        payload = result.get("payload")
        if not isinstance(payload, dict) or payload.get("code") != 0:
            api_code = payload.get("code") if isinstance(payload, dict) else "non-JSON"
            if not isinstance(api_code, (int, float)):
                api_code = "unknown"
            raise ExportError(f"平台业务请求失败（code={api_code}）；请检查商品权限或登录态。")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ExportError("主档接口 data 格式异常；已停止。")
        return data
