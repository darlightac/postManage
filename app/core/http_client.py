"""HTTP 请求引擎 - 基于 httpx"""

import time
import json
import re
import threading
from typing import Optional, Callable
from urllib.parse import urlparse

import httpx

from app.core.models import SavedRequest, HTTPResponse, HeaderItem
from app.config.constants import (
    BODY_TYPE_JSON, BODY_TYPE_FORM, BODY_TYPE_URLENCODED,
    BODY_TYPE_RAW, BODY_TYPE_BINARY, BODY_TYPE_NONE,
    AUTH_TYPE_BASIC, AUTH_TYPE_BEARER, AUTH_TYPE_APIKEY,
)


class HTTPClient:
    """HTTP 请求客户端"""

    def __init__(self):
        self._active_client: Optional[httpx.Client] = None
        self._active_lock = threading.Lock()

    def cancel_active(self):
        """关闭当前活跃的 httpx 客户端，中断正在进行的请求"""
        with self._active_lock:
            if self._active_client is not None:
                try:
                    self._active_client.close()
                except Exception:
                    pass
                self._active_client = None

    def send(self, request: SavedRequest, cancel_check: Callable[[], bool] = None) -> HTTPResponse:
        """发送请求并返回响应结果

        Args:
            request: 请求对象
            cancel_check: 可选回调函数，返回 True 表示请求已被取消
        """
        # ── 0. 执行前置处理 (PreProcessor): 动态生成/包装参数、环境变量替换等 ──
        try:
            from app.core.processors import PreProcessor
            request = PreProcessor.process(request)
        except Exception:
            pass

        def _apply_post_processor(res: HTTPResponse) -> HTTPResponse:
            if res and res.status_code > 0:
                try:
                    from app.core.processors import PostProcessor
                    PostProcessor.process(request, res)
                except Exception:
                    pass
            return res

        # ── 1. 统一构建请求头：先载入全局请求头，当前 Tab 中同名 key（大小写不敏感）优先覆盖 ──
        merged_headers = {}
        lower_to_key = {}
        try:
            from app.config.settings import Settings
            for gh in Settings().global_headers:
                if isinstance(gh, dict) and gh.get("enabled", True):
                    k = gh.get("key", "").strip()
                    v = gh.get("value", "")
                    if k or v:
                        merged_headers[k] = v
                        lower_to_key[k.lower()] = k
        except Exception:
            pass

        for h in request.headers:
            if getattr(h, "enabled", True):
                k = getattr(h, "key", "")
                v = getattr(h, "value", "")
                if k or v:
                    k_clean = k.strip()
                    k_lower = k_clean.lower()
                    if k_lower in lower_to_key and lower_to_key[k_lower] != k_clean:
                        merged_headers.pop(lower_to_key[k_lower], None)
                    merged_headers[k_clean] = v
                    lower_to_key[k_lower] = k_clean

        # ── 2. 统一构建 Cookies：按请求 URL 域名自动检索全局 Cookie 库 + Tab 专属 Cookie ──
        merged_cookies = {}
        try:
            from app.widgets.cookie_manager import GlobalCookieStorage
            domain_cookies = GlobalCookieStorage.get_instance().get_cookies_for_url(request.url)
            for c in domain_cookies:
                name = c.get("name") or c.get("key") or ""
                if name:
                    merged_cookies[name] = c.get("value", "")
        except Exception:
            pass

        for c in getattr(request, "cookies", []):
            if isinstance(c, dict):
                k = c.get("name") or c.get("key") or ""
                v = c.get("value") or ""
                if k and c.get("enabled", True):
                    merged_cookies[k] = v

        # ── 3. 统一解析代理策略：接口级代理优先于全局代理 ──
        req_proxy = getattr(request, "proxy", None)
        active_proxy_cfg = None
        if isinstance(req_proxy, dict) and req_proxy.get("mode") and req_proxy.get("mode") != "default":
            active_proxy_cfg = req_proxy
        else:
            try:
                from app.config.settings import Settings
                active_proxy_cfg = Settings().proxy
            except Exception:
                active_proxy_cfg = {"mode": "system"}

        from app.core.proxy_manager import resolve_httpx_proxy
        proxy_url, trust_env = resolve_httpx_proxy(active_proxy_cfg, request.url)
        is_custom_or_direct = active_proxy_cfg.get("mode") in ("none", "direct", "custom", "manual", "pac")

        # 准备 Go 引擎使用的参数列表
        headers_list = [{"key": k, "value": v, "enabled": True} for k, v in merged_headers.items()]
        cookies_list = [{"key": k, "value": v, "enabled": True} for k, v in merged_cookies.items()]
        params_list = [{"key": p.key, "value": p.value, "enabled": p.enabled} for p in request.params if p.key or p.value]

        # 1. 尝试通过 Go 高性能引擎发送（若为直连或自定义代理或已解析出特定代理则交由支持精准代理调度的 httpx 引擎）
        if not is_custom_or_direct and not proxy_url:
            try:
                from app.core.go_engine import GoEngineManager
                engine = GoEngineManager.get_instance()
                if engine.ensure_started():
                    req_payload = {
                        "id": request.id,
                        "name": request.name,
                        "method": request.method,
                        "url": request.url,
                        "headers": headers_list,
                        "params": params_list,
                        "body_type": request.body_type,
                        "body_content": request.body_content,
                        "auth_type": request.auth_type,
                        "auth_config": request.auth_config,
                        "cookies": cookies_list,
                        "timeout": request.timeout,
                    }

                    if cancel_check and cancel_check():
                        return HTTPResponse(error="请求已取消")

                    resp_data = engine.send_with_timing(req_payload)

                    if cancel_check and cancel_check():
                        return HTTPResponse(error="请求已取消")

                    if resp_data.get("error") and resp_data.get("status_code", 0) == 0:
                        return HTTPResponse(error=resp_data.get("error"))

                    resp_cookies = []
                    cookies_dict = resp_data.get("cookies") or {}
                    if isinstance(cookies_dict, dict):
                        for ck, cv in cookies_dict.items():
                            resp_cookies.append({"name": ck, "value": cv})
                    elif isinstance(cookies_dict, list):
                        resp_cookies = cookies_dict

                    # 自动将服务端 Set-Cookie 合并回全局 Cookie 共享池
                    if resp_cookies:
                        try:
                            from app.widgets.cookie_manager import GlobalCookieStorage
                            parsed_host = urlparse(request.url).hostname or ""
                            GlobalCookieStorage.get_instance().merge_cookies(resp_cookies, default_domain=parsed_host)
                        except Exception:
                            pass

                    clean_reason = re.sub(r'^\d{3}\s*', '', str(resp_data.get("reason") or "OK")).strip() or "OK"

                    return _apply_post_processor(HTTPResponse(
                        status_code=resp_data.get("status_code", 200),
                        reason=clean_reason,
                        headers=resp_data.get("headers", {}),
                        body=resp_data.get("body", ""),
                        elapsed_ms=round(resp_data.get("elapsed_ms", 0.0), 2),
                        size_bytes=resp_data.get("size_bytes", len(resp_data.get("body", "").encode("utf-8"))),
                        cookies=resp_cookies,
                        timing=resp_data.get("timing"),
                    ))
            except Exception:
                # Go 引擎不可用时平滑回退到标准 httpx
                pass

        try:
            # 构建 URL（含 query params）
            url = request.url
            params = {}
            for p in request.params:
                if p.enabled and (p.key or p.value):
                    params[p.key] = p.value

            # 使用已合并覆盖后的 headers
            headers = dict(merged_headers)

            # 构建 body
            body_content = None
            data_content = None
            files_content = None

            if request.body_type == BODY_TYPE_JSON:
                body_content = request.body_content
                if "Content-Type" not in headers:
                    headers["Content-Type"] = "application/json"
            elif request.body_type == BODY_TYPE_FORM:
                # multipart/form-data - 使用 files 参数让 httpx 自动处理 boundary
                files_content = self._parse_form_data_to_files(request.body_content)
                # 移除手动设置的 multipart/form-data Content-Type（缺少 boundary）
                # httpx 使用 files 参数时会自动设置正确的 Content-Type 和 boundary
                headers = {k: v for k, v in headers.items()
                           if k.lower() != 'content-type' or 'multipart' not in v.lower()}
            elif request.body_type == BODY_TYPE_URLENCODED:
                # application/x-www-form-urlencoded - 使用 data 参数
                data_content = self._parse_form_data(request.body_content)
                if "Content-Type" not in headers:
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
            elif request.body_type == BODY_TYPE_RAW:
                body_content = request.body_content
            elif request.body_type == BODY_TYPE_BINARY:
                if request.body_content:
                    from pathlib import Path
                    bin_path = Path(request.body_content)
                    if bin_path.is_file():
                        try:
                            body_content = bin_path.read_bytes()
                            if "Content-Type" not in headers:
                                import mimetypes
                                mime, _ = mimetypes.guess_type(str(bin_path))
                                headers["Content-Type"] = mime or "application/octet-stream"
                        except Exception as e:
                            return HTTPResponse(error=f"读取二进制文件失败: {e}")
                    else:
                        return HTTPResponse(error=f"二进制文件不存在: {request.body_content}")

            # 构建 cookies
            req_cookies = {}
            for c in getattr(request, "cookies", []):
                if isinstance(c, dict) and c.get("name"):
                    req_cookies[c["name"]] = c.get("value", "")

            # 构建认证
            auth = None
            if request.auth_type == AUTH_TYPE_BASIC:
                username = request.auth_config.get("username", "")
                password = request.auth_config.get("password", "")
                auth = httpx.BasicAuth(username, password)
            elif request.auth_type == AUTH_TYPE_BEARER:
                token = request.auth_config.get("token", "")
                headers["Authorization"] = f"Bearer {token}"
            elif request.auth_type == AUTH_TYPE_APIKEY:
                key = request.auth_config.get("key", "")
                value = request.auth_config.get("value", "")
                add_to = request.auth_config.get("add_to", "header")
                if add_to == "header":
                    headers[key] = value
                else:
                    params[key] = value

            # Cookies
            req_cookies = dict(merged_cookies)

            # 超时（0 表示无限制）
            timeout = request.timeout / 1000.0 if request.timeout > 0 else None

            # 发送请求 (严格按照当前有效代理策略执行)
            start_time = time.monotonic()
            with httpx.Client(
                proxy=proxy_url,
                trust_env=trust_env,
                timeout=timeout,
                follow_redirects=True,
                verify=False,
            ) as client:
                with self._active_lock:
                    self._active_client = client
                try:
                    resp = client.request(
                        method=request.method,
                        url=url,
                        params=params or None,
                        headers=headers or None,
                        cookies=req_cookies or None,
                        content=body_content,
                        data=data_content,
                        files=files_content,
                        auth=auth,
                    )
                finally:
                    with self._active_lock:
                        self._active_client = None

                # 请求完成后检查是否被取消
                if cancel_check and cancel_check():
                    return HTTPResponse(error="请求已取消")

            elapsed_ms = (time.monotonic() - start_time) * 1000

            # 解析响应
            body_bytes = resp.content
            try:
                body_text = resp.text
            except Exception:
                body_text = body_bytes.decode("utf-8", errors="replace")

            # 提取响应中的 cookies
            resp_cookies = []
            try:
                for c in resp.cookies.jar:
                    resp_cookies.append({
                        "name": c.name,
                        "value": c.value,
                        "domain": getattr(c, "domain", "") or "",
                        "path": getattr(c, "path", "/") or "/",
                        "secure": getattr(c, "secure", False),
                        "expires": str(getattr(c, "expires", "")) if getattr(c, "expires", None) else "",
                    })
                # 自动将服务端 Set-Cookie 合并回全局 Cookie 共享池
                if resp_cookies:
                    from app.widgets.cookie_manager import GlobalCookieStorage
                    parsed_host = urlparse(request.url).hostname or ""
                    GlobalCookieStorage.get_instance().merge_cookies(resp_cookies, default_domain=parsed_host)
            except Exception:
                pass

            clean_reason = re.sub(r'^\d{3}\s*', '', str(resp.reason_phrase or "OK")).strip() or "OK"

            return _apply_post_processor(HTTPResponse(
                status_code=resp.status_code,
                reason=clean_reason,
                headers=dict(resp.headers),
                body=body_text,
                elapsed_ms=round(elapsed_ms, 2),
                size_bytes=len(body_bytes),
                cookies=resp_cookies,
                timing={
                    "total_ms": round(elapsed_ms, 2),
                    "ttfb_ms": round(elapsed_ms, 2),
                },
            ))

        except httpx.TimeoutException:
            return HTTPResponse(error="请求超时，请检查网络连接或增加超时时间")
        except httpx.ConnectError as e:
            return HTTPResponse(error=f"连接失败: {e}")
        except Exception as e:
            if cancel_check and cancel_check():
                return HTTPResponse(error="请求已取消")
            return HTTPResponse(error=f"请求出错: {e}")

    @staticmethod
    def _parse_form_data(content: str) -> dict:
        """解析表单数据（每行 key=value）"""
        data = {}
        for line in content.strip().split("\n"):
            line = line.strip()
            if "=" in line:
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip()
        return data

    @staticmethod
    def _parse_form_data_to_files(content: str) -> list:
        """解析表单数据为 files 格式（用于 multipart/form-data）
        httpx 的 files 参数接受 [(key, (None, value)), ...] 形式，支持重复 key"""
        files = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if "=" in line:
                key, value = line.split("=", 1)
                files.append((key.strip(), (None, value.strip())))
        return files
