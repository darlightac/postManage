"""代理配置对话框 - 支持全局代理与单接口专属代理配置"""

import time
import urllib.request
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QRadioButton, QButtonGroup,
    QLabel, QLineEdit, QSpinBox, QComboBox, QCheckBox, QPushButton,
    QGroupBox, QFrame, QMessageBox, QTextEdit, QWidget, QStackedLayout,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

from app.config.themes import ThemeManager
from app.config.settings import Settings
from app.config.i18n import tr
from app.core.proxy_manager import (
    get_system_proxy_info, fetch_pac_content, evaluate_pac_script,
    resolve_httpx_proxy,
)
from app.core.logger import get_logger

logger = get_logger("proxy_dialog")


class ProxyTestWorker(QThread):
    """异步测试代理连通性工作线程"""
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, proxy_cfg: dict, test_url: str = "https://httpbin.org/ip"):
        super().__init__()
        self.proxy_cfg = proxy_cfg
        self.test_url = test_url

    def run(self):
        start = time.perf_counter()
        try:
            import httpx
            proxy_url, trust_env = resolve_httpx_proxy(self.proxy_cfg, self.test_url)
            with httpx.Client(proxy=proxy_url, trust_env=trust_env, timeout=5.0, verify=False) as client:
                resp = client.get(self.test_url)
                dur = (time.perf_counter() - start) * 1000
                if resp.status_code == 200:
                    text_snippet = resp.text.strip().replace("\n", " ")
                    if len(text_snippet) > 80:
                        text_snippet = text_snippet[:77] + "..."
                    msg = f"连接成功！耗时: {dur:.0f}ms\n响应内容: {text_snippet}"
                    self.finished.emit(True, msg)
                else:
                    self.finished.emit(False, f"HTTP 响应状态码: {resp.status_code}")
        except Exception as e:
            dur = (time.perf_counter() - start) * 1000
            self.finished.emit(False, f"连接失败 ({dur:.0f}ms): {str(e)}")


