"""主题管理系统 - 亮色/暗色主题定义与切换"""

from pathlib import Path
import sys
from PyQt6.QtGui import QPalette, QColor, QIcon
from PyQt6.QtCore import Qt, QSize


def _get_icon_file(filename: str) -> str:
    """获取图标文件绝对路径，使用正斜杠供 QSS url() 使用"""
    if getattr(sys, 'frozen', False):
        base_dir = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    else:
        base_dir = Path(__file__).parent.parent.parent
    p = base_dir / "app" / "resources" / "icons" / filename
    return str(p).replace("\\", "/")


# ─── 颜色定义 ─────────────────────────────────────────────────

class LightTheme:
    """亮色主题颜色定义"""
    name = "light"
    close_btn_icon = _get_icon_file("tab_close_light.png")
    close_btn_icon_hover = _get_icon_file("tab_close_light_hover.png")

    # 基础色
    bg_primary = "#ffffff"
    bg_secondary = "#f8f9fa"
    bg_sidebar = "#f4f5f7"
    bg_input = "#ffffff"
    bg_code = "#f8f8f8"
    bg_hover = "#e5e7eb"
    bg_selected = "#e5edfa"
    bg_tab_active = "#ffffff"
    bg_tab_inactive = "#e8eaed"

    # 文字色
    text_primary = "#1f2937"
    text_secondary = "#4b5563"
    text_placeholder = "#9ca3af"
    text_disabled = "#9ca3af"
    text_name = "#2563eb"  # 请求名称（蓝调，表示可编辑）

    # 边框
    border = "#d1d5db"
    border_focus = "#3b82f6"
    border_light = "#e5e7eb"

    # 强调色
    accent = "#3b82f6"
    accent_hover = "#2563eb"
    primary_color = "#3b82f6"
    primary_hover = "#2563eb"
    send_btn = "#10b981"
    send_btn_hover = "#059669"
    send_btn_pressed = "#047857"

    # 状态栏
    statusbar_bg = "#3b82f6"
    statusbar_text = "#ffffff"

    # 分割线
    splitter = "#d1d5db"

    # 滚动条
    scrollbar_bg = "#f3f4f6"
    scrollbar_handle = "#c5c9d1"
    scrollbar_handle_hover = "#9ca3af"

    # 表头
    header_bg = "#f3f4f6"
    header_text = "#374151"

    # 代码区
    code_bg = "#f8f8f8"
    code_text = "#1f2937"

    # 响应区状态色
    status_success = "#15803d"
    status_redirect = "#b45309"
    status_client_error = "#b91c1c"
    status_server_error = "#991b1b"

    # Pygments 语法高亮风格
    pygments_style = "default"
    code_highlight_bg = "#f8f8f8"

    close_btn_hover = "rgba(0, 0, 0, 0.08)"

    # HTTP 方法颜色（亮色主题：优雅温润的高对比度非荧光色系，长时间查看护眼不眩晕）
    method_colors = {
        "GET": "#15803d",      # 沉稳森林绿（杜绝高光刺眼荧光绿）
        "POST": "#b45309",     # 温润深琥珀/暖赭橙
        "PUT": "#1d4ed8",      # 典雅皇家蓝
        "PATCH": "#6d28d9",    # 雅致深紫
        "DELETE": "#b91c1c",   # 沉稳酒红
        "HEAD": "#475569",     # 铅灰
        "OPTIONS": "#0e7490",  # 深墨青
    }


