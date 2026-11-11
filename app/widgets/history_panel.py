"""历史面板组件 - 展示请求历史"""

from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QMessageBox, QToolTip,
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QTimer, QPoint, QEvent
from PyQt6.QtGui import QColor, QCursor

from app.core.db import Database
from app.core.models import HistoryRecord
from app.config.themes import get_method_color, ThemeManager
from app.widgets.request_tabs import create_method_badge_icon


class CustomHistoryListWidget(QListWidget):
    """支持光标悬停超过 1 秒展示完整接口名称的历史列表控件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._fullname_tooltip_timer = QTimer(self)
        self._fullname_tooltip_timer.setSingleShot(True)
        self._fullname_tooltip_timer.setInterval(1000)
        self._fullname_tooltip_timer.timeout.connect(self._show_hover_fullname_tooltip)
        self._last_hovered_item: Optional[QListWidgetItem] = None
        self._hover_global_pos: Optional[QPoint] = None

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        item = self.itemAt(event.position().toPoint())
        if item != self._last_hovered_item:
            self._fullname_tooltip_timer.stop()
            QToolTip.hideText()
            self._last_hovered_item = item
            if item:
                self._hover_global_pos = event.globalPosition().toPoint()
                self._fullname_tooltip_timer.start(1000)
        else:
            if item and self._fullname_tooltip_timer.isActive():
                self._hover_global_pos = event.globalPosition().toPoint()

    def leaveEvent(self, event):
        self._fullname_tooltip_timer.stop()
        QToolTip.hideText()
        self._last_hovered_item = None
        super().leaveEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            # 屏蔽系统瞬时默认 ToolTip，统一由 1 秒稳定悬停计时器接管
            return True
        return super().viewportEvent(event)

    def _show_hover_fullname_tooltip(self):
        """光标在历史项上停留满 1 秒时，弹出完整接口名称提示"""
        item = self._last_hovered_item
        if not item:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        if not record:
            return

        name = getattr(record, "name", "") or ""
        url = getattr(record, "url", "") or ""
        method = getattr(record, "method", "GET") or "GET"
        status = str(getattr(record, "status_code", "--"))
        time_str = getattr(record, "created_at", "") or ""

        display_name = name if name else url
        tip_lines = [
            f"📌 接口全称: {display_name}",
            f"🏷️ 请求方法: {method}",
        ]
        if url and url != display_name:
            tip_lines.append(f"🔗 请求 URL: {url}")
        if status and status != "--":
            tip_lines.append(f"📊 响应状态: {status}")
        if time_str:
            tip_lines.append(f"🕒 请求时间: {time_str}")

        pos = self._hover_global_pos or QCursor.pos()
        QToolTip.showText(pos, "\n".join(tip_lines), self)


class HistoryPanel(QWidget):
    """历史面板"""

    history_selected = pyqtSignal(object)  # HistoryRecord

    def __init__(self):
        super().__init__()
        self.db = Database()
        self._loaded = False
        self._init_ui()

    def ensure_loaded(self):
        """确保历史数据已加载（首次切换到历史 Tab 或空闲时触发）"""
        if not self._loaded:
            self._loaded = True
            self.refresh_history()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 标题栏
        header = QHBoxLayout()
        self.title_label = QLabel("历史记录")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        header.addWidget(self.title_label)
        header.addStretch()

        self.btn_clear = QPushButton("清空")
        self.btn_clear.setFixedSize(48, 24)
        self.btn_clear.setToolTip("清空所有历史记录")
        self.btn_clear.clicked.connect(self._on_clear)
        header.addWidget(self.btn_clear)

        layout.addLayout(header)

        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索历史...")
        self.search_input.textChanged.connect(self._on_search)
        self.search_input.setStyleSheet("padding: 4px 8px; font-size: 12px;")
        layout.addWidget(self.search_input)

        # 历史列表
        self.history_list = CustomHistoryListWidget()
        self.history_list.setIconSize(QSize(38, 18))
        self.history_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.history_list)

    def apply_theme(self, t):
        """应用主题"""
        self.title_label.setStyleSheet(
            f"font-weight: bold; font-size: 13px; padding: 4px; color: {t.text_primary};"
        )
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                padding: 4px 8px;
                border: 1px solid {t.border};
                border-radius: 4px;
                font-size: 12px;
                background-color: {t.bg_input};
                color: {t.text_primary};
            }}
        """)
        self.history_list.setStyleSheet(f"""
            QListWidget {{
                border: none;
                font-size: 12px;
                background-color: {t.bg_sidebar};
                color: {t.text_primary};
            }}
            QListWidget::item {{
                padding: 6px 4px;
                border-bottom: 1px solid {t.border_light};
            }}
            QListWidget::item:selected {{
                background-color: {t.bg_selected};
                border-radius: 3px;
                color: {t.text_primary};
            }}
            QListWidget::item:hover {{
                background-color: {t.bg_hover};
            }}
        """)
        # 刷新已有历史记录的图标和文字颜色
        is_dark = (t.name == "dark")
        for i in range(self.history_list.count()):
            item = self.history_list.item(i)
            record = item.data(Qt.ItemDataRole.UserRole)
            if record:
                method = getattr(record, "method", "GET")
                item.setIcon(create_method_badge_icon(method, is_dark))
                item.setForeground(QColor(t.text_primary))

    def refresh_history(self):
        """刷新历史列表"""
        self._loaded = True
        self.history_list.clear()
        records = self.db.get_history(limit=100)
        for record in records:
            self._add_history_item(record)

    def _add_history_item(self, record: HistoryRecord):
        """添加一条历史记录的显示项（方法彩色徽章图标，标准文字颜色）"""
        method = record.method
        is_dark = (ThemeManager.current().name == "dark")
        badge_icon = create_method_badge_icon(method, is_dark)
        t = ThemeManager.current()

        # 优先使用请求名称，如果没有则使用 URL
        display_name = record.name if hasattr(record, 'name') and record.name else record.url

        # 截断长文本
        if len(display_name) > 50:
            display_name = display_name[:47] + "..."

        status = str(record.status_code) if record.status_code else "--"
        time_str = record.created_at.split(" ")[-1] if record.created_at else ""

        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, record)
        item.setIcon(badge_icon)
        item.setText(f"{status}  {display_name}  {time_str}")
        item.setForeground(QColor(t.text_primary))
        item.setToolTip(f"[{method}] {record.url}\n状态: {status}\n时间: {record.created_at}")
        self.history_list.addItem(item)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        """双击历史记录"""
        record = item.data(Qt.ItemDataRole.UserRole)
        if record:
            self.history_selected.emit(record)

    def _on_search(self, keyword: str):
        """搜索历史"""
        self.history_list.clear()
        if keyword.strip():
            records = self.db.search_history(keyword.strip())
        else:
            records = self.db.get_history(limit=100)
        for record in records:
            self._add_history_item(record)

    def _on_clear(self):
        """清空历史"""
        reply = QMessageBox.question(
            self, "清空历史",
            "确定清空所有历史记录？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.clear_history()
            self.refresh_history()

    def add_record(self, record: HistoryRecord):
        """添加新的历史记录到列表顶部"""
        self.history_list.insertItem(0, QListWidgetItem())
        item = self.history_list.item(0)
        self._add_history_item(record)
