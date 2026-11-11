"""极简高并发压测面板 (依托 Go 原生协程引擎实现万级 TPS)"""

import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
    QPushButton, QProgressBar, QGroupBox, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit,
    QMessageBox, QFileDialog, QWidget, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from app.config.themes import ThemeManager, get_method_color
from app.core.go_engine import GoEngineManager
from app.core.models import SavedRequest


class StressWorker(QThread):
    """后台压测工作线程"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, request: SavedRequest, config: dict):
        super().__init__()
        self.request = request
        self.config = config

    def run(self):
        try:
            # 执行前置处理：包装参数、函数生成、环境变量占位符替换
            from app.core.processors import PreProcessor
            req = PreProcessor.process(self.request)

            # 序列化请求参数供 Go 引擎读取
            headers = [{"key": h.key, "value": h.value, "enabled": h.enabled} for h in req.headers]
            params = [{"key": p.key, "value": p.value, "enabled": p.enabled} for p in req.params]
            cookies = [{"key": c.get("key", ""), "value": c.get("value", ""), "enabled": c.get("enabled", True)} for c in req.cookies]

            req_payload = {
                "id": req.id,
                "name": req.name,
                "method": req.method,
                "url": req.url,
                "headers": headers,
                "params": params,
                "body_type": req.body_type,
                "body_content": req.body_content,
                "auth_type": req.auth_type,
                "auth_config": req.auth_config,
                "cookies": cookies,
                "timeout": req.timeout,
                "proxy_url": self.config.get("proxy_url", ""),
            }

            engine = GoEngineManager.get_instance()
            result = engine.run_stress_test(req_payload, self.config)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class StressDialog(QDialog):
    """并发压测对话框"""

    def __init__(self, request: SavedRequest, parent=None):
        super().__init__(parent)
        self.request = request
        self._last_result = None
        self._worker = None
        self._proxy_cfg = dict(getattr(self.request, "proxy", {}) or {})

        self.setWindowTitle("高并发性能压测 (Go 协程引擎)")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(880, 720)
        self.setMinimumSize(780, 600)
        self._init_ui()
        self._apply_theme()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(12)

        # ─── 1. 目标请求信息卡片 ─────────────────────────────────
        target_card = QFrame()
        target_card.setObjectName("targetCard")
        target_card.setFrameShape(QFrame.Shape.StyledPanel)
        t_layout = QHBoxLayout(target_card)
        t_layout.setContentsMargins(12, 10, 12, 10)
        t_layout.setSpacing(10)

        method_color = get_method_color(self.request.method)
        self.lbl_method = QLabel(self.request.method)
        self.lbl_method.setStyleSheet(f"""
            font-weight: bold;
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 4px;
            color: #ffffff;
            background-color: {method_color};
            font-family: Consolas, Monaco, monospace;
        """)
        t_layout.addWidget(self.lbl_method)

        self.lbl_url = QLabel(self.request.url or "http://example.com")
        self.lbl_url.setStyleSheet("font-size: 13px; font-weight: 500; font-family: Consolas, Monaco, monospace;")
        t_layout.addWidget(self.lbl_url, 1)

        # 代理模式标识与快速配置按钮
        self.btn_proxy = QPushButton("🌐 代理")
        self.btn_proxy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_proxy.setFixedHeight(28)
        self.btn_proxy.clicked.connect(self._on_open_proxy_dialog)
        t_layout.addWidget(self.btn_proxy)

        main_layout.addWidget(target_card)

        # ─── 2. 压测参数配置 ─────────────────────────────────────
        cfg_group = QGroupBox("压测参数配置")
        cfg_layout = QGridLayout(cfg_group)
        cfg_layout.setContentsMargins(14, 12, 14, 12)
        cfg_layout.setHorizontalSpacing(20)
        cfg_layout.setVerticalSpacing(10)

        # 并发数
        cfg_layout.addWidget(QLabel("并发用户数 (Concurrency):"), 0, 0)
        self.spin_concurrency = QSpinBox()
        self.spin_concurrency.setRange(1, 200)
        self.spin_concurrency.setValue(20)
        self.spin_concurrency.setSuffix(" 人")
        cfg_layout.addWidget(self.spin_concurrency, 0, 1)

        # 持续时间
        cfg_layout.addWidget(QLabel("压测持续时间 (Duration):"), 0, 2)
        self.spin_duration = QSpinBox()
        self.spin_duration.setRange(1, 300)
        self.spin_duration.setValue(10)
        self.spin_duration.setSuffix(" 秒")
        cfg_layout.addWidget(self.spin_duration, 0, 3)

        # 爬坡升压时间
        cfg_layout.addWidget(QLabel("爬坡加压时间 (Ramp-up):"), 1, 0)
        self.spin_rampup = QSpinBox()
        self.spin_rampup.setRange(0, 60)
        self.spin_rampup.setValue(2)
        self.spin_rampup.setSuffix(" 秒")
        cfg_layout.addWidget(self.spin_rampup, 1, 1)

        # 请求间隔
        cfg_layout.addWidget(QLabel("单请求间隔延迟 (Delay):"), 1, 2)
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(0, 5000)
        self.spin_delay.setValue(0)
        self.spin_delay.setSuffix(" ms")
        cfg_layout.addWidget(self.spin_delay, 1, 3)

        main_layout.addWidget(cfg_group)

        # ─── 3. 控制按钮与进度条 ─────────────────────────────────
        ctrl_layout = QHBoxLayout()
        self.btn_start = QPushButton("开始并发压测")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setFixedHeight(34)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border-radius: 6px;
                padding: 0 24px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:pressed { background-color: #047857; }
        """)
        self.btn_start.clicked.connect(self._on_start_stress)
        ctrl_layout.addWidget(self.btn_start)

        self.btn_records = QPushButton("📋 结果列表")
        self.btn_records.setFixedHeight(34)
        self.btn_records.setEnabled(False)
        self.btn_records.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border-radius: 6px;
                padding: 0 16px;
            }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:pressed { background-color: #1d4ed8; }
            QPushButton:disabled { background-color: #9ca3af; }
        """)
        self.btn_records.clicked.connect(self._on_open_records)
        ctrl_layout.addWidget(self.btn_records)

        self.btn_export = QPushButton("导出 JSON 报告")
        self.btn_export.setFixedHeight(34)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._on_export_report)
        ctrl_layout.addWidget(self.btn_export)

        self.btn_export_html = QPushButton("📑 导出 HTML 报告")
        self.btn_export_html.setFixedHeight(34)
        self.btn_export_html.setEnabled(False)
        self.btn_export_html.setStyleSheet("font-weight: 500;")
        self.btn_export_html.clicked.connect(self._on_export_html_report)
        ctrl_layout.addWidget(self.btn_export_html)

        self.btn_minimize = QPushButton("🗕 最小化")
        self.btn_minimize.setFixedHeight(34)
        self.btn_minimize.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #475569;
                font-weight: 500;
                font-size: 12px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 0 10px;
            }
            QPushButton:hover { background-color: #e2e8f0; color: #1e293b; }
            QPushButton:pressed { background-color: #cbd5e1; }
        """)
        self.btn_minimize.setToolTip("最小化压测面板至任务栏，方便在主窗口中调试接口")
        self.btn_minimize.clicked.connect(self.showMinimized)
        ctrl_layout.addWidget(self.btn_minimize)

        ctrl_layout.addStretch()

        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet("color: #6b7280; font-size: 12px;")
        ctrl_layout.addWidget(self.lbl_status)

        main_layout.addLayout(ctrl_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # ─── 4. 压测指标大盘卡片 (8 大核心指标) ────────────────────
        metrics_group = QGroupBox("压测聚合性能指标")
        m_layout = QGridLayout(metrics_group)
        m_layout.setContentsMargins(12, 10, 12, 10)
        m_layout.setSpacing(8)

        self.card_total = self._create_metric_card("总请求数", "--", "成功率: --")
        self.card_tps = self._create_metric_card("平均吞吐量 (TPS / QPS)", "--", "峰值 TPS: --", highlight=True)
        self.card_p90 = self._create_metric_card("P90 延迟分位数", "--", "P50: -- | P99: --")
        self.card_rt = self._create_metric_card("平均请求时间 (Avg RTT)", "--", "网络带宽: --")

        m_layout.addWidget(self.card_total["widget"], 0, 0)
        m_layout.addWidget(self.card_tps["widget"], 0, 1)
        m_layout.addWidget(self.card_p90["widget"], 0, 2)
        m_layout.addWidget(self.card_rt["widget"], 0, 3)

        main_layout.addWidget(metrics_group)

        # ─── 5. 耗时分布与状态码分布 ─────────────────────────────
        detail_layout = QHBoxLayout()
        detail_layout.setSpacing(12)

        # 延迟区间分布表格
        bins_group = QGroupBox("响应耗时区间分布")
        bins_layout = QVBoxLayout(bins_group)
        bins_layout.setContentsMargins(8, 8, 8, 8)
        self.table_bins = QTableWidget(4, 2)
        self.table_bins.setHorizontalHeaderLabels(["延迟区间", "请求数量"])
        self.table_bins.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_bins.verticalHeader().setVisible(False)
        self.table_bins.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_bins.setItem(0, 0, QTableWidgetItem("< 50 ms (优)"))
        self.table_bins.setItem(1, 0, QTableWidgetItem("50 ~ 200 ms (良)"))
        self.table_bins.setItem(2, 0, QTableWidgetItem("200 ~ 500 ms (中)"))
        self.table_bins.setItem(3, 0, QTableWidgetItem("> 500 ms (慢)"))
        for i in range(4):
            self.table_bins.setItem(i, 1, QTableWidgetItem("0"))
        bins_layout.addWidget(self.table_bins)
        detail_layout.addWidget(bins_group, 1)

        # 状态码分布列表
        codes_group = QGroupBox("HTTP 状态码分布")
        codes_layout = QVBoxLayout(codes_group)
        codes_layout.setContentsMargins(8, 8, 8, 8)
        self.table_codes = QTableWidget(0, 2)
        self.table_codes.setHorizontalHeaderLabels(["HTTP 状态码", "响应数量"])
        self.table_codes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_codes.verticalHeader().setVisible(False)
        self.table_codes.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        codes_layout.addWidget(self.table_codes)
        detail_layout.addWidget(codes_group, 1)

        main_layout.addLayout(detail_layout)

        # ─── 6. 智能瓶颈诊断建议 ─────────────────────────────────
        diag_group = QGroupBox("🤖 智能性能瓶颈诊断与优化建议 (Smart Diagnosis)")
        diag_layout = QVBoxLayout(diag_group)
        diag_layout.setContentsMargins(10, 8, 10, 8)
        self.txt_diagnosis = QTextEdit()
        self.txt_diagnosis.setReadOnly(True)
        self.txt_diagnosis.setMaximumHeight(85)
        self.txt_diagnosis.setText("压测完成后，系统将自动分析网络建连消耗、长尾排队与服务端瓶颈并给出针对性调优建议。")
        diag_layout.addWidget(self.txt_diagnosis)
        main_layout.addWidget(diag_group)

    def _create_metric_card(self, title: str, val: str, sub: str, highlight=False):
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet("""
            QFrame {
                border: 1px solid #d1d5db;
                border-radius: 6px;
                background-color: #f9fafb;
                padding: 6px;
            }
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: 500;")
        layout.addWidget(lbl_title)

        color_str = "#2563eb" if highlight else "#111827"
        lbl_val = QLabel(val)
        lbl_val.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {color_str};")
        layout.addWidget(lbl_val)

        lbl_sub = QLabel(sub)
        lbl_sub.setStyleSheet("font-size: 10px; color: #9ca3af;")
        layout.addWidget(lbl_sub)

        return {"widget": frame, "val": lbl_val, "sub": lbl_sub}

    def _apply_theme(self):
        t = ThemeManager.current()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.bg_primary};
                color: {t.text_primary};
            }}
            QGroupBox {{
                font-size: 12px;
                font-weight: bold;
                border: 1px solid {t.border};
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 10px;
                color: {t.text_primary};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
            #targetCard {{
                background-color: {t.bg_secondary};
                border: 1px solid {t.border};
                border-radius: 6px;
            }}
        """)
        self._update_proxy_display()

    def _update_proxy_display(self):
        """刷新压测界面的代理展示与提示"""
        cfg = self._proxy_cfg or {}
        mode = cfg.get("mode", "default")
        t = ThemeManager.current()
        is_dark = (getattr(t, "name", "light") == "dark")

        if mode in ("default", "", None):
            # 继承全局代理策略
            try:
                from app.config.settings import Settings
                g_cfg = Settings().proxy
                g_mode = g_cfg.get("mode", "system")
            except Exception:
                g_mode = "system"
                g_cfg = {}

            if g_mode == "system":
                title = "🌐 代理: 全局(系统)"
                desc = "使用全局代理策略: 跟随系统代理"
            elif g_mode in ("none", "direct"):
                title = "🔌 代理: 全局(直连)"
                desc = "使用全局代理策略: 网卡直连无代理"
            elif g_mode == "pac":
                pac = g_cfg.get("pac_url", "")
                title = "📜 代理: 全局(PAC)"
                desc = f"使用全局代理策略: PAC 脚本 ({pac})"
            elif g_mode in ("custom", "manual"):
                h = g_cfg.get("host") or g_cfg.get("server") or "自定义"
                p = g_cfg.get("port", "")
                srv = f"{h}:{p}" if p else h
                title = f"⚙️ 代理: 全局({srv})"
                desc = f"使用全局自定义代理: {srv}"
            else:
                title = "🌐 代理: 跟随全局"
                desc = "使用全局设定的代理策略"

            bg = "#334155" if is_dark else "#f1f5f9"
            color = "#cbd5e1" if is_dark else "#475569"
            border = "#475569" if is_dark else "#cbd5e1"
            self.btn_proxy.setText(title)
            self.btn_proxy.setToolTip(f"{desc}\n点击可为本次压测配置专属代理")
            self.btn_proxy.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg};
                    color: {color};
                    font-size: 11px;
                    font-weight: 500;
                    border: 1px solid {border};
                    border-radius: 5px;
                    padding: 2px 10px;
                }}
                QPushButton:hover {{
                    background-color: {"#475569" if is_dark else "#e2e8f0"};
                    color: {"#ffffff" if is_dark else "#1e293b"};
                }}
            """)
        else:
            # 单请求/本次压测已自定义代理，高亮显示
            if mode == "system":
                title = "🌐 代理: 系统代理"
                desc = "本次压测使用系统代理"
            elif mode in ("none", "direct"):
                title = "🔌 代理: 直连无代理"
                desc = "本次压测强制直连（绕过代理）"
            elif mode == "pac":
                pac = cfg.get("pac_url", "")
                title = "📜 代理: PAC 脚本"
                desc = f"本次压测使用 PAC: {pac}"
            elif mode in ("custom", "manual"):
                h = cfg.get("host") or cfg.get("server") or "自定义"
                p = cfg.get("port", "")
                srv = f"{h}:{p}" if p else h
                title = f"⚙️ 代理: {srv}"
                desc = f"本次压测使用自定义代理: {srv}"
            else:
                title = f"🌐 代理: {mode}"
                desc = f"本次压测指定代理: {mode}"

            self.btn_proxy.setText(title)
            self.btn_proxy.setToolTip(f"{desc}\n点击修改压测代理配置")
            self.btn_proxy.setStyleSheet(f"""
                QPushButton {{
                    background-color: {"#064e3b" if is_dark else "#ecfdf5"};
                    color: {"#6ee7b7" if is_dark else "#065f46"};
                    font-size: 11px;
                    font-weight: bold;
                    border: 1px solid {"#059669" if is_dark else "#10b981"};
                    border-radius: 5px;
                    padding: 2px 10px;
                }}
                QPushButton:hover {{
                    background-color: {"#065f46" if is_dark else "#d1fae5"};
                }}
            """)

    def _on_open_proxy_dialog(self):
        """弹出并发压测专属代理配置对话框"""
        from app.widgets.proxy_dialog import RequestProxyDialog
        dlg = RequestProxyDialog(self._proxy_cfg, self)
        dlg.setWindowTitle("并发压测专属代理设置")
        if dlg.exec():
            self._proxy_cfg = dlg.get_result()
            self._update_proxy_display()

    def _on_start_stress(self):
        if not self.request.url:
            QMessageBox.warning(self, "警告", "当前请求未配置目标 URL")
            return

        # 解析生效代理配置：单次/当前界面设置 > 接口自身代理 > 全局系统代理
        active_proxy_cfg = self._proxy_cfg
        if not active_proxy_cfg or active_proxy_cfg.get("mode") in ("default", "", None):
            try:
                from app.config.settings import Settings
                active_proxy_cfg = Settings().proxy
            except Exception:
                active_proxy_cfg = {"mode": "system"}

        from app.core.proxy_manager import resolve_httpx_proxy
        resolved_proxy_url, _ = resolve_httpx_proxy(active_proxy_cfg, self.request.url)
        mode = (active_proxy_cfg.get("mode") or "system").lower()
        if mode in ("none", "direct"):
            final_proxy_arg = "direct"
        elif resolved_proxy_url:
            final_proxy_arg = resolved_proxy_url
        else:
            final_proxy_arg = ""

        cfg = {
            "concurrency": self.spin_concurrency.value(),
            "duration_sec": self.spin_duration.value(),
            "ramp_up_sec": self.spin_rampup.value(),
            "delay_ms": self.spin_delay.value(),
            "proxy_url": final_proxy_arg,
            "proxy_cfg": active_proxy_cfg,
        }

        self.btn_start.setEnabled(False)
        self.btn_records.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.btn_export_html.setEnabled(False)
        self.progress_bar.setRange(0, 0)  # 跑马灯等待

        proxy_tip = ""
        if final_proxy_arg == "direct":
            proxy_tip = " | 直连"
        elif final_proxy_arg:
            proxy_tip = f" | 代理: {final_proxy_arg}"
        self.lbl_status.setText(f"压测中 (并发: {cfg['concurrency']} / 时长: {cfg['duration_sec']}s{proxy_tip})...")

        self._worker = StressWorker(self.request, cfg)
        self._worker.finished.connect(self._on_stress_finished)
        self._worker.error.connect(self._on_stress_error)
        self._worker.start()

    def _on_open_records(self):
        if not self._last_result:
            QMessageBox.information(self, "提示", "请先执行压测以生成结果记录")
            return
        records = self._last_result.get("records", [])
        if not records:
            QMessageBox.information(self, "提示", "本次压测未采集到请求明细数据")
            return
        from app.widgets.stress_records_dialog import StressRecordsDialog
        name = self.request.name or self.request.url or "压测目标"
        self._records_dialog = StressRecordsDialog(records, title=f"压测结果请求明细与多维分析 - {name}", parent=self)
        self._records_dialog.show()
        self._records_dialog.raise_()
        self._records_dialog.activateWindow()

    def _on_stress_finished(self, result: dict):
        self._last_result = result
        self.btn_start.setEnabled(True)
        self.btn_records.setEnabled(bool(result.get("records")))
        self.btn_export.setEnabled(True)
        self.btn_export_html.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        proxy_url = result.get("proxy_url") or ""
        proxy_desc = ""
        if proxy_url:
            if proxy_url == "direct":
                proxy_desc = " [直连无代理]"
            else:
                proxy_desc = f" [代理: {proxy_url}]"
        self.lbl_status.setText(f"压测已完成{proxy_desc}")

        # 更新大盘卡片
        total = result.get("total_requests", 0)
        rate = result.get("success_rate", 0.0)
        succ = result.get("success_count", 0)
        fail = result.get("failure_count", 0)
        self.card_total["val"].setText(str(total))
        self.card_total["sub"].setText(f"成功: {succ} | 失败: {fail} ({rate:.1f}%)")

        avg_tps = result.get("avg_tps", 0.0) or result.get("qps", 0.0)
        peak_tps = result.get("peak_tps", 0.0)
        self.card_tps["val"].setText(f"{avg_tps:.1f} req/s")
        self.card_tps["sub"].setText(f"峰值 TPS: {peak_tps:.1f} | QPS: {avg_tps:.1f}")

        p90 = result.get("p90_ms", 0.0)
        p50 = result.get("p50_ms", 0.0)
        p99 = result.get("p99_ms", 0.0)
        self.card_p90["val"].setText(f"{p90:.1f} ms")
        self.card_p90["sub"].setText(f"P50: {p50:.1f}ms | P99: {p99:.1f}ms")

        avg_rt = result.get("avg_latency_ms", 0.0)
        bw = result.get("bandwidth_kbps", 0.0)
        self.card_rt["val"].setText(f"{avg_rt:.1f} ms")
        self.card_rt["sub"].setText(f"平均请求时间 | 带宽: {bw:.1f} KB/s")

        # 延迟区间
        bins = result.get("latency_bins", {})
        self.table_bins.setItem(0, 1, QTableWidgetItem(str(bins.get("<50ms", 0))))
        self.table_bins.setItem(1, 1, QTableWidgetItem(str(bins.get("50-200ms", 0))))
        self.table_bins.setItem(2, 1, QTableWidgetItem(str(bins.get("200-500ms", 0))))
        self.table_bins.setItem(3, 1, QTableWidgetItem(str(bins.get(">500ms", 0))))

        # 状态码分布
        codes = result.get("status_code_dist", {})
        self.table_codes.setRowCount(len(codes))
        for row, (code, count) in enumerate(codes.items()):
            self.table_codes.setItem(row, 0, QTableWidgetItem(f"HTTP {code}"))
            self.table_codes.setItem(row, 1, QTableWidgetItem(str(count)))

        # 诊断建议
        tips = result.get("diagnosis_tips", [])
        if tips:
            self.txt_diagnosis.setText("\n".join([f"• {t}" for t in tips]))
        else:
            self.txt_diagnosis.setText("当前并发表现优异，响应耗时分布均匀，未发现明显性能瓶颈。")

    def _on_stress_error(self, err_msg: str):
        self.btn_start.setEnabled(True)
        self.btn_export.setEnabled(False)
        self.btn_export_html.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("压测失败")
        QMessageBox.critical(self, "压测错误", f"执行并发压测失败: {err_msg}")

    def _on_export_report(self):
        if not self._last_result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出压测分析报告 (JSON)", "stress_report.json", "JSON Files (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._last_result, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "导出成功", f"压测报告已保存至:\n{path}")

    def _on_export_html_report(self):
        if not self._last_result:
            return
        records = self._last_result.get("records", [])
        from app.widgets.stress_records_dialog import StressRecordsDialog
        name = self.request.name or self.request.url or "单接口压测"
        dlg = StressRecordsDialog(records, title=f"性能压测报告 - {name}", parent=self)
        html_content = dlg._generate_html_report()
        path, _ = QFileDialog.getSaveFileName(self, "导出压测分析报告 (HTML)", "stress_report.html", "HTML Files (*.html)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(html_content)
            QMessageBox.information(self, "导出成功", f"HTML 性能压测报告已保存至:\n{path}")
