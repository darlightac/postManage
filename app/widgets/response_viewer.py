"""响应查看器组件 - 展示 HTTP 响应结果"""

import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QApplication, QStackedWidget, QFrame,
)
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QClipboard, QTextOption, QPainter, QPainterPath, QPixmap

from app.core.models import HTTPResponse
from app.config.themes import ThemeManager
from app.widgets.json_editor import JsonTextEdit


class WaterfallBarWidget(QWidget):
    """水平堆叠分段耗时比例条"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.segments = []  # [(color_hex, ratio, name)]

    def set_segments(self, segments):
        self.segments = segments
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = float(self.width())
        h = float(self.height())
        r = 6.0

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e2e8f0"))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        if not self.segments:
            p.end()
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), r, r)
        p.setClipPath(path)

        cur_x = 0.0
        for color_hex, ratio, _name in self.segments:
            seg_w = w * ratio
            if seg_w > 0:
                p.setBrush(QColor(color_hex))
                p.drawRect(QRectF(cur_x, 0, seg_w, h))
                cur_x += seg_w
        p.end()


class TimingWaterfallWidget(QWidget):
    """全链路网络生命周期耗时拆解与瓶颈诊断面板"""

    STAGES_DEF = [
        ("dns_lookup_ms", "🌐 DNS 解析 (DNS Lookup)", "#3b82f6", "域名解析获取目标主机 IP 地址耗时"),
        ("tcp_connect_ms", "🔌 TCP 建连 (TCP Connect)", "#10b981", "与远程主机建立 TCP 三次握手耗时"),
        ("tls_handshake_ms", "🔒 TLS 握手 (TLS Handshake)", "#8b5cf6", "SSL/TLS 安全协议加密协商及证书验证耗时"),
        ("request_send_ms", "📤 发送请求 (Request Send)", "#f59e0b", "向网络套接字写入请求报文及 Body 耗时"),
        ("ttfb_ms", "⏳ 等待首包 (TTFB)", "#ec4899", "发送完成到接收服务端首个字节耗时 (反映后端业务及数据库延迟)"),
        ("download_ms", "📥 内容下载 (Content Download)", "#06b6d4", "从首字节到完整下载全部响应体报文耗时 (反映传输带宽)"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # 顶部总览卡片
        top_card = QFrame()
        top_card.setObjectName("timingTopCard")
        top_card_layout = QHBoxLayout(top_card)
        top_card_layout.setContentsMargins(10, 8, 10, 8)
        top_card_layout.setSpacing(12)

        self.total_label = QLabel("⏱ 总耗时: --")
        self.total_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        top_card_layout.addWidget(self.total_label)

        self.insight_badge = QLabel("准备就绪")
        self.insight_badge.setStyleSheet(
            "font-size: 12px; font-weight: 500; color: #475569; background: #e2e8f0; padding: 3px 10px; border-radius: 10px;"
        )
        top_card_layout.addWidget(self.insight_badge)
        top_card_layout.addStretch()

        layout.addWidget(top_card)

        # 耗时比例条
        self.bar_widget = WaterfallBarWidget()
        layout.addWidget(self.bar_widget)

        # 阶段表格
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["网络阶段", "耗时 (ms)", "耗时占比", "阶段说明"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        # 诊断建议条
        self.advice_box = QLabel("💡 提示：点击发送请求后，系统将自动利用 Go 高性能网络引擎捕获全链路 DNS、TCP、TLS、首包 (TTFB) 的微秒级耗时指标。")
        self.advice_box.setWordWrap(True)
        self.advice_box.setStyleSheet(
            "background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px 14px; font-size: 12px; color: #475569;"
        )
        layout.addWidget(self.advice_box)

    def set_timing(self, timing: dict | None, elapsed_ms: float = 0.0):
        if not timing:
            self.total_label.setText(f"⏱ 总耗时: {elapsed_ms:.1f} ms" if elapsed_ms > 0 else "⏱ 总耗时: --")
            self.insight_badge.setText("基础计时模式")
            self.bar_widget.set_segments([])
            self.table.setRowCount(0)
            return

        total_ms = timing.get("total_ms", 0.0) or elapsed_ms or 0.0
        self.total_label.setText(f"⏱ 总耗时: {total_ms:.2f} ms")

        # 收集各阶段数据
        segments = []
        rows_data = []
        max_stage_name = ""
        max_stage_val = -1.0
        max_stage_pct = 0.0

        for key, name, color, desc in self.STAGES_DEF:
            val = float(timing.get(key, 0.0))
            pct = (val / total_ms * 100.0) if total_ms > 0 else 0.0
            if val > 0 and total_ms > 0:
                segments.append((color, val / total_ms, name))
            rows_data.append((name, f"{val:.2f} ms", f"{pct:.1f}%", desc, color))
            if val > max_stage_val:
                max_stage_val = val
                max_stage_name = name
                max_stage_pct = pct

        self.bar_widget.set_segments(segments)

        if max_stage_pct > 0:
            short_name = max_stage_name.split("(")[0].strip()
            self.insight_badge.setText(f"主要耗时: {short_name} ({max_stage_pct:.1f}%)")

        self.table.setRowCount(len(rows_data))
        for row_idx, (name, dur_str, pct_str, desc, color) in enumerate(rows_data):
            item_name = QTableWidgetItem(name)
            item_name.setForeground(QColor(color))
            font = item_name.font()
            font.setBold(True)
            item_name.setFont(font)
            self.table.setItem(row_idx, 0, item_name)

            item_dur = QTableWidgetItem(dur_str)
            item_dur.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row_idx, 1, item_dur)

            item_pct = QTableWidgetItem(pct_str)
            item_pct.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row_idx, 2, item_pct)

            item_desc = QTableWidgetItem(desc)
            self.table.setItem(row_idx, 3, item_desc)

        # 智能瓶颈诊断
        ttfb = float(timing.get("ttfb_ms", 0.0))
        dns = float(timing.get("dns_lookup_ms", 0.0))
        tcp = float(timing.get("tcp_connect_ms", 0.0))
        tls = float(timing.get("tls_handshake_ms", 0.0))
        download = float(timing.get("download_ms", 0.0))

        if total_ms > 0:
            if (ttfb / total_ms) >= 0.55 and ttfb > 100:
                self.advice_box.setText(
                    f"💡 链路性能诊断：耗时主要消耗在 等待首包 (TTFB, {ttfb/total_ms*100:.1f}%)。"
                    "表明底层网络连接通畅，延迟主要产生在远程服务器端的内部业务逻辑、微服务调用或数据库慢查询，建议重点优化后端接口实现与加装缓存。"
                )
            elif (dns / total_ms) >= 0.35 and dns > 50:
                self.advice_box.setText(
                    f"💡 链路性能诊断：DNS 解析耗时过高 ({dns/total_ms*100:.1f}%)。"
                    "建议排查本地网络 DNS 服务器配置（推荐使用 114.114.114.114 或 223.5.5.5）或在系统 hosts 中做静态映射加速。"
                )
            elif ((tcp + tls) / total_ms) >= 0.45 and (tcp + tls) > 80:
                self.advice_box.setText(
                    f"💡 链路性能诊断：TCP 建连与 TLS 握手耗时占比高 ({(tcp+tls)/total_ms*100:.1f}%)。"
                    "建议服务端与客户端开启 HTTP Keep-Alive 长连接复用，避免每次请求重复进行三步握手与证书协商开销。"
                )
            elif (download / total_ms) >= 0.4 and download > 100:
                self.advice_box.setText(
                    f"💡 链路性能诊断：内容传输耗时占比显著 ({download/total_ms*100:.1f}%)。"
                    "响应体数据体积较大，建议服务端开启 Gzip/Brotli 传输压缩或针对大数据量列表接口增加分页限制。"
                )
            else:
                self.advice_box.setText("💡 链路性能诊断：全链路各阶段耗时分布均衡，网络连接与服务端响应效率良好。")

    def clear(self):
        self.total_label.setText("⏱ 总耗时: --")
        self.insight_badge.setText("准备就绪")
        self.bar_widget.set_segments([])
        self.table.setRowCount(0)
        self.advice_box.setText("💡 提示：点击发送请求后，系统将自动利用 Go 高性能网络引擎捕获全链路 DNS、TCP、TLS、首包 (TTFB) 的微秒级耗时指标。")

    def apply_theme(self, t):
        is_dark = t.name == "dark"
        card_bg = t.bg_secondary if is_dark else "#f8fafc"
        badge_bg = t.bg_hover if is_dark else "#e2e8f0"
        text_color = t.text_primary
        self.total_label.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {text_color};")
        self.insight_badge.setStyleSheet(
            f"font-size: 12px; font-weight: 500; color: {t.text_secondary}; background: {badge_bg}; padding: 3px 10px; border-radius: 10px;"
        )
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {t.bg_primary};
                color: {t.text_primary};
                border: 1px solid {t.border_light};
                border-radius: 6px;
            }}
            QHeaderView::section {{
                background-color: {t.header_bg};
                color: {t.header_text};
                padding: 6px;
                border: none;
                border-bottom: 1px solid {t.border_light};
                font-weight: bold;
            }}
        """)
        self.advice_box.setStyleSheet(
            f"background: {card_bg}; border: 1px solid {t.border_light}; border-radius: 6px; padding: 10px 14px; font-size: 12px; color: {t.text_secondary};"
        )


