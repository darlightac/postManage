"""全局请求头管理对话框 - 全局生效，支持单个请求同名覆盖"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from app.config.settings import Settings
from app.config.themes import ThemeManager
from app.config.i18n import tr
from app.widgets.request_editor import KeyValueEditor


class GlobalHeadersDialog(QDialog):
    """全局请求头管理对话框"""

    headers_updated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = Settings()
        self.setMinimumSize(560, 420)
        self.resize(620, 480)
        self._init_ui()
        self.load_data()
        self.apply_theme(ThemeManager.current())

    def _init_ui(self):
        self.setWindowTitle(tr("gh_dialog_title", "全局请求头设置"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 顶部提示栏
        self.tip_label = QLabel(tr("gh_tip"))
        self.tip_label.setWordWrap(True)
        self.tip_label.setStyleSheet("""
            QLabel {
                padding: 10px 14px;
                border-radius: 6px;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        layout.addWidget(self.tip_label)

        # 键值编辑器
        self.editor = KeyValueEditor("Header", "Value")
        layout.addWidget(self.editor, 1)

        # 底部按钮栏
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.clear_btn = QPushButton(tr("btn_clear_all", "清空全部"))
        self.clear_btn.setFixedWidth(90)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(self.clear_btn)

        btn_layout.addStretch()

        self.cancel_btn = QPushButton(tr("dialog_cancel", "取消"))
        self.cancel_btn.setFixedWidth(80)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.save_btn = QPushButton(tr("dialog_save", "保存"))
        self.save_btn.setFixedWidth(80)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

    def load_data(self):
        """加载已保存的全局请求头"""
        data = self.settings.global_headers
        self.editor.set_data(data)

    def _on_clear(self):
        """清空全局请求头"""
        if self.editor.table.rowCount() <= 1 and not self.editor.get_data():
            return
        reply = QMessageBox.question(
            self,
            tr("gh_clear_confirm_title", "清空确认"),
            tr("gh_clear_confirm_msg", "确定要清空所有全局请求头吗？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.editor.table.setRowCount(0)
            self.editor._add_empty_row()

    def _on_save(self):
        """保存全局请求头"""
        headers_data = self.editor.get_data()
        self.settings.global_headers = headers_data
        self.settings.save()
        self.headers_updated.emit()
        self.accept()

    def apply_theme(self, t):
        """应用主题样式"""
        is_dark = (t.name == "dark")
        tip_bg = "#1e293b" if is_dark else "#eff6ff"
        tip_text = "#93c5fd" if is_dark else "#1e40af"
        tip_border = "#334155" if is_dark else "#bfdbfe"

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.bg_primary};
                color: {t.text_primary};
            }}
        """)
        self.tip_label.setStyleSheet(f"""
            QLabel {{
                background-color: {tip_bg};
                color: {tip_text};
                border: 1px solid {tip_border};
                border-radius: 6px;
                padding: 10px 14px;
                font-size: 13px;
                line-height: 1.5;
            }}
        """)
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {t.status_client_error};
                border: 1px solid {t.border};
                border-radius: 5px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: rgba(239, 68, 68, 0.1);
                border-color: {t.status_client_error};
            }}
        """)
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t.bg_input};
                color: {t.text_primary};
                border: 1px solid {t.border};
                border-radius: 5px;
                padding: 6px 16px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {t.bg_hover};
            }}
        """)
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #3b82f6;
                color: white;
                font-weight: 500;
                font-size: 13px;
                border: none;
                border-radius: 5px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{
                background-color: #2563eb;
            }}
            QPushButton:pressed {{
                background-color: #1d4ed8;
            }}
        """)
