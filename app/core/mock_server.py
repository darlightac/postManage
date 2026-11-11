"""Mock HTTP 服务引擎 - 支持多接口路由匹配、延时模拟与实时请求监控"""

import json
import time
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import threading
from typing import Optional, Callable
from PyQt6.QtCore import QObject, pyqtSignal

from app.core.db import Database
from app.core.models import MockApi


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """支持多线程并发处理请求的 HTTP 服务器"""
    daemon_threads = True
    allow_reuse_address = True


class MockRequestHandler(BaseHTTPRequestHandler):
    """处理外部 Mock 请求的 Handler"""

    server: "ThreadedHTTPServer"

    def do_HEAD(self):
        self._handle_request("HEAD")

    def do_GET(self):
        self._handle_request("GET")

    def do_POST(self):
        self._handle_request("POST")

    def do_PUT(self):
        self._handle_request("PUT")

    def do_DELETE(self):
        self._handle_request("DELETE")

    def do_PATCH(self):
        self._handle_request("PATCH")

    def do_OPTIONS(self):
        # 跨域预检处理
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

        log_data = self._build_log_entry("OPTIONS", 200, b"")
        if hasattr(self.server, "mock_server_instance"):
            self.server.mock_server_instance.record_request(log_data)

    def _handle_request(self, method: str):
        start_time = time.time()
        parsed_url = urllib.parse.urlparse(self.path)
        req_path = parsed_url.path
        query_str = parsed_url.query

        # 读取请求体
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            body_text = body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            body_text = body_bytes.decode("latin1", errors="replace")

        # 查找匹配的 Mock 规则
        mock_server = getattr(self.server, "mock_server_instance", None)
        matched_api: Optional[MockApi] = None
        if mock_server:
            matched_api = mock_server.match_api(method, req_path)

        if matched_api:
            # 模拟延时
            if matched_api.delay_ms > 0:
                time.sleep(matched_api.delay_ms / 1000.0)

            status_code = matched_api.status_code or 200
            resp_body = (matched_api.body_content or "").encode("utf-8")

            self.send_response(status_code)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "*")
            self.send_header("Access-Control-Allow-Headers", "*")

            resp_headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
            }
            has_ct = False
            for h in (matched_api.headers or []):
                k = h.get("key", "").strip()
                v = h.get("value", "")
                if k and h.get("enabled", True):
                    if k.lower() == "content-type":
                        has_ct = True
                    self.send_header(k, v)
                    resp_headers[k] = v

            if not has_ct:
                if matched_api.body_type == "json":
                    ct_val = "application/json; charset=utf-8"
                elif matched_api.body_type == "html":
                    ct_val = "text/html; charset=utf-8"
                elif matched_api.body_type == "xml":
                    ct_val = "application/xml; charset=utf-8"
                else:
                    ct_val = "text/plain; charset=utf-8"
                self.send_header("Content-Type", ct_val)
                resp_headers["Content-Type"] = ct_val

            self.send_header("Content-Length", str(len(resp_body)))
            resp_headers["Content-Length"] = str(len(resp_body))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(resp_body)
            resp_body_text = matched_api.body_content or ""
        else:
            status_code = 404
            err_json_str = json.dumps({
                "code": 404,
                "message": "Mock route not found",
                "method": method,
                "path": req_path
            }, ensure_ascii=False, indent=2)
            err_json = err_json_str.encode("utf-8")
            self.send_response(404)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_json)))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(err_json)
            resp_body_text = err_json_str
            resp_headers = {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(err_json)),
            }

        duration_ms = (time.time() - start_time) * 1000.0
        log_data = self._build_log_entry(
            method, status_code, body_text, query_str, duration_ms,
            resp_body=resp_body_text, resp_headers=resp_headers
        )
        if mock_server:
            mock_server.record_request(log_data)

    def _build_log_entry(
        self, method: str, status_code: int, body_text: str,
        query_str: str = "", duration_ms: float = 0.0,
        resp_body: str = "", resp_headers: Optional[dict] = None
    ) -> dict:
        parsed_url = urllib.parse.urlparse(self.path)
        headers_dict = dict(self.headers.items())
        
        # 解析 Cookie
        cookie_header = self.headers.get("Cookie", "")
        cookies_dict = {}
        if cookie_header:
            for item in cookie_header.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    cookies_dict[k.strip()] = v.strip()

        # 解析 Query
        params_dict = urllib.parse.parse_qs(query_str or parsed_url.query, keep_blank_values=True)
        # 将 list 展开为单值或保留 list
        query_formatted = {k: v[0] if len(v) == 1 else v for k, v in params_dict.items()}

        return {
            "timestamp": time.strftime("%H:%M:%S"),
            "method": method,
            "path": parsed_url.path,
            "query_raw": parsed_url.query,
            "query": query_formatted,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
            "client_ip": self.client_address[0] if self.client_address else "unknown",
            "headers": headers_dict,
            "cookies": cookies_dict,
            "body": body_text,
            "response_body": resp_body,
            "response_headers": resp_headers or {},
        }

    def log_message(self, format, *args):
        # 静默默认的 stderr 控制台输出
        pass


