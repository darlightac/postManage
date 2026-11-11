"""流式响应自动提取与整合对话框 - 支持 SSE / Chunked 响应字段提取与拼接"""

import json
import re
import time
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QSplitter, QComboBox, QMessageBox, QFrame, QApplication,
    QWidget,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from app.config.settings import Settings
from app.config.themes import ThemeManager


def find_key_values(obj, target_key: str):
    """递归查找所有匹配 key 的值"""
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == target_key:
                results.append(v)
            results.extend(find_key_values(v, target_key))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(find_key_values(item, target_key))
    return results


def extract_by_path(obj, path_str: str):
    """根据路径提取值，支持点号与下标，如 choices[0].delta.content 或 choices.0.delta.content"""
    tokens = re.findall(r'[^.\[\]]+|\[\d+\]', path_str)
    curr = obj
    for token in tokens:
        if token.startswith('[') and token.endswith(']'):
            try:
                idx = int(token[1:-1])
                if isinstance(curr, list) and 0 <= idx < len(curr):
                    curr = curr[idx]
                else:
                    return None
            except ValueError:
                return None
        elif token.isdigit() and isinstance(curr, list):
            idx = int(token)
            if 0 <= idx < len(curr):
                curr = curr[idx]
            else:
                return None
        elif isinstance(curr, dict):
            if token in curr:
                curr = curr[token]
            else:
                return None
        else:
            return None
    return curr


