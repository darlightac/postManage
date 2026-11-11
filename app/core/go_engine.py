"""Go 高性能引擎管理器 - 启动、通信与生命周期托管

作为 Sidecar 架构的核心：Python 端负责精美原生的 PyQt6 UI，
Go 端负责高并发压测 (Goroutine 协程池)、页面接口嗅探与毫秒级全链路耗时追踪。
"""

import atexit
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class GoEngineManager:
    """Go 引擎进程管理器（单例模式）"""

    _instance: Optional["GoEngineManager"] = None

    @classmethod
    def get_instance(cls) -> "GoEngineManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._port: Optional[int] = None
        self._base_url: Optional[str] = None
        atexit.register(self.shutdown)

    @staticmethod
    def get_engine_path() -> Path:
        """获取 Go 引擎二进制执行路径"""
        if getattr(sys, "frozen", False):
            # PyInstaller 打包环境：从临时目录解压路径获取
            base_dir = Path(sys._MEIPASS)
            candidates = [
                base_dir / "app" / "bin" / "postmanage-engine.exe",
                base_dir / "bin" / "postmanage-engine.exe",
                base_dir / "postmanage-engine.exe",
            ]
            for c in candidates:
                if c.exists():
                    return c
            return candidates[0]
        else:
            # 开发环境
            base_dir = Path(__file__).resolve().parent.parent
            exe_path = base_dir / "bin" / "postmanage-engine.exe"
            if not exe_path.exists():
                # 兜底查找 postmanage-go 编译目录
                fallback = base_dir.parent / "postmanage-go" / "engine.exe"
                if fallback.exists():
                    return fallback
            return exe_path

    def ensure_started(self) -> bool:
        """确保 Go 引擎已启动并就绪"""
        if self._process is not None and self._port is not None:
            if self.is_healthy():
                return True

        engine_exe = self.get_engine_path()
        if not engine_exe.exists():
            logger.error(f"未找到 Go 引擎可执行文件: {engine_exe}")
            return False

        try:
            # 在 Windows 下静默启动后台子进程，不弹出 CMD 黑框
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            self._process = subprocess.Popen(
                [str(engine_exe), "-port=0"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creationflags,
            )

            # 读取第一行就绪输出获取随机绑定的端口
            ready_line = ""
            for _ in range(50):
                if self._process.stdout:
                    line = self._process.stdout.readline()
                    if "POSTMANAGE_ENGINE_READY:" in line:
                        ready_line = line.strip()
                        break
                time.sleep(0.05)

            if not ready_line:
                logger.error("Go 引擎未能在规定时间内输出就绪信号")
                return False

            port_str = ready_line.split("POSTMANAGE_ENGINE_READY:")[1].strip()
            self._port = int(port_str)
            self._base_url = f"http://127.0.0.1:{self._port}"
            logger.info(f"Go 高性能引擎已就绪，端口: {self._port}")
            return True
        except Exception as e:
            logger.error(f"启动 Go 引擎失败: {e}")
            self.shutdown()
            return False

    def is_healthy(self) -> bool:
        """检查引擎健康状态"""
        if not self._base_url:
            return False
        try:
            req = urllib.request.Request(f"{self._base_url}/api/health")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("status") == "ok"
        except Exception:
            return False

    def run_stress_test(self, request_payload: Dict[str, Any], config_payload: Dict[str, Any]) -> Dict[str, Any]:
        """发起高并发压测（通过 Go 协程池执行，无 GIL 锁瓶颈）"""
        if not self.ensure_started():
            raise RuntimeError("Go 压测核心引擎未启动，请检查 postmanage-engine.exe 是否存在")

        url = f"{self._base_url}/api/stress/run"
        payload = {
            "request": request_payload,
            "config": config_payload,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        timeout = (config_payload.get("duration_sec", 10) + 15)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def scan_page(
        self,
        target_url: str,
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
        proxy_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """嗅探指定网页中调用的全部后端接口并并发健康巡检（支持携带全局请求头与 Cookie、代理）"""
        if not self.ensure_started():
            raise RuntimeError("Go 嗅探核心引擎未启动，请检查 postmanage-engine.exe 是否存在")

        url = f"{self._base_url}/api/sniffer/scan"
        payload = {
            "target_url": target_url,
            "headers": headers or {},
            "cookies": cookies or {},
            "proxy_url": proxy_url or "",
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30.0) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def stress_page(self, config_payload: Dict[str, Any]) -> Dict[str, Any]:
        """对指定页面及其全部嗅探接口执行高并发压测并按接口分别统计指标"""
        if not self.ensure_started():
            raise RuntimeError("Go 压测核心引擎未启动，请检查 postmanage-engine.exe 是否存在")

        url = f"{self._base_url}/api/sniffer/stress"
        req = urllib.request.Request(
            url,
            data=json.dumps(config_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        total_reqs = config_payload.get("total_requests", 30)
        delay_ms = config_payload.get("delay_ms", 50)
        est_seconds = max(60.0, ((total_reqs * (delay_ms + 100)) / 1000.0) + 30.0)

        with urllib.request.urlopen(req, timeout=est_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_with_timing(self, request_payload: Dict[str, Any]) -> Dict[str, Any]:
        """全链路网络生命周期耗时打点 (HTTP Trace)"""
        if not self.ensure_started():
            raise RuntimeError("Go 核心引擎未启动，请检查 postmanage-engine.exe 是否存在")

        url = f"{self._base_url}/api/timing/send"
        req = urllib.request.Request(
            url,
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        timeout = 30.0
        if "timeout" in request_payload and request_payload["timeout"] > 0:
            timeout = (request_payload["timeout"] / 1000.0) + 5.0

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def shutdown(self):
        """安全停止 Go 引擎子进程"""
        if self._process is not None:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
                self._process.terminate()
                self._process.wait(timeout=1.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            finally:
                self._process = None
                self._port = None
                self._base_url = None
