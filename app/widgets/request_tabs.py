"""请求标签页管理组件 - 类似浏览器的多请求 tab 页"""

import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QSplitter, QLabel, QLineEdit,
    QMenu, QInputDialog,
)
from PyQt6.QtCore import pyqtSignal, Qt, QPoint, QTimer, QEvent
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPixmap, QFont, QIcon

from app.widgets.request_editor import RequestEditor
from app.widgets.response_viewer import ResponseViewer
from app.core.models import generate_id
from app.config.themes import ThemeManager


_METHOD_BADGE_CACHE = {}


def create_method_badge_icon(method: str, is_dark: bool = False) -> QIcon:
    """生成高清晰度 HTTP 方法彩色徽章图标"""
    method = (method or "GET").upper().strip()
    cache_key = (method, is_dark)
    if cache_key in _METHOD_BADGE_CACHE:
        return _METHOD_BADGE_CACHE[cache_key]

    # 配色方案 (背景色, 文字色)
    if not is_dark:
        palette = {
            "GET": ("#dcfce7", "#15803d"),
            "POST": ("#fef3c7", "#b45309"),
            "PUT": ("#dbeafe", "#1d4ed8"),
            "DELETE": ("#fee2e2", "#b91c1c"),
            "PATCH": ("#f3e8ff", "#6d28d9"),
            "HEAD": ("#f1f5f9", "#475569"),
            "OPTIONS": ("#cffafe", "#0e7490"),
        }
        default_colors = ("#f3f4f6", "#4b5563")
    else:
        palette = {
            "GET": ("#133824", "#49cc90"),
            "POST": ("#3d2806", "#fca130"),
            "PUT": ("#172b4d", "#60a5fa"),
            "DELETE": ("#3b1414", "#f87171"),
            "PATCH": ("#2e184d", "#a78bfa"),
            "HEAD": ("#242c38", "#94a3b8"),
            "OPTIONS": ("#102d42", "#38bdf8"),
        }
        default_colors = ("#2d3748", "#cbd5e1")

    bg_color, text_color = palette.get(method, default_colors)
    disp_text = "DEL" if method == "DELETE" else ("OPT" if method == "OPTIONS" else method)

    w, h = 38, 18
    scale = 2
    pix = QPixmap(w * scale, h * scale)
    pix.fill(Qt.GlobalColor.transparent)
    pix.setDevicePixelRatio(scale)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(bg_color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, w, h, 4, 4)

    font = QFont("Segoe UI", 8, QFont.Weight.Bold)
    font.setPixelSize(10)
    painter.setFont(font)
    painter.setPen(QColor(text_color))
    painter.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, disp_text)
    painter.end()

    icon = QIcon(pix)
    _METHOD_BADGE_CACHE[cache_key] = icon
    return icon


