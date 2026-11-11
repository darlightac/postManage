"""PostManage 安装程序 - 打包后双击即可选择安装目录"""

import sys
import os
import shutil
import tempfile
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox, QSplashScreen
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap


def get_embedded_payload() -> Path:
    """获取嵌入的完整应用包目录或单文件"""
    if getattr(sys, 'frozen', False):
        # 打包后：优先检查 app_payload 目录（免解压直接运行版）
        base_path = Path(sys._MEIPASS)
        payload_dir = base_path / "app_payload"
        if payload_dir.exists():
            return payload_dir
        # 回退兼容单文件
        return base_path
    else:
        # 开发环境：优先从 dist/PostManage 目录获取
        dir_path = Path(__file__).parent / "dist" / "PostManage"
        if dir_path.exists():
            return dir_path
        return Path(__file__).parent / "dist"


def install():
    """安装应用到指定目录"""
    app = QApplication(sys.argv)
    app.setApplicationName("PostManage 安装程序")
    
    try:
        source_payload = get_embedded_payload()
    except Exception as e:
        QMessageBox.critical(None, "错误", str(e))
        return False
    
    # 欢迎对话框
    reply = QMessageBox.question(
        None,
        "PostManage 安装程序",
        "欢迎安装 PostManage！\n\n"
        "点击「是」选择安装目录\n"
        "点击「否」退出安装",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes
    )
    
    if reply != QMessageBox.StandardButton.Yes:
        return False
    
    # 选择安装目录
    default_dir = str(Path.home() / "Desktop")
    install_base = QFileDialog.getExistingDirectory(
        None,
        "选择安装目录",
        default_dir,
        QFileDialog.Option.ShowDirsOnly
    )
    
    if not install_base:
        return False
    
    install_path = Path(install_base) / "PostManage"
    
    # 检查是否已存在
    if install_path.exists() and list(install_path.iterdir()):
        overwrite = QMessageBox.question(
            None,
            "目录已存在",
            f"目标目录已存在：\n{install_path}\n\n"
            "是否覆盖安装？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if overwrite != QMessageBox.StandardButton.Yes:
            return False
    
    # 创建安装目录
    install_path.mkdir(parents=True, exist_ok=True)
    
    dest_exe = install_path / "PostManage.exe"
    try:
        if source_payload.is_dir() and (source_payload / "PostManage.exe").exists():
            # 完整免解压目录安装模式 (极速秒开模式)
            for item in source_payload.iterdir():
                if item.name == "data":
                    # 若目标已有 data 目录，则保留用户历史数据
                    target_data = install_path / "data"
                    if not target_data.exists():
                        target_data.mkdir(parents=True, exist_ok=True)
                    continue
                target_item = install_path / item.name
                if item.is_dir():
                    shutil.copytree(item, target_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target_item)
        else:
            # 回退单文件复制模式
            source_exe = source_payload / "PostManage.exe" if source_payload.is_dir() else source_payload
            shutil.copy2(source_exe, dest_exe)
    except Exception as e:
        QMessageBox.critical(None, "安装失败", f"无法释放安装文件到目标目录：\n{e}")
        return False
    
    # 创建桌面快捷方式
    create_shortcut = QMessageBox.question(
        None,
        "创建快捷方式",
        "是否在桌面创建快捷方式？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes
    ) == QMessageBox.StandardButton.Yes
    
    if create_shortcut:
        desktop = Path.home() / "Desktop"
        shortcut_path = desktop / "PostManage.lnk"
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(str(shortcut_path))
            shortcut.TargetPath = str(dest_exe)
            shortcut.WorkingDirectory = str(install_path)
            shortcut.Description = "PostManage"
            shortcut.save()
        except ImportError:
            # 如果没有 pywin32，使用 VBScript 方式创建快捷方式
            import subprocess
            vbs_content = (
                f'Set oWS = WScript.CreateObject("WScript.Shell")\n'
                f'sLink = "{shortcut_path}"\n'
                f'sTarget = "{dest_exe}"\n'
                f'sWorkDir = "{install_path}"\n'
                f'Set oLink = oWS.CreateShortcut(sLink)\n'
                f'oLink.TargetPath = sTarget\n'
                f'oLink.WorkingDirectory = sWorkDir\n'
                f'oLink.Save\n'
            )
            vbs_file = Path(tempfile.gettempdir()) / "create_shortcut.vbs"
            vbs_file.write_text(vbs_content, encoding='gbk')
            subprocess.run(['cscript', '//Nologo', str(vbs_file)], check=True)
            vbs_file.unlink(missing_ok=True)
    
    # 完成
    QMessageBox.information(
        None,
        "安装完成",
        f"✓ PostManage 已成功安装！\n\n"
        f"安装位置：\n{install_path}\n\n"
        f"数据目录：\n{install_path / 'data'}\n\n"
        f"{'✓ 已创建桌面快捷方式' if create_shortcut else ''}"
    )
    
    # 询问是否立即运行
    run_now = QMessageBox.question(
        None,
        "启动应用",
        "是否立即启动 PostManage？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes
    ) == QMessageBox.StandardButton.Yes
    
    if run_now:
        os.startfile(str(dest_exe))
    
    return True


if __name__ == "__main__":
    install()