class StreamExtractorDialog(QDialog):
    """流式响应内容提取整合对话框"""

    PRESETS = [
        ("快捷模板选择...", "", ""),
        ("OpenAI / 兼容接口 (data: -> choices[0].delta.content)", "data:", "choices[0].delta.content"),
        ("Anthropic Claude (data: -> delta.text)", "data:", "delta.text"),
        ("Ollama / 通用 (data: -> response)", "data:", "response"),
        ("通用单字段 (data: -> content)", "data:", "content"),
        ("无前缀 JSON (-> choices[0].delta.content)", "", "choices[0].delta.content"),
    ]

    def __init__(self, raw_body: str, parent=None):
        super().__init__(parent)
        self.raw_body = raw_body or ""
        self.settings = Settings()
        self.setMinimumSize(820, 560)
        self.resize(960, 620)
        self._init_ui()
        self.load_config()
        self.apply_theme(ThemeManager.current())
        # 初始自动提取一次
        QTimer.singleShot(50, self.do_extract)

    def _init_ui(self):
        self.setWindowTitle("流式响应内容自动提取与整合")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # ─── 顶部信息横幅 ─────────────────────────────────────
        self.header_card = QFrame()
        header_layout = QHBoxLayout(self.header_card)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(10)

        header_icon = QLabel("⚡")
        header_icon.setStyleSheet("font-size: 20px;")
        header_layout.addWidget(header_icon)

        header_text_layout = QVBoxLayout()
        header_text_layout.setSpacing(2)
        title_label = QLabel("流式响应内容自动提取整合")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        desc_label = QLabel("支持从 SSE / 分块传输响应中快速提取指定 JSON 字段并自动连续拼接，方便查看与一键复制。")
        desc_label.setStyleSheet("font-size: 12px; color: #64748b;")
        header_text_layout.addWidget(title_label)
        header_text_layout.addWidget(desc_label)
        header_layout.addLayout(header_text_layout)
        header_layout.addStretch()

        layout.addWidget(self.header_card)

        # ─── 主体分栏 ─────────────────────────────────────────
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self.splitter, 1)

        # 左侧：配置与原始流预览
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(8)

        # 配置卡片
        self.config_card = QFrame()
        cfg_layout = QVBoxLayout(self.config_card)
        cfg_layout.setContentsMargins(10, 10, 10, 10)
        cfg_layout.setSpacing(8)

        # 模板选择
        tpl_layout = QHBoxLayout()
        tpl_layout.setSpacing(8)
        tpl_label = QLabel("常用模板:")
        tpl_label.setFixedWidth(65)
        self.preset_combo = QComboBox()
        for label, _, _ in self.PRESETS:
            self.preset_combo.addItem(label)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        tpl_layout.addWidget(tpl_label)
        tpl_layout.addWidget(self.preset_combo, 1)
        cfg_layout.addLayout(tpl_layout)

        # 截取前缀
        prefix_layout = QHBoxLayout()
        prefix_layout.setSpacing(8)
        prefix_label = QLabel("截取前缀:")
        prefix_label.setFixedWidth(65)
        self.prefix_input = QLineEdit()
        self.prefix_input.setPlaceholderText("例如: data: (留空则解析整行)")
        self.prefix_input.returnPressed.connect(self.do_extract)
        prefix_layout.addWidget(prefix_label)
        prefix_layout.addWidget(self.prefix_input, 1)
        cfg_layout.addLayout(prefix_layout)

        # 提取字段
        field_layout = QHBoxLayout()
        field_layout.setSpacing(8)
        field_label = QLabel("提取字段:")
        field_label.setFixedWidth(65)
        self.field_input = QLineEdit()
        self.field_input.setPlaceholderText("如 choices[0].delta.content 或 content")
        self.field_input.returnPressed.connect(self.do_extract)
        field_layout.addWidget(field_label)
        field_layout.addWidget(self.field_input, 1)
        cfg_layout.addLayout(field_layout)

        # 按钮栏
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(8)

        self.extract_btn = QPushButton("开始提取")
        self.extract_btn.setFixedHeight(30)
        self.extract_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.extract_btn.clicked.connect(self.do_extract)
        btn_bar.addWidget(self.extract_btn, 1)

        self.reset_btn = QPushButton("重置")
        self.reset_btn.setFixedHeight(30)
        self.reset_btn.setFixedWidth(60)
        self.reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_btn.clicked.connect(self._on_reset)
        btn_bar.addWidget(self.reset_btn)

        cfg_layout.addLayout(btn_bar)
        left_layout.addWidget(self.config_card)

        # 原始数据预览
        raw_header = QLabel("原始流式响应数据:")
        raw_header.setStyleSheet("font-weight: 500; font-size: 12px;")
        left_layout.addWidget(raw_header)

        self.raw_view = QTextEdit()
        self.raw_view.setReadOnly(True)
        self.raw_view.setFont(QFont("Consolas", 10))
        self.raw_view.setPlainText(self.raw_body)
        left_layout.addWidget(self.raw_view, 1)

        self.splitter.addWidget(left_widget)

        # 右侧：整合提取结果与一键复制
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(8)

        right_top = QHBoxLayout()
        right_top.setSpacing(10)

        right_title = QLabel("整合提取内容:")
        right_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        right_top.addWidget(right_title)

        self.count_badge = QLabel("0 字符")
        self.count_badge.setStyleSheet(
            "font-size: 11px; padding: 2px 8px; border-radius: 10px; background: #e2e8f0; color: #475569;"
        )
        right_top.addWidget(self.count_badge)

        right_top.addStretch()

        self.copy_btn = QPushButton("一键复制")
        self.copy_btn.setFixedHeight(28)
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.clicked.connect(self._on_copy_result)
        right_top.addWidget(self.copy_btn)

        right_layout.addLayout(right_top)

        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setFont(QFont("Consolas", 11))
        self.result_view.setPlaceholderText("提取的内容将在此处整合拼接展示...")
        right_layout.addWidget(self.result_view, 1)

        self.splitter.addWidget(right_widget)
        self.splitter.setSizes([420, 540])

        # ─── 底部状态栏 ───────────────────────────────────────
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("font-size: 12px; color: #64748b;")
        bottom_layout.addWidget(self.status_label)

        bottom_layout.addStretch()

        self.close_btn = QPushButton("关闭")
        self.close_btn.setFixedHeight(30)
        self.close_btn.setFixedWidth(80)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(self.close_btn)

        layout.addLayout(bottom_layout)

    def load_config(self):
        """加载已保存的前缀与字段配置"""
        prefix = self.settings.get("stream_extractor_prefix", "data:")
        field = self.settings.get("stream_extractor_field", "choices[0].delta.content")
        self.prefix_input.setText(prefix)
        self.field_input.setText(field)

    def save_config(self):
        """持久化配置"""
        self.settings.set("stream_extractor_prefix", self.prefix_input.text().strip())
        self.settings.set("stream_extractor_field", self.field_input.text().strip())

    def _on_preset_changed(self, index: int):
        if index <= 0 or index >= len(self.PRESETS):
            return
        _, prefix, field = self.PRESETS[index]
        self.prefix_input.setText(prefix)
        self.field_input.setText(field)
        self.do_extract()

    def _on_reset(self):
        self.prefix_input.setText("data:")
        self.field_input.setText("choices[0].delta.content")
        self.preset_combo.setCurrentIndex(0)
        self.do_extract()

    def do_extract(self):
        """执行流式响应字段提取与整合"""
        raw_text = self.raw_body.strip()
        if not raw_text:
            self.status_label.setText("当前响应体为空")
            self.result_view.clear()
            self.count_badge.setText("0 字符")
            return

        prefix = self.prefix_input.text().strip()
        field_path = self.field_input.text().strip()

        if not field_path:
            QMessageBox.warning(self, "提示", "请输入需要提取的字段名称或路径！")
            return

        is_simple_field = not ("." in field_path or "[" in field_path)

        # 解析数据块
        chunks = []
        if prefix:
            current_chunk = []
            for line in self.raw_body.splitlines():
                stripped = line.strip()
                if stripped.startswith(prefix):
                    if current_chunk:
                        chunks.append("\n".join(current_chunk))
                        current_chunk = []
                    payload = stripped[len(prefix):].strip()
                    current_chunk.append(payload)
                elif current_chunk:
                    if not stripped:
                        chunks.append("\n".join(current_chunk))
                        current_chunk = []
                    else:
                        current_chunk.append(stripped)
            if current_chunk:
                chunks.append("\n".join(current_chunk))
        else:
            for line in self.raw_body.splitlines():
                stripped = line.strip()
                if stripped:
                    chunks.append(stripped)

        extracted_pieces = []
        total_chunks = len(chunks)
        success_chunks = 0

        for chunk_str in chunks:
            chunk_clean = chunk_str.strip()
            if not chunk_clean or chunk_clean in ("[DONE]", "DONE"):
                continue

            try:
                parsed = json.loads(chunk_clean)
            except Exception:
                continue

            if is_simple_field:
                # 简单单字段：检查是否存在多个同名字段
                found_values = find_key_values(parsed, field_path)
                if len(found_values) > 1:
                    QMessageBox.warning(
                        self,
                        "提取失败",
                        f"检测到流式数据块中存在多个同名字段 '{field_path}'（数量: {len(found_values)}），无法精确定位。\n\n"
                        f"请在提取字段中配置完整的提取路径（例如: choices[0].delta.{field_path}）。"
                    )
                    return
                elif len(found_values) == 1:
                    val = found_values[0]
                    if val is not None:
                        if isinstance(val, str):
                            extracted_pieces.append(val)
                        elif isinstance(val, (int, float, bool)):
                            extracted_pieces.append(str(val))
                        else:
                            extracted_pieces.append(json.dumps(val, ensure_ascii=False))
                        success_chunks += 1
            else:
                # 完整路径提取
                val = extract_by_path(parsed, field_path)
                if val is not None:
                    if isinstance(val, str):
                        extracted_pieces.append(val)
                    elif isinstance(val, (int, float, bool)):
                        extracted_pieces.append(str(val))
                    else:
                        extracted_pieces.append(json.dumps(val, ensure_ascii=False))
                    success_chunks += 1

        consolidated_text = "".join(extracted_pieces)
        self.result_view.setPlainText(consolidated_text)
        self.count_badge.setText(f"{len(consolidated_text)} 字符")
        self.status_label.setText(
            f"提取完成：扫描 {total_chunks} 个数据块，成功提取 {success_chunks} 条数据，整合文本共 {len(consolidated_text)} 字符"
        )
        self.save_config()

    def _on_copy_result(self):
        """一键复制整合提取后的文本"""
        text = self.result_view.toPlainText()
        if not text:
            QMessageBox.information(self, "提示", "暂无提取结果可复制。")
            return

        clipboard = QApplication.clipboard()
        for attempt in range(3):
            try:
                clipboard.setText(text)
                break
            except Exception:
                if attempt < 2:
                    time.sleep(0.1)

        # 按钮文字短暂变为已复制反馈
        self.copy_btn.setText("已复制 ✓")
        self.copy_btn.setStyleSheet("color: #10b981; font-weight: bold;")
        QTimer.singleShot(1500, self._restore_copy_btn)

    def _restore_copy_btn(self):
        self.copy_btn.setText("一键复制")
        t = ThemeManager.current()
        self.apply_theme(t)

    def apply_theme(self, t):
        """应用主题样式"""
        is_dark = t.name == "dark"
        card_bg = t.bg_secondary if is_dark else "#f8fafc"
        badge_bg = t.bg_hover if is_dark else "#e2e8f0"
        border_color = t.border_light

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.bg_primary};
                color: {t.text_primary};
            }}
            QLabel {{
                color: {t.text_primary};
            }}
            QLineEdit, QComboBox {{
                background-color: {t.bg_secondary};
                color: {t.text_primary};
                border: 1px solid {border_color};
                border-radius: 5px;
                padding: 4px 8px;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border-color: {t.primary_color};
            }}
            QTextEdit {{
                background-color: {t.code_bg};
                color: {t.code_text};
                border: 1px solid {border_color};
                border-radius: 6px;
                padding: 6px;
            }}
            QSplitter::handle {{
                background-color: {border_color};
                width: 2px;
            }}
        """)

        self.header_card.setStyleSheet(f"""
            QFrame {{
                background-color: {card_bg};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)

        self.config_card.setStyleSheet(f"""
            QFrame {{
                background-color: {card_bg};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)

        self.extract_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t.primary_color};
                color: #ffffff;
                border: none;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {t.primary_hover};
            }}
        """)

        self.copy_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #10b981;
                color: #ffffff;
                border: none;
                border-radius: 5px;
                font-weight: bold;
                padding: 2px 14px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #059669;
            }}
        """)

        self.reset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t.bg_secondary};
                color: {t.text_primary};
                border: 1px solid {border_color};
                border-radius: 5px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {t.bg_hover};
            }}
        """)

        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t.bg_secondary};
                color: {t.text_primary};
                border: 1px solid {border_color};
                border-radius: 5px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {t.bg_hover};
            }}
        """)

        self.count_badge.setStyleSheet(f"""
            QLabel {{
                font-size: 11px;
                padding: 2px 8px;
                border-radius: 10px;
                background-color: {badge_bg};
                color: {t.text_secondary};
            }}
        """)