def make_status_dot_pixmap(color_hex: str, size: int = 8) -> QPixmap:
    """绘制高保真抗锯齿实心圆点图标，支持 High-DPI 屏幕缩放"""
    scale = 2
    pix = QPixmap(size * scale, size * scale)
    pix.fill(Qt.GlobalColor.transparent)
    pix.setDevicePixelRatio(scale)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color_hex))
    p.drawEllipse(0, 0, size, size)
    p.end()
    return pix


class StatusBadge(QFrame):
    """状态码胶囊指示徽章 - 包含抗锯齿圆形状态指示图标与清晰状态码文本"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self.setObjectName("statusBadge")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 10, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.dot_label = QLabel()
        self.dot_label.setFixedSize(10, 10)
        self.dot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dot_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.dot_label)

        self.text_label = QLabel("未请求")
        self.text_label.setStyleSheet("font-size: 12px; font-weight: bold; background: transparent; border: none;")
        layout.addWidget(self.text_label)

    def text(self) -> str:
        return self.text_label.text()

    def setText(self, text: str):
        self.text_label.setText(text)

    def set_badge(self, text: str, dot_color: str, text_color: str, bg_color: str, border_color: str):
        self.text_label.setText(text)
        self.text_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {text_color}; background: transparent; border: none;"
        )
        self.dot_label.setPixmap(make_status_dot_pixmap(dot_color, 8))
        self.setStyleSheet(
            f"QFrame#statusBadge {{ background-color: {bg_color}; border: 1px solid {border_color}; border-radius: 4px; }}"
        )


class ResponseViewer(QWidget):
    """响应查看器"""

    def __init__(self):
        super().__init__()
        self._current_response = None
        self._current_error = None
        self._init_ui()
        self._update_badges_style()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ─── 状态栏 ─────────────────────────────────────────
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(8, 6, 8, 6)
        status_layout.setSpacing(10)

        self.status_label = StatusBadge()
        status_layout.addWidget(self.status_label)

        self.time_label = QLabel("耗时: --")
        self.time_label.setFixedHeight(26)
        status_layout.addWidget(self.time_label)

        self.size_label = QLabel("大小: --")
        self.size_label.setFixedHeight(26)
        status_layout.addWidget(self.size_label)

        status_layout.addStretch()

        self.stream_btn = QPushButton("整合")
        self.stream_btn.setFixedHeight(26)
        self.stream_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stream_btn.setToolTip("从流式响应(SSE/Chunked)中提取字段并自动整合连续内容")
        self.stream_btn.clicked.connect(self._on_open_stream_extractor)
        self.stream_btn.setStyleSheet("""
            QPushButton {
                padding: 2px 12px;
                font-size: 12px;
                font-weight: 500;
                border-radius: 5px;
            }
        """)
        self.stream_btn.setVisible(False)
        status_layout.addWidget(self.stream_btn)

        self.copy_btn = QPushButton("复制响应")
        self.copy_btn.setFixedHeight(26)
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setToolTip("复制响应体到剪贴板")
        self.copy_btn.clicked.connect(self._on_copy_response)
        self.copy_btn.setStyleSheet("""
            QPushButton {
                padding: 2px 12px;
                font-size: 12px;
                font-weight: 500;
                border-radius: 5px;
            }
        """)
        self.copy_btn.setVisible(False)
        status_layout.addWidget(self.copy_btn)

        layout.addLayout(status_layout)

        # ─── 分隔线 ─────────────────────────────────────────
        self.separator = QWidget()
        self.separator.setFixedHeight(1)
        layout.addWidget(self.separator)

        # ─── Tab 区域 ─────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setObjectName("responseSubTabs")

        # Pretty 视图 - 使用 QStackedWidget 切换 JSON 折叠视图和 HTML 高亮视图
        self.pretty_stack = QStackedWidget()

        # 页面 0: JsonTextEdit（支持折叠 + 语法高亮）
        self.pretty_json = JsonTextEdit()
        self.pretty_json.setReadOnly(True)
        self.pretty_stack.addWidget(self.pretty_json)

        # 页面 1: QTextEdit（用于 XML/HTML/纯文本的 pygments 高亮）
        self.pretty_view = QTextEdit()
        self.pretty_view.setReadOnly(True)
        self.pretty_view.setFont(QFont("Consolas", 12))
        self.pretty_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.pretty_view.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.pretty_stack.addWidget(self.pretty_view)

        self.tabs.addTab(self.pretty_stack, "Pretty")

        # Raw 视图
        self.raw_view = QTextEdit()
        self.raw_view.setReadOnly(True)
        self.raw_view.setFont(QFont("Consolas", 12))
        self.raw_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.raw_view.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.tabs.addTab(self.raw_view, "Raw")

        # Headers 视图
        self.headers_view = QTableWidget()
        self.headers_view.setColumnCount(2)
        self.headers_view.setWordWrap(True)
        self.headers_view.setHorizontalHeaderLabels(["Header", "Value"])
        self.headers_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.headers_view.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.headers_view.verticalHeader().setVisible(False)
        self.headers_view.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.headers_view, "Headers")

        # 耗时拆解视图
        self.timing_widget = TimingWaterfallWidget()
        self.tabs.addTab(self.timing_widget, "耗时拆解")

        layout.addWidget(self.tabs)
        self.pretty_view.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        # 默认显示 HTML 高亮视图
        self.pretty_stack.setCurrentIndex(1)

    def retranslate_ui(self):
        """刷新界面语言"""
        from app.config.i18n import tr
        if hasattr(self, 'copy_btn'):
            self.copy_btn.setText(tr("btn_copy") + " " + tr("tab_body", "响应"))
        if hasattr(self, 'stream_btn'):
            self.stream_btn.setText(tr("btn_stream_extract", "整合"))
        self.tabs.setTabText(0, tr("tab_pretty"))
        self.tabs.setTabText(1, tr("tab_raw"))
        count = getattr(self, '_last_headers_count', 0)
        h_title = tr("tab_headers")
        self.tabs.setTabText(2, f"{h_title} ({count})" if count > 0 else h_title)
        self.tabs.setTabText(3, tr("tab_timing", "耗时拆解"))

    def _update_badges_style(self, t=None):
        """统一刷新状态码徽章、耗时与响应大小胶囊标签的主题样式（夜间模式专属柔和配色）"""
        if t is None:
            t = ThemeManager.current()
        is_dark = (t.name == "dark")

        # 1. 耗时与大小标签配色（夜间模式调优：哑光 Slate 灰，拒绝刺眼高光）
        if is_dark:
            meta_bg = "#1c1e22"
            meta_border = "#2d3139"
            meta_fg = "#94a3b8"
        else:
            meta_bg = "#f8fafc"
            meta_border = "#e2e8f0"
            meta_fg = "#475569"

        meta_qss = (
            f"padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 500; "
            f"background-color: {meta_bg}; border: 1px solid {meta_border}; color: {meta_fg};"
        )
        self.time_label.setStyleSheet(meta_qss)
        self.size_label.setStyleSheet(meta_qss)

        # 2. 状态码徽章配色（圆点抗锯齿微标 + 舒适阅读色阶）
        if self._current_error:
            if is_dark:
                dot = "#ef4444"
                fg = "#fca5a5"
                bg = "#2b1417"
                border = "#4c1e24"
            else:
                dot = "#dc2626"
                fg = "#b91c1c"
                bg = "#fef2f2"
                border = "#fecaca"
            self.status_label.set_badge("错误", dot, fg, bg, border)

        elif self._current_response:
            code = self._current_response.status_code
            import re
            clean_reason = re.sub(r'^\d{3}\s*', '', str(self._current_response.reason or "")).strip()
            status_text = f"{code} {clean_reason}" if clean_reason else str(code)

            if 200 <= code < 300:
                if is_dark:
                    dot = "#22c55e"
                    fg = "#86efac"
                    bg = "#14291e"
                    border = "#1c452e"
                else:
                    dot = "#16a34a"
                    fg = "#15803d"
                    bg = "#f0fdf4"
                    border = "#bbf7d0"
            elif 300 <= code < 400:
                if is_dark:
                    dot = "#f59e0b"
                    fg = "#fcd34d"
                    bg = "#281e10"
                    border = "#423214"
                else:
                    dot = "#d97706"
                    fg = "#b45309"
                    bg = "#fffbeb"
                    border = "#fde68a"
            else:
                if is_dark:
                    dot = "#ef4444"
                    fg = "#fca5a5"
                    bg = "#2b1417"
                    border = "#4c1e24"
                else:
                    dot = "#dc2626"
                    fg = "#b91c1c"
                    bg = "#fef2f2"
                    border = "#fecaca"

            self.status_label.set_badge(status_text, dot, fg, bg, border)
            self.time_label.setText(f"⏱ {self._current_response.elapsed_ms:.0f} ms")
            self.size_label.setText(f"📦 {self._current_response.size_display}")

        else:
            if is_dark:
                dot = "#64748b"
                fg = "#71717a"
                bg = "#1c1e22"
                border = "#2d3139"
            else:
                dot = "#94a3b8"
                fg = "#64748b"
                bg = "#f8fafc"
                border = "#e2e8f0"
            self.status_label.set_badge("未请求", dot, fg, bg, border)
            self.time_label.setText("耗时: --")
            self.size_label.setText("大小: --")

    def apply_theme(self, t):
        """应用主题"""
        self.separator.setStyleSheet(f"background-color: {t.border_light};")
        self._update_badges_style(t)

        btn_qss = f"""
            QPushButton {{
                background-color: {t.bg_secondary};
                color: {t.text_primary};
                border: 1px solid {t.border_light};
                padding: 2px 12px;
                font-size: 12px;
                font-weight: 500;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: {t.bg_hover};
                border-color: {t.primary_color};
            }}
        """
        if hasattr(self, 'copy_btn'):
            self.copy_btn.setStyleSheet(btn_qss)
        if hasattr(self, 'stream_btn'):
            self.stream_btn.setStyleSheet(btn_qss)

        code_style = f"""
            QTextEdit {{
                background-color: {t.code_bg};
                color: {t.code_text};
                border: none;
                padding: 8px;
                font-family: Consolas, monospace;
            }}
        """
        self.pretty_json.setStyleSheet(code_style)
        self.pretty_view.setStyleSheet(code_style)
        self.raw_view.setStyleSheet(code_style)

        self.headers_view.setStyleSheet(f"""
            QTableWidget {{
                background-color: {t.bg_primary};
                color: {t.text_primary};
                border: none;
            }}
            QHeaderView::section {{
                background-color: {t.header_bg};
                color: {t.header_text};
                padding: 6px;
                border: none;
                border-bottom: 1px solid {t.border_light};
                border-right: 1px solid {t.border_light};
                font-weight: bold;
            }}
        """)
        if hasattr(self, 'timing_widget'):
            self.timing_widget.apply_theme(t)

    def set_response(self, response: HTTPResponse):
        """设置响应数据"""
        t = ThemeManager.current()

        if response.error:
            self._show_error(response.error)
            return

        self._current_response = response
        self._current_error = None
        self._update_badges_style(t)

        self._raw_body = response.body
        self.copy_btn.setVisible(True)
        self.stream_btn.setVisible(bool(response.body))

        # Raw 视图
        self.raw_view.setPlainText(response.body)

        # Pretty 视图 - 根据内容类型切换显示
        body_stripped = response.body.strip()
        is_json = False
        try:
            json.loads(body_stripped)
            is_json = True
        except (json.JSONDecodeError, ValueError):
            pass

        if is_json:
            # JSON 内容：使用 JsonTextEdit（支持折叠 + 语法高亮）
            self.pretty_json.setPlainText(response.body)
            self.pretty_json.format_json()
            self.pretty_stack.setCurrentIndex(0)
        else:
            # 非 JSON 内容：使用 pygments HTML 高亮
            self.pretty_view.setHtml(self._format_body(response.body))
            self.pretty_stack.setCurrentIndex(1)

        # Headers 视图
        self.headers_view.setRowCount(0)
        self.headers_view.setRowCount(0)
        for key, value in response.headers.items():
            row = self.headers_view.rowCount()
            self.headers_view.insertRow(row)
            self.headers_view.setItem(row, 0, QTableWidgetItem(key))
            self.headers_view.setItem(row, 1, QTableWidgetItem(value))
        self.headers_view.resizeRowsToContents()

        # 更新 Headers Tab 数量角标
        h_count = len(response.headers)
        self.tabs.setTabText(2, f"Headers ({h_count})" if h_count > 0 else "Headers")

        # 更新耗时拆解视图
        if hasattr(self, 'timing_widget'):
            self.timing_widget.set_timing(getattr(response, "timing", None), response.elapsed_ms)

    def _show_error(self, error: str):
        """显示错误信息"""
        t = ThemeManager.current()
        self._current_response = None
        self._current_error = error
        self._update_badges_style(t)
        self.tabs.setTabText(2, "Headers")

        self.pretty_view.setHtml(
            f'<div style="color: #c62828; font-size: 14px; padding: 16px;">'
            f'<b>请求错误</b><br><br>{error}</div>'
        )
        self.pretty_stack.setCurrentIndex(1)  # 错误时显示 HTML 视图
        self.raw_view.setPlainText(f"Error: {error}")
        self.headers_view.setRowCount(0)

    def _format_body(self, body: str) -> str:
        """格式化响应体（自动检测 JSON/XML/HTML）"""
        from pygments import highlight
        from pygments.lexers import JsonLexer, XmlLexer, HtmlLexer
        from pygments.formatters import HtmlFormatter

        t = ThemeManager.current()
        body_stripped = body.strip()
        pygments_style = t.pygments_style
        highlight_bg = t.code_highlight_bg

        # 尝试 JSON 格式化
        try:
            parsed = json.loads(body_stripped)
            formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
            highlighted = highlight(formatted, JsonLexer(), HtmlFormatter(
                style=pygments_style,
                noclasses=True,
                linenos=False,
                nowrap=False,  # ← 关键修改：允许换行
            ))
            # return f'<div style="background-color: {highlight_bg}; padding: 8px; white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word;">{highlighted}</div>'
            return f'''<div style="background-color: {highlight_bg}; padding: 8px;">
                <style>
                    span {{ white-space: pre-wrap !important; word-wrap: break-word !important; }}
                </style>
                {highlighted}
            </div>'''
        except (json.JSONDecodeError, ValueError):
            pass

        # 尝试 XML
        if body_stripped.startswith("<?xml") or body_stripped.startswith("<"):
            if self._is_xml(body_stripped):
                highlighted = highlight(body, XmlLexer(), HtmlFormatter(
                    style=pygments_style,
                    noclasses=True,
                    linenos=False,
                    nowrap=False,  # ← 关键修改
                ))
                return f'<div style="background-color: {highlight_bg}; padding: 8px; white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word;">{highlighted}</div>'

        # 尝试 HTML
        if body_stripped.startswith("<!DOCTYPE") or body_stripped.startswith("<html"):
            highlighted = highlight(body, HtmlLexer(), HtmlFormatter(
                style=pygments_style,
                noclasses=True,
                linenos=False,
                nowrap=False,  # ← 关键修改
            ))
            return f'<div style="background-color: {highlight_bg}; padding: 8px; white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word;">{highlighted}</div>'

        # 纯文本（使用 <pre> 并强制换行）
        escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            f'<pre style="background-color: {t.code_bg}; color: {t.code_text}; '
            f'padding: 8px; font-family: Consolas, monospace; '
            f'white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word;">{escaped}</pre>'
        )

    # def _format_body(self, body: str) -> str:
    #     """格式化响应体（自动检测 JSON/XML/HTML）"""
    #     t = ThemeManager.current()
    #     body_stripped = body.strip()
    #     pygments_style = t.pygments_style
    #     highlight_bg = t.code_highlight_bg
    #
    #     # 尝试 JSON 格式化
    #     try:
    #         parsed = json.loads(body_stripped)
    #         formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
    #         highlighted = highlight(formatted, JsonLexer(), HtmlFormatter(
    #             style=pygments_style,
    #             noclasses=True,
    #             linenos=False,
    #         ))
    #         return f'<div style="background-color: {highlight_bg}; padding: 8px; white-space: pre-wrap; word-wrap: break-word;">{highlighted}</div>'
    #     except (json.JSONDecodeError, ValueError):
    #         pass
    #
    #     # 尝试 XML
    #     if body_stripped.startswith("<?xml") or body_stripped.startswith("<"):
    #         if self._is_xml(body_stripped):
    #             highlighted = highlight(body, XmlLexer(), HtmlFormatter(
    #                 style=pygments_style, noclasses=True, linenos=False,
    #             ))
    #             return f'<div style="background-color: {highlight_bg}; padding: 8px; white-space: pre-wrap; word-wrap: break-word;">{highlighted}</div>'
    #
    #     # 尝试 HTML
    #     if body_stripped.startswith("<!DOCTYPE") or body_stripped.startswith("<html"):
    #         highlighted = highlight(body, HtmlLexer(), HtmlFormatter(
    #             style=pygments_style, noclasses=True, linenos=False,
    #         ))
    #         return f'<div style="background-color: {highlight_bg}; padding: 8px; white-space: pre-wrap; word-wrap: break-word;">{highlighted}</div>'
    #
    #     # 纯文本
    #     escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    #     return (
    #         f'<pre style="background-color: {t.code_bg}; color: {t.code_text}; '
    #         f'padding: 8px; font-family: Consolas, monospace; '
    #         f'white-space: pre-wrap; word-wrap: break-word;">{escaped}</pre>'
    #     )

    @staticmethod
    def _is_xml(text: str) -> bool:
        """简单判断是否为 XML"""
        return text.startswith("<?xml") or (
                text.startswith("<") and text.endswith(">") and "\n" in text
        )

    @staticmethod
    def _get_status_color(status_code: int) -> str:
        t = ThemeManager.current()
        if 200 <= status_code < 300:
            return t.status_success
        elif 300 <= status_code < 400:
            return t.status_redirect
        elif 400 <= status_code < 500:
            return t.status_client_error
        elif status_code >= 500:
            return t.status_server_error
        return t.text_primary

    def _on_copy_response(self):
        """复制响应体到剪贴板"""
        body = getattr(self, "_raw_body", "")
        if body:
            # 尝试格式化 JSON
            try:
                text = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                text = body
            self._safe_copy_to_clipboard(text)

    def _safe_copy_to_clipboard(self, text: str):
        """安全地复制到剪贴板，处理 Windows 剪贴板锁定问题"""
        import time
        clipboard = QApplication.clipboard()
        for attempt in range(3):
            try:
                clipboard.setText(text)
                return
            except Exception:
                if attempt < 2:
                    time.sleep(0.1)  # 等待 100ms 后重试
        # 所有重试都失败，忽略错误（剪贴板可能被其他进程占用）

    def clear(self):
        """清空响应"""
        t = ThemeManager.current()
        self._current_response = None
        self._current_error = None
        self._update_badges_style(t)
        self.tabs.setTabText(2, "Headers")
        self.pretty_json.clear()
        self.pretty_view.clear()
        self.raw_view.clear()
        self.headers_view.setRowCount(0)
        if hasattr(self, 'timing_widget'):
            self.timing_widget.clear()
        self.copy_btn.setVisible(False)
        self.stream_btn.setVisible(False)
        self._raw_body = ""

    def _on_open_stream_extractor(self):
        """打开流式响应自动提取与整合对话框"""
        from app.widgets.stream_extractor_dialog import StreamExtractorDialog
        body = getattr(self, "_raw_body", "")
        dlg = StreamExtractorDialog(body, self)
        dlg.exec()
