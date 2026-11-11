"""请求编辑器组件 - URL 输入、方法选择、Headers/Body/Params/Auth 编辑"""

import re
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit,
    QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QCheckBox, QLabel, QHeaderView, QFormLayout,
    QSpinBox, QAbstractItemView, QFileDialog, QFrame,
    QStackedWidget, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QEvent
from PyQt6.QtGui import QColor, QBrush, QTextOption, QFontMetrics

from app.core.models import SavedRequest, HeaderItem, ParamItem
from app.config.constants import HTTP_METHODS, BODY_TYPES, AUTH_TYPES
from app.config.i18n import tr


class CellEditWidget(QWidget):
    """单元格编辑控件：QLineEdit 显示 + QTextEdit 编辑，单击切换"""

    edit_finished = pyqtSignal()  # 编辑完成信号

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._editing = False
        self._text = text
        self._table = None  # 由外部设置，用于调整行高
        self._row = -1
        self._col = -1
        self._owner_editor = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 显示模式：QLineEdit 只读，超长文本手动 elide 截断
        self.display = QLineEdit(text)
        self.display.setReadOnly(True)
        self.display.setFrame(False)
        self.display.setCursor(Qt.CursorShape.PointingHandCursor)
        self.display.setToolTip(text)  # 鼠标悬停查看完整内容
        # self.display.setStyleSheet("""
        #     QLineEdit {
        #         border: none;
        #         background: transparent;
        #         padding: 2px 4px;
        #         font-size: 13px;
        #     }
        # """)
        self.display.setStyleSheet("""
            QLineEdit {
                border: none;
                background: transparent;
                padding: 2px 4px;
                font-size: 13px;
                outline: none;   /* 去除焦点边框 */
            }
        """)
        self.display.mousePressEvent = lambda e: self._start_edit()
        self._update_display_text()
        layout.addWidget(self.display)

        # 编辑模式：QTextEdit 自动换行，高度自适应
        self.editor = QTextEdit()
        self.editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor.setFrameStyle(QFrame.Shape.NoFrame)
        self.editor.setHidden(True)
        self.editor.setStyleSheet("""
            QTextEdit {
                border: 1px solid #4a90d9;
                background: white;
                padding: 2px 4px;
                font-size: 13px;
            }
        """)
        self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor)
        self.editor.installEventFilter(self)  # 安装事件过滤器

    def eventFilter(self, obj, event):
        if obj == self.editor:
            if event.type() == QEvent.Type.FocusOut:
                self._finish_edit()
                return False  # 继续传递事件
            elif event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                    is_shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) or (key == Qt.Key.Key_Backtab)
                    self._finish_edit()
                    if self._owner_editor and hasattr(self._owner_editor, "_navigate_cell"):
                        self._owner_editor._navigate_cell(self._row, self._col, forward=not is_shift)
                    return True
                elif key == Qt.Key.Key_Escape:
                    self._cancel_edit()
                    return True
        return super().eventFilter(obj, event)

    def _cancel_edit(self):
        """取消编辑，恢复原文本"""
        if not self._editing:
            return
        self._editing = False
        self.editor.setHidden(True)
        self.display.setHidden(False)
        self.display.deselect()
        self.display.clearFocus()
        if self._table:
            self._table.clearSelection()
        QTimer.singleShot(0, self._update_display_text)
        if self._table and self._row >= 0:
            self._table.setRowHeight(self._row, 30)
    def _update_display_text(self):
        """根据当前宽度计算 elided 文本并更新显示"""
        if self._editing:
            return
        width = self.display.width() - 8  # 减去 padding
        if width <= 0:
            self.display.setText(self._text)
            return
        fm = QFontMetrics(self.display.font())
        elided = fm.elidedText(self._text, Qt.TextElideMode.ElideRight, width)
        self.display.setText(elided)

    def resizeEvent(self, event):
        """窗口大小变化时重新计算 elide 截断"""
        super().resizeEvent(event)
        self._update_display_text()

    def _start_edit(self):
        """单击 QLineEdit → 切换到 QTextEdit 编辑模式"""
        if self._editing:
            return
        self._editing = True
        self.display.setHidden(True)
        self.editor.setHidden(False)
        self.editor.setPlainText(self._text)
        self.editor.setFocus()
        self.editor.selectAll()
        # 调整行高以适应编辑器
        self._adjust_row_height()
        # 清除表格选中状态，避免其他单元格高亮
        if self._table:
            self._table.clearSelection()
            self._table.setCurrentItem(None)   # 清除当前项
        self._adjust_row_height()
    def _finish_edit(self):
        """失去焦点或 Ctrl+Enter → 保存内容，切换回 QLineEdit"""
        if not self._editing:
            return
        self._editing = False
        new_text = self.editor.toPlainText()
        self._text = new_text
        self.display.setToolTip(new_text)
        self.editor.setHidden(True)
        self.display.setHidden(False)
        # 取消选中状态和焦点，避免高亮残留
        self.display.deselect()
        self.display.clearFocus()
        # 清除表格行选中高亮
        if self._table:
            self._table.clearSelection()
        # 先显示 display，再延迟更新 elide 截断（等布局完成宽度计算）
        QTimer.singleShot(0, self._update_display_text)
        # 恢复行高为单行展示高度（不再是编辑器多行高度）
        if self._table and self._row >= 0:
            self._table.setRowHeight(self._row, 30)
        self.edit_finished.emit()

    def commit(self):
        """强制提交当前编辑态内容"""
        if self._editing:
            self._finish_edit()

    def _on_text_changed(self):
        """编辑时动态调整行高"""
        self._adjust_row_height()

    def _adjust_row_height(self):
        """根据 QTextEdit 内容高度调整表格行高"""
        if self._table and self._row >= 0:
            doc_height = int(self.editor.document().size().height())
            min_height = 24  # 最小行高
            row_height = max(min_height, doc_height + 8)  # 8px 边距
            self._table.setRowHeight(self._row, row_height)
            # 同步调整编辑器高度
            self.editor.setFixedHeight(row_height)

    def keyPressEvent(self, event):
        """Ctrl+Enter 提交，Escape 取消，Tab/Backtab 切换下一个输入框"""
        key = event.key()
        if key == Qt.Key.Key_Return and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self._finish_edit()
        elif key == Qt.Key.Key_Escape:
            self._cancel_edit()
        elif key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            is_shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) or (key == Qt.Key.Key_Backtab)
            self._finish_edit()
            if self._owner_editor and hasattr(self._owner_editor, "_navigate_cell"):
                self._owner_editor._navigate_cell(self._row, self._col, forward=not is_shift)
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        """编辑器失焦时保存"""
        if self._editing:
            # 延迟检查，避免点击其他 cell 时误触发
            QTimer.singleShot(100, self._delayed_finish)
        super().focusOutEvent(event)

    def _delayed_finish(self):
        """延迟保存：检查焦点是否还在编辑器内"""
        if self._editing and not self.editor.hasFocus():
            self._finish_edit()

    def get_text(self) -> str:
        """获取当前文本（无论显示还是编辑模式）"""
        if self._editing:
            return self.editor.toPlainText()
        return self._text

    def set_text(self, text: str):
        """设置文本"""
        self._text = text
        self._update_display_text()
        self.display.setToolTip(text)
        if self._editing:
            self.editor.setPlainText(text)


