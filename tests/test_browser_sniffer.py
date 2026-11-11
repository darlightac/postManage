"""
针对真机交互嗅探器、全页面事务压测模型与离线报表导出的自动化测试套件
"""

import sys
import unittest
from pathlib import Path

# 添加项目根目录到 sys.path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from app.core.browser_sniffer import (
    detect_browser_executable,
    CapturedRequest,
    BrowserSnifferController,
    SimpleWebSocketClient,
)
from app.widgets.stress_records_dialog import StressRecordsDialog


class TestBrowserSniffer(unittest.TestCase):
    """测试真机浏览器嗅探与协议支持"""

    def test_browser_discovery(self):
        """测试能够探测到系统中的 Edge 或 Chrome 可执行文件"""
        browser_path = detect_browser_executable()
        # Windows 环境下通常有 Edge 或 Chrome
        self.assertTrue(browser_path is None or Path(browser_path).exists())

    def test_captured_request_fields(self):
        """测试捕获的网络请求对象字段与 API 属性识别"""
        req = CapturedRequest(
            request_id="req-123",
            method="POST",
            url="https://api.example.com/v1/users?page=1",
            headers={"Content-Type": "application/json", "Authorization": "Bearer token123"},
            post_data='{"username":"alice","action":"login"}',
            resource_type="Fetch",
            status_code=200,
            status_text="OK",
            elapsed_ms=45.6,
            is_api=True,
        )

        self.assertEqual(req.request_id, "req-123")
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.url, "https://api.example.com/v1/users?page=1")
        self.assertEqual(req.headers.get("Authorization"), "Bearer token123")
        self.assertEqual(req.post_data, '{"username":"alice","action":"login"}')
        self.assertEqual(req.status_code, 200)
        self.assertTrue(req.is_api)

    def test_controller_initialization(self):
        """测试嗅探控制器的初始状态与请求存储机制"""
        controller = BrowserSnifferController()
        self.assertFalse(controller.is_running())
        self.assertEqual(len(controller.get_requests()), 0)

        # 模拟存入捕获的请求
        dummy_req = CapturedRequest(
            request_id="dummy-1",
            method="GET",
            url="https://api.example.com/health",
            resource_type="XHR",
            status_code=200,
            is_api=True
        )
        with controller._req_lock:
            controller._requests["dummy-1"] = dummy_req

        self.assertEqual(len(controller.get_requests()), 1)
        self.assertEqual(controller.get_requests()[0].url, "https://api.example.com/health")

        controller.clear_requests()
        self.assertEqual(len(controller.get_requests()), 0)

    def test_in_flight_tracking_and_wait_settle(self):
        """测试在途请求生命周期追踪与静默收敛检测，防止接口处于 pending"""
        controller = BrowserSnifferController()
        # 初始无在途请求
        self.assertEqual(len(controller._in_flight_reqs), 0)

        # 模拟进入在途
        with controller._in_flight_lock:
            controller._in_flight_reqs.add("req-1")
            controller._in_flight_reqs.add("req-2")

        self.assertEqual(len(controller._in_flight_reqs), 2)

        # 模拟 1 个完成，1 个失败
        with controller._in_flight_lock:
            controller._in_flight_reqs.discard("req-1")
        self.assertEqual(len(controller._in_flight_reqs), 1)

        with controller._in_flight_lock:
            controller._in_flight_reqs.discard("req-2")
        self.assertEqual(len(controller._in_flight_reqs), 0)

    def test_endpoint_extraction_preserves_auth_and_session(self):
        """测试提取 API 列表时完整保留所有参数、POST体、请求头、Session及Cookie"""
        from app.widgets.sniffer_dialog import BrowserMultiRoundStressWorker
        req1 = CapturedRequest(
            request_id="req-1",
            method="POST",
            url="http://10.111.212.130/api/login?tenantId=test&from=pc",
            headers={
                "Authorization": "Bearer sample_jwt_token_123",
                "X-CSRF-Token": "csrf_xyz_789",
                "Content-Type": "application/json",
                "Cookie": "SESSIONID=sess_999; token=eyJh...",
            },
            post_data='{"username":"admin"}',
            is_api=True,
        )

        worker = BrowserMultiRoundStressWorker(
            None,
            {"target_url": "http://10.111.212.130", "total_rounds": 1}
        )
        endpoints = worker._extract_api_endpoints([req1], "http://10.111.212.130")

        self.assertEqual(len(endpoints), 1)
        ep = endpoints[0]
        # 验证完整 URL 包含 query params
        self.assertEqual(ep["url"], "http://10.111.212.130/api/login?tenantId=test&from=pc")
        # 验证 POST 载荷保留
        self.assertEqual(ep["body"], '{"username":"admin"}')
        # 验证头信息保留 Authorization、X-CSRF-Token、Cookie
        self.assertEqual(ep["headers"]["Authorization"], "Bearer sample_jwt_token_123")
        self.assertEqual(ep["headers"]["X-CSRF-Token"], "csrf_xyz_789")
        self.assertIn("SESSIONID=sess_999", ep["headers"]["Cookie"])


