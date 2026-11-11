"""页面接口智能嗅探与健康巡检面板 (支持真实浏览器动态录制、全页面事务级并发压测与图表分析报告导出)"""

import json
import time
from typing import Dict, List, Optional, Any

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QGroupBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QFrame,
    QSplitter, QSpinBox, QTextEdit, QGridLayout, QCheckBox,
    QComboBox, QTabWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QGuiApplication, QFont

from app.config.themes import ThemeManager, get_method_color
from app.core.go_engine import GoEngineManager
from app.core.models import SavedRequest
from app.core.browser_sniffer import (
    BrowserSnifferController, CapturedRequest, detect_browser_executable
)


class BrowserSnifferSignalBridge(QObject):
    """跨线程 Qt 信号桥接器 (从 CDP WebSocket 接收线程安全传递至主 UI 线程)"""
    request_captured = pyqtSignal(object)
    request_updated = pyqtSignal(object)
    status_changed = pyqtSignal(str)


class SnifferWorker(QThread):
    """后台单次页面静态代码扫描工作线程"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, target_url: str, headers: dict = None, cookies: dict = None, proxy_url: str = ""):
        super().__init__()
        self.target_url = target_url
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.proxy_url = proxy_url

    def run(self):
        try:
            engine = GoEngineManager.get_instance()
            result = engine.scan_page(
                self.target_url,
                headers=self.headers,
                cookies=self.cookies,
                proxy_url=self.proxy_url,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class PageStressWorker(QThread):
    """后台全页面及所有接口并发事务压测工作线程"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, config: dict):
        super().__init__()
        self.config = config

    def run(self):
        try:
            engine = GoEngineManager.get_instance()
            result = engine.stress_page(self.config)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class BrowserMultiRoundStressWorker(QThread):
    """真机多轮页面刷新嗅探与并发压测工作线程"""
    round_progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, browser_ctrl: BrowserSnifferController, config: dict):
        super().__init__()
        self.browser_ctrl = browser_ctrl
        self.config = config
        self._cancelled = False
        self._page_durations: List[float] = []

    def cancel(self):
        self._cancelled = True

    def run(self):
        url = self.config["target_url"]
        total_rounds = self.config.get("total_rounds", 20)
        concurrency = self.config.get("concurrency", 5)
        delay_ms = self.config.get("delay_ms", 50)
        timeout_ms = self.config.get("timeout_ms", 5000)
        headers = self.config.get("headers", {})
        cookies = self.config.get("cookies", {})
        headless = self.config.get("headless", False)

        try:
            from app.config.settings import Settings
            from app.core.proxy_manager import resolve_httpx_proxy
            proxy_cfg = Settings().proxy

            # 1. 启动或复用真机浏览器并连接 CDP (注入代理配置)
            if not self.browser_ctrl.is_running():
                self.round_progress.emit(1, total_rounds, f"正在启动真实浏览器并连接网络监听... [第 1/{total_rounds} 轮]")
                t_start = time.perf_counter()
                self.browser_ctrl.start(
                    url=url,
                    headless=headless,
                    headers=headers,
                    cookies=cookies,
                    proxy_cfg=proxy_cfg,
                )
                self.browser_ctrl.wait_for_round_settle(timeout_sec=timeout_ms / 1000.0)
                dur1 = (time.perf_counter() - t_start) * 1000.0
                self._page_durations.append(dur1)
            else:
                self.round_progress.emit(1, total_rounds, f"复用当前登录浏览器，正在执行第 1/{total_rounds} 轮嗅探...")
                t_start = time.perf_counter()
                self.browser_ctrl.reload_page(ignore_cache=True)
                self.browser_ctrl.wait_for_round_settle(timeout_sec=timeout_ms / 1000.0)
                dur1 = (time.perf_counter() - t_start) * 1000.0
                self._page_durations.append(dur1)

            reqs_so_far = len(self.browser_ctrl.get_requests())
            self.round_progress.emit(1, total_rounds, f"第 1/{total_rounds} 轮完成，已截获 {reqs_so_far} 个接口请求")

            # 2. 自动化多轮页面刷新 (从第 2 轮至第 total_rounds 轮)
            for r in range(2, total_rounds + 1):
                if self._cancelled or not self.browser_ctrl.is_running():
                    break

                if delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)

                t_reload_start = time.perf_counter()
                self.round_progress.emit(r, total_rounds, f"正在进行第 {r}/{total_rounds} 轮页面刷新嗅探... [已完成 {r-1} 轮]")
                self.browser_ctrl.reload_page(ignore_cache=True)

                # 等待当前轮次页面全部异步网络请求返回完成 (智能在途请求收敛，杜绝 pending 状态)
                self.browser_ctrl.wait_for_round_settle(timeout_sec=timeout_ms / 1000.0)
                dur_r = (time.perf_counter() - t_reload_start) * 1000.0
                self._page_durations.append(dur_r)

                cur_reqs = len(self.browser_ctrl.get_requests())
                self.round_progress.emit(r, total_rounds, f"第 {r}/{total_rounds} 轮完成，已累计监听 {cur_reqs} 个接口请求")

            # 3. 若配置了并发用户数 (> 1 协程)，且截获到了有效 API 接口，协同 Go 原生协程池压测引擎
            go_result = None
            captured_requests = self.browser_ctrl.get_requests()
            api_endpoints = self._extract_api_endpoints(captured_requests, url)

            # 提取浏览器最新全量有效 Cookie（包含会话 Session 及 HttpOnly 凭据）
            live_cookies = {}
            if self.browser_ctrl and self.browser_ctrl.is_running():
                live_cookies = self.browser_ctrl.get_browser_cookies(url)
            merged_cookies = dict(cookies)
            if live_cookies:
                merged_cookies.update(live_cookies)

            proxy_url, _ = resolve_httpx_proxy(proxy_cfg, url)

            if concurrency > 1 and api_endpoints and not self._cancelled:
                self.round_progress.emit(total_rounds, total_rounds, f"正在协同 Go 协程引擎并发施压 ({concurrency} 协程)...")
                try:
                    from app.core.go_engine import GoEngineManager
                    engine = GoEngineManager.get_instance()
                    go_cfg = {
                        "target_url": url,
                        "endpoints": api_endpoints,
                        "concurrency": concurrency,
                        "total_requests": total_rounds,
                        "delay_ms": delay_ms,
                        "timeout_ms": timeout_ms,
                        "headers": headers,
                        "cookies": merged_cookies,
                        "proxy_url": proxy_url or "",
                    }
                    go_result = engine.stress_page(go_cfg)
                except Exception:
                    pass

            # 4. 聚合真机多轮捕获与并发压测指标，生成结构化压测报告
            if not self._cancelled:
                # 4. 聚合真机多轮捕获与并发压测指标，生成结构化压测报告
                stress_result = self._aggregate_results(captured_requests, go_result, total_rounds, url)
                self.finished.emit(stress_result)

        except Exception as e:
            self.error.emit(str(e))

    def _wait_for_page_settle(self, timeout_sec: float = 3.0):
        """等待当前轮次页面网络请求处于稳定状态"""
        start = time.perf_counter()
        min_wait = min(0.6, timeout_sec * 0.3)
        last_count = len(self.browser_ctrl.get_requests())
        stable_ticks = 0
        while time.perf_counter() - start < timeout_sec:
            if self._cancelled or not self.browser_ctrl.is_running():
                break
            time.sleep(0.08)
            elapsed = time.perf_counter() - start
            if elapsed < min_wait:
                last_count = len(self.browser_ctrl.get_requests())
                continue
            cur_count = len(self.browser_ctrl.get_requests())
            if cur_count == last_count:
                stable_ticks += 1
                if stable_ticks >= 4:
                    break
            else:
                last_count = cur_count
                stable_ticks = 0

    def _extract_api_endpoints(self, captured: List[CapturedRequest], base_url: str) -> List[dict]:
        """从捕获列表中提取出 API 接口去重列表，完整保留所有参数、请求头、Session 及 Cookie"""
        live_cookies = {}
        if self.browser_ctrl and self.browser_ctrl.is_running():
            try:
                live_cookies = self.browser_ctrl.get_browser_cookies(base_url)
            except Exception:
                pass

        seen = set()
        endpoints = []
        for req in captured:
            if not req.is_api:
                continue
            key = (req.method.upper(), req.url.split("?")[0])
            if key not in seen:
                seen.add(key)
                merged_headers = dict(req.headers)

                # 确保会话 Cookie 完整注入：若单请求未捕获到 Cookie，从真机浏览器会话提取补齐
                has_cookie = any(k.lower() == "cookie" for k in merged_headers)
                if not has_cookie and live_cookies:
                    c_str = "; ".join(f"{k}={v}" for k, v in live_cookies.items() if k and v)
                    if c_str:
                        merged_headers["Cookie"] = c_str

                endpoints.append({
                    "method": req.method.upper(),
                    "url": req.url,  # 完整保留 query params
                    "path": req.url.split("?")[0],
                    "body": req.post_data,  # 完整保留 POST/PUT 载荷
                    "headers": merged_headers,  # 完整保留 Authorization, token, session, CSRF 等头
                    "is_api": True,
                })
        if not endpoints and base_url:
            base_headers = {}
            if live_cookies:
                c_str = "; ".join(f"{k}={v}" for k, v in live_cookies.items() if k and v)
                if c_str:
                    base_headers["Cookie"] = c_str
            endpoints.append({
                "method": "GET",
                "url": base_url,
                "path": "/",
                "body": "",
                "headers": base_headers,
                "is_api": True,
            })
        return endpoints

    def _aggregate_results(self, captured: List[CapturedRequest], go_result: Optional[dict], total_rounds: int, url: str) -> dict:
        """聚合多轮请求样本数据，构建与 PageStressResult 完全兼容的报告结构"""
        # 如果 Go 引擎压测成功且包含丰富的报告，优先基于 Go 引擎并融合真机页面指标
        if go_result and go_result.get("endpoint_reports"):
            if self._page_durations:
                avg_page_load = sum(self._page_durations) / len(self._page_durations)
                go_result["avg_page_load_duration_ms"] = round(avg_page_load, 2)
            return go_result

        # 纯真机多轮捕获聚合统计
        api_reqs = [r for r in captured if r.is_api]
        target_reqs = api_reqs if api_reqs else captured

        completed_rounds = max(len(self._page_durations), 1)
        avg_page_load = (sum(self._page_durations) / completed_rounds) if self._page_durations else 0.0
        total_time_sec = (sum(self._page_durations) / 1000.0) if self._page_durations else 1.0

        if not target_reqs:
            return {
                "target_url": url,
                "total_endpoints": 0,
                "total_requests": 0,
                "success_count": 0,
                "error_count": 0,
                "timeout_count": 0,
                "avg_latency_ms": 0.0,
                "elapsed_sec": round(total_time_sec, 2),
                "overall_tps": 0.0,
                "total_page_iterations": completed_rounds,
                "successful_page_iterations": 0,
                "page_success_rate": 0.0,
                "avg_page_load_duration_ms": round(avg_page_load, 2),
                "page_rps": 0.0,
                "endpoint_reports": [],
                "records": [],
            }

        ep_map: Dict[tuple, List[CapturedRequest]] = {}
        for req in target_reqs:
            key = (req.method.upper(), req.url.split("?")[0])
            ep_map.setdefault(key, []).append(req)

        endpoint_reports = []
        all_records = []
        total_api_requests = 0
        total_api_success = 0
        total_api_error = 0
        latency_sum = 0.0

        for (method, path), reqs in ep_map.items():
            sample_count = len(reqs)
            total_api_requests += sample_count
            latencies = [r.elapsed_ms for r in reqs if r.elapsed_ms > 0]
            if not latencies:
                latencies = [40.0]

            succ_cnt = sum(1 for r in reqs if 200 <= r.status_code < 400 and not r.error)
            err_cnt = sample_count - succ_cnt
            total_api_success += succ_cnt
            total_api_error += err_cnt

            avg_lat = sum(latencies) / len(latencies)
            latency_sum += sum(latencies)
            min_lat = min(latencies)
            max_lat = max(latencies)

            sorted_lats = sorted(latencies)
            p90 = sorted_lats[int(len(sorted_lats) * 0.9)] if sorted_lats else avg_lat
            p99 = sorted_lats[int(len(sorted_lats) * 0.99)] if sorted_lats else max_lat

            err_rate = round(err_cnt / sample_count * 100.0, 1) if sample_count > 0 else 0.0
            succ_rate = round(100.0 - err_rate, 1)

            bins = {
                "<50ms": sum(1 for l in latencies if l < 50),
                "50-200ms": sum(1 for l in latencies if 50 <= l < 200),
                "200-500ms": sum(1 for l in latencies if 200 <= l < 500),
                ">500ms": sum(1 for l in latencies if l >= 500),
            }

            status_dist = {}
            for r in reqs:
                code_k = str(r.status_code) if r.status_code > 0 else "0"
                status_dist[code_k] = status_dist.get(code_k, 0) + 1

            tips = []
            if err_rate > 5.0:
                tips.append(f"接口错误率较高 ({err_rate}%)，建议核查服务端异常日志")
            if avg_lat > 500.0:
                tips.append(f"接口平均响应耗时较长 ({avg_lat:.1f}ms)，建议优化后台处理或引入缓存")
            if p99 > 1000.0:
                tips.append(f"存在长尾延迟 (P99 达 {p99:.1f}ms)，部分请求等待过久")
            if not tips:
                tips.append("接口多轮嗅探表现稳定，响应延迟正常。")

            rep_records = [
                {
                    "request_id": r.request_id,
                    "method": r.method,
                    "url": r.url,
                    "status_code": r.status_code,
                    "elapsed_ms": r.elapsed_ms,
                    "error": r.error,
                    "timestamp": r.timestamp,
                    "request_headers": r.headers if isinstance(r.headers, dict) else {},
                    "request_body": r.post_data or "",
                    "response_headers": r.response_headers if isinstance(r.response_headers, dict) else {},
                    "response_body": r.response_body or "",
                }
                for r in reqs
            ]
            all_records.extend(rep_records)

            endpoint_reports.append({
                "method": method,
                "url": reqs[0].url,
                "path": path,
                "total_requests": sample_count,
                "success_count": succ_cnt,
                "error_count": err_cnt,
                "timeout_count": 0,
                "timeout_rate": 0.0,
                "avg_latency_ms": round(avg_lat, 2),
                "min_latency_ms": round(min_lat, 2),
                "max_latency_ms": round(max_lat, 2),
                "p90_latency_ms": round(p90, 2),
                "p99_latency_ms": round(p99, 2),
                "error_rate": err_rate,
                "success_rate": succ_rate,
                "qps": round(sample_count / max(total_time_sec, 0.1), 1),
                "latency_bins": bins,
                "status_code_dist": status_dist,
                "diagnosis_tips": tips,
                "records": rep_records,
            })

        page_rps = round(completed_rounds / max(total_time_sec, 0.1), 2)
        overall_succ_rate = round(total_api_success / max(total_api_requests, 1) * 100.0, 1)

        return {
            "target_url": url,
            "total_endpoints": len(endpoint_reports),
            "total_requests": total_api_requests,
            "success_count": total_api_success,
            "error_count": total_api_error,
            "timeout_count": 0,
            "avg_latency_ms": round(latency_sum / max(total_api_requests, 1), 2),
            "elapsed_sec": round(total_time_sec, 2),
            "overall_tps": round(total_api_requests / max(total_time_sec, 0.1), 2),
            "qps": round(total_api_requests / max(total_time_sec, 0.1), 2),
            "throughput_rps": round(total_api_requests / max(total_time_sec, 0.1), 2),
            "page_tps": page_rps,
            "total_page_iterations": completed_rounds,
            "successful_page_iterations": completed_rounds if total_api_error == 0 else int(completed_rounds * (overall_succ_rate / 100.0)),
            "page_success_rate": overall_succ_rate,
            "avg_page_load_duration_ms": round(avg_page_load, 2),
            "page_rps": page_rps,
            "endpoint_reports": endpoint_reports,
            "records": all_records,
        }