class NameLineEdit(QLineEdit):
    """请求名输入框：默认只读展示，双击进入编辑态"""

    double_clicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        if self.isReadOnly():
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class RequestTabPage(QWidget):
    """单个标签页：请求名栏 + 上方请求编辑器 + 下方响应查看器"""

    save_requested = pyqtSignal()  # 点击保存按钮（保存到集合）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tab_id = generate_id()  # 唯一标识，用于 open_tabs 持久化
        self.request_id = None  # 关联的已保存请求 ID（用于去重打开）
        self._name_editing = False  # 是否处于铅笔触发的编辑态
        self._edit_start_text = ""  # 进入编辑态时的文本（用于判断是否改动）

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ─── 请求名栏：左侧名称(靛蓝可双击编辑)、右侧保存 ───
        name_bar = QWidget()
        name_bar_layout = QHBoxLayout(name_bar)
        name_bar_layout.setContentsMargins(8, 2, 8, 2)
        name_bar_layout.setSpacing(6)

        self.request_name_input = NameLineEdit()
        self.request_name_input.setPlaceholderText("未命名请求（双击可命名）")
        self.request_name_input.setReadOnly(True)  # 默认展示态，双击才进入编辑，离焦保存
        self.request_name_input.setToolTip("双击修改请求名称，离焦自动保存")
        self.request_name_input.setCursor(Qt.CursorShape.PointingHandCursor)
        self.request_name_input.double_clicked.connect(self._on_edit_name)
        self.request_name_input.setStyleSheet("""
            QLineEdit {
                border: none;
                background: transparent;
                color: #3F51B5;
                padding: 4px 8px;
                font-size: 13px;
                font-weight: 500;
            }
        """)
        name_bar_layout.addWidget(self.request_name_input, 1)

        # 代理按钮：放置在保存按钮前面
        self.proxy_btn = QPushButton("🌐 代理")
        self.proxy_btn.setFixedSize(76, 28)
        self.proxy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.proxy_btn.clicked.connect(self._on_open_proxy_dialog)
        name_bar_layout.addWidget(self.proxy_btn)

        # 保存按钮：现代蓝底白字
        self.save_btn = QPushButton("保存")
        self.save_btn.setFixedSize(68, 28)
        self.save_btn.setToolTip("将当前请求保存到集合 (Ctrl+S)")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                font-weight: 500;
                font-size: 13px;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:pressed { background-color: #1d4ed8; }
        """)
        self.save_btn.clicked.connect(self.save_requested.emit)
        name_bar_layout.addWidget(self.save_btn)

        layout.addWidget(name_bar)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.request_editor = RequestEditor()
        self.response_viewer = ResponseViewer()

        self.splitter.addWidget(self.request_editor)
        self.splitter.addWidget(self.response_viewer)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)

        layout.addWidget(self.splitter)

    def _on_edit_name(self):
        """双击名称：进入编辑态，离焦/回车后保存"""
        self._name_editing = True
        self._edit_start_text = self.request_name_input.text()
        self.request_name_input.setReadOnly(False)
        self.request_name_input.setCursor(Qt.CursorShape.IBeamCursor)
        self.request_name_input.setFocus()
        self.request_name_input.selectAll()

    def refresh_name_display(self):
        """名称栏显示请求名全称；无名称时默认显示 URL（回到展示态）"""
        name = self.request_editor._request_name
        url = self.request_editor.url_input.text().strip()
        display = name if name else url
        self.request_name_input.blockSignals(True)
        self.request_name_input.setText(display)
        self.request_name_input.blockSignals(False)
        self.request_name_input.setReadOnly(True)
        self.request_name_input.setCursor(Qt.CursorShape.PointingHandCursor)
        self._name_editing = False
        self.refresh_proxy_button_state()

    def _on_open_proxy_dialog(self):
        """点击代理按钮：弹出当前接口的专属代理配置对话框"""
        from app.widgets.proxy_dialog import RequestProxyDialog
        current_cfg = getattr(self.request_editor, "proxy_config", {}) or {}
        dlg = RequestProxyDialog(current_cfg, self)
        if dlg.exec():
            new_cfg = dlg.get_result()
            self.request_editor.proxy_config = new_cfg
            self.refresh_proxy_button_state()
            # 触发防抖保存标签页状态
            main_win = self.window()
            if hasattr(main_win, "_trigger_tab_save"):
                main_win._trigger_tab_save(self)

    def refresh_proxy_button_state(self):
        """刷新代理按钮的外观状态与提示"""
        try:
            cfg = getattr(self.request_editor, "proxy_config", {}) or {}
            mode = cfg.get("mode", "default")
            t = ThemeManager.current()
            is_dark = (getattr(t, "name", "light") == "dark")

            if mode in ("default", "", None):
                # 跟随全局策略（中性简洁风格）
                self.proxy_btn.setText("🌐 代理")
                bg = "#334155" if is_dark else "#f1f5f9"
                color = "#cbd5e1" if is_dark else "#475569"
                border = "#475569" if is_dark else "#cbd5e1"
                self.proxy_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {bg};
                        color: {color};
                        font-size: 12px;
                        font-weight: 500;
                        border: 1px solid {border};
                        border-radius: 5px;
                        padding: 0 4px;
                    }}
                    QPushButton:hover {{
                        background-color: {"#475569" if is_dark else "#e2e8f0"};
                        color: {"#ffffff" if is_dark else "#1e293b"};
                    }}
                """)
                self.proxy_btn.setToolTip("接口代理配置 (当前: 跟随全局代理策略)\n点击自定义当前接口专属代理")
            else:
                # 接口覆盖了全局代理，使用高亮强调色标识
                mode_names = {
                    "none": "直连",
                    "direct": "直连",
                    "system": "系统代理",
                    "custom": "自定义",
                    "manual": "自定义",
                    "pac": "PAC模式",
                }
                mode_desc = mode_names.get(mode, mode)
                self.proxy_btn.setText(f"🌐 {mode_desc}")
                self.proxy_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #059669;
                        color: #ffffff;
                        font-size: 12px;
                        font-weight: bold;
                        border: none;
                        border-radius: 5px;
                        padding: 0 4px;
                    }
                    QPushButton:hover { background-color: #047857; }
                    QPushButton:pressed { background-color: #065f46; }
                """)
                self.proxy_btn.setToolTip(f"接口代理配置 (已自定义: {mode_desc}，优先于全局生效)\n点击修改代理策略")
        except Exception:
            pass

    def apply_theme(self, t):
        """应用主题到页内所有组件"""
        self.request_editor.apply_theme(t)
        self.response_viewer.apply_theme(t)
        # 请求名：靛蓝色表示可编辑，无边框无背景
        self.request_name_input.setStyleSheet(f"""
            QLineEdit {{
                border: none;
                background: transparent;
                color: {t.text_name};
                padding: 3px 6px;
                font-size: 13px;
            }}
        """)
        self.refresh_proxy_button_state()

    def retranslate_ui(self):
        """刷新界面语言"""
        from app.config.i18n import tr
        self.save_btn.setText(tr("btn_save"))
        self.request_name_input.setPlaceholderText(tr("placeholder_untitled"))
        self.refresh_proxy_button_state()
        if hasattr(self.request_editor, 'retranslate_ui'):
            self.request_editor.retranslate_ui()


def elide_text(text: str, fm: QFontMetrics, max_width: int) -> str:
    """按像素宽度截断文本，超出部分以省略号结尾"""
    if not text or fm.horizontalAdvance(text) <= max_width:
        return text
    for i in range(len(text), 0, -1):
        candidate = text[:i] + "…"
        if fm.horizontalAdvance(candidate) <= max_width:
            return candidate
    return "…"


def make_tab_title(page: RequestTabPage, fm: QFontMetrics = None) -> str:
    """生成标签页标题，合理保留请求名或路径，由 Qt 按照标签实际宽度弹性省略"""
    from app.config.i18n import tr
    name = page.request_editor._request_name
    url = page.request_editor.url_input.text().strip()
    raw = name if name else url
    if not raw:
        return tr("menu_new_request", "新建请求")
    if not name:
        # URL 去掉协议头与查询串，保留清晰的 API 路径
        raw = re.sub(r'^https?://', '', raw).split('?')[0].rstrip('/')
    if fm is not None:
        # 允许展示宽度约 14 个汉字或 28 个字符（配合 max-width: 200px）
        raw = elide_text(raw, fm, fm.horizontalAdvance("汉") * 14)
    return raw or "新请求"


class AddTabButton(QPushButton):
    """新建标签页按钮：自绘白色十字，避免加号字符被字体误渲染"""

    def paintEvent(self, event):
        # 不绘制文字，仅绘制蓝底与白色十字线（不调用 super，跳过默认文字绘制）
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isDown():
            bg = "#2f6ab0"
        elif self.underMouse():
            bg = "#3a7bc8"
        else:
            bg = "#4a90d9"
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 4, 4)
        pen = QPen(QColor("#ffffff"))
        pen.setWidth(2)
        p.setPen(pen)
        cx, cy = self.width() // 2, self.height() // 2
        p.drawLine(cx - 5, cy, cx + 5, cy)
        p.drawLine(cx, cy - 5, cx, cy + 5)
        p.end()


class RequestTabWidget(QTabWidget):
    """自定义 TabWidget：为右侧保留独立安全区域放置 '+' 按钮，确保标签页填满时绝不覆盖最后一个标签页及其关闭按钮"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._reserved_right_width = 38  # 为右侧 '+' 按钮预留的专属宽度

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._adjust_tab_bar_width()

    def event(self, e):
        res = super().event(e)
        if e.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Show):
            self._adjust_tab_bar_width()
        return res

    def _adjust_tab_bar_width(self):
        tb = self.tabBar()
        if tb:
            target_w = max(0, self.width() - self._reserved_right_width)
            if tb.width() != target_w:
                tb.resize(target_w, tb.height())

    def paintEvent(self, event):
        super().paintEvent(event)
        tb = self.tabBar()
        if tb and self.width() > tb.width():
            from app.config.themes import ThemeManager
            t = ThemeManager.current()
            p = QPainter(self)
            bar_h = tb.height()
            r_w = self.width() - tb.width()
            p.fillRect(tb.width(), 0, r_w, bar_h, QColor(t.bg_secondary))
            p.setPen(QColor(t.border_light))
            p.drawLine(tb.width(), bar_h - 1, self.width(), bar_h - 1)
            p.end()


class RequestTabBar(QWidget):
    """请求标签页栏：管理多个 RequestTabPage"""

    new_tab_requested = pyqtSignal()          # 点击 "+" 按钮
    page_cleared = pyqtSignal()               # 最后一个标签页被清空
    duplicate_tab_requested = pyqtSignal(int)  # 复制标签页（传入 tab index）
    set_timeout_requested = pyqtSignal(int)    # 设置超时时间（传入 tab index）
    tab_closed = pyqtSignal(str)               # 关闭标签页（传入 tab_id）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tab_widget = RequestTabWidget(self)
        self.tab_widget.setObjectName("requestTabWidget")
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setElideMode(Qt.TextElideMode.ElideRight)
        self.tab_widget.tabCloseRequested.connect(self._on_close_requested)
        self.tab_widget.tabBar().tabMoved.connect(lambda *_: self._reposition_add_btn())
        self.tab_widget.currentChanged.connect(lambda *_: self._reposition_add_btn())
        # 安装事件过滤器，拦截标签栏右键事件
        self.tab_widget.tabBar().installEventFilter(self)

        # "+" 按钮：紧跟在最后一个标签页后面，蓝底白十字（自绘，悬浮于标签栏上方）
        self.add_btn = AddTabButton(self)
        self.add_btn.setFixedSize(26, 22)
        self.add_btn.setToolTip("新建请求标签页 (Ctrl+N)")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setStyleSheet("background: transparent; border: none;")
        self.add_btn.clicked.connect(self.new_tab_requested.emit)

        layout.addWidget(self.tab_widget)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_add_btn()

    def showEvent(self, event):
        super().showEvent(event)
        self._reposition_add_btn()

    def _reposition_add_btn(self):
        """将 "+" 按钮移动到合适位置：未满时紧跟最后一个标签页，填满时固定展示在最右侧专属预留区，绝不与标签页重叠"""
        self.tab_widget._adjust_tab_bar_width()
        bar = self.tab_widget.tabBar()
        if bar.width() <= 0:
            return
        count = self.tab_widget.count()

        # 检测是否有可见的滚动按钮
        scroll_btn_w = 0
        from PyQt6.QtWidgets import QToolButton
        for btn in bar.findChildren(QToolButton):
            if btn.isVisible():
                scroll_btn_w = max(scroll_btn_w, btn.width())

        btn_w = self.add_btn.width()
        btn_h = self.add_btn.height()
        y = max(0, (bar.height() - btn_h) // 2)

        if count > 0:
            r = bar.tabRect(count - 1)
            candidate_x = r.right() + 8
        else:
            candidate_x = 4

        # 安全边界：bar 内部如果放不下（或者出现滚动条），则停靠在 tabBar 右侧预留的专属安全区域
        max_x_in_bar = bar.width() - btn_w - (scroll_btn_w + 4 if scroll_btn_w > 0 else 4)

        if scroll_btn_w == 0 and candidate_x <= max_x_in_bar:
            # 未填满且无滚动：紧跟在最后一个 tab 之后
            target_pt = bar.mapTo(self, QPoint(candidate_x, y))
        else:
            # 填满或出现滚动条：放置在 tabBar 右侧专属保留区，永不覆盖 tab 与关闭按钮
            target_pt = bar.mapTo(self, QPoint(bar.width() + 6, y))

        self.add_btn.setVisible(True)
        self.add_btn.move(target_pt)
        self.add_btn.raise_()

    # ─── 标签页管理 ───────────────────────────────────────────

    def add_page(self, page: RequestTabPage, title: str = "新请求") -> int:
        """添加标签页并切换过去"""
        index = self.tab_widget.addTab(page, title)
        self.tab_widget.setCurrentIndex(index)
        self.refresh_title(page)
        self._reposition_add_btn()
        # addTab 后标签栏布局尚未完成，延迟到事件循环重新定位，避免按钮与新 tab 重合
        QTimer.singleShot(0, self._reposition_add_btn)
        return index

    def current_page(self) -> RequestTabPage:
        """当前标签页"""
        return self.tab_widget.currentWidget()

    def page_count(self) -> int:
        return self.tab_widget.count()

    def find_page_by_request_id(self, request_id: str):
        """查找已打开指定请求的标签页"""
        if not request_id:
            return None
        for i in range(self.tab_widget.count()):
            page = self.tab_widget.widget(i)
            if isinstance(page, RequestTabPage) and page.request_id == request_id:
                return page
        return None

    def activate_page(self, page: RequestTabPage):
        """切换到指定标签页"""
        self.tab_widget.setCurrentWidget(page)

    def refresh_title(self, page: RequestTabPage):
        """根据页内容刷新标签页标题、方法徽章与完整提示"""
        index = self.tab_widget.indexOf(page)
        if index >= 0:
            fm = QFontMetrics(self.tab_widget.tabBar().font())
            self.tab_widget.setTabText(index, make_tab_title(page, fm))
            method = page.request_editor.method_combo.currentText()
            from app.config.themes import ThemeManager
            is_dark = ThemeManager.current().name == "dark"
            self.tab_widget.setTabIcon(index, create_method_badge_icon(method, is_dark))

            name = page.request_editor._request_name
            url = page.request_editor.url_input.text().strip()
            display_name = name or url or "新请求"
            tooltip = f"[{method}] {display_name}"
            if url and name:
                tooltip += f"\n{url}"
            self.tab_widget.setTabToolTip(index, tooltip)

    def _on_close_requested(self, index: int):
        """关闭标签页；只剩一个时清空内容而不是关闭"""
        page = self.tab_widget.widget(index)
        if self.tab_widget.count() <= 1:
            if isinstance(page, RequestTabPage):
                # 最后一个标签页清空时，也删除持久化记录（相当于重置）
                self.tab_closed.emit(page.tab_id)
                page.tab_id = generate_id()  # 重新分配 ID
                page.request_editor.clear_editor()
                page.response_viewer.clear()
                page.request_id = None
                page.refresh_name_display()
                self.refresh_title(page)
                self.page_cleared.emit()
            return
        if isinstance(page, RequestTabPage):
            self.tab_closed.emit(page.tab_id)
        self.tab_widget.removeTab(index)
        page.deleteLater()
        self._reposition_add_btn()
        QTimer.singleShot(0, self._reposition_add_btn)

    def eventFilter(self, obj, event):
        """拦截标签栏右键事件，并在尺寸变动时保持 '+' 按钮位置准确"""
        from PyQt6.QtCore import QEvent
        if obj is self.tab_widget.tabBar():
            if event.type() == QEvent.Type.ContextMenu:
                tab_index = self.tab_widget.tabBar().tabAt(event.pos())
                if tab_index >= 0:
                    self._show_context_menu(tab_index, event.globalPos())
                return True
            elif event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                self._reposition_add_btn()
        return super().eventFilter(obj, event)

    def _show_context_menu(self, tab_index: int, global_pos):
        """显示标签页右键菜单"""
        menu = QMenu(self)

        act_close = menu.addAction("关闭标签页")
        act_close.triggered.connect(lambda: self._on_close_requested(tab_index))

        act_duplicate = menu.addAction("复制标签页")
        act_duplicate.triggered.connect(lambda: self.duplicate_tab_requested.emit(tab_index))

        menu.addSeparator()

        act_timeout = menu.addAction("设置超时时间...")
        act_timeout.triggered.connect(lambda: self.set_timeout_requested.emit(tab_index))

        # 只有一个标签页时禁用关闭
        if self.tab_widget.count() <= 1:
            act_close.setEnabled(False)

        menu.exec(global_pos)

    def apply_theme(self, t):
        """应用主题并刷新所有打开标签页的徽章图标与标题"""
        for i in range(self.tab_widget.count()):
            page = self.tab_widget.widget(i)
            if isinstance(page, RequestTabPage):
                self.refresh_title(page)