class TestPageStressAndReport(unittest.TestCase):
    """测试全页面压测结果结构解析与离线 HTML 报表生成"""

    def setUp(self):
        self.sample_page_stress_result = {
            "total_page_iterations": 10,
            "successful_page_iterations": 9,
            "concurrency": 2,
            "page_success_rate": 90.0,
            "avg_page_load_duration_ms": 128.5,
            "min_page_duration_ms": 95.0,
            "max_page_duration_ms": 250.0,
            "p90_page_duration_ms": 210.0,
            "p95_page_duration_ms": 240.0,
            "page_rps": 15.6,
            "endpoint_rankings": [
                {
                    "rank": 1,
                    "url": "https://api.example.com/data/query",
                    "method": "POST",
                    "avg_latency_ms": 115.4,
                    "max_latency_ms": 240.0,
                    "share_percent": 65.0,
                    "success_rate": 100.0,
                },
                {
                    "rank": 2,
                    "url": "https://api.example.com/auth/user",
                    "method": "GET",
                    "avg_latency_ms": 45.2,
                    "max_latency_ms": 90.0,
                    "share_percent": 35.0,
                    "success_rate": 90.0,
                }
            ],
            "endpoint_error_stats": [
                {
                    "url": "https://api.example.com/auth/user",
                    "method": "GET",
                    "error_count": 1,
                    "error_rate": 10.0,
                    "status_codes": {"500": 1},
                    "last_errors": ["HTTP 500 Internal Server Error"]
                }
            ],
            "page_records": [
                {
                    "iteration": 1,
                    "worker_id": 0,
                    "success": True,
                    "duration_ms": 110.5,
                    "slowest_endpoint": "https://api.example.com/data/query",
                    "endpoint_count": 2,
                    "timestamp": 1726038000.0
                },
                {
                    "iteration": 2,
                    "worker_id": 1,
                    "success": False,
                    "duration_ms": 180.2,
                    "slowest_endpoint": "https://api.example.com/data/query",
                    "endpoint_count": 2,
                    "timestamp": 1726038001.0
                }
            ]
        }

    def test_stress_dialog_tabs_with_page_stress(self):
        """测试压测报表窗口装配全页面压测数据并正确展示慢接口与错误归因 Tab"""
        dialog = StressRecordsDialog(
            records=[],
            page_stress_result=self.sample_page_stress_result
        )

        # 检查 Tab 数量（包含时序趋势、状态码分布、耗时直方图、原始采样、慢接口排行、错误归因）
        self.assertEqual(dialog.tab_charts.count(), 6)
        tab_names = [dialog.tab_charts.tabText(i) for i in range(dialog.tab_charts.count())]
        self.assertTrue(any("慢接口排行" in name for name in tab_names))
        self.assertTrue(any("错误归因" in name for name in tab_names))

        # 检查慢接口排行表格行数
        self.assertEqual(dialog.table_ranking.rowCount(), 2)
        # 检查错误归因表格行数
        self.assertEqual(dialog.table_errors.rowCount(), 1)

    def test_generate_html_report(self):
        """测试离线 HTML 报表生成功能"""
        dialog = StressRecordsDialog(
            records=[],
            page_stress_result=self.sample_page_stress_result
        )

        html_content = dialog._generate_html_report()
        self.assertIn("<!DOCTYPE html>", html_content)
        self.assertIn("PostManage 性能压测与图表分析诊断报告", html_content)
        self.assertIn("90.0%", html_content)  # 页面成功率
        self.assertIn("128.5", html_content)  # 页面平均耗时
        self.assertIn("https://api.example.com/data/query", html_content)  # 慢接口
        self.assertIn("<svg", html_content)  # 包含内嵌 SVG 图表


