"""cURL 语法高亮编辑器"""

import re
from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import (
    QColor, QFont, QTextCharFormat, 
    QSyntaxHighlighter, QTextCursor, QTextOption,
)


class CurlHighlighter(QSyntaxHighlighter):
    """cURL 语法高亮器"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlight_rules = []

        # cURL 选项格式 (-X, -H, -u 等)
        option_format = QTextCharFormat()
        option_format.setForeground(QColor("#FF6B6B"))  # 红色
        option_format.setFontWeight(QFont.Weight.Bold)
        self.highlight_rules.append((r'-[A-Za-z][A-Za-z0-9]*', option_format))

        # URL 格式
        url_format = QTextCharFormat()
        url_format.setForeground(QColor("#4EC9B0"))  # 青色
        self.highlight_rules.append((r'https?://[^\s\'\"\n]+', url_format))

        # 引号内的内容格式
        quoted_format = QTextCharFormat()
        quoted_format.setForeground(QColor("#CE9178"))  # 橙色
        self.highlight_rules.append((r'\'[^\']*\'', quoted_format))
        self.highlight_rules.append((r'\"[^\"]*\"', quoted_format))

        # HTTP 方法格式
        method_format = QTextCharFormat()
        method_format.setForeground(QColor("#DCDCAA"))  # 黄色
        method_format.setFontWeight(QFont.Weight.Bold)
        self.highlight_rules.append((r'\b(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b', method_format))

    def highlightBlock(self, text):
        """高亮单行文本"""
        for pattern, fmt in self.highlight_rules:
            for match in re.finditer(pattern, text):
                start, end = match.span()
                self.setFormat(start, end - start, fmt)


class CurlTextEdit(QTextEdit):
    """支持语法高亮的 cURL 编辑器"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighter = CurlHighlighter(self.document())
        
        # 设置等宽字体
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        
        # 启用自动换行
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WordWrap)

    def insertFromMimeData(self, source: QMimeData):
        """强制以纯文本粘贴，避免带入源格式"""
        if source.hasText():
            self.textCursor().insertText(source.text())
        else:
            super().insertFromMimeData(source)