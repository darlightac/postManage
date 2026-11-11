"""Windows 任务栏图标与系统集成自动化测试"""

import sys
import os
import unittest
from pathlib import Path

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QMainWindow
from app.core.win_utils import (
    APP_USER_MODEL_ID,
    get_permanent_icon_path,
    init_windows_app_id,
    apply_windows_taskbar_icon,
)


class TestWindowsTaskbarIcon(unittest.TestCase):
    """测试 Windows 任务栏图标集成与注册"""

    def setUp(self):
        self.app = QApplication.instance() or QApplication(sys.argv)

    def test_01_permanent_icon_path(self):
        """测试 1：持久化 .ico 文件路径定位与导出"""
        ico_path = get_permanent_icon_path()
        self.assertIsInstance(ico_path, Path)
        self.assertTrue(ico_path.exists(), f"图标文件必须存在: {ico_path}")
        self.assertGreater(ico_path.stat().st_size, 0, "图标文件不应为空")

    def test_02_init_windows_app_id(self):
        """测试 2：进程级 AppUserModelID 与注册表项无异常初始化"""
        if sys.platform != "win32":
            return
        
        # 执行注册
        init_windows_app_id()

        # 验证注册表项是否存在
        import winreg
        key_path = f"Software\\Classes\\AppUserModelId\\{APP_USER_MODEL_ID}"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                name, _ = winreg.QueryValueEx(key, "DisplayName")
                ico, _ = winreg.QueryValueEx(key, "IconUri")
                self.assertEqual(name, "PostManage")
                self.assertTrue(Path(ico).exists(), f"注册表中的图标路径必须真实存在: {ico}")
        except FileNotFoundError:
            self.fail(f"注册表项 HKCU\\{key_path} 未正确创建")

    def test_03_apply_windows_taskbar_icon(self):
        """测试 3：针对窗口实例安全注入原生 Win32 图标，且不引起崩溃"""
        if sys.platform != "win32":
            return

        win = QMainWindow()
        win.show()
        try:
            apply_windows_taskbar_icon(win)
            # 验证 HWND 存在
            self.assertGreater(int(win.winId()), 0)
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
