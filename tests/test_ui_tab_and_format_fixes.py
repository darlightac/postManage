"""UI Bug 修复单元测试：
1. 格式化 JSON 按钮文本完整展示，宽度自适应
2. 标签页占满标签栏时，与新增按钮无重叠，最后一个标签页展示完整且可正常关闭
"""

import sys
import unittest
from PyQt6.QtWidgets import QApplication, QHBoxLayout
from PyQt6.QtCore import Qt

from app.widgets.request_editor import RequestEditor
from app.widgets.request_tabs import RequestTabBar, RequestTabPage
from app.config.i18n import I18nManager

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class TestJsonFormatButton(unittest.TestCase):
    def setUp(self):
        self.editor = RequestEditor()

    def test_json_format_btn_sizing_and_layout(self):
        """测试 1：格式化 JSON 按钮紧凑自适应尺寸，完全展示文字且不过度膨胀"""
        btn = self.editor.json_format_btn
        self.assertEqual(btn.text(), "格式化 JSON")
        
        # 验证按钮高度为紧凑高度 24px
        self.assertEqual(btn.height(), 24)
        
        # 验证按钮宽度能完全容纳文字且尺寸适中紧凑（不冗余膨胀到 130px 以上）
        fm = btn.fontMetrics()
        text_width = fm.horizontalAdvance(btn.text())
        hint_width = btn.sizeHint().width()
        self.assertGreaterEqual(hint_width, text_width)
        self.assertLessEqual(hint_width, 110)

    def test_json_format_btn_i18n(self):
        """测试 2：语言切换为英文后，按钮文本完整展示且尺寸自适应紧凑"""
        mgr = I18nManager()
        mgr.set_language("en")
        try:
            self.editor.retranslate_ui()
            btn = self.editor.json_format_btn
            self.assertEqual(btn.text(), "Format JSON")
            fm = btn.fontMetrics()
            text_width = fm.horizontalAdvance(btn.text())
            hint_width = btn.sizeHint().width()
            self.assertGreaterEqual(hint_width, text_width)
            self.assertLessEqual(hint_width, 110)
        finally:
            mgr.set_language("zh")
            self.editor.retranslate_ui()


class TestTabBarOverlap(unittest.TestCase):
    def setUp(self):
        self.bar = RequestTabBar()
        self.bar.resize(800, 600)
        self.bar.show()

    def test_add_btn_next_to_tab_when_few_tabs(self):
        """测试 3：标签较少时，'+' 按钮紧跟在最后一个标签之后"""
        p1 = RequestTabPage()
        p1.request_editor._request_name = "Tab 1"
        self.bar.add_page(p1)

        p2 = RequestTabPage()
        p2.request_editor._request_name = "Tab 2"
        self.bar.add_page(p2)

        self.bar._reposition_add_btn()
        tb = self.bar.tab_widget.tabBar()
        last_tab_right = tb.tabRect(1).right()
        btn_x = self.bar.add_btn.pos().x()

        # 紧随其后（有少量间隙）
        self.assertGreaterEqual(btn_x, last_tab_right)
        self.assertLessEqual(btn_x, last_tab_right + 20)

    def test_no_overlap_when_tabs_fill_bar(self):
        """测试 4：标签页占满标签栏时，新增按钮位于专属预留区，与标签栏完全零重叠"""
        # 添加大量标签页，使其占满并超出 800px 标签栏
        for i in range(12):
            p = RequestTabPage()
            p.request_editor._request_name = f"Very Long Request Name {i}"
            self.bar.add_page(p)

        self.bar._reposition_add_btn()
        tb = self.bar.tab_widget.tabBar()
        btn = self.bar.add_btn

        # 1. 标签栏宽度必须为新增按钮预留空间（tb 宽度 <= bar 宽度 - 36）
        self.assertLessEqual(tb.width(), self.bar.width() - 36)

        # 2. 新增按钮的左侧坐标必须 >= tb.width()，保证与所有标签页完全零重叠！
        self.assertGreaterEqual(btn.pos().x(), tb.width())

        # 3. 新增按钮必须完整显示在可视窗口内
        self.assertLessEqual(btn.pos().x() + btn.width(), self.bar.width())

        # 4. 最后一个标签页可以正常关闭
        initial_count = self.bar.tab_widget.count()
        last_index = initial_count - 1
        self.bar.tab_widget.tabCloseRequested.emit(last_index)
        self.assertEqual(self.bar.tab_widget.count(), initial_count - 1)


if __name__ == "__main__":
    unittest.main()
