"""Mock 中心弹窗组件 - 包含端口配置、服务启停、接口多级树管理、规则配置与实时外部请求监控"""

import json
from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox,
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QTextEdit, QPlainTextEdit,
    QMessageBox, QInputDialog, QMenu, QCheckBox, QGroupBox,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QRect, QTimer, QMimeData
from PyQt6.QtGui import (
    QColor, QFont, QIcon, QKeySequence, QDrag, QPainter,
    QPen, QBrush, QPixmap, QFontMetrics,
)

from app.core.db import Database
from app.core.models import MockCollection, MockApi, generate_id
from app.core.mock_server import MockService
from app.widgets.request_tabs import create_method_badge_icon
from app.widgets.request_editor import CenteredCheckBox
from app.config.i18n import tr


class MockTreeWidget(QTreeWidget):
    """支持拖拽移动、悬停高亮动画、自动展开及标准快捷键 (Ctrl+C, Ctrl+X, Ctrl+V, Del, F2) 的 Mock 树控件"""

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)

        # 拖拽内部状态
        self._dragged_item: Optional[QTreeWidgetItem] = None
        self._dragged_data: Optional[dict] = None
        self._hover_target_item: Optional[QTreeWidgetItem] = None

        # 悬停 500ms 自动展开文件夹动画计时器
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(500)
        self._hover_timer.timeout.connect(self._on_hover_timeout)

        # 强调色 (科技蓝)
        self._accent_color = QColor("#3b82f6")

    def _on_hover_timeout(self):
        """悬停达到阈值后自动展开目标文件夹"""
        if self._hover_target_item and not self._hover_target_item.isExpanded():
            data = self._hover_target_item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "collection":
                self._hover_target_item.setExpanded(True)
                name = data.get("name", "")
                self._hover_target_item.setText(0, f"📂 {name}")
                self.viewport().update()

    def _clear_hover(self):
        """清除高亮与悬停展开计时器"""
        self._hover_timer.stop()
        if self._hover_target_item is not None:
            self._hover_target_item = None
            self.viewport().update()

    def startDrag(self, supportedActions):
        """启动拖拽：记录源项，生成预览徽章浮层，采用 MoveAction，不调用 super().startDrag() 避免误删"""
        item = self.currentItem()
        if not item:
            selected = self.selectedItems()
            if selected:
                item = selected[0]
        if not item:
            return

        d_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not d_data:
            return

        self._dragged_item = item
        self._dragged_data = dict(d_data)

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-postmanage-mock-item", b"1")
        drag.setMimeData(mime)

        pixmap = self._create_drag_pixmap(item, d_data)
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(15, 12))

        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._clear_hover()
            self._dragged_item = None
            self._dragged_data = None

    def _create_drag_pixmap(self, item: QTreeWidgetItem, data: dict) -> QPixmap:
        """生成拖拽时的半透明圆角徽章预览图"""
        item_type = data.get("type", "api")
        if item_type == "api":
            api = data.get("api")
            name = api.name if api else data.get("name", "")
            method = api.method if api else data.get("method", "GET")
            path = api.path if api else data.get("path", "")
            text = f"[{method}] {name or path}"
        else:
            text = f"📁 {data.get('name', '文件夹')}"

        if len(text) > 24:
            text = text[:22] + "…"

        font = self.font()
        font.setPointSize(9)
        font.setBold(True)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(text)
        w = max(110, text_w + 24)
        h = 26

        pix = QPixmap(w, h)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 胶囊圆角背景
        bg_color = QColor(self._accent_color)
        bg_color.setAlpha(210)
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(QColor(255, 255, 255, 120), 1))
        painter.drawRoundedRect(1, 1, w - 2, h - 2, 6, 6)

        painter.setPen(QColor("#ffffff"))
        painter.setFont(font)
        painter.drawText(QRect(10, 0, w - 16, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.end()
        return pix

    def dragEnterEvent(self, event):
        if (event.source() is None or event.source() == self) and self._dragged_data:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if (event.source() is not None and event.source() != self) or not self._dragged_data:
            event.ignore()
            return

        target_item = self.itemAt(event.position().toPoint())
        d_data = self._dragged_data
        d_type = d_data.get("type")

        target_folder_item = None
        valid_target = False

        if d_type == "api":
            if target_item is None:
                # 拖拽到空白区域：移到顶层（无文件夹）
                valid_target = True
            else:
                t_data = target_item.data(0, Qt.ItemDataRole.UserRole)
                if t_data and t_data.get("type") == "collection":
                    target_folder_item = target_item
                    valid_target = True
                elif t_data and t_data.get("type") == "api":
                    target_folder_item = target_item.parent()
                    valid_target = True
        elif d_type == "collection":
            if target_item is None:
                # 拖到空白区域：移为顶级文件夹
                valid_target = True
            else:
                t_data = target_item.data(0, Qt.ItemDataRole.UserRole)
                if t_data and t_data.get("type") == "api":
                    target_item = target_item.parent()
                    t_data = target_item.data(0, Qt.ItemDataRole.UserRole) if target_item else None

                if target_item and t_data and t_data.get("type") == "collection":
                    # 循环嵌套安全检测
                    curr = target_item
                    is_descendant = False
                    dragged_id = d_data.get("id")
                    while curr:
                        c_data = curr.data(0, Qt.ItemDataRole.UserRole)
                        if c_data and c_data.get("id") == dragged_id:
                            is_descendant = True
                            break
                        curr = curr.parent()
                    if not is_descendant and t_data.get("id") != dragged_id:
                        target_folder_item = target_item
                        valid_target = True
                elif target_item is None:
                    valid_target = True

        if target_folder_item != self._hover_target_item:
            self._hover_target_item = target_folder_item
            self.viewport().update()
            if self._hover_target_item and not self._hover_target_item.isExpanded():
                self._hover_timer.start()
            else:
                self._hover_timer.stop()

        if valid_target:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._clear_hover()
        super().dragLeaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        # 绘制目标文件夹悬停高亮框与直观的「移入 ↵」徽章
        if self._hover_target_item:
            rect = self.visualItemRect(self._hover_target_item)
            if rect.isValid() and not rect.isEmpty():
                painter = QPainter(self.viewport())
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                glow_color = QColor(self._accent_color)
                glow_color.setAlpha(45)
                painter.setBrush(QBrush(glow_color))

                border_color = QColor(self._accent_color)
                border_color.setAlpha(210)
                painter.setPen(QPen(border_color, 1.5, Qt.PenStyle.SolidLine))

                draw_rect = rect.adjusted(2, 1, -2, -1)
                painter.drawRoundedRect(draw_rect, 4, 4)

                badge_w = 48
                badge_h = 16
                badge_x = draw_rect.right() - badge_w - 6
                badge_y = draw_rect.top() + (draw_rect.height() - badge_h) // 2
                badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)

                painter.setBrush(QBrush(border_color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(badge_rect, 3, 3)

                painter.setPen(QColor("#ffffff"))
                font = self.font()
                font.setPointSize(8)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, tr("mock_drop_into", "移入 ↵"))
                painter.end()

    def dropEvent(self, event):
        self._clear_hover()
        d_data = self._dragged_data
        if not d_data:
            selected = self.selectedItems()
            if selected:
                d_data = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if not d_data:
            event.ignore()
            return

        target_item = self.itemAt(event.position().toPoint())
        t_data = target_item.data(0, Qt.ItemDataRole.UserRole) if target_item else None

        if d_data.get("type") == "api":
            target_coll_id = ""
            if t_data and t_data.get("type") == "collection":
                target_coll_id = t_data["id"]
            elif t_data and t_data.get("type") == "api":
                target_coll_id = t_data.get("collection_id", "")
            elif target_item and target_item.parent():
                p_data = target_item.parent().data(0, Qt.ItemDataRole.UserRole)
                if p_data and p_data.get("type") == "collection":
                    target_coll_id = p_data["id"]

            if target_coll_id != d_data.get("collection_id", ""):
                ok = self.dialog.db.move_mock_api(d_data["id"], target_coll_id)
                if ok:
                    self.dialog._load_tree()
                    self.dialog._select_api_in_tree(d_data["id"])
                    event.acceptProposedAction()
                    return

        elif d_data.get("type") == "collection":
            new_parent_id = None
            if target_item:
                if t_data and t_data.get("type") == "collection":
                    new_parent_id = t_data["id"]
                elif t_data and t_data.get("type") == "api":
                    target_item = target_item.parent()
                    if target_item:
                        p_data = target_item.data(0, Qt.ItemDataRole.UserRole)
                        if p_data and p_data.get("type") == "collection":
                            new_parent_id = p_data["id"]

            if new_parent_id != d_data["id"]:
                ok = self.dialog.db.move_mock_collection(d_data["id"], new_parent_id)
                if ok:
                    self.dialog._load_tree()
                    self.dialog._select_collection_in_tree(d_data["id"])
                    event.acceptProposedAction()
                    return

        event.ignore()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.dialog._copy_selected()
            event.accept()
        elif event.matches(QKeySequence.StandardKey.Cut):
            self.dialog._cut_selected()
            event.accept()
        elif event.matches(QKeySequence.StandardKey.Paste):
            self.dialog._paste_selected()
            event.accept()
        elif event.key() == Qt.Key.Key_Delete:
            self.dialog._on_delete_tree_item()
            event.accept()
        elif event.key() == Qt.Key.Key_F2:
            self.dialog._rename_selected()
            event.accept()
        elif event.matches(QKeySequence.StandardKey.SaveAs) or (event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_D):
            item = self.currentItem()
            if item:
                data = item.data(0, Qt.ItemDataRole.UserRole) or {}
                if data.get("type") == "api":
                    self.dialog._on_clone_api(data.get("id"))
                    event.accept()
                    return
            super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if not item:
            self.setCurrentItem(None)
            self.clearSelection()
        super().mousePressEvent(event)


class MockCenterDialog(QDialog):
    """Mock 中心主窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("mock_title", "Mock 服务中心"))
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(1150, 780)
        self.setMinimumSize(950, 600)

        self.db = Database()
        self.mock_service = MockService.instance()

        # 剪贴板缓冲
        self._clipboard_mode: Optional[str] = None  # "copy" 或 "cut"
        self._clipboard_type: Optional[str] = None  # "collection" 或 "api"
        self._clipboard_id: Optional[str] = None

        self._current_selected_api: Optional[MockApi] = None

        self._setup_ui()
        self._load_tree()
        self._sync_server_state()

        # 监听服务请求到达
        self.mock_service.request_received.connect(self._on_request_received)
        self.mock_service.server_started.connect(self._on_server_started)
        self.mock_service.server_stopped.connect(self._on_server_stopped)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # ─── 顶部工具栏（端口配置、启停、状态、地址提示、视图切换）严格单行紧凑 ───
        top_bar = QWidget()
        top_bar.setFixedHeight(34)
        top_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(6, 2, 6, 2)
        top_layout.setSpacing(8)

        lbl_port = QLabel(tr("mock_listen_port", "Mock 监听端口:"))
        lbl_port.setStyleSheet("font-weight: bold; font-size: 12px;")
        top_layout.addWidget(lbl_port)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(self.mock_service.port if self.mock_service.port else 9999)
        self.port_spin.setFixedWidth(80)
        self.port_spin.setFixedHeight(24)
        top_layout.addWidget(self.port_spin)

        self.start_btn = QPushButton(tr("mock_start", "开始 Mock"))
        self.start_btn.setFixedSize(88, 24)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                font-weight: bold;
                font-size: 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:pressed { background-color: #047857; }
        """)
        self.start_btn.clicked.connect(self._on_toggle_service)
        top_layout.addWidget(self.start_btn)

        self.status_label = QLabel(tr("mock_status_stopped", "● 未启动"))
        self.status_label.setStyleSheet("color: #6b7280; font-weight: bold; font-size: 12px;")
        top_layout.addWidget(self.status_label)

        self.url_hint = QLabel("")
        self.url_hint.setStyleSheet("color: #3b82f6; font-size: 12px; margin-left: 6px;")
        self.url_hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top_layout.addWidget(self.url_hint)

        top_layout.addStretch()

        self.toggle_monitor_btn = QPushButton(tr("mock_collapse_monitor", "▼ 折叠监控区"))
        self.toggle_monitor_btn.setFixedHeight(24)
        self.toggle_monitor_btn.setStyleSheet("font-size: 12px; padding: 2px 8px;")
        self.toggle_monitor_btn.setToolTip("折叠下方请求监控，将全部垂直空间留给响应内容编辑区")
        self.toggle_monitor_btn.clicked.connect(self._toggle_monitor_collapsed)
        top_layout.addWidget(self.toggle_monitor_btn)

        self.clear_logs_btn = QPushButton(tr("mock_clear_logs", "清空请求日志"))
        self.clear_logs_btn.setFixedSize(104, 25)
        self.clear_logs_btn.setStyleSheet("font-size: 12px; padding: 1px 4px;")
        self.clear_logs_btn.clicked.connect(self._on_clear_logs)
        top_layout.addWidget(self.clear_logs_btn)

        self.btn_minimize = QPushButton(tr("mock_minimize", "🗕 最小化"))
        self.btn_minimize.setFixedSize(78, 25)
        self.btn_minimize.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #475569;
                font-weight: 500;
                font-size: 12px;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 1px 4px;
            }
            QPushButton:hover { background-color: #e2e8f0; color: #1e293b; }
            QPushButton:pressed { background-color: #cbd5e1; }
        """)
        self.btn_minimize.setToolTip("最小化 Mock 中心窗口至任务栏，方便在主窗口中调试接口")
        self.btn_minimize.clicked.connect(self.showMinimized)
        top_layout.addWidget(self.btn_minimize)

        main_layout.addWidget(top_bar, 0)

        # ─── 主体水平分割器（左侧：接口列表树；右侧：配置与监控面板） ───
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧面板（紧凑固定宽度，不随窗口放大瓜分宽度）
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_widget.setMinimumWidth(200)
        left_widget.setMaximumWidth(420)

        left_toolbar = QHBoxLayout()
        left_toolbar.setSpacing(4)

        self.add_api_btn = QPushButton(tr("mock_add_api", "+ 新建接口"))
        self.add_api_btn.setFixedHeight(26)
        self.add_api_btn.clicked.connect(self._on_create_api)
        self.add_folder_btn = QPushButton(tr("mock_folder_btn", "+ 文件夹 ▾"))
        self.add_folder_btn.setFixedHeight(26)
        folder_menu = QMenu(self)
        act_top = folder_menu.addAction(tr("mock_new_top_folder", "📁 新建顶级文件夹"))
        act_top.triggered.connect(self._on_create_top_collection)
        act_sub = folder_menu.addAction(tr("mock_new_sub_folder", "📁 新建子文件夹"))
        act_sub.triggered.connect(self._on_create_sub_collection)
        self.add_folder_btn.setMenu(folder_menu)
        self.del_tree_btn = QPushButton(tr("mock_del_btn", "删除"))
        self.del_tree_btn.setFixedHeight(26)
        self.del_tree_btn.clicked.connect(self._on_delete_tree_item)

        left_toolbar.addWidget(self.add_api_btn)
        left_toolbar.addWidget(self.add_folder_btn)
        left_toolbar.addWidget(self.del_tree_btn)
        left_layout.addLayout(left_toolbar)

        self.search_input = QLineEdit()
        self.search_input.setFixedHeight(26)
        self.search_input.setPlaceholderText(tr("mock_search_placeholder", "🔍 搜索接口/URL..."))
        self.search_input.textChanged.connect(self._on_filter_tree)
        left_layout.addWidget(self.search_input)

        self.tree = MockTreeWidget(self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        left_layout.addWidget(self.tree)

        self.main_splitter.addWidget(left_widget)

        # 右侧垂直分割器（上部：规则编辑；下部：实时请求监控）
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)

        # 右上：接口配置与响应编辑区（核心功能区）
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(4, 0, 4, 4)
        editor_layout.setSpacing(4)

        # 接口基本信息行（紧凑精炼）
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        lbl_name = QLabel(tr("mock_name_label", "名称:"))
        self.api_name_input = QLineEdit()
        self.api_name_input.setFixedHeight(26)
        self.api_name_input.setPlaceholderText(tr("mock_name_placeholder", "Mock 接口描述"))

        lbl_method = QLabel(tr("mock_method_label", "方式:"))
        self.api_method_combo = QComboBox()
        self.api_method_combo.setFixedHeight(26)
        self.api_method_combo.addItems(["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])

        lbl_path = QLabel(tr("mock_path_label", "URL Path:"))
        self.api_path_input = QLineEdit()
        self.api_path_input.setFixedHeight(26)
        self.api_path_input.setPlaceholderText("/api/v1/users")

        self.api_enabled_chk = QCheckBox(tr("mock_enabled_chk", "启用"))
        self.api_enabled_chk.setChecked(True)

        row1.addWidget(lbl_name)
        row1.addWidget(self.api_name_input, 2)
        row1.addWidget(lbl_method)
        row1.addWidget(self.api_method_combo, 1)
        row1.addWidget(lbl_path)
        row1.addWidget(self.api_path_input, 3)
        row1.addWidget(self.api_enabled_chk)
        editor_layout.addLayout(row1)

        # 响应状态码、延时与响应格式（紧凑精炼）
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        lbl_status = QLabel(tr("mock_status_code_label", "响应码:"))
        self.api_status_spin = QSpinBox()
        self.api_status_spin.setFixedHeight(26)
        self.api_status_spin.setRange(100, 599)
        self.api_status_spin.setValue(200)

        lbl_delay = QLabel(tr("mock_delay_label", "延时(ms):"))
        self.api_delay_spin = QSpinBox()
        self.api_delay_spin.setFixedHeight(26)
        self.api_delay_spin.setRange(0, 60000)
        self.api_delay_spin.setValue(0)

        lbl_body_type = QLabel(tr("mock_format_label", "格式:"))
        self.api_body_type_combo = QComboBox()
        self.api_body_type_combo.setFixedHeight(26)
        self.api_body_type_combo.addItems(["json", "text", "html", "xml"])

        self.format_json_btn = QPushButton(tr("btn_format_json", "格式化 JSON"))
        self.format_json_btn.setFixedHeight(26)
        self.format_json_btn.clicked.connect(self._on_format_json)

        self.save_api_btn = QPushButton(tr("mock_save_api", "保存接口配置"))
        self.save_api_btn.setFixedHeight(26)
        self.save_api_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                font-weight: bold;
                padding: 2px 14px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        self.save_api_btn.clicked.connect(self._on_save_current_api)

        row2.addWidget(lbl_status)
        row2.addWidget(self.api_status_spin)
        row2.addWidget(lbl_delay)
        row2.addWidget(self.api_delay_spin)
        row2.addWidget(lbl_body_type)
        row2.addWidget(self.api_body_type_combo)
        row2.addWidget(self.format_json_btn)
        row2.addStretch()
        row2.addWidget(self.save_api_btn)
        editor_layout.addLayout(row2)

        # 响应体与响应头选项卡（设置 Expanding 策略，拉伸窗口时最大化扩展）
        rule_tabs = QTabWidget()
        rule_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 响应体编辑器
        body_widget = QWidget()
        body_layout = QVBoxLayout(body_widget)
        body_layout.setContentsMargins(2, 2, 2, 2)
        body_layout.setSpacing(4)
        self.api_body_edit = QPlainTextEdit()
        self.api_body_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.api_body_edit.setPlaceholderText('例如: {"code": 200, "data": {"message": "success"}}')
        self.api_body_edit.setFont(QFont("Consolas", 10))
        body_layout.addWidget(self.api_body_edit, 1)
        rule_tabs.addTab(body_widget, tr("mock_tab_response_body", "响应内容 (Response Body)"))

        # 响应头表格
        headers_widget = QWidget()
        headers_layout = QVBoxLayout(headers_widget)
        headers_layout.setContentsMargins(2, 2, 2, 2)
        headers_layout.setSpacing(4)
        self.api_headers_table = QTableWidget(0, 3)
        self.api_headers_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.api_headers_table.setHorizontalHeaderLabels([
            tr("mock_col_header_enabled", "启用"),
            tr("mock_col_header_name", "响应头名称"),
            tr("mock_col_header_value", "响应头值"),
        ])
        h0 = self.api_headers_table.horizontalHeaderItem(0)
        if h0:
            h0.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.api_headers_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.api_headers_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.api_headers_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.api_headers_table.setColumnWidth(0, 50)
        
        h_btn_row = QHBoxLayout()
        add_h_btn = QPushButton(tr("mock_add_header", "+ 添加响应头"))
        add_h_btn.setFixedHeight(24)
        add_h_btn.clicked.connect(self._on_add_response_header)
        del_h_btn = QPushButton(tr("btn_delete_selected", "删除选中"))
        del_h_btn.setFixedHeight(24)
        del_h_btn.clicked.connect(self._on_del_response_header)
        h_btn_row.addWidget(add_h_btn)
        h_btn_row.addWidget(del_h_btn)
        h_btn_row.addStretch()
        headers_layout.addLayout(h_btn_row)
        headers_layout.addWidget(self.api_headers_table, 1)
        rule_tabs.addTab(headers_widget, tr("mock_tab_response_headers", "自定义响应头 (Response Headers)"))

        editor_layout.addWidget(rule_tabs, 1)
        self.right_splitter.addWidget(editor_widget)

        # 右下：实时请求监控详情面板
        monitor_widget = QWidget()
        monitor_layout = QVBoxLayout(monitor_widget)
        monitor_layout.setContentsMargins(4, 4, 4, 2)
        monitor_layout.setSpacing(4)

        monitor_header_row = QHBoxLayout()
        lbl_monitor = QLabel(tr("mock_lbl_monitor", "📡 实时外部请求监控 (捕获打入的外部请求与详情):"))
        lbl_monitor.setStyleSheet("font-weight: bold; font-size: 12px; color: #1e293b;")
        monitor_header_row.addWidget(lbl_monitor)
        monitor_header_row.addStretch()

        self.max_monitor_btn = QPushButton(tr("mock_btn_maximize_monitor", "⛶ 最大化监控"))
        self.max_monitor_btn.setFixedHeight(24)
        self.max_monitor_btn.clicked.connect(self._toggle_monitor_maximized)
        monitor_header_row.addWidget(self.max_monitor_btn)
        monitor_layout.addLayout(monitor_header_row)

        # 监控分割器：左侧请求列表表格，右侧选中请求的入参、请求头、Cookie、Body与返回响应
        sub_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 监控列表表格
        self.log_table = QTableWidget(0, 6)
        self.log_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log_table.setHorizontalHeaderLabels([
            tr("mock_col_time", "时间"),
            tr("mock_col_method", "方法"),
            tr("mock_col_path", "URL 路径"),
            tr("mock_col_status", "状态码"),
            tr("mock_col_duration", "耗时"),
            tr("mock_col_client_ip", "客户端 IP"),
        ])
        self.log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.log_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.log_table.itemSelectionChanged.connect(self._on_log_row_selected)
        sub_splitter.addWidget(self.log_table)

        # 详情 Tab
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 1. 入参 (Query)
        self.query_table = QTableWidget(0, 2)
        self.query_table.setHorizontalHeaderLabels([tr("mock_col_param_name", "参数名"), tr("mock_col_param_value", "参数值")])
        self.query_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.detail_tabs.addTab(self.query_table, tr("mock_tab_params", "入参 (Query)"))

        # 2. 请求头 (Headers)
        self.headers_table = QTableWidget(0, 2)
        self.headers_table.setHorizontalHeaderLabels([tr("mock_col_header_name", "Header 名"), tr("mock_col_header_value", "Header 值")])
        self.headers_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.detail_tabs.addTab(self.headers_table, tr("mock_tab_headers", "请求头 (Headers)"))

        # 3. Cookie
        self.cookie_table = QTableWidget(0, 2)
        self.cookie_table.setHorizontalHeaderLabels([tr("mock_col_cookie_name", "Cookie 键"), tr("mock_col_cookie_value", "Cookie 值")])
        self.cookie_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.detail_tabs.addTab(self.cookie_table, tr("mock_tab_cookie", "Cookie"))

        # 4. 请求体 (Body)
        self.req_body_view = QTextEdit()
        self.req_body_view.setReadOnly(True)
        self.req_body_view.setFont(QFont("Consolas", 10))
        self.detail_tabs.addTab(self.req_body_view, tr("mock_tab_body", "请求体 (Body)"))

        # 5. 返回响应 (Response)
        self.resp_view = QTextEdit()
        self.resp_view.setReadOnly(True)
        self.resp_view.setFont(QFont("Consolas", 10))
        self.detail_tabs.addTab(self.resp_view, tr("mock_tab_response", "返回响应 (Response)"))

        sub_splitter.addWidget(self.detail_tabs)
        sub_splitter.setStretchFactor(0, 4)
        sub_splitter.setStretchFactor(1, 6)

        monitor_layout.addWidget(sub_splitter, 1)
        self.right_splitter.addWidget(monitor_widget)

        # 右侧上下分割比：上部响应编辑区占大部分（70%），且放大窗口时获取优先拉伸
        self.right_splitter.setStretchFactor(0, 3)
        self.right_splitter.setStretchFactor(1, 1)
        self.right_splitter.setSizes([480, 240])

        self.main_splitter.addWidget(self.right_splitter)
        # 左侧树固定权重 0，所有拉大水平空间 100% 分配给右侧功能区 1
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([260, 940])

        main_layout.addWidget(self.main_splitter, 1)

    def _toggle_monitor_collapsed(self):
        """折叠或展开监控区域，使响应编辑器占满垂直空间"""
        sizes = self.right_splitter.sizes()
        if sizes[1] > 20:
            self._saved_right_splitter_sizes = sizes
            self.right_splitter.setSizes([sum(sizes), 0])
            self.toggle_monitor_btn.setText(tr("mock_expand_monitor", "▲ 展开监控区"))
        else:
            restore_sizes = getattr(self, "_saved_right_splitter_sizes", [480, 240])
            self.right_splitter.setSizes(restore_sizes)
            self.toggle_monitor_btn.setText(tr("mock_collapse_monitor", "▼ 折叠监控区"))

    def _toggle_monitor_maximized(self):
        """最大化或还原监控区域"""
        sizes = self.right_splitter.sizes()
        if sizes[0] > 20:
            self._saved_right_splitter_sizes = sizes
            self.right_splitter.setSizes([0, sum(sizes)])
            self.max_monitor_btn.setText(tr("mock_btn_restore_monitor", "⛶ 还原监控"))
            self.toggle_monitor_btn.setText(tr("mock_expand_monitor", "▲ 展开监控区"))
        else:
            restore_sizes = getattr(self, "_saved_right_splitter_sizes", [480, 240])
            self.right_splitter.setSizes(restore_sizes)
            self.max_monitor_btn.setText(tr("mock_btn_maximize_monitor", "⛶ 最大化监控"))
            self.toggle_monitor_btn.setText(tr("mock_collapse_monitor", "▼ 折叠监控区"))

    # ─── 服务控制 ────────────────────────────────────────────────

    def _sync_server_state(self):
        """同步后台 Mock 服务的实际状态"""
        if self.mock_service.is_running:
            self._on_server_started(self.mock_service.port)
        else:
            self._on_server_stopped()
        # 恢复已有请求日志
        for log in reversed(self.mock_service.recent_logs):
            self._insert_log_row(log)

    def _on_toggle_service(self):
        if self.mock_service.is_running:
            self.mock_service.stop()
            QMessageBox.information(self, tr("mock_title", "Mock 服务"), tr("mock_stopped_msg", "Mock 服务已停止。"))
        else:
            port = self.port_spin.value()
            reply = QMessageBox.question(
                self,
                tr("mock_start_confirm_title", "确认启动 Mock 服务"),
                tr("mock_start_confirm_msg", "是否同意使用本地端口 {port} 启动 Mock 服务？\n\n启动后，外部可通过 http://127.0.0.1:{port}/ 访问配置的接口。").format(port=port),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            ok, msg = self.mock_service.start(port)
            if ok:
                QMessageBox.information(self, tr("mock_started_title", "Mock 服务已启动"), msg)
            else:
                QMessageBox.critical(self, tr("mock_start_failed_title", "启动失败"), msg)

    def _on_server_started(self, port: int):
        self.start_btn.setText(tr("mock_stop", "停止 Mock"))
        self.start_btn.setFixedSize(88, 24)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef4444;
                color: white;
                font-weight: bold;
                font-size: 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #dc2626; }
            QPushButton:pressed { background-color: #b91c1c; }
        """)
        self.status_label.setText(f"{tr('mock_status_running', '● 运行中')}: {port}")
        self.status_label.setStyleSheet("color: #10b981; font-weight: bold; font-size: 12px;")
        self.url_hint.setText(f"{tr('mock_base_url', '基准地址')}: http://127.0.0.1:{port}")
        self.port_spin.setEnabled(False)

    def _on_server_stopped(self):
        self.start_btn.setText(tr("mock_start", "开始 Mock"))
        self.start_btn.setFixedSize(88, 24)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                font-weight: bold;
                font-size: 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:pressed { background-color: #047857; }
        """)
        self.status_label.setText(tr("mock_status_stopped", "● 未启动"))
        self.status_label.setStyleSheet("color: #6b7280; font-weight: bold; font-size: 12px;")
        self.url_hint.setText("")
        self.port_spin.setEnabled(True)

    # ─── 树加载与管理 ────────────────────────────────────────────

    def _load_tree(self):
        self.tree.clear()
        collections = self.db.get_mock_collections(parent_id=None)
        for col in collections:
            item = QTreeWidgetItem(self.tree)
            item.setText(0, f"📁 {col.name}")
            item.setData(0, Qt.ItemDataRole.UserRole, {"type": "collection", "id": col.id, "name": col.name})
            self._load_sub_tree(item, col.id)

        # 加载根目录下的无所属文件夹接口
        apis = self.db.get_mock_apis(collection_id="")
        for api in apis:
            self._create_api_tree_item(self.tree, api)

        self.tree.expandAll()

    def _load_sub_tree(self, parent_item: QTreeWidgetItem, parent_id: str):
        sub_cols = self.db.get_mock_collections(parent_id=parent_id)
        for col in sub_cols:
            item = QTreeWidgetItem(parent_item)
            item.setText(0, f"📁 {col.name}")
            item.setData(0, Qt.ItemDataRole.UserRole, {"type": "collection", "id": col.id, "name": col.name})
            self._load_sub_tree(item, col.id)

        apis = self.db.get_mock_apis(collection_id=parent_id)
        for api in apis:
            self._create_api_tree_item(parent_item, api)

    def _create_api_tree_item(self, parent, api: MockApi) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent)
        item.setIcon(0, create_method_badge_icon(api.method))
        status_disp = "" if api.is_enabled else f" [{tr('mock_status_disabled', '已禁用')}]"
        item.setText(0, f"{api.name} ({api.path}){status_disp}")
        if not api.is_enabled:
            item.setForeground(0, QColor("#9ca3af"))
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "type": "api",
            "id": api.id,
            "api": api,
            "collection_id": api.collection_id
        })
        return item

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("type") != "api":
            return
        api_id = data.get("id")
        api = self.db.get_mock_api(api_id)
        if api:
            self._display_api_in_editor(api)

    def _display_api_in_editor(self, api: MockApi):
        self._current_selected_api = api
        self.api_name_input.setText(api.name)
        idx = self.api_method_combo.findText(api.method)
        if idx >= 0:
            self.api_method_combo.setCurrentIndex(idx)
        self.api_path_input.setText(api.path)
        self.api_status_spin.setValue(api.status_code)
        self.api_delay_spin.setValue(api.delay_ms)
        self.api_enabled_chk.setChecked(api.is_enabled)
        
        bidx = self.api_body_type_combo.findText(api.body_type)
        if bidx >= 0:
            self.api_body_type_combo.setCurrentIndex(bidx)
        self.api_body_edit.setPlainText(api.body_content)

        # 填充响应头表格
        self.api_headers_table.setRowCount(0)
        for h in (api.headers or []):
            row = self.api_headers_table.rowCount()
            self.api_headers_table.insertRow(row)
            chk = CenteredCheckBox(h.get("enabled", True))
            self.api_headers_table.setCellWidget(row, 0, chk)
            self.api_headers_table.setItem(row, 1, QTableWidgetItem(h.get("key", "")))
            self.api_headers_table.setItem(row, 2, QTableWidgetItem(h.get("value", "")))

    def _on_save_current_api(self):
        if not self._current_selected_api:
            # 若未选择接口，提示新建
            self._on_create_api()
            return

        name = self.api_name_input.text().strip() or tr("mock_untitled_api", "未命名 Mock 接口")
        path = self.api_path_input.text().strip()
        if not path:
            QMessageBox.warning(self, tr("mock_missing_param_title", "参数不全"), tr("mock_input_path_msg", "请输入 URL Path，例如 /api/test"))
            return
        if not path.startswith("/"):
            path = "/" + path

        method = self.api_method_combo.currentText()
        status_code = self.api_status_spin.value()
        delay_ms = self.api_delay_spin.value()
        body_type = self.api_body_type_combo.currentText()
        body_content = self.api_body_edit.toPlainText()
        is_enabled = self.api_enabled_chk.isChecked()

        headers = []
        for r in range(self.api_headers_table.rowCount()):
            chk = self.api_headers_table.cellWidget(r, 0)
            k_item = self.api_headers_table.item(r, 1)
            v_item = self.api_headers_table.item(r, 2)
            k = k_item.text().strip() if k_item else ""
            v = v_item.text() if v_item else ""
            if k:
                headers.append({
                    "enabled": chk.isChecked() if chk else True,
                    "key": k,
                    "value": v
                })

        api = self._current_selected_api
        api.name = name
        api.method = method
        api.path = path
        api.status_code = status_code
        api.delay_ms = delay_ms
        api.body_type = body_type
        api.body_content = body_content
        api.is_enabled = is_enabled
        api.headers = headers

        self.db.update_mock_api(api)
        self._load_tree()
        self._select_api_in_tree(api.id)
        QMessageBox.information(self, tr("mock_saved_title", "保存成功"), tr("mock_saved_msg", "Mock 接口 [{name}] 保存成功！").format(name=name))

    def _select_api_in_tree(self, api_id: str):
        """在树中根据 API ID 选中对应的项目并加载到编辑器"""
        def _find(item: QTreeWidgetItem):
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "api" and data.get("id") == api_id:
                self.tree.setCurrentItem(item)
                return True
            for i in range(item.childCount()):
                if _find(item.child(i)):
                    return True
            return False

        for i in range(self.tree.topLevelItemCount()):
            if _find(self.tree.topLevelItem(i)):
                break

        api = self.db.get_mock_api(api_id)
        if api:
            self._display_api_in_editor(api)

    def _select_collection_in_tree(self, col_id: str):
        """在树中根据集合 ID 选中对应的项目"""
        def _find(item: QTreeWidgetItem):
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "collection" and data.get("id") == col_id:
                self.tree.setCurrentItem(item)
                return True
            for i in range(item.childCount()):
                if _find(item.child(i)):
                    return True
            return False

        for i in range(self.tree.topLevelItemCount()):
            if _find(self.tree.topLevelItem(i)):
                break

    def _copy_selected(self):
        item = self.tree.currentItem()
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        itype = data.get("type")
        iid = data.get("id")
        if itype and iid:
            self._set_clipboard("copy", itype, iid)

    def _cut_selected(self):
        item = self.tree.currentItem()
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        itype = data.get("type")
        iid = data.get("id")
        if itype and iid:
            self._set_clipboard("cut", itype, iid)

    def _paste_selected(self):
        self._on_paste()

    def _rename_selected(self):
        item = self.tree.currentItem()
        if item:
            self._on_rename_item(item)

    def _on_format_json(self):
        text = self.api_body_edit.toPlainText().strip()
        if not text:
            return
        try:
            parsed = json.loads(text)
            self.api_body_edit.setPlainText(json.dumps(parsed, ensure_ascii=False, indent=2))
        except Exception as e:
            QMessageBox.warning(self, tr("mock_json_fail_title", "JSON 格式化失败"), tr("mock_json_fail_msg", "非法的 JSON 内容:\n{err}").format(err=e))

    def _on_add_response_header(self):
        r = self.api_headers_table.rowCount()
        self.api_headers_table.insertRow(r)
        chk = CenteredCheckBox(True)
        self.api_headers_table.setCellWidget(r, 0, chk)
        self.api_headers_table.setItem(r, 1, QTableWidgetItem(""))
        self.api_headers_table.setItem(r, 2, QTableWidgetItem(""))

    def _on_del_response_header(self):
        row = self.api_headers_table.currentRow()
        if row >= 0:
            self.api_headers_table.removeRow(row)

    # ─── 树增删改查与剪贴板 ──────────────────────────────────────

    def _get_target_collection_id(self) -> str:
        item = self.tree.currentItem()
        if not item:
            return ""
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("type") == "collection":
            return data.get("id", "")
        elif data.get("type") == "api":
            return data.get("collection_id", "")
        return ""

    def _on_create_top_collection(self):
        """新建顶级文件夹（不受当前选中项影响，直接作为顶层根文件夹创建）"""
        name, ok = QInputDialog.getText(self, tr("mock_new_top_folder_title", "新建顶级文件夹"), tr("mock_top_folder_name_label", "顶级文件夹名称:"))
        if ok and name.strip():
            col = MockCollection(id=generate_id(), name=name.strip(), parent_id=None)
            self.db.create_mock_collection(col)
            self._load_tree()
            self._select_collection_in_tree(col.id)

    def _on_create_sub_collection(self, parent_id: Optional[str] = None):
        """新建子文件夹（以选中的文件夹为父级）"""
        target_pid = parent_id or self._get_target_collection_id()
        if not target_pid:
            reply = QMessageBox.question(
                self,
                tr("mock_tip_title", "提示"),
                tr("mock_prompt_create_root", "当前未选中任何文件夹作为父级，是否新建为顶级文件夹？"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._on_create_top_collection()
            return

        name, ok = QInputDialog.getText(self, tr("mock_new_subfolder_title", "新建子文件夹"), tr("mock_subfolder_name_label", "子文件夹名称:"))
        if ok and name.strip():
            col = MockCollection(id=generate_id(), name=name.strip(), parent_id=target_pid)
            self.db.create_mock_collection(col)
            self._load_tree()
            self._select_collection_in_tree(col.id)

    def _on_create_collection(self):
        """兼容入口：新建顶级文件夹"""
        self._on_create_top_collection()

    def _on_create_api(self):
        col_id = self._get_target_collection_id()
        name, ok = QInputDialog.getText(self, tr("mock_new_api_title", "新建 Mock 接口"), tr("mock_api_name_label", "接口名称:"), text=tr("mock_new_api_default_name", "新建Mock接口"))
        if not ok or not name.strip():
            return
        path, ok2 = QInputDialog.getText(self, tr("mock_api_path_title", "接口 URL 路径"), tr("mock_path_label", "URL 路径 (如 /api/test):"), text="/api/test")
        if not ok2 or not path.strip():
            return
        norm_path = "/" + path.strip().lstrip("/")
        api = MockApi(
            id=generate_id(),
            collection_id=col_id,
            name=name.strip(),
            method="GET",
            path=norm_path,
            status_code=200,
            body_type="json",
            body_content='{"code": 200, "message": "success"}',
            is_enabled=True,
        )
        self.db.create_mock_api(api)
        self._load_tree()
        self._display_api_in_editor(api)
        self._select_api_in_tree(api.id)

    def _on_delete_tree_item(self):
        item = self.tree.currentItem()
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        itype = data.get("type")
        iid = data.get("id")
        if itype == "collection":
            reply = QMessageBox.question(self, tr("mock_del_confirm_title", "删除确认"), tr("mock_del_folder_confirm", "确定删除该文件夹及其内部所有 Mock 接口吗？"))
            if reply == QMessageBox.StandardButton.Yes:
                self.db.delete_mock_collection(iid)
                self._load_tree()
        elif itype == "api":
            reply = QMessageBox.question(self, tr("mock_del_confirm_title", "删除确认"), tr("mock_del_api_confirm", "确定删除该 Mock 接口吗？"))
            if reply == QMessageBox.StandardButton.Yes:
                self.db.delete_mock_api(iid)
                if self._current_selected_api and self._current_selected_api.id == iid:
                    self._current_selected_api = None
                self._load_tree()

    def _on_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item:
            self.tree.setCurrentItem(item)
        else:
            self.tree.setCurrentItem(None)
            self.tree.clearSelection()

        menu = QMenu(self)

        # 始终提供新建顶级文件夹
        act_new_top_folder = menu.addAction(tr("mock_new_top_folder", "📁 新建顶级文件夹"))
        act_new_top_folder.triggered.connect(self._on_create_top_collection)

        if item:
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            itype = data.get("type")
            iid = data.get("id")

            if itype == "collection":
                act_new_sub_folder = menu.addAction(tr("mock_new_sub_folder", "📁 新建子文件夹"))
                act_new_sub_folder.triggered.connect(lambda: self._on_create_sub_collection(iid))
                act_new_api = menu.addAction(tr("mock_new_api_folder", "➕ 新建接口 (当前文件夹)"))
                act_new_api.triggered.connect(self._on_create_api)
            else:
                col_id = data.get("collection_id")
                if col_id:
                    act_new_sub_folder = menu.addAction(tr("mock_new_subfolder_peer", "📁 新建子文件夹 (同级)"))
                    act_new_sub_folder.triggered.connect(lambda: self._on_create_sub_collection(col_id))
                act_new_api = menu.addAction(tr("mock_add_api", "➕ 新建接口"))
                act_new_api.triggered.connect(self._on_create_api)
        else:
            act_new_api = menu.addAction(tr("mock_new_root_api", "➕ 新建根接口"))
            act_new_api.triggered.connect(self._on_create_api)

        menu.addSeparator()

        if item:
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            itype = data.get("type")
            iid = data.get("id")

            act_copy = menu.addAction(f"{tr('action_copy', '复制')}\tCtrl+C")
            act_copy.triggered.connect(lambda: self._set_clipboard("copy", itype, iid))

            act_cut = menu.addAction(f"{tr('action_cut', '剪切')}\tCtrl+X")
            act_cut.triggered.connect(lambda: self._set_clipboard("cut", itype, iid))

            if itype == "api":
                act_clone = menu.addAction(f"{tr('action_clone', '克隆接口')}\tCtrl+D")
                act_clone.triggered.connect(lambda: self._on_clone_api(iid))

            act_rename = menu.addAction(f"{tr('action_rename', '重命名')}\tF2")
            act_rename.triggered.connect(lambda: self._on_rename_item(item))

            menu.addSeparator()
            act_del = menu.addAction(f"{tr('action_delete', '删除')}\tDel")
            act_del.triggered.connect(self._on_delete_tree_item)

        if self._clipboard_id:
            menu.addSeparator()
            clipboard_info = f" ({tr('action_cut', '剪切')})" if self._clipboard_mode == "cut" else f" ({tr('action_copy', '复制')})"
            act_paste = menu.addAction(f"{tr('action_paste', '粘贴')}{clipboard_info}\tCtrl+V")
            act_paste.triggered.connect(self._on_paste)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _set_clipboard(self, mode: str, itype: str, iid: str):
        self._clipboard_mode = mode
        self._clipboard_type = itype
        self._clipboard_id = iid

    def _on_clone_api(self, api_id: str):
        target_cid = self._get_target_collection_id()
        cloned = self.db.clone_mock_api(api_id, target_cid)
        self._load_tree()
        if cloned:
            self._select_api_in_tree(cloned.id)

    def _on_rename_item(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        itype = data.get("type")
        iid = data.get("id")
        old_name = data.get("name", "")
        if itype == "api":
            api = self.db.get_mock_api(iid)
            old_name = api.name if api else ""

        new_name, ok = QInputDialog.getText(self, tr("mock_rename_title", "重命名"), tr("mock_rename_prompt", "输入新名称:"), text=old_name)
        if ok and new_name.strip():
            if itype == "collection":
                self.db.rename_mock_collection(iid, new_name.strip())
            elif itype == "api":
                api = self.db.get_mock_api(iid)
                if api:
                    api.name = new_name.strip()
                    self.db.update_mock_api(api)
            self._load_tree()

    def _on_paste(self):
        if not self._clipboard_id:
            return
        target_cid = self._get_target_collection_id()
        pasted_id = None

        if self._clipboard_type == "api":
            if self._clipboard_mode == "cut":
                self.db.move_mock_api(self._clipboard_id, target_cid)
                pasted_id = self._clipboard_id
                self._clipboard_id = None
                self._clipboard_mode = None
            else:
                cloned = self.db.clone_mock_api(self._clipboard_id, target_cid)
                if cloned:
                    pasted_id = cloned.id
            self._load_tree()
            if pasted_id:
                self._select_api_in_tree(pasted_id)

        elif self._clipboard_type == "collection":
            target_parent = target_cid or None
            if self._clipboard_mode == "cut":
                if self._clipboard_id != target_parent:
                    ok = self.db.move_mock_collection(self._clipboard_id, target_parent)
                    if ok:
                        pasted_id = self._clipboard_id
                        self._clipboard_id = None
                        self._clipboard_mode = None
                    else:
                        QMessageBox.warning(self, tr("mock_op_fail_title", "操作失败"), tr("mock_cannot_move_child", "无法将文件夹移动到自身或其子文件夹中。"))
            else:
                cloned = self.db.clone_mock_collection(self._clipboard_id, target_parent)
                if cloned:
                    pasted_id = cloned.id
            self._load_tree()
            if pasted_id:
                self._select_collection_in_tree(pasted_id)

    def _on_filter_tree(self, text: str):
        text = text.strip().lower()
        if not text:
            self._load_tree()
            return

        def filter_item(item: QTreeWidgetItem) -> bool:
            matched = False
            item_text = item.text(0).lower()
            if text in item_text:
                matched = True

            child_matched = False
            for i in range(item.childCount()):
                if filter_item(item.child(i)):
                    child_matched = True

            should_show = matched or child_matched
            item.setHidden(not should_show)
            if should_show:
                item.setExpanded(True)
            return should_show

        for i in range(self.tree.topLevelItemCount()):
            filter_item(self.tree.topLevelItem(i))

    # ─── 实时请求监控 ────────────────────────────────────────────

    def _on_request_received(self, log_entry: dict):
        self._insert_log_row(log_entry)

    def _insert_log_row(self, log_entry: dict):
        row = 0
        self.log_table.insertRow(row)

        t_item = QTableWidgetItem(log_entry.get("timestamp", ""))
        m_item = QTableWidgetItem(log_entry.get("method", ""))
        p_item = QTableWidgetItem(log_entry.get("path", ""))
        s_code = log_entry.get("status_code", 200)
        s_item = QTableWidgetItem(str(s_code))
        d_item = QTableWidgetItem(f"{log_entry.get('duration_ms', 0)} ms")
        ip_item = QTableWidgetItem(log_entry.get("client_ip", ""))

        if s_code == 200 or s_code == 201:
            s_item.setForeground(QColor("#10b981"))
        elif s_code == 404:
            s_item.setForeground(QColor("#f59e0b"))
        else:
            s_item.setForeground(QColor("#ef4444"))

        t_item.setData(Qt.ItemDataRole.UserRole, log_entry)

        self.log_table.setItem(row, 0, t_item)
        self.log_table.setItem(row, 1, m_item)
        self.log_table.setItem(row, 2, p_item)
        self.log_table.setItem(row, 3, s_item)
        self.log_table.setItem(row, 4, d_item)
        self.log_table.setItem(row, 5, ip_item)

        # 默认选中最新一行展示
        if self.log_table.rowCount() == 1:
            self.log_table.selectRow(0)

    def _on_log_row_selected(self):
        row = self.log_table.currentRow()
        if row < 0:
            return
        t_item = self.log_table.item(row, 0)
        if not t_item:
            return
        log_entry = t_item.data(Qt.ItemDataRole.UserRole) or {}

        # 1. 填充 Query
        query = log_entry.get("query", {})
        self.query_table.setRowCount(0)
        if isinstance(query, dict):
            for k, v in query.items():
                r = self.query_table.rowCount()
                self.query_table.insertRow(r)
                self.query_table.setItem(r, 0, QTableWidgetItem(str(k)))
                self.query_table.setItem(r, 1, QTableWidgetItem(str(v)))

        # 2. 填充 Headers
        headers = log_entry.get("headers", {})
        self.headers_table.setRowCount(0)
        if isinstance(headers, dict):
            for k, v in headers.items():
                r = self.headers_table.rowCount()
                self.headers_table.insertRow(r)
                self.headers_table.setItem(r, 0, QTableWidgetItem(str(k)))
                self.headers_table.setItem(r, 1, QTableWidgetItem(str(v)))

        # 3. 填充 Cookie
        cookies = log_entry.get("cookies", {})
        self.cookie_table.setRowCount(0)
        if isinstance(cookies, dict):
            for k, v in cookies.items():
                r = self.cookie_table.rowCount()
                self.cookie_table.insertRow(r)
                self.cookie_table.setItem(r, 0, QTableWidgetItem(str(k)))
                self.cookie_table.setItem(r, 1, QTableWidgetItem(str(v)))

        # 4. 填充 Body
        body = log_entry.get("body", "")
        try:
            body_json = json.loads(body)
            self.req_body_view.setPlainText(json.dumps(body_json, ensure_ascii=False, indent=2))
        except Exception:
            self.req_body_view.setPlainText(body)

        # 5. 填充返回响应 (Response)
        resp_status = log_entry.get("status_code", 200)
        resp_body = log_entry.get("response_body", "")
        resp_headers = log_entry.get("response_headers", {})

        resp_lines = [f"HTTP/1.1 {resp_status}"]
        if resp_headers:
            resp_lines.append("\n[Response Headers]")
            for hk, hv in resp_headers.items():
                resp_lines.append(f"{hk}: {hv}")
        resp_lines.append("\n[Response Body]")
        if resp_body:
            try:
                parsed_resp = json.loads(resp_body)
                resp_lines.append(json.dumps(parsed_resp, ensure_ascii=False, indent=2))
            except Exception:
                resp_lines.append(resp_body)
        else:
            resp_lines.append("<Empty Body>")

        self.resp_view.setPlainText("\n".join(resp_lines))

    def _on_clear_logs(self):
        self.log_table.setRowCount(0)
        self.query_table.setRowCount(0)
        self.headers_table.setRowCount(0)
        self.cookie_table.setRowCount(0)
        self.req_body_view.clear()
        self.resp_view.clear()
        self.mock_service.clear_logs()
