"""Test cURL export auto-generation on tab switch"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
from app.widgets.request_editor import RequestEditor
from app.core.models import HeaderItem, ParamItem


def get_app():
    return QApplication.instance() or QApplication(sys.argv)


def test_curl_export_on_tab_switch():
    app = get_app()
    editor = RequestEditor()

    # Configure request
    editor.method_combo.setCurrentText("POST")
    editor.url_input.setText("https://httpbin.org/post")
    editor.headers_editor.set_data([
        {"enabled": True, "key": "X-Custom-Header", "value": "my-val"}
    ])
    editor.body_type_combo.setCurrentText("json")
    editor.body_edit.setPlainText('{"name": "alice"}')
    editor.auth_type_combo.setCurrentText("bearer")
    editor.auth_token.setText("secret-token-123")

    # Switch to cURL tab directly
    curl_tab_idx = editor.tabs.indexOf(editor.curl_widget)
    editor.tabs.setCurrentIndex(curl_tab_idx)

    curl_text = editor.curl_display.toPlainText()
    print("Exported cURL:\n", curl_text)

    assert "-X POST" in curl_text
    assert "'https://httpbin.org/post'" in curl_text
    assert "-H 'X-Custom-Header: my-val'" in curl_text
    assert "-H 'Content-Type: application/json'" in curl_text
    assert "--data-raw '{\"name\": \"alice\"}'" in curl_text
    assert "-H 'Authorization: Bearer secret-token-123'" in curl_text


def test_curl_query_param_no_duplication():
    app = get_app()
    editor = RequestEditor()

    editor.url_input.setText("https://api.example.com/search?q=postman")
    curl_tab_idx = editor.tabs.indexOf(editor.curl_widget)
    editor.tabs.setCurrentIndex(curl_tab_idx)

    curl_text = editor.curl_display.toPlainText()
    assert "https://api.example.com/search?q=postman" in curl_text
    assert "q=postman&q=postman" not in curl_text


def test_curl_toggle_tab():
    app = get_app()
    editor = RequestEditor()

    curl_tab_idx = editor.tabs.indexOf(editor.curl_widget)
    editor.url_input.setText("https://api.example.com/data")

    # Toggle to curl tab
    editor._on_toggle_curl_tab()
    assert editor.tabs.currentIndex() == curl_tab_idx
    assert "https://api.example.com/data" in editor.curl_display.toPlainText()

    # Toggle again should switch back to Params tab (0)
    editor._on_toggle_curl_tab()
    assert editor.tabs.currentIndex() == 0


def test_curl_auth_apikey_and_cookies():
    app = get_app()
    editor = RequestEditor()

    editor.url_input.setText("https://api.example.com/secure")
    editor.auth_type_combo.setCurrentText("apikey")
    editor.auth_apikey_key.setText("X-API-Key")
    editor.auth_apikey_value.setText("key_12345")
    editor.cookie_manager.set_cookies([
        {"name": "session_id", "value": "abc123xyz", "domain": "api.example.com", "path": "/"}
    ])

    curl_tab_idx = editor.tabs.indexOf(editor.curl_widget)
    editor.tabs.setCurrentIndex(curl_tab_idx)

    curl_text = editor.curl_display.toPlainText()
    assert "-H 'X-API-Key: key_12345'" in curl_text
    assert "--cookie 'session_id=abc123xyz'" in curl_text


if __name__ == "__main__":
    test_curl_export_on_tab_switch()
    test_curl_query_param_no_duplication()
    test_curl_toggle_tab()
    test_curl_auth_apikey_and_cookies()
    print("All cURL export tests passed successfully!")