class CenteredCheckBox(QWidget):
    """水平垂直完全居中的表格复选框容器组件，与 QCheckBox 常用 API 及信号完全兼容"""

    toggled = pyqtSignal(bool)
    stateChanged = pyqtSignal(int)

    def __init__(self, checked: bool = True, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.checkbox = QCheckBox(self)
        self.checkbox.setChecked(checked)
        self.checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.checkbox.toggled.connect(self.toggled.emit)
        self.checkbox.stateChanged.connect(self.stateChanged.emit)

        layout.addWidget(self.checkbox)
        self.setLayout(layout)

    def isChecked(self) -> bool:
        return self.checkbox.isChecked()

    def setChecked(self, checked: bool):
        self.checkbox.setChecked(checked)

    def toggle(self):
        self.checkbox.toggle()

    def checkState(self):
        return self.checkbox.checkState()

    def setCheckState(self, state):
        self.checkbox.setCheckState(state)

    def text(self) -> str:
        return self.checkbox.text()

    def setText(self, text: str):
        self.checkbox.setText(text)

    def blockSignals(self, b: bool) -> bool:
        self.checkbox.blockSignals(b)
        return super().blockSignals(b)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.checkbox.toggle()
            event.accept()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.checkbox.toggle()
            event.accept()
        else:
            super().keyPressEvent(event)


class KeyValueEditor(QWidget):
    """通用的 Key-Value 编辑器（用于 Headers / Params）"""

    data_changed = pyqtSignal()

    def __init__(self, key_placeholder="Key", value_placeholder="Value"):
        super().__init__()
        self.key_placeholder = key_placeholder
        self.value_placeholder = value_placeholder
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ─── 顶部工具栏：批量编辑切换 ───
        header_bar = QHBoxLayout()
        header_bar.setContentsMargins(0, 0, 0, 4)

        self.bulk_edit_btn = QPushButton(tr("btn_bulk_edit", "批量编辑"))
        self.bulk_edit_btn.setFixedSize(72, 24)
        self.bulk_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bulk_edit_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #4a90d9;
                font-size: 12px;
                border: 1px solid #4a90d9;
                border-radius: 3px;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background-color: #4a90d9;
                color: white;
            }
        """)
        self.bulk_edit_btn.clicked.connect(self._toggle_bulk_edit)
        header_bar.addStretch()
        header_bar.addWidget(self.bulk_edit_btn)

        # ── 表格 + 批量文本区（堆叠切换） ───
        self._bulk_edit_mode = False
        self.stacked_widget = QStackedWidget()

        self.table = QTableWidget(0, 4)  # 增加一列用于删除按钮
        self.table.setWordWrap(True)
        self.table.setHorizontalHeaderLabels([tr("col_enabled", "启用"), self.key_placeholder, self.value_placeholder, ""])
        header_item = self.table.horizontalHeaderItem(0)
        if header_item:
            header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(3, 60)  # 删除按钮列宽度
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.SelectedClicked)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stacked_widget.addWidget(self.table)  # index 0: 表格模式

        # 批量编辑文本区
        self.bulk_text = QTextEdit()
        self.bulk_text.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.bulk_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.bulk_text.setPlaceholderText("每行一个键值对，格式: key: value\n\n示例:\nContent-Type: application/json\nAuthorization: Bearer token123")
        self.bulk_text.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, 'Courier New', monospace;
                font-size: 13px;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 8px;
            }
            QTextEdit:focus {
                border-color: #4a90d9;
            }
        """)
        self.stacked_widget.addWidget(self.bulk_text)  # index 1: 批量编辑模式

        # 容器：工具栏 + 堆叠区
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addLayout(header_bar)
        container_layout.addWidget(self.stacked_widget)
        layout.addWidget(container)

    def _add_empty_row(self):
        """添加一个空行"""
        self._add_row(True, "", "")

    def _sync_cell_rows(self):
        """同步所有 CellEditWidget 的行号、列号与宿主引用"""
        for r in range(self.table.rowCount()):
            for col in (1, 2):
                w = self.table.cellWidget(r, col)
                if isinstance(w, CellEditWidget):
                    w._row = r
                    w._col = col
                    w._owner_editor = self

    def _navigate_cell(self, row: int, col: int, forward: bool = True):
        """Tab / Shift+Tab 导航：移动到下一个/上一个单元格并自动开启编辑态"""
        if forward:
            if col == 1:
                next_row, next_col = row, 2
            else:
                next_row, next_col = row + 1, 1
                if next_row >= self.table.rowCount():
                    self._add_empty_row()
                    self._sync_cell_rows()
        else:
            if col == 2:
                next_row, next_col = row, 1
            else:
                if row > 0:
                    next_row, next_col = row - 1, 2
                else:
                    next_row, next_col = 0, 1

        if 0 <= next_row < self.table.rowCount():
            target = self.table.cellWidget(next_row, next_col)
            if isinstance(target, CellEditWidget):
                model_idx = self.table.model().index(next_row, next_col)
                if model_idx.isValid():
                    self.table.scrollTo(model_idx)
                QTimer.singleShot(0, target._start_edit)

    def set_data(self, items: list):
        """设置数据 items: list[HeaderItem] or list[ParamItem] or list[dict]"""
        # 加载数据时强制回到表格模式
        if self._bulk_edit_mode:
            self._bulk_edit_mode = False
            self.bulk_edit_btn.setText(tr("btn_bulk_edit", "批量编辑"))
            self.stacked_widget.setCurrentIndex(0)
        self.table.setRowCount(0)
        for item in items:
            if isinstance(item, dict):
                k = item.get("key", "")
                v = item.get("value", "")
                en = item.get("enabled", True)
            else:
                k = getattr(item, "key", "")
                v = getattr(item, "value", "")
                en = getattr(item, "enabled", True)
            # 只要 key 或 value 任意一项不为空，均保留展示（支持空 key 或空 value）
            if k or v:
                self._add_row(en, k, v)
        # 始终保留一个尾部空行，方便用户直接输入新条目（空行不会参与数据收集）
        self._add_empty_row()
        # 加载数据后自动调整行高以适配换行内容
        self.table.resizeRowsToContents()
        if hasattr(self, '_parent') and self._parent and hasattr(self._parent, '_update_tab_badges'):
            self._parent._update_tab_badges()
        self.data_changed.emit()

    def _add_row(self, enabled: bool, key: str, value: str):
        row = self.table.rowCount()
        self.table.insertRow(row)

        # 启用复选框（居中放置）
        cb = CenteredCheckBox(enabled)
        cb.toggled.connect(lambda *_: self.data_changed.emit())
        self.table.setCellWidget(row, 0, cb)

        # Key 列 - CellEditWidget
        key_editor = CellEditWidget(key, self.table)
        key_editor._table = self.table
        key_editor._row = row
        key_editor._col = 1
        key_editor._owner_editor = self
        key_editor.edit_finished.connect(self._on_cell_edit_finished)
        self.table.setCellWidget(row, 1, key_editor)

        # Value 列 - CellEditWidget
        val_editor = CellEditWidget(value, self.table)
        val_editor._table = self.table
        val_editor._row = row
        val_editor._col = 2
        val_editor._owner_editor = self
        val_editor.edit_finished.connect(self._on_cell_edit_finished)
        self.table.setCellWidget(row, 2, val_editor)

        # 删除按钮
        delete_btn = QPushButton("删除")
        delete_btn.setFixedSize(50, 24)
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #4a90d9;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover {
                color: #ff4444;
            }
        """)
        delete_btn.clicked.connect(self._on_delete_clicked)
        self.table.setCellWidget(row, 3, delete_btn)

    def get_data(self) -> list[dict]:
        """获取数据列表（表格模式和批量编辑模式均支持，保留空 key 或空 value）"""
        if self._bulk_edit_mode:
            return self._parse_bulk_text(self.bulk_text.toPlainText())
        result = []
        for row in range(self.table.rowCount()):
            cb = self.table.cellWidget(row, 0)
            key_widget = self.table.cellWidget(row, 1)
            val_widget = self.table.cellWidget(row, 2)
            # 强制提交正在编辑态的单元格，防止切 Tab 丢失正在输入的值
            if isinstance(key_widget, CellEditWidget):
                key_widget.commit()
            if isinstance(val_widget, CellEditWidget):
                val_widget.commit()
            enabled = cb.isChecked() if cb else True
            key = key_widget.get_text() if isinstance(key_widget, CellEditWidget) else ""
            value = val_widget.get_text() if isinstance(val_widget, CellEditWidget) else ""
            # 只要 key 或 value 任意一个不为空，即保留该项（即使某一项为 null/empty）
            if key or value:
                result.append({"key": key, "value": value, "enabled": enabled})
        return result

    def _toggle_bulk_edit(self):
        """切换表格模式 / 批量编辑模式"""
        self._bulk_edit_mode = not self._bulk_edit_mode
        if self._bulk_edit_mode:
            # 表格 → 批量文本：将当前表格数据序列化为 key: value 文本
            lines = []
            for row in range(self.table.rowCount()):
                cb = self.table.cellWidget(row, 0)
                key_widget = self.table.cellWidget(row, 1)
                val_widget = self.table.cellWidget(row, 2)
                if isinstance(key_widget, CellEditWidget):
                    key_widget.commit()
                if isinstance(val_widget, CellEditWidget):
                    val_widget.commit()
                enabled = cb.isChecked() if cb else True
                key = key_widget.get_text() if isinstance(key_widget, CellEditWidget) else ""
                value = val_widget.get_text() if isinstance(val_widget, CellEditWidget) else ""
                if key or value:
                    prefix = "" if enabled else "# "
                    lines.append(f"{prefix}{key}: {value}")
            self.bulk_text.setPlainText("\n".join(lines))
            self.bulk_edit_btn.setText(tr("btn_kv_edit", "键值编辑"))
            self.stacked_widget.setCurrentIndex(1)
        else:
            # 批量文本 → 表格：解析文本填充表格
            self._parse_bulk_to_table(self.bulk_text.toPlainText())
            self.bulk_edit_btn.setText(tr("btn_bulk_edit", "批量编辑"))
            self.stacked_widget.setCurrentIndex(0)

    def _parse_bulk_to_table(self, text: str):
        """将批量编辑文本解析并填充到表格"""
        items = self._parse_bulk_text(text)
        self.table.setRowCount(0)
        for item in items:
            self._add_row(item["enabled"], item["key"], item["value"])
        self._add_empty_row()
        self.table.resizeRowsToContents()
        self.data_changed.emit()

    def _parse_bulk_text(self, text: str) -> list[dict]:
        """解析批量编辑文本为键值对列表"""
        result = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            enabled = True
            if line.startswith("#"):
                enabled = False
                line = line[1:].strip()
            elif line.startswith("//"):
                enabled = False
                line = line[2:].strip()
            if not line:
                continue
            # 优先按 ": " 分割（HTTP 头标准格式），其次按 ":" 分割
            if ": " in line:
                key, value = line.split(": ", 1)
            elif ":" in line:
                key, value = line.split(":", 1)
            else:
                key, value = line, ""
            if key or value:
                result.append({"key": key, "value": value, "enabled": enabled})
        return result

    def _on_cell_edit_finished(self):
        """CellEditWidget 编辑完成后的回调：更新 URL + 检查自动添加行"""
        # 通知父组件更新 URL（如果是 params_editor）
        if hasattr(self, '_parent') and self._parent:
            self._parent._update_url_from_params()
            if hasattr(self._parent, '_update_tab_badges'):
                self._parent._update_tab_badges()
        # 检查最后一行是否有内容，有则自动添加新空行
        self._check_and_add_row()
        self.data_changed.emit()

    def _check_and_add_row(self):
        """检查最后一行是否有内容（key 或 value），有则自动添加新空行"""
        last_row = self.table.rowCount() - 1
        if last_row < 0:
            return
        key_widget = self.table.cellWidget(last_row, 1)
        val_widget = self.table.cellWidget(last_row, 2)
        key_text = key_widget.get_text() if isinstance(key_widget, CellEditWidget) else ""
        val_text = val_widget.get_text() if isinstance(val_widget, CellEditWidget) else ""
        if key_text or val_text:
            self._add_empty_row()
            self._sync_cell_rows()
            # 通知父组件更新 URL（如果是 params_editor）
            if hasattr(self, '_parent') and self._parent:
                self._parent._update_url_from_params()
                if hasattr(self._parent, '_update_tab_badges'):
                    self._parent._update_tab_badges()

    def _remove_selected(self):
        rows = set()
        for item in self.table.selectedItems():
            rows.add(item.row())
        for row in sorted(rows, reverse=True):
            self.table.removeRow(row)

    def _on_delete_clicked(self):
        """动态查找点击删除按钮所在的行并删除"""
        button = self.sender()
        if not button:
            return
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 3) is button:
                self._delete_row(r)
                break

    def _delete_row(self, row: int):
        """删除指定行"""
        self.table.removeRow(row)
        self._sync_cell_rows()
        # 通知父组件更新 URL（如果是 params_editor）
        if hasattr(self, '_parent') and self._parent:
            self._parent._update_url_from_params()
            if hasattr(self._parent, '_update_tab_badges'):
                self._parent._update_tab_badges()
        self.data_changed.emit()

    def retranslate_ui(self):
        """刷新表头与批量编辑按钮语言"""
        self.table.setHorizontalHeaderLabels([tr("col_enabled", "启用"), self.key_placeholder, self.value_placeholder, ""])
        header_item = self.table.horizontalHeaderItem(0)
        if header_item:
            header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if hasattr(self, 'bulk_edit_btn'):
            self.bulk_edit_btn.setText(tr("btn_kv_edit", "键值编辑") if self._bulk_edit_mode else tr("btn_bulk_edit", "批量编辑"))
        for r in range(self.table.rowCount()):
            del_btn = self.table.cellWidget(r, 3)
            if isinstance(del_btn, QPushButton):
                del_btn.setText(tr("btn_delete", "删除"))


class RequestEditor(QWidget):
    """请求编辑器主组件"""

    send_requested = pyqtSignal(object)  # SavedRequest
    cancel_requested = pyqtSignal()  # 取消请求信号
    global_headers_updated = pyqtSignal()  # 全局请求头变更信号（广播至所有 Tab）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_request_id = None
        self._request_name = ""  # 请求名称（用于标签页标题与集合树展示）
        self._collection_id = ""  # 关联的集合 ID
        self._timeout = 0  # 超时时间（毫秒），0 表示无超时
        self.proxy_config = {}  # 接口专属代理配置 (为空或 mode="default" 表示继承全局)
        self._sending = False  # 是否正在发送中
        self._is_exporting_curl = False  # 是否正在导出 cURL（防循环解析）
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ─── URL 栏 ─────────────────────────────────────────
        url_layout = QHBoxLayout()
        url_layout.setSpacing(6)

        self.method_combo = QComboBox()
        self.method_combo.addItems(HTTP_METHODS)
        self.method_combo.setFixedWidth(105)
        self.method_combo.setFixedHeight(36)
        self.method_combo.currentTextChanged.connect(self._on_method_changed)
        url_layout.addWidget(self.method_combo)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("输入请求 URL，例如 https://api.example.com/users")
        self.url_input.setFixedHeight(36)
        self.url_input.setStyleSheet("QLineEdit { padding: 4px 12px; font-size: 13px; font-family: Consolas, 'Segoe UI', monospace; }")
        self.url_input.returnPressed.connect(self._on_send)
        self.url_input.textChanged.connect(self._on_url_changed)  # 监听 URL 变化
        url_layout.addWidget(self.url_input)

        self.send_btn = QPushButton("发送")
        self.send_btn.setFixedSize(92, 36)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                font-weight: bold;
                font-size: 13px;
                padding: 0 16px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:pressed {
                background-color: #047857;
            }
        """)
        self.send_btn.clicked.connect(self._on_send)
        url_layout.addWidget(self.send_btn)

        # cURL 导出按钮
        self.curl_btn = QPushButton("cURL")
        self.curl_btn.setFixedSize(64, 36)
        self.curl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.curl_btn.setToolTip("将请求转换为 cURL 命令（点击切换显示/隐藏）")
        self.curl_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #555555;
                font-weight: 500;
                font-size: 12px;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.05);
            }
        """)
        self.curl_btn.clicked.connect(self._on_toggle_curl_tab)
        url_layout.addWidget(self.curl_btn)

        # 压测按钮 (Go 协程高并发引擎)
        self.stress_btn = QPushButton("压测")
        self.stress_btn.setFixedSize(68, 36)
        self.stress_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stress_btn.setToolTip("针对当前接口发起高并发性能压测 (Go 原生协程池、P90/P99延迟与瓶颈诊断)")
        self.stress_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #555555;
                font-weight: 500;
                font-size: 12px;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 0 8px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.05);
            }
        """)
        self.stress_btn.clicked.connect(self._on_open_stress_dialog)
        url_layout.addWidget(self.stress_btn)

        # 页面接口嗅探按钮
        self.sniffer_btn = QPushButton("嗅探")
        self.sniffer_btn.setFixedSize(68, 36)
        self.sniffer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sniffer_btn.setToolTip("页面接口智能嗅探 (输入前端网页 URL，自动提取后端 API 并健康巡检)")
        self.sniffer_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #555555;
                font-weight: 500;
                font-size: 12px;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 0 8px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.05);
            }
        """)
        self.sniffer_btn.clicked.connect(self._on_open_sniffer_dialog)
        url_layout.addWidget(self.sniffer_btn)

        layout.addLayout(url_layout)

        # ─── Tab 区域 ─────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setObjectName("editorSubTabs")

        # Params Tab
        self.params_editor = KeyValueEditor("参数名", "参数值")
        self.params_editor._parent = self  # 设置父组件引用
        self.params_editor._add_empty_row()  # 添加默认空行
        self.tabs.addTab(self.params_editor, "Params")

        # Headers Tab
        self.headers_editor = KeyValueEditor("Header", "Value")
        self.headers_editor._parent = self
        self.headers_editor._add_empty_row()  # 添加默认空行
        self.tabs.addTab(self.headers_editor, "Headers")

        # Cookies Tab
        from app.widgets.cookie_manager import CookieManager
        self.cookie_manager = CookieManager()
        self.tabs.addTab(self.cookie_manager, "Cookies")

        # Body Tab
        body_widget = QWidget()
        body_layout = QVBoxLayout(body_widget)
        body_layout.setContentsMargins(4, 4, 4, 4)

        body_type_layout = QHBoxLayout()
        self.body_type_label = QLabel("Body 类型:")
        body_type_layout.addWidget(self.body_type_label)
        self.body_type_combo = QComboBox()
        self.body_type_combo.addItems(BODY_TYPES)
        self.body_type_combo.currentTextChanged.connect(self._on_body_type_changed)
        body_type_layout.addWidget(self.body_type_combo)
        body_type_layout.addStretch()
        body_layout.addLayout(body_type_layout)

        # Body 内容区域（动态切换）
        self.body_stack = QWidget()
        self.body_stack_layout = QVBoxLayout(self.body_stack)
        self.body_stack_layout.setContentsMargins(0, 0, 0, 0)
        
        # Text Edit for JSON/Raw/URLEncoded
        from app.widgets.json_editor import JsonTextEdit
        self.body_edit = JsonTextEdit()
        self.body_edit.setPlaceholderText('输入请求体内容...\n\nJSON 示例:\n{\n  "key": "value"\n}\n\nForm 示例（每行 key=value）:\nname=test\nage=18')
        self.body_edit.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, 'Courier New', monospace;
                font-size: 13px;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        
        # JSON 格式化按钮（紧凑尺寸，完全展示文字，不冗余占位）
        self.json_format_btn = QPushButton("格式化 JSON")
        self.json_format_btn.setFixedHeight(24)
        self.json_format_btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.json_format_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.json_format_btn.setStyleSheet("""
            QPushButton {
                padding: 2px 8px;
                text-align: center;
                font-size: 12px;
                border-radius: 4px;
            }
        """)
        self.json_format_btn.clicked.connect(self._format_json)
        self.json_format_btn.setVisible(False)  # 初始隐藏，仅在 body_type 为 json 时显示

        # 底部操作栏（左对齐，自适应文字宽度）
        json_btn_layout = QHBoxLayout()
        json_btn_layout.setContentsMargins(0, 4, 0, 0)
        json_btn_layout.addWidget(self.json_format_btn)
        json_btn_layout.addStretch()

        # 创建一个容器布局放置编辑器和格式化按钮
        body_edit_container = QWidget()
        body_edit_layout = QVBoxLayout(body_edit_container)
        body_edit_layout.setContentsMargins(0, 0, 0, 0)
        body_edit_layout.addWidget(self.body_edit)
        body_edit_layout.addLayout(json_btn_layout)
        
        self.body_stack_layout.addWidget(body_edit_container)
        
        # Form Data Editor (KeyValueEditor)
        self.formdata_editor = KeyValueEditor("字段名", "值")
        self.formdata_editor._parent = self
        self.formdata_editor.setVisible(False)
        self.formdata_editor._add_empty_row()  # 添加默认空行
        self.body_stack_layout.addWidget(self.formdata_editor)
        
        # Binary File Selector
        self.binary_widget = QWidget()
        binary_layout = QHBoxLayout(self.binary_widget)
        binary_layout.setContentsMargins(0, 0, 0, 0)
        self.binary_file_input = QLineEdit()
        self.binary_file_input.setPlaceholderText("选择文件...")
        self.binary_file_input.setReadOnly(True)
        binary_layout.addWidget(self.binary_file_input)
        
        self.binary_select_btn = QPushButton("选择文件")
        self.binary_select_btn.clicked.connect(self._on_select_binary_file)
        binary_layout.addWidget(self.binary_select_btn)
        self.binary_widget.setVisible(False)
        self.body_stack_layout.addWidget(self.binary_widget)
        
        body_layout.addWidget(self.body_stack)
        self.tabs.addTab(body_widget, "Body")

        # Auth Tab
        auth_widget = QWidget()
        auth_layout = QFormLayout(auth_widget)
        auth_layout.setContentsMargins(8, 8, 8, 8)

        self.auth_type_combo = QComboBox()
        self.auth_type_combo.addItems(AUTH_TYPES)
        self.auth_type_combo.currentTextChanged.connect(self._on_auth_type_changed)
        auth_layout.addRow("认证类型:", self.auth_type_combo)

        self.auth_username = QLineEdit()
        self.auth_username.setPlaceholderText("用户名")
        auth_layout.addRow("用户名:", self.auth_username)

        self.auth_password = QLineEdit()
        self.auth_password.setPlaceholderText("密码")
        self.auth_password.setEchoMode(QLineEdit.EchoMode.Password)
        auth_layout.addRow("密码:", self.auth_password)

        self.auth_token = QLineEdit()
        self.auth_token.setPlaceholderText("Token")
        self.auth_token.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        auth_layout.addRow("Token:", self.auth_token)

        self.auth_apikey_key = QLineEdit()
        self.auth_apikey_key.setPlaceholderText("Key 名称")
        auth_layout.addRow("Key:", self.auth_apikey_key)

        self.auth_apikey_value = QLineEdit()
        self.auth_apikey_value.setPlaceholderText("Key 值")
        auth_layout.addRow("Value:", self.auth_apikey_value)

        self.tabs.addTab(auth_widget, "Auth")

        # ─── 前置处理与后置处理 Tab ───
        from app.widgets.pre_post_processor_widget import PreProcessorWidget, PostProcessorWidget
        self.pre_processor_widget = PreProcessorWidget()
        self.tabs.addTab(self.pre_processor_widget, tr("tab_pre_processor", "前置处理"))

        self.post_processor_widget = PostProcessorWidget()
        self.tabs.addTab(self.post_processor_widget, tr("tab_post_processor", "后置处理"))
        
        # cURL Export Tab
        curl_widget = QWidget()
        curl_layout = QVBoxLayout(curl_widget)
        curl_layout.setContentsMargins(8, 8, 8, 8)
        curl_layout.setSpacing(8)
        
        curl_header_layout = QHBoxLayout()
        self.curl_copy_btn = QPushButton("复制")
        self.curl_copy_btn.setFixedWidth(80)
        self.curl_copy_btn.clicked.connect(self._on_copy_curl)
        self.curl_label = QLabel("cURL 命令:")
        curl_header_layout.addWidget(self.curl_label)
        curl_header_layout.addStretch()
        curl_header_layout.addWidget(self.curl_copy_btn)
        curl_layout.addLayout(curl_header_layout)
        
        from app.widgets.curl_editor import CurlTextEdit
        self.curl_display = CurlTextEdit()
        self.curl_display.setReadOnly(False)  # 允许编辑，用于粘贴 cURL
        self.curl_display.textChanged.connect(self._on_curl_pasted)  # 监听粘贴事件
        curl_layout.addWidget(self.curl_display)
        
        self.curl_widget = curl_widget
        self.tabs.addTab(self.curl_widget, "cURL Export")

        # ─── 全局请求头 Tab（紧随 cURL Export 之后，与其他 Tab 风格保持一致） ───
        self.global_headers_widget = QWidget()
        gh_layout = QVBoxLayout(self.global_headers_widget)
        gh_layout.setContentsMargins(4, 4, 4, 4)
        gh_layout.setSpacing(6)

        # 顶部提示栏与操作按钮
        gh_top_layout = QHBoxLayout()
        gh_top_layout.setContentsMargins(2, 2, 2, 2)
        gh_top_layout.setSpacing(8)

        self.gh_tip_label = QLabel(tr("gh_tab_tip", "💡 全局请求头在所有请求中均自动生效。若某个请求单独配置了相同名称（大小写不敏感）的请求头，将以该请求中的配置为准。"))
        self.gh_tip_label.setWordWrap(True)
        gh_top_layout.addWidget(self.gh_tip_label, 1)

        self.gh_clear_btn = QPushButton(tr("btn_clear_all", "清空全部"))
        self.gh_clear_btn.setFixedSize(72, 24)
        self.gh_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gh_clear_btn.clicked.connect(self._on_clear_global_headers)
        gh_top_layout.addWidget(self.gh_clear_btn)

        self.gh_save_btn = QPushButton(tr("dialog_save", "保存"))
        self.gh_save_btn.setFixedSize(60, 24)
        self.gh_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gh_save_btn.clicked.connect(self._on_manual_save_global_headers)
        gh_top_layout.addWidget(self.gh_save_btn)

        gh_layout.addLayout(gh_top_layout)

        # KeyValueEditor 编辑器
        self.global_headers_editor = KeyValueEditor("Header", "Value")
        self.global_headers_editor._parent = self
        gh_layout.addWidget(self.global_headers_editor, 1)

        self.tabs.addTab(self.global_headers_widget, tr("tab_global_headers", "全局请求头"))

        # 初始化载入全局请求头数据并连接变更信号
        self._reload_global_headers()
        self.global_headers_editor.data_changed.connect(self._save_global_headers)

        layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._on_auth_type_changed("none")

        # 信号连接以动态刷新角标
        self.params_editor.table.cellChanged.connect(lambda *_: self._update_tab_badges())
        self.headers_editor.table.cellChanged.connect(lambda *_: self._update_tab_badges())
        self.body_type_combo.currentTextChanged.connect(lambda *_: self._update_tab_badges())
        self.auth_type_combo.currentTextChanged.connect(lambda *_: self._update_tab_badges())

        from app.config.themes import ThemeManager
        self.apply_theme(ThemeManager.current())
        self._update_tab_badges()

    def _save_global_headers(self):
        """保存全局请求头到 Settings 并刷新角标，向所有 Tab 发出广播"""
        if getattr(self, '_loading_global_headers', False):
            return
        from app.config.settings import Settings
        data = self.global_headers_editor.get_data()
        Settings().global_headers = data
        Settings().save()
        self._update_tab_badges()
        self.global_headers_updated.emit()

    def _on_manual_save_global_headers(self):
        """手动点击保存按钮"""
        self._save_global_headers()
        from PyQt6.QtWidgets import QToolTip
        from PyQt6.QtGui import QCursor
        from app.config.i18n import tr
        QToolTip.showText(QCursor.pos(), tr("gh_saved_msg", "全局请求头已保存"), self.gh_save_btn, msecShowTime=2000)

    def _reload_global_headers(self):
        """从 Settings 载入最新的全局请求头"""
        if not hasattr(self, 'global_headers_editor'):
            return
        self._loading_global_headers = True
        try:
            from app.config.settings import Settings
            data = Settings().global_headers or []
            self.global_headers_editor.set_data(data)
        finally:
            self._loading_global_headers = False
        self._update_tab_badges()

    def _on_clear_global_headers(self):
        """清空全局请求头"""
        if self.global_headers_editor.table.rowCount() <= 1 and not self.global_headers_editor.get_data():
            return
        from PyQt6.QtWidgets import QMessageBox
        from app.config.i18n import tr
        reply = QMessageBox.question(
            self,
            tr("gh_clear_confirm_title", "清空确认"),
            tr("gh_clear_confirm_msg", "确定要清空所有全局请求头吗？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.global_headers_editor.set_data([])
            self._save_global_headers()

    def switch_to_global_headers_tab(self):
        """快捷切换到全局请求头 Tab"""
        if hasattr(self, 'global_headers_widget'):
            idx = self.tabs.indexOf(self.global_headers_widget)
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)

    def _on_open_stress_dialog(self):
        """打开高并发压测对话框 (Go 协程引擎)"""
        self._ensure_url_protocol()
        req = self.build_request()
        if not req.url:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "无法压测", "请先输入请求 URL")
            return
        from app.widgets.stress_dialog import StressDialog
        self._stress_dlg = StressDialog(req, self)
        self._stress_dlg.show()
        self._stress_dlg.raise_()
        self._stress_dlg.activateWindow()

    def _on_open_sniffer_dialog(self):
        """打开页面接口智能嗅探对话框"""
        self._ensure_url_protocol()
        url = self.url_input.text().strip()
        win = self.window()
        if win and hasattr(win, "_on_open_page_sniffer_for_url"):
            win._on_open_page_sniffer_for_url(url)
        else:
            from app.widgets.sniffer_dialog import PageSnifferDialog
            self._sniffer_dlg = PageSnifferDialog(url, self)
            self._sniffer_dlg.import_request_requested.connect(self._on_sniffed_request_imported)
            self._sniffer_dlg.show()

    def load_from_saved_request(self, req):
        """从 SavedRequest 对象加载完整数据（包含方法、URL、请求头、参数、请求体与代理）"""
        if not req:
            return
        if hasattr(req, "method") and req.method:
            self.method_combo.setCurrentText(req.method)
        if hasattr(req, "url") and req.url:
            self.url_input.setText(req.url)
        if hasattr(req, "name") and req.name:
            self._request_name = req.name

        # Headers
        headers = getattr(req, "headers", None)
        if headers is not None:
            if isinstance(headers, str):
                try:
                    headers = json.loads(headers)
                except Exception:
                    headers = []
            if isinstance(headers, list):
                self.headers_editor.set_data(headers)
            elif isinstance(headers, dict):
                self.headers_editor.set_data([{"key": str(k), "value": str(v), "enabled": True} for k, v in headers.items()])

        # Params
        params = getattr(req, "params", None)
        if params is not None and params != "[]":
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except Exception:
                    params = []
            if isinstance(params, list):
                self.params_editor.set_data(params)
        else:
            req_url = getattr(req, "url", "")
            if req_url and "?" in req_url:
                self._sync_url_to_params(req_url)

        # Body
        body_type = getattr(req, "body_type", "none") or "none"
        body_content = getattr(req, "body_content", "") or ""
        self.body_type_combo.setCurrentText(body_type)
        if body_type in ("json", "raw", "xml", "text"):
            self.body_edit.setPlainText(body_content)
        elif body_type == "form":
            form_items = []
            for line in body_content.split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    form_items.append({"key": key.strip(), "value": value.strip(), "enabled": True})
            self.formdata_editor.table.setRowCount(0)
            for item in form_items:
                self.formdata_editor._add_row(True, item['key'], item['value'])
            self.formdata_editor._add_empty_row()
        elif body_type == "binary":
            self.binary_file_input.setText(body_content)

        # Proxy
        proxy = getattr(req, "proxy", None)
        if proxy is not None:
            self.proxy_config = dict(proxy) if isinstance(proxy, dict) else {}

        self._update_method_style()

    def _on_sniffed_request_imported(self, req_data):
        """从嗅探对话框导入选中的接口并打开新标签页进行独立调试（防止覆盖原有内容）"""
        win = self.window()
        if win and hasattr(win, "_on_import_sniffed_request"):
            win._on_import_sniffed_request(req_data)
        else:
            self.load_from_saved_request(req_data)
            # 联动刷新外层 RequestTabPage 与 Tab 标题
            parent = self.parent()
            while parent:
                if hasattr(parent, "refresh_name_display"):
                    parent.refresh_name_display()
                    tab_bar = parent.parent()
                    while tab_bar:
                        if hasattr(tab_bar, "refresh_title"):
                            tab_bar.refresh_title(parent)
                            break
                        tab_bar = tab_bar.parent()
                    break
                parent = parent.parent()

    def apply_theme(self, t):
        """应用主题"""
        self._update_method_style()
        btn_sub_style = f"""
            QPushButton {{
                background-color: {t.bg_input};
                color: {t.text_secondary};
                font-weight: 500;
                font-size: 12px;
                border: 1px solid {t.border};
                border-radius: 6px;
                padding: 0 8px;
            }}
            QPushButton:hover {{
                background-color: {t.bg_hover};
                color: {t.text_primary};
                border-color: {t.border_focus};
            }}
        """
        self.curl_btn.setStyleSheet(btn_sub_style)
        if hasattr(self, 'stress_btn'):
            self.stress_btn.setStyleSheet(btn_sub_style)
        if hasattr(self, 'sniffer_btn'):
            self.sniffer_btn.setStyleSheet(btn_sub_style)
        self.body_edit.setStyleSheet(f"""
            QTextEdit {{
                font-family: Consolas, 'Courier New', monospace;
                font-size: 13px;
                border: 1px solid {t.border_light};
                border-radius: 4px;
                padding: 8px;
                background-color: {t.bg_input};
                color: {t.text_primary};
            }}
        """)
        self.body_type_label.setStyleSheet(f"color: {t.text_primary};")
        if hasattr(self, 'json_format_btn'):
            self.json_format_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t.bg_input};
                    color: {t.text_primary};
                    border: 1px solid {t.border};
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 12px;
                    text-align: center;
                }}
                QPushButton:hover {{
                    background-color: {t.bg_hover};
                    border-color: {t.border_focus};
                }}
            """)
        if hasattr(self, 'gh_tip_label'):
            self.gh_tip_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {t.bg_secondary};
                    color: {t.text_secondary};
                    border: 1px solid {t.border_light};
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 12px;
                }}
            """)
        if hasattr(self, 'gh_clear_btn'):
            self.gh_clear_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {t.text_secondary};
                    border: 1px solid {t.border};
                    border-radius: 3px;
                    font-size: 12px;
                    padding: 2px 8px;
                }}
                QPushButton:hover {{
                    background-color: {t.bg_hover};
                    color: {t.status_client_error};
                    border-color: {t.status_client_error};
                }}
            """)
        if hasattr(self, 'gh_save_btn'):
            self.gh_save_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t.accent};
                    color: #ffffff;
                    border: none;
                    border-radius: 3px;
                    font-size: 12px;
                    font-weight: 500;
                    padding: 2px 8px;
                }}
                QPushButton:hover {{
                    background-color: {t.accent_hover};
                }}
            """)
        if hasattr(self, 'global_headers_btn'):
            self.global_headers_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t.bg_input};
                    color: {t.text_secondary};
                    border: 1px solid {t.border};
                    border-radius: 4px;
                    padding: 3px 8px;
                    font-size: 12px;
                    margin-right: 4px;
                }}
                QPushButton:hover {{
                    background-color: {t.bg_hover};
                    color: {t.text_primary};
                }}
            """)
        if hasattr(self, 'curl_label'):
            self.curl_label.setStyleSheet(f"color: {t.text_primary}; font-weight: 500;")
        if hasattr(self, 'curl_copy_btn'):
            self.curl_copy_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t.bg_input};
                    color: {t.text_primary};
                    border: 1px solid {t.border};
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: {t.bg_hover};
                }}
            """)
        if hasattr(self, 'curl_display'):
            self.curl_display.setStyleSheet(f"""
                QTextEdit {{
                    font-family: Consolas, 'Courier New', monospace;
                    font-size: 13px;
                    border: 1px solid {t.border_light};
                    border-radius: 4px;
                    padding: 8px;
                    background-color: {t.bg_input};
                    color: {t.text_primary};
                }}
            """)

    def _on_method_changed(self, method: str):
        self._update_method_style(method)

    def _update_method_style(self, method: str = None):
        """根据当前方法与主题动态为方法选择框着色"""
        m = method or self.method_combo.currentText()
        from app.config.themes import ThemeManager
        t = ThemeManager.current()
        color = t.method_colors.get(m, t.text_primary)
        self.method_combo.setStyleSheet(f"""
            QComboBox {{
                font-family: Consolas, 'Courier New', monospace;
                font-weight: bold;
                font-size: 13px;
                color: {color};
                background-color: {t.bg_input};
                border: 1px solid {t.border};
                border-radius: 6px;
                padding: 4px 10px;
            }}
            QComboBox:hover {{
                border-color: {t.border_focus};
            }}
        """)

    def retranslate_ui(self):
        """动态刷新界面语言"""
        from app.config.i18n import tr
        if hasattr(self, 'send_btn'):
            self.send_btn.setText(tr("btn_cancel") if self._sending else tr("btn_send"))
        if hasattr(self, 'curl_btn'):
            self.curl_btn.setText(tr("btn_curl"))
        if hasattr(self, 'stress_btn'):
            self.stress_btn.setText(tr("btn_stress", "压测"))
        if hasattr(self, 'sniffer_btn'):
            self.sniffer_btn.setText(tr("btn_sniffer", "嗅探"))
        if hasattr(self, 'global_headers_btn'):
            self.global_headers_btn.setText(tr("btn_global_headers"))
        if hasattr(self, 'gh_tip_label'):
            self.gh_tip_label.setText(tr("gh_tab_tip", "💡 全局请求头在所有请求中均自动生效。若某个请求单独配置了相同名称（大小写不敏感）的请求头，将以该请求中的配置为准。"))
        if hasattr(self, 'gh_clear_btn'):
            self.gh_clear_btn.setText(tr("btn_clear_all", "清空全部"))
        if hasattr(self, 'gh_save_btn'):
            self.gh_save_btn.setText(tr("dialog_save", "保存"))
        if hasattr(self, 'body_type_label'):
            self.body_type_label.setText(tr("label_body_type"))
        if hasattr(self, 'json_format_btn'):
            self.json_format_btn.setText(tr("btn_format_json"))
            self.json_format_btn.adjustSize()
        if hasattr(self, 'binary_select_btn'):
            self.binary_select_btn.setText(tr("btn_select_file"))
        if hasattr(self, 'curl_label'):
            self.curl_label.setText(tr("label_curl_cmd"))
        if hasattr(self, 'curl_copy_btn'):
            self.curl_copy_btn.setText(tr("btn_copy"))
        if hasattr(self, 'url_input'):
            self.url_input.setPlaceholderText(tr("placeholder_url"))
        if hasattr(self, 'cookie_manager'):
            if hasattr(self.cookie_manager, 'add_btn'):
                self.cookie_manager.add_btn.setText(tr("btn_add_cookie"))
            if hasattr(self.cookie_manager, 'global_headers_btn'):
                self.cookie_manager.global_headers_btn.setText(tr("btn_global_headers"))
        if hasattr(self, 'pre_processor_widget') and hasattr(self.pre_processor_widget, 'retranslate_ui'):
            self.pre_processor_widget.retranslate_ui()
        if hasattr(self, 'post_processor_widget') and hasattr(self.post_processor_widget, 'retranslate_ui'):
            self.post_processor_widget.retranslate_ui()
        for ed_name in ('params_editor', 'headers_editor', 'formdata_editor', 'global_headers_editor'):
            ed = getattr(self, ed_name, None)
            if ed and hasattr(ed, 'retranslate_ui'):
                ed.retranslate_ui()
        self._update_tab_badges()

    def _update_tab_badges(self):
        """动态更新子标签页数据条数角标"""
        try:
            from app.config.i18n import tr
            p_data = self.params_editor.get_data()
            p_count = sum(1 for p in p_data if p.get("key", "").strip())
            p_title = tr("tab_params")
            p_idx = self.tabs.indexOf(self.params_editor)
            if p_idx >= 0:
                self.tabs.setTabText(p_idx, f"{p_title} ({p_count})" if p_count > 0 else p_title)

            h_data = self.headers_editor.get_data()
            h_count = sum(1 for h in h_data if h.get("key", "").strip())
            h_title = tr("tab_headers")
            h_idx = self.tabs.indexOf(self.headers_editor)
            if h_idx >= 0:
                self.tabs.setTabText(h_idx, f"{h_title} ({h_count})" if h_count > 0 else h_title)

            c_idx = self.tabs.indexOf(self.cookie_manager)
            if c_idx >= 0:
                self.tabs.setTabText(c_idx, tr("tab_cookies"))

            b_type = self.body_type_combo.currentText()
            b_title = tr("tab_body")
            b_idx = 3
            if b_type and b_type != "none":
                self.tabs.setTabText(b_idx, f"{b_title} ({b_type})")
            else:
                self.tabs.setTabText(b_idx, b_title)

            a_type = self.auth_type_combo.currentText()
            a_title = tr("tab_auth")
            a_idx = 4
            if a_type and a_type != "none":
                self.tabs.setTabText(a_idx, f"{a_title} ({a_type})")
            else:
                self.tabs.setTabText(a_idx, a_title)

            if hasattr(self, 'pre_processor_widget'):
                pre_idx = self.tabs.indexOf(self.pre_processor_widget)
                if pre_idx >= 0:
                    pre_rules = self.pre_processor_widget.get_config().get("rules", [])
                    pre_cnt = len(pre_rules)
                    pre_title = tr("tab_pre_processor", "前置处理")
                    self.tabs.setTabText(pre_idx, f"{pre_title} ({pre_cnt})" if pre_cnt > 0 else pre_title)

            if hasattr(self, 'post_processor_widget'):
                post_idx = self.tabs.indexOf(self.post_processor_widget)
                if post_idx >= 0:
                    post_rules = self.post_processor_widget.get_config().get("rules", [])
                    post_cnt = len(post_rules)
                    post_title = tr("tab_post_processor", "后置处理")
                    self.tabs.setTabText(post_idx, f"{post_title} ({post_cnt})" if post_cnt > 0 else post_title)

            if hasattr(self, 'curl_widget'):
                curl_idx = self.tabs.indexOf(self.curl_widget)
                if curl_idx >= 0:
                    self.tabs.setTabText(curl_idx, tr("tab_curl"))

            if hasattr(self, 'global_headers_widget') and hasattr(self, 'global_headers_editor'):
                gh_idx = self.tabs.indexOf(self.global_headers_widget)
                if gh_idx >= 0:
                    gh_data = self.global_headers_editor.get_data()
                    gh_count = sum(1 for gh in gh_data if gh.get("key", "").strip())
                    gh_title = tr("tab_global_headers", "全局请求头")
                    self.tabs.setTabText(gh_idx, f"{gh_title} ({gh_count})" if gh_count > 0 else gh_title)
        except Exception:
            pass

    def _on_url_changed(self, url: str):
        """当 URL 变化时，自动解析查询参数到 Params Tab（仅当用户手动编辑 URL 时）"""
        from urllib.parse import urlparse, parse_qs
        
        # 防止循环更新
        if hasattr(self, '_updating_from_params') and self._updating_from_params:
            return
        
        # 关键保护：仅当用户主动聚焦在 URL 输入框编辑时，才执行 URL 到 params 的反向同步
        # 切换 tab、加载请求等场景绝不清空用户已录入的参数
        if not self.url_input.hasFocus():
            return
        
        if not url or '?' not in url:
            # URL 中没有参数，清空 params 编辑器（仅在用户手动编辑 URL 时）
            if not hasattr(self, '_skip_params_clear') or not self._skip_params_clear:
                if self.params_editor.table.rowCount() > 0:
                    self.params_editor.table.setRowCount(0)
                    self.params_editor._add_empty_row()
            return
        
        # 解析 URL
        parsed = urlparse(url)
        if not parsed.query:
            return
        
        # 解析查询参数
        params_dict = parse_qs(parsed.query, keep_blank_values=True)
        
        # 始终同步 URL 中的参数到 params 编辑器
        self.params_editor.table.setRowCount(0)
        for key, values in params_dict.items():
            for val in values:
                self.params_editor._add_row(True, key, val)
        # 添加一个空行供用户继续输入
        self.params_editor._add_empty_row()

    def _update_url_from_params(self):
        """从 Params Tab 更新 URL"""
        from urllib.parse import urlencode
        
        # 标记正在从参数更新，防止循环
        self._updating_from_params = True
        
        try:
            # 保存当前光标位置
            cursor_pos = self.url_input.cursorPosition()
            
            # 获取当前 URL（不含查询参数部分）
            url = self.url_input.text().strip()
            if '?' in url:
                url = url.split('?')[0]
            
            # 构建查询参数字符串（只要 key 或 value 任意一个有输入，均予以拼接并保留）
            params_data = self.params_editor.get_data()
            if params_data:
                valid_items = []
                for p in params_data:
                    if p.get('enabled', True):
                        k = p.get('key', '')
                        v = p.get('value', '')
                        if k or v:
                            valid_items.append((k, v))
                if valid_items:
                    query_string = urlencode(valid_items)
                    url += f'?{query_string}'
            
            # 阻止 textChanged 信号触发 params 清空
            self._skip_params_clear = True
            self.url_input.blockSignals(True)
            # 更新 URL 输入框
            self.url_input.setText(url)
            self.url_input.blockSignals(False)
            self._skip_params_clear = False
            
            # 恢复光标位置
            self.url_input.setCursorPosition(cursor_pos)
        finally:
            self._updating_from_params = False

    def _on_body_type_changed(self, body_type: str):
        is_binary = (body_type == "binary")
        is_form = (body_type == "form")
        is_none = (body_type == "none")
        is_text = not (is_binary or is_form)

        self.formdata_editor.setVisible(is_form)
        if hasattr(self, "binary_widget"):
            self.binary_widget.setVisible(is_binary)
        self.body_edit.setVisible(is_text)
        self.body_edit.setEnabled(not is_none)
        self.json_format_btn.setVisible(body_type == "json")

        if is_none:
            self.body_edit.setPlaceholderText("无请求体")
        elif is_form:
            if self.formdata_editor.table.rowCount() == 0:
                self.formdata_editor._add_empty_row()
        elif body_type == "json":
            self.body_edit.setPlaceholderText('{\n  "key": "value"\n}')
        elif body_type == "urlencoded":
            self.body_edit.setPlaceholderText("name=value\nkey2=value2")
        elif is_text:
            self.body_edit.setPlaceholderText("输入原始请求体内容...")
    
    def _format_json(self):
        """格式化 JSON 内容"""
        if hasattr(self.body_edit, 'format_json'):
            # 如果是 JsonTextEdit，使用内置格式化方法
            self.body_edit.format_json()
        else:
            # 否则使用通用方法
            import json
            try:
                raw_text = self.body_edit.toPlainText().strip()
                if not raw_text:
                    return
                    
                # 解析 JSON
                parsed_json = json.loads(raw_text)
                    
                # 格式化 JSON
                formatted_json = json.dumps(parsed_json, indent=2, ensure_ascii=False)
                    
                # 设置回编辑器
                self.body_edit.setPlainText(formatted_json)
            except json.JSONDecodeError as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "JSON 格式错误", f"无效的 JSON 格式:\n{str(e)}")

    def _on_auth_type_changed(self, auth_type: str):
        is_basic = auth_type == "basic"
        is_bearer = auth_type == "bearer"
        is_apikey = auth_type == "apikey"

        self.auth_username.setVisible(is_basic)
        self.auth_password.setVisible(is_basic)
        self.auth_token.setVisible(is_bearer)
        self.auth_apikey_key.setVisible(is_apikey)
        self.auth_apikey_value.setVisible(is_apikey)

        for i in range(self.auth_username.parentWidget().layout().rowCount()):
            label_item = self.auth_username.parentWidget().layout().itemAt(i, QFormLayout.ItemRole.LabelRole)
            if label_item and label_item.widget():
                label = label_item.widget()
                text = label.text()
                if "用户名" in text or "密码" in text:
                    label.setVisible(is_basic)
                elif "Token" in text:
                    label.setVisible(is_bearer)
                elif text in ("Key:", "Value:"):
                    label.setVisible(is_apikey)

    def _ensure_url_protocol(self):
        """用户触发发送前，若 URL 未填写协议头，自动补齐默认的 http:// 并回写输入框"""
        url = self.url_input.text().strip()
        if url and not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', url):
            url = 'http://' + url
            self.url_input.setText(url)

    def _on_send(self):
        if self._sending:
            self.cancel_requested.emit()
        else:
            self._ensure_url_protocol()
            req = self.build_request()
            self.send_requested.emit(req)

    def build_request(self) -> SavedRequest:
        """从 UI 构建 SavedRequest 对象（纯读取 UI 状态，不修改输入框内容）"""
        headers_data = self.headers_editor.get_data()
        params_data = self.params_editor.get_data()

        headers = [HeaderItem(key=h["key"], value=h["value"], enabled=h["enabled"]) for h in headers_data]
        params = [ParamItem(key=p["key"], value=p["value"], enabled=p["enabled"]) for p in params_data]
        
        # 获取 Cookies
        cookies = self.cookie_manager.get_all_cookies()

        auth_type = self.auth_type_combo.currentText()
        auth_config = {}
        if auth_type == "basic":
            auth_config = {
                "username": self.auth_username.text(),
                "password": self.auth_password.text(),
            }
        elif auth_type == "bearer":
            auth_config = {"token": self.auth_token.text()}
        elif auth_type == "apikey":
            auth_config = {
                "key": self.auth_apikey_key.text(),
                "value": self.auth_apikey_value.text(),
                "add_to": "header",
            }

        # Body content - 根据 body_type 决定来源
        body_type = self.body_type_combo.currentText()
        if body_type == "form":
            # Form Data - 从 KeyValueEditor 获取
            formdata_list = self.formdata_editor.get_data()
            body_content = "\n".join([f"{f['key']}={f['value']}" for f in formdata_list])
        elif body_type == "binary":
            # Binary - 文件路径
            body_content = self.binary_file_input.text()
        else:
            # JSON/URLEncoded/Raw - 从 TextEdit 获取
            body_content = self.body_edit.toPlainText()
            # JSON 类型：自动修复字符串值内的裸换行符（粘贴多行文本时常见）
            if body_type == "json" and body_content.strip():
                from app.widgets.json_editor import JsonTextEdit
                body_content = JsonTextEdit.auto_fix_json(body_content)

        url = self.url_input.text().strip()
        pre_script = self.pre_processor_widget.get_config() if hasattr(self, 'pre_processor_widget') else {}
        post_script = self.post_processor_widget.get_config() if hasattr(self, 'post_processor_widget') else {}
        return SavedRequest(
            id=self._current_request_id or "",
            collection_id=self._collection_id or "",
            name=self._request_name or "新建请求",
            method=self.method_combo.currentText(),
            url=url,
            headers=headers,
            params=params,
            body_type=body_type,
            body_content=body_content,
            auth_type=auth_type,
            auth_config=auth_config,
            cookies=cookies,  # 添加 cookies
            pre_script=pre_script,
            post_script=post_script,
            timeout=self._timeout,
            proxy=dict(getattr(self, "proxy_config", {})),
        )

    def load_request(self, request_id: str):
        """从数据库加载请求到编辑器"""
        from app.core.db import Database
        db = Database()
        req = db.get_request(request_id)
        if req:
            self._current_request_id = req.id
            self._request_name = req.name
            self._collection_id = req.collection_id
            self.method_combo.setCurrentText(req.method)
            self.url_input.setText(req.url)
            self.headers_editor.set_data(req.headers)
            self.params_editor.set_data(req.params)
            self.body_type_combo.setCurrentText(req.body_type)
            
            # 根据 body_type 设置内容
            if req.body_type == "form":
                # Form Data - 解析 key=value 格式
                form_items = []
                for line in req.body_content.split('\n'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        form_items.append({"key": key.strip(), "value": value.strip(), "enabled": True})
                self.formdata_editor.table.setRowCount(0)
                for item in form_items:
                    self.formdata_editor._add_row(True, item['key'], item['value'])
                self.formdata_editor._add_empty_row()
            elif req.body_type == "binary":
                # Binary - 文件路径
                self.binary_file_input.setText(req.body_content)
            else:
                # JSON/URLEncoded/Raw - TextEdit
                self.body_edit.setPlainText(req.body_content)
            
            self.auth_type_combo.setCurrentText(req.auth_type)

            if req.auth_type == "basic":
                self.auth_username.setText(req.auth_config.get("username", ""))
                self.auth_password.setText(req.auth_config.get("password", ""))
            elif req.auth_type == "bearer":
                self.auth_token.setText(req.auth_config.get("token", ""))
            elif req.auth_type == "apikey":
                self.auth_apikey_key.setText(req.auth_config.get("key", ""))
                self.auth_apikey_value.setText(req.auth_config.get("value", ""))
            
            # 加载 Cookies
            if hasattr(req, 'cookies') and req.cookies:
                self.cookie_manager.set_cookies(req.cookies)

            # 加载前置与后置处理
            if hasattr(self, 'pre_processor_widget'):
                self.pre_processor_widget.set_config(getattr(req, 'pre_script', {}))
            if hasattr(self, 'post_processor_widget'):
                self.post_processor_widget.set_config(getattr(req, 'post_script', {}))
            
            # 加载超时时间
            self._timeout = req.timeout
            # 加载专属代理配置
            self.proxy_config = dict(getattr(req, "proxy", {})) if getattr(req, "proxy", None) else {}
            self._update_method_style(req.method)
            self._update_tab_badges()

    def clear_editor(self):
        """清空编辑器"""
        self._current_request_id = None
        self._request_name = ""
        self._collection_id = ""
        self._timeout = 0
        self.proxy_config = {}
        self.method_combo.setCurrentText("GET")
        self.url_input.clear()
        self.headers_editor.table.setRowCount(0)
        self.params_editor.table.setRowCount(0)
        # 添加一个空行供用户输入
        self.params_editor._add_empty_row()
        self.body_type_combo.setCurrentText("none")
        self.body_edit.clear()
        self.formdata_editor.table.setRowCount(0)
        self.formdata_editor._add_empty_row()  # 保留一个空行
        self.binary_file_input.clear()
        self.auth_type_combo.setCurrentText("none")
        self.auth_username.clear()
        self.auth_password.clear()
        self.auth_token.clear()
        self.auth_apikey_key.clear()
        self.auth_apikey_value.clear()
        # 清空 Cookies
        self.cookie_manager.cookies = {}
        self.cookie_manager._refresh_tree()
        # 清空前置与后置处理
        if hasattr(self, 'pre_processor_widget'):
            self.pre_processor_widget.set_config({})
        if hasattr(self, 'post_processor_widget'):
            self.post_processor_widget.set_config({})
        self._update_method_style("GET")
        self._update_tab_badges()

    def set_sending_state(self, sending: bool):
        """设置发送中状态：按钮在「发送」与「取消发送」之间切换"""
        self._sending = sending
        if sending:
            self.send_btn.setText("取消发送")
            self.send_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ef4444;
                    color: white;
                    font-weight: bold;
                    font-size: 13px;
                    border: none;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background-color: #dc2626;
                }
                QPushButton:pressed {
                    background-color: #b91c1c;
                }
            """)
        else:
            self.send_btn.setText("发送")
            self.send_btn.setStyleSheet("""
                QPushButton {
                    background-color: #10b981;
                    color: white;
                    font-weight: bold;
                    font-size: 13px;
                    border: none;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background-color: #059669;
                }
                QPushButton:pressed {
                    background-color: #047857;
                }
            """)

    def _on_tab_changed(self, index: int):
        """Tab 切换事件处理：强制提交编辑态数据，切换到 cURL Export Tab 时刷新命令；切换到全局请求头时刷新数据"""
        if getattr(self, '_is_exporting_curl', False):
            return
        # 强制提交所有表格编辑态文本，防止切 Tab 数据丢失
        if hasattr(self, 'params_editor'):
            self.params_editor.get_data()
        if hasattr(self, 'headers_editor'):
            self.headers_editor.get_data()
        if hasattr(self, 'global_headers_editor'):
            self.global_headers_editor.get_data()

        if hasattr(self, 'curl_widget') and self.tabs.widget(index) == self.curl_widget:
            self._on_export_curl()
        elif hasattr(self, 'global_headers_widget') and self.tabs.widget(index) == self.global_headers_widget:
            self._reload_global_headers()

    def _on_export_curl(self):
        """将当前请求转换为 cURL 命令并显示在 Curl Export Tab"""
        if getattr(self, '_is_exporting_curl', False):
            return
        self._is_exporting_curl = True
        try:
            req = self.build_request()
            curl_parts = ["curl"]
            
            # HTTP 方法
            if req.method != "GET":
                curl_parts.append(f"-X {req.method}")
            
            # URL（包含查询参数）
            url = req.url or ""
            # 如果 URL 中未包含 '?'，且 params 中有启用项，则把参数拼接到 URL 中（避免重复拼接）
            if '?' not in url and req.params:
                valid_params = [
                    f"{p.key}={p.value}"
                    for p in req.params
                    if getattr(p, "enabled", True) and getattr(p, "key", "").strip()
                ]
                if valid_params:
                    url += f"?{'&'.join(valid_params)}"
            curl_parts.append(f"'{url}'")
            
            # Headers（合并全局请求头与单请求请求头，单请求配置同名 key 优先覆盖）
            merged_headers = {}
            lower_to_key = {}
            try:
                from app.config.settings import Settings
                for gh in Settings().global_headers:
                    if isinstance(gh, dict) and gh.get("enabled", True) and gh.get("key", "").strip():
                        k = gh["key"].strip()
                        merged_headers[k] = gh.get("value", "")
                        lower_to_key[k.lower()] = k
            except Exception:
                pass

            for h in req.headers:
                if getattr(h, "enabled", True) and getattr(h, "key", "").strip():
                    k = h.key.strip()
                    k_lower = k.lower()
                    if k_lower in lower_to_key and lower_to_key[k_lower] != k:
                        merged_headers.pop(lower_to_key[k_lower], None)
                    merged_headers[k] = getattr(h, "value", "")
                    lower_to_key[k_lower] = k

            for k, val in merged_headers.items():
                val_escaped = str(val).replace("'", "'\\''")
                curl_parts.append(f"-H '{k}: {val_escaped}'")
            
            # Cookies
            if getattr(req, "cookies", None):
                cookie_pairs = [
                    f"{c['name']}={c.get('value', '')}"
                    for c in req.cookies
                    if isinstance(c, dict) and c.get("name")
                ]
                if cookie_pairs:
                    cookie_str = "; ".join(cookie_pairs).replace("'", "'\\''")
                    curl_parts.append(f"--cookie '{cookie_str}'")

            # Body
            if req.body_type == "json" and req.body_content.strip():
                header_keys = [k.lower() for k in merged_headers.keys()]
                if "content-type" not in header_keys:
                    curl_parts.append("-H 'Content-Type: application/json'")
                body_escaped = req.body_content.replace("'", "'\\''")
                curl_parts.append(f"--data-raw '{body_escaped}'")
            elif req.body_type == "urlencoded" and req.body_content.strip():
                header_keys = [k.lower() for k in merged_headers.keys()]
                if "content-type" not in header_keys:
                    curl_parts.append("-H 'Content-Type: application/x-www-form-urlencoded'")
                body_escaped = req.body_content.replace("'", "'\\''")
                curl_parts.append(f"--data-raw '{body_escaped}'")
            elif req.body_type == "form" and req.body_content.strip():
                for line in req.body_content.split('\n'):
                    line = line.strip()
                    if '=' in line:
                        k, v = line.split('=', 1)
                        k = k.strip()
                        v = v.strip()
                        if k:
                            v_escaped = v.replace("'", "'\\''")
                            curl_parts.append(f"-F '{k}={v_escaped}'")
            elif req.body_type == "binary" and req.body_content.strip():
                curl_parts.append(f"--data-binary '@{req.body_content.strip()}'")
            elif req.body_type not in ("none", "form", "binary") and req.body_content.strip():
                body_escaped = req.body_content.replace("'", "'\\''")
                curl_parts.append(f"--data-raw '{body_escaped}'")
            
            # Auth
            if req.auth_type == "basic":
                username = req.auth_config.get("username", "")
                password = req.auth_config.get("password", "")
                curl_parts.append(f"-u '{username}:{password}'")
            elif req.auth_type == "bearer":
                token = req.auth_config.get("token", "")
                if token:
                    curl_parts.append(f"-H 'Authorization: Bearer {token}'")
            elif req.auth_type == "apikey":
                key = req.auth_config.get("key", "").strip()
                value = req.auth_config.get("value", "")
                add_to = req.auth_config.get("add_to", "header")
                if key:
                    if add_to == "header":
                        curl_parts.append(f"-H '{key}: {value}'")
            
            curl_cmd = " \\\n  ".join(curl_parts)
            self._show_curl_export_tab(curl_cmd)
        finally:
            self._is_exporting_curl = False
    
    def _on_toggle_curl_tab(self):
        """切换 cURL Export Tab 的显示/隐藏"""
        curl_tab_index = self.tabs.indexOf(self.curl_widget) if hasattr(self, 'curl_widget') else 5
        if curl_tab_index < 0:
            curl_tab_index = 5
        
        if self.tabs.currentIndex() == curl_tab_index:
            # 如果当前已经在 cURL Tab，点击后切换到 Params Tab
            self.tabs.setCurrentIndex(0)
        else:
            # 否则显示 cURL Tab 并生成导出内容
            self._on_export_curl()
    
    def _show_curl_export_tab(self, curl_cmd: str):
        """显示 cURL Export Tab 并填入命令"""
        self.curl_display.setPlainText(curl_cmd)
        
        # 切换到 cURL Export Tab
        curl_tab_index = self.tabs.indexOf(self.curl_widget) if hasattr(self, 'curl_widget') else 5
        if curl_tab_index < 0:
            curl_tab_index = 5
        if self.tabs.currentIndex() != curl_tab_index:
            self.tabs.setCurrentIndex(curl_tab_index)
    
    def _on_copy_curl(self):
        """复制 cURL 命令到剪贴板"""
        from PyQt6.QtWidgets import QApplication, QMessageBox
        
        curl_cmd = self.curl_display.toPlainText()
        if not curl_cmd:
            return
        
        # 安全复制到剪贴板（处理 Windows 剪贴板锁定）
        import time
        clipboard = QApplication.clipboard()
        for attempt in range(3):
            try:
                clipboard.setText(curl_cmd)
                break
            except Exception:
                if attempt < 2:
                    time.sleep(0.1)
        
        QMessageBox.information(
            self,
            "已复制",
            "cURL 命令已复制到剪贴板！"
        )
    
    def _on_curl_pasted(self):
        """当 cURL 被粘贴时，离焦后触发解析并映射到请求展示中"""
        if getattr(self, '_is_exporting_curl', False):
            return
        # 使用定时器延迟解析，避免在输入过程中频繁触发
        if hasattr(self, '_curl_parse_timer'):
            self._curl_parse_timer.stop()
        else:
            from PyQt6.QtCore import QTimer
            self._curl_parse_timer = QTimer(self)
            self._curl_parse_timer.setSingleShot(True)
            self._curl_parse_timer.timeout.connect(self._parse_and_apply_curl)
        
        self._curl_parse_timer.start(500)  # 500ms 后解析
    
    def _parse_and_apply_curl(self):
        """解析 cURL 命令并应用到请求编辑器"""
        if getattr(self, '_is_exporting_curl', False):
            return
        curl_text = self.curl_display.toPlainText().strip()
        if not curl_text or not (curl_text.lower().startswith("curl ") or curl_text.lower().startswith("curl\t")):
            return
        
        try:
            from app.core.importer import parse_curl
            req = parse_curl(curl_text)
            
            # 设置 HTTP 方法
            self.method_combo.setCurrentText(req.method)
            
            # 设置 URL 与 Params（避免 _on_url_changed 误清空）
            self._skip_params_clear = True
            self.url_input.setText(req.url)
            self._skip_params_clear = False
            self.params_editor.set_data(req.params)
            
            # 设置 Headers
            self.headers_editor.set_data(req.headers)
            
            # 设置 Body
            self.body_type_combo.setCurrentText(req.body_type)
            if req.body_type == "form":
                self.formdata_editor.table.setRowCount(0)
                for line in req.body_content.split('\n'):
                    if '=' in line:
                        k, v = line.split('=', 1)
                        self.formdata_editor._add_row(True, k.strip(), v.strip())
                self.formdata_editor._add_empty_row()
            elif req.body_type == "binary":
                self.binary_file_input.setText(req.body_content)
            else:
                self.body_edit.setPlainText(req.body_content)
            
            # 设置 Auth
            self.auth_type_combo.setCurrentText(req.auth_type)
            if req.auth_type == "basic":
                self.auth_username.setText(req.auth_config.get("username", ""))
                self.auth_password.setText(req.auth_config.get("password", ""))
            elif req.auth_type == "bearer":
                self.auth_token.setText(req.auth_config.get("token", ""))
            elif req.auth_type == "apikey":
                self.auth_apikey_key.setText(req.auth_config.get("key", ""))
                self.auth_apikey_value.setText(req.auth_config.get("value", ""))
        except Exception:
            pass

    def _on_select_binary_file(self):
        """选择二进制文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            "",
            "所有文件 (*)"
        )
        if file_path:
            self.binary_file_input.setText(file_path)
