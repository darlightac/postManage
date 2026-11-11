"""UI 改进与标签页尺寸优化自动化测试"""

import sys
import os

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics, QFont

# 初始化 Qt 应用（无头测试）
app = QApplication.instance() or QApplication(sys.argv)

from app.config.themes import ThemeManager, get_method_color
from app.widgets.request_tabs import create_method_badge_icon, make_tab_title, RequestTabBar, RequestTabPage
from app.widgets.request_editor import RequestEditor
from app.widgets.response_viewer import ResponseViewer
from app.core.models import HTTPResponse, HeaderItem, ParamItem


def test_method_badge_generation():
    """测试各 HTTP 方法彩色徽章生成"""
    methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
    for is_dark in (False, True):
        for m in methods:
            icon = create_method_badge_icon(m, is_dark=is_dark)
            assert not icon.isNull(), f"方法 {m} 生成的图标为空"
    print("✓ [UI Test 1] HTTP 方法彩色徽章生成与缓存测试通过")


def test_tab_title_length_reasonable():
    """测试标签页标题长度合理性（废弃原 5 字符截断缺陷）"""
    page = RequestTabPage()
    
    # 场景 1：中等长度中文名称
    page.request_editor._request_name = "获取用户详细资料"
    title1 = make_tab_title(page)
    assert title1 == "获取用户详细资料", f"标题不应被截断为 5 字符，实际为: {title1}"

    # 场景 2：API 路径名称
    page.request_editor._request_name = ""
    page.request_editor.url_input.setText("https://api.example.com/v1/orders/detail?id=123")
    title2 = make_tab_title(page)
    assert "api.example.com/v1/orders/detail" in title2, f"路径展示异常: {title2}"
    print("✓ [UI Test 2] 标签页标题展示尺寸合理性测试通过")


def test_request_tab_bar_features():
    """测试 RequestTabBar 徽章联动与 ToolTip 提示"""
    tab_bar = RequestTabBar()
    assert tab_bar.tab_widget.objectName() == "requestTabWidget"
    assert tab_bar.tab_widget.elideMode() == Qt.TextElideMode.ElideRight

    page = RequestTabPage()
    page.request_editor.method_combo.setCurrentText("POST")
    page.request_editor._request_name = "创建新订单"
    page.request_editor.url_input.setText("https://api.example.com/orders")

    idx = tab_bar.add_page(page, "临时标题")
    
    # 验证文字与图标设置
    tab_text = tab_bar.tab_widget.tabText(idx)
    assert tab_text == "创建新订单"
    icon = tab_bar.tab_widget.tabIcon(idx)
    assert not icon.isNull()

    # 验证 ToolTip 包含完整方法与 URL
    tooltip = tab_bar.tab_widget.tabToolTip(idx)
    assert "[POST] 创建新订单" in tooltip
    assert "https://api.example.com/orders" in tooltip

    # 验证方法切换后刷新
    page.request_editor.method_combo.setCurrentText("DELETE")
    tab_bar.refresh_title(page)
    assert "[DELETE] 创建新订单" in tab_bar.tab_widget.tabToolTip(idx)
    print("✓ [UI Test 3] RequestTabBar 徽章与 ToolTip 动态联动测试通过")


def test_editor_subtabs_and_badges():
    """测试 RequestEditor 子标签页与条目数量角标联动"""
    editor = RequestEditor()
    assert editor.tabs.objectName() == "editorSubTabs"

    # 默认状态
    assert editor.tabs.tabText(0) == "Params"
    assert editor.tabs.tabText(1) == "Headers"
    assert editor.tabs.tabText(3) == "Body"

    # 添加 Params
    editor.params_editor.set_data([
        ParamItem(enabled=True, key="page", value="1"),
        ParamItem(enabled=True, key="size", value="20"),
    ])
    assert editor.tabs.tabText(0) == "Params (2)"

    # 添加 Headers
    editor.headers_editor.set_data([
        HeaderItem(enabled=True, key="Authorization", value="Bearer token"),
    ])
    assert editor.tabs.tabText(1) == "Headers (1)"

    # 切换 Body 类型
    editor.body_type_combo.setCurrentText("json")
    assert editor.tabs.tabText(3) == "Body (json)"

    # 切换 Auth 类型
    editor.auth_type_combo.setCurrentText("bearer")
    assert editor.tabs.tabText(4) == "Auth (bearer)"

    print("✓ [UI Test 4] RequestEditor 子标签页条目数量角标测试通过")


def test_response_viewer_pill_badges():
    """测试 ResponseViewer 状态栏胶囊徽章与 Headers 角标"""
    viewer = ResponseViewer()
    assert viewer.tabs.objectName() == "responseSubTabs"
    assert "未请求" in viewer.status_label.text()

    resp = HTTPResponse(
        status_code=200,
        reason="OK",
        headers={"Content-Type": "application/json", "X-Request-Id": "abc-123"},
        body='{"success": true}',
        elapsed_ms=45.2,
    )
    viewer.set_response(resp)

    # 胶囊徽章
    assert "200 OK" in viewer.status_label.text()
    assert "45 ms" in viewer.time_label.text()
    assert viewer.tabs.tabText(2) == "Headers (2)"

    # 清空后复原
    viewer.clear()
    assert "未请求" in viewer.status_label.text()
    assert viewer.tabs.tabText(2) == "Headers"
    print("✓ [UI Test 5] ResponseViewer 胶囊徽章与 Headers 响应角标测试通过")


if __name__ == "__main__":
    print("=" * 60)
    print("开始执行 UI 界面与标签页合理尺寸优化自动化验证测试")
    print("=" * 60)
    test_method_badge_generation()
    test_tab_title_length_reasonable()
    test_request_tab_bar_features()
    test_editor_subtabs_and_badges()
    test_response_viewer_pill_badges()
    print("=" * 60)
    print("🎉 全部 UI 与标签页优化测试通过！")
    print("=" * 60)
