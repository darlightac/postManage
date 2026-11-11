"""代理管理器 - 系统代理检测、PAC 解析、直连与自定义代理调度"""

import os
import re
import socket
import urllib.request
from urllib.parse import urlparse
from typing import Optional, Tuple, Dict, Any

from app.core.logger import get_logger

logger = get_logger("proxy_manager")

# PAC 脚本内存缓存 (URL -> (fetch_time, pac_text))
_PAC_CACHE: Dict[str, Tuple[float, str]] = {}


def get_system_proxy_info() -> Dict[str, Any]:
    """获取当前操作系统的系统代理配置与状态"""
    info = {
        "enabled": False,
        "server": "",
        "http": "",
        "https": "",
        "bypass": "",
        "pac_url": "",
        "source": "none",
        "description": "未检测到系统代理 (直连)",
    }

    # 1. 优先尝试从 Windows 注册表读取 Internet Settings
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            try:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                info["enabled"] = bool(enabled)
            except OSError:
                pass

            try:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
                info["server"] = str(server).strip() if server else ""
            except OSError:
                pass

            try:
                override, _ = winreg.QueryValueEx(key, "ProxyOverride")
                info["bypass"] = str(override).strip() if override else ""
            except OSError:
                pass

            try:
                pac, _ = winreg.QueryValueEx(key, "AutoConfigURL")
                info["pac_url"] = str(pac).strip() if pac else ""
            except OSError:
                pass

        if info["enabled"] and info["server"]:
            info["source"] = "windows_registry"
            server = info["server"]
            if "=" in server:
                for part in server.split(";"):
                    if "=" in part:
                        proto, s_url = part.split("=", 1)
                        proto = proto.strip().lower()
                        s_url = s_url.strip()
                        if not s_url.startswith("http://") and not s_url.startswith("https://") and not s_url.startswith("socks5://"):
                            s_url = f"http://{s_url}"
                        if proto == "http":
                            info["http"] = s_url
                        elif proto == "https":
                            info["https"] = s_url
            else:
                s_url = server
                if not s_url.startswith("http://") and not s_url.startswith("https://") and not s_url.startswith("socks5://"):
                    s_url = f"http://{s_url}"
                info["http"] = s_url
                info["https"] = s_url

            info["description"] = f"Windows 系统代理已启用: {info['server']}"
            return info
        elif info["pac_url"]:
            info["source"] = "windows_pac"
            info["description"] = f"Windows 系统自动代理 (PAC): {info['pac_url']}"
            return info
    except Exception as e:
        logger.debug(f"读取 Windows 注册表代理失败: {e}")

    # 2. 尝试从 urllib / 系统环境变量检测
    try:
        proxies = urllib.request.getproxies()
        http_p = proxies.get("http") or proxies.get("all")
        https_p = proxies.get("https") or proxies.get("all")
        if http_p or https_p:
            info["enabled"] = True
            info["http"] = http_p or ""
            info["https"] = https_p or ""
            info["server"] = http_p or https_p or ""
            info["source"] = "environment"
            info["description"] = f"环境变量系统代理: {info['server']}"
            return info
    except Exception:
        pass

    return info


def is_host_bypassed(target_host: str, bypass_rules: str) -> bool:
    """检查目标主机是否匹配绕过代理列表 (No Proxy / Bypass)"""
    if not target_host or not bypass_rules:
        return False

    host = target_host.strip().lower()
    # 本地环回默认通常被大部分系统 bypass
    rules = [r.strip().lower() for r in re.split(r"[;,\s]+", bypass_rules) if r.strip()]

    for rule in rules:
        if rule == "<local>" and (host in ("localhost", "127.0.0.1", "::1") or "." not in host):
            return True
        if rule in ("localhost", "127.0.0.1", "::1") and host in ("localhost", "127.0.0.1", "::1"):
            return True
        if rule.startswith("*."):
            domain = rule[2:]
            if host == domain or host.endswith("." + domain):
                return True
        if rule.startswith("."):
            domain = rule[1:]
            if host == domain or host.endswith("." + domain):
                return True
        if host == rule:
            return True
        # IP 段简易通配，例如 192.168.*
        if "*" in rule:
            pattern = re.escape(rule).replace(r"\*", ".*")
            if re.fullmatch(pattern, host):
                return True

    return False


