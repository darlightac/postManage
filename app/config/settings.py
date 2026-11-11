"""应用配置管理 - 负责数据存储路径和全局设置"""

import os
import sys
import json
from pathlib import Path
from typing import Optional


def get_app_dir() -> Path:
    """获取应用安装/运行目录（PostManage.exe 或 main.py 所在目录）"""
    if getattr(sys, 'frozen', False):
        # 打包后的单文件或可执行程序目录
        return Path(sys.executable).parent
    else:
        # 开发环境：从 settings.py 向上三级到项目根目录
        return Path(__file__).parent.parent.parent


def get_default_data_dir() -> Path:
    """获取默认数据存储目录 - 安装/可执行文件同级 data 目录"""
    return get_app_dir() / "data"


def get_default_log_dir() -> Path:
    """获取默认日志输出目录 - 默认在数据目录下 logs 目录"""
    return get_default_data_dir() / "logs"


def _get_bootstrap_path() -> Path:
    """获取引导配置文件路径（优先应用同级目录，其次用户 AppData 回退）"""
    app_dir = get_app_dir()
    app_cfg = app_dir / "path_config.json"
    if app_cfg.exists():
        return app_cfg
    try:
        test_file = app_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
        return app_cfg
    except Exception:
        appdata = Path(os.environ.get("APPDATA", Path.home())) / "PostManage"
        appdata.mkdir(parents=True, exist_ok=True)
        return appdata / "path_config.json"