class BaseProxyWidget(QWidget):
    """代理配置核心面板组件（被全局代理与单接口代理复用）"""

    def __init__(self, is_request_level: bool = False, parent=None):
        super().__init__(parent)
        self.is_request_level = is_request_level
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ── 1. 代理模式选择区 ──
        mode_group = QGroupBox("代理策略模式")
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setSpacing(8)

        self.btn_group = QButtonGroup(self)

        # 接口级特有：跟随全局代理
        if self.is_request_level:
            self.rb_default = QRadioButton("🔗 跟随全局代理策略 (默认)")
            self.rb_default.setToolTip("使用主菜单【编辑 -> 全局代理配置】中设定的代理策略")
            self.btn_group.addButton(self.rb_default, 0)
            mode_layout.addWidget(self.rb_default)

        # 跟随系统代理
        self.rb_system = QRadioButton("🌐 跟随系统代理 (自动检测操作系统代理)")
        self.rb_system.setToolTip("自动同步并使用 Windows 系统代理或环境变量代理设置")
        self.btn_group.addButton(self.rb_system, 1)
        mode_layout.addWidget(self.rb_system)

        # 网卡直连
        self.rb_none = QRadioButton("🔌 网卡直连无代理 (完全绕过任何代理)")
        self.rb_none.setToolTip("强制不走任何代理，通过本地物理网卡直接访问目标服务器")
        self.btn_group.addButton(self.rb_none, 2)
        mode_layout.addWidget(self.rb_none)

        # 自定义代理
        self.rb_custom = QRadioButton("⚙️ 自定义手动代理 (指定 HTTP / HTTPS / SOCKS5 代理)")
        self.rb_custom.setToolTip("手动指定代理服务器地址、端口及账号密码")
        self.btn_group.addButton(self.rb_custom, 3)
        mode_layout.addWidget(self.rb_custom)

        # PAC 模式
        self.rb_pac = QRadioButton("📜 PAC 自动脚本模式 (Proxy Auto-Configuration)")
        self.rb_pac.setToolTip("通过远程或本地 PAC 脚本动态判定代理路线")
        self.btn_group.addButton(self.rb_pac, 4)
        mode_layout.addWidget(self.rb_pac)

        layout.addWidget(mode_group)

        # ── 2. 系统代理状态提示栏 ──
        self.sys_info_frame = QFrame()
        self.sys_info_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.sys_info_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(59, 130, 246, 0.08);
                border: 1px solid rgba(59, 130, 246, 0.3);
                border-radius: 6px;
                padding: 6px;
            }
        """)
        sys_layout = QHBoxLayout(self.sys_info_frame)
        sys_layout.setContentsMargins(8, 4, 8, 4)
        self.lbl_sys_info = QLabel()
        self.lbl_sys_info.setWordWrap(True)
        self.lbl_sys_info.setStyleSheet("font-size: 12px; color: #1e40af;")
        sys_layout.addWidget(self.lbl_sys_info, 1)

        self.btn_refresh_sys = QPushButton("🔄 刷新")
        self.btn_refresh_sys.setFixedSize(56, 26)
        self.btn_refresh_sys.setStyleSheet("font-size: 11px;")
        self.btn_refresh_sys.clicked.connect(self.refresh_system_proxy_display)
        sys_layout.addWidget(self.btn_refresh_sys)

        layout.addWidget(self.sys_info_frame)

        # ── 3. 自定义代理配置面板 ──
        self.custom_group = QGroupBox("自定义代理参数")
        c_layout = QVBoxLayout(self.custom_group)
        c_layout.setSpacing(8)

        # 协议 + 主机 + 端口
        h_row = QHBoxLayout()
        h_row.addWidget(QLabel("协议:"))
        self.combo_proto = QComboBox()
        self.combo_proto.addItems(["HTTP", "HTTPS", "SOCKS5"])
        self.combo_proto.setFixedWidth(85)
        h_row.addWidget(self.combo_proto)

        h_row.addWidget(QLabel("服务器:"))
        self.edit_host = QLineEdit("127.0.0.1")
        self.edit_host.setPlaceholderText("例如: 127.0.0.1")
        h_row.addWidget(self.edit_host, 1)

        h_row.addWidget(QLabel("端口:"))
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(7890)
        self.spin_port.setFixedWidth(80)
        h_row.addWidget(self.spin_port)
        c_layout.addLayout(h_row)

        # 不代理列表 (Bypass)
        b_row = QHBoxLayout()
        b_row.addWidget(QLabel("不代理的主机 (Bypass):"))
        self.edit_bypass = QLineEdit("localhost, 127.0.0.1, ::1")
        self.edit_bypass.setPlaceholderText("用逗号分隔，如: localhost, 127.0.0.1, 192.168.*, *.internal")
        b_row.addWidget(self.edit_bypass, 1)
        c_layout.addLayout(b_row)

        # 身份认证
        auth_row = QHBoxLayout()
        self.chk_auth = QCheckBox("启用代理身份认证")
        self.chk_auth.toggled.connect(self._on_auth_toggled)
        auth_row.addWidget(self.chk_auth)

        self.edit_user = QLineEdit()
        self.edit_user.setPlaceholderText("用户名")
        self.edit_user.setEnabled(False)
        auth_row.addWidget(self.edit_user)

        self.edit_pwd = QLineEdit()
        self.edit_pwd.setPlaceholderText("密码")
        self.edit_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_pwd.setEnabled(False)
        auth_row.addWidget(self.edit_pwd)
        c_layout.addLayout(auth_row)

        layout.addWidget(self.custom_group)

        # ── 4. PAC 模式配置面板 ──
        self.pac_group = QGroupBox("PAC 自动配置脚本")
        p_layout = QVBoxLayout(self.pac_group)
        p_layout.setSpacing(8)

        pac_row = QHBoxLayout()
        pac_row.addWidget(QLabel("PAC 脚本 URL / 本地路径:"))
        self.edit_pac_url = QLineEdit()
        self.edit_pac_url.setPlaceholderText("http://127.0.0.1:1080/pac 或 file:///C:/proxy.pac")
        pac_row.addWidget(self.edit_pac_url, 1)

        self.btn_test_pac = QPushButton("🔍 探测 PAC")
        self.btn_test_pac.setFixedSize(85, 28)
        self.btn_test_pac.clicked.connect(self._on_test_pac)
        pac_row.addWidget(self.btn_test_pac)
        p_layout.addLayout(pac_row)

        self.lbl_pac_status = QLabel("")
        self.lbl_pac_status.setStyleSheet("font-size: 11px; color: #64748b;")
        self.lbl_pac_status.setWordWrap(True)
        p_layout.addWidget(self.lbl_pac_status)

        layout.addWidget(self.pac_group)

        # 绑定模式切换联动
        self.btn_group.idToggled.connect(self._on_mode_changed)

        self.refresh_system_proxy_display()

    def _on_auth_toggled(self, checked: bool):
        self.edit_user.setEnabled(checked)
        self.edit_pwd.setEnabled(checked)

    def refresh_system_proxy_display(self):
        info = get_system_proxy_info()
        if info["enabled"] and info["server"]:
            self.lbl_sys_info.setText(
                f"🖥️ <b>当前系统代理:</b> 已开启 | 地址: <code>{info['server']}</code> "
                f"(来源: {info['source']})"
            )
        elif info.get("pac_url"):
            self.lbl_sys_info.setText(
                f"🖥️ <b>当前系统代理:</b> 已开启 PAC 自动配置 | 脚本: <code>{info['pac_url']}</code>"
            )
        else:
            self.lbl_sys_info.setText("🖥️ <b>当前系统代理:</b> 未开启或直连模式（系统无全局代理）")

    def _on_mode_changed(self, btn_id: int, checked: bool):
        if not checked:
            return

        is_default = (btn_id == 0) and self.is_request_level
        is_system = (btn_id == 1)
        is_none = (btn_id == 2)
        is_custom = (btn_id == 3)
        is_pac = (btn_id == 4)

        self.sys_info_frame.setVisible(is_system or is_default)
        self.custom_group.setVisible(is_custom)
        self.pac_group.setVisible(is_pac)

    def _on_test_pac(self):
        url = self.edit_pac_url.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请输入 PAC 脚本的 URL 地址或本地路径")
            return
        self.lbl_pac_status.setText("正在拉取并解析 PAC 脚本...")
        text = fetch_pac_content(url)
        if text:
            res = evaluate_pac_script(text, "https://www.google.com")
            self.lbl_pac_status.setText(f"✔ PAC 脚本解析成功！针对外网默认路由: {res or 'DIRECT'}")
            self.lbl_pac_status.setStyleSheet("font-size: 11px; color: #16a34a; font-weight: bold;")
        else:
            self.lbl_pac_status.setText("❌ 获取 PAC 脚本失败，请检查 URL 是否可连通")
            self.lbl_pac_status.setStyleSheet("font-size: 11px; color: #dc2626; font-weight: bold;")

    def get_config(self) -> dict:
        """导出当前配置字典"""
        btn_id = self.btn_group.checkedId()
        mode_map = {
            0: "default",
            1: "system",
            2: "none",
            3: "custom",
            4: "pac",
        }
        mode = mode_map.get(btn_id, "system")
        return {
            "mode": mode,
            "protocol": self.combo_proto.currentText(),
            "host": self.edit_host.text().strip(),
            "port": self.spin_port.value(),
            "all_proxy": "",
            "bypass": self.edit_bypass.text().strip(),
            "auth_enabled": self.chk_auth.isChecked(),
            "username": self.edit_user.text().strip(),
            "password": self.edit_pwd.text(),
            "pac_url": self.edit_pac_url.text().strip(),
        }

    def set_config(self, cfg: Optional[dict]):
        """加载配置字典并刷新界面"""
        c = cfg or {}
        mode = c.get("mode", "default" if self.is_request_level else "system")

        if self.is_request_level and mode == "default":
            self.rb_default.setChecked(True)
        elif mode == "none":
            self.rb_none.setChecked(True)
        elif mode in ("custom", "manual"):
            self.rb_custom.setChecked(True)
        elif mode == "pac":
            self.rb_pac.setChecked(True)
        else:
            self.rb_system.setChecked(True)

        proto = c.get("protocol", "HTTP").upper()
        idx = self.combo_proto.findText(proto)
        if idx >= 0:
            self.combo_proto.setCurrentIndex(idx)

        self.edit_host.setText(c.get("host", "127.0.0.1"))
        self.spin_port.setValue(int(c.get("port", 7890) or 7890))
        self.edit_bypass.setText(c.get("bypass", "localhost, 127.0.0.1, ::1"))

        auth_en = bool(c.get("auth_enabled", False))
        self.chk_auth.setChecked(auth_en)
        self.edit_user.setText(c.get("username", ""))
        self.edit_pwd.setText(c.get("password", ""))
        self._on_auth_toggled(auth_en)

        self.edit_pac_url.setText(c.get("pac_url", ""))


class GlobalProxyDialog(QDialog):
    """全局代理配置对话框 (编辑 -> 全局代理配置)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("全局代理配置")
        self.resize(560, 480)
        self.setMinimumSize(500, 420)
        self._test_worker = None

        self._init_ui()
        self._load_current()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 14)
        main_layout.setSpacing(12)

        # 核心面板 (全局级别)
        self.proxy_widget = BaseProxyWidget(is_request_level=False, parent=self)
        main_layout.addWidget(self.proxy_widget)

        # 连通性测试区
        test_frame = QFrame()
        test_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 0, 0, 0.02);
                border: 1px dashed #cbd5e1;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        t_layout = QHBoxLayout(test_frame)
        t_layout.setContentsMargins(8, 4, 8, 4)

        self.btn_test = QPushButton("⚡ 测试代理连接")
        self.btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test.setFixedHeight(28)
        self.btn_test.clicked.connect(self._on_test_connection)
        t_layout.addWidget(self.btn_test)

        self.lbl_test_result = QLabel("点击测试当前代理配置是否可正常访问外部网络")
        self.lbl_test_result.setStyleSheet("font-size: 11px; color: #64748b;")
        self.lbl_test_result.setWordWrap(True)
        t_layout.addWidget(self.lbl_test_result, 1)

        main_layout.addWidget(test_frame)

        # 底部确定取消按钮
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedSize(75, 30)
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("保存配置")
        self.btn_save.setFixedSize(90, 30)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        self.btn_save.clicked.connect(self._on_save)
        btn_box.addWidget(self.btn_save)

        main_layout.addLayout(btn_box)

    def _load_current(self):
        cfg = Settings().proxy
        self.proxy_widget.set_config(cfg)

    def _on_test_connection(self):
        cfg = self.proxy_widget.get_config()
        self.btn_test.setEnabled(False)
        self.lbl_test_result.setText("正在通过代理发起网络连接探测，请稍候...")
        self.lbl_test_result.setStyleSheet("font-size: 11px; color: #2563eb;")

        self._test_worker = ProxyTestWorker(cfg)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.start()

    def _on_test_finished(self, ok: bool, msg: str):
        self.btn_test.setEnabled(True)
        self.lbl_test_result.setText(msg)
        color = "#16a34a" if ok else "#dc2626"
        self.lbl_test_result.setStyleSheet(f"font-size: 11px; color: {color}; font-weight: 500;")

    def _on_save(self):
        cfg = self.proxy_widget.get_config()
        Settings().proxy = cfg
        logger.info(f"全局代理配置已更新: {cfg.get('mode')}")
        self.accept()