def fetch_pac_content(pac_url: str, timeout: float = 4.0) -> str:
    """获取 PAC 脚本内容 (支持 http/https/file)，始终使用直连拉取 PAC 避免被代理环路阻断"""
    import time
    pac_url = (pac_url or "").strip()
    if not pac_url:
        return ""

    now = time.time()
    if pac_url in _PAC_CACHE:
        cache_time, text = _PAC_CACHE[pac_url]
        if now - cache_time < 300:  # 缓存 5 分钟
            return text

    text = ""
    try:
        if pac_url.startswith("file://") or os.path.isfile(pac_url):
            path = pac_url[7:] if pac_url.startswith("file://") else pac_url
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        elif pac_url.startswith("http://") or pac_url.startswith("https://"):
            # 使用空 ProxyHandler 确保直连拉取 PAC 脚本本身（特别是 127.0.0.1 类似本地服务器）
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(pac_url, headers={"User-Agent": "PostManage-PAC-Engine/1.0"})
            with opener.open(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"获取 PAC 脚本失败 ({pac_url}): {e}")

    if text:
        _PAC_CACHE[pac_url] = (now, text)
    return text


import fnmatch
import ipaddress


class JSString(str):
    """支持 JavaScript 字符串常见方法的字符串封装，供 PAC 脚本无缝调用"""
    def substring(self, start: int, end: Optional[int] = None):
        if end is None:
            return JSString(self[start:])
        return JSString(self[start:end])

    def substr(self, start: int, length: Optional[int] = None):
        if length is None:
            return JSString(self[start:])
        return JSString(self[start:start + length])

    def indexOf(self, sub: str) -> int:
        return self.find(sub)

    def toLowerCase(self):
        return JSString(super().lower())

    def toUpperCase(self):
        return JSString(super().upper())


def shExpMatch(s: str, pat: str) -> bool:
    """PAC 标准函数: 通配符匹配 (如 *.example.com, 10.111.*)"""
    return fnmatch.fnmatch(str(s).lower(), str(pat).lower())


def dnsDomainIs(host: str, domain: str) -> bool:
    """PAC 标准函数: 域名后缀匹配"""
    h = str(host).lower()
    d = str(domain).lower()
    if not d.startswith("."):
        d = "." + d
    return h.endswith(d) or h == d.lstrip(".")


def isPlainHostName(host: str) -> bool:
    """PAC 标准函数: 是否为无点单标签主机名"""
    return "." not in str(host)


def isInNet(ip: str, net: str, mask: str) -> bool:
    """PAC 标准函数: 判断 IP 是否位于指定子网"""
    try:
        network = ipaddress.IPv4Network(f"{net}/{mask}", strict=False)
        return ipaddress.IPv4Address(ip) in network
    except Exception:
        return False


def localHostOrDomainIs(host: str, hostdom: str) -> bool:
    """PAC 标准函数: 匹配主机名或完整主机域名"""
    h = str(host).lower()
    hd = str(hostdom).lower()
    return h == hd or hd.startswith(h + ".")


def dnsResolve(host: str) -> str:
    """PAC 标准函数: 解析主机为 IP"""
    try:
        return socket.gethostbyname(host)
    except Exception:
        return ""


def myIpAddress() -> str:
    """PAC 标准函数: 获取本机 IP"""
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def _normalize_target_url(target_url: str) -> Tuple[str, str]:
    """标准化 URL 并提取 hostname（即便未带协议头如 10.111.212.130 也可准确识别 host）"""
    u = (target_url or "").strip()
    if not u:
        return "", ""
    if "://" not in u:
        parsed = urlparse(f"http://{u}")
    else:
        parsed = urlparse(u)
    host = (parsed.hostname or "").lower()
    return u, host


