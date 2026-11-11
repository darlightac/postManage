"""Tests for Global & Request Proxy, Left Panel Resizability, and 1s Hover ToolTip.
"""
import os
import sys
import unittest
import tempfile
from unittest.mock import patch, MagicMock

from PyQt6.QtWidgets import QApplication

from app.core.proxy_manager import (
    resolve_httpx_proxy,
    is_host_bypassed,
    evaluate_pac_script,
    get_system_proxy_info,
)
from app.core.models import SavedRequest, Collection
from app.core.db import Database
from app.config.settings import Settings


app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)


class TestProxyManager(unittest.TestCase):
    def test_direct_mode(self):
        proxy, trust_env = resolve_httpx_proxy({"mode": "direct"}, "https://example.com")
        self.assertIsNone(proxy)
        self.assertFalse(trust_env)

        proxy, trust_env = resolve_httpx_proxy({"mode": "none"}, "https://example.com")
        self.assertIsNone(proxy)
        self.assertFalse(trust_env)

    def test_system_mode(self):
        proxy, trust_env = resolve_httpx_proxy({"mode": "system"}, "https://example.com")
        # System mode returns trust_env=True or specific system proxy
        if proxy is None:
            self.assertTrue(trust_env)
        else:
            self.assertIsInstance(proxy, str)

    def test_custom_mode_simple(self):
        cfg = {
            "mode": "custom",
            "protocol": "http",
            "server": "127.0.0.1:7890",
            "bypass": "localhost, 127.0.0.1",
        }
        # Non-bypassed target
        proxy, trust_env = resolve_httpx_proxy(cfg, "https://api.github.com/repos")
        self.assertEqual(proxy, "http://127.0.0.1:7890")
        self.assertFalse(trust_env)

        # Bypassed target
        proxy_bypassed, trust_env_bypassed = resolve_httpx_proxy(cfg, "http://localhost:8080/test")
        self.assertIsNone(proxy_bypassed)
        self.assertFalse(trust_env_bypassed)

    def test_custom_mode_with_auth_and_socks5(self):
        cfg = {
            "mode": "custom",
            "protocol": "socks5",
            "server": "proxy.corp.com:1080",
            "username": "alice",
            "password": "secret&password",
            "bypass": "",
        }
        proxy, trust_env = resolve_httpx_proxy(cfg, "https://example.com")
        self.assertTrue(proxy.startswith("socks5://alice:"))
        self.assertIn("@proxy.corp.com:1080", proxy)
        self.assertFalse(trust_env)

    def test_bypass_wildcard_and_local(self):
        bypass_str = "*.internal.domain, 192.168.*, <local>"
        self.assertTrue(is_host_bypassed("service.internal.domain", bypass_str))
        self.assertTrue(is_host_bypassed("192.168.1.100", bypass_str))
        self.assertTrue(is_host_bypassed("my-nas-box", bypass_str))  # <local> matches single-label host
        self.assertFalse(is_host_bypassed("google.com", bypass_str))
        self.assertFalse(is_host_bypassed("10.0.0.1", bypass_str))

    def test_pac_script_evaluation(self):
        pac_js = """
        function FindProxyForURL(url, host) {
            if (shExpMatch(host, "*.internal.lan")) {
                return "DIRECT";
            }
            if (host === "proxy.test") {
                return "PROXY 127.0.0.1:8888";
            }
            return "SOCKS5 127.0.0.1:1080; DIRECT";
        }
        """
        res_direct = evaluate_pac_script(pac_js, "http://api.internal.lan/v1")
        self.assertEqual(res_direct, "DIRECT")

        res_http = evaluate_pac_script(pac_js, "http://proxy.test/abc")
        self.assertEqual(res_http, "http://127.0.0.1:8888")

        res_socks = evaluate_pac_script(pac_js, "http://example.com")
        self.assertEqual(res_socks, "socks5://127.0.0.1:1080")

        # Test PAC resolve_httpx_proxy integration
        cfg_pac = {
            "mode": "pac",
            "pac_content": pac_js,
        }
        p1, _ = resolve_httpx_proxy(cfg_pac, "http://proxy.test/data")
        self.assertEqual(p1, "http://127.0.0.1:8888")

        p2, _ = resolve_httpx_proxy(cfg_pac, "http://api.internal.lan/query")
        self.assertIsNone(p2)

    def test_user_pac_compound_and_substring(self):
        user_pac = """function FindProxyForURL(url, host) 
{
	//begin
	//read current proxy configuration
	

	//set ffcs proxy configuration
	
	if (shExpMatch(host, '10.119.254.59'))
	{
		return 'PROXY 192.168.184.165:8443';
	}
	if (shExpMatch(host, '10.111.212.130')
		|| shExpMatch(host, '10.111.11.141')
		|| shExpMatch(host, '10.111.11.144'))
			{
		return 'PROXY 192.168.66.44:8443';
	}
	if(url.substring(0,5) == 'http:')
	{
		return 'DIRECT';
	}
	else if(url.substring(0,6) == 'https:')
	{
		return 'DIRECT';
	}
	else
	{
		return 'DIRECT';
	}
}"""
        # 1. 完整 URL 访问 10.111.212.130
        self.assertEqual(evaluate_pac_script(user_pac, "http://10.111.212.130"), "http://192.168.66.44:8443")
        self.assertEqual(evaluate_pac_script(user_pac, "http://10.111.212.130:8080/api/v1"), "http://192.168.66.44:8443")

        # 2. 未携带协议头的 URL (如用户直接在输入框输入 10.111.212.130)
        self.assertEqual(evaluate_pac_script(user_pac, "10.111.212.130"), "http://192.168.66.44:8443")
        self.assertEqual(evaluate_pac_script(user_pac, "10.111.212.130:8080/test"), "http://192.168.66.44:8443")

        # 3. 复合 || 判断条件中的第 2、第 3 个 IP
        self.assertEqual(evaluate_pac_script(user_pac, "http://10.111.11.141/test"), "http://192.168.66.44:8443")
        self.assertEqual(evaluate_pac_script(user_pac, "http://10.111.11.144/test"), "http://192.168.66.44:8443")

        # 4. 单独匹配第一条规则的 IP
        self.assertEqual(evaluate_pac_script(user_pac, "http://10.119.254.59/test"), "http://192.168.184.165:8443")

        # 5. substring 匹配的直连域名
        self.assertEqual(evaluate_pac_script(user_pac, "http://www.google.com"), "DIRECT")
        self.assertEqual(evaluate_pac_script(user_pac, "https://www.google.com"), "DIRECT")

        # 6. resolve_httpx_proxy 集成
        cfg = {"mode": "pac", "pac_content": user_pac}
        proxy, trust_env = resolve_httpx_proxy(cfg, "http://10.111.212.130:8080")
        self.assertEqual(proxy, "http://192.168.66.44:8443")
        self.assertFalse(trust_env)

        # 直连解析
        proxy_direct, _ = resolve_httpx_proxy(cfg, "http://www.google.com")
        self.assertIsNone(proxy_direct)


