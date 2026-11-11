"""统一日志管理模块 - 负责将应用与网络引擎关键日志输出到文件与控制台"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from app.config.settings import get_log_path, get_log_dir
from app.config.constants import APP_NAME, APP_VERSION

import threading

_LOGGING_INITIALIZED = False


def _install_exception_hooks(logger: logging.Logger):
    """安装全局未处理异常、多线程异常与 Qt 底层消息拦截器，确保任何崩溃均记录到日志"""
    def global_excepthook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "【严重错误】主线程发生未捕获异常 (Uncaught Global Exception):",
            exc_info=(exc_type, exc_value, exc_traceback)
        )
        for handler in logger.handlers:
            try:
                handler.flush()
            except Exception:
                pass

    sys.excepthook = global_excepthook

    if hasattr(threading, "excepthook"):
        def thread_excepthook(args):
            logger.critical(
                f"【严重错误】子线程 [{args.thread.name if args.thread else 'Unknown'}] 发生未捕获异常:",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
            )
            for handler in logger.handlers:
                try:
                    handler.flush()
                except Exception:
                    pass

        threading.excepthook = thread_excepthook

    # 拦截 Qt 底层致命与警告消息
    try:
        from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
        def qt_message_handler(mode, context, message):
            if mode == QtMsgType.QtFatalMsg:
                logger.critical(f"[Qt Fatal] {message}")
            elif mode == QtMsgType.QtCriticalMsg:
                logger.error(f"[Qt Error] {message}")
            elif mode == QtMsgType.QtWarningMsg:
                logger.warning(f"[Qt Warning] {message}")
        qInstallMessageHandler(qt_message_handler)
    except Exception:
        pass


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化全局日志配置，设置 RotatingFileHandler 和控制台输出"""
    global _LOGGING_INITIALIZED
    
    logger = logging.getLogger(APP_NAME)
    if _LOGGING_INITIALIZED:
        return logger
        
    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. 配置文件日志处理器 (10MB 自动轮转，保留 5 个备份)
    try:
        log_file = get_log_path()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        if sys.stderr:
            print(f"初始化文件日志失败: {e}", file=sys.stderr)

    # 2. 配置控制台日志处理器（严密检查：仅当存在真实的控制台标准输出时才添加，彻底避免无控制台模式下空指针报错死循环）
    if sys.stdout is not None and hasattr(sys.stdout, "write"):
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass
        try:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(level)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        except Exception:
            pass

    _LOGGING_INITIALIZED = True
    _install_exception_hooks(logger)
    logger.info(f"=== {APP_NAME} v{APP_VERSION} 日志系统已初始化 | 日志路径: {get_log_path()} ===")
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """获取指定名称的 Logger，若未初始化则自动初始化"""
    if not _LOGGING_INITIALIZED:
        setup_logging()
    if name:
        return logging.getLogger(f"{APP_NAME}.{name}")
    return logging.getLogger(APP_NAME)


def reconfigure_logging(new_log_path: Optional[Path] = None) -> logging.Logger:
    """动态重新配置文件日志输出路径（用户自定义日志目录时调用）"""
    global _LOGGING_INITIALIZED
    logger = logging.getLogger(APP_NAME)
    if not _LOGGING_INITIALIZED:
        return setup_logging()

    # 1. 移除并关闭已有的 RotatingFileHandler
    for h in list(logger.handlers):
        if isinstance(h, RotatingFileHandler):
            try:
                h.close()
            except Exception:
                pass
            logger.removeHandler(h)

    # 2. 获取新的日志路径并确保目录存在
    target_path = new_log_path or get_log_path()
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler = RotatingFileHandler(
            str(target_path),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
            delay=False,
        )
        file_handler.setLevel(logger.level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info(f"=== 日志输出路径已重定向至: {target_path} ===")
    except Exception as e:
        if sys.stderr:
            print(f"重新配置文件日志处理器失败: {e}", file=sys.stderr)

    return logger
