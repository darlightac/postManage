"""设置对话框 - 全局超时时间、语言与数据/日志目录自定义"""

import os
import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QPushButton, QFormLayout, QComboBox,
    QLineEdit, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt

from app.config.settings import (
    Settings, get_data_dir, get_log_dir,
    get_default_data_dir, get_default_log_dir,
)
from app.config.themes import ThemeManager
from app.config.i18n import I18nManager, tr
from app.core.logger import reconfigure_logging
from app.core.db import Database


class SettingsDialog(QDialog):
    """全局设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = Settings()
        self.setWindowTitle(tr("settings_title", "全局设置"))
        self.setFixedWidth(580)
        self._init_ui()
        self._apply_theme()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        # 标题
        title_label = QLabel(tr("settings_title", "全局设置"))
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title_label)

        # 表单区域
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # 1. 超时时间设置
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(0, 999999)
        self.timeout_spin.setSingleStep(1000)
        self.timeout_spin.setSuffix(" ms")
        self.timeout_spin.setSpecialValueText(tr("settings_no_timeout", "无超时限制"))
        self.timeout_spin.setValue(self.settings.default_timeout)
        self.timeout_spin.setToolTip("默认超时时间（毫秒），0 表示不限制超时")
        self.timeout_spin.setFixedWidth(200)
        form_layout.addRow(tr("settings_default_timeout", "全局默认超时:"), self.timeout_spin)

        # 2. 界面语言选择
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("简体中文", "zh")
        self.lang_combo.addItem("English", "en")
        current_lang = I18nManager().current_language
        index = self.lang_combo.findData(current_lang)
        if index >= 0:
            self.lang_combo.setCurrentIndex(index)
        self.lang_combo.setFixedWidth(200)
        form_layout.addRow(tr("settings_language", "界面语言:"), self.lang_combo)

        # 3. 数据存储目录 (Data Directory)
        data_layout = QHBoxLayout()
        data_layout.setSpacing(6)

        self.data_dir_input = QLineEdit()
        self.data_dir_input.setText(str(get_data_dir()))
        self.data_dir_input.setToolTip("当前实际生效的 SQLite 数据库与数据文件存储目录")
        data_layout.addWidget(self.data_dir_input, 1)

        self.data_dir_browse_btn = QPushButton(tr("settings_browse", "浏览..."))
        self.data_dir_browse_btn.setFixedSize(68, 28)
        self.data_dir_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.data_dir_browse_btn.clicked.connect(self._on_browse_data_dir)
        data_layout.addWidget(self.data_dir_browse_btn)

        self.data_dir_reset_btn = QPushButton(tr("settings_reset_default", "恢复默认"))
        self.data_dir_reset_btn.setFixedSize(72, 28)
        self.data_dir_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.data_dir_reset_btn.setToolTip("恢复为软件安装目录同级 data 目录")
        self.data_dir_reset_btn.clicked.connect(self._on_reset_data_dir)
        data_layout.addWidget(self.data_dir_reset_btn)

        form_layout.addRow(tr("settings_data_dir", "数据存储目录:"), data_layout)

        # 4. 日志输出目录 (Log Directory)
        log_layout = QHBoxLayout()
        log_layout.setSpacing(6)

        self.log_dir_input = QLineEdit()
        self.log_dir_input.setText(str(get_log_dir()))
        self.log_dir_input.setToolTip("当前运行日志 postmanage.log 所在目录")
        log_layout.addWidget(self.log_dir_input, 1)

        self.log_dir_browse_btn = QPushButton(tr("settings_browse", "浏览..."))
        self.log_dir_browse_btn.setFixedSize(68, 28)
        self.log_dir_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_dir_browse_btn.clicked.connect(self._on_browse_log_dir)
        log_layout.addWidget(self.log_dir_browse_btn)

        self.log_dir_reset_btn = QPushButton(tr("settings_reset_default", "恢复默认"))
        self.log_dir_reset_btn.setFixedSize(72, 28)
        self.log_dir_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_dir_reset_btn.setToolTip("恢复为默认日志目录（数据目录下的 logs 文件夹）")
        self.log_dir_reset_btn.clicked.connect(self._on_reset_log_dir)
        log_layout.addWidget(self.log_dir_reset_btn)

        form_layout.addRow(tr("settings_log_dir", "日志输出目录:"), log_layout)

        layout.addLayout(form_layout)

        # 提示说明
        self.path_tip_label = QLabel(tr(
            "settings_path_tip",
            "💡 说明：数据和日志目录默认位于安装程序同级的 data 目录及 logs 目录（便携模式）。修改后，新数据和日志将保存在所选目录。"
        ))
        self.path_tip_label.setWordWrap(True)
        self.path_tip_label.setStyleSheet("font-size: 12px; color: #64748b; line-height: 1.5;")
        layout.addWidget(self.path_tip_label)

        hint_label = QLabel(tr("settings_hint", "提示：超时时间为 0 时表示不限制，请求将一直等待直到收到响应"))
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(hint_label)

        layout.addSpacing(6)

        # 底部操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton(tr("dialog_cancel", "取消"))
        self.cancel_btn.setFixedSize(84, 32)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.save_btn = QPushButton(tr("dialog_save", "保存"))
        self.save_btn.setFixedSize(84, 32)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:pressed { background-color: #1d4ed8; }
        """)
        self.save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

    def _on_browse_data_dir(self):
        """选择数据存储目录"""
        init_dir = self.data_dir_input.text().strip() or str(get_default_data_dir())
        chosen = QFileDialog.getExistingDirectory(
            self, tr("settings_data_dir", "选择数据存储目录"), init_dir
        )
        if chosen:
            self.data_dir_input.setText(str(Path(chosen).resolve()))

    def _on_reset_data_dir(self):
        """恢复数据目录为默认安装同级 data 目录"""
        self.data_dir_input.setText(str(get_default_data_dir()))

    def _on_browse_log_dir(self):
        """选择日志输出目录"""
        init_dir = self.log_dir_input.text().strip() or str(get_default_log_dir())
        chosen = QFileDialog.getExistingDirectory(
            self, tr("settings_log_dir", "选择日志输出目录"), init_dir
        )
        if chosen:
            self.log_dir_input.setText(str(Path(chosen).resolve()))

    def _on_reset_log_dir(self):
        """恢复日志目录为默认日志目录"""
        # 如果当前数据目录已修改，则默认是 <当前数据目录>/logs；否则是默认 logs
        curr_data = self.data_dir_input.text().strip()
        if curr_data:
            self.log_dir_input.setText(str(Path(curr_data) / "logs"))
        else:
            self.log_dir_input.setText(str(get_default_log_dir()))

    def _on_save(self):
        """保存设置，处理路径迁移与组件联动"""
        raw_data_dir = self.data_dir_input.text().strip()
        raw_log_dir = self.log_dir_input.text().strip()

        if not raw_data_dir:
            raw_data_dir = str(get_default_data_dir())
        if not raw_log_dir:
            raw_log_dir = str(Path(raw_data_dir) / "logs")

        target_data_path = Path(raw_data_dir).resolve()
        target_log_path = Path(raw_log_dir).resolve()

        old_data_path = get_data_dir().resolve()
        old_log_path = get_log_dir().resolve()

        data_dir_changed = (target_data_path != old_data_path)
        log_dir_changed = (target_log_path != old_log_path)

        # 1. 如果数据目录发生变更，执行数据迁移校验
        if data_dir_changed:
            target_data_path.mkdir(parents=True, exist_ok=True)
            old_db = old_data_path / "requestmanager.db"
            new_db = target_data_path / "requestmanager.db"

            if old_db.exists() and not new_db.exists():
                reply = QMessageBox.question(
                    self,
                    tr("settings_migrate_title", "数据迁移确认"),
                    tr("settings_migrate_msg", "检测到所选数据目录中暂无数据库，是否将当前现有数据（接口集合、历史记录等）复制迁移到新目录？\n\n点击【Yes】自动迁移复制数据\n点击【No】在新目录中创建空白数据库"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    try:
                        shutil.copy2(old_db, new_db)
                        # 迁移配置文件
                        old_cfg = old_data_path / "config.json"
                        new_cfg = target_data_path / "config.json"
                        if old_cfg.exists() and not new_cfg.exists():
                            shutil.copy2(old_cfg, new_cfg)
                        # 迁移 Cookie 库
                        old_ck = old_data_path / "cookies.json"
                        new_ck = target_data_path / "cookies.json"
                        if old_ck.exists() and not new_ck.exists():
                            shutil.copy2(old_ck, new_ck)
                    except Exception as e:
                        QMessageBox.warning(self, "数据迁移提示", f"部分文件复制失败:\n{e}")

        # 2. 持久化路径配置
        custom_data = str(target_data_path) if target_data_path != get_default_data_dir().resolve() else None
        curr_expected_logs = (target_data_path / "logs").resolve()
        custom_log = str(target_log_path) if (target_log_path != curr_expected_logs and target_log_path != get_default_log_dir().resolve()) else None

        self.settings.set_custom_paths(custom_data, custom_log)

        # 3. 动态热切换组件
        if data_dir_changed:
            Database().switch_database(self.settings.db_path)
            # 通知主界面刷新集合树与历史面板
            p = self.parent()
            while p:
                if hasattr(p, 'collection_tree'):
                    p.collection_tree.refresh_tree()
                if hasattr(p, 'history_panel'):
                    p.history_panel.refresh_history()
                p = p.parent()

        if log_dir_changed or data_dir_changed:
            reconfigure_logging()

        # 4. 保存超时与语言
        self.settings.default_timeout = self.timeout_spin.value()
        new_lang = self.lang_combo.currentData()
        if new_lang:
            I18nManager().set_language(new_lang)

        QMessageBox.information(
            self,
            tr("settings_title", "全局设置"),
            tr("settings_saved_tip", "设置已成功保存并生效！")
        )
        self.accept()

    def _apply_theme(self):
        t = ThemeManager.current()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.bg_primary};
            }}
            QLabel {{
                color: {t.text_primary};
            }}
            QLineEdit {{
                padding: 4px 8px;
                border: 1px solid {t.border};
                border-radius: 4px;
                background-color: {t.bg_input};
                color: {t.text_primary};
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border-color: {t.border_focus};
            }}
            QSpinBox {{
                padding: 4px 8px;
                border: 1px solid {t.border};
                border-radius: 4px;
                background-color: {t.bg_input};
                color: {t.text_primary};
            }}
            QComboBox {{
                padding: 4px 8px;
                border: 1px solid {t.border};
                border-radius: 4px;
                background-color: {t.bg_input};
                color: {t.text_primary};
            }}
            QPushButton {{
                background-color: {t.bg_input};
                color: {t.text_primary};
                border: 1px solid {t.border};
                border-radius: 4px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {t.bg_hover};
                border-color: {t.border_focus};
            }}
        """)