class PageSnifferDialog(QDialog):
    """页面接口智能嗅探与健康巡检对话框（含真实浏览器动态抓包录制与全页面事务并发压测）"""

    import_request_requested = pyqtSignal(object)  # SavedRequest

    def __init__(self, target_url: str = "", parent=None):
        if isinstance(target_url, QWidget):
            parent, target_url = target_url, ""
        super().__init__(parent)
        self._worker = None
        self._endpoints = []
        self._reports_map = {}  # url -> report dict
        self._selected_ep = None
        self._last_page_stress_records = []
        self._last_page_stress_result: Optional[dict] = None
        self._multi_round_worker: Optional[BrowserMultiRoundStressWorker] = None
        self._is_sniffing: bool = False

        # 真机动态嗅探引擎控制器与桥接
        self._browser_ctrl = BrowserSnifferController()
        self._bridge = BrowserSnifferSignalBridge()
        self._bridge.request_captured.connect(self._on_browser_request_captured)
        self._bridge.request_updated.connect(self._on_browser_request_updated)
        self._bridge.status_changed.connect(self._on_browser_status_changed)

        self._browser_ctrl.on_request_captured = self._bridge.request_captured.emit
        self._browser_ctrl.on_request_updated = self._bridge.request_updated.emit
        self._browser_ctrl.on_status_changed = self._bridge.status_changed.emit

        self._captured_requests: List[CapturedRequest] = []
        self._captured_requests_map: Dict[str, CapturedRequest] = {}

        self.setWindowTitle("页面接口智能嗅探与全链路事务压测")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(1180, 800)
        self.setMinimumSize(980, 660)
        self._init_ui(target_url or "https://example.com")
        self._apply_theme()
        self._update_auth_status_label()

    def done(self, r):
        """确保窗口关闭或结束时（无论是 Esc、右上角还是代码调用）均彻底清理真机浏览器进程与后台线程"""
        if hasattr(self, "_multi_round_worker") and self._multi_round_worker and self._multi_round_worker.isRunning():
            self._multi_round_worker.cancel()
            self._multi_round_worker.quit()
            self._multi_round_worker.wait(1000)
            self._multi_round_worker = None
        if hasattr(self, "_browser_ctrl"):
            self._browser_ctrl.stop()
        super().done(r)

    def closeEvent(self, event):
        if hasattr(self, "_multi_round_worker") and self._multi_round_worker and self._multi_round_worker.isRunning():
            self._multi_round_worker.cancel()
            self._multi_round_worker.quit()
            self._multi_round_worker.wait(1000)
            self._multi_round_worker = None
        if hasattr(self, "_browser_ctrl"):
            self._browser_ctrl.stop()
        super().closeEvent(event)

    def _init_ui(self, default_url: str):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # ─── 1. 顶部控制栏 (URL 输入与真机/压测控制) ─────────────────
        cfg_frame = QFrame()
        cfg_frame.setObjectName("configFrame")
        cfg_frame.setFrameShape(QFrame.Shape.StyledPanel)
        cfg_vbox = QVBoxLayout(cfg_frame)
        cfg_vbox.setContentsMargins(12, 10, 12, 10)
        cfg_vbox.setSpacing(8)

        # 第一行：目标 URL + 核心动作按钮
        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        lbl_url = QLabel("目标 Web 页面 URL:")
        lbl_url.setStyleSheet("font-weight: 500;")
        url_row.addWidget(lbl_url)

        self.edit_url = QLineEdit(default_url)
        self.edit_url.setPlaceholderText("https://example.com 或内网系统登录页")
        self.edit_url.setStyleSheet("font-family: Consolas, Monaco, monospace; font-size: 13px;")
        self.edit_url.textChanged.connect(self._update_auth_status_label)
        url_row.addWidget(self.edit_url, 1)

        # 1.1 调起真机浏览器
        self.btn_browser_sniff = QPushButton("🚀 调起真机浏览器")
        self.btn_browser_sniff.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browser_sniff.setFixedHeight(34)
        self.btn_browser_sniff.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border-radius: 6px;
                padding: 0 14px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton:pressed { background-color: #1e40af; }
            QPushButton:disabled { background-color: #9ca3af; }
        """)
        self.btn_browser_sniff.setToolTip("调起真实 Edge/Chrome 窗口并注入全局请求头与 Cookie，支持在浏览器中手动登录、输入验证码与导航")
        self.btn_browser_sniff.clicked.connect(self._on_toggle_browser_sniff)
        url_row.addWidget(self.btn_browser_sniff)

        # 1.2 开始多轮嗅探压测 (支持随时启动多轮刷新与并发报告)
        self.btn_start_multi_round = QPushButton("▶ 开始嗅探压测")
        self.btn_start_multi_round.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start_multi_round.setFixedHeight(34)
        self.btn_start_multi_round.setEnabled(True)
        self.btn_start_multi_round.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border-radius: 6px;
                padding: 0 14px;
            }
            QPushButton:hover { background-color: #047857; }
            QPushButton:pressed { background-color: #065f46; }
            QPushButton:disabled { background-color: #e2e8f0; color: #94a3b8; }
        """)
        self.btn_start_multi_round.setToolTip("在浏览器中完成登录并进入目标页面后，点击此按钮开始自动化多轮刷新并统计所有接口性能，避免未登录时页面死循环刷新")
        self.btn_start_multi_round.clicked.connect(self._on_start_multi_round_sniff)
        url_row.addWidget(self.btn_start_multi_round)

        # 1.3 刷新页面重新触发请求
        self.btn_browser_reload = QPushButton("🔄 刷新页面")
        self.btn_browser_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browser_reload.setFixedHeight(34)
        self.btn_browser_reload.setEnabled(False)
        self.btn_browser_reload.setStyleSheet("""
            QPushButton {
                background-color: #0284c7;
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                border-radius: 6px;
                padding: 0 10px;
            }
            QPushButton:hover { background-color: #0369a1; }
            QPushButton:pressed { background-color: #075985; }
            QPushButton:disabled { background-color: #e2e8f0; color: #94a3b8; }
        """)
        self.btn_browser_reload.setToolTip("向浏览器下发强制无缓存刷新指令，重新发起页面全量 JS 请求")
        self.btn_browser_reload.clicked.connect(self._on_browser_reload)
        url_row.addWidget(self.btn_browser_reload)

        # 1.4 停止嗅探 / 关闭浏览器
        self.btn_browser_stop = QPushButton("🛑 停止嗅探")
        self.btn_browser_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browser_stop.setFixedHeight(34)
        self.btn_browser_stop.setEnabled(False)
        self.btn_browser_stop.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                border-radius: 6px;
                padding: 0 10px;
            }
            QPushButton:hover { background-color: #b91c1c; }
            QPushButton:pressed { background-color: #991b1b; }
            QPushButton:disabled { background-color: #e2e8f0; color: #94a3b8; }
        """)
        self.btn_browser_stop.clicked.connect(self._on_browser_stop)
        url_row.addWidget(self.btn_browser_stop)

        # 1.5 最小化窗口按钮
        self.btn_minimize = QPushButton("🗕 最小化")
        self.btn_minimize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_minimize.setFixedHeight(34)
        self.btn_minimize.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #475569;
                font-weight: 500;
                font-size: 12px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 0 10px;
            }
            QPushButton:hover { background-color: #e2e8f0; color: #1e293b; }
            QPushButton:pressed { background-color: #cbd5e1; }
        """)
        self.btn_minimize.setToolTip("最小化嗅探窗口至任务栏，方便在主窗口中调试接口")
        self.btn_minimize.clicked.connect(self.showMinimized)
        url_row.addWidget(self.btn_minimize)

        cfg_vbox.addLayout(url_row)

        # 第二行：多轮自动化压测参数配置 + 全页面压测与扫描 (独立成行，避免与过滤和无头选项挤压重叠)
        param_row = QHBoxLayout()
        param_row.setSpacing(10)

        # 自动多轮刷新嗅探并压测开关
        self.chk_auto_multi_round = QCheckBox("自动多轮刷新与压测")
        self.chk_auto_multi_round.setChecked(True)
        self.chk_auto_multi_round.setStyleSheet("color: #2563eb; font-weight: bold; font-size: 12px;")
        self.chk_auto_multi_round.setToolTip("开启后，点击【开始嗅探压测】将根据配置的轮次自动刷新页面并生成压测大盘报告")
        param_row.addWidget(self.chk_auto_multi_round)

        # 压测轮次与并发配置
        param_row.addWidget(QLabel("计划轮次:"))
        self.spin_requests = QSpinBox()
        self.spin_requests.setRange(1, 500)
        self.spin_requests.setValue(20)
        self.spin_requests.setSuffix(" 轮")
        self.spin_requests.setFixedWidth(75)
        param_row.addWidget(self.spin_requests)

        param_row.addWidget(QLabel("并发用户:"))
        self.spin_concurrency = QSpinBox()
        self.spin_concurrency.setRange(1, 50)
        self.spin_concurrency.setValue(5)
        self.spin_concurrency.setSuffix(" 协程")
        self.spin_concurrency.setFixedWidth(80)
        param_row.addWidget(self.spin_concurrency)

        param_row.addWidget(QLabel("请求间隔:"))
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(0, 2000)
        self.spin_delay.setSingleStep(20)
        self.spin_delay.setValue(50)
        self.spin_delay.setSuffix(" ms")
        self.spin_delay.setFixedWidth(75)
        param_row.addWidget(self.spin_delay)

        param_row.addWidget(QLabel("超时:"))
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(1, 30)
        self.spin_timeout.setValue(5)
        self.spin_timeout.setSuffix(" s")
        self.spin_timeout.setFixedWidth(65)
        param_row.addWidget(self.spin_timeout)

        # 后台无头模式
        self.chk_browser_headless = QCheckBox("后台静默执行 (无头模式)")
        self.chk_browser_headless.setToolTip("勾选后不弹出可视化浏览器窗口，在后台静默加载并拦截请求")
        param_row.addWidget(self.chk_browser_headless)

        param_row.addStretch()

        # 2.1 全页面全接口并发压测 (事务模型)
        self.btn_stress = QPushButton("⚡ 全页面并发压测")
        self.btn_stress.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stress.setFixedHeight(28)
        self.btn_stress.setStyleSheet("""
            QPushButton {
                background-color: #0d9488;
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                border-radius: 5px;
                padding: 0 12px;
            }
            QPushButton:hover { background-color: #0f766e; }
            QPushButton:disabled { background-color: #9ca3af; }
        """)
        self.btn_stress.setToolTip("将捕获到的所有真实接口交由 Go 协程引擎并发回放压测。所有接口皆成功才算一次页面成功，严格统计页面加载时长与慢接口排行")
        self.btn_stress.clicked.connect(self._on_start_page_stress)
        param_row.addWidget(self.btn_stress)

        # 2.2 静态扫描兜底
        self.btn_scan = QPushButton("🔍 静态扫描")
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.setFixedHeight(28)
        self.btn_scan.setStyleSheet("""
            QPushButton {
                background-color: #64748b;
                color: #ffffff;
                font-weight: 500;
                font-size: 12px;
                border-radius: 5px;
                padding: 0 10px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_scan.setToolTip("轻量离线启发式分析 HTML 与 JS 代码词法路由（无需调起浏览器）")
        self.btn_scan.clicked.connect(self._on_start_scan)
        param_row.addWidget(self.btn_scan)

        cfg_vbox.addLayout(param_row)

        # 第三行：过滤展示、全局请求头与 Cookie 联动指示 + 结果大盘进入按钮 + 清空按钮
        auth_row = QHBoxLayout()
        auth_row.setSpacing(10)

        # 过滤类型选择
        auth_row.addWidget(QLabel("展示类型:"))
        self.combo_type_filter = QComboBox()
        self.combo_type_filter.addItems(["仅展示 API 接口 (Fetch / XHR / POST)", "展示全部网络请求 (含资源)"])
        self.combo_type_filter.setFixedWidth(210)
        self.combo_type_filter.currentIndexChanged.connect(self._on_filter_type_changed)
        auth_row.addWidget(self.combo_type_filter)

        self.chk_carry_auth = QCheckBox("自动携带全局请求头与匹配 Cookie")
        self.chk_carry_auth.setChecked(True)
        self.chk_carry_auth.setStyleSheet("font-size: 12px; font-weight: 500;")
        self.chk_carry_auth.toggled.connect(self._update_auth_status_label)
        auth_row.addWidget(self.chk_carry_auth)

        self.lbl_auth_tip = QLabel("")
        self.lbl_auth_tip.setStyleSheet("font-size: 11px; color: #15803d; font-weight: bold;")
        auth_row.addWidget(self.lbl_auth_tip)

        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet("color: #6b7280; font-size: 12px; font-weight: 500;")
        auth_row.addWidget(self.lbl_status)

        auth_row.addStretch()

        # 清空记录
        self.btn_clear_captured = QPushButton("🧹 清空列表")
        self.btn_clear_captured.setFixedHeight(28)
        self.btn_clear_captured.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self.btn_clear_captured.clicked.connect(self._on_clear_captured)
        auth_row.addWidget(self.btn_clear_captured)

        self.btn_page_records = QPushButton("📋 全页面压测明细与图表 (支持导出)")
        self.btn_page_records.setFixedHeight(28)
        self.btn_page_records.setEnabled(False)
        self.btn_page_records.setStyleSheet("font-size: 11px; font-weight: bold; padding: 2px 12px; color: #2563eb;")
        self.btn_page_records.clicked.connect(self._on_view_all_page_records)
        auth_row.addWidget(self.btn_page_records)

        cfg_vbox.addLayout(auth_row)
        main_layout.addWidget(cfg_frame)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # ─── 2. 主内容区：左右分栏 QSplitter ─────────────────────────
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)

        # ─── 2.1 左侧面板：汇总卡片 + 接口大盘列表 ──────────────────
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(8)

        # 聚合指标大盘卡片
        m_layout = QHBoxLayout()
        m_layout.setSpacing(8)
        self.card_total = self._create_card("嗅探接口总数", "0", "#2563eb")
        self.card_healthy = self._create_card("页面整体成功率", "- %", "#15803d")
        self.card_avg_lat = self._create_card("平均请求时间", "- ms", "#b45309")
        self.card_errors = self._create_card("吞吐量 (TPS / QPS)", "- /s", "#0284c7")

        m_layout.addWidget(self.card_total["widget"])
        m_layout.addWidget(self.card_healthy["widget"])
        m_layout.addWidget(self.card_avg_lat["widget"])
        m_layout.addWidget(self.card_errors["widget"])
        left_layout.addLayout(m_layout)

        # 接口表格
        table_group = QGroupBox("捕获接口清单 (点击任意请求行查看完整报文与深度报告)")
        t_layout = QVBoxLayout(table_group)
        t_layout.setContentsMargins(6, 8, 6, 6)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Method", "API Endpoint URL", "类型 / 轮次", "耗时 (ms)", "状态", "大小 / 详情", "操作"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(50)
        header.setStretchLastSection(False)
        self.table.setColumnWidth(0, 75)   # Method
        self.table.setColumnWidth(1, 380)  # API Endpoint URL (宽敞清晰，边界可自由拖动调节)
        self.table.setColumnWidth(2, 90)   # 类型 / 轮次
        self.table.setColumnWidth(3, 85)   # 耗时
        self.table.setColumnWidth(4, 90)   # 状态
        self.table.setColumnWidth(5, 95)   # 大小 / 详情
        self.table.setColumnWidth(6, 260)  # 操作列 (调试, cURL, 压测, 明细)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        self.table.itemClicked.connect(self._on_table_item_clicked)
        self.table.currentCellChanged.connect(self._on_table_cell_changed)
        t_layout.addWidget(self.table)

        left_layout.addWidget(table_group)
        self.splitter.addWidget(left_widget)

        # ─── 2.2 右侧面板：选中接口专属深度检查器与报告 ───────────────
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(8)

        self.detail_group = QGroupBox("接口深度检查器与压测看板")
        d_layout = QVBoxLayout(self.detail_group)
        d_layout.setContentsMargins(10, 10, 10, 10)
        d_layout.setSpacing(8)

        # 标题栏：选中的 Method Badge + URL + 动作
        d_header = QHBoxLayout()
        self.lbl_det_method = QLabel("GET")
        self.lbl_det_method.setStyleSheet("""
            background-color: #10b981;
            color: #ffffff;
            font-weight: bold;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 4px;
        """)
        d_header.addWidget(self.lbl_det_method)

        self.lbl_det_url = QLabel("请从左侧列表选择一个接口")
        self.lbl_det_url.setStyleSheet("font-size: 12px; font-weight: bold; color: #1f2937;")
        self.lbl_det_url.setWordWrap(True)
        d_header.addWidget(self.lbl_det_url, 1)

        self.btn_copy_url = QPushButton("复制 URL")
        self.btn_copy_url.setFixedHeight(26)
        self.btn_copy_url.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        self.btn_copy_url.clicked.connect(self._on_copy_selected_url)
        d_header.addWidget(self.btn_copy_url)

        self.btn_fetch_resp_body = QPushButton("查看响应体")
        self.btn_fetch_resp_body.setFixedHeight(26)
        self.btn_fetch_resp_body.setStyleSheet("font-size: 11px; padding: 2px 8px; color: #0284c7;")
        self.btn_fetch_resp_body.clicked.connect(self._on_fetch_response_body)
        d_header.addWidget(self.btn_fetch_resp_body)

        d_layout.addLayout(d_header)

        # 详情分页 Tab (指标看板 / 请求头与Payload / 响应数据)
        self.tab_details = QTabWidget()

        # Tab 1: 📊 压测指标与延迟分布
        tab_perf = QWidget()
        tp_layout = QVBoxLayout(tab_perf)
        tp_layout.setContentsMargins(4, 6, 4, 4)
        tp_layout.setSpacing(6)

        grid = QGridLayout()
        grid.setSpacing(6)
        self.card_det_avg = self._create_card("平均请求时间", "- ms", "#2563eb")
        self.card_det_timeout = self._create_card("超时率 (%)", "0.0%", "#b45309")
        self.card_det_error = self._create_card("错误率 (%)", "0.0%", "#b91c1c")
        self.card_det_qps = self._create_card("吞吐量 (QPS / TPS)", "- /s", "#059669")
        self.card_det_p90 = self._create_card("P90 / P99 延迟", "- / -", "#4f46e5")
        self.card_det_counts = self._create_card("状态统计", "成功: 0 / 失败: 0", "#374151")

        grid.addWidget(self.card_det_avg["widget"], 0, 0)
        grid.addWidget(self.card_det_timeout["widget"], 0, 1)
        grid.addWidget(self.card_det_error["widget"], 0, 2)
        grid.addWidget(self.card_det_qps["widget"], 1, 0)
        grid.addWidget(self.card_det_p90["widget"], 1, 1)
        grid.addWidget(self.card_det_counts["widget"], 1, 2)
        tp_layout.addLayout(grid)

        # 延迟区间与状态码
        bins_frame = QFrame()
        bins_frame.setStyleSheet("border: 1px solid #e5e7eb; border-radius: 6px; background-color: #fafafa; padding: 6px;")
        b_vbox = QVBoxLayout(bins_frame)
        b_vbox.setContentsMargins(6, 4, 6, 4)
        b_vbox.addWidget(QLabel("<b>响应延迟阶梯分布:</b>"))
        self.lbl_bins = QLabel("<50ms: -  |  50-200ms: -  |  200-500ms: -  |  >500ms: -")
        self.lbl_bins.setStyleSheet("font-size: 11px; color: #4b5563;")
        b_vbox.addWidget(self.lbl_bins)
        tp_layout.addWidget(bins_frame)

        self.lbl_codes = QLabel("状态码分布: -")
        self.lbl_codes.setStyleSheet("font-size: 11px; color: #4b5563;")
        tp_layout.addWidget(self.lbl_codes)

        # 智能诊断文本
        self.txt_tips = QTextEdit()
        self.txt_tips.setReadOnly(True)
        self.txt_tips.setMaximumHeight(80)
        self.txt_tips.setStyleSheet("font-size: 11px; background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 4px;")
        self.txt_tips.setPlaceholderText("接口健康诊断与建议将在此展示...")
        tp_layout.addWidget(self.txt_tips)

        self.tab_details.addTab(tab_perf, "📊 性能指标与分布")

        # Tab 2: 📤 请求头与 Payload
        tab_req = QWidget()
        tr_layout = QVBoxLayout(tab_req)
        tr_layout.setContentsMargins(4, 6, 4, 4)
        tr_layout.addWidget(QLabel("<b>请求数据体 (Payload / Body):</b>"))
        self.txt_req_body = QTextEdit()
        self.txt_req_body.setReadOnly(True)
        self.txt_req_body.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; background: #fafafa;")
        self.txt_req_body.setPlaceholderText("无 POST/PUT 请求体")
        tr_layout.addWidget(self.txt_req_body, 1)

        tr_layout.addWidget(QLabel("<b>请求头 (Request Headers):</b>"))
        self.txt_req_headers = QTextEdit()
        self.txt_req_headers.setReadOnly(True)
        self.txt_req_headers.setMaximumHeight(110)
        self.txt_req_headers.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; background: #fafafa;")
        tr_layout.addWidget(self.txt_req_headers)

        self.tab_details.addTab(tab_req, "📤 请求报文 (Payload)")

        # Tab 3: 📥 响应头与响应体
        tab_resp = QWidget()
        tresp_layout = QVBoxLayout(tab_resp)
        tresp_layout.setContentsMargins(4, 6, 4, 4)
        tresp_layout.addWidget(QLabel("<b>响应内容 (Response Body):</b>"))
        self.txt_resp_body = QTextEdit()
        self.txt_resp_body.setReadOnly(True)
        self.txt_resp_body.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; background: #fafafa;")
        self.txt_resp_body.setPlaceholderText("点击右上角【查看响应体】懒加载实际响应内容...")
        tresp_layout.addWidget(self.txt_resp_body, 1)

        tresp_layout.addWidget(QLabel("<b>响应头 (Response Headers):</b>"))
        self.txt_resp_headers = QTextEdit()
        self.txt_resp_headers.setReadOnly(True)
        self.txt_resp_headers.setMaximumHeight(100)
        self.txt_resp_headers.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; background: #fafafa;")
        tresp_layout.addWidget(self.txt_resp_headers)

        self.tab_details.addTab(tab_resp, "📥 响应数据 (Response)")

        d_layout.addWidget(self.tab_details, 1)

        # 底部操作栏
        d_actions = QHBoxLayout()
        d_actions.setSpacing(8)

        self.btn_det_import = QPushButton("📥 导入调试")
        self.btn_det_import.setEnabled(False)
        self.btn_det_import.setFixedHeight(30)
        self.btn_det_import.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                font-weight: bold;
                border-radius: 4px;
                padding: 0 12px;
            }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:disabled { background-color: #cbd5e1; }
        """)
        self.btn_det_import.clicked.connect(self._on_import_current_selection)
        d_actions.addWidget(self.btn_det_import)

        self.btn_det_copy_curl = QPushButton("📋 复制 cURL")
        self.btn_det_copy_curl.setFixedHeight(30)
        self.btn_det_copy_curl.clicked.connect(self._on_copy_curl)
        d_actions.addWidget(self.btn_det_copy_curl)

        self.btn_det_stress = QPushButton("⚡ 单独压测")
        self.btn_det_stress.setEnabled(False)
        self.btn_det_stress.setFixedHeight(30)
        self.btn_det_stress.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: #ffffff;
                font-weight: bold;
                border-radius: 4px;
                padding: 0 12px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #cbd5e1; }
        """)
        self.btn_det_stress.clicked.connect(self._on_stress_current_selection)
        d_actions.addWidget(self.btn_det_stress)

        self.btn_det_records = QPushButton("📋 压测明细与图表")
        self.btn_det_records.setEnabled(False)
        self.btn_det_records.setFixedHeight(30)
        self.btn_det_records.clicked.connect(self._on_view_selected_records)
        d_actions.addWidget(self.btn_det_records)

        d_layout.addLayout(d_actions)
        right_layout.addWidget(self.detail_group)
        self.splitter.addWidget(right_widget)

        self.splitter.setSizes([720, 460])
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        main_layout.addWidget(self.splitter, 1)

    def _create_card(self, title: str, default_val: str, color_hex: str) -> dict:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 4px;
            }}
        """)
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(6, 4, 6, 4)
        vbox.setSpacing(2)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: 500;")
        vbox.addWidget(lbl_t)

        lbl_v = QLabel(default_val)
        lbl_v.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color_hex};")
        vbox.addWidget(lbl_v)

        return {"widget": card, "title": lbl_t, "val": lbl_v}

    def _apply_theme(self):
        t = ThemeManager.current()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.bg_primary};
                color: {t.text_primary};
            }}
            #configFrame {{
                background-color: {t.bg_secondary};
                border: 1px solid {t.border};
                border-radius: 8px;
            }}
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {t.border};
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                color: {t.text_secondary};
            }}
            QTableWidget {{
                background-color: {t.bg_input};
                color: {t.text_primary};
                border: 1px solid {t.border_light};
                gridline-color: {t.border_light};
            }}
            QHeaderView::section {{
                background-color: {t.header_bg};
                color: {t.header_text};
                padding: 4px 6px;
                border: none;
                border-right: 1px solid {t.border_light};
                border-bottom: 1px solid {t.border_light};
                font-weight: bold;
            }}
            QSplitter::handle:horizontal {{
                background-color: {t.border_light};
                width: 8px;
                margin: 2px 0px;
                border-radius: 4px;
            }}
            QSplitter::handle:horizontal:hover {{
                background-color: #3b82f6;
            }}
            QSplitter::handle:horizontal:pressed {{
                background-color: #1d4ed8;
            }}
        """)

    # ─── 真机动态嗅探与交互流程 ─────────────────────────────────

    def _on_toggle_browser_sniff(self):
        """调起真实浏览器进行环境就绪与抓包监听（用户可从容登录、输入验证码）"""
        if self._browser_ctrl.is_running():
            return

        url = self.edit_url.text().strip()
        if not url:
            QMessageBox.warning(self, "警告", "请输入要嗅探的目标页面 URL")
            return

        if not url.startswith("http://") and not url.startswith("https://"):
            url = "http://" + url
            self.edit_url.setText(url)

        headers, cookies = ({}, {})
        if self.chk_carry_auth.isChecked():
            headers, cookies = self._get_auth_headers_and_cookies(url)

        headless = self.chk_browser_headless.isChecked()

        self._on_clear_captured()
        self.progress_bar.setRange(0, 0)
        self.lbl_status.setText("正在启动真机浏览器并连接 CDP 网络监听...")
        self.lbl_status.setStyleSheet("color: #2563eb; font-weight: bold; font-size: 12px;")

        try:
            from app.config.settings import Settings
            self._browser_ctrl.start(
                url=url,
                headless=headless,
                headers=headers,
                cookies=cookies,
                proxy_cfg=Settings().proxy,
            )
            self._is_sniffing = True
            self.btn_browser_sniff.setText("🌐 浏览器运行中")
            self.btn_browser_sniff.setEnabled(False)
            self.btn_start_multi_round.setEnabled(True)
            self.btn_browser_reload.setEnabled(True)
            self.btn_browser_stop.setEnabled(True)
            self.btn_scan.setEnabled(False)
            self.btn_stress.setEnabled(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
            self.lbl_status.setText("🟢 浏览器已就绪！可在浏览器中登录系统，进入目标页面后点击【▶ 开始嗅探压测】")
            self.lbl_status.setStyleSheet("color: #16a34a; font-weight: bold; font-size: 12px;")
        except Exception as e:
            self._on_browser_stop()
            QMessageBox.critical(self, "启动浏览器失败", str(e))

    def _on_start_multi_round_sniff(self):
        """开始或停止多轮自动化刷新嗅探压测（解决登录态系统被死循环刷新无法输入的问题）"""
        if self._multi_round_worker and self._multi_round_worker.isRunning():
            self._multi_round_worker.cancel()
            self._multi_round_worker.quit()
            self._multi_round_worker.wait(1000)
            self._multi_round_worker = None
            self.btn_start_multi_round.setText("▶ 开始嗅探压测")
            self.btn_start_multi_round.setStyleSheet("""
                QPushButton {
                    background-color: #059669;
                    color: #ffffff;
                    font-weight: bold;
                    font-size: 13px;
                    border-radius: 6px;
                    padding: 0 14px;
                }
                QPushButton:hover { background-color: #047857; }
                QPushButton:pressed { background-color: #065f46; }
            """)
            self.lbl_status.setText("已停止多轮压测，浏览器保持运行中（可随时再次点击开始）")
            self.lbl_status.setStyleSheet("color: #6b7280; font-size: 12px;")
            return

        url = self.edit_url.text().strip()
        if not url:
            QMessageBox.warning(self, "警告", "请输入要嗅探的目标页面 URL")
            return

        if not url.startswith("http://") and not url.startswith("https://"):
            url = "http://" + url
            self.edit_url.setText(url)

        headers, cookies = ({}, {})
        if self.chk_carry_auth.isChecked():
            headers, cookies = self._get_auth_headers_and_cookies(url)

        headless = self.chk_browser_headless.isChecked()
        total_rounds = self.spin_requests.value()
        concurrency = self.spin_concurrency.value()
        delay_ms = self.spin_delay.value()
        timeout_ms = self.spin_timeout.value() * 1000

        # 如果浏览器尚未启动，自动启动浏览器并开始嗅探
        if not self._browser_ctrl.is_running():
            try:
                from app.config.settings import Settings
                self._browser_ctrl.start(
                    url=url,
                    headless=headless,
                    headers=headers,
                    cookies=cookies,
                    proxy_cfg=Settings().proxy,
                )
            except Exception as e:
                QMessageBox.critical(self, "启动浏览器失败", str(e))
                return

        self._is_sniffing = True
        self.btn_browser_sniff.setText("🌐 浏览器运行中")
        self.btn_browser_sniff.setEnabled(False)
        self.btn_start_multi_round.setText("🛑 停止多轮压测")
        self.btn_start_multi_round.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border-radius: 6px;
                padding: 0 14px;
            }
            QPushButton:hover { background-color: #b91c1c; }
            QPushButton:pressed { background-color: #991b1b; }
        """)
        self.btn_browser_reload.setEnabled(True)
        self.btn_browser_stop.setEnabled(True)
        self.btn_scan.setEnabled(False)
        self.btn_stress.setEnabled(False)

        self.progress_bar.setRange(0, total_rounds)
        self.progress_bar.setValue(0)
        self.lbl_status.setText(f"🚀 正在执行多轮自动化刷新压测 (计划 {total_rounds} 轮，并发 {concurrency} 协程)...")
        self.lbl_status.setStyleSheet("color: #2563eb; font-weight: bold; font-size: 12px;")

        config = {
            "target_url": url,
            "total_rounds": total_rounds,
            "concurrency": concurrency,
            "delay_ms": delay_ms,
            "timeout_ms": timeout_ms,
            "headers": headers,
            "cookies": cookies,
            "headless": headless,
        }
        self._multi_round_worker = BrowserMultiRoundStressWorker(self._browser_ctrl, config)
        self._multi_round_worker.round_progress.connect(self._on_multi_round_progress)
        self._multi_round_worker.finished.connect(self._on_multi_round_finished)
        self._multi_round_worker.error.connect(self._on_multi_round_error)
        self._multi_round_worker.start()

    def _on_multi_round_progress(self, cur_round: int, total_rounds: int, msg: str):
        self.progress_bar.setRange(0, total_rounds)
        self.progress_bar.setValue(cur_round)
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #2563eb; font-weight: bold; font-size: 12px;")

    def _on_multi_round_finished(self, result: dict):
        self._is_sniffing = False
        self.btn_start_multi_round.setText("▶ 开始嗅探压测")
        self.btn_start_multi_round.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border-radius: 6px;
                padding: 0 14px;
            }
            QPushButton:hover { background-color: #047857; }
            QPushButton:pressed { background-color: #065f46; }
        """)
        self.btn_start_multi_round.setEnabled(True)
        self.btn_browser_sniff.setEnabled(not self._browser_ctrl.is_running())
        self.btn_browser_reload.setEnabled(self._browser_ctrl.is_running())
        self.btn_browser_stop.setEnabled(self._browser_ctrl.is_running())
        self.btn_scan.setEnabled(True)
        self.btn_stress.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.lbl_status.setText("🟢 真机多轮嗅探与全页面压测完成，报告已生成！")
        self.lbl_status.setStyleSheet("color: #16a34a; font-weight: bold; font-size: 12px;")
        self._on_page_stress_finished(result)

    def _on_multi_round_error(self, err_msg: str):
        self._on_browser_stop()
        QMessageBox.critical(self, "真机多轮嗅探异常", f"执行多轮嗅探压测时发生错误:\n{err_msg}")

    def _on_browser_reload(self):
        """命令浏览器刷新当前页面，重新触发 JS 请求"""
        if self._browser_ctrl.is_running():
            self._browser_ctrl.reload_page(ignore_cache=True)
            self.lbl_status.setText("🔄 已命令浏览器刷新页面，重新捕获全量请求中...")

    def _on_browser_stop(self):
        """停止真机嗅探及多轮压测，安全关闭浏览器"""
        self._is_sniffing = False
        if self._multi_round_worker and self._multi_round_worker.isRunning():
            self._multi_round_worker.cancel()
            self._multi_round_worker.quit()
            self._multi_round_worker.wait(1500)
            self._multi_round_worker = None

        if self._browser_ctrl.is_running():
            self._browser_ctrl.stop()

        self.btn_browser_sniff.setText("🚀 调起真机浏览器")
        self.btn_browser_sniff.setEnabled(True)
        self.btn_browser_sniff.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border-radius: 6px;
                padding: 0 14px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton:pressed { background-color: #1e40af; }
            QPushButton:disabled { background-color: #9ca3af; }
        """)
        self.btn_start_multi_round.setText("▶ 开始嗅探压测")
        self.btn_start_multi_round.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border-radius: 6px;
                padding: 0 14px;
            }
            QPushButton:hover { background-color: #047857; }
            QPushButton:pressed { background-color: #065f46; }
        """)
        self.btn_start_multi_round.setEnabled(True)
        self.btn_browser_reload.setEnabled(False)
        self.btn_browser_stop.setEnabled(False)
        self.btn_scan.setEnabled(True)
        self.btn_stress.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.lbl_status.setText("嗅探已停止，浏览器已安全关闭")
        self.lbl_status.setStyleSheet("color: #6b7280; font-size: 12px;")

    def _on_clear_captured(self):
        """清空当前抓包记录与控制器缓存"""
        self._captured_requests.clear()
        self._captured_requests_map.clear()
        self._endpoints.clear()
        self._reports_map.clear()
        if hasattr(self, "_browser_ctrl") and self._browser_ctrl:
            self._browser_ctrl.clear_requests()
        self.table.setRowCount(0)
        self.card_total["val"].setText("0")
        self.card_healthy["val"].setText("- %")
        self.card_avg_lat["val"].setText("- ms")
        self.card_errors["val"].setText("- /s")
        self._selected_ep = None
        self.lbl_det_url.setText("请从左侧列表选择一个接口")
        self.txt_req_body.clear()
        self.txt_req_headers.clear()
        self.txt_resp_body.clear()
        self.txt_resp_headers.clear()

    def _on_filter_type_changed(self):
        """重新过滤渲染列表"""
        self._rerender_captured_table()

    def _on_browser_request_captured(self, req: CapturedRequest):
        """CDP 捕获到新请求回调"""
        self._captured_requests.append(req)
        self._captured_requests_map[req.request_id] = req

        ep = {
            "method": req.method,
            "url": req.url,
            "path": req.url.split("?")[0],
            "body": req.post_data,
            "headers": req.headers,
            "latency_ms": req.elapsed_ms,
            "status_code": req.status_code,
            "status_type": "healthy" if 200 <= req.status_code < 400 else ("warning" if req.status_code == 0 else "critical"),
            "is_api": req.is_api,
            "request_id": req.request_id,
            "resource_type": req.resource_type,
        }
        self._endpoints.append(ep)

        # 默认聚合报告框架
        self._reports_map[req.url] = {
            "method": req.method,
            "url": req.url,
            "path": ep["path"],
            "total_requests": 1,
            "success_count": 1 if 200 <= req.status_code < 400 else 0,
            "error_count": 1 if req.status_code >= 400 or req.error else 0,
            "timeout_count": 0,
            "avg_latency_ms": req.elapsed_ms,
            "records": [
                {
                    "index": len(self._endpoints),
                    "offset_ms": 0,
                    "method": req.method,
                    "url": req.url,
                    "status_code": req.status_code,
                    "elapsed_ms": req.elapsed_ms,
                    "size_bytes": req.size_bytes,
                    "error": req.error,
                    "request_headers": req.headers if isinstance(req.headers, dict) else {},
                    "request_body": req.post_data or "",
                    "response_headers": req.response_headers if isinstance(req.response_headers, dict) else {},
                    "response_body": req.response_body or "",
                }
            ],
        }

        only_api = self.combo_type_filter.currentIndex() == 0
        if only_api and not req.is_api:
            self._update_cards_summary()
            return

        self._append_table_row(ep)
        self._update_cards_summary()

    def _on_browser_request_updated(self, req: CapturedRequest):
        """CDP 接收到响应或加载完成时更新行（支持动态将识别出的 API 补入表格，并同步更新凭证请求头）"""
        self._captured_requests_map[req.request_id] = req

        target_ep = None
        for ep in self._endpoints:
            if ep.get("request_id") == req.request_id:
                ep["latency_ms"] = req.elapsed_ms
                ep["status_code"] = req.status_code
                ep["size_bytes"] = req.size_bytes
                ep["status_type"] = "healthy" if 200 <= req.status_code < 400 else "critical"
                ep["is_api"] = req.is_api
                if req.headers:
                    ep["headers"] = dict(req.headers)
                target_ep = ep
                break

        # 更新表格中的单元格或动态补充新增 API 行
        found_in_table = False
        for row in range(self.table.rowCount()):
            item_url = self.table.item(row, 1)
            if item_url and item_url.toolTip() == req.url:
                found_in_table = True
                # 耗时
                lat_item = self.table.item(row, 3)
                if lat_item and req.elapsed_ms > 0:
                    lat_item.setText(f"{req.elapsed_ms:.1f} ms")

                # 状态码
                stat_item = self.table.item(row, 4)
                if stat_item and req.status_code > 0:
                    stat_item.setText(f"HTTP {req.status_code}")
                    stat_item.setForeground(QColor("#16a34a" if 200 <= req.status_code < 400 else "#dc2626"))

                # 大小 / 错误
                info_item = self.table.item(row, 5)
                if info_item:
                    if req.error:
                        info_item.setText(f"❌ {req.error}")
                        info_item.setForeground(QColor("#dc2626"))
                    elif req.size_bytes > 0:
                        size_str = f"{req.size_bytes / 1024.0:.1f} KB" if req.size_bytes >= 1024 else f"{req.size_bytes} B"
                        info_item.setText(size_str)
                break

        only_api = self.combo_type_filter.currentIndex() == 0
        if not found_in_table and target_ep:
            if not only_api or target_ep.get("is_api", True):
                self._append_table_row(target_ep)
                self._update_cards_summary()

        # 同步更新聚合报告中该接口的初始采样记录
        if req.url in self._reports_map and self._reports_map[req.url].get("records"):
            rec = self._reports_map[req.url]["records"][0]
            rec["status_code"] = req.status_code
            rec["elapsed_ms"] = req.elapsed_ms
            rec["size_bytes"] = req.size_bytes
            rec["error"] = req.error
            if req.headers:
                rec["request_headers"] = dict(req.headers)
            if req.post_data:
                rec["request_body"] = req.post_data
            if req.response_headers:
                rec["response_headers"] = dict(req.response_headers)
            if req.response_body:
                rec["response_body"] = req.response_body

        # 若当前正好在查看该接口，同步刷新右侧详情
        if self._selected_ep and self._selected_ep.get("request_id") == req.request_id:
            self._show_endpoint_detail(self._selected_ep, self._reports_map.get(req.url))

    def _on_browser_status_changed(self, status: str):
        self.lbl_status.setText(status)

    def _update_cards_summary(self):
        api_count = sum(1 for e in self._endpoints if e.get("is_api", True))
        total_count = len(self._endpoints)
        self.card_total["val"].setText(f"{api_count} API / {total_count} 总请求")

    def _rerender_captured_table(self):
        self.table.setRowCount(0)
        only_api = self.combo_type_filter.currentIndex() == 0
        for ep in self._endpoints:
            if only_api and not ep.get("is_api", True):
                continue
            self._append_table_row(ep)

    def _append_table_row(self, ep: dict):
        row = self.table.rowCount()
        self.table.insertRow(row)

        method = ep.get("method", "GET")
        m_color = get_method_color(method)
        m_item = QTableWidgetItem(f" {method} ")
        m_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        m_item.setForeground(QColor("#ffffff"))
        m_item.setBackground(QColor(m_color))
        self.table.setItem(row, 0, m_item)

        url = ep.get("url", "")
        url_item = QTableWidgetItem(ep.get("path") or url)
        url_item.setToolTip(url)
        self.table.setItem(row, 1, url_item)

        type_str = ep.get("resource_type", "API")
        type_item = QTableWidgetItem(type_str)
        type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 2, type_item)

        lat = ep.get("latency_ms", 0.0)
        lat_item = QTableWidgetItem(f"{lat:.1f} ms" if lat > 0 else "-")
        lat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 3, lat_item)

        code = ep.get("status_code", 0)
        code_item = QTableWidgetItem(f"HTTP {code}" if code > 0 else "Pending")
        code_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if code > 0:
            code_item.setForeground(QColor("#16a34a" if 200 <= code < 400 else "#dc2626"))
        self.table.setItem(row, 4, code_item)

        size = ep.get("size_bytes", 0)
        size_str = f"{size / 1024.0:.1f} KB" if size >= 1024 else (f"{size} B" if size > 0 else "-")
        info_item = QTableWidgetItem(size_str)
        info_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 5, info_item)

        action_widget = self._create_row_actions(ep)
        self.table.setCellWidget(row, 6, action_widget)

    # ─── 单次静态扫描流程 (兜底) ────────────────────────────────

    def _on_start_scan(self):
        url = self.edit_url.text().strip()
        if not url:
            QMessageBox.warning(self, "警告", "请输入要嗅探的目标页面 URL")
            return

        headers, cookies = ({}, {})
        if self.chk_carry_auth.isChecked():
            headers, cookies = self._get_auth_headers_and_cookies(url)

        from app.config.settings import Settings
        from app.core.proxy_manager import resolve_httpx_proxy
        proxy_url, _ = resolve_httpx_proxy(Settings().proxy, url)

        self._set_busy(True, "正在探测页面并静态分析后端 API...")
        self.table.setRowCount(0)
        self._endpoints = []
        self._reports_map = {}
        self._last_page_stress_records = []
        self.btn_page_records.setEnabled(False)

        self._worker = SnifferWorker(url, headers, cookies, proxy_url=proxy_url or "")
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.error.connect(self._on_task_error)
        self._worker.start()

    def _on_scan_finished(self, result: dict):
        self._set_busy(False, "静态扫描完成")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        endpoints = result.get("endpoints", [])
        self._endpoints = endpoints
        self.table.setRowCount(0)
        for ep in endpoints:
            ep["is_api"] = True
            self._append_table_row(ep)

        total = len(endpoints)
        healthy = result.get("healthy_count", 0)
        self.card_total["val"].setText(str(total))
        self.card_healthy["val"].setText(str(healthy))
        self.card_avg_lat["val"].setText(f"{result.get('elapsed_ms', 0):.0f} ms")

        if len(endpoints) > 0:
            self.table.selectRow(0)
            self._show_endpoint_detail(endpoints[0], None)

    # ─── 全页面全接口高并发压测流程 (事务模型) ─────────────────

    def _on_start_page_stress(self):
        url = self.edit_url.text().strip()
        if not url:
            QMessageBox.warning(self, "警告", "请输入要压测的目标页面 URL")
            return

        total_reqs = self.spin_requests.value()
        concurrency = self.spin_concurrency.value()
        delay_ms = self.spin_delay.value()
        timeout_ms = self.spin_timeout.value() * 1000

        headers, cookies = ({}, {})
        if self.chk_carry_auth.isChecked():
            headers, cookies = self._get_auth_headers_and_cookies(url)

        # 提取真机浏览器最新 Cookie 会话凭据与 Session，并解析当前代理策略
        from app.config.settings import Settings
        from app.core.proxy_manager import resolve_httpx_proxy

        proxy_cfg = Settings().proxy
        proxy_url, _ = resolve_httpx_proxy(proxy_cfg, url)

        merged_cookies = dict(cookies)
        if self._browser_ctrl and self._browser_ctrl.is_running():
            try:
                b_cookies = self._browser_ctrl.get_browser_cookies(url)
                if b_cookies:
                    merged_cookies.update(b_cookies)
            except Exception:
                pass

        # 严格基于当前已捕获的接口清单列表发起压测，完整保留每一个接口的所有参数、请求头、Session 及 Cookie
        raw_list = [e for e in self._endpoints if e.get("is_api", True)]
        if not raw_list:
            raw_list = list(self._endpoints)

        seen_keys = set()
        cleaned_endpoints = []
        for ep in raw_list:
            m = ep.get("method", "GET").upper()
            u = ep.get("url", "")
            if not u:
                continue
            key = (m, u)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            # 完整保留并补齐所有请求头、Session、Token 及 Cookie
            ep_headers = dict(ep.get("headers") or {})
            req_id = ep.get("request_id")
            if req_id and req_id in self._captured_requests_map:
                cap_req = self._captured_requests_map[req_id]
                if cap_req.headers:
                    ep_headers.update(cap_req.headers)

            # 如果请求头中没有 Cookie 字段，但真机浏览器已持有 Cookie，则自动注入完整的 Cookie 头
            has_cookie = any(k.lower() == "cookie" for k in ep_headers)
            if not has_cookie and merged_cookies:
                cookie_str = "; ".join(f"{k}={v}" for k, v in merged_cookies.items() if k and v)
                if cookie_str:
                    ep_headers["Cookie"] = cookie_str

            body = ep.get("body") or ""
            if not body and req_id and req_id in self._captured_requests_map:
                body = self._captured_requests_map[req_id].post_data or ""

            cleaned_endpoints.append({
                "method": m,
                "url": u,
                "path": ep.get("path") or u.split("?")[0],
                "body": body,
                "headers": ep_headers,
                "is_api": True,
            })

        if not cleaned_endpoints:
            QMessageBox.warning(self, "警告", "当前捕获列表中尚无有效接口，请先在真机浏览器中浏览或刷新页面以捕获接口")
            return

        config = {
            "target_url": url,
            "endpoints": cleaned_endpoints,
            "concurrency": concurrency,
            "total_requests": total_reqs,
            "delay_ms": delay_ms,
            "timeout_ms": timeout_ms,
            "headers": headers,
            "cookies": merged_cookies,
            "proxy_url": proxy_url or "",
        }

        self._set_busy(True, f"正在执行全页面事务级并发压测 (计划 {total_reqs} 轮，并发 {concurrency} 协程)...")
        self.progress_bar.setRange(0, 0)

        self._worker = PageStressWorker(config)
        self._worker.finished.connect(self._on_page_stress_finished)
        self._worker.error.connect(self._on_task_error)
        self._worker.start()

    def _on_page_stress_finished(self, result: dict):
        self._set_busy(False, "全页面事务压测完成")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        self._last_page_stress_result = result
        reports = result.get("endpoint_reports", [])
        total_eps = result.get("total_endpoints", len(reports))

        # 新增事务级统计核心指标
        page_succ = result.get("page_success_rate", 0.0)
        avg_page_load = result.get("avg_page_load_duration_ms", 0.0)
        succ_iters = result.get("successful_page_iterations", 0)
        total_iters = result.get("total_page_iterations", 0)
        page_rps = result.get("page_rps", 0.0) or result.get("page_tps", 0.0)
        overall_tps = result.get("overall_tps", 0.0) or result.get("qps", 0.0)

        self.card_total["val"].setText(f"{total_eps} 接口")
        self.card_healthy["val"].setText(f"{page_succ:.1f}% ({succ_iters}/{total_iters})")
        self.card_healthy["title"].setText("页面整体成功率")
        self.card_avg_lat["val"].setText(f"{avg_page_load:.1f} ms")
        self.card_avg_lat["title"].setText("平均请求时间 (RTT)")
        self.card_errors["val"].setText(f"{page_rps:.1f} TPS ({overall_tps:.0f} QPS)" if overall_tps > 0 else f"{page_rps:.1f} TPS")
        self.card_errors["title"].setText("吞吐量 (TPS / QPS)")

        self._reports_map = {}
        for r in reports:
            self._reports_map[r.get("url", "")] = r

        all_page_recs = result.get("records") or []
        if not all_page_recs:
            for r in reports:
                all_page_recs.extend(r.get("records", []))
        self._last_page_stress_records = all_page_recs
        self.btn_page_records.setEnabled(bool(all_page_recs))

        # 刷新表格展示各接口详细压测报告
        self.table.setRowCount(len(reports))
        for row, r in enumerate(reports):
            ep_dict = {
                "method": r.get("method", "GET"),
                "url": r.get("url", ""),
                "path": r.get("path", ""),
                "is_api": True,
            }
            method = ep_dict["method"]
            m_color = get_method_color(method)
            m_item = QTableWidgetItem(f" {method} ")
            m_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            m_item.setForeground(QColor("#ffffff"))
            m_item.setBackground(QColor(m_color))
            self.table.setItem(row, 0, m_item)

            url_item = QTableWidgetItem(ep_dict.get("path") or ep_dict.get("url"))
            url_item.setToolTip(ep_dict.get("url"))
            self.table.setItem(row, 1, url_item)

            req_item = QTableWidgetItem(f"{r.get('total_requests', 0)} 轮")
            req_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, req_item)

            lat = r.get("avg_latency_ms", 0.0)
            lat_item = QTableWidgetItem(f"{lat:.1f} ms")
            lat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, lat_item)

            err_rate = r.get("error_rate", 0.0)
            status_str = f"成功 {r.get('success_rate', 0.0):.1f}%"
            stat_item = QTableWidgetItem(status_str)
            stat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            stat_item.setForeground(QColor("#16a34a" if err_rate == 0 else "#dc2626"))
            self.table.setItem(row, 4, stat_item)

            err_item = QTableWidgetItem(f"超时: {r.get('timeout_count', 0)} | 错误: {r.get('error_count', 0)}")
            err_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 5, err_item)

            action_widget = self._create_row_actions(ep_dict)
            self.table.setCellWidget(row, 6, action_widget)

        if len(reports) > 0:
            self.table.selectRow(0)
            self._show_endpoint_detail(reports[0], reports[0])

    # ─── 表格选中与详情联动 ─────────────────────────────────────

    def _on_table_item_clicked(self, item: QTableWidgetItem):
        self._select_row(item.row())

    def _on_table_cell_changed(self, current_row: int, current_col: int, prev_row: int, prev_col: int):
        if current_row >= 0:
            self._select_row(current_row)

    def _select_row(self, row: int):
        item_url = self.table.item(row, 1)
        if not item_url:
            return
        full_url = item_url.toolTip() or item_url.text()

        # 匹配对应 endpoint
        matched_ep = next((e for e in self._endpoints if e.get("url") == full_url), None)
        if not matched_ep:
            matched_ep = {"method": self.table.item(row, 0).text().strip(), "url": full_url}

        report = self._reports_map.get(full_url)
        self._show_endpoint_detail(matched_ep, report)

    def _show_endpoint_detail(self, ep: dict, report: dict = None):
        """将选中的接口报文与指标完整展现于右侧检查器"""
        self._selected_ep = ep
        self.btn_det_import.setEnabled(True)
        self.btn_det_stress.setEnabled(True)

        method = ep.get("method", "GET")
        url = ep.get("url", "")
        m_color = get_method_color(method)

        self.lbl_det_method.setText(method)
        self.lbl_det_method.setStyleSheet(f"background-color: {m_color}; color: #ffffff; font-weight: bold; font-size: 11px; padding: 2px 8px; border-radius: 4px;")
        self.lbl_det_url.setText(url)

        # 填充请求报文与参数
        body = ep.get("body", "") or ep.get("post_data", "")
        if body:
            try:
                parsed_json = json.loads(body)
                self.txt_req_body.setPlainText(json.dumps(parsed_json, ensure_ascii=False, indent=2))
            except Exception:
                self.txt_req_body.setPlainText(str(body))
        else:
            self.txt_req_body.setPlainText("（无 POST / PUT 请求体）")

        headers = ep.get("headers", {})
        if isinstance(headers, dict) and headers:
            h_lines = [f"{k}: {v}" for k, v in headers.items()]
            self.txt_req_headers.setPlainText("\n".join(h_lines))
        else:
            self.txt_req_headers.setPlainText("（无专属请求头）")

        # 填充响应数据
        req_id = ep.get("request_id")
        if req_id and req_id in self._captured_requests_map:
            cap_req = self._captured_requests_map[req_id]
            resp_headers = cap_req.response_headers
            if resp_headers:
                self.txt_resp_headers.setPlainText("\n".join([f"{k}: {v}" for k, v in resp_headers.items()]))
            else:
                self.txt_resp_headers.setPlainText("（无响应头）")

            if not cap_req.response_body and hasattr(self, "_browser_ctrl") and self._browser_ctrl.is_running():
                # 尝试自动拉取响应体
                try:
                    fetched_body = self._browser_ctrl.fetch_response_body(cap_req.request_id)
                    if fetched_body:
                        cap_req.response_body = fetched_body
                        ep["body"] = fetched_body
                except Exception:
                    pass

            if cap_req.response_body:
                try:
                    self.txt_resp_body.setPlainText(json.dumps(json.loads(cap_req.response_body), ensure_ascii=False, indent=2))
                except Exception:
                    self.txt_resp_body.setPlainText(cap_req.response_body)
            else:
                self.txt_resp_body.setPlainText("（无响应体或服务器未返回内容）")
        else:
            self.txt_resp_headers.setPlainText("（尚未捕获完整响应数据）")
            self.txt_resp_body.setPlainText("（尚未捕获完整响应数据）")

        # 填充压测性能指标
        if report:
            avg_ms = report.get("avg_latency_ms", 0.0)
            timeout_rate = report.get("timeout_rate", 0.0)
            error_rate = report.get("error_rate", 0.0)
            qps = report.get("qps", 0.0)
            p90 = report.get("p90_ms", 0.0)
            p99 = report.get("p99_ms", 0.0)
            success = report.get("success_count", 0)
            failed = report.get("error_count", 0)
            timed_out = report.get("timeout_count", 0)

            self.card_det_avg["val"].setText(f"{avg_ms:.1f} ms")
            self.card_det_timeout["val"].setText(f"{timeout_rate:.1f}%")
            self.card_det_error["val"].setText(f"{error_rate:.1f}%")
            self.card_det_qps["val"].setText(f"{qps:.1f} QPS/TPS")
            self.card_det_p90["val"].setText(f"{p90:.0f} / {p99:.0f} ms")
            self.card_det_counts["val"].setText(f"成:{success} 错:{failed} 超:{timed_out}")

            bins = report.get("latency_bins", {})
            self.lbl_bins.setText(
                f"<50ms: <b>{bins.get('<50ms', 0)}</b>  |  "
                f"50-200ms: <b>{bins.get('50-200ms', 0)}</b>  |  "
                f"200-500ms: <b>{bins.get('200-500ms', 0)}</b>  |  "
                f">500ms: <b>{bins.get('>500ms', 0)}</b>"
            )

            status_map = report.get("status_code_dist", {})
            if status_map:
                codes_str = "  ".join([f"HTTP {k}: <b>{v}次</b>" for k, v in sorted(status_map.items())])
            else:
                codes_str = "暂无状态码统计"
            self.lbl_codes.setText(codes_str)

            tips = report.get("diagnosis_tips", [])
            tips_text = "\n".join([f"• {t}" for t in tips]) if tips else "接口各项性能指标健康，未见明显瓶颈。"
            self.txt_tips.setPlainText(tips_text)
            self.btn_det_records.setEnabled(bool(report.get("records")))
        else:
            lat = ep.get("latency_ms", 0.0)
            code = ep.get("status_code", 0)
            self.card_det_avg["val"].setText(f"{lat:.1f} ms" if lat else "-")
            self.card_det_timeout["val"].setText("未压测")
            self.card_det_error["val"].setText("未压测")
            self.card_det_qps["val"].setText("-")
            self.card_det_p90["val"].setText("-")
            self.card_det_counts["val"].setText(f"单次状态: HTTP {code}")
            self.lbl_bins.setText("尚未针对此接口发起高并发多轮采样，请点击下方【单独压测】")
            self.lbl_codes.setText(f"捕获状态码: HTTP {code}")
            self.txt_tips.setPlainText("提示：可点击下方【单独压测】针对此接口进行专项并发压测，或点击【全页面并发压测】进行整站链路体检。")
            self.btn_det_records.setEnabled(False)

    def _on_fetch_response_body(self):
        if not self._selected_ep:
            return
        req_id = self._selected_ep.get("request_id")
        if not req_id:
            QMessageBox.information(self, "提示", "仅真机动态嗅探捕获的请求支持按需查看完整响应体")
            return
        body = self._browser_ctrl.fetch_response_body(req_id)
        if body:
            try:
                self.txt_resp_body.setPlainText(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
            except Exception:
                self.txt_resp_body.setPlainText(body)
            self.tab_details.setCurrentIndex(2)
        else:
            QMessageBox.information(self, "提示", "未能获取到响应体内容（可能为二进制、空响应或浏览器连接已关闭）")

    def _create_row_actions(self, ep: dict) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        btn_import = QPushButton("调试")
        btn_import.setFixedHeight(24)
        btn_import.setStyleSheet("padding: 2px 6px; font-size: 11px;")
        btn_import.clicked.connect(lambda _, e=ep: self._on_import_endpoint(e))
        layout.addWidget(btn_import)

        btn_curl = QPushButton("cURL")
        btn_curl.setFixedHeight(24)
        btn_curl.setStyleSheet("padding: 2px 6px; font-size: 11px;")
        btn_curl.clicked.connect(lambda _, e=ep: self._on_copy_curl_for_endpoint(e))
        layout.addWidget(btn_curl)

        btn_stress = QPushButton("压测")
        btn_stress.setFixedHeight(24)
        btn_stress.setStyleSheet("padding: 2px 6px; font-size: 11px;")
        btn_stress.clicked.connect(lambda _, e=ep: self._on_stress_endpoint(e))
        layout.addWidget(btn_stress)

        btn_records = QPushButton("明细")
        btn_records.setFixedHeight(24)
        btn_records.setStyleSheet("padding: 2px 6px; font-size: 11px;")
        btn_records.clicked.connect(lambda _, e=ep: self._on_view_records_for_endpoint(e))
        layout.addWidget(btn_records)

        return widget

    def _set_busy(self, busy: bool, msg: str = ""):
        is_sniffing = getattr(self, "_is_sniffing", False) or \
                      (hasattr(self, "_browser_ctrl") and self._browser_ctrl.is_running()) or \
                      (hasattr(self, "_multi_round_worker") and self._multi_round_worker and self._multi_round_worker.isRunning())
        if is_sniffing:
            self.btn_browser_sniff.setEnabled(True)
            self.btn_browser_stop.setEnabled(True)
        else:
            self.btn_browser_sniff.setEnabled(not busy)
            self.btn_browser_stop.setEnabled(False)
        self.btn_stress.setEnabled(not busy and not is_sniffing)
        self.btn_scan.setEnabled(not busy and not is_sniffing)
        self.lbl_status.setText(msg)
        if busy:
            self.lbl_status.setStyleSheet("color: #2563eb; font-weight: bold; font-size: 12px;")
        else:
            self.lbl_status.setStyleSheet("color: #6b7280; font-size: 12px;")

    def _on_task_error(self, err_msg: str):
        self._set_busy(False, "执行异常")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        QMessageBox.critical(self, "执行失败", f"请求执行失败:\n{err_msg}")

    def _on_copy_selected_url(self):
        if self._selected_ep and self._selected_ep.get("url"):
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(self._selected_ep.get("url"))
            self.lbl_status.setText("已复制当前接口 URL 到剪贴板")

    def _on_copy_curl(self):
        if self._selected_ep:
            self._on_copy_curl_for_endpoint(self._selected_ep)

    def _on_copy_curl_for_endpoint(self, ep: dict):
        headers = []
        raw_headers = ep.get("headers", {})
        if isinstance(raw_headers, dict):
            for k, v in raw_headers.items():
                headers.append({"key": str(k), "value": str(v), "enabled": True})

        body = ep.get("body", "") or ep.get("post_data", "")
        req = SavedRequest(
            name=ep.get("url", ""),
            method=ep.get("method", "GET"),
            url=ep.get("url", ""),
            headers=headers,
            body_type="json" if body and (body.strip().startswith("{") or body.strip().startswith("[")) else "raw",
            body_content=body,
        )
        from app.core.exporter import Exporter
        curl_cmd = Exporter.export_curl(req)
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(curl_cmd)
        self.lbl_status.setText("已复制 cURL 命令行到剪贴板")

    def _on_import_current_selection(self):
        if self._selected_ep:
            self._on_import_endpoint(self._selected_ep)

    def _on_stress_current_selection(self):
        if self._selected_ep:
            self._on_stress_endpoint(self._selected_ep)

    def _on_import_endpoint(self, ep: dict):
        url_name = ep.get("url", "").split("/")[-1] or ep.get("url")
        headers = []
        raw_headers = ep.get("headers", {})
        if isinstance(raw_headers, dict):
            for k, v in raw_headers.items():
                headers.append({"key": str(k), "value": str(v), "enabled": True})
        elif isinstance(raw_headers, list):
            headers = raw_headers

        body = ep.get("body", "") or ep.get("post_data", "")
        body_type = "json" if body and (body.strip().startswith("{") or body.strip().startswith("[")) else "raw"

        req = SavedRequest(
            name=f"嗅探: {url_name}",
            method=ep.get("method", "GET"),
            url=ep.get("url", ""),
            headers=headers,
            body_type=body_type,
            body_content=body,
        )
        self.import_request_requested.emit(req)
        # 保持嗅探对话框开启，便于用户继续查看压测数据或同时调试其它接口
        method = ep.get("method", "GET")
        url_text = ep.get("url", "")
        self.lbl_status.setText(f"✓ 接口 [{method}] {url_text} 已在主窗口新标签页打开调试")
        from PyQt6.QtWidgets import QToolTip
        from PyQt6.QtGui import QCursor
        QToolTip.showText(QCursor.pos(), f"✓ 接口已载入新标签页进行独立调试\n嗅探面板保持打开，可继续查看或调试其他接口", self)

    def _on_stress_endpoint(self, ep: dict):
        from app.widgets.stress_dialog import StressDialog
        url_name = ep.get("url", "").split("/")[-1] or ep.get("url")
        headers = []
        raw_headers = ep.get("headers", {})
        if isinstance(raw_headers, dict):
            for k, v in raw_headers.items():
                headers.append({"key": str(k), "value": str(v), "enabled": True})
        elif isinstance(raw_headers, list):
            headers = raw_headers

        body = ep.get("body", "") or ep.get("post_data", "")
        body_type = "json" if body and (body.strip().startswith("{") or body.strip().startswith("[")) else "raw"

        proxy_cfg = getattr(self, "proxy_cfg", None) or Settings().proxy
        req = SavedRequest(
            name=f"压测: {url_name}",
            method=ep.get("method", "GET"),
            url=ep.get("url", ""),
            headers=headers,
            body_type=body_type,
            body_content=body,
            proxy=proxy_cfg,
        )
        self._endpoint_stress_dialog = StressDialog(req, self)
        self._endpoint_stress_dialog.show()
        self._endpoint_stress_dialog.raise_()
        self._endpoint_stress_dialog.activateWindow()

    def _get_auth_headers_and_cookies(self, target_url: str):
        headers = {}
        cookies = {}
        try:
            from app.config.settings import Settings
            for gh in Settings().global_headers:
                if isinstance(gh, dict) and gh.get("enabled", True):
                    k = gh.get("key", "").strip()
                    v = gh.get("value", "")
                    if k or v:
                        headers[k] = v
        except Exception:
            pass

        try:
            from app.widgets.cookie_manager import GlobalCookieStorage
            domain_cookies = GlobalCookieStorage.get_instance().get_cookies_for_url(target_url)
            for c in domain_cookies:
                name = c.get("name") or c.get("key") or ""
                if name:
                    cookies[name] = c.get("value", "")
        except Exception:
            pass

        return headers, cookies

    def _update_auth_status_label(self):
        url = self.edit_url.text().strip() if hasattr(self, "edit_url") else ""
        if not hasattr(self, "chk_carry_auth") or not self.chk_carry_auth.isChecked():
            if hasattr(self, "lbl_auth_tip"):
                self.lbl_auth_tip.setText("（已关闭自动携带认证）")
                self.lbl_auth_tip.setStyleSheet("font-size: 11px; color: #9ca3af;")
                self.lbl_auth_tip.setToolTip("当前未开启认证联动，浏览器将以无认证状态发起嗅探")
            return

        headers, cookies = self._get_auth_headers_and_cookies(url)
        h_cnt = len(headers)
        c_cnt = len(cookies)

        if h_cnt > 0 or c_cnt > 0:
            h_keys = list(headers.keys())
            h_summary = ", ".join(h_keys[:3])
            if len(h_keys) > 3:
                h_summary += f" 等 {h_cnt} 项"
            h_part = f"{h_cnt} 个全局请求头 [{h_summary}]" if h_cnt > 0 else "0 个全局头"
            c_part = f"{c_cnt} 个 Cookie"
            tip = f"✔ 已生效联动: {h_part}, {c_part}"
            color = "#15803d"
        else:
            tip = "当前未配置全局请求头与 Cookie（可在主界面【全局请求头】中添加）"
            color = "#6b7280"

        if hasattr(self, "lbl_auth_tip"):
            self.lbl_auth_tip.setText(tip)
            self.lbl_auth_tip.setStyleSheet(f"font-size: 11px; color: {color}; font-weight: bold;")

            tt_lines = ["【全局认证注入状态】"]
            if headers:
                tt_lines.append("▶ 已注入浏览器与压测引擎的全局请求头:")
                for k, v in headers.items():
                    val_str = str(v)
                    preview = (val_str[:32] + "...") if len(val_str) > 32 else val_str
                    tt_lines.append(f"   • {k}: {preview}")
            else:
                tt_lines.append("▶ 全局请求头: 无 (可在主界面点击【全局请求头】添加 Token / Cookie 等)")

            if cookies:
                tt_lines.append("\n▶ 已注入当前域名的 Cookie:")
                for k, v in cookies.items():
                    val_str = str(v)
                    preview = (val_str[:32] + "...") if len(val_str) > 32 else val_str
                    tt_lines.append(f"   • {k}: {preview}")
            else:
                tt_lines.append("\n▶ 匹配域名 Cookie: 无")

            self.lbl_auth_tip.setToolTip("\n".join(tt_lines))

    def _on_view_selected_records(self):
        if not self._selected_ep:
            return
        url = self._selected_ep.get("url", "")
        report = self._reports_map.get(url)
        if not report or not report.get("records"):
            QMessageBox.information(
                self, "提示",
                "当前选中的接口尚未执行高并发压测采样。\n请先点击上方【全页面并发压测】或下方【单独压测】生成采样明细。"
            )
            return
        from app.widgets.stress_records_dialog import StressRecordsDialog
        method = self._selected_ep.get("method", "GET")
        self._selected_records_dlg = StressRecordsDialog(
            report.get("records", []),
            title=f"接口压测深度图表与明细 - [{method}] {url}",
            parent=self,
            page_stress_result=self._last_page_stress_result,
        )
        self._selected_records_dlg.show()
        self._selected_records_dlg.raise_()
        self._selected_records_dlg.activateWindow()

    def _on_view_records_for_endpoint(self, ep: dict):
        url = ep.get("url", "")
        report = self._reports_map.get(url)
        if not report or not report.get("records"):
            QMessageBox.information(
                self, "提示",
                f"接口 {url} 尚未执行高并发压测采样。\n请先点击上方【全页面并发压测】或操作列【压测】生成明细。"
            )
            return
        from app.widgets.stress_records_dialog import StressRecordsDialog
        method = ep.get("method", "GET")
        self._ep_records_dlg = StressRecordsDialog(
            report.get("records", []),
            title=f"接口压测结果列表与多维分析 - [{method}] {url}",
            parent=self,
            page_stress_result=self._last_page_stress_result,
        )
        self._ep_records_dlg.show()
        self._ep_records_dlg.raise_()
        self._ep_records_dlg.activateWindow()

    def _on_view_all_page_records(self):
        if not self._last_page_stress_records:
            QMessageBox.information(self, "提示", "尚未执行全页面并发压测，请先点击【全页面并发压测】")
            return
        from app.widgets.stress_records_dialog import StressRecordsDialog
        self._all_page_records_dlg = StressRecordsDialog(
            self._last_page_stress_records,
            title=f"全页面事务压测综合图表与明细 - {self.edit_url.text().strip()}",
            parent=self,
            page_stress_result=self._last_page_stress_result,
        )
        self._all_page_records_dlg.show()
        self._all_page_records_dlg.raise_()
        self._all_page_records_dlg.activateWindow()
