"""压测与嗅探结果明细清单与多维可视化分析看板 (基于轻量原生 QPainter 矢量渲染)"""

import csv
import json
from typing import List, Dict, Any, Optional

from urllib.parse import urlparse, parse_qsl

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QComboBox, QFileDialog, QMessageBox, QFrame,
    QScrollArea, QTabWidget, QTextEdit, QApplication
)
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPainterPath,
    QLinearGradient
)

from app.config.themes import ThemeManager, get_method_color


# ─────────────────────────────────────────────────────────────────────────────
# 1. 自定义矢量图表组件 (零三方库，毫秒级响应，自适应明暗主题)
# ─────────────────────────────────────────────────────────────────────────────

class LatencyLineChart(QWidget):
    """响应耗时趋势折线图 (带均值参考线与渐变阴影填充)"""

    def __init__(self, latencies: List[float], parent=None):
        super().__init__(parent)
        self.latencies = latencies or []
        self.setMinimumSize(280, 200)
        self.setMouseTracking(True)
        self._hover_idx: Optional[int] = None

    def set_data(self, latencies: List[float]):
        self.latencies = latencies or []
        self._hover_idx = None
        self.update()

    def mouseMoveEvent(self, event):
        if not self.latencies:
            return
        w = self.width() - 50
        if w <= 0:
            return
        x = event.position().x() - 40
        ratio = max(0.0, min(1.0, x / w))
        idx = int(ratio * (len(self.latencies) - 1))
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()

    def leaveEvent(self, event):
        self._hover_idx = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        t = ThemeManager.current()
        is_dark = t.is_dark if hasattr(t, "is_dark") else False

        bg_color = QColor(t.bg_secondary)
        border_color = QColor(t.border)
        text_color = QColor(t.text_secondary)
        grid_color = QColor(t.border_light)
        line_color = QColor("#3b82f6") if not is_dark else QColor("#60a5fa")
        avg_line_color = QColor("#ef4444")

        # 绘制背景卡片
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(rect, 8, 8)

        # 标题与指标摘要
        count = len(self.latencies)
        avg_val = sum(self.latencies) / count if count > 0 else 0.0
        max_val = max(self.latencies) if count > 0 else 100.0
        min_val = min(self.latencies) if count > 0 else 0.0

        painter.setPen(QPen(QColor(t.text_primary), 1))
        font_title = QFont()
        font_title.setBold(True)
        font_title.setPixelSize(12)
        painter.setFont(font_title)
        painter.drawText(16, 22, "📈 响应耗时波动趋势 (ms)")

        font_sub = QFont()
        font_sub.setPixelSize(11)
        painter.setFont(font_sub)
        painter.setPen(QPen(text_color, 1))
        info_str = f"均值: {avg_val:.1f}ms  |  峰值: {max_val:.1f}ms  |  点数: {count}"
        painter.drawText(self.width() - 16 - painter.fontMetrics().horizontalAdvance(info_str), 22, info_str)

        if count < 2:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无足够时序数据")
            return

        # 绘图区域坐标
        left = 45.0
        right = float(self.width() - 20)
        top = 40.0
        bottom = float(self.height() - 28)
        plot_w = right - left
        plot_h = bottom - top

        y_max = max(max_val * 1.15, 10.0)
        y_min = 0.0

        # 绘制水平网格线与 Y 轴刻度
        painter.setPen(QPen(grid_color, 1, Qt.PenStyle.DashLine))
        grid_steps = 4
        for step in range(grid_steps + 1):
            val = y_min + (y_max - y_min) * (step / grid_steps)
            y = bottom - (val / y_max) * plot_h
            painter.drawLine(int(left), int(y), int(right), int(y))
            painter.setPen(QPen(text_color, 1))
            painter.drawText(6, int(y + 4), f"{val:.0f}")
            painter.setPen(QPen(grid_color, 1, Qt.PenStyle.DashLine))

        # 计算折线点
        points = []
        step_x = plot_w / (count - 1)
        for i, lat in enumerate(self.latencies):
            px = left + i * step_x
            py = bottom - (min(lat, y_max) / y_max) * plot_h
            points.append(QPointF(px, py))

        # 绘制渐变填充区域
        fill_path = QPainterPath()
        fill_path.moveTo(points[0].x(), bottom)
        for pt in points:
            fill_path.lineTo(pt)
        fill_path.lineTo(points[-1].x(), bottom)
        fill_path.closeSubpath()

        grad = QLinearGradient(0, top, 0, bottom)
        grad.setColorAt(0.0, QColor(59, 130, 246, 75))
        grad.setColorAt(1.0, QColor(59, 130, 246, 0))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(fill_path)

        # 绘制主折线
        painter.setPen(QPen(line_color, 2))
        for i in range(len(points) - 1):
            painter.drawLine(points[i], points[i + 1])

        # 绘制平均耗时基准参考线 (红色虚线)
        avg_y = bottom - (min(avg_val, y_max) / y_max) * plot_h
        painter.setPen(QPen(avg_line_color, 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(int(left), int(avg_y), int(right), int(avg_y))
        painter.drawText(int(right - 70), int(avg_y - 4), f"Avg: {avg_val:.1f}ms")

        # 绘制鼠标悬停指示
        if self._hover_idx is not None and 0 <= self._hover_idx < len(points):
            h_pt = points[self._hover_idx]
            h_lat = self.latencies[self._hover_idx]

            # 竖直指示线
            painter.setPen(QPen(QColor("#9ca3af"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(int(h_pt.x()), int(top), int(h_pt.x()), int(bottom))

            # 点标记
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.setBrush(QBrush(QColor("#ef4444")))
            painter.drawEllipse(h_pt, 4.5, 4.5)

            # Tooltip 气泡
            tip_str = f"#{self._hover_idx + 1}: {h_lat:.1f} ms"
            tip_w = painter.fontMetrics().horizontalAdvance(tip_str) + 12
            tip_x = min(h_pt.x() + 8, right - tip_w)
            tip_y = max(h_pt.y() - 20, top + 10)
            painter.setPen(QPen(border_color, 1))
            painter.setBrush(QBrush(QColor(t.bg_primary)))
            painter.drawRoundedRect(QRectF(tip_x, tip_y, tip_w, 20), 4, 4)
            painter.setPen(QPen(QColor(t.text_primary), 1))
            painter.drawText(int(tip_x + 6), int(tip_y + 14), tip_str)


class StatusCodeDonutChart(QWidget):
    """HTTP 状态码分布环形饼图与分类图例"""

    def __init__(self, code_dist: Dict[int, int], parent=None):
        super().__init__(parent)
        self.code_dist = code_dist or {}
        self.setMinimumSize(280, 180)

    def set_data(self, code_dist: Dict[int, int]):
        self.code_dist = code_dist or {}
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        t = ThemeManager.current()
        bg_color = QColor(t.bg_secondary)
        border_color = QColor(t.border)

        # 绘制背景框
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(rect, 8, 8)

        # 标题
        font_title = QFont()
        font_title.setBold(True)
        font_title.setPixelSize(12)
        painter.setFont(font_title)
        painter.setPen(QPen(QColor(t.text_primary), 1))
        painter.drawText(16, 22, "🍩 HTTP 状态码占比分布")

        total = sum(self.code_dist.values())
        if total <= 0:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无状态码统计")
            return

        # 归类状态码: 2xx, 3xx, 4xx, 5xx, 其它
        categories = [
            {"label": "2xx 成功", "codes": [], "count": 0, "color": QColor("#10b981")},
            {"label": "3xx 重定向", "codes": [], "count": 0, "color": QColor("#3b82f6")},
            {"label": "4xx 客户端异常", "codes": [], "count": 0, "color": QColor("#f59e0b")},
            {"label": "5xx 服务端错误", "codes": [], "count": 0, "color": QColor("#ef4444")},
            {"label": "0/网络超时", "codes": [], "count": 0, "color": QColor("#6b7280")},
        ]

        for code, cnt in self.code_dist.items():
            if 200 <= code < 300:
                categories[0]["count"] += cnt
                categories[0]["codes"].append(code)
            elif 300 <= code < 400:
                categories[1]["count"] += cnt
                categories[1]["codes"].append(code)
            elif 400 <= code < 500:
                categories[2]["count"] += cnt
                categories[2]["codes"].append(code)
            elif 500 <= code < 600:
                categories[3]["count"] += cnt
                categories[3]["codes"].append(code)
            else:
                categories[4]["count"] += cnt
                categories[4]["codes"].append(code)

        # 过滤 count > 0 的项
        active_cats = [c for c in categories if c["count"] > 0]

        # 环形饼图区域 (偏左)
        donut_size = min(120.0, self.height() - 50.0)
        donut_rect = QRectF(25, 38, donut_size, donut_size)
        start_angle = 90 * 16

        for cat in active_cats:
            span_angle = int((cat["count"] / total) * 360 * 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(cat["color"]))
            painter.drawPie(donut_rect, start_angle, span_angle)
            start_angle += span_angle

        # 镂空中心实现 Donut 效果
        hole_size = donut_size * 0.55
        hole_rect = QRectF(
            donut_rect.center().x() - hole_size / 2,
            donut_rect.center().y() - hole_size / 2,
            hole_size, hole_size
        )
        painter.setBrush(QBrush(bg_color))
        painter.drawEllipse(hole_rect)

        # 中心文字 (显示总请求数)
        painter.setPen(QPen(QColor(t.text_primary), 1))
        f_mid = QFont()
        f_mid.setBold(True)
        f_mid.setPixelSize(11)
        painter.setFont(f_mid)
        painter.drawText(hole_rect, Qt.AlignmentFlag.AlignCenter, f"{total}\n次")

        # 右侧图例列表
        legend_x = int(donut_rect.right() + 24)
        legend_y = 44
        f_leg = QFont()
        f_leg.setPixelSize(11)
        painter.setFont(f_leg)

        for cat in active_cats:
            pct = (cat["count"] / total) * 100.0
            # 色块
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(cat["color"]))
            painter.drawRoundedRect(QRectF(legend_x, legend_y + 2, 10, 10), 2, 2)

            # 文字
            painter.setPen(QPen(QColor(t.text_primary), 1))
            txt = f"{cat['label']}: {cat['count']} ({pct:.1f}%)"
            painter.drawText(legend_x + 16, legend_y + 11, txt)
            legend_y += 20


class LatencyBarChart(QWidget):
    """耗时区间分布阶梯柱状图"""

    def __init__(self, bins: Dict[str, int], parent=None):
        super().__init__(parent)
        self.bins = bins or {}
        self.setMinimumSize(280, 180)

    def set_data(self, bins: Dict[str, int]):
        self.bins = bins or {}
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        t = ThemeManager.current()
        bg_color = QColor(t.bg_secondary)
        border_color = QColor(t.border)

        # 绘制卡片背景
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(rect, 8, 8)

        # 标题
        font_title = QFont()
        font_title.setBold(True)
        font_title.setPixelSize(12)
        painter.setFont(font_title)
        painter.setPen(QPen(QColor(t.text_primary), 1))
        painter.drawText(16, 22, "📊 响应耗时阶梯分布 (Histogram)")

        items = [
            ("< 50ms", self.bins.get("<50ms") or self.bins.get("< 50ms") or 0, QColor("#10b981")),
            ("50-200ms", self.bins.get("50-200ms") or 0, QColor("#3b82f6")),
            ("200-500ms", self.bins.get("200-500ms") or 0, QColor("#f59e0b")),
            ("> 500ms", self.bins.get(">500ms") or self.bins.get("> 500ms") or 0, QColor("#ef4444")),
        ]

        total = sum(v for _, v, _ in items)
        max_val = max(v for _, v, _ in items) if total > 0 else 10
        if max_val == 0:
            max_val = 10

        left = 25.0
        right = float(self.width() - 25)
        bottom = float(self.height() - 28)
        top = 45.0
        avail_w = right - left
        bar_w = min(46.0, avail_w / 6.0)
        gap = (avail_w - (bar_w * 4)) / 3.0

        f_label = QFont()
        f_label.setPixelSize(10)
        painter.setFont(f_label)

        for i, (cat_name, count, color) in enumerate(items):
            bx = left + i * (bar_w + gap)
            bar_h = (count / max_val) * (bottom - top) if total > 0 else 0
            by = bottom - bar_h

            # 绘制柱子
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(QRectF(bx, by, bar_w, max(bar_h, 3.0)), 4, 4)

            # 柱子上方数值与占比
            painter.setPen(QPen(QColor(t.text_primary), 1))
            val_str = f"{count}"
            painter.drawText(QRectF(bx - 10, by - 16, bar_w + 20, 14), Qt.AlignmentFlag.AlignCenter, val_str)

            # 柱子下方分类文字
            painter.setPen(QPen(QColor(t.text_secondary), 1))
            painter.drawText(QRectF(bx - 14, bottom + 4, bar_w + 28, 16), Qt.AlignmentFlag.AlignCenter, cat_name)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 压测/嗅探结果清单与多维分析对话框 (StressRecordsDialog)
# ─────────────────────────────────────────────────────────────────────────────

class StressRecordsDialog(QDialog):
    """请求结果详情列表、报文全景探查与侧边多维分析看板对话框"""

    def __init__(
        self,
        records: List[Dict[str, Any]],
        title: str = "压测结果明细与图表分析",
        parent=None,
        page_stress_result: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(parent)
        self.all_records = records or []
        self.filtered_records = list(self.all_records)
        self.page_stress_result = page_stress_result or {}
        self._current_selected_record: Optional[Dict[str, Any]] = None

        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(1240, 800)
        self.setMinimumSize(980, 620)

        self._init_ui()
        self._apply_theme()
        self._load_data()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # ─── 顶部汇总指标指示栏 ─────────────────────────────────────
        top_frame = QFrame()
        top_frame.setObjectName("topFrame")
        top_frame.setFrameShape(QFrame.Shape.StyledPanel)
        tf_vbox = QVBoxLayout(top_frame)
        tf_vbox.setContentsMargins(12, 8, 12, 8)
        tf_vbox.setSpacing(6)

        # 第一行指标：请求级与页面级大盘 KPI
        tf_row1 = QHBoxLayout()
        tf_row1.setSpacing(14)

        self.lbl_metric_total = QLabel("总请求: 0")
        self.lbl_metric_total.setStyleSheet("font-weight: bold; font-size: 13px; color: #2563eb;")
        tf_row1.addWidget(self.lbl_metric_total)

        self.lbl_metric_tps = QLabel("⚡ 吞吐量: 0.0 TPS/QPS")
        self.lbl_metric_tps.setStyleSheet("font-weight: bold; font-size: 13px; color: #0284c7;")
        tf_row1.addWidget(self.lbl_metric_tps)

        self.lbl_metric_succ = QLabel("请求成功率: 0.0%")
        self.lbl_metric_succ.setStyleSheet("font-weight: bold; font-size: 13px; color: #15803d;")
        tf_row1.addWidget(self.lbl_metric_succ)

        self.lbl_metric_avg = QLabel("⏱️ 平均请求时间: 0.0 ms")
        self.lbl_metric_avg.setStyleSheet("font-weight: bold; font-size: 13px; color: #b45309;")
        tf_row1.addWidget(self.lbl_metric_avg)

        self.lbl_metric_p90 = QLabel("P90: 0.0 ms")
        self.lbl_metric_p90.setStyleSheet("font-weight: bold; font-size: 13px; color: #7c3aed;")
        tf_row1.addWidget(self.lbl_metric_p90)

        # 全页面事务压测专用指标指示
        self.lbl_page_metric = QLabel("")
        self.lbl_page_metric.setStyleSheet("font-weight: bold; font-size: 12px; color: #0284c7; background: rgba(2,132,199,0.1); padding: 2px 8px; border-radius: 4px;")
        self.lbl_page_metric.setVisible(False)
        tf_row1.addWidget(self.lbl_page_metric)

        tf_row1.addStretch()

        # 导出图表 PNG 按钮
        self.btn_export_png = QPushButton("📸 导出图表 (PNG)")
        self.btn_export_png.setFixedHeight(28)
        self.btn_export_png.setToolTip("将当前视图或综合图表导出为高清 PNG 图片")
        self.btn_export_png.clicked.connect(self._on_export_png)
        tf_row1.addWidget(self.btn_export_png)

        # 导出 HTML 报告按钮
        self.btn_export_html = QPushButton("📑 导出分析报告 (HTML)")
        self.btn_export_html.setFixedHeight(28)
        self.btn_export_html.setToolTip("生成独立的离线交互式 HTML 性能分析与诊断报告")
        self.btn_export_html.clicked.connect(self._on_export_html)
        tf_row1.addWidget(self.btn_export_html)

        # 最小化窗口按钮
        self.btn_minimize = QPushButton("🗕 最小化")
        self.btn_minimize.setFixedHeight(28)
        self.btn_minimize.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #475569;
                font-weight: 500;
                font-size: 11px;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 0 10px;
            }
            QPushButton:hover { background-color: #e2e8f0; color: #1e293b; }
            QPushButton:pressed { background-color: #cbd5e1; }
        """)
        self.btn_minimize.setToolTip("最小化明细图表窗口至任务栏，方便在主窗口中调试接口")
        self.btn_minimize.clicked.connect(self.showMinimized)
        tf_row1.addWidget(self.btn_minimize)

        # 导出清单明细 (CSV / JSON)
        self.btn_export = QPushButton("📥 导出清单")
        self.btn_export.setFixedHeight(28)
        self.btn_export.clicked.connect(self._on_export)
        tf_row1.addWidget(self.btn_export)

        tf_vbox.addLayout(tf_row1)

        # 第二行：搜索与过滤
        tf_row2 = QHBoxLayout()
        tf_row2.setSpacing(10)

        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("🔍 搜索 URL / 接口路径 / 状态码 / 异常信息 / 请求体 / 响应内容...")
        self.edit_search.textChanged.connect(self._apply_filter)
        tf_row2.addWidget(self.edit_search, 1)

        self.combo_filter = QComboBox()
        self.combo_filter.addItems(["全部状态 (All)", "仅成功 (2xx)", "仅重定向 (3xx)", "仅异常 (4xx/5xx/Error)"])
        self.combo_filter.currentIndexChanged.connect(self._apply_filter)
        self.combo_filter.setFixedWidth(160)
        tf_row2.addWidget(self.combo_filter)

        tf_vbox.addLayout(tf_row2)
        main_layout.addWidget(top_frame)

        # ─── 主水平分割区 (左侧清单与报文探查 + 右侧分析图表) ──────────
        self.h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.h_splitter.setChildrenCollapsible(False)
        self.h_splitter.setHandleWidth(8)
        self.splitter_main = self.h_splitter

        # ─── 左侧垂直分割区 (上部清单表格 + 下部请求/响应报文探查器) ───
        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.v_splitter.setChildrenCollapsible(False)
        self.v_splitter.setHandleWidth(8)
        self.splitter_left = self.v_splitter

        # 1. 上部：表格与状态提示容器
        table_container = QWidget()
        tc_layout = QVBoxLayout(table_container)
        tc_layout.setContentsMargins(0, 0, 4, 0)
        tc_layout.setSpacing(4)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "#", "偏移", "方法", "URL / 接口", "状态", "耗时 (ms)", "大小", "异常 / 详情"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(40)
        header.setStretchLastSection(False)
        self.table.setColumnWidth(0, 50)   # #
        self.table.setColumnWidth(1, 80)   # 偏移
        self.table.setColumnWidth(2, 70)   # 方法
        self.table.setColumnWidth(3, 340)  # URL / 接口 (宽敞可读，且可随意拖拽边界调整大小)
        self.table.setColumnWidth(4, 85)   # 状态
        self.table.setColumnWidth(5, 85)   # 耗时 (ms)
        self.table.setColumnWidth(6, 80)   # 大小
        self.table.setColumnWidth(7, 180)  # 异常 / 详情
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setMouseTracking(True)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        tc_layout.addWidget(self.table)

        self.lbl_table_tip = QLabel("就绪")
        self.lbl_table_tip.setStyleSheet("font-size: 11px; color: #6b7280;")
        tc_layout.addWidget(self.lbl_table_tip)

        self.v_splitter.addWidget(table_container)

        # 2. 下部：选定请求的请求参数、响应参数、请求头、响应体多维探查器
        inspector_widget = self._create_detail_inspector()
        self.v_splitter.addWidget(inspector_widget)

        self.v_splitter.setSizes([380, 320])
        self.v_splitter.setStretchFactor(0, 5)
        self.v_splitter.setStretchFactor(1, 4)

        self.h_splitter.addWidget(self.v_splitter)

        # ─── 右侧图表面板 (采用 TabWidget 与垂直平铺滚动视图) ───────────
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(6)

        self.tab_charts = QTabWidget()

        # Tab 1: 平铺综合大盘 (含 3 大核心图表滚动展现)
        scroll_all = QScrollArea()
        scroll_all.setWidgetResizable(True)
        scroll_all.setFrameShape(QFrame.Shape.NoFrame)
        scroll_inner = QWidget()
        s_layout = QVBoxLayout(scroll_inner)
        s_layout.setContentsMargins(4, 4, 4, 4)
        s_layout.setSpacing(12)

        self.chart_line = LatencyLineChart([])
        self.chart_donut = StatusCodeDonutChart({})
        self.chart_bar = LatencyBarChart({})

        s_layout.addWidget(self.chart_line)
        s_layout.addWidget(self.chart_donut)
        s_layout.addWidget(self.chart_bar)
        s_layout.addStretch()

        scroll_all.setWidget(scroll_inner)
        self.tab_charts.addTab(scroll_all, "📊 综合看板")

        # Tab 2: 独立大图 - 耗时趋势
        self.chart_line_solo = LatencyLineChart([])
        self.tab_charts.addTab(self.chart_line_solo, "📈 耗时波动")

        # Tab 3: 独立大图 - 状态码分布
        self.chart_donut_solo = StatusCodeDonutChart({})
        self.tab_charts.addTab(self.chart_donut_solo, "🍩 状态分布")

        # Tab 4: 独立大图 - 耗时阶梯
        self.chart_bar_solo = LatencyBarChart({})
        self.tab_charts.addTab(self.chart_bar_solo, "📊 延迟阶梯")

        # Tab 5: 慢接口平均耗时排行 (页面压测专用)
        self.table_ranking = QTableWidget(0, 7)
        self.table_ranking.setHorizontalHeaderLabels([
            "排名", "方法", "接口路径", "平均耗时 (ms)", "峰值耗时", "耗时占比", "成功率"
        ])
        header_rank = self.table_ranking.horizontalHeader()
        header_rank.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header_rank.setMinimumSectionSize(40)
        header_rank.setStretchLastSection(False)
        self.table_ranking.setColumnWidth(0, 55)   # 排名
        self.table_ranking.setColumnWidth(1, 70)   # 方法
        self.table_ranking.setColumnWidth(2, 280)  # 接口路径 (宽敞可读，可自由拖拽调整)
        self.table_ranking.setColumnWidth(3, 90)   # 平均耗时
        self.table_ranking.setColumnWidth(4, 90)   # 峰值耗时
        self.table_ranking.setColumnWidth(5, 80)   # 耗时占比
        self.table_ranking.setColumnWidth(6, 80)   # 成功率
        self.table_ranking.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table_ranking.verticalHeader().setVisible(False)
        self.table_ranking.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_ranking.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_ranking.setMouseTracking(True)
        self.tab_charts.addTab(self.table_ranking, "🏆 慢接口排行")

        # Tab 6: 接口错误与异常归因 (页面压测专用)
        self.table_errors = QTableWidget(0, 5)
        self.table_errors.setHorizontalHeaderLabels([
            "方法", "接口 URL", "异常次数", "错误率", "主要状态码与信息"
        ])
        header_err = self.table_errors.horizontalHeader()
        header_err.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header_err.setMinimumSectionSize(40)
        header_err.setStretchLastSection(False)
        self.table_errors.setColumnWidth(0, 70)   # 方法
        self.table_errors.setColumnWidth(1, 280)  # 接口 URL (宽敞可读，可自由拖拽调整)
        self.table_errors.setColumnWidth(2, 80)   # 异常次数
        self.table_errors.setColumnWidth(3, 80)   # 错误率
        self.table_errors.setColumnWidth(4, 260)  # 主要状态码与信息
        self.table_errors.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table_errors.verticalHeader().setVisible(False)
        self.table_errors.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_errors.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_errors.setMouseTracking(True)
        self.tab_charts.addTab(self.table_errors, "⚠️ 接口错误归因")

        right_layout.addWidget(self.tab_charts)
        self.h_splitter.addWidget(right_widget)

        self.h_splitter.setSizes([720, 480])
        self.h_splitter.setStretchFactor(0, 3)
        self.h_splitter.setStretchFactor(1, 2)
        main_layout.addWidget(self.h_splitter, 1)

    def _create_detail_inspector(self) -> QWidget:
        """构建选定请求的请求参数、响应参数、请求头、响应体多维报文探查器"""
        inspector = QFrame()
        inspector.setObjectName("inspectorFrame")
        inspector.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(inspector)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # 头部：当前选中的方法、URL 与快速操作按钮
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.lbl_det_title = QLabel("🔍 报文探查器：请在上方列表中点击任意请求查看其请求参数与响应内容")
        self.lbl_det_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #2563eb;")
        top_bar.addWidget(self.lbl_det_title, 1)

        self.btn_copy_url = QPushButton("📋 复制 URL")
        self.btn_copy_url.setFixedHeight(24)
        self.btn_copy_url.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        self.btn_copy_url.clicked.connect(self._on_copy_current_url)
        top_bar.addWidget(self.btn_copy_url)

        layout.addLayout(top_bar)

        # 详情分栏 TabWidget
        self.tab_details = QTabWidget()
        self.tab_details.setStyleSheet("QTabWidget::pane { border: 1px solid #e5e7eb; border-radius: 4px; }")

        # ── Tab 1: 📌 概览与 URL 参数 ──
        tab_overview = QWidget()
        ov_layout = QVBoxLayout(tab_overview)
        ov_layout.setContentsMargins(8, 8, 8, 8)
        ov_layout.setSpacing(8)

        self.lbl_overview_summary = QLabel("尚未选中请求")
        self.lbl_overview_summary.setStyleSheet("font-size: 12px; padding: 4px; background: rgba(0,0,0,0.03); border-radius: 4px;")
        ov_layout.addWidget(self.lbl_overview_summary)

        lbl_params_title = QLabel("<b>URL 查询参数 (Query String Parameters):</b>")
        lbl_params_title.setStyleSheet("font-size: 11px; color: #4b5563;")
        ov_layout.addWidget(lbl_params_title)

        self.table_params = QTableWidget(0, 2)
        self.table_params.setHorizontalHeaderLabels(["参数名 (Parameter)", "参数值 (Value)"])
        header_params = self.table_params.horizontalHeader()
        header_params.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header_params.setMinimumSectionSize(60)
        header_params.setStretchLastSection(False)
        self.table_params.setColumnWidth(0, 160)
        self.table_params.setColumnWidth(1, 320)
        self.table_params.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table_params.verticalHeader().setVisible(False)
        self.table_params.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_params.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_params.setMouseTracking(True)
        ov_layout.addWidget(self.table_params, 1)

        self.tab_details.addTab(tab_overview, "📌 概览与参数")

        # ── Tab 2: 📤 请求头 (Request Headers) ──
        tab_req_headers = QWidget()
        rh_layout = QVBoxLayout(tab_req_headers)
        rh_layout.setContentsMargins(6, 6, 6, 6)
        rh_layout.setSpacing(4)
        rh_bar = QHBoxLayout()
        btn_copy_rh = QPushButton("📋 复制请求头")
        btn_copy_rh.setFixedHeight(22)
        btn_copy_rh.setStyleSheet("font-size: 11px; padding: 1px 8px;")
        btn_copy_rh.clicked.connect(lambda: self._copy_text(self.txt_req_headers.toPlainText(), "请求头"))
        rh_bar.addWidget(QLabel("<b>发送的 HTTP 请求头:</b>"))
        rh_bar.addStretch()
        rh_bar.addWidget(btn_copy_rh)
        rh_layout.addLayout(rh_bar)

        self.txt_req_headers = QTextEdit()
        self.txt_req_headers.setReadOnly(True)
        self.txt_req_headers.setPlaceholderText("（无专属请求头数据）")
        rh_layout.addWidget(self.txt_req_headers)
        self.tab_details.addTab(tab_req_headers, "📤 请求头")

        # ── Tab 3: 📝 请求体 (Request Body) ──
        tab_req_body = QWidget()
        rb_layout = QVBoxLayout(tab_req_body)
        rb_layout.setContentsMargins(6, 6, 6, 6)
        rb_layout.setSpacing(4)
        rb_bar = QHBoxLayout()
        btn_format_rb = QPushButton("✨ 格式化 JSON")
        btn_format_rb.setFixedHeight(22)
        btn_format_rb.setStyleSheet("font-size: 11px; padding: 1px 8px;")
        btn_format_rb.clicked.connect(lambda: self._format_json_in_editor(self.txt_req_body))
        btn_copy_rb = QPushButton("📋 复制请求体")
        btn_copy_rb.setFixedHeight(22)
        btn_copy_rb.setStyleSheet("font-size: 11px; padding: 1px 8px;")
        btn_copy_rb.clicked.connect(lambda: self._copy_text(self.txt_req_body.toPlainText(), "请求体"))
        rb_bar.addWidget(QLabel("<b>请求数据载荷 (Payload):</b>"))
        rb_bar.addStretch()
        rb_bar.addWidget(btn_format_rb)
        rb_bar.addWidget(btn_copy_rb)
        rb_layout.addLayout(rb_bar)

        self.txt_req_body = QTextEdit()
        self.txt_req_body.setReadOnly(True)
        self.txt_req_body.setPlaceholderText("（无请求体内容）")
        rb_layout.addWidget(self.txt_req_body)
        self.tab_details.addTab(tab_req_body, "📝 请求体")

        # ── Tab 4: 📥 响应头 (Response Headers) ──
        tab_resp_headers = QWidget()
        rsh_layout = QVBoxLayout(tab_resp_headers)
        rsh_layout.setContentsMargins(6, 6, 6, 6)
        rsh_layout.setSpacing(4)
        rsh_bar = QHBoxLayout()
        btn_copy_rsh = QPushButton("📋 复制响应头")
        btn_copy_rsh.setFixedHeight(22)
        btn_copy_rsh.setStyleSheet("font-size: 11px; padding: 1px 8px;")
        btn_copy_rsh.clicked.connect(lambda: self._copy_text(self.txt_resp_headers.toPlainText(), "响应头"))
        rsh_bar.addWidget(QLabel("<b>服务器返回的 HTTP 响应头:</b>"))
        rsh_bar.addStretch()
        rsh_bar.addWidget(btn_copy_rsh)
        rsh_layout.addLayout(rsh_bar)

        self.txt_resp_headers = QTextEdit()
        self.txt_resp_headers.setReadOnly(True)
        self.txt_resp_headers.setPlaceholderText("（无响应头数据）")
        rsh_layout.addWidget(self.txt_resp_headers)
        self.tab_details.addTab(tab_resp_headers, "📥 响应头")

        # ── Tab 5: 📄 响应体 (Response Body) ──
        tab_resp_body = QWidget()
        rsb_layout = QVBoxLayout(tab_resp_body)
        rsb_layout.setContentsMargins(6, 6, 6, 6)
        rsb_layout.setSpacing(4)
        rsb_bar = QHBoxLayout()
        self.lbl_resp_status = QLabel("<b>响应内容体:</b>")
        btn_format_rsb = QPushButton("✨ 格式化 JSON")
        btn_format_rsb.setFixedHeight(22)
        btn_format_rsb.setStyleSheet("font-size: 11px; padding: 1px 8px;")
        btn_format_rsb.clicked.connect(lambda: self._format_json_in_editor(self.txt_resp_body))
        btn_copy_rsb = QPushButton("📋 复制响应体")
        btn_copy_rsb.setFixedHeight(22)
        btn_copy_rsb.setStyleSheet("font-size: 11px; padding: 1px 8px;")
        btn_copy_rsb.clicked.connect(lambda: self._copy_text(self.txt_resp_body.toPlainText(), "响应体"))
        rsb_bar.addWidget(self.lbl_resp_status, 1)
        rsb_bar.addWidget(btn_format_rsb)
        rsb_bar.addWidget(btn_copy_rsb)
        rsb_layout.addLayout(rsb_bar)

        self.txt_resp_body = QTextEdit()
        self.txt_resp_body.setReadOnly(True)
        self.txt_resp_body.setPlaceholderText("（无响应体或服务器未返回内容）")
        rsb_layout.addWidget(self.txt_resp_body)
        self.tab_details.addTab(tab_resp_body, "📄 响应体")

        layout.addWidget(self.tab_details, 1)
        return inspector

    def _on_table_selection_changed(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if selected_rows:
            row = selected_rows[0].row()
            if 0 <= row < len(self.filtered_records):
                self._show_record_detail(self.filtered_records[row])

    def _on_table_cell_clicked(self, row: int, _col: int):
        if 0 <= row < len(self.filtered_records):
            self._show_record_detail(self.filtered_records[row])

    def _show_record_detail(self, r: Dict[str, Any]):
        """在下方多维探查器中完整渲染所选请求的全部报文数据"""
        self._current_selected_record = r
        method = r.get("method", "GET").upper()
        url = r.get("url", "")
        code = int(r.get("status_code", 0))
        elapsed = float(r.get("elapsed_ms", 0.0))
        size = int(r.get("size_bytes", 0))
        err = r.get("error", "")

        status_text = f"HTTP {code}" if code > 0 else "Error"
        self.lbl_det_title.setText(f"🔍 [{method}] {url}  ({status_text} | {elapsed:.1f}ms)")
        self.lbl_det_title.setToolTip(f"点击可查看完整报文\n完整请求 URL: {url}")

        # 1. 概览与 URL Query 参数
        self._update_overview_tab(r)

        # 2. 请求头
        req_headers = r.get("request_headers") or r.get("headers") or {}
        if isinstance(req_headers, dict) and req_headers:
            self.txt_req_headers.setPlainText("\\n".join(f"{k}: {v}" for k, v in req_headers.items()))
        elif isinstance(req_headers, list) and req_headers:
            self.txt_req_headers.setPlainText("\\n".join(f"{h.get('key', '')}: {h.get('value', '')}" for h in req_headers if isinstance(h, dict)))
        else:
            self.txt_req_headers.setPlainText("（无专属请求头或使用全局默认配置）")

        # 3. 请求体
        req_body = r.get("request_body") or r.get("body") or r.get("post_data") or ""
        if req_body:
            try:
                parsed = json.loads(req_body)
                self.txt_req_body.setPlainText(json.dumps(parsed, ensure_ascii=False, indent=2))
            except Exception:
                self.txt_req_body.setPlainText(str(req_body))
        else:
            self.txt_req_body.setPlainText("（无请求体内容）")

        # 4. 响应头
        resp_headers = r.get("response_headers") or {}
        if isinstance(resp_headers, dict) and resp_headers:
            self.txt_resp_headers.setPlainText("\\n".join(f"{k}: {v}" for k, v in resp_headers.items()))
        else:
            self.txt_resp_headers.setPlainText("（无响应头数据）")

        # 5. 响应体
        resp_body = r.get("response_body") or ""
        size_str = f"{size / 1024.0:.1f} KB" if size >= 1024 else f"{size} B"
        self.lbl_resp_status.setText(f"<b>响应内容体:</b> ({status_text}  |  大小: {size_str})")

        if resp_body:
            try:
                parsed = json.loads(resp_body)
                self.txt_resp_body.setPlainText(json.dumps(parsed, ensure_ascii=False, indent=2))
            except Exception:
                self.txt_resp_body.setPlainText(str(resp_body))
        else:
            if err:
                self.txt_resp_body.setPlainText(f"❌ 请求失败，无响应体内容。\\n\\n异常归因: {err}")
            else:
                self.txt_resp_body.setPlainText("（服务器返回空响应体或状态码 204）")

    def _update_overview_tab(self, r: Dict[str, Any]):
        method = r.get("method", "GET").upper()
        url = r.get("url", "")
        code = int(r.get("status_code", 0))
        elapsed = float(r.get("elapsed_ms", 0.0))
        size = int(r.get("size_bytes", 0))
        offset_ms = float(r.get("offset_ms", 0.0))
        err = r.get("error", "")

        status_color = "#16a34a" if 200 <= code < 400 else "#dc2626"
        size_str = f"{size / 1024.0:.1f} KB" if size >= 1024 else f"{size} B"
        offset_str = f"+{offset_ms/1000.0:.2f}s" if offset_ms >= 1000 else f"+{offset_ms:.0f}ms"

        summary_text = (
            f"<b>方法:</b> <span style='color:{get_method_color(method)}; font-weight:bold;'>{method}</span>  |  "
            f"<b>状态码:</b> <span style='color:{status_color}; font-weight:bold;'>HTTP {code or 'Err'}</span>  |  "
            f"<b>响应耗时:</b> <b>{elapsed:.1f} ms</b>  |  "
            f"<b>报文大小:</b> <b>{size_str}</b>  |  "
            f"<b>相对偏移:</b> <b>{offset_str}</b>"
        )
        if err:
            summary_text += f"<br><span style='color:#dc2626;'><b>异常信息:</b> {err}</span>"

        self.lbl_overview_summary.setText(summary_text)

        # 解析 URL 查询参数
        parsed = urlparse(url)
        q_params = parse_qsl(parsed.query, keep_blank_values=True)
        self.table_params.setRowCount(len(q_params))
        for row, (pk, pv) in enumerate(q_params):
            item_k = QTableWidgetItem(pk)
            item_k.setToolTip(f"参数名: {pk}")
            item_v = QTableWidgetItem(pv)
            item_v.setToolTip(f"参数值: {pv}")
            self.table_params.setItem(row, 0, item_k)
            self.table_params.setItem(row, 1, item_v)

    def _on_copy_current_url(self):
        if self._current_selected_record:
            url = self._current_selected_record.get("url", "")
            if url:
                QApplication.clipboard().setText(url)
                QMessageBox.information(self, "复制成功", f"URL 已复制到剪贴板:\n{url}")

    def _copy_text(self, text: str, tip: str):
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "复制成功", f"{tip}已成功复制到剪贴板")

    def _format_json_in_editor(self, editor: QTextEdit):
        raw = editor.toPlainText().strip()
        if not raw:
            return
        try:
            parsed = json.loads(raw)
            editor.setPlainText(json.dumps(parsed, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def _apply_theme(self):
        t = ThemeManager.current()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.bg_primary};
                color: {t.text_primary};
            }}
            #topFrame, #inspectorFrame {{
                background-color: {t.bg_secondary};
                border: 1px solid {t.border};
                border-radius: 6px;
            }}
            QTableWidget {{
                background-color: {t.bg_input};
                color: {t.text_primary};
                border: 1px solid {t.border_light};
                gridline-color: {t.border_light};
            }}
            QTextEdit {{
                background-color: {t.bg_input};
                color: {t.text_primary};
                border: 1px solid {t.border_light};
                border-radius: 4px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 11px;
            }}
            QHeaderView::section {{
                background-color: {t.header_bg};
                color: {t.header_text};
                padding: 4px 6px;
                border: none;
                border-right: 1px solid {t.border_light};
                border-bottom: 1px solid {t.border_light};
                font-weight: bold;
            }}
            QSplitter::handle:horizontal {{
                background-color: {t.border_light};
                width: 8px;
                margin: 2px 0px;
                border-radius: 4px;
            }}
            QSplitter::handle:horizontal:hover {{
                background-color: #3b82f6;
            }}
            QSplitter::handle:horizontal:pressed {{
                background-color: #1d4ed8;
            }}
            QSplitter::handle:vertical {{
                background-color: {t.border_light};
                height: 8px;
                margin: 0px 2px;
                border-radius: 4px;
            }}
            QSplitter::handle:vertical:hover {{
                background-color: #3b82f6;
            }}
            QSplitter::handle:vertical:pressed {{
                background-color: #1d4ed8;
            }}
        """)

    def _load_data(self):
        """装载初始数据并刷新指标与图表"""
        total = len(self.all_records)
        if total == 0:
            self.lbl_table_tip.setText("没有采集到请求明细数据")
        else:
            # 计算聚合统计数据
            success_count = 0
            latencies = []
            code_dist: Dict[int, int] = {}
            bins = {"<50ms": 0, "50-200ms": 0, "200-500ms": 0, ">500ms": 0}

            for r in self.all_records:
                lat = float(r.get("elapsed_ms", 0.0))
                latencies.append(lat)
                code = int(r.get("status_code", 0))
                code_dist[code] = code_dist.get(code, 0) + 1

                if 200 <= code < 400:
                    success_count += 1

                if lat < 50:
                    bins["<50ms"] += 1
                elif lat <= 200:
                    bins["50-200ms"] += 1
                elif lat <= 500:
                    bins["200-500ms"] += 1
                else:
                    bins[">500ms"] += 1

            succ_rate = (success_count / total) * 100.0 if total > 0 else 0.0
            avg_lat = sum(latencies) / total if total > 0 else 0.0
            sorted_lat = sorted(latencies)
            p50 = sorted_lat[int(total * 0.5)] if total > 0 else 0.0
            p90 = sorted_lat[int(total * 0.9)] if total > 0 else 0.0
            p99 = sorted_lat[int(min(len(sorted_lat) - 1, total * 0.99))] if total > 0 else 0.0

            # 计算 TPS / QPS 吞吐量
            tps_val = 0.0
            if self.page_stress_result:
                tps_val = float(self.page_stress_result.get("overall_tps", 0.0) or self.page_stress_result.get("qps", 0.0))
            if tps_val <= 0.0 and self.all_records:
                offsets = [float(r.get("offset_ms", 0.0)) for r in self.all_records if "offset_ms" in r]
                if offsets and max(offsets) > min(offsets):
                    dur_sec = (max(offsets) - min(offsets)) / 1000.0
                    if dur_sec > 0.05:
                        tps_val = total / dur_sec
                elif len(latencies) > 0 and sum(latencies) > 0:
                    tps_val = total / max(sum(latencies) / 1000.0 / 5.0, 0.1)

            self.lbl_metric_total.setText(f"总请求: {total}")
            self.lbl_metric_tps.setText(f"⚡ 吞吐量: {tps_val:.1f} TPS/QPS")
            self.lbl_metric_succ.setText(f"请求成功率: {succ_rate:.1f}%")
            self.lbl_metric_avg.setText(f"⏱️ 平均请求时间: {avg_lat:.1f} ms")
            self.lbl_metric_p90.setText(f"P90: {p90:.1f} ms (P50: {p50:.1f}ms | P99: {p99:.1f}ms)")

            # 填充图表数据
            self.chart_line.set_data(latencies)
            self.chart_donut.set_data(code_dist)
            self.chart_bar.set_data(bins)

            self.chart_line_solo.set_data(latencies)
            self.chart_donut_solo.set_data(code_dist)
            self.chart_bar_solo.set_data(bins)

        # 全页面事务压测指标联动
        if self.page_stress_result:
            page_succ = self.page_stress_result.get("page_success_rate", 0.0)
            avg_load = self.page_stress_result.get("avg_page_load_duration_ms", 0.0)
            p_rps = self.page_stress_result.get("page_rps", 0.0)
            p_tps = self.page_stress_result.get("page_tps", 0.0) or p_rps
            qps_val = self.page_stress_result.get("qps", 0.0) or self.page_stress_result.get("overall_tps", 0.0)
            t_iters = self.page_stress_result.get("total_page_iterations", 0)
            s_iters = self.page_stress_result.get("successful_page_iterations", 0)
            if t_iters > 0:
                self.lbl_page_metric.setText(
                    f"🎯 页面成功率: {page_succ:.1f}% ({s_iters}/{t_iters})  |  "
                    f"⏱️ 页面平均加载: {avg_load:.1f} ms  |  "
                    f"⚡ 页面吞吐: {p_tps:.1f} TPS ({qps_val:.0f} QPS)"
                )
                self.lbl_page_metric.setVisible(True)

            # 填充慢接口排行榜
            rankings = self.page_stress_result.get("endpoint_rankings", [])
            self.table_ranking.setRowCount(len(rankings))
            for row, rk in enumerate(rankings):
                rank_item = QTableWidgetItem(f"#{rk.get('rank', row + 1)}")
                rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                rank_item.setToolTip(f"慢接口排行: #{rk.get('rank', row + 1)}")
                if row == 0:
                    rank_item.setForeground(QColor("#ef4444"))
                    font_b = QFont()
                    font_b.setBold(True)
                    rank_item.setFont(font_b)
                self.table_ranking.setItem(row, 0, rank_item)

                m_item = QTableWidgetItem(rk.get("method", "GET"))
                m_item.setForeground(QColor(get_method_color(rk.get("method", "GET"))))
                m_item.setToolTip(f"HTTP 方法: {rk.get('method', 'GET')}")
                self.table_ranking.setItem(row, 1, m_item)

                url_item = QTableWidgetItem(rk.get("path") or rk.get("url", ""))
                url_item.setToolTip(f"完整接口 URL:\n{rk.get('url', '')}")
                self.table_ranking.setItem(row, 2, url_item)

                avg_item = QTableWidgetItem(f"{rk.get('avg_latency_ms', 0.0):.1f}")
                avg_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                avg_item.setToolTip(f"平均响应耗时: {rk.get('avg_latency_ms', 0.0):.2f} ms")
                self.table_ranking.setItem(row, 3, avg_item)

                max_item = QTableWidgetItem(f"{rk.get('max_latency_ms', 0.0):.1f}")
                max_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                max_item.setToolTip(f"最大峰值耗时: {rk.get('max_latency_ms', 0.0):.2f} ms")
                self.table_ranking.setItem(row, 4, max_item)

                share = rk.get("share_percent", 0.0)
                share_item = QTableWidgetItem(f"{share:.1f}%")
                share_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                share_item.setToolTip(f"整站耗时占比: {share:.1f}%")
                self.table_ranking.setItem(row, 5, share_item)

                succ = rk.get("success_rate", 100.0)
                succ_item = QTableWidgetItem(f"{succ:.1f}%")
                succ_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                succ_item.setToolTip(f"请求成功率: {succ:.1f}%")
                if succ < 95.0:
                    succ_item.setForeground(QColor("#ef4444"))
                self.table_ranking.setItem(row, 6, succ_item)

            # 填充接口错误归因
            err_stats = self.page_stress_result.get("endpoint_error_stats", [])
            self.table_errors.setRowCount(len(err_stats))
            for row, es in enumerate(err_stats):
                em_item = QTableWidgetItem(es.get("method", "GET"))
                em_item.setForeground(QColor(get_method_color(es.get("method", "GET"))))
                em_item.setToolTip(f"HTTP 方法: {es.get('method', 'GET')}")
                self.table_errors.setItem(row, 0, em_item)

                eurl_item = QTableWidgetItem(es.get("url", ""))
                eurl_item.setToolTip(f"接口完整 URL:\n{es.get('url', '')}")
                self.table_errors.setItem(row, 1, eurl_item)

                cnt_item = QTableWidgetItem(str(es.get("error_count", 0)))
                cnt_item.setForeground(QColor("#ef4444"))
                cnt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                cnt_item.setToolTip(f"累计异常发生次数: {es.get('error_count', 0)} 次")
                self.table_errors.setItem(row, 2, cnt_item)

                rate_item = QTableWidgetItem(f"{es.get('error_rate', 0.0):.1f}%")
                rate_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                rate_item.setToolTip(f"接口错误率: {es.get('error_rate', 0.0):.1f}%")
                self.table_errors.setItem(row, 3, rate_item)

                codes = es.get("status_codes", {})
                code_str = ", ".join([f"{k}: {v}次" for k, v in codes.items()])
                last_errs = es.get("last_errors", [])
                err_text = f"状态码[{code_str}]"
                if last_errs:
                    err_text += f" | {last_errs[0]}"
                info_item = QTableWidgetItem(err_text)
                info_item.setToolTip(f"完整异常归因日志:\n{err_text}")
                self.table_errors.setItem(row, 4, info_item)

        self._render_table()

    def _apply_filter(self):
        query = self.edit_search.text().strip().lower()
        mode = self.combo_filter.currentIndex()

        filtered = []
        for r in self.all_records:
            code = int(r.get("status_code", 0))
            url = str(r.get("url", "")).lower()
            err = str(r.get("error", "")).lower()
            method = str(r.get("method", "")).lower()
            idx_str = str(r.get("index", ""))
            body = str(r.get("request_body", "")).lower()
            resp = str(r.get("response_body", "")).lower()

            # 状态分类筛选
            if mode == 1 and not (200 <= code < 300):
                continue
            if mode == 2 and not (300 <= code < 400):
                continue
            if mode == 3 and (200 <= code < 400):
                continue

            # 搜索文本过滤
            if query:
                if (query not in url and query not in err and query not in str(code)
                    and query not in method and query not in idx_str
                    and query not in body and query not in resp):
                    continue

            filtered.append(r)

        self.filtered_records = filtered
        self._render_table()

    def _render_table(self):
        self.table.setRowCount(len(self.filtered_records))
        for row, r in enumerate(self.filtered_records):
            idx = r.get("index", row + 1)
            offset_ms = r.get("offset_ms", 0.0)
            offset_str = f"+{offset_ms/1000.0:.2f}s" if offset_ms >= 1000 else f"+{offset_ms:.0f}ms"
            method = r.get("method", "GET").upper()
            url = r.get("url", "")
            code = int(r.get("status_code", 0))
            elapsed = float(r.get("elapsed_ms", 0.0))
            size = int(r.get("size_bytes", 0))
            err = r.get("error", "")

            # 序号
            item_idx = QTableWidgetItem(str(idx))
            item_idx.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_idx.setToolTip(f"请求序号: #{idx}")
            self.table.setItem(row, 0, item_idx)

            # 偏移
            item_off = QTableWidgetItem(offset_str)
            item_off.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_off.setToolTip(f"距离压测启动相对时间: {offset_str} ({offset_ms:.2f} ms)")
            self.table.setItem(row, 1, item_off)

            # 方法 Badge
            item_m = QTableWidgetItem(f" {method} ")
            item_m.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_m.setForeground(QColor("#ffffff"))
            item_m.setBackground(QColor(get_method_color(method)))
            item_m.setToolTip(f"HTTP 方法: {method}")
            self.table.setItem(row, 2, item_m)

            # URL
            item_url = QTableWidgetItem(url)
            item_url.setToolTip(f"完整请求 URL:\n{url}")
            self.table.setItem(row, 3, item_url)

            # 状态码
            code_str = str(code) if code > 0 else "Err"
            item_code = QTableWidgetItem(code_str)
            item_code.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_code.setToolTip(f"HTTP 状态码: HTTP {code_str}")
            if 200 <= code < 300:
                item_code.setForeground(QColor("#15803d"))
            elif 300 <= code < 400:
                item_code.setForeground(QColor("#2563eb"))
            elif 400 <= code < 500:
                item_code.setForeground(QColor("#b45309"))
            else:
                item_code.setForeground(QColor("#b91c1c"))
            self.table.setItem(row, 4, item_code)

            # 耗时
            item_lat = QTableWidgetItem(f"{elapsed:.1f}")
            item_lat.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_lat.setToolTip(f"响应耗时: {elapsed:.2f} ms")
            if elapsed > 500:
                item_lat.setForeground(QColor("#ef4444"))
            elif elapsed > 200:
                item_lat.setForeground(QColor("#f59e0b"))
            self.table.setItem(row, 5, item_lat)

            # 大小
            size_str = f"{size / 1024.0:.1f} KB" if size >= 1024 else f"{size} B"
            item_size = QTableWidgetItem(size_str)
            item_size.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_size.setToolTip(f"响应数据大小: {size_str} ({size} 字节)")
            self.table.setItem(row, 6, item_size)

            # 异常信息
            item_err = QTableWidgetItem(err or ("✓ 正常" if 200 <= code < 400 else "状态码非2xx"))
            item_err.setToolTip(f"状态与异常信息:\n{err or ('✓ 正常 HTTP ' + str(code))}")
            if err:
                item_err.setForeground(QColor("#ef4444"))
            self.table.setItem(row, 7, item_err)

        self.lbl_table_tip.setText(f"显示 {len(self.filtered_records)} / {len(self.all_records)} 条记录  (点击任意行可探查请求体与服务器响应体)")

        # 默认选中第一条记录并呈现报文探查详情
        if self.filtered_records:
            self.table.selectRow(0)
            self._show_record_detail(self.filtered_records[0])


    def _on_export(self):
        if not self.all_records:
            QMessageBox.information(self, "提示", "没有可导出的数据")
            return

        path, flt = QFileDialog.getSaveFileName(
            self, "导出压测请求清单明细", "stress_records.csv", "CSV 文件 (*.csv);;JSON 文件 (*.json)"
        )
        if not path:
            return

        try:
            if path.endswith(".json"):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.filtered_records, f, ensure_ascii=False, indent=2)
            else:
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["序号", "偏移时间(ms)", "方法", "URL", "状态码", "耗时(ms)", "数据大小(B)", "错误信息"])
                    for r in self.filtered_records:
                        writer.writerow([
                            r.get("index"), r.get("offset_ms"), r.get("method"),
                            r.get("url"), r.get("status_code"), r.get("elapsed_ms"),
                            r.get("size_bytes"), r.get("error")
                        ])
            QMessageBox.information(self, "成功", f"成功导出 {len(self.filtered_records)} 条记录到:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"文件写入失败:\n{e}")

    def _on_export_png(self):
        """将当前分析图表视图导出为高清晰度 PNG 图片"""
        current_w = self.tab_charts.currentWidget()
        if not current_w:
            QMessageBox.information(self, "提示", "没有可导出的图表")
            return

        idx = self.tab_charts.currentIndex()
        tab_name = self.tab_charts.tabText(idx).split()[-1] if self.tab_charts.tabText(idx) else "chart"
        default_file = f"stress_{tab_name}.png"

        path, _ = QFileDialog.getSaveFileName(
            self, "导出图表为 PNG 高清图片", default_file, "PNG 图片 (*.png)"
        )
        if not path:
            return

        try:
            pixmap = current_w.grab()
            if pixmap.save(path, "PNG"):
                QMessageBox.information(self, "导出成功", f"图表已成功保存为高清图片:\n{path}")
            else:
                QMessageBox.critical(self, "失败", "图片保存失败，请检查写入权限")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出图表出错:\n{e}")

    def _on_export_html(self):
        """生成独立离线交互式 HTML 性能分析诊断报告"""
        if not self.all_records:
            QMessageBox.information(self, "提示", "没有可导出的压测数据")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "导出完整可视化 HTML 诊断报告", "stress_report.html", "HTML 报告 (*.html)"
        )
        if not path:
            return

        try:
            html = self._generate_html_report()
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)

            reply = QMessageBox.question(
                self, "导出成功",
                f"完整性能诊断分析报告已生成:\n{path}\n\n是否立即在默认浏览器中打开查看？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                import webbrowser
                webbrowser.open(f"file:///{path.replace('\\', '/')}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"生成 HTML 报告失败:\n{e}")

    def _generate_html_report(self) -> str:
        """生成带内联 SVG 矢量图表和指标卡片的高级 HTML 分析报告"""
        import datetime
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        total = len(self.all_records)
        succ_count = sum(1 for r in self.all_records if 200 <= int(r.get("status_code", 0)) < 400)
        succ_rate = (succ_count / total * 100.0) if total > 0 else 0.0

        latencies = [float(r.get("elapsed_ms", 0.0)) for r in self.all_records]
        avg_lat = sum(latencies) / total if total > 0 else 0.0
        max_lat = max(latencies) if latencies else 0.0
        min_lat = min(latencies) if latencies else 0.0

        sorted_lat = sorted(latencies)
        p50 = sorted_lat[int(len(sorted_lat) * 0.50)] if sorted_lat else 0.0
        p90 = sorted_lat[int(len(sorted_lat) * 0.90)] if sorted_lat else 0.0
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0.0
        p99 = sorted_lat[int(min(len(sorted_lat) - 1, len(sorted_lat) * 0.99))] if sorted_lat else 0.0

        # 计算压测耗时与吞吐量 (TPS / QPS)
        elapsed_sec = 0.0
        if self.page_stress_result and self.page_stress_result.get("elapsed_sec"):
            elapsed_sec = float(self.page_stress_result.get("elapsed_sec"))
        if elapsed_sec <= 0.0 and self.all_records:
            offsets = [float(r.get("offset_ms", 0.0)) for r in self.all_records if "offset_ms" in r]
            if offsets and max(offsets) > min(offsets):
                elapsed_sec = (max(offsets) - min(offsets)) / 1000.0
        if elapsed_sec <= 0.0:
            elapsed_sec = max(sum(latencies) / 1000.0 / 5.0, 1.0) if latencies else 1.0

        # 单接口吞吐量与 QPS
        tps_val = (total / max(elapsed_sec, 0.1)) if total > 0 else 0.0
        qps_val = tps_val

        # 数据传输带宽
        total_bytes = sum(int(r.get("size_bytes", 0)) for r in self.all_records)
        bandwidth_kbps = (total_bytes / 1024.0) / max(elapsed_sec, 0.1)
        if total_bytes >= 1024 * 1024:
            total_bytes_str = f"{total_bytes / (1024.0 * 1024.0):.2f} MB"
        elif total_bytes >= 1024:
            total_bytes_str = f"{total_bytes / 1024.0:.1f} KB"
        else:
            total_bytes_str = f"{total_bytes} B"

        # 状态码分布
        code_dist: Dict[int, int] = {}
        bins = {"<50ms": 0, "50-200ms": 0, "200-500ms": 0, ">500ms": 0}
        for r in self.all_records:
            c = int(r.get("status_code", 0))
            code_dist[c] = code_dist.get(c, 0) + 1
            l = float(r.get("elapsed_ms", 0.0))
            if l < 50:
                bins["<50ms"] += 1
            elif l <= 200:
                bins["50-200ms"] += 1
            elif l <= 500:
                bins["200-500ms"] += 1
            else:
                bins[">500ms"] += 1

        # 页面级压测指标
        is_page = bool(self.page_stress_result)
        target_url = self.page_stress_result.get("target_url", "API 压测目标")
        page_succ = self.page_stress_result.get("page_success_rate", 0.0)
        avg_page_load = self.page_stress_result.get("avg_page_load_duration_ms", 0.0)
        page_rps = self.page_stress_result.get("page_rps", 0.0)
        page_tps = self.page_stress_result.get("page_tps", 0.0) or page_rps
        qps_page = self.page_stress_result.get("qps", 0.0) or self.page_stress_result.get("overall_tps", 0.0) or qps_val
        total_iters = self.page_stress_result.get("total_page_iterations", 0)
        succ_iters = self.page_stress_result.get("successful_page_iterations", 0)
        rankings = self.page_stress_result.get("endpoint_rankings", [])
        error_stats = self.page_stress_result.get("endpoint_error_stats", [])

        # 生成折线图 SVG (采样最多 100 点，平滑曲线)
        plot_lats = latencies
        if len(plot_lats) > 100:
            step = len(plot_lats) / 100.0
            plot_lats = [plot_lats[int(i * step)] for i in range(100)]

        svg_w, svg_h = 760, 220
        pad_l, pad_r, pad_t, pad_b = 50, 20, 30, 30
        pw, ph = svg_w - pad_l - pad_r, svg_h - pad_t - pad_b
        y_max = max(max_lat * 1.15, 10.0)

        points = []
        area_pts = [f"{pad_l},{pad_t + ph}"]
        for i, val in enumerate(plot_lats):
            x = pad_l + (i / (len(plot_lats) - 1 if len(plot_lats) > 1 else 1)) * pw
            y = pad_t + ph - (val / y_max) * ph
            points.append(f"{x:.1f},{y:.1f}")
            area_pts.append(f"{x:.1f},{y:.1f}")
        area_pts.append(f"{pad_l + pw},{pad_t + ph}")

        avg_y = pad_t + ph - (avg_lat / y_max) * ph

        line_svg = f"""
        <svg viewBox="0 0 {svg_w} {svg_h}" class="chart-svg">
            <defs>
                <linearGradient id="lineGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.35"/>
                    <stop offset="100%" stop-color="#3b82f6" stop-opacity="0.0"/>
                </linearGradient>
            </defs>
            <polygon points="{' '.join(area_pts)}" fill="url(#lineGrad)"/>
            <polyline points="{' '.join(points)}" fill="none" stroke="#2563eb" stroke-width="2"/>
            <line x1="{pad_l}" y1="{avg_y:.1f}" x2="{pad_l + pw}" y2="{avg_y:.1f}" stroke="#ef4444" stroke-width="1.5" stroke-dasharray="4,4"/>
            <text x="{pad_l + pw - 10}" y="{avg_y - 6:.1f}" fill="#ef4444" font-size="11" text-anchor="end">均值: {avg_lat:.1f}ms</text>
            <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + ph}" stroke="#e5e7eb" stroke-width="1"/>
            <line x1="{pad_l}" y1="{pad_t + ph}" x2="{pad_l + pw}" y2="{pad_t + ph}" stroke="#e5e7eb" stroke-width="1"/>
            <text x="{pad_l - 6}" y="{pad_t + 10}" fill="#9ca3af" font-size="10" text-anchor="end">{y_max:.0f}ms</text>
            <text x="{pad_l - 6}" y="{pad_t + ph}" fill="#9ca3af" font-size="10" text-anchor="end">0ms</text>
        </svg>
        """

        # 生成状态码分布 SVG
        code_items = []
        for c, cnt in sorted(code_dist.items()):
            col = "#10b981" if 200 <= c < 300 else ("#3b82f6" if 300 <= c < 400 else ("#f59e0b" if 400 <= c < 500 else "#ef4444"))
            code_items.append((c, cnt, col))

        # 慢接口排行 HTML
        ranking_rows = ""
        for rk in rankings:
            share = rk.get("share_percent", 0.0)
            m = rk.get("method", "GET")
            m_col = "#2563eb" if m == "GET" else ("#16a34a" if m == "POST" else ("#d97706" if m == "PUT" else "#dc2626"))
            ranking_rows += f"""
            <tr>
                <td style="text-align: center; font-weight: bold;">#{rk.get('rank')}</td>
                <td><span class="badge" style="background: {m_col}20; color: {m_col};">{m}</span></td>
                <td class="truncate" title="{rk.get('url')}">{rk.get('path') or rk.get('url')}</td>
                <td style="text-align: right; font-weight: bold;">{rk.get('avg_latency_ms', 0.0):.1f} ms</td>
                <td style="text-align: right;">{rk.get('max_latency_ms', 0.0):.1f} ms</td>
                <td>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <div style="flex: 1; background: #f3f4f6; height: 10px; border-radius: 5px; overflow: hidden;">
                            <div style="width: {min(100.0, share)}%; background: #3b82f6; height: 100%;"></div>
                        </div>
                        <span style="font-size: 11px; color: #4b5563; width: 42px;">{share:.1f}%</span>
                    </div>
                </td>
                <td style="text-align: right; color: {'#16a34a' if rk.get('success_rate', 100) >= 95 else '#dc2626'}; font-weight: 500;">
                    {rk.get('success_rate', 100.0):.1f}%
                </td>
            </tr>
            """

        # 异常归因 HTML
        error_rows = ""
        for es in error_stats:
            m = es.get("method", "GET")
            codes_txt = ", ".join([f"{k}: {v}次" for k, v in es.get("status_codes", {}).items()])
            error_rows += f"""
            <tr>
                <td><span class="badge" style="background: #ef444420; color: #dc2626;">{m}</span></td>
                <td class="truncate" title="{es.get('url')}">{es.get('url')}</td>
                <td style="text-align: center; font-weight: bold; color: #dc2626;">{es.get('error_count')}</td>
                <td style="text-align: center; color: #dc2626;">{es.get('error_rate', 0.0):.1f}%</td>
                <td style="font-size: 12px; color: #4b5563;">状态码分布: [{codes_txt}]</td>
            </tr>
            """

        # 请求采样明细表 (前 100 条)
        sample_rows = ""
        for r in self.all_records[:100]:
            c = int(r.get("status_code", 0))
            c_col = "#15803d" if 200 <= c < 300 else ("#2563eb" if 300 <= c < 400 else "#dc2626")
            m = r.get("method", "GET")
            m_col = "#2563eb" if m == "GET" else ("#16a34a" if m == "POST" else "#d97706")
            err = r.get("error", "")
            sample_rows += f"""
            <tr>
                <td style="text-align: center;">{r.get('index')}</td>
                <td><span class="badge" style="background: {m_col}20; color: {m_col};">{m}</span></td>
                <td class="truncate" title="{r.get('url')}">{r.get('url')}</td>
                <td style="text-align: center; font-weight: bold; color: {c_col};">{c if c > 0 else 'ERR'}</td>
                <td style="text-align: right;">{r.get('elapsed_ms', 0.0):.1f} ms</td>
                <td style="text-align: right;">{r.get('size_bytes', 0)} B</td>
                <td style="color: {'#dc2626' if err else '#16a34a'}; font-size: 11px;">{err or '✓ 正常'}</td>
            </tr>
            """

        html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PostManage 性能压测与图表分析诊断报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #f8fafc;
            color: #1e293b;
            padding: 24px;
            line-height: 1.5;
        }}
        .container {{ max-width: 1120px; margin: 0 auto; }}
        .header {{
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 20px 24px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.03);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header h1 {{ font-size: 20px; font-weight: 700; color: #0f172a; }}
        .header .meta {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
        .badge {{
            display: inline-block;
            padding: 2px 7px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 14px;
            margin-bottom: 20px;
        }}
        .kpi-card {{
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 16px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.02);
        }}
        .kpi-title {{ font-size: 12px; font-weight: 500; color: #64748b; }}
        .kpi-val {{ font-size: 24px; font-weight: 700; margin-top: 6px; }}
        .kpi-sub {{ font-size: 11px; color: #94a3b8; margin-top: 4px; }}
        .card {{
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.02);
        }}
        .card-title {{
            font-size: 15px;
            font-weight: 600;
            color: #0f172a;
            margin-bottom: 14px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .chart-svg {{ width: 100%; height: auto; display: block; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            text-align: left;
        }}
        th {{
            background: #f1f5f9;
            color: #475569;
            font-weight: 600;
            padding: 8px 10px;
            border-bottom: 1px solid #e2e8f0;
        }}
        td {{
            padding: 8px 10px;
            border-bottom: 1px solid #f1f5f9;
            color: #1e293b;
        }}
        tr:hover td {{ background: #f8fafc; }}
        .truncate {{
            max-width: 320px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .footer {{
            text-align: center;
            font-size: 12px;
            color: #94a3b8;
            margin-top: 28px;
        }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <div>
            <h1>🚀 PostManage 性能压测与图表分析诊断报告</h1>
            <div class="meta">目标: <strong>{target_url}</strong> | 生成时间: {now_str}</div>
        </div>
        <div>
            <button onclick="window.print()" style="padding: 6px 14px; background: #2563eb; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 12px;">🖨️ 打印 / 存为 PDF</button>
        </div>
    </div>

    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-title">总并发请求数</div>
            <div class="kpi-val" style="color: #2563eb;">{total}</div>
            <div class="kpi-sub">成功请求: {succ_count} ({succ_rate:.1f}%)</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">⚡ 吞吐量 (Throughput / TPS)</div>
            <div class="kpi-val" style="color: #0284c7;">{page_tps if is_page else tps_val:.1f} <span style="font-size: 13px;">{'页/秒' if is_page else 'req/s'}</span></div>
            <div class="kpi-sub">{'底层接口 QPS: ' + f'{qps_page:.1f} 次/秒' if is_page else f'QPS: {qps_val:.1f} | TPS: {tps_val:.1f}'}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">⏱️ 平均请求时间 (Avg RTT)</div>
            <div class="kpi-val" style="color: #b45309;">{avg_lat:.1f} <span style="font-size: 14px;">ms</span></div>
            <div class="kpi-sub">Min: {min_lat:.1f}ms | Max: {max_lat:.1f}ms</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">延迟分位数 (P50 / P90 / P99)</div>
            <div class="kpi-val" style="color: #7c3aed;">{p50:.0f} / {p90:.0f} / {p99:.0f} <span style="font-size: 14px;">ms</span></div>
            <div class="kpi-sub">P50: {p50:.1f}ms | P90: {p90:.1f}ms | P99: {p99:.1f}ms</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">网络数据吞吐量 (Bandwidth)</div>
            <div class="kpi-val" style="color: #059669;">{bandwidth_kbps:.1f} <span style="font-size: 14px;">KB/s</span></div>
            <div class="kpi-sub">总传输流量: {total_bytes_str}</div>
        </div>
        {"<div class='kpi-card'><div class='kpi-title'>页面整体成功率 (全接口皆成功)</div><div class='kpi-val' style='color: " + ('#16a34a' if page_succ >= 95 else '#dc2626') + ";'>" + f"{page_succ:.1f}%" + "</div><div class='kpi-sub'>成功轮次: " + f"{succ_iters} / {total_iters}" + "</div></div>" if is_page else ""}
        {"<div class='kpi-card'><div class='kpi-title'>页面平均加载时长 (关键路径)</div><div class='kpi-val' style='color: #0284c7;'>" + f"{avg_page_load:.1f}" + " <span style='font-size: 14px;'>ms</span></div><div class='kpi-sub'>吞吐量: " + f"{page_rps:.1f}" + " 页/秒</div></div>" if is_page else ""}
    </div>

    <div class="card">
        <div class="card-title">📊 核心性能测试指标度量与基准对照</div>
        <table>
            <thead>
                <tr>
                    <th style="width: 80px;">指标分类</th>
                    <th style="width: 180px;">核心压测指标</th>
                    <th style="width: 140px; text-align: right;">测得数值</th>
                    <th style="width: 90px; text-align: center;">标准单位</th>
                    <th style="width: 140px;">基线参考等级</th>
                    <th>业务含义与技术解读</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><span class="badge" style="background: #2563eb15; color: #2563eb;">吞吐能力</span></td>
                    <td><strong>吞吐量 (Throughput)</strong></td>
                    <td style="text-align: right; font-weight: bold; color: #0284c7;">{page_tps if is_page else tps_val:.1f}</td>
                    <td style="text-align: center; color: #64748b;">{'页/秒' if is_page else 'req/s'}</td>
                    <td><span class="badge" style="background: #10b98115; color: #15803d;">正常/良好</span></td>
                    <td>系统在单位时间内成功处理的事务/请求吞吐总量</td>
                </tr>
                <tr>
                    <td><span class="badge" style="background: #2563eb15; color: #2563eb;">吞吐能力</span></td>
                    <td><strong>QPS (Queries Per Second)</strong></td>
                    <td style="text-align: right; font-weight: bold; color: #0284c7;">{qps_page if is_page else qps_val:.1f}</td>
                    <td style="text-align: center; color: #64748b;">次/秒</td>
                    <td><span class="badge" style="background: #10b98115; color: #15803d;">接口处理频次</span></td>
                    <td>后端服务器每秒能够处理并响应的 HTTP 查询/API 访问总频次</td>
                </tr>
                <tr>
                    <td><span class="badge" style="background: #2563eb15; color: #2563eb;">吞吐能力</span></td>
                    <td><strong>TPS (Transactions Per Second)</strong></td>
                    <td style="text-align: right; font-weight: bold; color: #0284c7;">{page_tps if is_page else tps_val:.1f}</td>
                    <td style="text-align: center; color: #64748b;">笔/秒 (事务/秒)</td>
                    <td><span class="badge" style="background: #10b98115; color: #15803d;">完整事务能力</span></td>
                    <td>单位时间内系统完成的端到端完整业务事务数（单接口时1请求=1事务；全页面嗅探时1整页加载=1事务）</td>
                </tr>
                <tr>
                    <td><span class="badge" style="background: #b4530915; color: #b45309;">响应延时</span></td>
                    <td><strong>平均请求时间 (Average RTT)</strong></td>
                    <td style="text-align: right; font-weight: bold; color: {'#15803d' if avg_lat < 200 else ('#b45309' if avg_lat < 500 else '#dc2626')};">{avg_lat:.1f}</td>
                    <td style="text-align: center; color: #64748b;">毫秒 (ms)</td>
                    <td><span class="badge" style="background: {'#10b98115' if avg_lat < 200 else '#f59e0b15'}; color: {'#15803d' if avg_lat < 200 else '#b45309'};">{'优秀 (<200ms)' if avg_lat < 200 else ('良好 (<500ms)' if avg_lat < 500 else '需优化 (>500ms)')}</span></td>
                    <td>客户端发起请求到完全接收到服务端响应报文的平均往返耗时</td>
                </tr>
                <tr>
                    <td><span class="badge" style="background: #b4530915; color: #b45309;">响应延时</span></td>
                    <td><strong>中位数延迟 (P50)</strong></td>
                    <td style="text-align: right; font-weight: bold;">{p50:.1f}</td>
                    <td style="text-align: center; color: #64748b;">毫秒 (ms)</td>
                    <td>常规体验基准</td>
                    <td>50% 的用户请求能在此时长内快速获得响应，反映常规业务处理效率</td>
                </tr>
                <tr>
                    <td><span class="badge" style="background: #7c3aed15; color: #7c3aed;">延迟分位</span></td>
                    <td><strong>90分位延迟 (P90)</strong></td>
                    <td style="text-align: right; font-weight: bold; color: #7c3aed;">{p90:.1f}</td>
                    <td style="text-align: center; color: #64748b;">毫秒 (ms)</td>
                    <td>SLA 核心保障线</td>
                    <td>90% 的请求响应快于此数值，用于衡量大多数用户的系统体验水平</td>
                </tr>
                <tr>
                    <td><span class="badge" style="background: #7c3aed15; color: #7c3aed;">延迟分位</span></td>
                    <td><strong>99分位延迟 (P99 长尾延迟)</strong></td>
                    <td style="text-align: right; font-weight: bold; color: {'#15803d' if p99 < 500 else '#dc2626'};">{p99:.1f}</td>
                    <td style="text-align: center; color: #64748b;">毫秒 (ms)</td>
                    <td>长尾排队瓶颈线</td>
                    <td>1% 极端缓慢请求的上限，反映垃圾回收(GC)、锁争用、数据库慢查询等长尾波动</td>
                </tr>
                <tr>
                    <td><span class="badge" style="background: #05966915; color: #059669;">网络流量</span></td>
                    <td><strong>数据传输带宽 (Bandwidth)</strong></td>
                    <td style="text-align: right; font-weight: bold; color: #059669;">{bandwidth_kbps:.1f}</td>
                    <td style="text-align: center; color: #64748b;">KB/s</td>
                    <td>网卡流量负载</td>
                    <td>压测执行期间网卡每秒吞吐的数据量（累计数据量: {total_bytes_str}）</td>
                </tr>
                <tr>
                    <td><span class="badge" style="background: #16a34a15; color: #16a34a;">稳定性</span></td>
                    <td><strong>请求成功率 (Success Rate)</strong></td>
                    <td style="text-align: right; font-weight: bold; color: {'#15803d' if succ_rate >= 99 else ('#b45309' if succ_rate >= 95 else '#dc2626')};">{succ_rate:.1f}%</td>
                    <td style="text-align: center; color: #64748b;">%</td>
                    <td>可用性准则</td>
                    <td>返回 HTTP 2xx/3xx 且无协议/网络异常的正常响应请求比例</td>
                </tr>
            </tbody>
        </table>
    </div>

    <div class="card">
        <div class="card-title">📈 响应耗时波动趋势 (ms)</div>
        {line_svg}
    </div>

    {'''
    <div class="card">
        <div class="card-title">🏆 页面接口平均耗时排行 (慢接口识别与瓶颈占比)</div>
        <table>
            <thead>
                <tr>
                    <th style="width: 50px; text-align: center;">排名</th>
                    <th style="width: 70px;">方法</th>
                    <th>接口路径</th>
                    <th style="width: 110px; text-align: right;">平均耗时</th>
                    <th style="width: 110px; text-align: right;">峰值耗时</th>
                    <th style="width: 180px;">耗时占比</th>
                    <th style="width: 80px; text-align: right;">成功率</th>
                </tr>
            </thead>
            <tbody>
                ''' + ranking_rows + '''
            </tbody>
        </table>
    </div>
    ''' if is_page and rankings else ''}

    {'''
    <div class="card">
        <div class="card-title">⚠️ 页面接口异常与错误归因分析</div>
        <table>
            <thead>
                <tr>
                    <th style="width: 70px;">方法</th>
                    <th>接口 URL</th>
                    <th style="width: 90px; text-align: center;">失败次数</th>
                    <th style="width: 80px; text-align: center;">错误率</th>
                    <th>主要状态码与异常</th>
                </tr>
            </thead>
            <tbody>
                ''' + error_rows + '''
            </tbody>
        </table>
    </div>
    ''' if is_page and error_stats else ''}

    <div class="card">
        <div class="card-title">📋 请求时序采样明细 (前 100 条)</div>
        <table>
            <thead>
                <tr>
                    <th style="width: 50px; text-align: center;">#</th>
                    <th style="width: 65px;">方法</th>
                    <th>请求 URL</th>
                    <th style="width: 70px; text-align: center;">状态码</th>
                    <th style="width: 90px; text-align: right;">耗时</th>
                    <th style="width: 80px; text-align: right;">大小</th>
                    <th>详情 / 状态</th>
                </tr>
            </thead>
            <tbody>
                {sample_rows}
            </tbody>
        </table>
    </div>

    <div class="footer">
        由 PostManage API 性能工程套件自动生成 · 专注极速、安全与离线高并发测试
    </div>
</div>
</body>
</html>
"""
        return html_doc