def _eval_pac_condition(cond: str, env: Dict[str, Any]) -> bool:
    """安全解析 PAC 条件表达式（支持 compound 逻辑: ||, &&, ! 以及函数调用）"""
    cond = cond.strip()
    if not cond:
        return False

    # 1. 转换 JS 常见语法为 Python 语法
    py_expr = cond.replace("||", " or ").replace("&&", " and ")
    py_expr = py_expr.replace("===", " == ").replace("!==", " != ")
    py_expr = re.sub(r'\btrue\b', 'True', py_expr, flags=re.IGNORECASE)
    py_expr = re.sub(r'\bfalse\b', 'False', py_expr, flags=re.IGNORECASE)

    try:
        return bool(eval(py_expr, {"__builtins__": {}}, env))
    except Exception:
        pass

    # 2. 降级容错: 提取所有 shExpMatch 逐项评估
    host = env.get("host", "")
    url = env.get("url", "")
    for m in re.finditer(r'shExpMatch\s*\(\s*(host|url)\s*,\s*["\']([^"\']+)["\']\s*\)', cond, re.IGNORECASE):
        target = host if m.group(1).lower() == "host" else url
        pat = m.group(2)
        if fnmatch.fnmatch(str(target), pat):
            return True

    # 域名匹配降级
    for m in re.finditer(r'dnsDomainIs\s*\(\s*host\s*,\s*["\']([^"\']+)["\']\s*\)', cond, re.IGNORECASE):
        if dnsDomainIs(host, m.group(1)):
            return True

    return False


def evaluate_pac_script(pac_script: str, target_url: str) -> Optional[str]:
    """解析 PAC 脚本并决策目标 URL 的代理模式

    返回:
        "DIRECT" 表示直连
        "http://host:port" 或 "socks5://host:port" 表示具体代理
    """
    if not pac_script:
        return "DIRECT"

    url_str, host_str = _normalize_target_url(target_url)
    if not host_str:
        return "DIRECT"

    # 简单内网/本地环回直连规则预检
    if host_str in ("localhost", "127.0.0.1", "::1"):
        return "DIRECT"

    env: Dict[str, Any] = {
        "url": JSString(url_str),
        "host": JSString(host_str),
        "shExpMatch": shExpMatch,
        "dnsDomainIs": dnsDomainIs,
        "isPlainHostName": isPlainHostName,
        "isInNet": isInNet,
        "localHostOrDomainIs": localHostOrDomainIs,
        "dnsResolve": dnsResolve,
        "myIpAddress": myIpAddress,
    }

    def _convert_directive(directive: str) -> str:
        d = directive.strip().strip(";").strip('"').strip("'").strip()
        parts = [p.strip().strip('"').strip("'").strip() for p in d.split(";") if p.strip()]
        for p in parts:
            up = p.upper()
            if up == "DIRECT":
                return "DIRECT"
            m = re.match(r'^(PROXY|SOCKS5|SOCKS|HTTPS|HTTP)\s+([a-zA-Z0-9_\-\.]+:\d+)', p, re.IGNORECASE)
            if m:
                proto = m.group(1).upper()
                addr = m.group(2)
                if proto in ("SOCKS5", "SOCKS"):
                    return f"socks5://{addr}"
                return f"http://{addr}"
        return "DIRECT"

    # 1. 逐个提取 if (...) return ...; 或 if (...) { return ...; }
    def _extract_control_blocks(script: str):
        idx = 0
        while True:
            m = re.search(r'\bif\s*\(', script[idx:], re.IGNORECASE)
            if not m:
                break
            start_cond = idx + m.end()
            depth = 1
            pos = start_cond
            while pos < len(script) and depth > 0:
                if script[pos] == '(':
                    depth += 1
                elif script[pos] == ')':
                    depth -= 1
                pos += 1
            if depth == 0:
                cond = script[start_cond:pos - 1].strip()
                rest = script[pos:]
                m_ret = re.search(r'^\s*\{?[^}]*?return\s+([^;\}]+);?', rest, re.IGNORECASE)
                if m_ret:
                    yield cond, m_ret.group(1).strip()
            idx = pos

    for cond_expr, ret_val in _extract_control_blocks(pac_script):
        if _eval_pac_condition(cond_expr, env):
            return _convert_directive(ret_val)

    # 2. 检查兜底 return (使用函数末尾最后一个兜底 return 语句)
    all_returns = re.findall(r'return\s+([^;\}]+);?', pac_script, re.IGNORECASE)
    if all_returns:
        return _convert_directive(all_returns[-1])

    return "DIRECT"