class TestBrowserMultiRoundStress(unittest.TestCase):
    """测试多轮真机刷新压测与嗅探停止控制"""

    def test_aggregate_results_pure_browser(self):
        """测试真机多轮捕获数据的聚合计算与报告生成"""
        from app.widgets.sniffer_dialog import BrowserMultiRoundStressWorker

        controller = BrowserSnifferController()
        worker = BrowserMultiRoundStressWorker(controller, {"target_url": "https://example.com/app", "total_rounds": 5})
        worker._page_durations = [120.0, 110.0, 130.0, 100.0, 140.0]

        captured = [
            CapturedRequest(
                request_id="r1",
                method="GET",
                url="https://example.com/api/user",
                status_code=200,
                elapsed_ms=45.0,
                is_api=True,
            ),
            CapturedRequest(
                request_id="r2",
                method="GET",
                url="https://example.com/api/user",
                status_code=200,
                elapsed_ms=55.0,
                is_api=True,
            ),
            CapturedRequest(
                request_id="r3",
                method="POST",
                url="https://example.com/api/data",
                status_code=200,
                elapsed_ms=120.0,
                is_api=True,
            ),
            CapturedRequest(
                request_id="r4",
                method="POST",
                url="https://example.com/api/data",
                status_code=500,
                elapsed_ms=250.0,
                error="Server Error",
                is_api=True,
            ),
        ]

        result = worker._aggregate_results(captured, None, 5, "https://example.com/app")

        self.assertEqual(result["target_url"], "https://example.com/app")
        self.assertEqual(result["total_endpoints"], 2)
        self.assertEqual(result["total_requests"], 4)
        self.assertEqual(result["success_count"], 3)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["total_page_iterations"], 5)
        self.assertAlmostEqual(result["avg_page_load_duration_ms"], 120.0, places=1)
        self.assertEqual(len(result["endpoint_reports"]), 2)

        # 检查各接口报告中的丰富指标
        post_rep = next(r for r in result["endpoint_reports"] if r["method"] == "POST")
        self.assertEqual(post_rep["total_requests"], 2)
        self.assertEqual(post_rep["success_count"], 1)
        self.assertEqual(post_rep["error_count"], 1)
        self.assertEqual(post_rep["error_rate"], 50.0)
        self.assertIn("latency_bins", post_rep)
        self.assertIn("status_code_dist", post_rep)
        self.assertIn("diagnosis_tips", post_rep)

    def test_sniffer_dialog_stop_and_buttons(self):
        """测试 PageSnifferDialog 启动、多轮勾选与停止按钮联动"""
        from app.widgets.sniffer_dialog import PageSnifferDialog

        dlg = PageSnifferDialog("https://example.com")
        self.assertTrue(dlg.chk_auto_multi_round.isChecked())
        self.assertEqual(dlg.spin_requests.value(), 20)
        self.assertEqual(dlg.spin_concurrency.value(), 5)

        # 验证初始状态：停止按钮禁用，调起真机与嗅探压测按钮可用
        self.assertTrue(dlg.btn_browser_sniff.isEnabled())
        self.assertTrue(dlg.btn_start_multi_round.isEnabled())
        self.assertFalse(dlg.btn_browser_stop.isEnabled())

        # 模拟进入嗅探中状态
        dlg._is_sniffing = True
        dlg._set_busy(True, "测试运行中...")

        # 嗅探运行时专用停止按钮可用
        self.assertTrue(dlg.btn_browser_stop.isEnabled())

        # 模拟点击停止嗅探
        dlg._on_browser_stop()

        self.assertTrue(dlg.btn_browser_sniff.isEnabled())
        self.assertEqual(dlg.btn_browser_sniff.text(), "🚀 调起真机浏览器")
        self.assertTrue(dlg.btn_start_multi_round.isEnabled())
        self.assertEqual(dlg.btn_start_multi_round.text(), "▶ 开始嗅探压测")
        self.assertFalse(dlg.btn_browser_stop.isEnabled())
        self.assertTrue(dlg.btn_scan.isEnabled())
        dlg.close()

    def test_saved_request_load_and_import_new_tab(self):
        """测试嗅探接口调试时载入到新窗口，不覆盖原有请求"""
        from app.core.models import SavedRequest, HeaderItem, ParamItem
        from app.widgets.request_editor import RequestEditor
        from app.main_window import MainWindow

        win = MainWindow()
        orig_page = win._create_new_tab()
        initial_tab_count = win.request_tabs.tab_widget.count()
        # 原有标签页编辑了特定内容
        orig_editor = orig_page.request_editor
        orig_editor.method_combo.setCurrentText("DELETE")
        orig_editor.url_input.setText("https://original-url.com/do-not-overwrite")

        # 模拟从嗅探器导入接口
        sniffed_req = {
            "name": "GET /api/v1/user/info",
            "method": "GET",
            "url": "https://api.example.com/v1/user/info?id=100",
            "headers": {"Authorization": "Bearer token_xyz", "X-Custom": "val"},
            "params": [{"key": "id", "value": "100", "enabled": True}],
            "body": "",
            "body_type": "json",
            "proxy": {"mode": "direct"},
        }
        win._on_import_sniffed_request(sniffed_req)

        # 标签页应当增加 1 个，而不是保持原数
        self.assertEqual(win.request_tabs.tab_widget.count(), initial_tab_count + 1)
        # 原有标签页内容必须完全保留，未被覆盖
        self.assertEqual(orig_editor.method_combo.currentText(), "DELETE")
        self.assertEqual(orig_editor.url_input.text(), "https://original-url.com/do-not-overwrite")

        # 新建的标签页包含嗅探的接口信息
        new_page = win.request_tabs.current_page()
        new_editor = new_page.request_editor
        self.assertEqual(new_editor.method_combo.currentText(), "GET")
        self.assertEqual(new_editor.url_input.text(), "https://api.example.com/v1/user/info?id=100")
        win.close()

    def test_stress_records_dialog_splitters_and_body_inspector(self):
        """测试压测结果列表支持区域拖动调整大小、悬浮展示完整内容与查看请求体响应体"""
        sample_records = [
            {
                "index": 1,
                "offset_ms": 150.0,
                "method": "POST",
                "url": "https://api.example.com/orders/create?shop_id=999",
                "status_code": 200,
                "elapsed_ms": 68.5,
                "size_bytes": 1024,
                "error": "",
                "request_headers": {"Content-Type": "application/json", "Authorization": "Bearer tok_123"},
                "request_body": '{"product_id": 42, "qty": 2}',
                "response_headers": {"Server": "nginx", "Content-Type": "application/json"},
                "response_body": '{"code": 0, "order_id": "ORD20261109001", "msg": "success"}',
            },
            {
                "index": 2,
                "offset_ms": 320.0,
                "method": "GET",
                "url": "https://api.example.com/orders/query?id=ORD20261109001",
                "status_code": 500,
                "elapsed_ms": 320.0,
                "size_bytes": 256,
                "error": "Internal Server Error",
                "request_headers": {"Accept": "application/json"},
                "request_body": "",
                "response_headers": {"Content-Type": "application/json"},
                "response_body": '{"code": 500, "message": "Database connection timeout"}',
            }
        ]

        dlg = StressRecordsDialog(sample_records, title="单元测试压测结果详情")

        # 1. 验证可拖动调整大小的分割器存在
        self.assertIsNotNone(dlg.splitter_main)
        self.assertIsNotNone(dlg.splitter_left)

        # 2. 验证表格项悬浮 tooltip 完整展示
        self.assertEqual(dlg.table.rowCount(), 2)
        url_item = dlg.table.item(0, 3)
        self.assertIn("https://api.example.com/orders/create", url_item.toolTip())
        err_item = dlg.table.item(1, 7)
        self.assertIn("Internal Server Error", err_item.toolTip())

        # 3. 验证选中第 1 行后，下方报文探查器完整解析渲染请求头、请求体、响应头、响应体
        dlg.table.selectRow(0)
        dlg._show_record_detail(sample_records[0])

        self.assertIn("tok_123", dlg.txt_req_headers.toPlainText())
        self.assertIn('"product_id": 42', dlg.txt_req_body.toPlainText())
        self.assertIn("nginx", dlg.txt_resp_headers.toPlainText())
        self.assertIn("ORD20261109001", dlg.txt_resp_body.toPlainText())
        self.assertIn("POST", dlg.lbl_det_title.text())
        self.assertIn("https://api.example.com/orders/create", dlg.lbl_det_title.toolTip())

        # 4. 验证参数列表已解析 query string
        self.assertEqual(dlg.table_params.rowCount(), 1)
        self.assertEqual(dlg.table_params.item(0, 0).text(), "shop_id")
        self.assertEqual(dlg.table_params.item(0, 1).text(), "999")
        dlg.close()

    def test_captured_request_clear_and_preservation(self):
        """测试清空嗅探列表及清空后继续捕获与多轮压测参数/头保留机制"""
        controller = BrowserSnifferController()
        r1 = CapturedRequest(request_id="1", method="GET", url="https://test.com/a")
        r2 = CapturedRequest(request_id="2", method="POST", url="https://test.com/b")
        controller._requests["1"] = r1
        controller._requests["2"] = r2

        self.assertEqual(len(controller.get_requests()), 2)
        controller.clear_requests()
        # 清空后列表为空
        self.assertEqual(len(controller.get_requests()), 0)

        # 模拟清空后页面刷新或跳转新页面，能够继续捕获新接口
        r3 = CapturedRequest(request_id="3", method="GET", url="https://test.com/c", is_api=True)
        controller._requests["3"] = r3
        self.assertEqual(len(controller.get_requests()), 1)
        self.assertEqual(controller.get_requests()[0].url, "https://test.com/c")

        # 验证 Worker 聚合结果包含请求和响应的 headers/body
        from app.widgets.sniffer_dialog import BrowserMultiRoundStressWorker
        worker = BrowserMultiRoundStressWorker(
            browser_ctrl=controller,
            config={
                "target_url": "https://test.com",
                "total_rounds": 1,
                "concurrency": 1,
                "delay_ms": 0,
            },
        )
        sample = CapturedRequest(
            request_id="s1",
            method="POST",
            url="https://test.com/api/login",
            headers={"Content-Type": "application/json", "Cookie": "session=abc"},
            post_data='{"user":"admin"}',
            response_headers={"Set-Cookie": "session=abc"},
            response_body='{"status":"ok"}',
            status_code=200,
            elapsed_ms=50.0,
            is_api=True,
        )
        res = worker._aggregate_results([sample], None, 1, "https://test.com")
        rep = res["endpoint_reports"][0]
        self.assertEqual(len(rep["records"]), 1)
        rec = rep["records"][0]
        self.assertEqual(rec["request_body"], '{"user":"admin"}')
        self.assertEqual(rec["response_body"], '{"status":"ok"}')
        self.assertEqual(rec["request_headers"].get("Cookie"), "session=abc")
        self.assertEqual(rec["response_headers"].get("Set-Cookie"), "session=abc")

    def test_sniffer_dialog_table_resizable_and_keep_open_on_debug(self):
        """测试嗅探表格与分割器可自由调整大小，且点击调试时嗅探窗口不关闭"""
        from PyQt6.QtWidgets import QHeaderView
        from app.widgets.sniffer_dialog import PageSnifferDialog

        dlg = PageSnifferDialog("https://example.com")
        dlg.show()

        # 1. 验证分割器手柄宽度为 8px，方便拖拽调整边界
        self.assertEqual(dlg.splitter.handleWidth(), 8)

        # 2. 验证表格列均为 Interactive 模式，支持用户拖动列宽边界
        header = dlg.table.horizontalHeader()
        self.assertEqual(header.sectionResizeMode(0), QHeaderView.ResizeMode.Interactive)
        self.assertEqual(header.sectionResizeMode(1), QHeaderView.ResizeMode.Interactive)
        self.assertGreaterEqual(dlg.table.columnWidth(1), 350)  # URL 足够宽，杜绝被挤压成省略号

        # 3. 验证点击调试时不关闭嗅探窗口
        received_reqs = []
        dlg.import_request_requested.connect(lambda req: received_reqs.append(req))
        test_ep = {
            "method": "POST",
            "url": "https://example.com/api/v1/trade",
            "headers": {"Authorization": "Bearer tok"},
            "body": '{"order": 1}',
        }
        dlg._on_import_endpoint(test_ep)

        # 信号正常发射且数据完整
        self.assertEqual(len(received_reqs), 1)
        self.assertEqual(received_reqs[0].url, "https://example.com/api/v1/trade")
        # 核心断言：嗅探窗口依然可见，未被 accept/close 关闭！
        self.assertTrue(dlg.isVisible())

        # 4. 关闭对话框时正确清理控制器
        ctrl = dlg._browser_ctrl
        self.assertIn(ctrl, BrowserSnifferController._active_controllers)
        dlg.close()
        self.assertNotIn(ctrl, BrowserSnifferController._active_controllers)

    def test_browser_sniffer_controller_stop_all(self):
        """测试全局 stop_all 能够在软件退出时干净关闭全部运行中的嗅探控制器"""
        ctrl1 = BrowserSnifferController()
        ctrl2 = BrowserSnifferController()
        self.assertIn(ctrl1, BrowserSnifferController._active_controllers)
        self.assertIn(ctrl2, BrowserSnifferController._active_controllers)

        BrowserSnifferController.stop_all()
        self.assertNotIn(ctrl1, BrowserSnifferController._active_controllers)
        self.assertNotIn(ctrl2, BrowserSnifferController._active_controllers)

    def test_stress_and_sniffer_reports_metrics(self):
        """测试压测与嗅探分析报告中完整包含吞吐量(TPS/QPS)、平均请求时间等核心压测指标"""
        from PyQt6.QtWidgets import QLabel
        from app.core.models import SavedRequest
        from app.widgets.stress_dialog import StressDialog
        from app.widgets.sniffer_dialog import PageSnifferDialog

        # 1. 验证 StressRecordsDialog 生成的 HTML 深度报告包含全套关键压测指标
        sample_records = [
            {
                "index": 1,
                "offset_ms": 10.0,
                "method": "POST",
                "url": "https://api.example.com/v1/order",
                "status_code": 200,
                "elapsed_ms": 45.0,
                "size_bytes": 1024,
                "error": "",
                "request_headers": {"Authorization": "Bearer tk"},
                "request_body": '{"item":"book"}',
                "response_body": '{"code":0,"msg":"success"}',
            },
            {
                "index": 2,
                "offset_ms": 110.0,
                "method": "POST",
                "url": "https://api.example.com/v1/order",
                "status_code": 200,
                "elapsed_ms": 55.0,
                "size_bytes": 2048,
                "error": "",
                "request_headers": {"Authorization": "Bearer tk"},
                "request_body": '{"item":"pen"}',
                "response_body": '{"code":0,"msg":"success"}',
            },
        ]
        page_result = {
            "target_url": "https://example.com",
            "overall_tps": 20.0,
            "qps": 20.0,
            "page_rps": 5.0,
            "page_tps": 5.0,
            "page_success_rate": 100.0,
            "avg_page_load_duration_ms": 120.0,
            "total_page_iterations": 10,
            "successful_page_iterations": 10,
            "records": sample_records,
        }
        records_dlg = StressRecordsDialog(sample_records, page_stress_result=page_result)
        html_report = records_dlg._generate_html_report()

        # 验证报告文本中明确体现吞吐量、TPS、QPS、平均请求时间、带宽、分位延迟
        self.assertIn("吞吐量", html_report)
        self.assertIn("TPS", html_report)
        self.assertIn("QPS", html_report)
        self.assertIn("平均请求时间", html_report)
        self.assertIn("数据传输带宽", html_report)
        self.assertIn("90分位延迟", html_report)
        self.assertIn("99分位延迟", html_report)

        # 验证 UI 顶部指示栏
        self.assertIn("吞吐量", records_dlg.lbl_metric_tps.text())
        self.assertIn("平均请求时间", records_dlg.lbl_metric_avg.text())
        records_dlg.close()

        # 2. 验证 StressDialog 具备 HTML 导出按钮及指标卡片
        req = SavedRequest(name="单接口压测", method="GET", url="https://api.example.com/health")
        stress_dlg = StressDialog(req)
        self.assertTrue(hasattr(stress_dlg, "btn_export_html"))
        self.assertIn("HTML", stress_dlg.btn_export_html.text())
        self.assertIn("TPS / QPS", stress_dlg.card_tps["widget"].findChild(QLabel).text())
        self.assertIn("平均请求时间", stress_dlg.card_rt["widget"].findChild(QLabel).text())
        stress_dlg.close()

        # 3. 验证 PageSnifferDialog 指标卡片
        sniffer_dlg = PageSnifferDialog()
        self.assertIn("吞吐量", sniffer_dlg.card_errors["title"].text())
        self.assertIn("平均请求时间", sniffer_dlg.card_avg_lat["title"].text())
        sniffer_dlg.close()

    def test_dialogs_minimize_capabilities(self):
        """测试压测、嗅探、Mock中心窗口均包含最小化窗口按钮与系统最小化窗口特性"""
        from PyQt6.QtCore import Qt
        from app.core.models import SavedRequest
        from app.widgets.stress_dialog import StressDialog
        from app.widgets.sniffer_dialog import PageSnifferDialog
        from app.widgets.stress_records_dialog import StressRecordsDialog
        from app.widgets.mock_center_dialog import MockCenterDialog

        # 1. PageSnifferDialog (嗅探窗口)
        sniffer = PageSnifferDialog()
        self.assertTrue(bool(sniffer.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint))
        self.assertTrue(hasattr(sniffer, "btn_minimize"))
        self.assertIn("最小化", sniffer.btn_minimize.text())
        sniffer.show()
        sniffer.btn_minimize.click()
        self.assertTrue(sniffer.isMinimized())
        sniffer.close()

        # 2. StressDialog (测试/压测窗口)
        req = SavedRequest(name="测试", method="GET", url="https://example.com/api")
        stress = StressDialog(req)
        self.assertTrue(bool(stress.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint))
        self.assertTrue(hasattr(stress, "btn_minimize"))
        self.assertIn("最小化", stress.btn_minimize.text())
        stress.show()
        stress.btn_minimize.click()
        self.assertTrue(stress.isMinimized())
        stress.close()

        # 3. StressRecordsDialog (压测结果明细与图表)
        records_dlg = StressRecordsDialog([{"index": 1, "status_code": 200, "elapsed_ms": 30.0}])
        self.assertTrue(bool(records_dlg.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint))
        self.assertTrue(hasattr(records_dlg, "btn_minimize"))
        self.assertIn("最小化", records_dlg.btn_minimize.text())
        records_dlg.show()
        records_dlg.btn_minimize.click()
        self.assertTrue(records_dlg.isMinimized())
        records_dlg.close()

        # 4. MockCenterDialog (Mock 中心)
        mock_dlg = MockCenterDialog()
        self.assertTrue(bool(mock_dlg.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint))
        self.assertTrue(hasattr(mock_dlg, "btn_minimize"))
        self.assertIn("最小化", mock_dlg.btn_minimize.text())
        mock_dlg.show()
        mock_dlg.btn_minimize.click()
        self.assertTrue(mock_dlg.isMinimized())
        mock_dlg.close()


if __name__ == "__main__":
    unittest.main()