class RequestProxyDialog(QDialog):
    """接口专属代理配置对话框 (接口详情页面 -> 代理按钮)"""

    def __init__(self, current_proxy_cfg: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("当前接口代理设置")
        self.resize(560, 500)
        self.setMinimumSize(500, 440)
        self._test_worker = None
        self._current_cfg = current_proxy_cfg or {"mode": "default"}

        self._init_ui()
        self.proxy_widget.set_config(self._current_cfg)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 14)
        main_layout.setSpacing(12)

        # 顶部提示：说明接口级优先级
        tip_frame = QFrame()
        tip_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(16, 185, 129, 0.08);
                border: 1px solid rgba(16, 185, 129, 0.3);
                border-radius: 6px;
                padding: 4px;
            }
        """)
        tip_layout = QHBoxLayout(tip_frame)
        lbl_tip = QLabel("💡 <b>提示:</b> 此处设置仅对当前接口生效。若配置了接口独立代理，将优先于全局代理生效。")
        lbl_tip.setStyleSheet("font-size: 12px; color: #065f46;")
        tip_layout.addWidget(lbl_tip)
        main_layout.addWidget(tip_frame)

        # 核心面板 (接口级别，支持“跟随全局”)
        self.proxy_widget = BaseProxyWidget(is_request_level=True, parent=self)
        main_layout.addWidget(self.proxy_widget)

        # 连通性测试区
        test_frame = QFrame()
        test_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 0, 0, 0.02);
                border: 1px dashed #cbd5e1;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        t_layout = QHBoxLayout(test_frame)
        t_layout.setContentsMargins(8, 4, 8, 4)

        self.btn_test = QPushButton("⚡ 测试代理连接")
        self.btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test.setFixedHeight(28)
        self.btn_test.clicked.connect(self._on_test_connection)
        t_layout.addWidget(self.btn_test)

        self.lbl_test_result = QLabel("点击测试当前代理配置是否正常连通")
        self.lbl_test_result.setStyleSheet("font-size: 11px; color: #64748b;")
        self.lbl_test_result.setWordWrap(True)
        t_layout.addWidget(self.lbl_test_result, 1)

        main_layout.addWidget(test_frame)

        # 底部确定取消按钮
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedSize(75, 30)
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        self.btn_ok = QPushButton("应用此接口")
        self.btn_ok.setFixedSize(100, 30)
        self.btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: #ffffff;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #047857; }
        """)
        self.btn_ok.clicked.connect(self._on_apply)
        btn_box.addWidget(self.btn_ok)

        main_layout.addLayout(btn_box)

    def _on_test_connection(self):
        cfg = self.proxy_widget.get_config()
        # 若为跟随全局，测试时取全局配置
        test_cfg = cfg
        if cfg.get("mode") == "default":
            test_cfg = Settings().proxy

        self.btn_test.setEnabled(False)
        self.lbl_test_result.setText("正在通过代理发起网络连接探测，请稍候...")
        self.lbl_test_result.setStyleSheet("font-size: 11px; color: #2563eb;")

        self._test_worker = ProxyTestWorker(test_cfg)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.start()

    def _on_test_finished(self, ok: bool, msg: str):
        self.btn_test.setEnabled(True)
        self.lbl_test_result.setText(msg)
        color = "#16a34a" if ok else "#dc2626"
        self.lbl_test_result.setStyleSheet(f"font-size: 11px; color: {color}; font-weight: 500;")

    def _on_apply(self):
        self._result_cfg = self.proxy_widget.get_config()
        self.accept()

    def get_result(self) -> dict:
        return getattr(self, "_result_cfg", self._current_cfg)
