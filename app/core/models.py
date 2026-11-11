"""数据模型定义"""

from dataclasses import dataclass, field
from typing import Optional
import json
import uuid
import time


def generate_id() -> str:
    return uuid.uuid4().hex


def now_timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class HeaderItem:
    key: str = ""
    value: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return {"key": self.key, "value": self.value, "enabled": self.enabled}

    @staticmethod
    def from_dict(d: dict) -> "HeaderItem":
        return HeaderItem(key=d.get("key", ""), value=d.get("value", ""), enabled=d.get("enabled", True))


@dataclass
class ParamItem:
    key: str = ""
    value: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return {"key": self.key, "value": self.value, "enabled": self.enabled}

    @staticmethod
    def from_dict(d: dict) -> "ParamItem":
        return ParamItem(key=d.get("key", ""), value=d.get("value", ""), enabled=d.get("enabled", True))


@dataclass
class Collection:
    """请求集合（也可作为文件夹使用）"""
    id: str = field(default_factory=generate_id)
    name: str = "新建集合"
    description: str = ""
    parent_id: Optional[str] = None
    sort_order: int = 0
    created_at: str = field(default_factory=now_timestamp)
    updated_at: str = field(default_factory=now_timestamp)


@dataclass
class SavedRequest:
    """保存的请求"""
    id: str = field(default_factory=generate_id)
    collection_id: str = ""
    name: str = "新建请求"
    method: str = "GET"
    url: str = ""
    headers: list[HeaderItem] = field(default_factory=list)
    params: list[ParamItem] = field(default_factory=list)
    body_type: str = "none"
    body_content: str = ""
    auth_type: str = "none"
    auth_config: dict = field(default_factory=dict)
    cookies: list[dict] = field(default_factory=list)  # Cookie 列表
    timeout: int = 0  # 0 表示无超时限制
    sort_order: int = 0
    pre_script: dict = field(default_factory=dict)   # 前置处理配置
    post_script: dict = field(default_factory=dict)  # 后置处理配置
    proxy: dict = field(default_factory=dict)        # 接口专属代理配置 (为空或 mode="default" 表示继承全局)
    created_at: str = field(default_factory=now_timestamp)
    updated_at: str = field(default_factory=now_timestamp)

    def headers_json(self) -> str:
        return json.dumps([h.to_dict() for h in self.headers], ensure_ascii=False)

    def params_json(self) -> str:
        return json.dumps([p.to_dict() for p in self.params], ensure_ascii=False)

    def auth_config_json(self) -> str:
        from app.core.security import encrypt_auth_config
        return encrypt_auth_config(self.auth_config)

    def pre_script_json(self) -> str:
        return json.dumps(self.pre_script, ensure_ascii=False)

    def post_script_json(self) -> str:
        return json.dumps(self.post_script, ensure_ascii=False)

    def proxy_json(self) -> str:
        return json.dumps(self.proxy, ensure_ascii=False) if self.proxy else "{}"

    def __getitem__(self, key: str):
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default=None):
        return getattr(self, key, default)

    @staticmethod
    def from_db_row(row: dict) -> "SavedRequest":
        from app.core.security import decrypt_auth_config
        headers_val = row.get("headers")
        params_val = row.get("params")
        auth_config_val = row.get("auth_config")
        cookies_val = row.get("cookies")
        pre_script_val = row.get("pre_script")
        post_script_val = row.get("post_script")
        proxy_val = row.get("proxy")

        # 1. Headers 兼容解析 (支持 json 字符串、list、dict)
        headers = []
        try:
            if isinstance(headers_val, str):
                raw_h = json.loads(headers_val) if headers_val.strip() else []
            else:
                raw_h = headers_val or []
            if isinstance(raw_h, dict):
                headers = [HeaderItem(key=str(k), value=str(v), enabled=True) for k, v in raw_h.items()]
            elif isinstance(raw_h, list):
                for h in raw_h:
                    if isinstance(h, dict):
                        headers.append(HeaderItem.from_dict(h))
                    elif isinstance(h, (list, tuple)) and len(h) >= 2:
                        headers.append(HeaderItem(key=str(h[0]), value=str(h[1]), enabled=True))
        except Exception:
            headers = []

        # 2. Params 兼容解析 (支持 json 字符串、list、dict)
        params = []
        try:
            if isinstance(params_val, str):
                raw_p = json.loads(params_val) if params_val.strip() else []
            else:
                raw_p = params_val or []
            if isinstance(raw_p, dict):
                params = [ParamItem(key=str(k), value=str(v), enabled=True) for k, v in raw_p.items()]
            elif isinstance(raw_p, list):
                for p in raw_p:
                    if isinstance(p, dict):
                        params.append(ParamItem.from_dict(p))
                    elif isinstance(p, (list, tuple)) and len(p) >= 2:
                        params.append(ParamItem(key=str(p[0]), value=str(p[1]), enabled=True))
        except Exception:
            params = []

        # 3. AuthConfig 兼容解析
        auth_config = {}
        try:
            if isinstance(auth_config_val, str):
                auth_config = decrypt_auth_config(auth_config_val)
            elif isinstance(auth_config_val, dict):
                auth_config = auth_config_val
        except Exception:
            auth_config = {}
        if not isinstance(auth_config, dict):
            auth_config = {}

        # 4. Cookies 兼容解析
        cookies = []
        try:
            if isinstance(cookies_val, str):
                raw_c = json.loads(cookies_val) if cookies_val.strip() else []
            else:
                raw_c = cookies_val or []
            if isinstance(raw_c, list):
                cookies = raw_c
            elif isinstance(raw_c, dict):
                cookies = [{"name": str(k), "value": str(v)} for k, v in raw_c.items()]
        except Exception:
            cookies = []

        # 5. Pre/Post Scripts
        try:
            pre_script = json.loads(pre_script_val) if isinstance(pre_script_val, str) and pre_script_val.strip() else (pre_script_val if isinstance(pre_script_val, dict) else {})
        except Exception:
            pre_script = {}

        try:
            post_script = json.loads(post_script_val) if isinstance(post_script_val, str) and post_script_val.strip() else (post_script_val if isinstance(post_script_val, dict) else {})
        except Exception:
            post_script = {}

        # 6. Proxy 专属代理配置
        try:
            proxy = json.loads(proxy_val) if isinstance(proxy_val, str) and proxy_val.strip() else (proxy_val if isinstance(proxy_val, dict) else {})
        except Exception:
            proxy = {}

        return SavedRequest(
            id=row.get("id") or "",
            collection_id=row.get("collection_id") or "",
            name=row.get("name") or "新建请求",
            method=row.get("method") or "GET",
            url=row.get("url") or "",
            headers=headers,
            params=params,
            body_type=row.get("body_type") or "none",
            body_content=row.get("body_content") or "",
            auth_type=row.get("auth_type") or "none",
            auth_config=auth_config,
            cookies=cookies,
            timeout=row.get("timeout") or 0,
            sort_order=row.get("sort_order") or 0,
            pre_script=pre_script,
            post_script=post_script,
            proxy=proxy,
            created_at=row.get("created_at") or "",
            updated_at=row.get("updated_at") or "",
        )

    from_dict = from_db_row