def resolve_httpx_proxy(proxy_cfg: Optional[Dict[str, Any]], target_url: str = "") -> Tuple[Optional[str], bool]:
    """根据代理配置解析出 httpx.Client 所需的 (proxy_url, trust_env)

    返回值:
        (proxy_url, trust_env):
        - proxy_url: str 格式的代理 URL，或 None
        - trust_env: bool 是否信任系统环境变量
    """
    cfg = proxy_cfg or {}
    mode = cfg.get("mode", "system")

    # 1. 直连无代理
    if mode in ("none", "direct"):
        return None, False

    # 2. 系统代理 (默认)
    if mode == "system":
        sys_info = get_system_proxy_info()

        # A. 若 Windows 开启了 PAC 自动配置脚本 (AutoConfigURL)，自动执行 PAC 决策
        if sys_info.get("pac_url"):
            pac_text = fetch_pac_content(sys_info["pac_url"])
            if pac_text:
                res = evaluate_pac_script(pac_text, target_url)
                if res and res != "DIRECT":
                    return res, False
                return None, False

        # B. 若 Windows 配置了固定代理服务器 (ProxyServer)
        if sys_info.get("enabled"):
            target_url_norm, target_host = _normalize_target_url(target_url)
            target_parsed = urlparse(target_url_norm)
            target_scheme = (target_parsed.scheme or "http").lower()

            # 检查系统 bypass
            if sys_info.get("bypass") and is_host_bypassed(target_host, sys_info["bypass"]):
                return None, False

            proxy_target = sys_info.get(target_scheme) or sys_info.get("http") or sys_info.get("https")
            if proxy_target:
                return proxy_target, True

        return None, True

    # 3. PAC 模式
    if mode == "pac":
        pac_url = cfg.get("pac_url", "").strip()
        pac_text = cfg.get("pac_content", "").strip()
        if pac_url and not pac_text:
            pac_text = fetch_pac_content(pac_url)
        if pac_text:
            res = evaluate_pac_script(pac_text, target_url)
            if res and res != "DIRECT":
                return res, False
        # PAC 解析为 DIRECT 或无有效代理时直连
        return None, False

    # 4. 手动/自定义代理
    if mode in ("custom", "manual"):
        proto = (cfg.get("protocol") or "HTTP").lower()
        server = (cfg.get("server") or "").strip()
        host = (cfg.get("host") or "").strip()
        port = str(cfg.get("port") or "").strip()
        all_proxy = (cfg.get("all_proxy") or "").strip()

        # 检查绕过代理主机列表
        bypass = cfg.get("bypass", "")
        if target_url:
            _, t_host = _normalize_target_url(target_url)
            if t_host and is_host_bypassed(t_host, bypass):
                return None, False

        # 如果直接给出了完整 URL 或 server 地址
        target_server = all_proxy or server
        if target_server:
            proxy_url = target_server
            if not (proxy_url.startswith("http://") or proxy_url.startswith("https://") or proxy_url.startswith("socks5://")):
                u = cfg.get("username", "").strip()
                p = cfg.get("password", "")
                auth_part = f"{u}:{p}@" if (u and (cfg.get("auth_enabled") or p or u)) else ""
                proxy_url = f"{proto}://{auth_part}{proxy_url}"
            return proxy_url, False

        if host and port:
            auth_part = ""
            if cfg.get("auth_enabled") or cfg.get("username"):
                u = cfg.get("username", "").strip()
                p = cfg.get("password", "")
                if u:
                    auth_part = f"{u}:{p}@"
            proxy_url = f"{proto}://{auth_part}{host}:{port}"
            return proxy_url, False

    # 兜底系统代理
    return None, True
