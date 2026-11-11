"""cURL 命令解析与导入"""

import shlex
from urllib.parse import urlparse, parse_qs

from app.core.models import SavedRequest, HeaderItem, ParamItem


def parse_curl(curl_command: str) -> SavedRequest:
    """解析 cURL 命令字符串为 SavedRequest 对象

    支持的 cURL 参数:
        -X, --request     HTTP 方法
        -H, --header      请求头
        -d, --data        请求体
        --data-raw        原始请求体
        --data-urlencode  URL 编码数据
        -F, --form        表单字段（form-data）
        -u, --user        Basic Auth (user:password)
        -k, --insecure    忽略 SSL（记录但不处理）
        --compressed      压缩（忽略）
        -L, --location    跟随重定向（默认已启用）
        --max-time        超时
    """
    # 清理命令：移除换行符和反斜杠续行符
    cmd = curl_command.strip()
    # 将多行 cURL 命令合并为单行
    cmd = cmd.replace("\\\n", " ").replace("\\\r\n", " ").replace("\\", " ")
    # 规范化空白字符
    import re
    cmd = re.sub(r'\s+', ' ', cmd).strip()
    
    if cmd.lower().startswith("curl "):
        cmd = cmd[5:].strip()
    elif cmd.lower().startswith("curl\t"):
        cmd = cmd[5:].strip()

    try:
        tokens = shlex.split(cmd)
    except ValueError:
        # 如果 shlex 解析失败，尝试简单分割
        tokens = cmd.split()

    method = None
    url = ""
    headers = []
    data_parts = []
    data_mode = "raw"
    form_fields = []  # --form / -F 收集的表单字段 (key, value)
    auth_type = "none"
    auth_config = {}
    timeout = 30000

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token in ("-X", "--request") and i + 1 < len(tokens):
            method = tokens[i + 1].upper()
            i += 2
        elif token in ("-H", "--header") and i + 1 < len(tokens):
            header_str = tokens[i + 1]
            if ":" in header_str:
                key, value = header_str.split(":", 1)
                headers.append(HeaderItem(key=key.strip(), value=value.strip()))
            i += 2
        elif token in ("-d", "--data", "--data-raw") and i + 1 < len(tokens):
            data_parts.append(tokens[i + 1])
            data_mode = "raw"
            i += 2
        elif token == "--data-binary" and i + 1 < len(tokens):
            # @filename 格式暂不支持，跳过
            if not tokens[i + 1].startswith("@"):
                data_parts.append(tokens[i + 1])
            data_mode = "raw"
            i += 2
        elif token == "--data-urlencode" and i + 1 < len(tokens):
            data_parts.append(tokens[i + 1])
            data_mode = "urlencoded"
            i += 2
        elif token in ("-F", "--form", "--form-string") and i + 1 < len(tokens):
            field = tokens[i + 1]
            if "=" in field:
                fkey, fval = field.split("=", 1)
                # @开头为文件上传字段，编辑器暂不支持，跳过
                if not fval.startswith("@"):
                    # 去掉值两侧包裹的引号（如 page="1" → page=1）
                    fval = fval.strip()
                    if len(fval) >= 2 and fval[0] == fval[-1] and fval[0] in ('"', "'"):
                        fval = fval[1:-1]
                    form_fields.append((fkey.strip(), fval))
            i += 2
        elif token in ("-u", "--user") and i + 1 < len(tokens):
            user_pass = tokens[i + 1]
            if ":" in user_pass:
                username, password = user_pass.split(":", 1)
                auth_type = "basic"
                auth_config = {"username": username, "password": password}
            i += 2
        elif token in ("--max-time", "--connect-timeout") and i + 1 < len(tokens):
            try:
                timeout = int(float(tokens[i + 1]) * 1000)
            except ValueError:
                pass
            i += 2
        elif token.startswith("-") and len(token) > 1 and token[1] not in "-":
            # 短选项组合，如 -kL
            skip = False
            for ch in token[1:]:
                if ch == "X" and i + 1 < len(tokens):
                    pass  # 需要特殊处理，简化跳过
                elif ch == "k":
                    pass  # insecure，忽略
                elif ch == "L":
                    pass  # follow redirects，默认已启用
                elif ch in ("d", "u"):
                    # 需要下一个 token 作为参数
                    if i + 1 < len(tokens):
                        if ch == "d":
                            data_parts.append(tokens[i + 1])
                        elif ch == "u":
                            user_pass = tokens[i + 1]
                            if ":" in user_pass:
                                username, password = user_pass.split(":", 1)
                                auth_type = "basic"
                                auth_config = {"username": username, "password": password}
                        i += 1
            i += 1
        elif token in ("-k", "--insecure", "--compressed", "-L", "--location",
                        "--verbose", "-v", "-s", "--silent", "-o", "--output"):
            # 忽略的选项
            if token in ("-o", "--output") and i + 1 < len(tokens):
                i += 2
            else:
                i += 1
        elif not token.startswith("-"):
            # 这是 URL
            url = token
            i += 1
        else:
            i += 1

    # 确定 URL 和 params
    params = []
    if url:
        parsed = urlparse(url)
        if parsed.query:
            qs = parse_qs(parsed.query, keep_blank_values=True)
            for key, values in qs.items():
                for val in values:
                    params.append(ParamItem(key=key, value=val))
            url = url.split("?")[0]

    # 确定 body（--form 优先于 --data）
    body_content = ""
    body_type = "none"
    if form_fields:
        body_type = "form"
        body_content = "\n".join(f"{k}={v}" for k, v in form_fields)
    elif data_parts:
        if data_mode == "urlencoded":
            body_type = "urlencoded"
            body_content = "\n".join(data_parts)
        else:
            body_content = "&".join(data_parts) if data_mode == "raw" and "=" in data_parts[0] and not data_parts[0].strip().startswith("{") else "".join(data_parts)
            # 检测 JSON
            combined = "".join(data_parts)
            if combined.strip().startswith("{") or combined.strip().startswith("["):
                body_type = "json"
                body_content = combined
            else:
                body_type = "raw"
                body_content = combined

    # 确定 method（curl 规则：有 --form / --data 时默认 POST，显式 -X 优先）
    if method is None:
        method = "POST" if (form_fields or data_parts) else "GET"

    # 自动添加 Content-Type（如果有 body 且没有 Content-Type header）
    has_content_type = any(h.key.lower() == "content-type" for h in headers)
    if not has_content_type:
        if body_type == "json":
            headers.append(HeaderItem(key="Content-Type", value="application/json"))
        elif body_type == "urlencoded":
            headers.append(HeaderItem(key="Content-Type", value="application/x-www-form-urlencoded"))
        elif body_type == "form":
            headers.append(HeaderItem(key="Content-Type", value="multipart/form-data"))

    return SavedRequest(
        method=method,
        url=url,
        headers=headers,
        params=params,
        body_type=body_type,
        body_content=body_content,
        auth_type=auth_type,
        auth_config=auth_config,
        timeout=timeout,
    )
