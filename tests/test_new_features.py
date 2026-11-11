"""自动化测试套件：新特性验证
1. 浅色主题配色方案优化（去除荧光感，护眼低饱和）
2. 全局请求头（Global Headers）配置与优先级覆盖（大小写不敏感覆盖）
3. 帮助文档中全局请求头说明
4. 语言切换机制（I18nManager 中英文无缝切换与翻译覆盖）
5. cURL 导出合并全局请求头
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 确保控制台输出编码兼容
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 添加项目根目录到 sys.path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from PyQt6.QtWidgets import QApplication
# 创建全局 QApplication 实例供测试使用
app = QApplication.instance() or QApplication(sys.argv)

from app.config.themes import LightTheme, ThemeManager
from app.config.settings import Settings
from app.config.i18n import I18nManager, tr
from app.core.models import SavedRequest, HeaderItem
from app.core.http_client import HTTPClient
from app.widgets.help_viewer import _build_help_html
from app.widgets.request_editor import RequestEditor


class TestNewFeatures(unittest.TestCase):

    def test_01_light_theme_palette(self):
        """测试 1：浅色主题配色方案低饱和度优化，荧光色已彻底移除"""
        theme = LightTheme()
        # 验证旧的高荧光色已不再使用
        self.assertNotIn("#0cbb52", theme.method_colors.values(), "旧荧光绿 #0cbb52 仍存在！")
        self.assertNotIn("#f59e0b", theme.method_colors.values(), "旧荧光橙 #f59e0b 仍存在！")
        
        # 验证新的低饱和、清晰护眼配色方案
        self.assertEqual(theme.method_colors.get("GET"), "#15803d")
        self.assertEqual(theme.method_colors.get("POST"), "#b45309")
        self.assertEqual(theme.method_colors.get("PUT"), "#1d4ed8")
        self.assertEqual(theme.method_colors.get("DELETE"), "#b91c1c")
        self.assertEqual(theme.method_colors.get("PATCH"), "#6d28d9")
        self.assertEqual(theme.name, "light")
        self.assertEqual(theme.bg_sidebar, "#f4f5f7")
        print("[PASS] Light theme low saturation palette verified")

    def test_02_i18n_switching_and_translation(self):
        """测试 2：I18nManager 动态语言切换与多语言翻译覆盖"""
        i18n = I18nManager()
        i18n.set_language("zh")  # 统一基准状态

        received_languages = []

        def on_lang_changed(lang):
            received_languages.append(lang)

        i18n.language_changed.connect(on_lang_changed)

        # 切换到英文
        i18n.set_language("en")
        self.assertEqual(i18n.current_language, "en")
        self.assertEqual(tr("btn_global_headers"), "🌐 Global Headers")
        self.assertEqual(tr("btn_send"), "Send")
        self.assertEqual(tr("menu_language"), "Language(&L)")
        self.assertIn("en", received_languages)

        # 切换回中文
        i18n.set_language("zh")
        self.assertEqual(i18n.current_language, "zh")
        self.assertEqual(tr("btn_global_headers"), "🌐 全局请求头")
        self.assertEqual(tr("btn_send"), "发送")
        self.assertEqual(tr("menu_language"), "语言(&L)")
        self.assertIn("zh", received_languages)

        # 未知键回退为其自身
        self.assertEqual(tr("non_existent_key_xyz"), "non_existent_key_xyz")
        print("[PASS] i18n switching and translation dictionary verified")

    def test_03_global_headers_priority_in_http_client(self):
        """测试 3：全局请求头合并与单个请求同名 Header 优先覆盖（大小写不敏感）"""
        client = HTTPClient()
        settings = Settings()
        orig_global_headers = settings.global_headers

        try:
            # 1. 设置全局请求头
            settings.global_headers = [
                {"key": "X-Global-Only", "value": "global-123", "enabled": True},
                {"key": "Authorization", "value": "Bearer global-token", "enabled": True},
                {"key": "X-Conflict-Case", "value": "global-val", "enabled": True},
                {"key": "X-Disabled-Global", "value": "should-not-exist", "enabled": False},
            ]

            # 2. 单个请求中指定同名或不同大小写的 Header 进行覆盖
            req = SavedRequest(
                url="https://api.example.com/data",
                method="GET",
                headers=[
                    HeaderItem(key="authorization", value="Bearer request-token", enabled=True),
                    HeaderItem(key="x-conflict-case", value="request-val", enabled=True),
                    HeaderItem(key="X-Request-Only", value="req-456", enabled=True),
                ]
            )

            captured_headers = {}

            # 模拟 httpx.Client.request 拦截 headers
            def mock_request(method, url, **kwargs):
                nonlocal captured_headers
                captured_headers = kwargs.get("headers") or {}
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.content = b'{"status": "ok"}'
                mock_resp.text = '{"status": "ok"}'
                mock_resp.headers = {}
                mock_resp.cookies = {}
                mock_resp.http_version = "HTTP/1.1"
                return mock_resp

            with patch("httpx.Client.request", side_effect=mock_request), \
                 patch("app.core.go_engine.GoEngineManager.ensure_started", return_value=False):
                resp = client.send(req)
                self.assertIsNone(resp.error)

            # 3. 验证优先级和覆盖规则：
            # (a) 全局未冲突的 Header 应被携带
            self.assertEqual(captured_headers.get("X-Global-Only"), "global-123")

            # (b) 单请求配置的同名（大小写不敏感）Header 应以单请求为准
            # 检查大小写覆盖：字典中不应留存全局键，且值必须是单请求的值
            self.assertIn("authorization", captured_headers)
            self.assertNotIn("Authorization", captured_headers)
            self.assertEqual(captured_headers.get("authorization"), "Bearer request-token")

            self.assertIn("x-conflict-case", captured_headers)
            self.assertNotIn("X-Conflict-Case", captured_headers)
            self.assertEqual(captured_headers.get("x-conflict-case"), "request-val")

            # (c) 单请求专属 Header 应被携带
            self.assertEqual(captured_headers.get("X-Request-Only"), "req-456")

            # (d) 禁用的全局 Header 不应被携带
            self.assertNotIn("X-Disabled-Global", captured_headers)
            self.assertNotIn("x-disabled-global", captured_headers)

            print("[PASS] Global headers priority and case-insensitive override in HTTPClient verified")
        finally:
            settings.global_headers = orig_global_headers

    def test_04_curl_export_with_global_headers(self):
        """测试 4：cURL 导出时自动合并全局请求头并遵守单请求优先原则"""
        settings = Settings()
        orig_global_headers = settings.global_headers

        try:
            settings.global_headers = [
                {"key": "X-Global-Tenant", "value": "tenant-001", "enabled": True},
                {"key": "Accept-Language", "value": "zh-CN", "enabled": True},
                {"key": "X-Disabled-Header", "value": "no", "enabled": False},
            ]

            editor = RequestEditor()
            editor.url_input.setText("https://api.test.com/v1/users")
            editor.method_combo.setCurrentText("POST")
            # 单请求覆盖 Accept-Language，新增 User-Agent
            editor.headers_editor.set_data([
                HeaderItem(key="Accept-Language", value="en-US", enabled=True),
                HeaderItem(key="User-Agent", value="PostManage-Test", enabled=True),
            ])

            # 执行 cURL 导出
            editor._on_export_curl()
            curl_text = editor.curl_display.toPlainText()

            # 验证 cURL 命令内容
            self.assertIn("-X POST", curl_text)
            self.assertIn("'https://api.test.com/v1/users'", curl_text)
            self.assertIn("-H 'X-Global-Tenant: tenant-001'", curl_text)
            self.assertIn("-H 'Accept-Language: en-US'", curl_text)
            self.assertNotIn("zh-CN", curl_text)
            self.assertNotIn("X-Disabled-Header", curl_text)
            self.assertIn("-H 'User-Agent: PostManage-Test'", curl_text)

            print("[PASS] cURL export with merged global headers verified")
        finally:
            settings.global_headers = orig_global_headers

    def test_05_help_documentation(self):
        """测试 5：帮助文档中包含全局请求头说明章节与优先级解释"""
        help_html = _build_help_html()
        self.assertIn("全局请求头", help_html)
        self.assertIn("覆盖", help_html)
        self.assertIn("大小写不敏感", help_html)
        print("[PASS] Help viewer global headers documentation verified")

    def test_06_global_headers_tab_in_request_editor(self):
        """测试 6：全局请求头作为独立 Tab 紧跟在 cURL Export 之后，与其他 Tab 风格一致"""
        from PyQt6.QtCore import Qt
        settings = Settings()
        orig_global_headers = settings.global_headers

        try:
            settings.global_headers = [
                {"key": "X-Common-Auth", "value": "Bearer abc", "enabled": True},
                {"key": "X-Tenant-Id", "value": "tenant-99", "enabled": True},
            ]

            editor = RequestEditor()

            # 1. 验证 Tab 数量与相对位置：cURL Export 紧随其后为全局请求头
            self.assertEqual(editor.tabs.count(), 9)
            curl_idx = editor.tabs.indexOf(editor.curl_widget)
            gh_idx = editor.tabs.indexOf(editor.global_headers_widget)
            self.assertEqual(gh_idx, curl_idx + 1)

            # 2. 验证右侧角标 CornerWidget 已经移除（不再突兀出现在右上角）
            self.assertIsNone(editor.tabs.cornerWidget(Qt.Corner.TopRightCorner))

            # 3. 验证全局请求头 Tab 标题及其角标（与其他 Tab 风格保持一致，如 Headers (2)）
            tab_title = editor.tabs.tabText(gh_idx)
            self.assertIn("全局请求头", tab_title)
            self.assertIn("(2)", tab_title)

            # 4. 验证 Tab 内部组件完整性（提示栏、清空按钮、保存按钮、KeyValueEditor）
            self.assertTrue(hasattr(editor, 'gh_tip_label'))
            self.assertTrue(hasattr(editor, 'gh_clear_btn'))
            self.assertTrue(hasattr(editor, 'gh_save_btn'))
            self.assertTrue(hasattr(editor, 'global_headers_editor'))

            # 5. 验证快捷切换方法
            editor.switch_to_global_headers_tab()
            self.assertEqual(editor.tabs.currentIndex(), gh_idx)

            # 6. 验证在全局请求头编辑器中修改数据后，自动同步至 Settings 并刷新角标
            editor.global_headers_editor.set_data([
                {"key": "X-New-Global", "value": "123", "enabled": True},
            ])
            updated_settings = Settings().global_headers
            self.assertEqual(len(updated_settings), 1)
            self.assertEqual(updated_settings[0]["key"], "X-New-Global")
            self.assertIn("(1)", editor.tabs.tabText(gh_idx))

            # 7. 验证多语言切换为英文时，Tab 标题同步刷新为 Global Headers (1)
            i18n = I18nManager()
            i18n.set_language("en")
            editor.retranslate_ui()
            self.assertIn("Global Headers (1)", editor.tabs.tabText(gh_idx))

            # 切回中文
            i18n.set_language("zh")
            editor.retranslate_ui()
            self.assertIn("全局请求头 (1)", editor.tabs.tabText(gh_idx))

            print("[PASS] Global headers tab position, style consistency, and auto-sync verified")
        finally:
            settings.global_headers = orig_global_headers


def run_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestNewFeatures)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