def _load_path_config() -> dict:
    """从引导配置文件加载自定义路径"""
    app_cfg = get_app_dir() / "path_config.json"
    if app_cfg.exists():
        try:
            with open(app_cfg, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    appdata_cfg = Path(os.environ.get("APPDATA", Path.home())) / "PostManage" / "path_config.json"
    if appdata_cfg.exists():
        try:
            with open(appdata_cfg, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_path_config(data_dir: Optional[str] = None, log_dir: Optional[str] = None):
    """保存自定义路径到引导配置文件"""
    cfg_file = _get_bootstrap_path()
    cfg_data = {}
    if data_dir and str(data_dir).strip():
        try:
            if Path(data_dir).resolve() != get_default_data_dir().resolve():
                cfg_data["data_dir"] = str(data_dir).strip()
        except Exception:
            cfg_data["data_dir"] = str(data_dir).strip()

    if log_dir and str(log_dir).strip():
        try:
            curr_data_logs = (get_data_dir() / "logs").resolve()
            def_logs = get_default_log_dir().resolve()
            p_log = Path(log_dir).resolve()
            if p_log != curr_data_logs and p_log != def_logs:
                cfg_data["log_dir"] = str(log_dir).strip()
        except Exception:
            cfg_data["log_dir"] = str(log_dir).strip()

    if not cfg_data:
        # 若均为空或恢复为默认，则清理配置文件
        if cfg_file.exists():
            try:
                cfg_file.unlink()
            except Exception:
                pass
        other_cfg = Path(os.environ.get("APPDATA", Path.home())) / "PostManage" / "path_config.json"
        if other_cfg.exists() and other_cfg != cfg_file:
            try:
                other_cfg.unlink()
            except Exception:
                pass
        return

    try:
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg_data, f, indent=2, ensure_ascii=False)
    except Exception:
        fallback = Path(os.environ.get("APPDATA", Path.home())) / "PostManage" / "path_config.json"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        with open(fallback, "w", encoding="utf-8") as f:
            json.dump(cfg_data, f, indent=2, ensure_ascii=False)


def get_data_dir() -> Path:
    """获取数据存储目录 - 默认安装目录同级 data 文件夹，支持自定义"""
    cfg = _load_path_config()
    custom = cfg.get("data_dir")
    if custom:
        p = Path(custom)
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            pass
    default_dir = get_default_data_dir()
    default_dir.mkdir(parents=True, exist_ok=True)
    return default_dir


def get_db_path() -> Path:
    """获取数据库文件路径"""
    return get_data_dir() / "requestmanager.db"


def get_config_path() -> Path:
    """获取用户配置文件路径"""
    return get_data_dir() / "config.json"


def get_log_dir() -> Path:
    """获取应用日志文件存储目录 - 默认在数据目录下 logs 文件夹，支持自定义"""
    cfg = _load_path_config()
    custom = cfg.get("log_dir")
    if custom:
        p = Path(custom)
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            pass
    default_log_dir = get_data_dir() / "logs"
    default_log_dir.mkdir(parents=True, exist_ok=True)
    return default_log_dir


def get_log_path() -> Path:
    """获取应用主日志文件路径"""
    return get_log_dir() / "postmanage.log"


# 全局配置
class Settings:
    """应用全局配置（单例），支持持久化到 config.json"""

    _instance = None

    # 默认值
    _DEFAULTS = {
        "theme": "light",
        "max_history": 500,
        "default_timeout": 0,  # 全局默认超时（毫秒），0 表示无超时
        "language": "zh",      # 界面语言: "zh" (中文) 或 "en" (英文)
        "global_headers": [],  # 全局生效的请求头列表 [{"enabled": bool, "key": str, "value": str}]
        "proxy": {
            "mode": "system",  # "system" | "none" | "custom" | "pac"
            "protocol": "HTTP",
            "host": "127.0.0.1",
            "port": 7890,
            "all_proxy": "",
            "bypass": "localhost, 127.0.0.1, ::1",
            "pac_url": "",
            "auth_enabled": False,
            "username": "",
            "password": "",
        },
        "left_panel_width": 280,
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.db_path = get_db_path()
        self._config_path = get_config_path()
        self._data = dict(self._DEFAULTS)
        self._load()

    def _load(self):
        """从配置文件加载"""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._data.update(saved)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self):
        """持久化当前配置"""
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    # ─── 属性访问 ─────────────────────────────────────────────

    @property
    def theme(self) -> str:
        return self._data.get("theme", "light")

    @theme.setter
    def theme(self, value: str):
        self._data["theme"] = value
        self.save()

    @property
    def max_history(self) -> int:
        return self._data.get("max_history", 500)

    @max_history.setter
    def max_history(self, value: int):
        self._data["max_history"] = value
        self.save()

    @property
    def default_timeout(self) -> int:
        return self._data.get("default_timeout", 0)

    @default_timeout.setter
    def default_timeout(self, value: int):
        self._data["default_timeout"] = value
        self.save()

    @property
    def language(self) -> str:
        return self._data.get("language", "zh")

    @language.setter
    def language(self, value: str):
        self._data["language"] = value
        self.save()

    @property
    def global_headers(self) -> list:
        return list(self._data.get("global_headers", []))

    @global_headers.setter
    def global_headers(self, value: list):
        self._data["global_headers"] = list(value)
        self.save()

    @property
    def proxy(self) -> dict:
        p = self._data.get("proxy")
        if isinstance(p, dict):
            return dict(p)
        return dict(self._DEFAULTS["proxy"])

    @proxy.setter
    def proxy(self, value: dict):
        if isinstance(value, dict):
            self._data["proxy"] = dict(value)
            self.save()

    @property
    def left_panel_width(self) -> int:
        return self._data.get("left_panel_width", 280)

    @left_panel_width.setter
    def left_panel_width(self, value: int):
        self._data["left_panel_width"] = int(value)
        self.save()

    def get(self, key: str, default=None):
        """获取配置项"""
        return self._data.get(key, default)

    def set(self, key: str, value):
        """设置并持久化配置项"""
        self._data[key] = value
        self.save()

    # ─── 自定义存储路径管理 ────────────────────────────────────

    def set_custom_paths(self, data_dir: Optional[str] = None, log_dir: Optional[str] = None):
        """设置并持久化自定义数据与日志目录"""
        _save_path_config(data_dir, log_dir)
        self.db_path = get_db_path()
        self._config_path = get_config_path()
        self._load()
        self.save()

    def reset_paths_to_default(self):
        """恢复数据与日志目录为默认（安装目录同级）"""
        _save_path_config(None, None)
        self.db_path = get_db_path()
        self._config_path = get_config_path()
        self._load()
        self.save()

    @property
    def custom_data_dir(self) -> Optional[str]:
        """获取用户配置的自定义数据目录，未配置返回 None"""
        return _load_path_config().get("data_dir")

    @property
    def custom_log_dir(self) -> Optional[str]:
        """获取用户配置的自定义日志目录，未配置返回 None"""
        return _load_path_config().get("log_dir")

    @property
    def is_default_data_dir(self) -> bool:
        return not bool(self.custom_data_dir)

    @property
    def is_default_log_dir(self) -> bool:
        return not bool(self.custom_log_dir)