class DarkTheme:
    """暗色主题颜色定义"""
    name = "dark"
    close_btn_icon = _get_icon_file("tab_close_dark.png")
    close_btn_icon_hover = _get_icon_file("tab_close_dark_hover.png")

    # 基础色
    bg_primary = "#1e1e1e"
    bg_secondary = "#252526"
    bg_sidebar = "#252526"
    bg_input = "#3c3c3c"
    bg_code = "#1e1e1e"
    bg_hover = "#2d4a7a"
    bg_selected = "#3a6fbf"
    bg_tab_active = "#1e1e1e"
    bg_tab_inactive = "#2d2d2d"

    # 文字色
    text_primary = "#d4d4d4"
    text_secondary = "#aaaaaa"
    text_placeholder = "#666666"
    text_disabled = "#555555"
    text_name = "#9FA8DA"  # 请求名称（浅靛蓝，适配暗色背景）

    # 边框
    border = "#555555"
    border_focus = "#61affe"
    border_light = "#444444"

    # 强调色
    accent = "#61affe"
    accent_hover = "#4a90d9"
    primary_color = "#61affe"
    primary_hover = "#4a90d9"
    send_btn = "#49cc90"
    send_btn_hover = "#3db87a"
    send_btn_pressed = "#2fa068"

    # 状态栏
    statusbar_bg = "#007acc"
    statusbar_text = "#ffffff"

    # 分割线
    splitter = "#333333"

    # 滚动条
    scrollbar_bg = "#1e1e1e"
    scrollbar_handle = "#424242"
    scrollbar_handle_hover = "#4e4e4e"

    # 表头
    header_bg = "#2d2d2d"
    header_text = "#d4d4d4"

    # 代码区
    code_bg = "#1e1e1e"
    code_text = "#d4d4d4"

    # 响应区状态色
    status_success = "#49cc90"
    status_redirect = "#fca130"
    status_client_error = "#f93e3e"
    status_server_error = "#f93e3e"

    # Pygments 语法高亮风格
    pygments_style = "monokai"
    code_highlight_bg = "#272822"

    close_btn_hover = "rgba(255, 255, 255, 0.18)"

    # HTTP 方法颜色（暗色主题：浅色系高对比度规范配色）
    method_colors = {
        "GET": "#49cc90",      # 浅绿
        "POST": "#fca130",     # 浅橙/琥珀
        "PUT": "#60a5fa",      # 浅蓝
        "PATCH": "#a78bfa",    # 浅紫
        "DELETE": "#f87171",   # 浅红
        "HEAD": "#94a3b8",     # 浅灰
        "OPTIONS": "#38bdf8",  # 浅青蓝
    }


# ─── 主题管理器 ───────────────────────────────────────────────

class ThemeMeta(type):
    """主题元类，支持类属性访问 ThemeManager.current_theme"""
    @property
    def current_theme(cls):
        return cls.current()


class ThemeManager(metaclass=ThemeMeta):
    """主题管理器（单例）"""

    _instance = None
    _current_theme = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_theme(cls, name: str = "light"):
        if name == "dark":
            return DarkTheme
        return LightTheme

    @classmethod
    def current(cls):
        if cls._current_theme is None:
            cls._current_theme = LightTheme
        return cls._current_theme

    @classmethod
    def set_theme(cls, name: str):
        cls._current_theme = cls.get_theme(name)

    @classmethod
    def toggle(cls) -> str:
        """切换主题，返回新主题名"""
        if cls.current().name == "light":
            cls.set_theme("dark")
        else:
            cls.set_theme("light")
        return cls.current().name


def get_method_color(method: str, fallback: str = "#888888") -> str:
    """按当前主题取方法颜色，避免深色系在暗色背景上不可见"""
    return ThemeManager.current().method_colors.get(method, fallback)


# ─── 样式表生成 ───────────────────────────────────────────────

