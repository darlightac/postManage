"""PostManage - 启动加载窗口 (Loading Screen)

提供现代、丝滑且无阻塞的即时启动视觉反馈，展示各阶段加载进度与状态，
杜绝静态启动图黑屏盲等与字符编码乱码问题。
"""

import sys
import time
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QProgressBar, QGraphicsDropShadowEffect, QFrame, QApplication
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor, QPixmap

from app.config.constants import APP_NAME, APP_VERSION


class LoadingScreen(QWidget):
    """启动即时加载进度窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(460, 220)
        self._init_ui()
        self._center_on_screen()

    def _init_ui(self):
        # 根布局：带 12px 外边距留给阴影效果
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(0)

        # 核心卡片容器
        self.card = QFrame(self)
        self.card.setObjectName("loadingCard")
        self.card.setStyleSheet("""
            #loadingCard {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
            }
        """)

        # 卡片阴影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 35))
        shadow.setOffset(0, 4)
        self.card.setGraphicsEffect(shadow)

        # 卡片内部布局
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 20, 24, 18)
        card_layout.setSpacing(14)

        # ─── 顶部：图标 + 标题 + 版本 ───
        header_layout = QHBoxLayout()
        header_layout.setSpacing(14)

        # 应用图标
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(50, 50)
        self.icon_label.setStyleSheet("background: transparent;")
        try:
            from app.config.themes import get_app_icon
            icon = get_app_icon()
            if not icon.isNull():
                self.icon_label.setPixmap(icon.pixmap(50, 50))
        except Exception:
            pass
        header_layout.addWidget(self.icon_label)

        # 标题与副标题
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        title_box.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        app_title = QLabel(APP_NAME)
        app_title.setFont(QFont("Segoe UI, Microsoft YaHei", 17, QFont.Weight.Bold))
        app_title.setStyleSheet("color: #0f172a; background: transparent;")
        title_row.addWidget(app_title)

        version_badge = QLabel(f"v{APP_VERSION}")
        version_badge.setFont(QFont("Segoe UI, Microsoft YaHei", 10, QFont.Weight.DemiBold))
        version_badge.setStyleSheet("""
            color: #2563eb;
            background-color: #eff6ff;
            border: 1px solid #dbeafe;
            border-radius: 4px;
            padding: 2px 6px;
        """)
        title_row.addWidget(version_badge)
        title_row.addStretch()
        title_box.addLayout(title_row)

        subtitle = QLabel("现代化 API 开发与管理平台 · 离线安全版")
        subtitle.setFont(QFont("Microsoft YaHei, Segoe UI", 10))
        subtitle.setStyleSheet("color: #64748b; background: transparent;")
        title_box.addWidget(subtitle)

        header_layout.addLayout(title_box)
        card_layout.addLayout(header_layout)

        # ─── 中部分割细线 ───
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #f1f5f9; background-color: #f1f5f9; max-height: 1px;")
        card_layout.addWidget(sep)

        # ─── 进度状态信息 ───
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)

        self.status_label = QLabel("正在启动核心程序...")
        self.status_label.setFont(QFont("Microsoft YaHei, Segoe UI", 10))
        self.status_label.setStyleSheet("color: #334155; background: transparent;")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        self.percent_label = QLabel("0%")
        self.percent_label.setFont(QFont("Segoe UI, Microsoft YaHei", 10, QFont.Weight.Bold))
        self.percent_label.setStyleSheet("color: #2563eb; background: transparent;")
        status_layout.addWidget(self.percent_label)

        card_layout.addLayout(status_layout)

        # ─── 进度条 ───
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #f1f5f9;
                border-radius: 3px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #2563eb);
                border-radius: 3px;
            }
        """)
        card_layout.addWidget(self.progress_bar)

        root_layout.addWidget(self.card)

    def _center_on_screen(self):
        """将窗口居中在当前活动屏幕"""
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(x, y)

    def set_progress(self, value: int, text: str = ""):
        """更新当前加载进度并强制即时重绘"""
        self.progress_bar.setValue(value)
        self.percent_label.setText(f"{value}%")
        if text:
            self.status_label.setText(text)
        QApplication.processEvents()

    def finish(self, window=None):
        """完成加载平滑关闭"""
        self.close()
