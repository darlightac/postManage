"""RequestManager - 离线 API 请求管理工具

Author: 谭成洁
Copyright © 2026 谭成洁. All Rights Reserved.
Licensed under the MIT License.
"""

import sys
import os
from pathlib import Path

# 最早期初始化全局日志系统与全局异常拦截器
from app.core.logger import setup_logging, get_logger
setup_logging()

# Windows 下显式注册进程 AppUserModelID 与系统级 Shell 任务栏图标绑定 (异步完成外壳索引)
if sys.platform == "win32":
    try:
        from app.core.win_utils import init_windows_app_id
        init_windows_app_id()
    except Exception as e:
        get_logger().warning(f"init_windows_app_id 提示: {e}")

# Windows 下 PyInstaller 打包环境 DLL 目录补丁 (支持 Python 3.8+ / 3.14 动态库安全加载)
if getattr(sys, "frozen", False):
    base_dir = Path(sys._MEIPASS)
    for qt_bin in [
        base_dir / "PyQt6" / "Qt6" / "bin",
        base_dir / "Qt6" / "bin",
        base_dir,
    ]:
        if qt_bin.exists():
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(qt_bin))
                except Exception:
                    pass
            os.environ["PATH"] = str(qt_bin) + os.pathsep + os.environ.get("PATH", "")

    for qt_plugins in [
        base_dir / "PyQt6" / "Qt6" / "plugins",
        base_dir / "Qt6" / "plugins",
    ]:
        if qt_plugins.exists():
            os.environ["QT_PLUGIN_PATH"] = str(qt_plugins)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon

from app.config.constants import APP_NAME, APP_VERSION


def main():
    try:
        # 高 DPI 支持
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(APP_VERSION)
        if hasattr(app, "setDesktopFileName"):
            app.setDesktopFileName("postmanage.desktop.apimanager.v2")

        # 启动即时 Loading 窗口（极速响应用户点击，展示清晰的阶段性进度与状态）
        from app.widgets.loading_screen import LoadingScreen
        loader = LoadingScreen()
        loader.show()
        loader.set_progress(10, "正在初始化应用环境...")

        # 阶段 1：加载应用多尺寸图标
        from app.config.themes import get_app_icon
        app_icon = get_app_icon()
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
        loader.set_progress(30, "正在初始化全局配置与数据库...")

        # 阶段 2：预热核心存储引擎
        from app.core.db import Database
        _ = Database()
        loader.set_progress(55, "正在载入核心服务与网络组件...")

        # 阶段 3：按需导入并构建主界面
        from app.main_window import MainWindow
        loader.set_progress(80, "正在构建主界面工作台...")
        window = MainWindow()
        if not app_icon.isNull():
            window.setWindowIcon(app_icon)

        loader.set_progress(100, "启动就绪，即将进入...")

        # 阶段 4：平滑呈现主窗口并关闭 Loading 窗口
        def _reveal():
            window.show()
            loader.finish(window)
            if sys.platform == "win32":
                try:
                    from app.core.win_utils import apply_windows_taskbar_icon
                    apply_windows_taskbar_icon(window)
                except Exception as e:
                    get_logger("win_taskbar").warning(f"注入任务栏原生图标提示: {e}")

        QTimer.singleShot(150, _reveal)

        sys.exit(app.exec())
    except Exception as e:
        get_logger("main").critical("应用启动或主事件循环遭遇严重崩溃:", exc_info=True)
        raise


if __name__ == "__main__":
    main()
