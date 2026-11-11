"""主窗口 - 整合所有组件"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTabWidget, QLabel, QStatusBar,
    QMenuBar, QFileDialog, QMessageBox, QDialog,
    QInputDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QActionGroup

import sys
import json
import re

from app.config.i18n import I18nManager, tr

from app.config.constants import APP_NAME, APP_VERSION, APP_AUTHOR, APP_LICENSE, APP_COPYRIGHT
from app.config.settings import Settings
from app.config.themes import (
    ThemeManager, LightTheme, DarkTheme,
    generate_main_stylesheet, generate_left_panel_stylesheet,
    generate_left_tabs_stylesheet,
)
from app.core.db import Database
from app.core.logger import get_logger
from app.core.models import SavedRequest, HistoryRecord, HTTPResponse, Collection, generate_id
from app.core.http_client import HTTPClient
from app.core.exporter import export_collection, import_collection
from app.core.importer import parse_curl
from app.widgets.collection_tree import CollectionTree
from app.widgets.request_editor import RequestEditor
from app.widgets.request_tabs import RequestTabBar, RequestTabPage
from app.widgets.history_panel import HistoryPanel


class SendWorker(QThread):
    """后台发送请求的工作线程（每个 Worker 独立拥有 HTTPClient 实例，杜绝并发取消串扰）"""
    finished = pyqtSignal(object)  # HTTPResponse

    def __init__(self, request: SavedRequest):
        super().__init__()
        self.client = HTTPClient()
        self.request = request
        self._cancelled = False

    def cancel(self):
        """取消请求：设置标志并关闭底层连接"""
        self._cancelled = True
        self.client.cancel_active()

    def run(self):
        response = self.client.send(self.request, cancel_check=lambda: self._cancelled)
        self.finished.emit(response)


class MainWindow(QMainWindow):
    """应用主窗口"""

    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.db = Database()
        self.logger = get_logger("main_window")
        self.logger.info(f"{APP_NAME} v{APP_VERSION} starting...")
        self.http_client = HTTPClient()
        self._workers = {}  # RequestTabPage -> SendWorker（支持多标签页并发发送）
        self._help_viewer = None
        self._tab_save_timers = {}  # page -> QTimer（防抖保存）

        ThemeManager.set_theme(self.settings.theme)
        I18nManager().language_changed.connect(self._retranslate_ui)

        self._init_ui()
        self._build_menu()
        self._connect_signals()
        self._apply_theme(initial=True)
        self._retranslate_ui()

        # 启动性能优化：瞬间渲染主窗口骨架，首帧后懒加载恢复 tabs
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._restore_tabs)
        # 空闲后静默加载历史记录（切到历史标签亦会立即触发）
        QTimer.singleShot(500, self.history_panel.ensure_loaded)

        # 异步后台静默拉起 Go 引擎（完全脱离主 UI 线程，零卡顿）
        self._prewarm_go_engine()

    def _prewarm_go_engine(self):
        """后台独立线程静默拉起 Go 引擎，不阻塞主 UI 线程渲染与用户操作"""
        import threading
        def _bg():
            try:
                from app.core.go_engine import GoEngineManager
                GoEngineManager.get_instance().ensure_started()
            except Exception as e:
                self.logger.warning(f"Go 引擎后台预热提示: {e}")
        threading.Thread(target=_bg, daemon=True, name="GoPrewarmThread").start()

    def showEvent(self, event):
        super().showEvent(event)
        try:
            if sys.platform == "win32":
                from app.core.win_utils import apply_windows_taskbar_icon
                apply_windows_taskbar_icon(self)
        except Exception:
            pass

    # ─── 初始化 ───────────────────────────────────────────────

    def _init_ui(self):
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        from app.config.themes import get_app_icon
        app_icon = get_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ─── 左侧面板 ───────────────────────────────────────
        self.left_panel = QWidget()
        self.left_panel.setObjectName("leftPanel")
        self.left_panel.setMinimumWidth(180)
        self.left_panel.setMaximumWidth(900)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.left_tabs = QTabWidget()
        self.left_tabs.setObjectName("leftTabs")

        self.collection_tree = CollectionTree()
        self.left_tabs.addTab(self.collection_tree, "📁 集合")

        self.history_panel = HistoryPanel()
        self.left_tabs.addTab(self.history_panel, "🕒 历史")

        left_layout.addWidget(self.left_tabs)

        # ─── 右侧面板 ───────────────────────────────────────
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.request_tabs = RequestTabBar()
        right_layout.addWidget(self.request_tabs)

        # 标签页恢复在 _restore_tabs() 中处理（可能恢复上次未关闭的 tab）

        # ─── 水平分割器 (可自由拖动调整功能区大小) ─────────────
        self.horizontal_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.horizontal_splitter.addWidget(self.left_panel)
        self.horizontal_splitter.addWidget(right_panel)
        self.horizontal_splitter.setChildrenCollapsible(False)
        self.horizontal_splitter.setStretchFactor(0, 0)
        self.horizontal_splitter.setStretchFactor(1, 1)

        saved_left_w = self.settings.get("left_panel_width", 280)
        try:
            saved_left_w = int(saved_left_w)
        except Exception:
            saved_left_w = 280
        saved_left_w = max(180, min(900, saved_left_w))
        self.horizontal_splitter.setSizes([saved_left_w, max(600, 1400 - saved_left_w)])
        self.horizontal_splitter.splitterMoved.connect(self._on_left_splitter_moved)

        main_layout.addWidget(self.horizontal_splitter)

        # ─── 状态栏 ─────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(f"{APP_NAME} v{APP_VERSION} - 离线 API 请求管理工具")
        # 隐藏状态栏（移除底部蓝色条）
        self.status_bar.hide()

    def _build_menu(self):
        """构建菜单栏"""
        menubar = self.menuBar()

        # ─── 文件菜单 ───────────────────────────────────────
        self.file_menu = menubar.addMenu("文件(&F)")

        self.act_new_collection = QAction("新建集合", self)
        self.act_new_collection.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.act_new_collection.triggered.connect(self.collection_tree._on_add_collection)
        self.file_menu.addAction(self.act_new_collection)

        self.act_new_request = QAction("新建请求", self)
        self.act_new_request.setShortcut(QKeySequence("Ctrl+N"))
        self.act_new_request.triggered.connect(self._on_menu_new_request)
        self.file_menu.addAction(self.act_new_request)

        self.file_menu.addSeparator()

        self.act_import = QAction("导入集合...", self)
        self.act_import.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self.act_import.triggered.connect(self._on_import_collection)
        self.file_menu.addAction(self.act_import)

        self.act_import_postman = QAction("导入 Postman 集合...", self)
        self.act_import_postman.triggered.connect(self._on_import_postman)
        self.file_menu.addAction(self.act_import_postman)

        self.act_import_curl = QAction("从 cURL 导入...", self)
        self.act_import_curl.setShortcut(QKeySequence("Ctrl+Shift+V"))
        self.act_import_curl.triggered.connect(self._on_import_curl)
        self.file_menu.addAction(self.act_import_curl)

        self.file_menu.addSeparator()

        self.act_export = QAction("导出集合...", self)
        self.act_export.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.act_export.triggered.connect(self._on_export_collection)
        self.file_menu.addAction(self.act_export)

        self.file_menu.addSeparator()

        self.act_quit = QAction("退出", self)
        self.act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        self.act_quit.triggered.connect(self.close)
        self.file_menu.addAction(self.act_quit)

        # ─── 编辑菜单 ───────────────────────────────────────
        self.edit_menu = menubar.addMenu("编辑(&E)")

        self.act_save = QAction("保存请求", self)
        self.act_save.setShortcut(QKeySequence("Ctrl+S"))
        self.act_save.triggered.connect(self._on_save_request)
        self.edit_menu.addAction(self.act_save)

        self.act_save_as = QAction("请求另存为...", self)
        self.act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.act_save_as.triggered.connect(self._on_save_request_as)
        self.edit_menu.addAction(self.act_save_as)

        self.edit_menu.addSeparator()

        self.act_global_headers = QAction("全局请求头...", self)
        self.act_global_headers.setShortcut(QKeySequence("Ctrl+Shift+H"))
        self.act_global_headers.triggered.connect(self._on_open_global_headers)
        self.edit_menu.addAction(self.act_global_headers)

        self.act_global_proxy = QAction("全局代理配置...", self)
        self.act_global_proxy.triggered.connect(self._on_open_global_proxy)
        self.edit_menu.addAction(self.act_global_proxy)

        self.act_settings = QAction("设置...", self)
        self.act_settings.triggered.connect(self._on_open_settings)
        self.edit_menu.addAction(self.act_settings)

        # ─── Mock 中心菜单（紧邻文件与编辑菜单） ────────────────────
        self.mock_menu = menubar.addMenu("Mock中心(&M)")

        self.act_mock_center = QAction("Mock 服务中心...", self)
        self.act_mock_center.setShortcut(QKeySequence("Ctrl+Alt+M"))
        self.act_mock_center.triggered.connect(self._on_open_mock_center)
        self.mock_menu.addAction(self.act_mock_center)

        # ─── 工具菜单 ───────────────────────────────────────
        self.tools_menu = menubar.addMenu("工具(&T)")

        self.act_stress_test = QAction("高并发性能压测...", self)
        self.act_stress_test.setShortcut(QKeySequence("Ctrl+Alt+S"))
        self.act_stress_test.triggered.connect(self._on_open_stress_test)
        self.tools_menu.addAction(self.act_stress_test)

        self.act_sniffer = QAction("页面接口智能嗅探...", self)
        self.act_sniffer.setShortcut(QKeySequence("Ctrl+Alt+P"))
        self.act_sniffer.triggered.connect(self._on_open_page_sniffer)
        self.tools_menu.addAction(self.act_sniffer)

        # ─── 视图菜单 ───────────────────────────────────────
        self.view_menu = menubar.addMenu("视图(&V)")

        self.act_theme = QAction("切换主题", self)
        self.act_theme.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self.act_theme.triggered.connect(self._on_toggle_theme)
        self.view_menu.addAction(self.act_theme)

        # ─── 语言菜单 ───────────────────────────────────────
        self.lang_menu = menubar.addMenu("语言(&L)")
        self.lang_group = QActionGroup(self)
        self.lang_group.setExclusive(True)

        self.act_lang_zh = QAction("简体中文", self, checkable=True)
        self.act_lang_zh.setActionGroup(self.lang_group)
        self.act_lang_zh.triggered.connect(lambda: I18nManager().set_language("zh"))
        self.lang_menu.addAction(self.act_lang_zh)

        self.act_lang_en = QAction("English", self, checkable=True)
        self.act_lang_en.setActionGroup(self.lang_group)
        self.act_lang_en.triggered.connect(lambda: I18nManager().set_language("en"))
        self.lang_menu.addAction(self.act_lang_en)

        # ─── 帮助菜单 ───────────────────────────────────────
        self.help_menu = menubar.addMenu("帮助(&H)")

        self.act_help = QAction("使用说明书", self)
        self.act_help.setShortcut(QKeySequence("Ctrl+F1"))
        self.act_help.triggered.connect(self._on_show_help)
        self.help_menu.addAction(self.act_help)

        self.act_open_logs = QAction("打开日志目录", self)
        self.act_open_logs.triggered.connect(self._on_open_log_dir)
        self.help_menu.addAction(self.act_open_logs)

        self.help_menu.addSeparator()

        self.act_about = QAction("关于", self)
        self.act_about.triggered.connect(self._on_about)
        self.help_menu.addAction(self.act_about)

    def _retranslate_ui(self):
        """动态刷新界面语言"""
        current_lang = I18nManager().current_language
        self.act_lang_zh.setChecked(current_lang == "zh")
        self.act_lang_en.setChecked(current_lang == "en")

        self.file_menu.setTitle(tr("menu_file"))
        self.act_new_collection.setText(tr("menu_new_collection"))
        self.act_new_request.setText(tr("menu_new_request"))
        self.act_import.setText(tr("menu_import_collection"))
        self.act_import_postman.setText(tr("menu_import_postman"))
        self.act_import_curl.setText(tr("menu_import_curl"))
        self.act_export.setText(tr("menu_export_collection"))
        self.act_quit.setText(tr("menu_quit"))

        self.edit_menu.setTitle(tr("menu_edit"))
        self.act_save.setText(tr("menu_save_request"))
        self.act_save_as.setText(tr("menu_save_request_as", "请求另存为..."))
        self.act_global_headers.setText(tr("menu_global_headers"))
        self.act_global_proxy.setText(tr("menu_global_proxy", "全局代理配置..."))
        self.act_settings.setText(tr("menu_settings"))

        self.mock_menu.setTitle(tr("menu_mock", "Mock中心(&M)"))
        self.act_mock_center.setText(tr("menu_mock_center", "Mock 服务中心..."))

        self.tools_menu.setTitle(tr("menu_tools", "工具(&T)"))
        self.act_stress_test.setText(tr("menu_stress_test", "高并发性能压测..."))
        self.act_sniffer.setText(tr("menu_sniffer", "页面接口智能嗅探..."))

        self.view_menu.setTitle(tr("menu_view"))
        self.act_theme.setText(tr("menu_toggle_theme"))

        self.lang_menu.setTitle(tr("menu_language"))
        self.act_lang_zh.setText(tr("menu_lang_zh"))
        self.act_lang_en.setText(tr("menu_lang_en"))

        self.help_menu.setTitle(tr("menu_help"))
        self.act_help.setText(tr("menu_doc"))
        self.act_open_logs.setText(tr("menu_open_logs", "打开日志目录"))
        self.act_about.setText(tr("menu_about"))

        self.left_tabs.setTabText(0, tr("tab_collections"))
        self.left_tabs.setTabText(1, tr("tab_history"))
        self.history_panel.search_input.setPlaceholderText(tr("placeholder_search_history"))
        self.history_panel.btn_clear.setToolTip(tr("btn_clear_history"))
        self.collection_tree.btn_add.setToolTip(tr("btn_add_collection"))
        if hasattr(self.collection_tree, "retranslate_ui"):
            self.collection_tree.retranslate_ui()

        # 刷新所有标签页与子组件文本
        for i in range(self.request_tabs.tab_widget.count()):
            page = self.request_tabs.tab_widget.widget(i)
            if hasattr(page, "retranslate_ui"):
                page.retranslate_ui()

    def _on_open_global_headers(self):
        """打开全局请求头对话框"""
        from app.widgets.global_headers_dialog import GlobalHeadersDialog
        dialog = GlobalHeadersDialog(self)
        dialog.headers_updated.connect(self._on_global_headers_updated)
        dialog.exec()

    def _on_open_global_proxy(self):
        """打开全局代理配置对话框"""
        from app.widgets.proxy_dialog import GlobalProxyDialog
        dialog = GlobalProxyDialog(self)
        dialog.exec()

    def _on_left_splitter_moved(self, pos: int, index: int):
        """拖动左侧功能区边界时持久化宽度"""
        w = self.left_panel.width()
        if w >= 180:
            self.settings.set("left_panel_width", w)

    def _connect_signals(self):
        """连接信号与槽"""
        self.collection_tree.request_selected.connect(self._on_request_selected)
        self.history_panel.history_selected.connect(self._on_history_selected)
        self.left_tabs.currentChanged.connect(self._on_left_tabs_changed)
        self.request_tabs.new_tab_requested.connect(self._on_menu_new_request)
        self.request_tabs.duplicate_tab_requested.connect(self._on_duplicate_tab)
        self.request_tabs.set_timeout_requested.connect(self._on_set_tab_timeout)
        self.request_tabs.tab_closed.connect(self._on_tab_closed)

    def _on_left_tabs_changed(self, index: int):
        """左侧面板选项卡切换：若切换到历史记录（index==1），确保历史数据已加载"""
        if index == 1 and hasattr(self.history_panel, "ensure_loaded"):
            self.history_panel.ensure_loaded()

    # ─── 多标签页管理 ─────────────────────────────────────────

    @property
    def request_editor(self) -> RequestEditor:
        """当前标签页的请求编辑器"""
        return self.request_tabs.current_page().request_editor

    @property
    def response_viewer(self):
        """当前标签页的响应查看器"""
        return self.request_tabs.current_page().response_viewer

    def _create_new_tab(self, request_id=None) -> RequestTabPage:
        """新建标签页并连接信号"""
        page = RequestTabPage()
        page.request_id = request_id
        self.request_tabs.add_page(page)
        page.request_editor.send_requested.connect(self._on_send_request)
        page.request_editor.cancel_requested.connect(lambda p=page: self._on_cancel_request(p))
        page.save_requested.connect(self._on_save_request)
        page.request_name_input.editingFinished.connect(
            lambda p=page: self._on_name_committed(p)
        )

        def _on_page_url_changed(_text, p=page):
            self.request_tabs.refresh_title(p)
            p.refresh_name_display()
            self._schedule_tab_save(p)

        page.request_editor.url_input.textChanged.connect(_on_page_url_changed)
        # 连接编辑器内容变化信号，用于自动保存 tab 状态并刷新标签徽章
        def _on_page_method_changed(_text, p=page):
            self.request_tabs.refresh_title(p)
            self._schedule_tab_save(p)

        page.request_editor.method_combo.currentTextChanged.connect(_on_page_method_changed)
        page.request_editor.body_edit.textChanged.connect(
            lambda *_: self._schedule_tab_save(page))
        page.request_editor.body_type_combo.currentTextChanged.connect(
            lambda *_: self._schedule_tab_save(page))
        page.request_editor.headers_editor.table.cellChanged.connect(
            lambda *_: self._schedule_tab_save(page))
        page.request_editor.params_editor.table.cellChanged.connect(
            lambda *_: self._schedule_tab_save(page))
        page.request_editor.formdata_editor.table.cellChanged.connect(
            lambda *_: self._schedule_tab_save(page))
        page.request_editor.global_headers_updated.connect(self._on_global_headers_updated)
        page.apply_theme(ThemeManager.current())
        page.request_editor._timeout = self.settings.default_timeout
        page.refresh_name_display()
        return page

    def _on_global_headers_updated(self):
        """当任意 Tab 修改了全局请求头时，广播刷新所有已打开的 Tab"""
        for i in range(self.request_tabs.tab_widget.count()):
            page = self.request_tabs.tab_widget.widget(i)
            if isinstance(page, RequestTabPage):
                page.request_editor._reload_global_headers()

    def _page_of_editor(self, editor) -> RequestTabPage:
        """查找指定编辑器所在的标签页"""
        for i in range(self.request_tabs.tab_widget.count()):
            page = self.request_tabs.tab_widget.widget(i)
            if isinstance(page, RequestTabPage) and page.request_editor is editor:
                return page
        return self.request_tabs.current_page()

    def _on_duplicate_tab(self, tab_index: int):
        """复制标签页到新标签页"""
        src_page = self.request_tabs.tab_widget.widget(tab_index)
        if not isinstance(src_page, RequestTabPage):
            return
        src_editor = src_page.request_editor
        # 构建当前请求数据
        req = src_editor.build_request()
        # 创建新标签页并填充相同内容
        new_page = self._create_new_tab()
        new_editor = new_page.request_editor
        new_editor.method_combo.setCurrentText(req.method)
        new_editor.url_input.setText(req.url)
        new_editor.headers_editor.set_data(req.headers)
        new_editor.params_editor.set_data(req.params)
        new_editor.body_type_combo.setCurrentText(req.body_type)
        if req.body_type == "form":
            new_editor.formdata_editor.table.setRowCount(0)
            for line in req.body_content.split('\n'):
                if '=' in line:
                    k, v = line.split('=', 1)
                    new_editor.formdata_editor._add_row(True, k.strip(), v.strip())
            new_editor.formdata_editor._add_empty_row()
        else:
            new_editor.body_edit.setPlainText(req.body_content)
        new_editor.auth_type_combo.setCurrentText(req.auth_type)
        if req.auth_type == "basic":
            new_editor.auth_username.setText(req.auth_config.get("username", ""))
            new_editor.auth_password.setText(req.auth_config.get("password", ""))
        elif req.auth_type == "bearer":
            new_editor.auth_token.setText(req.auth_config.get("token", ""))
        elif req.auth_type == "apikey":
            new_editor.auth_apikey_key.setText(req.auth_config.get("key", ""))
            new_editor.auth_apikey_value.setText(req.auth_config.get("value", ""))
        # 复制请求名和超时时间与代理
        new_editor._request_name = req.name if req.name != "新建请求" else ""
        new_editor._timeout = req.timeout
        new_editor.proxy_config = dict(req.proxy) if getattr(req, "proxy", None) else {}
        new_editor._current_request_id = None  # 副本不关联原请求 ID
        new_editor._collection_id = ""  # 副本不保存到集合中
        new_page.request_id = None
        new_page.refresh_proxy_button_state()
        new_page.refresh_name_display()
        self.request_tabs.refresh_title(new_page)

    def _on_open_settings(self):
        """打开设置对话框"""
        from app.widgets.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()

    def _on_set_tab_timeout(self, tab_index: int):
        """通过右键菜单设置标签页超时时间"""
        page = self.request_tabs.tab_widget.widget(tab_index)
        if not isinstance(page, RequestTabPage):
            return
        editor = page.request_editor
        current_timeout = getattr(editor, '_timeout', 0)
        # 弹出输入框，0 表示无超时
        value, ok = QInputDialog.getInt(
            self, "设置超时时间",
            "请输入超时时间（毫秒）\n0 表示无超时限制:",
            current_timeout, 0, 999999, 1000,
        )
        if ok:
            editor._timeout = value
            self._save_tab_state(self.request_tabs.tab_widget.widget(tab_index))

    # ─── Tab 状态持久化 ──────────────────────────────────────────

    def _on_tab_closed(self, tab_id: str):
        """标签页关闭时删除持久化记录"""
        self.db.remove_open_tab(tab_id)
        self._tab_save_timers = {
            p: t for p, t in self._tab_save_timers.items()
            if getattr(p, 'tab_id', None) is not None
        }

    def _schedule_tab_save(self, page: RequestTabPage):
        """防抖保存：用户停止输入 500ms 后写入临时表"""
        # 启动恢复阶段不重复触发数据库回写
        if getattr(self, "_restoring_tabs", False):
            return
        from PyQt6.QtCore import QTimer
        if not isinstance(page, RequestTabPage):
            return
        timer = self._tab_save_timers.get(page)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(500)
            timer.timeout.connect(lambda p=page: self._save_tab_state(p))
            self._tab_save_timers[page] = timer
        timer.start()

    def _save_tab_state(self, page: RequestTabPage):
        """将标签页当前状态序列化写入 open_tabs 临时表"""
        if getattr(self, "_restoring_tabs", False):
            return
        if not isinstance(page, RequestTabPage):
            return
        from PyQt6 import sip
        if sip.isdeleted(page):
            return
        editor = page.request_editor
        url = editor.url_input.text().strip()
        name = editor._request_name
        params_data = editor.params_editor.get_data()
        headers_data = editor.headers_editor.get_data()
        if not url and not name and not params_data and not headers_data:
            return
        req = editor.build_request()
        tab_index = self.request_tabs.tab_widget.indexOf(page)
        self.db.save_open_tab(
            tab_id=page.tab_id,
            request_id=page.request_id or "",
            collection_id=req.collection_id or "",
            name=name,
            method=req.method,
            url=req.url,
            headers=req.headers_json(),
            params=req.params_json(),
            body_type=req.body_type,
            body_content=req.body_content,
            auth_type=req.auth_type,
            auth_config=req.auth_config_json(),
            timeout=req.timeout,
            sort_order=tab_index,
            pre_script=req.pre_script_json(),
            post_script=req.post_script_json(),
            proxy=req.proxy_json(),
        )

    def _restore_single_tab(self, data: dict) -> RequestTabPage:
        """还原单个标签页的数据与状态"""
        page = self._create_new_tab()
        page.tab_id = data["tab_id"]
        page.request_id = data.get("request_id") or None
        editor = page.request_editor
        editor._request_name = data.get("name", "")
        editor._timeout = data.get("timeout", 0)
        editor._current_request_id = data.get("request_id") or None
        editor.method_combo.setCurrentText(data.get("method", "GET"))
        editor.url_input.setText(data.get("url", ""))
        # Headers
        try:
            raw_h = data.get("headers")
            headers = json.loads(raw_h) if isinstance(raw_h, str) else (raw_h or [])
            from app.core.models import HeaderItem
            if isinstance(headers, dict):
                editor.headers_editor.set_data([HeaderItem(key=str(k), value=str(v)) for k, v in headers.items()])
            elif isinstance(headers, list):
                editor.headers_editor.set_data(
                    [HeaderItem.from_dict(h) if isinstance(h, dict) else h for h in headers]
                )
        except Exception:
            pass
        # Params
        try:
            raw_p = data.get("params")
            params = json.loads(raw_p) if isinstance(raw_p, str) else (raw_p or [])
            from app.core.models import ParamItem
            if isinstance(params, dict):
                editor.params_editor.set_data([ParamItem(key=str(k), value=str(v)) for k, v in params.items()])
            elif isinstance(params, list):
                editor.params_editor.set_data(
                    [ParamItem.from_dict(p) if isinstance(p, dict) else p for p in params]
                )
        except Exception:
            pass
        # Body
        editor.body_type_combo.setCurrentText(data.get("body_type") or "none")
        body_content = data.get("body_content") or ""
        if data.get("body_type") == "form":
            editor.formdata_editor.table.setRowCount(0)
            for line in body_content.split('\n'):
                if '=' in line:
                    k, v = line.split('=', 1)
                    editor.formdata_editor._add_row(True, k.strip(), v.strip())
            editor.formdata_editor._add_empty_row()
        elif data.get("body_type") == "binary":
            editor.binary_file_input.setText(body_content)
        else:
            editor.body_edit.setPlainText(body_content)
        # Auth
        editor.auth_type_combo.setCurrentText(data.get("auth_type") or "none")
        try:
            from app.core.security import decrypt_auth_config
            auth_conf = decrypt_auth_config(data.get("auth_config") or "{}")
        except Exception:
            auth_conf = {}
        if data.get("auth_type") == "basic":
            editor.auth_username.setText(auth_conf.get("username", ""))
            editor.auth_password.setText(auth_conf.get("password", ""))
        elif data.get("auth_type") == "bearer":
            editor.auth_token.setText(auth_conf.get("token", ""))
        elif data.get("auth_type") == "apikey":
            editor.auth_apikey_key.setText(auth_conf.get("key", ""))
            editor.auth_apikey_value.setText(auth_conf.get("value", ""))
        # 前置与后置处理
        try:
            pre_s = json.loads(data.get("pre_script") or "{}")
            if hasattr(editor, "pre_processor_widget"):
                editor.pre_processor_widget.set_config(pre_s)
        except Exception:
            pass
        try:
            post_s = json.loads(data.get("post_script") or "{}")
            if hasattr(editor, "post_processor_widget"):
                editor.post_processor_widget.set_config(post_s)
        except Exception:
            pass
        # 恢复接口代理配置
        try:
            proxy_c = json.loads(data.get("proxy") or "{}")
            editor.proxy_config = proxy_c if isinstance(proxy_c, dict) else {}
            if hasattr(page, "refresh_proxy_button_state"):
                page.refresh_proxy_button_state()
        except Exception:
            pass
        page.refresh_name_display()
        self.request_tabs.refresh_title(page)

        # 立即应用主题与国际化
        t = ThemeManager.current()
        page.apply_theme(t)
        if hasattr(page, "retranslate_ui"):
            page.retranslate_ui()

        return page

    def _restore_tabs(self):
        """启动时从 open_tabs 临时表恢复上次未关闭的标签页（渐进式恢复：优先加载首个标签页，其余标签页异步分帧载入）"""
        self._restoring_tabs = True
        try:
            tabs_data = self.db.get_open_tabs()
            if tabs_data:
                # 立即恢复第 1 个标签页（让主界面瞬间就绪可见）
                first_page = self._restore_single_tab(tabs_data[0])
                self.request_tabs.tab_widget.setCurrentWidget(first_page)

                # 剩余标签页加入待加载队列异步分帧恢复，不阻塞首帧呈现
                self._pending_tabs = list(tabs_data[1:])
                if self._pending_tabs:
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(25, self._restore_next_pending_tab)
                else:
                    self._restoring_tabs = False
            else:
                if self.request_tabs.tab_widget.count() == 0:
                    page = self._create_new_tab()
                    t = ThemeManager.current()
                    page.apply_theme(t)
                    if hasattr(page, "retranslate_ui"):
                        page.retranslate_ui()
                self._restoring_tabs = False
        except Exception as e:
            get_logger().error(f"恢复标签页异常: {e}", exc_info=True)
            if self.request_tabs.tab_widget.count() == 0:
                self._create_new_tab()
            self._restoring_tabs = False

    def _restore_next_pending_tab(self):
        """渐进式分帧恢复下一个待处理标签页"""
        if not hasattr(self, "_pending_tabs") or not self._pending_tabs:
            self._restoring_tabs = False
            return
        current_idx = self.request_tabs.tab_widget.currentIndex()
        data = self._pending_tabs.pop(0)
        try:
            self._restore_single_tab(data)
            # 保持用户当前正在交互的标签页索引不变
            if 0 <= current_idx < self.request_tabs.tab_widget.count():
                self.request_tabs.tab_widget.setCurrentIndex(current_idx)
        except Exception as e:
            get_logger().warning(f"恢复单个标签页失败: {e}")

        if self._pending_tabs:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(25, self._restore_next_pending_tab)
        else:
            self._restoring_tabs = False

    # ─── 主题 ─────────────────────────────────────────────────

    def _apply_theme(self, initial: bool = False):
        """应用当前主题到所有组件"""
        t = ThemeManager.current()

        self.setStyleSheet(generate_main_stylesheet(t))

        self.left_panel.setStyleSheet(
            f"#leftPanel {{ background-color: {t.bg_sidebar}; }}"
        )

        self.left_tabs.setStyleSheet(generate_left_tabs_stylesheet(t))

        self.status_bar.setStyleSheet(
            f"background-color: {t.statusbar_bg}; color: {t.statusbar_text}; font-size: 12px;"
        )

        self.collection_tree.apply_theme(t)
        self.request_tabs.apply_theme(t)
        for i in range(self.request_tabs.tab_widget.count()):
            page = self.request_tabs.tab_widget.widget(i)
            if isinstance(page, RequestTabPage):
                page.apply_theme(t)
        self.history_panel.apply_theme(t)

        # 仅在非初始启动（例如用户手动切换主题）时重建列表，避免启动时重复全量刷新树形
        if not initial:
            self.collection_tree.refresh_tree()
            self.history_panel.refresh_history()

    def _on_toggle_theme(self):
        """切换主题"""
        new_name = ThemeManager.toggle()
        self.settings.theme = new_name
        self._apply_theme()
        self.status_bar.showMessage(
            f"已切换到{'暗色' if new_name == 'dark' else '亮色'}主题", 3000
        )

    # ─── 菜单动作 ─────────────────────────────────────────────

    def _on_open_stress_test(self):
        """菜单：打开高并发压测面板 (Go 协程引擎)"""
        page = self.request_tabs.current_page()
        req = page.request_editor.build_request() if page else SavedRequest()
        if not req.url:
            QMessageBox.warning(self, "无法压测", "当前标签页未输入有效 URL，请先输入请求 URL")
            return
        from app.widgets.stress_dialog import StressDialog
        if hasattr(self, "_stress_dialog") and self._stress_dialog and self._stress_dialog.isVisible():
            self._stress_dialog.raise_()
            self._stress_dialog.activateWindow()
            return
        self._stress_dialog = StressDialog(req, self)
        self._stress_dialog.show()

    def _on_open_page_sniffer(self):
        """菜单：打开页面接口智能嗅探面板"""
        page = self.request_tabs.current_page()
        current_url = page.request_editor.url_input.text().strip() if page else ""
        self._on_open_page_sniffer_for_url(current_url)

    def _on_open_page_sniffer_for_url(self, url: str = ""):
        """打开页面接口智能嗅探面板（非模态，保持嗅探面板与主窗口同时可用）"""
        from app.widgets.sniffer_dialog import PageSnifferDialog
        if hasattr(self, "_sniffer_dialog") and self._sniffer_dialog and self._sniffer_dialog.isVisible():
            if url:
                self._sniffer_dialog.edit_url.setText(url)
            self._sniffer_dialog.raise_()
            self._sniffer_dialog.activateWindow()
            return
        self._sniffer_dialog = PageSnifferDialog(url, self)
        self._sniffer_dialog.import_request_requested.connect(self._on_import_sniffed_request)
        self._sniffer_dialog.show()

    def _on_import_sniffed_request(self, req_data):
        """从智能嗅探面板导入 API 到新标签页进行独立调试（完整保留请求头、参数、载荷与代理）"""
        from app.core.models import SavedRequest

        if isinstance(req_data, SavedRequest):
            req = req_data
        elif isinstance(req_data, dict):
            req = SavedRequest.from_dict(req_data)
        elif hasattr(req_data, "method"):
            req = req_data
        else:
            return

        page = self._create_new_tab()
        editor = page.request_editor
        editor.load_from_saved_request(req)
        page.refresh_name_display()
        if hasattr(page, "refresh_proxy_button_state"):
            page.refresh_proxy_button_state()
        self.request_tabs.refresh_title(page)
        self.request_tabs.tab_widget.setCurrentWidget(page)

    def _on_menu_new_request(self):
        """菜单：新建请求（打开新标签页）"""
        page = self._create_new_tab()
        page.request_editor.url_input.setFocus()

    def _on_save_request(self):
        """保存当前标签页的请求到集合（状态栏已隐藏，改用弹窗反馈）"""
        sender = self.sender()
        if isinstance(sender, RequestTabPage):
            page = sender
        elif isinstance(sender, RequestEditor):
            page = self._page_of_editor(sender)
        else:
            page = self.request_tabs.current_page()
        if page is None:
            return
        req = page.request_editor.build_request()
        if not req.url:
            QMessageBox.warning(self, "无法保存", "请先输入请求 URL")
            return

        # 如果编辑器已关联集合 ID，直接使用；否则弹窗选择
        editor_collection_id = getattr(page.request_editor, '_collection_id', '')
        if editor_collection_id:
            req.collection_id = editor_collection_id

        if not req.collection_id:
            from app.widgets.save_request_dialog import SaveRequestDialog
            dlg = SaveRequestDialog(self, current_name=req.name or "新建请求", default_collection_id=editor_collection_id)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            target_cid = dlg.get_selected_collection_id()
            if not target_cid:
                QMessageBox.warning(self, "无法保存", "请选择要保存到的目标文件夹")
                return
            req.collection_id = target_cid
            req.name = dlg.get_request_name()
            page.request_editor._request_name = req.name
            page.refresh_name_display()

        if req.id:
            self.db.update_request(req)
            page.request_id = req.id
        else:
            saved = self.db.create_request(req)
            page.request_editor._current_request_id = saved.id
            page.request_id = saved.id
        # 同步 collection_id 到编辑器，后续保存直接更新
        page.request_editor._collection_id = req.collection_id
        self.collection_tree.refresh_tree()
        self.request_tabs.refresh_title(page)
        # 保存到集合后，同步更新 open_tabs 临时表
        self._save_tab_state(page)
        QMessageBox.information(self, "保存成功", "请求已保存")

    def _on_save_request_as(self):
        """当前请求另存为新请求（支持选择多级文件夹）"""
        page = self.request_tabs.current_page()
        if page is None:
            return
        req = page.request_editor.build_request()
        if not req.url:
            QMessageBox.warning(self, "无法保存", "请先输入请求 URL")
            return

        from app.widgets.save_request_dialog import SaveRequestDialog
        dlg = SaveRequestDialog(
            self,
            current_name=f"{req.name or '新建请求'} - 副本",
            default_collection_id=getattr(page.request_editor, '_collection_id', '')
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        target_cid = dlg.get_selected_collection_id()
        if not target_cid:
            QMessageBox.warning(self, "无法保存", "请选择要保存到的目标文件夹")
            return

        req.id = ""
        req.collection_id = target_cid
        req.name = dlg.get_request_name()
        saved = self.db.create_request(req)
        page.request_editor._current_request_id = saved.id
        page.request_id = saved.id
        page.request_editor._collection_id = target_cid
        page.request_editor._request_name = req.name
        page.refresh_name_display()
        self.collection_tree.refresh_tree()
        self.request_tabs.refresh_title(page)
        self._save_tab_state(page)
        QMessageBox.information(self, "保存成功", f"请求已另存为 [{req.name}]")

    def _on_open_mock_center(self):
        """打开 Mock 服务中心面板"""
        from app.widgets.mock_center_dialog import MockCenterDialog
        if hasattr(self, "_mock_dialog") and self._mock_dialog and self._mock_dialog.isVisible():
            self._mock_dialog.raise_()
            self._mock_dialog.activateWindow()
            return
        self._mock_dialog = MockCenterDialog(self)
        self._mock_dialog.show()

    def _on_name_committed(self, page: RequestTabPage):
        """请求名编辑完成（回车或失焦），不弹框直接生效"""
        if page is None:
            return
        editor = page.request_editor
        new_name = page.request_name_input.text().strip()

        # 非铅笔触发的编辑、或内容未改动：仅恢复展示态（名称/URL 回退）
        unchanged = new_name == page._edit_start_text.strip()
        if not page._name_editing or unchanged or new_name == editor._request_name:
            page.refresh_name_display()
            return

        editor._request_name = new_name
        self.request_tabs.refresh_title(page)
        page.refresh_name_display()
        self._schedule_tab_save(page)

        # 已保存的请求：同步新名称到数据库与集合树
        if page.request_id:
            req = editor.build_request()
            if req.url:
                self.db.update_request(req)
                self.collection_tree.refresh_tree()

    def _on_import_collection(self):
        """菜单：导入集合（自动检测 PostManage / Postman 格式）"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入集合", "", "JSON 文件 (*.json);;所有文件 (*)"
        )
        if path:
            try:
                import_collection(path, self.db)
                self.collection_tree.refresh_tree()
                self.status_bar.showMessage("集合导入成功", 3000)
            except Exception as e:
                QMessageBox.warning(self, "导入失败", str(e))

    def _on_import_postman(self):
        """菜单：导入 Postman Collection"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 Postman 集合", "", "JSON 文件 (*.json);;所有文件 (*)"
        )
        if path:
            try:
                import_collection(path, self.db)
                self.collection_tree.refresh_tree()
                self.status_bar.showMessage("Postman 集合导入成功", 3000)
            except Exception as e:
                QMessageBox.warning(self, "导入失败", str(e))

    def _on_import_curl(self):
        """菜单：从 cURL 命令导入"""
        text, ok = QInputDialog.getMultiLineText(
            self, "从 cURL 导入",
            "粘贴 cURL 命令:",
            "curl https://api.example.com/users"
        )
        if ok and text.strip():
            try:
                req = parse_curl(text.strip())
                # 在新标签页中加载解析结果
                page = self._create_new_tab()
                editor = page.request_editor
                editor.clear_editor()
                editor.method_combo.setCurrentText(req.method)
                editor.url_input.setText(req.url)
                editor.headers_editor.set_data(req.headers)
                editor.params_editor.set_data(req.params)
                editor.body_type_combo.setCurrentText(req.body_type)
                if req.body_type == "form":
                    # form-data 内容填入 Form 表格（而非 body 文本框）
                    editor.formdata_editor.table.setRowCount(0)
                    for line in req.body_content.split('\n'):
                        if '=' in line:
                            k, v = line.split('=', 1)
                            editor.formdata_editor._add_row(True, k.strip(), v.strip())
                    editor.formdata_editor._add_empty_row()
                else:
                    editor.body_edit.setPlainText(req.body_content)
                editor.auth_type_combo.setCurrentText(req.auth_type)

                if req.auth_type == "basic":
                    editor.auth_username.setText(req.auth_config.get("username", ""))
                    editor.auth_password.setText(req.auth_config.get("password", ""))
                elif req.auth_type == "bearer":
                    editor.auth_token.setText(req.auth_config.get("token", ""))
                elif req.auth_type == "apikey":
                    editor.auth_apikey_key.setText(req.auth_config.get("key", ""))
                    editor.auth_apikey_value.setText(req.auth_config.get("value", ""))

                page.response_viewer.clear()
                self.request_tabs.refresh_title(page)
                self.status_bar.showMessage("cURL 命令已解析并加载到编辑器", 3000)
            except Exception as e:
                QMessageBox.warning(self, "解析失败", f"cURL 命令解析出错:\n{e}")

    def _on_export_collection(self):
        """菜单：导出集合"""
        collections = self.db.get_all_collections()
        if not collections:
            self.status_bar.showMessage("没有可导出的集合", 3000)
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "导出集合", "collections.json", "JSON 文件 (*.json)"
        )
        if path:
            try:
                export_collection(path, self.db)
                self.status_bar.showMessage("集合已导出", 3000)
            except Exception as e:
                QMessageBox.warning(self, "导出失败", str(e))

    def _on_show_help(self):
        """显示帮助文档"""
        if self._help_viewer is None:
            from app.widgets.help_viewer import HelpViewer
            self._help_viewer = HelpViewer(self)
        self._help_viewer.show()
        self._help_viewer.raise_()
        self._help_viewer.activateWindow()

    def _on_about(self):
        """关于对话框"""
        QMessageBox.about(
            self, f"关于 {APP_NAME}",
            f"<h2>{APP_NAME} v{APP_VERSION}</h2>"
            f"<p>离线 API 请求管理工具</p>"
            f"<p>轻量级桌面 API 请求管理客户端</p>"
            f"<p>所有数据保存在本地，无需联网同步</p>"
            f"<hr>"
            f"<p><b>作者：</b>{APP_AUTHOR}</p>"
            f"<p><b>许可协议：</b>{APP_LICENSE}</p>"
            f"<p>{APP_COPYRIGHT}</p>"
            f"<hr>"
            f"<p><b>快捷键：</b></p>"
            f"<p>Ctrl+Enter — 发送请求</p>"
            f"<p>Ctrl+S — 保存请求</p>"
            f"<p>Ctrl+F1 — 帮助文档</p>"
            f"<p>Ctrl+Shift+T — 切换主题</p>"
        )

    # ─── 请求处理 ─────────────────────────────────────────────

    def _on_request_selected(self, request_id: str):
        """从集合树选中一个请求：已打开则切换，否则新开标签页"""
        page = self.request_tabs.find_page_by_request_id(request_id)
        if page is not None:
            self.request_tabs.activate_page(page)
            return
        page = self._create_new_tab(request_id=request_id)
        page.request_editor.load_request(request_id)
        page.refresh_name_display()
        if hasattr(page, "refresh_proxy_button_state"):
            page.refresh_proxy_button_state()
        page.response_viewer.clear()
        self.request_tabs.refresh_title(page)

    def _on_history_selected(self, record: HistoryRecord):
        """从历史面板选中一条记录：在新标签页中打开"""
        page = self._create_new_tab()
        editor = page.request_editor
        editor.clear_editor()
        editor._request_name = getattr(record, "name", "") or ""
        editor.method_combo.setCurrentText(record.method)
        editor.url_input.setText(record.url)
        editor.headers_editor.set_data(record.headers)
        editor.params_editor.set_data(record.params)
        editor.body_type_combo.setCurrentText(record.body_type)
        if record.body_type == "form":
            editor.formdata_editor.table.setRowCount(0)
            for line in (record.body_content or "").split('\n'):
                if '=' in line:
                    k, v = line.split('=', 1)
                    editor.formdata_editor._add_row(True, k.strip(), v.strip())
            editor.formdata_editor._add_empty_row()
        elif record.body_type == "binary":
            editor.binary_file_input.setText(record.body_content or "")
        else:
            editor.body_edit.setPlainText(record.body_content or "")
        page.refresh_name_display()
        if hasattr(page, "refresh_proxy_button_state"):
            page.refresh_proxy_button_state()
        page.response_viewer.clear()
        self.request_tabs.refresh_title(page)

    def _on_open_log_dir(self):
        """打开日志文件夹"""
        import os
        import platform
        from app.config.settings import get_log_dir
        log_dir = get_log_dir()
        try:
            if platform.system() == "Windows":
                os.startfile(log_dir)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", log_dir])
        except Exception as e:
            QMessageBox.warning(self, "打开日志目录失败", f"无法打开日志目录:\n{e}")

    def _on_send_request(self, request: SavedRequest = None):
        """发送请求 / 取消请求（根据按钮状态切换）"""
        sender = self.sender()
        if isinstance(sender, RequestEditor):
            page = self._page_of_editor(sender)
        else:
            page = self.request_tabs.current_page()

        # 如果该页面正在发送中，则取消请求
        worker = self._workers.get(page)
        if worker is not None and worker.isRunning():
            self._on_cancel_request(page)
            return

        # 否则发送新请求
        if request is None:
            return
        if not request.url:
            self.status_bar.showMessage("请输入请求 URL", 3000)
            return

        if request.url and not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', request.url):
            request.url = 'http://' + request.url

        self.logger.info(f"Sending request: {request.method} {request.url}")
        page.request_editor.set_sending_state(True)
        page.response_viewer.clear()  # 发送中清空上一次返回结果
        self.status_bar.showMessage("正在发送请求...")

        worker = SendWorker(request)
        self._workers[page] = worker
        worker.finished.connect(
            lambda resp, p=page: self._on_response_received(resp, p)
        )
        worker.start()

    def _on_cancel_request(self, page: RequestTabPage = None):
        """立即取消指定标签页的请求发送"""
        if page is None:
            sender = self.sender()
            if isinstance(sender, RequestEditor):
                page = self._page_of_editor(sender)
            else:
                page = self.request_tabs.current_page()
        if page is None:
            return

        self.logger.info(f"Cancelling request for tab: {page.tab_id}")

        # 1. 立即重置 UI 发送按钮状态为正常（绿色「发送」）
        page.request_editor.set_sending_state(False)
        self.status_bar.showMessage("请求已取消", 3000)

        # 2. 终止底层 worker 并断开连接
        worker = self._workers.pop(page, None)
        if worker is not None:
            try:
                worker.finished.disconnect()
            except Exception:
                pass
            worker.cancel()

        # 3. 响应查看器立即呈现已取消
        page.response_viewer.set_response(HTTPResponse(error="请求已取消"))

    def _on_response_received(self, response: HTTPResponse, page: RequestTabPage):
        """收到响应（写回对应标签页）"""
        from PyQt6 import sip
        page_alive = not sip.isdeleted(page)
        cancelled = response.error == "请求已取消"

        if page_alive:
            page.response_viewer.set_response(response)
            page.request_editor.set_sending_state(False)
            # 若服务器返回了 Cookie，自动合并到当前页的 Cookie 管理器
            if getattr(response, "cookies", None) and hasattr(page.request_editor, "cookie_manager"):
                page.request_editor.cookie_manager.merge_cookies(response.cookies)
        self._workers.pop(page, None)

        # 取消的请求不记录历史
        if page_alive and not cancelled:
            current_req = page.request_editor.build_request()
            history = HistoryRecord(
                name=current_req.name if hasattr(current_req, 'name') and current_req.name else "",
                method=current_req.method,
                url=current_req.url,
                headers=current_req.headers,
                params=current_req.params,
                body_type=current_req.body_type,
                body_content=current_req.body_content,
                status_code=response.status_code,
                response_time=int(response.elapsed_ms),
                response_size=response.size_bytes,
            )
            self.db.add_history(history)
            self.history_panel.refresh_history()

        if cancelled:
            self.status_bar.showMessage("请求已取消", 3000)
            self.logger.info("Request was cancelled.")
        elif response.error:
            self.status_bar.showMessage(f"请求失败: {response.error}", 5000)
            self.logger.warning(f"Request failed: {response.error}")
        else:
            self.status_bar.showMessage(
                f"{response.status_code} {response.reason} | {response.elapsed_ms:.0f}ms | {response.size_display}",
                5000,
            )
            self.logger.info(f"Response: {response.status_code} {response.reason} in {response.elapsed_ms:.0f}ms")

    # ─── 快捷键 ───────────────────────────────────────────────

    def keyPressEvent(self, event):
        """全局快捷键"""
        modifiers = event.modifiers()
        key = event.key()

        # Ctrl+Enter 发送请求
        if modifiers == Qt.KeyboardModifier.ControlModifier and key in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter
        ):
            page = self.request_tabs.current_page()
            if page and hasattr(page, 'request_editor'):
                page.request_editor._on_send()
            elif hasattr(self, 'request_editor'):
                self.request_editor._on_send()
        # Ctrl+F1 帮助
        elif modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_F1:
            self._on_show_help()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        """关闭窗口时清理所有发送线程并刷新 tab 持久化"""
        # 停止所有防抖定时器并立即保存
        for timer in self._tab_save_timers.values():
            timer.stop()
        for i in range(self.request_tabs.tab_widget.count()):
            page = self.request_tabs.tab_widget.widget(i)
            if isinstance(page, RequestTabPage):
                self._save_tab_state(page)
        for worker in list(self._workers.values()):
            if worker.isRunning():
                worker.cancel()
                worker.quit()
                worker.wait(2000)
        if self._help_viewer:
            self._help_viewer.close()
        # 彻底关闭嗅探器弹窗及其调起的全部真机浏览器进程
        try:
            if hasattr(self, "_sniffer_dialog") and self._sniffer_dialog:
                self._sniffer_dialog.close()
            from app.core.browser_sniffer import BrowserSnifferController
            BrowserSnifferController.stop_all()
        except Exception:
            pass
        try:
            from app.core.go_engine import GoEngineManager
            GoEngineManager.get_instance().shutdown()
        except Exception:
            pass
        event.accept()