@dataclass
class HistoryRecord:
    """请求历史记录"""
    id: str = field(default_factory=generate_id)
    name: str = ""  # 请求名称（可选）
    method: str = "GET"
    url: str = ""
    headers: list[HeaderItem] = field(default_factory=list)
    params: list[ParamItem] = field(default_factory=list)  # 添加 params
    body_type: str = "none"
    body_content: str = ""
    status_code: Optional[int] = None
    response_time: Optional[int] = None
    response_size: Optional[int] = None
    created_at: str = field(default_factory=now_timestamp)

    def headers_json(self) -> str:
        return json.dumps([h.to_dict() for h in self.headers], ensure_ascii=False)
    
    def params_json(self) -> str:
        return json.dumps([p.to_dict() for p in self.params], ensure_ascii=False)

    @staticmethod
    def from_db_row(row: dict) -> "HistoryRecord":
        headers_val = row.get("headers")
        params_val = row.get("params")

        headers = []
        try:
            if isinstance(headers_val, str):
                raw_h = json.loads(headers_val) if headers_val.strip() else []
            else:
                raw_h = headers_val or []
            if isinstance(raw_h, dict):
                headers = [HeaderItem(key=str(k), value=str(v), enabled=True) for k, v in raw_h.items()]
            elif isinstance(raw_h, list):
                for h in raw_h:
                    if isinstance(h, dict):
                        headers.append(HeaderItem.from_dict(h))
                    elif isinstance(h, (list, tuple)) and len(h) >= 2:
                        headers.append(HeaderItem(key=str(h[0]), value=str(h[1]), enabled=True))
        except Exception:
            headers = []

        params = []
        try:
            if isinstance(params_val, str):
                raw_p = json.loads(params_val) if params_val.strip() else []
            else:
                raw_p = params_val or []
            if isinstance(raw_p, dict):
                params = [ParamItem(key=str(k), value=str(v), enabled=True) for k, v in raw_p.items()]
            elif isinstance(raw_p, list):
                for p in raw_p:
                    if isinstance(p, dict):
                        params.append(ParamItem.from_dict(p))
                    elif isinstance(p, (list, tuple)) and len(p) >= 2:
                        params.append(ParamItem(key=str(p[0]), value=str(p[1]), enabled=True))
        except Exception:
            params = []

        return HistoryRecord(
            id=row.get("id") or "",
            name=row.get("name") or "",
            method=row.get("method") or "GET",
            url=row.get("url") or "",
            headers=headers,
            params=params,
            body_type=row.get("body_type") or "none",
            body_content=row.get("body_content") or "",
            status_code=row.get("status_code"),
            response_time=row.get("response_time"),
            response_size=row.get("response_size"),
            created_at=row.get("created_at") or "",
        )