def generate_main_stylesheet(t) -> str:
    """根据主题生成全局样式表"""
    return f"""
        QMainWindow {{
            background-color: {t.bg_primary};
        }}
        QWidget {{
            color: {t.text_primary};
            font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
        }}
        QSplitter::handle {{
            background-color: {t.splitter};
        }}
        QSplitter::handle:horizontal {{
            width: 4px;
        }}
        QSplitter::handle:vertical {{
            height: 4px;
        }}
        QSplitter::handle:hover {{
            background-color: {t.accent};
        }}
        QStatusBar {{
            background-color: {t.statusbar_bg};
            color: {t.statusbar_text};
            font-size: 12px;
        }}
        QScrollBar:vertical {{
            background-color: {t.scrollbar_bg};
            width: 8px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {t.scrollbar_handle};
            border-radius: 4px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {t.scrollbar_handle_hover};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar:horizontal {{
            background-color: {t.scrollbar_bg};
            height: 8px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {t.scrollbar_handle};
            border-radius: 4px;
            min-width: 24px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: {t.scrollbar_handle_hover};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        QComboBox {{
            background-color: {t.bg_input};
            border: 1px solid {t.border};
            border-radius: 6px;
            padding: 4px 10px;
            color: {t.text_primary};
            font-size: 13px;
        }}
        QComboBox:hover {{
            border-color: {t.border_focus};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {t.bg_input};
            color: {t.text_primary};
            selection-background-color: {t.bg_selected};
            selection-color: {t.text_primary};
            border: 1px solid {t.border};
            border-radius: 4px;
            padding: 2px;
        }}
        QPushButton {{
            background-color: {t.bg_input};
            border: 1px solid {t.border};
            border-radius: 6px;
            padding: 5px 14px;
            color: {t.text_primary};
            font-size: 13px;
        }}
        QPushButton:hover {{
            background-color: {t.bg_hover};
            border-color: {t.accent};
        }}
        QLineEdit {{
            background-color: {t.bg_input};
            border: 1px solid {t.border};
            border-radius: 6px;
            padding: 5px 10px;
            color: {t.text_primary};
            font-size: 13px;
        }}
        QLineEdit:focus {{
            border-color: {t.border_focus};
        }}
        QTextEdit {{
            background-color: {t.bg_input};
            color: {t.text_primary};
            border: 1px solid {t.border_light};
            border-radius: 4px;
        }}
        QLabel {{
            color: {t.text_primary};
        }}
        QTableWidget {{
            background-color: {t.bg_primary};
            color: {t.text_primary};
            gridline-color: {t.border_light};
            border: 1px solid {t.border_light};
            border-radius: 4px;
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
        QListWidget {{
            background-color: {t.bg_sidebar};
            color: {t.text_primary};
        }}
        QTreeWidget {{
            background-color: {t.bg_sidebar};
            color: {t.text_primary};
        }}
        QMenu {{
            background-color: {t.bg_input};
            color: {t.text_primary};
            border: 1px solid {t.border};
            border-radius: 6px;
            padding: 4px 0px;
        }}
        QMenu::item {{
            padding: 6px 24px 6px 12px;
            border-radius: 3px;
            margin: 1px 4px;
        }}
        QMenu::item:selected {{
            background-color: {t.bg_selected};
            color: {t.text_primary};
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {t.border_light};
            margin: 4px 8px;
        }}
        QMessageBox {{
            background-color: {t.bg_primary};
        }}
        QInputDialog {{
            background-color: {t.bg_primary};
        }}
        QToolTip {{
            background-color: {t.bg_input};
            color: {t.text_primary};
            border: 1px solid {t.border};
            border-radius: 4px;
            padding: 5px 8px;
            font-size: 12px;
        }}
        QMenuBar {{
            background-color: {t.bg_secondary};
            color: {t.text_primary};
            border-bottom: 1px solid {t.border_light};
        }}
        QMenuBar::item {{
            background: transparent;
            padding: 5px 10px;
            border-radius: 4px;
        }}
        QMenuBar::item:selected {{
            background-color: {t.bg_hover};
        }}

        /* ─── 顶部请求标签栏专用样式 (#requestTabWidget) ─── */
        QTabWidget#requestTabWidget {{
            background-color: {t.bg_secondary};
        }}
        QTabWidget#requestTabWidget::pane {{
            border: none;
            background-color: {t.bg_primary};
        }}
        QTabWidget#requestTabWidget > QTabBar {{
            background-color: {t.bg_secondary};
            border-bottom: 1px solid {t.border_light};
            qproperty-drawBase: 0;
        }}
        QTabWidget#requestTabWidget > QTabBar::tab {{
            background-color: {t.bg_tab_inactive};
            color: {t.text_secondary};
            min-width: 80px;
            max-width: 200px;
            height: 34px;
            padding: 0px 8px 0px 8px;
            margin-right: 2px;
            margin-top: 3px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            border: 1px solid transparent;
            border-bottom: none;
            font-size: 12px;
        }}
        QTabWidget#requestTabWidget > QTabBar::tab:hover {{
            background-color: {t.bg_hover};
            color: {t.text_primary};
        }}
        QTabWidget#requestTabWidget > QTabBar::tab:selected {{
            background-color: {t.bg_tab_active};
            color: {t.text_primary};
            border: 1px solid {t.border_light};
            border-bottom: 2px solid {t.accent};
            font-weight: 500;
        }}
        QTabWidget#requestTabWidget > QTabBar::close-button {{
            subcontrol-position: right;
            margin-right: 4px;
            border-radius: 7px;
            padding: 2px;
            image: url({t.close_btn_icon});
        }}
        QTabWidget#requestTabWidget > QTabBar::close-button:hover {{
            background-color: {t.close_btn_hover};
            image: url({t.close_btn_icon_hover});
        }}

        /* ─── 请求与响应内部子标签页专用样式 (#editorSubTabs, #responseSubTabs) ─── */
        QTabWidget#editorSubTabs::pane, QTabWidget#responseSubTabs::pane {{
            border: none;
            border-top: 1px solid {t.border_light};
            background-color: {t.bg_primary};
        }}
        QTabWidget#editorSubTabs > QTabBar, QTabWidget#responseSubTabs > QTabBar {{
            background-color: transparent;
            border-bottom: 1px solid {t.border_light};
            qproperty-drawBase: 0;
        }}
        QTabWidget#editorSubTabs > QTabBar::tab, QTabWidget#responseSubTabs > QTabBar::tab {{
            background-color: transparent;
            color: {t.text_secondary};
            padding: 8px 16px;
            margin-right: 4px;
            border: none;
            border-bottom: 2px solid transparent;
            font-size: 13px;
            font-weight: 500;
        }}
        QTabWidget#editorSubTabs > QTabBar::tab:hover, QTabWidget#responseSubTabs > QTabBar::tab:hover {{
            color: {t.text_primary};
            background-color: {t.bg_hover};
            border-radius: 4px 4px 0 0;
        }}
        QTabWidget#editorSubTabs > QTabBar::tab:selected, QTabWidget#responseSubTabs > QTabBar::tab:selected {{
            color: {t.accent};
            border-bottom: 2px solid {t.accent};
            font-weight: bold;
            background-color: transparent;
        }}

        /* 默认通用 TabWidget 备用样式 */
        QTabWidget::pane {{
            border: none;
            background-color: {t.bg_primary};
        }}
        QTabBar {{
            background-color: {t.bg_secondary};
        }}
        QTabBar::tab {{
            background-color: {t.bg_tab_inactive};
            color: {t.text_secondary};
            padding: 6px 14px;
            border-right: 1px solid {t.border_light};
        }}
        QTabBar::tab:selected {{
            background-color: {t.bg_tab_active};
            color: {t.text_primary};
            border-bottom: 2px solid {t.accent};
        }}
        QCheckBox {{
            color: {t.text_primary};
            spacing: 6px;
        }}
    """


