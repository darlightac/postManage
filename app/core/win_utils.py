"""Windows 平台专属系统级特性与任务栏图标无缝集成模块"""

import sys
import os
from pathlib import Path

APP_USER_MODEL_ID = "postmanage.desktop.apimanager.v2"


def get_permanent_icon_path() -> Path:
    """获取或提取持久化 .ico 文件路径（解决 onefile 模式解压临时目录被清理导致图标失效的问题）"""
    try:
        from app.config.settings import get_data_dir
        target_dir = get_data_dir()
    except Exception:
        target_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PostManage"

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        perm_ico = target_dir / "postmanage.ico"
        from app.config.themes import get_resource_dir
        src_ico = get_resource_dir() / "app" / "resources" / "icons" / "postmanage.ico"
        if src_ico.exists():
            if not perm_ico.exists() or perm_ico.stat().st_size != src_ico.stat().st_size:
                import shutil
                shutil.copy2(src_ico, perm_ico)
        if perm_ico.exists():
            return perm_ico
    except Exception:
        pass

    # 回退到资源目录中的 ico
    try:
        from app.config.themes import get_resource_dir
        fallback_ico = get_resource_dir() / "app" / "resources" / "icons" / "postmanage.ico"
        if fallback_ico.exists():
            return fallback_ico
    except Exception:
        pass

    return Path("app/resources/icons/postmanage.ico")


def _async_shell_registration():
    """在后台线程静默执行图标持久化、HKCU 注册表关联与开始菜单快捷方式索引"""
    try:
        import winreg

        # 1. 提取并持久化图标
        ico_path = get_permanent_icon_path()
        ico_str = str(ico_path.resolve()) if ico_path.exists() else ""

        # 2. 注册 HKCU\Software\Classes\AppUserModelId\<APP_USER_MODEL_ID>
        if ico_str:
            try:
                key_path = f"Software\\Classes\\AppUserModelId\\{APP_USER_MODEL_ID}"
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "PostManage")
                    winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, ico_str)
                    winreg.SetValueEx(key, "IconBackgroundColor", 0, winreg.REG_SZ, "0")
            except Exception:
                pass

        # 3. 在当前用户的开始菜单静默写入快捷方式（让 Windows Shell 缓存并索引此 AppID）
        programs_dir = Path(os.environ.get("APPDATA", Path.home())) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        if programs_dir.exists():
            shortcut_path = programs_dir / "PostManage.lnk"
            target_exe = sys.executable if getattr(sys, 'frozen', False) else sys.argv[0]
            if os.path.exists(target_exe) and not shortcut_path.exists():
                import tempfile
                import subprocess
                vbs = (
                    f'Set ws = WScript.CreateObject("WScript.Shell")\n'
                    f'Set sc = ws.CreateShortcut("{shortcut_path}")\n'
                    f'sc.TargetPath = "{target_exe}"\n'
                    f'sc.WorkingDirectory = "{Path(target_exe).parent}"\n'
                    f'sc.IconLocation = "{ico_str if ico_str else target_exe},0"\n'
                    f'sc.Description = "PostManage"\n'
                    f'sc.Save\n'
                )
                vbs_path = Path(tempfile.gettempdir()) / "_pm_sc_reg.vbs"
                vbs_path.write_text(vbs, encoding="gbk")
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                subprocess.run(["cscript", "//Nologo", str(vbs_path)], capture_output=True, creationflags=creation_flags)
                vbs_path.unlink(missing_ok=True)
    except Exception:
        pass


def init_windows_app_id():
    """在进程初始化最早期注册 AppUserModelID
    底层注册表与 Shell 索引异步后台进行，实现主窗口 0 延迟秒开
    """
    if sys.platform != "win32":
        return

    import ctypes
    import threading

    # 1. 设置进程级 AppUserModelID (毫秒级即刻完成)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass

    # 2. 异步执行外壳注册与快捷方式索引，不占用主线程启动时间
    t = threading.Thread(target=_async_shell_registration, daemon=True, name="WinShellRegister")
    t.start()


def apply_windows_taskbar_icon(window):
    """针对 QMainWindow 注入原生 Win32 窗口类图标与窗口实例图标
    替换 Windows 窗口类默认的 IDI_APPLICATION (65579) 占位图标，确保任务栏精准采样
    """
    if sys.platform != "win32" or window is None:
        return

    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(window.winId())
        if not hwnd:
            return

        ico_path = get_permanent_icon_path()
        if not ico_path.exists():
            return

        ico_str = str(ico_path.resolve())
        user32 = ctypes.windll.user32
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010

        # 加载 48x48/32x32 大图标与 16x16 小图标
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.LoadImageW.restype = wintypes.HANDLE

        hIconBig = user32.LoadImageW(None, ico_str, IMAGE_ICON, 48, 48, LR_LOADFROMFILE)
        if not hIconBig:
            hIconBig = user32.LoadImageW(None, ico_str, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        hIconSmall = user32.LoadImageW(None, ico_str, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)

        if hIconBig:
            # 优先设置 Window Class 图标（GCLP_HICON = -14, GCLP_HICONSM = -34）
            SetClassLongPtr = getattr(user32, "SetClassLongPtrW", None) or getattr(user32, "SetClassLongW", None)
            if SetClassLongPtr is not None:
                try:
                    SetClassLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
                    SetClassLongPtr.restype = ctypes.c_void_p
                    SetClassLongPtr(hwnd, -14, hIconBig)
                    if hIconSmall:
                        SetClassLongPtr(hwnd, -34, hIconSmall)
                except Exception:
                    pass

            # 发送 WM_SETICON 消息 (ICON_BIG = 1, ICON_SMALL = 0, WM_SETICON = 0x007F)
            try:
                user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                user32.SendMessageW.restype = wintypes.LPARAM
                user32.SendMessageW(hwnd, 0x007F, 1, hIconBig)
                if hIconSmall:
                    user32.SendMessageW(hwnd, 0x007F, 0, hIconSmall)
            except Exception:
                pass
    except Exception:
        pass
