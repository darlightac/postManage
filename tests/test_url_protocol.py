"""URL 协议自动补全逻辑单元测试

验证需求：
在输入框输入 https 或其他内容时，不应在 url 前面自动加 http。
仅当用户没有输入协议时，在用户点击发送/执行发送前，才加上默认的 http://。
"""

import sys
import unittest
from PyQt6.QtWidgets import QApplication
from app.widgets.request_editor import RequestEditor
from app.core.models import SavedRequest

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class TestURLProtocol(unittest.TestCase):
    def setUp(self):
        self.editor = RequestEditor()

    def test_typing_https_does_not_prepend_http(self):
        """1. 用户在输入框中输入 'h', 'https', 'https://' 过程中，build_request 不篡改输入框"""
        test_inputs = ["h", "ht", "http", "https", "https:", "https:/", "https://api.example.com"]
        for typing_text in test_inputs:
            self.editor.url_input.setText(typing_text)
            req = self.editor.build_request()
            self.assertEqual(self.editor.url_input.text(), typing_text)
            self.assertEqual(req.url, typing_text)

    def test_typing_plain_domain_does_not_prepend_http_on_build(self):
        """2. 用户输入普通域名但未点击发送前，build_request 不篡改输入框"""
        self.editor.url_input.setText("api.example.com/users")
        req = self.editor.build_request()
        self.assertEqual(self.editor.url_input.text(), "api.example.com/users")
        self.assertEqual(req.url, "api.example.com/users")

    def test_send_prepends_http_when_protocol_missing(self):
        """3. 当用户未输入协议时，点击发送（_on_send）前才自动补齐 http://"""
        self.editor.url_input.setText("127.0.0.1:8080/health")
        
        captured_req = None
        def on_send(req: SavedRequest):
            nonlocal captured_req
            captured_req = req
            
        self.editor.send_requested.connect(on_send)
        self.editor._on_send()
        
        self.assertEqual(self.editor.url_input.text(), "http://127.0.0.1:8080/health")
        self.assertIsNotNone(captured_req)
        self.assertEqual(captured_req.url, "http://127.0.0.1:8080/health")

    def test_send_preserves_https(self):
        """4. 当用户输入了 https:// 时，点击发送绝不重复添加 http://"""
        self.editor.url_input.setText("https://api.github.com/users")
        
        captured_req = None
        def on_send(req: SavedRequest):
            nonlocal captured_req
            captured_req = req
            
        self.editor.send_requested.connect(on_send)
        self.editor._on_send()
        
        self.assertEqual(self.editor.url_input.text(), "https://api.github.com/users")
        self.assertIsNotNone(captured_req)
        self.assertEqual(captured_req.url, "https://api.github.com/users")

    def test_send_preserves_http(self):
        """5. 当用户输入了 http:// 时，点击发送保持原样"""
        self.editor.url_input.setText("http://example.com/test")
        
        captured_req = None
        def on_send(req: SavedRequest):
            nonlocal captured_req
            captured_req = req
            
        self.editor.send_requested.connect(on_send)
        self.editor._on_send()
        
        self.assertEqual(self.editor.url_input.text(), "http://example.com/test")
        self.assertIsNotNone(captured_req)
        self.assertEqual(captured_req.url, "http://example.com/test")

    def test_send_empty_url(self):
        """6. 输入为空时，点击发送不添加 http://"""
        self.editor.url_input.setText("")
        captured_req = None
        def on_send(req: SavedRequest):
            nonlocal captured_req
            captured_req = req
            
        self.editor.send_requested.connect(on_send)
        self.editor._on_send()
        
        self.assertEqual(self.editor.url_input.text(), "")
        self.assertIsNotNone(captured_req)
        self.assertEqual(captured_req.url, "")


if __name__ == "__main__":
    unittest.main()