def generate_left_panel_stylesheet(t) -> str:
    """左侧面板样式"""
    return f"""
        QWidget#leftPanel {{
            background-color: {t.bg_sidebar};
        }}
    """


def generate_left_tabs_stylesheet(t) -> str:
    """左侧 Tab 样式"""
    return f"""
        QTabWidget#leftTabs::pane, QTabWidget::pane {{
            border: none;
            background-color: {t.bg_sidebar};
        }}
        QTabBar {{
            background-color: {t.bg_sidebar};
            border-bottom: 1px solid {t.border_light};
            qproperty-drawBase: 0;
        }}
        QTabBar::tab {{
            padding: 8px 18px;
            font-size: 13px;
            font-weight: 500;
            color: {t.text_secondary};
            background-color: transparent;
            border-bottom: 2px solid transparent;
        }}
        QTabBar::tab:hover {{
            color: {t.text_primary};
            background-color: {t.bg_hover};
            border-radius: 4px;
        }}
        QTabBar::tab:selected {{
            background-color: transparent;
            color: {t.accent};
            font-weight: bold;
            border-bottom: 2px solid {t.accent};
        }}
    """


def get_resource_dir() -> Path:
    """获取资源文件根目录，自动兼容 PyInstaller 打包与源码开发环境"""
    if getattr(sys, 'frozen', False):
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent.parent


_CACHED_APP_ICON: Optional[QIcon] = None


def get_app_icon() -> QIcon:
    """构建多分辨率高清晰度应用程序图标，适配各种 DPI 和 Windows 任务栏（内存单例缓存）"""
    global _CACHED_APP_ICON
    if _CACHED_APP_ICON is not None and not _CACHED_APP_ICON.isNull():
        return _CACHED_APP_ICON

    base_dir = get_resource_dir()
    icons_dir = base_dir / "app" / "resources" / "icons"

    icon = QIcon()

    # 1. 优先加载包含多尺寸图层的 .ico 文件
    ico_path = icons_dir / "postmanage.ico"
    if ico_path.exists():
        icon.addFile(str(ico_path))

    # 2. 注入各级常见分辨率 PNG，确保 Windows 任务栏无论何种 DPI 缩放均能精准采样
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        png_path = icons_dir / f"icon_{size}.png"
        if png_path.exists():
            icon.addFile(str(png_path), QSize(size, size))

    # 3. 备选通用图标
    if icon.isNull():
        for fallback in ("icon_256.png", "postmanage.ico"):
            fb = icons_dir / fallback
            if fb.exists():
                icon = QIcon(str(fb))
                break

    _CACHED_APP_ICON = icon
    return icon
