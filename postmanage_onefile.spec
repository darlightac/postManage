# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onefile 打包配置 - 生成单个可执行文件

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        ('app/bin/postmanage-engine.exe', 'app/bin'),
    ],
    datas=[
        ('app/resources', 'app/resources'),
    ],
    hiddenimports=[
        'httpx',
        'pygments',
        'pygments.lexers',
        'pygments.formatters',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'app.core.go_engine',
        'app.core.browser_sniffer',
        'app.widgets.stress_dialog',
        'app.widgets.sniffer_dialog',
        'app.widgets.stress_records_dialog',
        'app.widgets.stream_extractor_dialog',
        'app.widgets.save_request_dialog',
        'app.widgets.mock_center_dialog',
        'app.widgets.pre_post_processor_widget',
        'app.widgets.help_viewer',
        'app.core.mock_server',
        'app.core.processors',
        'app.core.logger',
        'app.core.win_utils',
        'app.widgets.loading_screen',
        'app.core.proxy_manager',
        'app.widgets.proxy_dialog',
        'sqlite3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'pydoc',
        'pydoc_data',
        'sqlite3.test',
        'asyncio.test',
        'test',
        'pdb',
        'idlelib',
        'distutils',
        'lib2to3',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 过滤掉外部环境泄漏的 icu 相关冲突 DLL（保证 Qt6Core 使用 Windows 10/11 系统的原生 ICU 库）
a.binaries = [x for x in a.binaries if not x[0].lower().startswith('icu')]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PostManage',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app\\resources\\icons\\postmanage.ico',
)