@dataclass
class HTTPResponse:
    """HTTP 响应结果"""
    status_code: int = 0
    reason: str = ""
    headers: dict = field(default_factory=dict)
    body: str = ""
    elapsed_ms: float = 0.0
    size_bytes: int = 0
    cookies: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    timing: Optional[dict] = None  # 全链路网络细分耗时 (DNS, TCP, TLS, TTFB 等)

    @property
    def is_success(self) -> bool:
        return self.error is None and 200 <= self.status_code < 400

    @property
    def size_display(self) -> str:
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        elif self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        else:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"


@dataclass
class MockCollection:
    """Mock 文件夹集合"""
    id: str = field(default_factory=generate_id)
    name: str = "新建Mock文件夹"
    parent_id: Optional[str] = None
    sort_order: int = 0
    created_at: str = field(default_factory=now_timestamp)
    updated_at: str = field(default_factory=now_timestamp)


@dataclass
class MockApi:
    """Mock 接口配置"""
    id: str = field(default_factory=generate_id)
    collection_id: str = ""
    name: str = "Mock接口"
    method: str = "GET"
    path: str = "/api/example"
    status_code: int = 200
    delay_ms: int = 0
    headers: list[dict] = field(default_factory=list)
    body_type: str = "json"
    body_content: str = '{"code": 200, "message": "success"}'
    is_enabled: bool = True
    sort_order: int = 0
    created_at: str = field(default_factory=now_timestamp)
    updated_at: str = field(default_factory=now_timestamp)

    def headers_json(self) -> str:
        return json.dumps(self.headers, ensure_ascii=False)

    @staticmethod
    def from_db_row(row: dict) -> "MockApi":
        headers_str = row.get("headers") or "[]"
        try:
            headers = json.loads(headers_str)
        except Exception:
            headers = []
        return MockApi(
            id=row.get("id") or "",
            collection_id=row.get("collection_id") or "",
            name=row.get("name") or "Mock接口",
            method=row.get("method") or "GET",
            path=row.get("path") or "",
            status_code=int(row.get("status_code") or 200),
            delay_ms=int(row.get("delay_ms") or 0),
            headers=headers,
            body_type=row.get("body_type") or "json",
            body_content=row.get("body_content") or "",
            is_enabled=bool(row.get("is_enabled", 1)),
            sort_order=int(row.get("sort_order") or 0),
            created_at=row.get("created_at") or "",
            updated_at=row.get("updated_at") or "",
        )

    from_dict = from_db_row
