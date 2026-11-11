"""JSON 语法高亮编辑器 - 支持语法高亮和 {} 内容折叠"""

import json
import re

from PyQt6.QtCore import Qt, QRect, QMimeData
from PyQt6.QtGui import (
    QColor, QFont, QBrush, QTextCharFormat,
    QSyntaxHighlighter, QTextCursor, QPainter, QTextOption,
)
from PyQt6.QtWidgets import QTextEdit, QMessageBox, QWidget

from app.config.themes import ThemeManager


class JsonHighlighter(QSyntaxHighlighter):
    """JSON 语法高亮器（区分 key / value / 数字 / 布尔）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlight_rules = []

        # JSON 字符串（值）- 绿色
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#6A8759"))
        self.highlight_rules.append((re.compile(r'"(?:[^"\\]|\\.)*"'), string_format))

        # 数字 - 蓝色
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#6897BB"))
        self.highlight_rules.append(
            (re.compile(r'\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b'), number_format)
        )

        # 布尔值 / null - 橙色加粗
        boolean_format = QTextCharFormat()
        boolean_format.setForeground(QColor("#CC7832"))
        boolean_format.setFontWeight(QFont.Weight.Bold)
        self.highlight_rules.append((re.compile(r'\b(true|false|null)\b'), boolean_format))

        # 键名（冒号前的字符串）- 紫色加粗（规则在最后，覆盖绿色字符串）
        key_format = QTextCharFormat()
        key_format.setForeground(QColor("#9876AA"))
        key_format.setFontWeight(QFont.Weight.Bold)
        self.highlight_rules.append((re.compile(r'"(?:[^"\\]|\\.)*"(?=\s*:)'), key_format))

    def highlightBlock(self, text):
        for pattern, fmt in self.highlight_rules:
            for match in pattern.finditer(text):
                start, end = match.span()
                self.setFormat(start, end - start, fmt)


# 折叠栏宽度（像素）
FOLD_MARGIN = 20
# 行号栏宽度（像素）
LINE_NUMBER_MARGIN = 36
# 左侧边距总宽度（折叠栏 + 行号栏）
GUTTER_WIDTH = FOLD_MARGIN + LINE_NUMBER_MARGIN


class JsonGutter(QWidget):
    """编辑器左侧边栏控件：折叠栏 + 行号栏（位于文本区之外的独立区域）"""

    def __init__(self, editor: "JsonTextEdit"):
        super().__init__(editor)
        self.editor = editor

    def paintEvent(self, event):
        self.editor._gutter_paint(event)

    def mousePressEvent(self, event):
        self.editor._gutter_mouse_press(event)


class JsonTextEdit(QTextEdit):
    """支持语法高亮和折叠功能的 JSON 编辑器（左侧独立 gutter 方案）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighter = JsonHighlighter(self.document())

        self._fold_lines = None          # 格式化后的原始行列表（折叠状态的基准）
        self._cached_foldable_starts = set()  # 缓存的可折叠行集合（避免 paint 时频繁重算）
        self._folded_starts = set()      # 处于折叠状态的原始行号集合
        self._fold_marks = []            # [(QRect, 原始行号)] 折叠标记位置缓存（paint 时更新）
        self._display_mapping = []       # 显示行 -> 原始行号映射
        self._last_display_text = ""     # 最近一次重建的显示文本（用于检测用户手动编辑）
        self._rebuilding = False

        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        # 左侧预留折叠栏 + 行号栏空间，由独立的 gutter 控件占据（不覆盖文本区）
        self._gutter = JsonGutter(self)
        self.setViewportMargins(GUTTER_WIDTH, 0, 0, 0)

        self.textChanged.connect(self._on_text_changed)

    # ------------------------------------------------------------------
    # 文本设置 / 读取（对折叠状态透明）
    # ------------------------------------------------------------------
    def insertFromMimeData(self, source: QMimeData):
        """强制以纯文本粘贴，避免带入源格式（背景色等）"""
        if source.hasText():
            self.textCursor().insertText(source.text())
        else:
            super().insertFromMimeData(source)

    def setPlainText(self, text: str):
        self._invalidate_folds()
        super().setPlainText(text)

    def clear(self):
        self._invalidate_folds()
        super().clear()

    def toPlainText(self) -> str:
        """折叠状态下返回完整的原始 JSON（避免发送请求时携带占位符）"""
        if self._fold_lines is not None:
            return '\n'.join(self._fold_lines)
        return super().toPlainText()

    def _invalidate_folds(self):
        self._fold_lines = None
        self._cached_foldable_starts = set()
        self._folded_starts.clear()
        self._fold_marks.clear()
        self._display_mapping = []
        self._gutter.update()

    def _on_text_changed(self):
        """用户手动编辑文本时，废弃折叠状态并刷新一侧行号栏"""
        self._gutter.update()
        if self._rebuilding or self._fold_lines is None:
            return
        current = super().toPlainText().replace('\uFFFC', '')
        if current != self._last_display_text:
            self._invalidate_folds()

    # ------------------------------------------------------------------
    # JSON 自动修复：将字符串值内的裸换行/制表符转义
    # ------------------------------------------------------------------
    @staticmethod
    def auto_fix_json(text: str) -> str:
        """修复 JSON 字符串值中的裸换行符和制表符。

        用户在 JSON 字符串值内粘贴多行文本时，换行符是字面量 \n 而非
        转义序列 \\n，导致 json.loads 报错。此方法逐字符扫描，仅在
        字符串内部将裸控制字符替换为合法的 JSON 转义序列，不改变
        已经正确转义的内容。
        """
        result = []
        in_string = False
        escape_next = False

        for ch in text:
            if escape_next:
                result.append(ch)
                escape_next = False
                continue

            if in_string:
                if ch == '\\':
                    result.append(ch)
                    escape_next = True
                elif ch == '"':
                    result.append(ch)
                    in_string = False
                elif ch == '\n':
                    result.append('\\n')
                elif ch == '\r':
                    result.append('\\r')
                elif ch == '\t':
                    result.append('\\t')
                elif ord(ch) < 0x20:
                    # 其他 JSON 不允许的控制字符，用 \\u00XX 转义
                    result.append(f'\\u{ord(ch):04x}')
                else:
                    result.append(ch)
            else:
                result.append(ch)
                if ch == '"':
                    in_string = True

        return ''.join(result)

    # ------------------------------------------------------------------
    # 格式化 + 折叠状态管理
    # ------------------------------------------------------------------
    def format_json(self):
        """格式化 JSON 内容，并为每个 {} / [] 块在左侧折叠栏显示折叠按钮"""
        raw_text = self.toPlainText().strip()
        if not raw_text:
            return
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            # 尝试自动修复（处理字符串值内的裸换行符等常见问题）
            fixed = self.auto_fix_json(raw_text)
            try:
                parsed = json.loads(fixed)
            except json.JSONDecodeError as e:
                QMessageBox.warning(self, "JSON 格式错误", f"无效的 JSON 格式:\n{str(e)}")
                return

        formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
        self._fold_lines = formatted.split('\n')
        self._cached_foldable_starts = set(self._foldable_starts(self._fold_lines))
        self._folded_starts.clear()
        self._rebuild()

    def _foldable_starts(self, lines):
        """返回所有可折叠的起始行号（以 { 或 [ 开头且在后续行闭合）"""
        starts = []
        for i, line in enumerate(lines):
            stripped = line.rstrip()
            if stripped.endswith('{') or stripped.endswith('['):
                end_line = self._find_matching_close(lines, i)
                if end_line is not None and end_line > i:
                    starts.append(i)
        return starts

    def _rebuild(self):
        """根据折叠状态重建文档内容"""
        lines = self._fold_lines
        if lines is None:
            return

        # 1. 计算显示行（折叠块替换为占位符）及每行对应的原始行号
        display = []
        mapping = []  # 显示行 -> 原始行号（跳过的行不进入）
        i = 0
        while i < len(lines):
            if i in self._folded_starts:
                end = self._find_matching_close(lines, i)
                if end is not None and end > i:
                    # 折叠：整个块（含闭合括号行）收缩成一行，如 "key": { … },
                    closing = lines[end].strip()
                    display.append(lines[i] + ' … ' + closing)
                    mapping.append(i)
                    i = end + 1
                    continue
            display.append(lines[i])
            mapping.append(i)
            i += 1

        # 2. 重建文本并记录显示行 -> 原始行的映射（供绘制折叠标记）
        self._rebuilding = True
        super().setPlainText('\n'.join(display))
        self._rebuilding = False
        self._last_display_text = '\n'.join(display)
        self._display_mapping = mapping
        self._fold_marks = []  # paint 时重新计算并缓存
        self._gutter.update()

    def _toggle_fold(self, orig_line: int):
        """折叠/展开指定原始行开始的代码块"""
        if orig_line in self._folded_starts:
            self._folded_starts.discard(orig_line)
        else:
            self._folded_starts.add(orig_line)
        self._rebuild()

    # ------------------------------------------------------------------
    # 左侧 gutter：布局、绘制与鼠标交互（独立控件，不覆盖文本区）
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), GUTTER_WIDTH, cr.height()))

    def scrollContentsBy(self, dx: int, dy: int):
        super().scrollContentsBy(dx, dy)
        self._gutter.update()

    def _gutter_paint(self, event):
        """在 gutter 控件上绘制行号与折叠标记"""
        t = ThemeManager.current()
        painter = QPainter(self._gutter)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        gutter_h = self._gutter.height()
        # 整条边栏背景（与编辑区背景区分，形成独立的行号/折叠区域）
        painter.fillRect(QRect(0, 0, GUTTER_WIDTH, gutter_h), QColor(t.bg_secondary))

        doc_layout = self.document().documentLayout()
        v_offset = self.verticalScrollBar().value()

        # 1. 行号（视口可见性优化裁剪）
        painter.setPen(QColor(t.text_disabled))
        block = self.document().begin()
        line_no = 1
        while block.isValid():
            rect = doc_layout.blockBoundingRect(block)
            y = int(rect.top() - v_offset)
            if y > gutter_h:
                break  # 超出可视区域下方直接中断
            if y + int(rect.height()) > 0:
                painter.drawText(
                    FOLD_MARGIN, y, LINE_NUMBER_MARGIN - 6, int(rect.height()),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(line_no),
                )
            block = block.next()
            line_no += 1

        # 2. 折叠标记（仅格式化后的 JSON 显示）
        if self._fold_lines is None:
            painter.end()
            return

        foldable = self._cached_foldable_starts
        if not foldable and self._fold_lines:
            self._cached_foldable_starts = set(self._foldable_starts(self._fold_lines))
            foldable = self._cached_foldable_starts
        self._fold_marks = []
        for disp_idx, orig_idx in enumerate(self._display_mapping):
            if orig_idx not in foldable:
                continue
            block = self.document().findBlockByLineNumber(disp_idx)
            rect = doc_layout.blockBoundingRect(block)
            y = int(rect.top() - v_offset)
            if y > gutter_h:
                break
            h = int(rect.height())
            mark_rect = QRect(3, y + max(0, (h - 12) // 2), 12, 12)

            # 绘制折叠标记（小方块 +/-）
            folded = orig_idx in self._folded_starts
            painter.setPen(QColor("#8a97a8"))
            painter.setBrush(QBrush(QColor("#d7dee8")))
            painter.drawRoundedRect(mark_rect, 3, 3)
            painter.setPen(QColor("#333333"))
            painter.drawText(mark_rect, Qt.AlignmentFlag.AlignCenter, "+" if folded else "-")

            self._fold_marks.append((mark_rect, orig_idx))
        painter.end()

    def _gutter_mouse_press(self, event):
        """点击折叠栏标记时切换折叠状态"""
        if event.button() == Qt.MouseButton.LeftButton and self._fold_lines is not None:
            pos = event.position().toPoint()
            if pos.x() <= FOLD_MARGIN:
                for mark_rect, orig_idx in self._fold_marks:
                    if mark_rect.contains(pos):
                        self._toggle_fold(orig_idx)
                        return

    @staticmethod
    def _find_matching_close(lines, start: int):
        """从 start 行开始，找到 { / [ 匹配的闭合行号（忽略字符串内的括号）"""
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(lines)):
            for ch in lines[i]:
                if in_str:
                    if esc:
                        esc = False
                    elif ch == '\\':
                        esc = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch in '{[':
                        depth += 1
                    elif ch in '}]':
                        depth -= 1
                        if depth == 0:
                            return i
        return None
