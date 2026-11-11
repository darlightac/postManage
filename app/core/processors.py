"""接口前置处理与后置处理引擎
支持：
- 环境变量占位符替换 ({{var}})
- 本地文件读取参数 (JSON / Key-Value / 纯文本)
- 内置函数生成 (UUID, Timestamp, RandomInt, RandomStr, MD5, SHA256, Base64)
- 参数设置到请求头 (Headers) 或 Query 参数
- 响应参数提取 (Header, Cookie, JSONPath, 正则)
- 自动写入全局请求头 (Global Headers), Cookie 存储库, 环境变量
- 同步支持普通请求、高并发压测与嗅探回放
"""

import os
import re
import json
import uuid
import time
import random
import hashlib
import base64
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.core.models import SavedRequest, HTTPResponse, HeaderItem, ParamItem
from app.config.settings import Settings


# ─── 环境变量与全局变量管理 ──────────────────────────────────────────────

class EnvironmentManager:
    """环境变量与全局变量运行时管理器（单例）"""

    _instance: Optional["EnvironmentManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._vars = {}
            cls._instance._load()
        return cls._instance

    def _load(self):
        """从 Settings 载入全局变量"""
        try:
            stored = Settings().get("global_variables", {})
            if isinstance(stored, dict):
                self._vars.update(stored)
        except Exception:
            pass

    def save(self):
        """持久化全局变量"""
        try:
            Settings().set("global_variables", self._vars)
        except Exception:
            pass

    def get(self, key: str, default: str = "") -> str:
        """获取变量值（优先内存/配置，回退系统环境变量）"""
        if key in self._vars:
            return str(self._vars[key])
        return os.environ.get(key, default)

    def set(self, key: str, value: Any, persist: bool = True):
        """设置变量值"""
        self._vars[key] = str(value)
        if persist:
            self.save()

    def get_all(self) -> Dict[str, str]:
        """获取所有当前变量字典"""
        return dict(self._vars)

    def clear(self):
        """清空变量"""
        self._vars.clear()
        self.save()


# ─── 文件读取引擎 ──────────────────────────────────────────────────────────

class FileReader:
    """支持多格式文件的参数读取引擎"""

    @staticmethod
    def read_param_from_file(file_path: str, key: str = "", format_type: str = "auto") -> str:
        """从文件中提取指定参数值

        支持格式：
        - json: JSON 对象文件，通过 key 取值，如 {"token": "abc"}
        - kv: 键值对文本（.env, .txt, .properties），如 token=abc
        - text: 纯文本读取全文
        """
        if not file_path or not str(file_path).strip():
            return ""

        path = Path(file_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            return ""

        try:
            content = path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            try:
                content = path.read_text(encoding="gbk").strip()
            except Exception:
                return ""
        except Exception:
            return ""

        fmt = format_type.lower()
        if fmt == "auto":
            ext = path.suffix.lower()
            if ext == ".json":
                fmt = "json"
            elif ext in (".env", ".properties"):
                fmt = "kv"
            else:
                # 尝试解析为 JSON，否则 fallback
                if content.startswith("{") and content.endswith("}"):
                    fmt = "json"
                elif "=" in content:
                    fmt = "kv"
                else:
                    fmt = "text"

        if fmt == "json":
            try:
                data = json.loads(content)
                if not key:
                    return content
                # 支持简单嵌套提取，如 data.token
                curr = data
                for part in key.split("."):
                    if isinstance(curr, dict) and part in curr:
                        curr = curr[part]
                    else:
                        return ""
                return str(curr)
            except Exception:
                return ""

        elif fmt == "kv":
            if not key:
                return content
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == key.strip():
                        return v.strip().strip("'\"")
            return ""

        else:
            # 纯文本模式
            return content


# ─── 内置计算与加密函数 ──────────────────────────────────────────────────

class BuiltinFunctions:
    """系统支持的动态函数生成器"""

    @staticmethod
    def uuid4() -> str:
        """生成标准 UUID v4"""
        return str(uuid.uuid4())

    @staticmethod
    def timestamp(unit: str = "ms") -> str:
        """生成时间戳 (ms: 13位毫秒, s: 10位秒)"""
        now = time.time()
        if unit == "s":
            return str(int(now))
        return str(int(now * 1000))

    @staticmethod
    def random_int(min_val: int = 1, max_val: int = 100000) -> str:
        """生成指定区间随机整数"""
        if min_val > max_val:
            min_val, max_val = max_val, min_val
        return str(random.randint(min_val, max_val))

    @staticmethod
    def random_string(length: int = 8) -> str:
        """生成指定长度随机英文字符串"""
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        length = max(1, min(length, 256))
        return "".join(random.choice(chars) for _ in range(length))

    @staticmethod
    def md5(text: str) -> str:
        """计算 MD5 32位小写哈希"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def sha256(text: str) -> str:
        """计算 SHA256 64位小写哈希"""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def base64_encode(text: str) -> str:
        """Base64 编码"""
        return base64.b64encode(text.encode("utf-8")).decode("utf-8")

    @staticmethod
    def base64_decode(text: str) -> str:
        """Base64 解码"""
        try:
            return base64.b64decode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    @classmethod
    def evaluate_expression(cls, expr: str, context: Optional[Dict[str, str]] = None) -> str:
        """解析并计算包含变量或简单函数的表达式"""
        if not expr:
            return ""

        ctx = context or {}
        env_mgr = EnvironmentManager()

        # 1. 替换环境变量占位符 {{var}}
        def _replace_var(match):
            var_name = match.group(1).strip()
            # 内置简写函数
            if var_name.lower() in ("$guid", "$uuid", "uuid"):
                return cls.uuid4()
            elif var_name.lower() in ("$timestamp", "timestamp"):
                return cls.timestamp("ms")
            elif var_name.lower() in ("$timestamp_s", "timestamps"):
                return cls.timestamp("s")
            elif var_name.lower() in ("$randomint", "randomint"):
                return cls.random_int()
            elif var_name.lower() in ("$randomstr", "randomstr"):
                return cls.random_string()
            # 上下文或环境变量
            if var_name in ctx:
                return str(ctx[var_name])
            return env_mgr.get(var_name, match.group(0))

        result = re.sub(r"\{\{([^}]+)\}\}", _replace_var, expr)
        result = re.sub(r"\$\{([^}]+)\}", _replace_var, result)

        # 2. 识别函数调用 MD5(...), SHA256(...), Base64Encode(...), RandomInt(min, max)
        func_patterns = [
            (r"^MD5\((.*)\)$", lambda m: cls.md5(m.group(1).strip())),
            (r"^SHA256\((.*)\)$", lambda m: cls.sha256(m.group(1).strip())),
            (r"^Base64Encode\((.*)\)$", lambda m: cls.base64_encode(m.group(1).strip())),
            (r"^Base64Decode\((.*)\)$", lambda m: cls.base64_decode(m.group(1).strip())),
            (r"^UUID\(\)$", lambda m: cls.uuid4()),
            (r"^Timestamp\((.*?)\)$", lambda m: cls.timestamp(m.group(1).strip() or "ms")),
            (r"^RandomInt\((\d+),\s*(\d+)\)$", lambda m: cls.random_int(int(m.group(1)), int(m.group(2)))),
            (r"^RandomString\((\d+)\)$", lambda m: cls.random_string(int(m.group(1)))),
        ]

        trimmed = result.strip()
        for pat, handler in func_patterns:
            m = re.match(pat, trimmed, re.IGNORECASE)
            if m:
                return handler(m)

        return result


# ─── 前置处理器 (Pre-processor) ────────────────────────────────────────────

class PreProcessor:
    """请求前置处理器 - 发送请求前执行参数包装与变量渲染"""

    @classmethod
    def process(cls, request: SavedRequest) -> SavedRequest:
        """执行前置处理，返回渲染/包装后的请求克隆副本，不破坏原始模板"""
        # 复制基础属性
        req_copy = SavedRequest(
            id=request.id,
            collection_id=request.collection_id,
            name=request.name,
            method=request.method,
            url=request.url,
            headers=[HeaderItem(h.key, h.value, h.enabled) for h in request.headers],
            params=[ParamItem(p.key, p.value, p.enabled) for p in request.params],
            body_type=request.body_type,
            body_content=request.body_content,
            auth_type=request.auth_type,
            auth_config=dict(request.auth_config) if request.auth_config else {},
            cookies=list(request.cookies) if request.cookies else [],
            timeout=request.timeout,
            sort_order=request.sort_order,
            pre_script=dict(getattr(request, "pre_script", {})) if getattr(request, "pre_script", None) else {},
            post_script=dict(getattr(request, "post_script", {})) if getattr(request, "post_script", None) else {},
            proxy=dict(getattr(request, "proxy", {})) if getattr(request, "proxy", None) else {},
        )

        pre_cfg = req_copy.pre_script
        rules = pre_cfg.get("rules", []) if isinstance(pre_cfg, dict) else []
        local_context: Dict[str, str] = {}

        # 1. 逐条执行前置配置规则
        for rule in rules:
            if not isinstance(rule, dict) or not rule.get("enabled", True):
                continue

            source_type = rule.get("source_type", "env").lower()
            target_type = rule.get("target_type", "header").lower()
            target_name = rule.get("target_name", "").strip()

            val = ""
            if source_type == "env":
                # 从环境变量/表达式中提取
                expr = rule.get("expression", "")
                val = BuiltinFunctions.evaluate_expression(expr, local_context)

            elif source_type == "file":
                # 从本地文件读取
                fpath = rule.get("file_path", "")
                fkey = rule.get("file_key", "")
                ffmt = rule.get("file_format", "auto")
                val = FileReader.read_param_from_file(fpath, fkey, ffmt)

            elif source_type == "function":
                # 函数生成
                fname = rule.get("func_name", "UUID")
                fargs = rule.get("func_args", "")
                expr = f"{fname}({fargs})" if fargs else f"{fname}()"
                val = BuiltinFunctions.evaluate_expression(expr, local_context)

            elif source_type == "custom":
                val = BuiltinFunctions.evaluate_expression(rule.get("expression", ""), local_context)

            # 注入目标
            if target_type == "header" and target_name:
                # 添加或替换请求头
                found = False
                for h in req_copy.headers:
                    if h.key.strip().lower() == target_name.lower():
                        h.value = val
                        h.enabled = True
                        found = True
                        break
                if not found:
                    req_copy.headers.append(HeaderItem(key=target_name, value=val, enabled=True))

            elif target_type == "param" and target_name:
                # 添加或替换 Query 参数
                found = False
                for p in req_copy.params:
                    if p.key.strip().lower() == target_name.lower():
                        p.value = val
                        p.enabled = True
                        found = True
                        break
                if not found:
                    req_copy.params.append(ParamItem(key=target_name, value=val, enabled=True))

            elif target_type == "body" and target_name:
                cls._inject_into_body(req_copy, target_name, val)

            elif target_type == "variable" and target_name:
                # 保存至临时上下文，供后续规则或 URL/Body 占位符渲染
                local_context[target_name] = val
                # 也写入环境运行时
                EnvironmentManager().set(target_name, val, persist=False)

        # 2. 全局占位符替换 (URL, Headers, Params, Body)
        env_mgr = EnvironmentManager()
        def _render(s: str) -> str:
            if not s or "{{" not in s:
                return s
            return BuiltinFunctions.evaluate_expression(s, local_context)

        req_copy.url = _render(req_copy.url)
        for h in req_copy.headers:
            h.value = _render(h.value)
        for p in req_copy.params:
            p.value = _render(p.value)
        if req_copy.body_type not in ("none", "binary"):
            req_copy.body_content = _render(req_copy.body_content)

        return req_copy

    @classmethod
    def _inject_into_body(cls, req: SavedRequest, target_name: str, val: Any):
        """将参数组装注入到请求体中，若已存在相同字段则覆盖"""
        if not target_name:
            return

        b_type = (req.body_type or "none").lower()

        # 若当前 body_type 为 none 或空，自动转为 json
        if b_type in ("none", ""):
            req.body_type = "json"
            data = {}
            cls._set_nested_dict_value(data, target_name, val)
            req.body_content = json.dumps(data, ensure_ascii=False, indent=2)
            return

        # 1. JSON 格式
        if b_type == "json":
            raw_text = (req.body_content or "").strip()
            data = {}
            if raw_text:
                try:
                    parsed = json.loads(raw_text)
                    if isinstance(parsed, dict):
                        data = parsed
                    else:
                        data = {"_root": parsed}
                except Exception:
                    data = {}

            cls._set_nested_dict_value(data, target_name, val)
            req.body_content = json.dumps(data, ensure_ascii=False, indent=2)
            return

        # 2. Form 或 Urlencoded 格式 (每行 key=value)
        if b_type in ("form", "urlencoded"):
            raw_text = req.body_content or ""
            lines = raw_text.splitlines()
            found = False
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if "=" in stripped:
                    k, _ = stripped.split("=", 1)
                    if k.strip().lower() == target_name.lower():
                        new_lines.append(f"{target_name}={val}")
                        found = True
                        continue
                new_lines.append(line)

            if not found:
                if new_lines and new_lines[-1].strip():
                    new_lines.append(f"{target_name}={val}")
                else:
                    if not new_lines:
                        new_lines.append(f"{target_name}={val}")
                    else:
                        new_lines[-1] = f"{target_name}={val}"

            req.body_content = "\n".join(new_lines)
            return

        # 3. Raw 格式
        if b_type == "raw":
            raw_text = (req.body_content or "").strip()
            # 尝试作为 JSON 处理
            if (raw_text.startswith("{") and raw_text.endswith("}")) or not raw_text:
                try:
                    data = json.loads(raw_text) if raw_text else {}
                    if isinstance(data, dict):
                        cls._set_nested_dict_value(data, target_name, val)
                        req.body_content = json.dumps(data, ensure_ascii=False, indent=2)
                        return
                except Exception:
                    pass

            # 尝试作为 key=value 替换
            if "=" in raw_text:
                lines = raw_text.splitlines()
                found = False
                new_lines = []
                for line in lines:
                    if "=" in line:
                        k, _ = line.split("=", 1)
                        if k.strip().lower() == target_name.lower():
                            new_lines.append(f"{target_name}={val}")
                            found = True
                            continue
                    new_lines.append(line)
                if not found:
                    new_lines.append(f"{target_name}={val}")
                req.body_content = "\n".join(new_lines)
                return

            req.body_content = f"{raw_text}\n{target_name}={val}".strip()

    @classmethod
    def _set_nested_dict_value(cls, data: dict, path: str, val: Any):
        """支持将值按点号路径 (e.g. 'token' 或 'data.user.id') 注入到字典中，并智能转换/保留类型"""
        parts = [p.strip() for p in path.split(".") if p.strip()]
        if not parts:
            return

        curr = data
        for part in parts[:-1]:
            if part not in curr or not isinstance(curr[part], dict):
                curr[part] = {}
            curr = curr[part]

        last_key = parts[-1]

        # 智能类型匹配与转换
        parsed_val = val
        if last_key in curr:
            orig = curr[last_key]
            if isinstance(orig, bool) and isinstance(val, str):
                if val.lower() in ("true", "1"):
                    parsed_val = True
                elif val.lower() in ("false", "0"):
                    parsed_val = False
            elif isinstance(orig, int) and not isinstance(orig, bool) and isinstance(val, str):
                try:
                    parsed_val = int(val)
                except ValueError:
                    parsed_val = val
            elif isinstance(orig, float) and isinstance(val, str):
                try:
                    parsed_val = float(val)
                except ValueError:
                    parsed_val = val
            elif isinstance(orig, (dict, list)) and isinstance(val, str):
                try:
                    parsed_val = json.loads(val)
                except Exception:
                    parsed_val = val
        else:
            if isinstance(val, str):
                trimmed = val.strip()
                if (trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]")):
                    try:
                        parsed_val = json.loads(trimmed)
                    except Exception:
                        parsed_val = val

        curr[last_key] = parsed_val


# ─── 后置处理器 (Post-processor) ───────────────────────────────────────────

class PostProcessor:
    """请求后置处理器 - 收到响应后从响应中提取参数并回写"""

    @classmethod
    def process(cls, request: SavedRequest, response: HTTPResponse) -> Dict[str, Any]:
        """执行后置处理规则，返回所有提取到的键值字典"""
        post_cfg = getattr(request, "post_script", {})
        if not isinstance(post_cfg, dict):
            return {}

        rules = post_cfg.get("rules", [])
        if not rules:
            return {}

        extracted_results: Dict[str, Any] = {}

        for rule in rules:
            if not isinstance(rule, dict) or not rule.get("enabled", True):
                continue

            extract_from = rule.get("extract_from", "body_jsonpath").lower()
            expression = rule.get("expression", "").strip()
            dest = rule.get("target_destination", "global_headers").lower()
            target_key = rule.get("target_key", "").strip()

            if not expression or not target_key:
                continue

            val = cls._extract_value(extract_from, expression, response)
            if val is not None:
                str_val = str(val)
                extracted_results[target_key] = str_val

                # 写入目标目的地
                if dest == "global_headers":
                    cls._write_to_global_headers(target_key, str_val)
                elif dest == "cookies":
                    cls._write_to_cookies(request.url, target_key, str_val)
                elif dest in ("environment", "env"):
                    EnvironmentManager().set(target_key, str_val, persist=True)

        return extracted_results

    @classmethod
    def _extract_value(cls, extract_from: str, expression: str, response: HTTPResponse) -> Optional[str]:
        """按配置从响应中提取值，支持直接表达式与 `${...}` 占位符自定义文本组装 (如 'Bearer ${data.body}')"""
        if not expression:
            return None

        # 检查是否包含 ${...} 占位符
        placeholders = re.findall(r"\$\{([^}]+)\}", expression)
        if placeholders:
            result = expression
            for ph in placeholders:
                ph_clean = ph.strip()
                extracted_part = cls._resolve_placeholder(extract_from, ph_clean, response)
                if extracted_part is None:
                    # 关键占位符无法提取到值
                    return None
                result = result.replace(f"${{{ph}}}", str(extracted_part))
            return result

        # 不含 ${...} 占位符，走原生单项提取
        return cls._resolve_placeholder(extract_from, expression, response)

    @classmethod
    def _resolve_placeholder(cls, extract_from: str, expr: str, response: HTTPResponse) -> Optional[str]:
        """从响应中解析单个字段/表达式的值"""
        try:
            expr_trimmed = expr.strip()
            expr_lower = expr_trimmed.lower()

            if extract_from == "header":
                # 从响应头提取
                for k, v in response.headers.items():
                    if k.lower() == expr_lower:
                        return str(v)
                return None

            elif extract_from == "cookie":
                # 从响应 Cookie 提取
                cookies = getattr(response, "cookies", {})
                if isinstance(cookies, dict):
                    c_val = cookies.get(expr_trimmed)
                    return str(c_val) if c_val is not None else None
                elif isinstance(cookies, list):
                    for c in cookies:
                        if isinstance(c, dict) and (c.get("name") == expr_trimmed or c.get("key") == expr_trimmed):
                            return str(c.get("value"))
                return None

            elif extract_from == "body_regex":
                # 从响应体正则表达式提取
                body = getattr(response, "body", "") or getattr(response, "body_text", "") or ""
                m = re.search(expr_trimmed, body)
                if m:
                    return str(m.group(1) if m.groups() else m.group(0))
                return None

            elif extract_from == "body_text":
                # 全文提取
                return getattr(response, "body", "") or getattr(response, "body_text", "") or ""

            elif extract_from == "body_jsonpath":
                # 从响应体 JSONPath 提取
                body = getattr(response, "body", "") or getattr(response, "body_text", "") or ""
                if not body:
                    return None

                parsed_json = None
                try:
                    parsed_json = json.loads(body)
                except Exception:
                    parsed_json = None

                if parsed_json is not None:
                    res = cls._eval_jsonpath(parsed_json, expr_trimmed)
                    if res is not None:
                        return str(res)

                    # 若未命中，支持 data.body / body / text 等别名平滑回退
                    if expr_lower in ("data.body", "body", "text", "content", "raw_body", "response.body"):
                        if isinstance(parsed_json, dict) and "data" in parsed_json:
                            d_val = parsed_json["data"]
                            if isinstance(d_val, (str, int, float, bool)):
                                return str(d_val)
                            elif isinstance(d_val, dict) and "body" in d_val:
                                return str(d_val["body"])
                        return body
                    return None
                else:
                    # 纯文本响应（非 JSON）
                    if expr_lower in ("data.body", "body", "text", "content", "raw_body", "response.body", "val", "value"):
                        return body
                    return None

            else:
                return getattr(response, "body", "") or getattr(response, "body_text", "") or ""

        except Exception:
            return None

    @classmethod
    def _eval_jsonpath(cls, data: Any, path: str) -> Optional[Any]:
        """轻量高性能 JSONPath 求值器 (支持 $.data.token, data.token, items[0].id 等)"""
        clean_path = path.strip()
        if clean_path.startswith("$."):
            clean_path = clean_path[2:]
        elif clean_path.startswith("$"):
            clean_path = clean_path[1:]

        if not clean_path:
            return str(data)

        # 将 a[0].b 统一转换为 a.0.b 格式
        normalized = re.sub(r"\[(\d+)\]", r".\1", clean_path)
        parts = [p.strip() for p in normalized.split(".") if p.strip()]

        curr = data
        for part in parts:
            if isinstance(curr, dict):
                if part in curr:
                    curr = curr[part]
                else:
                    return None
            elif isinstance(curr, (list, tuple)):
                try:
                    idx = int(part)
                    if 0 <= idx < len(curr):
                        curr = curr[idx]
                    else:
                        return None
                except ValueError:
                    return None
            else:
                return None

        return str(curr) if curr is not None else None

    @staticmethod
    def _write_to_global_headers(header_name: str, header_value: str):
        """将提取值写入全局请求头"""
        try:
            settings = Settings()
            ghs = list(settings.global_headers)
            found = False
            for item in ghs:
                if isinstance(item, dict) and item.get("key", "").strip().lower() == header_name.lower():
                    item["value"] = header_value
                    item["enabled"] = True
                    found = True
                    break
            if not found:
                ghs.append({"key": header_name, "value": header_value, "enabled": True})
            settings.global_headers = ghs
        except Exception:
            pass

    @staticmethod
    def _write_to_cookies(url: str, cookie_name: str, cookie_value: str):
        """将提取值写入全局 Cookie 存储库"""
        try:
            from app.widgets.cookie_manager import GlobalCookieStorage
            from urllib.parse import urlparse
            domain = urlparse(url).hostname or "localhost"
            GlobalCookieStorage.get_instance().set_cookie(domain, cookie_name, cookie_value)
        except Exception:
            pass