class MockService(QObject):
    """Mock 服务管理器（Qt 信号驱动）"""

    request_received = pyqtSignal(dict)  # 当有请求到达时发送通知字典
    server_started = pyqtSignal(int)     # 服务启动 (端口号)
    server_stopped = pyqtSignal()        # 服务停止

    _instance: Optional["MockService"] = None

    @classmethod
    def instance(cls) -> "MockService":
        if cls._instance is None:
            cls._instance = MockService()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self.httpd: Optional[ThreadedHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.port: int = 9999
        self.is_running: bool = False
        self._lock = threading.Lock()
        self.recent_logs: list[dict] = []
        self._max_logs = 200

    def start(self, port: int) -> tuple[bool, str]:
        """在指定端口启动 Mock 服务"""
        with self._lock:
            if self.is_running:
                if self.port == port:
                    return True, "Mock 服务已在运行"
                self._stop_internal()

            try:
                self.port = port
                self.httpd = ThreadedHTTPServer(("0.0.0.0", port), MockRequestHandler)
                self.httpd.mock_server_instance = self
                self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
                self.thread.start()
                self.is_running = True
                self.server_started.emit(port)
                return True, f"Mock 服务已成功启动于端口 {port}"
            except Exception as e:
                self.httpd = None
                self.thread = None
                self.is_running = False
                return False, f"启动 Mock 服务失败: {e}"

    def stop(self):
        """停止 Mock 服务"""
        with self._lock:
            self._stop_internal()

    def _stop_internal(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None
            self.thread = None
        self.is_running = False
        self.server_stopped.emit()

    def record_request(self, log_entry: dict):
        """记录收到的请求并触发信号通知 UI"""
        with self._lock:
            self.recent_logs.insert(0, log_entry)
            if len(self.recent_logs) > self._max_logs:
                self.recent_logs.pop()
        self.request_received.emit(log_entry)

    def clear_logs(self):
        with self._lock:
            self.recent_logs.clear()

    def match_api(self, method: str, path: str) -> Optional[MockApi]:
        """根据 HTTP Method 和 Path 匹配已配置的 MockApi"""
        # 从数据库读取所有 Mock 接口
        try:
            apis = Database().get_all_mock_apis()
            # 路径规范化（去掉首尾多余斜杠并忽略末尾斜杠）
            norm_req_path = "/" + path.strip("/")
            for api in apis:
                if not api.is_enabled:
                    continue
                if api.method.upper() != method.upper():
                    continue
                norm_api_path = "/" + api.path.strip("/")
                if norm_api_path == norm_req_path:
                    return api
        except Exception:
            pass
        return None