class TestDatabaseAndModelsProxy(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_proxy.db")
        self.db = Database()
        self.orig_db_path = self.db.db_path
        self.db.switch_database(self.db_path)

    def tearDown(self):
        self.db.switch_database(self.orig_db_path)
        self.temp_dir.cleanup()

    def test_saved_request_proxy_serialization(self):
        req = SavedRequest(
            name="Proxy Test",
            method="POST",
            url="https://api.test/proxy",
            proxy={"mode": "custom", "server": "127.0.0.1:8080", "protocol": "http"}
        )
        self.assertEqual(req.proxy.get("mode"), "custom")
        json_str = req.proxy_json()
        self.assertIn('"mode": "custom"', json_str)
        self.assertIn('"server": "127.0.0.1:8080"', json_str)

    def test_db_create_and_read_proxy(self):
        col = self.db.create_collection(Collection(name="Col 1"))
        req = SavedRequest(
            name="Req with Custom Proxy",
            collection_id=col.id,
            method="GET",
            url="https://api.test/get",
            proxy={"mode": "custom", "server": "10.0.0.1:8888", "bypass": "localhost"}
        )
        saved = self.db.create_request(req)
        self.assertIsNotNone(saved.id)

        loaded = self.db.get_request(saved.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.proxy.get("mode"), "custom")
        self.assertEqual(loaded.proxy.get("server"), "10.0.0.1:8888")
        self.assertEqual(loaded.proxy.get("bypass"), "localhost")

    def test_db_update_proxy(self):
        col = self.db.create_collection(Collection(name="Col 1"))
        req = SavedRequest(
            name="Req to update proxy",
            collection_id=col.id,
            method="GET",
            url="https://api.test/test",
            proxy={"mode": "system"}
        )
        saved = self.db.create_request(req)

        saved.proxy = {"mode": "direct"}
        self.db.update_request(saved)

        loaded = self.db.get_request(saved.id)
        self.assertEqual(loaded.proxy.get("mode"), "direct")

    def test_save_open_tab_with_proxy(self):
        self.db.save_open_tab(
            tab_id="tab_1",
            request_id="",
            collection_id="",
            name="Tab with proxy",
            method="DELETE",
            url="https://api.test/delete",
            headers="[]",
            params="[]",
            body_type="none",
            body_content="",
            auth_type="none",
            auth_config="{}",
            timeout=0,
            sort_order=0,
            proxy='{"mode": "custom", "server": "127.0.0.1:1080"}'
        )
        tabs = self.db.get_open_tabs()
        self.assertEqual(len(tabs), 1)
        self.assertIn('"mode": "custom"', tabs[0]["proxy"])
        self.assertIn('"server": "127.0.0.1:1080"', tabs[0]["proxy"])


class TestHTTPClientProxyPriority(unittest.TestCase):
    @patch("app.core.http_client.httpx.Client")
    def test_request_proxy_overrides_global(self, mock_client_cls):
        mock_ctx = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_ctx
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.reason_phrase = "OK"
        mock_resp.headers = {}
        mock_resp.content = b'{"ok": true}'
        mock_resp.text = '{"ok": true}'
        mock_resp.cookies.jar = []
        mock_ctx.request.return_value = mock_resp

        from app.core.http_client import HTTPClient

        # Settings has custom global proxy
        with patch.object(Settings, "proxy", {"mode": "custom", "server": "global.proxy:8080", "protocol": "http"}):
            # 1. Request with explicit direct mode -> should override global!
            req_direct = SavedRequest(
                method="GET",
                url="https://httpbin.org/get",
                proxy={"mode": "direct"}
            )
            client = HTTPClient()
            client.send(req_direct)

            call_kwargs = mock_client_cls.call_args[1]
            self.assertIsNone(call_kwargs.get("proxy"))
            self.assertFalse(call_kwargs.get("trust_env"))

            # 2. Request with default mode -> should fall back to global proxy!
            req_default = SavedRequest(
                method="GET",
                url="https://httpbin.org/get",
                proxy={"mode": "default"}
            )
            client.send(req_default)
            call_kwargs_default = mock_client_cls.call_args[1]
            self.assertEqual(call_kwargs_default.get("proxy"), "http://global.proxy:8080")
            self.assertFalse(call_kwargs_default.get("trust_env"))


class TestLeftPanelAndTooltips(unittest.TestCase):
    def test_settings_left_panel_width(self):
        settings = Settings()
        orig = settings.left_panel_width
        try:
            settings.left_panel_width = 360
            self.assertEqual(settings.left_panel_width, 360)
        finally:
            settings.left_panel_width = orig

    def test_collection_tree_tooltip_timer(self):
        from app.widgets.collection_tree import CollectionTree
        tree = CollectionTree()
        self.assertTrue(tree.tree.hasMouseTracking())
        self.assertTrue(hasattr(tree.tree, "_fullname_tooltip_timer"))
        self.assertEqual(tree.tree._fullname_tooltip_timer.interval(), 1000)
        self.assertTrue(tree.tree._fullname_tooltip_timer.isSingleShot())

    def test_history_list_tooltip_timer(self):
        from app.widgets.history_panel import CustomHistoryListWidget
        history_list = CustomHistoryListWidget()
        self.assertTrue(history_list.hasMouseTracking())
        self.assertTrue(hasattr(history_list, "_fullname_tooltip_timer"))
        self.assertEqual(history_list._fullname_tooltip_timer.interval(), 1000)
        self.assertTrue(history_list._fullname_tooltip_timer.isSingleShot())

    def test_legacy_data_compatibility(self):
        from app.core.models import SavedRequest, HistoryRecord

        # 1. 历史遗留字典格式 headers 与空 proxy
        row_legacy = {
            "id": "leg_1",
            "collection_id": "c_1",
            "name": "Legacy Req",
            "method": "POST",
            "url": "https://api.old.com/data",
            "headers": '{"Authorization": "Bearer token123", "Content-Type": "application/json"}',
            "params": '{"page": "1", "size": "20"}',
            "auth_config": None,
            "cookies": None,
            "pre_script": None,
            "post_script": None,
            "proxy": None,
        }
        req = SavedRequest.from_db_row(row_legacy)
        self.assertEqual(len(req.headers), 2)
        self.assertEqual(req.headers[0].key, "Authorization")
        self.assertEqual(req.headers[0].value, "Bearer token123")
        self.assertEqual(len(req.params), 2)
        self.assertEqual(req.proxy, {})

        # 2. 历史遗留元组/列表格式 headers
        row_tuple_headers = {
            "id": "leg_2",
            "name": "Tuple Headers",
            "headers": '[["X-Custom", "123"]]',
            "params": '[["q", "test"]]',
        }
        req2 = SavedRequest.from_db_row(row_tuple_headers)
        self.assertEqual(len(req2.headers), 1)
        self.assertEqual(req2.headers[0].key, "X-Custom")
        self.assertEqual(req2.headers[0].value, "123")

        # 3. 历史记录兼容解析
        hist_legacy = {
            "id": "h_1",
            "method": "GET",
            "url": "https://api.test/history",
            "headers": '{"User-Agent": "PostManage"}',
            "params": '{"k": "v"}',
        }
        hist = HistoryRecord.from_db_row(hist_legacy)
        self.assertEqual(len(hist.headers), 1)
        self.assertEqual(hist.headers[0].key, "User-Agent")
        self.assertEqual(len(hist.params), 1)

    def test_request_tab_page_refresh_proxy_state(self):
        from app.widgets.request_tabs import RequestTabPage

        page = RequestTabPage()
        # 验证调用 refresh_name_display 及 refresh_proxy_button_state 无 NameError 崩溃
        page.refresh_name_display()
        self.assertIn("代理", page.proxy_btn.text())

        # 设置自定义代理状态
        page.request_editor.proxy_config = {"mode": "custom", "server": "127.0.0.1:8888"}
        page.refresh_proxy_button_state()
        self.assertIn("自定义", page.proxy_btn.text())

    def test_stress_dialog_proxy_initialization_and_display(self):
        """测试压测对话框中的代理状态初始化、展示及切换"""
        from app.widgets.stress_dialog import StressDialog

        req = SavedRequest(
            name="压测测试接口",
            method="POST",
            url="https://api.example.com/v1/trade",
            proxy={"mode": "custom", "host": "192.168.1.100", "port": 8888},
        )
        dlg = StressDialog(req)
        self.assertTrue(hasattr(dlg, "btn_proxy"))
        self.assertIn("192.168.1.100:8888", dlg.btn_proxy.text())

        # 切换为直连模式
        dlg._proxy_cfg = {"mode": "direct"}
        dlg._update_proxy_display()
        self.assertIn("直连", dlg.btn_proxy.text())

        # 切换为 PAC 模式
        dlg._proxy_cfg = {"mode": "pac", "pac_url": "http://127.0.0.1:18033/proxy.pac"}
        dlg._update_proxy_display()
        self.assertIn("PAC", dlg.btn_proxy.text())

        # 切换为跟随全局模式
        dlg._proxy_cfg = {"mode": "default"}
        dlg._update_proxy_display()
        self.assertIn("全局", dlg.btn_proxy.text())

    def test_stress_dialog_resolve_proxy_on_start(self):
        """测试点击开始并发压测时，代理配置被正确解析并透传至 Worker 与 Go 引擎"""
        from app.widgets.stress_dialog import StressDialog, StressWorker

        req = SavedRequest(
            name="压测交易接口",
            method="GET",
            url="http://10.111.212.130/api/order",
        )
        dlg = StressDialog(req)

        # 模拟 PAC 模式
        pac_content = """
        function FindProxyForURL(url, host) {
            if (host === '10.111.212.130') {
                return 'PROXY 192.168.66.44:8443';
            }
            return 'DIRECT';
        }
        """
        dlg._proxy_cfg = {
            "mode": "pac",
            "pac_content": pac_content,
        }

        # 捕获启动时的配置
        launched_cfg = None
        orig_worker_start = StressWorker.start
        def mock_start(worker_self):
            nonlocal launched_cfg
            launched_cfg = worker_self.config
        StressWorker.start = mock_start

        try:
            dlg._on_start_stress()
            self.assertIsNotNone(launched_cfg)
            self.assertEqual(launched_cfg.get("proxy_url"), "http://192.168.66.44:8443")

            # 模拟直连模式
            dlg._proxy_cfg = {"mode": "direct"}
            dlg._on_start_stress()
            self.assertEqual(launched_cfg.get("proxy_url"), "direct")
        finally:
            StressWorker.start = orig_worker_start

    def test_key_value_editor_tab_navigation(self):
        """测试 KeyValueEditor 在输入框中按下 Tab / Shift+Tab 时自动导航到下一个/上一个输入框"""
        from app.widgets.request_editor import KeyValueEditor, CellEditWidget
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtCore import QEvent, Qt

        editor = KeyValueEditor("Key", "Value")
        editor.set_data([
            {"key": "Authorization", "value": "Bearer token123"},
        ])
        # 1行数据 + 1行尾部空行 = 2行
        self.assertEqual(editor.table.rowCount(), 2)

        key_widget_0 = editor.table.cellWidget(0, 1)
        val_widget_0 = editor.table.cellWidget(0, 2)
        key_widget_1 = editor.table.cellWidget(1, 1)

        self.assertIsInstance(key_widget_0, CellEditWidget)
        self.assertIsInstance(val_widget_0, CellEditWidget)
        self.assertIsInstance(key_widget_1, CellEditWidget)

        # 1. 在第0行 Key 中模拟 Tab 键按下
        key_widget_0._start_edit()
        self.assertTrue(key_widget_0._editing)

        tab_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)
        handled = key_widget_0.eventFilter(key_widget_0.editor, tab_event)
        self.assertTrue(handled)
        self.assertFalse(key_widget_0._editing)

        # 2. 模拟 Tab 从第0行 Value 导航到第1行 Key
        val_widget_0._start_edit()
        self.assertTrue(val_widget_0._editing)
        handled2 = val_widget_0.eventFilter(val_widget_0.editor, tab_event)
        self.assertTrue(handled2)
        self.assertFalse(val_widget_0._editing)

        # 3. 模拟在第1行 Key 中按下 Shift+Tab (或 Backtab) 导航回到第0行 Value
        backtab_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        key_widget_1._start_edit()
        self.assertTrue(key_widget_1._editing)
        handled3 = key_widget_1.eventFilter(key_widget_1.editor, backtab_event)
        self.assertTrue(handled3)
        self.assertFalse(key_widget_1._editing)

    def test_help_viewer_proxy_and_sniffer_documentation(self):
        """测试帮助文档中已完整补充代理功能、配置示例、无头模式对比与嗅探报表说明"""
        from app.widgets.help_viewer import _build_help_html

        html = _build_help_html()
        # 验证代理模块
        self.assertIn('id="sec-proxy"', html)
        self.assertIn("全场景代理管理与智能调度指南", html)
        self.assertIn("PAC 自动配置脚本模式", html)
        self.assertIn("FindProxyForURL", html)
        self.assertIn("shExpMatch", html)
        self.assertIn("标准 PAC 函数支持清单", html)
        self.assertIn("isInNet", html)
        self.assertIn("dnsDomainIs", html)
        self.assertIn("测试代理连接", html)

        # 验证嗅探模块
        self.assertIn('id="sec-sniffer"', html)
        self.assertIn("无头模式 (Headless)", html)
        self.assertIn("GUI 真实浏览器模式", html)
        self.assertIn("启动真机交互嗅探", html)
        self.assertIn("开始嗅探压测", html)
        self.assertIn("停止真机交互嗅探", html)
        self.assertIn("Network Idle", html)
        self.assertIn("全页面接口耗时排行榜", html)
        self.assertIn("HTTP Timing", html)
        self.assertIn("导出离线 HTML 报告", html)


if __name__ == "__main__":
    unittest.main()
