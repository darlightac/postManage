"""基于 Chrome DevTools Protocol (CDP) 的真实浏览器交互嗅探与动态请求录制引擎

零第三方外部框架依赖 (纯 Python 标准库 + Windows 原生 Edge / Chrome)。
支持：
1. 调起真实浏览器窗口供用户点击、交互、登录、触发动态异步请求；
2. 一键强制刷新当前网页并重新执行全量 JS；
3. 底层协议栈实时监听并捕获所有 Fetch / XHR / POST / GET 网络请求与数据体；
4. 自动注入全局请求头与匹配域名 Cookie。
"""

import os
import sys
import json
import time
import socket
import ssl
import struct
import base64
import shutil
import tempfile
import threading
import subprocess
import urllib.request
import atexit
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field


def detect_browser_executable() -> Optional[str]:
    """探测本机安装的 Microsoft Edge 或 Google Chrome 路径 (优先系统自带 Edge)"""
    candidates = []
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

        candidates.extend([
            os.path.join(prog_files_x86, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(prog_files, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(local_app, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(prog_files, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(prog_files_x86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local_app, r"Google\Chrome\Application\chrome.exe"),
        ])

    for path in candidates:
        if path and os.path.isfile(path):
            return path

    # 兜底查询环境变量 PATH
    for name in ["msedge", "chrome", "google-chrome", "chromium"]:
        p = shutil.which(name)
        if p and os.path.isfile(p):
            return p

    return None


class SimpleWebSocketClient:
    """轻量级同步 RFC 6455 WebSocket 客户端 (专用于本地 localhost CDP 通信)"""

    def __init__(self, ws_url: str, timeout: float = 3.0):
        self.ws_url = ws_url
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._connect()

    def _connect(self):
        url = self.ws_url
        if url.startswith("ws://"):
            url = url[5:]
            use_ssl = False
        elif url.startswith("wss://"):
            url = url[6:]
            use_ssl = True
        else:
            raise ValueError(f"非法的 WebSocket URL: {url}")

        host_port, path = url.split("/", 1)
        path = "/" + path
        if ":" in host_port:
            host, port_str = host_port.split(":")
            port = int(port_str)
        else:
            host = host_port
            port = 443 if use_ssl else 80

        raw_sock = socket.create_connection((host, port), timeout=self.timeout)
        if use_ssl:
            ctx = ssl.create_default_context()
            self.sock = ctx.wrap_socket(raw_sock, server_hostname=host)
        else:
            self.sock = raw_sock

        sec_key = base64.b64encode(os.urandom(16)).decode("utf-8")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {sec_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode("utf-8"))

        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket 握手失败：连接被服务端关闭")
            buf += chunk

        lines = buf.split(b"\r\n")
        if not lines or b"101" not in lines[0]:
            raise ConnectionError(f"WebSocket 握手状态码异常: {lines[0].decode('utf-8', errors='ignore')}")

    def send_json(self, req: dict):
        payload = json.dumps(req).encode("utf-8")
        length = len(payload)
        header = bytearray([0x81])  # FIN=1, opcode=1 (text)
        mask = os.urandom(4)

        if length <= 125:
            header.append(0x80 | length)
        elif length <= 65535:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))

        header.extend(mask)
        masked_payload = bytearray(length)
        for i in range(length):
            masked_payload[i] = payload[i] ^ mask[i % 4]

        with self._lock:
            if self.sock:
                self.sock.sendall(header + masked_payload)

    def recv_json(self, timeout: float = 0.5) -> Optional[dict]:
        if not self.sock:
            return None
        self.sock.settimeout(timeout)
        try:
            head = self._recv_exact(2)
        except (TimeoutError, socket.timeout):
            return None
        except (ConnectionError, BrokenPipeError, ConnectionResetError, OSError) as e:
            self.close()
            raise ConnectionError(f"WebSocket 连接已断开: {e}")
        except Exception:
            return None

        b1, b2 = head[0], head[1]
        opcode = b1 & 0x0F
        is_masked = bool(b2 & 0x80)
        length = b2 & 0x7F

        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]

        mask = self._recv_exact(4) if is_masked else None
        payload = self._recv_exact(length)

        if is_masked and mask:
            unmasked = bytearray(length)
            for i in range(length):
                unmasked[i] = payload[i] ^ mask[i % 4]
            payload = bytes(unmasked)

        if opcode == 0x8:  # Close
            return None
        elif opcode == 0x9:  # Ping
            pong = bytearray([0x8A, 0x80]) + os.urandom(4)
            with self._lock:
                if self.sock:
                    self.sock.sendall(pong)
            return None
        elif opcode == 0x1:  # Text
            try:
                return json.loads(payload.decode("utf-8", errors="replace"))
            except Exception:
                return None
        return None

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Socket 已断开")
            buf.extend(chunk)
        return bytes(buf)

    def close(self):
        with self._lock:
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None


@dataclass
class CapturedRequest:
    """真机嗅探捕获的网络请求对象"""
    request_id: str
    method: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    post_data: str = ""
    resource_type: str = "XHR"  # XHR, Fetch, Document, Script, Stylesheet, Image, Other
    status_code: int = 0
    status_text: str = ""
    response_headers: Dict[str, str] = field(default_factory=dict)
    mime_type: str = ""
    elapsed_ms: float = 0.0
    size_bytes: int = 0
    error: str = ""
    timestamp: float = 0.0
    start_time: float = 0.0
    response_body: str = ""
    is_api: bool = True  # 是否为 API 接口 (XHR / Fetch / POST / JSON)


class BrowserSnifferController:
    """真机浏览器嗅探与动态录制控制器"""

    _active_controllers: set = set()

    def __init__(self):
        BrowserSnifferController._active_controllers.add(self)
        self._proc: Optional[subprocess.Popen] = None
        self._ws: Optional[SimpleWebSocketClient] = None
        self._temp_dir: Optional[str] = None
        self._port: int = 0
        self._is_running: bool = False
        self._worker_thread: Optional[threading.Thread] = None

        self._requests: Dict[str, CapturedRequest] = {}
        self._req_lock = threading.Lock()
        self._id_counter: int = 100

        # 在途网络请求追踪 (Network In-flight Tracker，保障数据完整返回与极致并发压测效率)
        self._in_flight_reqs: set = set()
        self._in_flight_lock = threading.Lock()

        # 回调通知 (UI 线程可通过信号联动)
        self.on_request_captured: Optional[Callable[[CapturedRequest], None]] = None
        self.on_request_updated: Optional[Callable[[CapturedRequest], None]] = None
        self.on_status_changed: Optional[Callable[[str], None]] = None

    @classmethod
    def stop_all(cls):
        """全局清理：终止所有运行中的嗅探浏览器进程"""
        for ctrl in list(cls._active_controllers):
            try:
                ctrl.stop()
            except Exception:
                pass

    def is_running(self) -> bool:
        return self._is_running and self._proc is not None and self._proc.poll() is None

    def get_requests(self) -> List[CapturedRequest]:
        with self._req_lock:
            return list(self._requests.values())

    def clear_requests(self):
        with self._req_lock:
            self._requests.clear()
        with self._in_flight_lock:
            self._in_flight_reqs.clear()

    def start(
        self,
        url: str,
        headless: bool = False,
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
        browser_path: Optional[str] = None,
        proxy_cfg: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """启动浏览器并开始抓包 (支持代理自动注入、静默无头模式与全协议栈录制)"""
        if self.is_running():
            self.stop()

        exe = browser_path or detect_browser_executable()
        if not exe:
            raise FileNotFoundError(
                "未在系统中检测到 Microsoft Edge 或 Google Chrome 浏览器。\n"
                "请安装 Edge 或 Chrome，或在设置中配置浏览器路径。"
            )

        # 分配空闲端口
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self._port = s.getsockname()[1]

        self._temp_dir = tempfile.mkdtemp(prefix="postmanage_browser_")

        args = [
            exe,
            f"--remote-debugging-port={self._port}",
            f"--user-data-dir={self._temp_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            "--disable-translate",
            "--disable-background-networking",
            "--disable-client-side-phishing-detection",
        ]

        if headless:
            args.append("--headless=new")
            args.append("--disable-gpu")

        # ── 解析并注入代理配置 (彻底解决后台无头静默压测时代理失效的问题) ──
        try:
            from app.config.settings import Settings
            from app.core.proxy_manager import get_system_proxy_info

            p_cfg = proxy_cfg if proxy_cfg is not None else (Settings().proxy or {})
            p_mode = p_cfg.get("mode", "system")

            if p_mode in ("none", "direct"):
                args.append("--no-proxy-server")
            elif p_mode == "pac":
                pac_url = p_cfg.get("pac_url", "").strip()
                if pac_url:
                    args.append(f"--proxy-pac-url={pac_url}")
            elif p_mode in ("custom", "manual"):
                proto = (p_cfg.get("protocol") or "http").lower()
                server = (p_cfg.get("server") or "").strip()
                host = (p_cfg.get("host") or "").strip()
                port = str(p_cfg.get("port") or "").strip()
                all_p = (p_cfg.get("all_proxy") or "").strip()
                t_server = all_p or server or (f"{host}:{port}" if host and port else "")
                if t_server:
                    if not t_server.startswith("http://") and not t_server.startswith("https://") and not t_server.startswith("socks5://"):
                        t_server = f"{proto}://{t_server}"
                    args.append(f"--proxy-server={t_server}")
                bypass = p_cfg.get("bypass", "").strip()
                if bypass:
                    args.append(f"--proxy-bypass-list={bypass}")
            elif p_mode == "system":
                sys_info = get_system_proxy_info()
                if sys_info.get("pac_url"):
                    args.append(f'--proxy-pac-url={sys_info["pac_url"]}')
                elif sys_info.get("enabled") and sys_info.get("server"):
                    args.append(f'--proxy-server={sys_info["server"]}')
                    if sys_info.get("bypass"):
                        args.append(f'--proxy-bypass-list={sys_info["bypass"]}')
        except Exception:
            pass

        # 允许忽略 HTTPS 代理证书校验 (确保企业自签名、内网 HTTPS 代理正常握手)
        args.append("--ignore-certificate-errors")
        args.append("--allow-insecure-localhost")

        # 启动时先打开空白页，确保 CDP 连接与全局请求头/Cookie 注入就绪后，再导航至目标 URL
        args.append("about:blank")

        try:
            self._proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self._cleanup()
            raise RuntimeError(f"启动浏览器进程失败: {e}")

        # 等待 CDP 端点就绪
        ws_url = None
        for _ in range(30):
            if self._proc.poll() is not None:
                raise RuntimeError("浏览器进程意外退出")
            time.sleep(0.2)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/json", timeout=1.0) as resp:
                    targets = json.loads(resp.read().decode("utf-8"))
                    page_target = next((t for t in targets if t.get("type") == "page"), None)
                    if page_target and "webSocketDebuggerUrl" in page_target:
                        ws_url = page_target["webSocketDebuggerUrl"]
                        break
            except Exception:
                continue

        if not ws_url:
            self.stop()
            raise TimeoutError("连接浏览器 CDP 调试端点超时")

        self._ws = SimpleWebSocketClient(ws_url, timeout=5.0)

        # 启用 Network 和 Page 域并开启跨页面/新建标签自动挂接 (AutoAttach)
        self._send_cdp("Network.enable", {"maxPostDataSize": 65536})
        self._send_cdp("Page.enable")
        self._send_cdp("Target.setAutoAttach", {
            "autoAttach": True,
            "waitForDebuggerOnStart": False,
            "flatten": True,
        })

        # 注入全局请求头 (使浏览器发出的所有首屏及后续请求 100% 携带)
        if headers:
            clean_headers = {k: v for k, v in headers.items() if k and v}
            if clean_headers:
                self._send_cdp("Network.setExtraHTTPHeaders", {"headers": clean_headers})

        # 注入匹配的 Cookie
        if cookies:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain = parsed.hostname or "localhost"
                for ck_name, ck_val in cookies.items():
                    if ck_name:
                        self._send_cdp(
                            "Network.setCookie",
                            {
                                "name": ck_name,
                                "value": ck_val,
                                "domain": domain,
                                "path": "/",
                            },
                        )
            except Exception:
                pass

        self._is_running = True

        # 开启后台事件监听循环
        self._worker_thread = threading.Thread(target=self._cdp_listener_loop, daemon=True)
        self._worker_thread.start()

        # CDP 及认证环境就绪后，正式命令浏览器加载目标 URL
        if url:
            self._send_cdp("Page.navigate", {"url": url})

        if self.on_status_changed:
            self.on_status_changed("🟢 浏览器已连接，实时抓包录制中...")

        return True

    def reload_page(self, ignore_cache: bool = True):
        """发送命令强制刷新页面，重新触发全部 JS 与 API 请求"""
        with self._in_flight_lock:
            self._in_flight_reqs.clear()
        if self.is_running() and self._ws:
            self._send_cdp("Page.reload", {"ignoreCache": ignore_cache})
            if self.on_status_changed:
                self.on_status_changed("🔄 已命令浏览器刷新页面，正在重新抓取请求...")

    def wait_for_round_settle(self, timeout_sec: float = 5.0, quiet_window_ms: int = 150) -> bool:
        """智能等待当前轮次的所有在途网络请求完成 (Network Idle)
        
        特点:
        1. 只要当前轮次发出的所有接口数据全部返回，立即收敛完成，绝不多等 1 毫秒（保证极致压测效率）；
        2. 若接口处理缓慢，会耐心等待其返回（最长至 timeout_sec），彻底解决接口处于 Pending 状态的问题；
        3. 结合小静默窗口 (quiet_window_ms)，防止接口链式异步调用被误判中断。
        """
        start = time.perf_counter()
        time.sleep(0.12)  # 给浏览器下发指令并启动首批网络请求预留基础缓冲

        quiet_start = None
        while time.perf_counter() - start < timeout_sec:
            if not self.is_running() or not self._ws:
                break

            with self._in_flight_lock:
                pending_count = len(self._in_flight_reqs)

            if pending_count == 0:
                if quiet_start is None:
                    quiet_start = time.perf_counter()
                elif (time.perf_counter() - quiet_start) * 1000.0 >= quiet_window_ms:
                    return True
            else:
                quiet_start = None

            time.sleep(0.04)

        # 超时后将依然处于 pending 的在途请求归因标记为超时
        with self._in_flight_lock:
            still_pending = list(self._in_flight_reqs)
            self._in_flight_reqs.clear()

        with self._req_lock:
            for req_id in still_pending:
                r = self._requests.get(req_id)
                if r and r.status_code == 0:
                    r.error = "请求超时 (Pending Timeout)"
                    r.status_text = "Timeout"
                    r.elapsed_ms = round(timeout_sec * 1000.0, 2)

        return False

    def get_browser_cookies(self, url: Optional[str] = None) -> Dict[str, str]:
        """从真实浏览器会话中提取全量有效 Cookie（包含 HttpOnly 会话凭据与 Session ID）"""
        if not self.is_running() or not self._ws:
            return {}
        cmd_id = self._id_counter
        self._id_counter += 1
        params = {}
        if url:
            params["urls"] = [url]
        try:
            self._ws.send_json({
                "id": cmd_id,
                "method": "Network.getCookies",
                "params": params,
            })
            start = time.time()
            while time.time() - start < 1.5:
                msg = self._ws.recv_json(timeout=0.2)
                if msg and msg.get("id") == cmd_id:
                    cookies_list = msg.get("result", {}).get("cookies", [])
                    res = {}
                    for c in cookies_list:
                        name = c.get("name")
                        val = c.get("value")
                        if name:
                            res[name] = val or ""
                    return res
        except Exception:
            pass
        return {}

    def navigate_to(self, url: str):
        """命令浏览器跳转到新页面"""
        if self.is_running() and self._ws and url:
            self._send_cdp("Page.navigate", {"url": url})

    def fetch_response_body(self, request_id: str) -> str:
        """从 CDP 获取指定请求的完整响应体"""
        if not self.is_running() or not self._ws:
            return ""
        req_cmd_id = self._id_counter
        self._id_counter += 1
        try:
            self._ws.send_json({
                "id": req_cmd_id,
                "method": "Network.getResponseBody",
                "params": {"requestId": request_id}
            })
            start = time.time()
            while time.time() - start < 2.0:
                msg = self._ws.recv_json(timeout=0.2)
                if msg and msg.get("id") == req_cmd_id:
                    result = msg.get("result", {})
                    body = result.get("body", "")
                    if result.get("base64Encoded", False):
                        try:
                            body = base64.b64decode(body).decode("utf-8", errors="replace")
                        except Exception:
                            pass
                    with self._req_lock:
                        if request_id in self._requests:
                            self._requests[request_id].response_body = body
                    return body
        except Exception:
            pass
        return ""

    def stop(self):
        """停止录制并彻底关闭浏览器与全部子进程"""
        self._is_running = False
        BrowserSnifferController._active_controllers.discard(self)

        # 1. 优先通过 Browser Target 发送 Browser.close 命令优雅退出
        if self._port > 0:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/json/version", timeout=0.8) as resp:
                    v_data = json.loads(resp.read().decode("utf-8"))
                    browser_ws_url = v_data.get("webSocketDebuggerUrl")
                    if browser_ws_url:
                        b_ws = SimpleWebSocketClient(browser_ws_url, timeout=1.0)
                        b_ws.send_json({"id": 999999, "method": "Browser.close"})
                        time.sleep(0.15)
                        b_ws.close()
            except Exception:
                pass

        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

        # 2. 彻底销毁进程及其全部衍生子进程树（避免 Windows 下 Edge/Chrome 悬挂后台窗口）
        if self._proc:
            pid = self._proc.pid
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    self._proc.terminate()
                    self._proc.wait(timeout=1.0)
            except Exception:
                pass
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

        # 3. 兜底扫描：若仍有以此临时目录为 user-data-dir 的浏览器残余进程，予以强制清理
        if sys.platform == "win32" and self._temp_dir:
            try:
                safe_dir = self._temp_dir.replace("\\", "\\\\")
                subprocess.run(
                    ["wmic", "process", "where", f"CommandLine like '%{safe_dir}%'", "call", "terminate"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass

        self._cleanup()
        if self.on_status_changed:
            self.on_status_changed("⚪ 嗅探已停止，浏览器已关闭")

    def _cleanup(self):
        if self._temp_dir and os.path.exists(self._temp_dir):
            time.sleep(0.3)
            try:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except Exception:
                pass
            self._temp_dir = None

    def _send_cdp(self, method: str, params: Optional[dict] = None):
        if not self._ws:
            return
        cmd_id = self._id_counter
        self._id_counter += 1
        msg = {"id": cmd_id, "method": method}
        if params:
            msg["params"] = params
        try:
            self._ws.send_json(msg)
        except Exception:
            pass

    def _reconnect_active_target(self) -> bool:
        """探测并重连浏览器当前活跃的页面 target（应对跨域导航、新建标签页或断线重连）"""
        if not self._port or not self._is_running:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/json", timeout=1.0) as resp:
                targets = json.loads(resp.read().decode("utf-8"))
            # 优先寻找最新 page 类型目标
            page_target = next((t for t in targets if t.get("type") == "page" and "webSocketDebuggerUrl" in t), None)
            if page_target and "webSocketDebuggerUrl" in page_target:
                ws_url = page_target["webSocketDebuggerUrl"]
                if self._ws:
                    try:
                        self._ws.close()
                    except Exception:
                        pass
                self._ws = SimpleWebSocketClient(ws_url, timeout=3.0)
                # 重新启用 Network 和 Page 域并开启跨页面自动挂接
                self._send_cdp("Network.enable", {"maxPostDataSize": 65536})
                self._send_cdp("Page.enable")
                self._send_cdp("Target.setAutoAttach", {
                    "autoAttach": True,
                    "waitForDebuggerOnStart": False,
                    "flatten": True
                })
                return True
        except Exception:
            pass
        return False

    def _cdp_listener_loop(self):
        """后台轮询解析 CDP 事件（具备自愈与断线自动重连能力）"""
        while self._is_running:
            if not self._ws or not self._ws.sock:
                reconnected = self._reconnect_active_target()
                if not reconnected:
                    time.sleep(0.3)
                    continue

            try:
                msg = self._ws.recv_json(timeout=0.2)
            except ConnectionError:
                # 发生断开，尝试关闭旧连接并在下一轮重连活跃页面
                if self._ws:
                    self._ws.close()
                time.sleep(0.1)
                continue
            except Exception:
                continue

            if not msg:
                continue

            method = msg.get("method", "")
            params = msg.get("params", {})

            if method == "Network.requestWillBeSent":
                req_id = params.get("requestId", "")
                req_obj = params.get("request", {})
                req_type = params.get("type", "Other")
                url = req_obj.get("url", "")
                if not url or url.startswith("about:") or url.startswith("data:"):
                    continue

                http_method = req_obj.get("method", "GET").upper()

                lower_url = url.lower()
                is_api = (
                    req_type in ["XHR", "Fetch", "Document", "Ping"]
                    or http_method not in ["GET", "HEAD"]
                    or "?" in url
                    or any(k in lower_url for k in [
                        "/api/", "/v1/", "/v2/", "/v3/", "/ajax/", "/service/", "/services/",
                        "/rest/", "/data/", "/query/", "/auth/", "/login", "/user",
                        ".json", ".xml", ".action", ".do", ".jsp", ".php"
                    ])
                )

                post_data = req_obj.get("postData", "")

                if req_type not in ("WebSocket", "EventSource"):
                    with self._in_flight_lock:
                        self._in_flight_reqs.add(req_id)

                captured = CapturedRequest(
                    request_id=req_id,
                    method=http_method,
                    url=url,
                    headers=dict(req_obj.get("headers", {})),
                    post_data=post_data,
                    resource_type=req_type,
                    timestamp=params.get("wallTime", time.time()),
                    start_time=params.get("timestamp", time.time()),
                    is_api=is_api,
                )

                with self._req_lock:
                    self._requests[req_id] = captured

                if self.on_request_captured:
                    try:
                        self.on_request_captured(captured)
                    except Exception:
                        pass

            elif method == "Network.requestWillBeSentExtraInfo":
                req_id = params.get("requestId", "")
                extra_headers = params.get("headers", {})
                if req_id and extra_headers:
                    with self._req_lock:
                        req = self._requests.get(req_id)
                        if req:
                            req.headers.update(extra_headers)
                    if req and self.on_request_updated:
                        try:
                            self.on_request_updated(req)
                        except Exception:
                            pass

            elif method == "Network.responseReceived":
                req_id = params.get("requestId", "")
                resp_obj = params.get("response", {})
                status = resp_obj.get("status", 0)
                mime = resp_obj.get("mimeType", "")
                resp_time = params.get("timestamp", 0.0)

                with self._req_lock:
                    req = self._requests.get(req_id)
                    if req:
                        req.status_code = status
                        req.status_text = resp_obj.get("statusText", "")
                        req.response_headers = resp_obj.get("headers", {})
                        req.mime_type = mime
                        if "json" in mime.lower() or "xml" in mime.lower():
                            req.is_api = True
                        if resp_time > 0 and req.start_time > 0:
                            req.elapsed_ms = round((resp_time - req.start_time) * 1000.0, 2)

                if req and self.on_request_updated:
                    try:
                        self.on_request_updated(req)
                    except Exception:
                        pass

            elif method == "Network.loadingFinished":
                req_id = params.get("requestId", "")
                data_len = params.get("encodedDataLength", 0)
                fin_time = params.get("timestamp", 0.0)

                with self._in_flight_lock:
                    self._in_flight_reqs.discard(req_id)

                with self._req_lock:
                    req = self._requests.get(req_id)
                    if req:
                        req.size_bytes = data_len
                        if fin_time > 0 and req.start_time > 0 and req.elapsed_ms <= 0:
                            req.elapsed_ms = round((fin_time - req.start_time) * 1000.0, 2)

                if req and self.on_request_updated:
                    try:
                        self.on_request_updated(req)
                    except Exception:
                        pass

            elif method == "Network.loadingFailed":
                req_id = params.get("requestId", "")
                err_text = params.get("errorText", "加载失败")

                with self._in_flight_lock:
                    self._in_flight_reqs.discard(req_id)

                with self._req_lock:
                    req = self._requests.get(req_id)
                    if req:
                        req.error = err_text

                if req and self.on_request_updated:
                    try:
                        self.on_request_updated(req)
                    except Exception:
                        pass


atexit.register(BrowserSnifferController.stop_all)
