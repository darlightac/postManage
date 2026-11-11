"""安全辅助模块 - 提供敏感凭据（如 Auth Config）的本地加密与解密保护"""

import os
import json
import base64
import hashlib
import platform
from typing import Optional


def _get_machine_key() -> bytes:
    """基于当前设备和用户特征生成本地加密密钥（32字节）"""
    parts = [
        platform.node(),
        os.environ.get("USERNAME", os.environ.get("USER", "default_user")),
        platform.machine(),
    ]
    # 尝试获取 Windows 机器特定标识
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        parts.append(str(guid))
        winreg.CloseKey(key)
    except Exception:
        parts.append("RequestManager-Local-Salt-2026")

    raw_id = "::".join(parts).encode("utf-8")
    return hashlib.sha256(raw_id).digest()


_KEY = _get_machine_key()
_PREFIX = "enc:v1:"


def _keystream(key: bytes, length: int) -> bytes:
    """生成与数据等长的密钥流（基于 SHA256 迭代）"""
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        h = hashlib.sha256(key + counter.to_bytes(4, "big")).digest()
        stream.extend(h)
        counter += 1
    return bytes(stream[:length])


def encrypt_auth_config(auth_config: dict) -> str:
    """将 auth_config 字典加密序列化为字符串"""
    if not auth_config:
        return "{}"
    raw_json = json.dumps(auth_config, ensure_ascii=False).encode("utf-8")
    key_stream = _keystream(_KEY, len(raw_json))
    encrypted_bytes = bytes(b ^ k for b, k in zip(raw_json, key_stream))
    b64 = base64.urlsafe_b64encode(encrypted_bytes).decode("ascii")
    return f"{_PREFIX}{b64}"


def decrypt_auth_config(stored_str: Optional[str]) -> dict:
    """将存储的凭据字符串解密为 auth_config 字典（透明兼容历史明文）"""
    if not stored_str:
        return {}

    stored_str = stored_str.strip()
    # 兼容历史明文 JSON
    if not stored_str.startswith(_PREFIX):
        try:
            return json.loads(stored_str)
        except Exception:
            return {}

    b64 = stored_str[len(_PREFIX):]
    try:
        encrypted_bytes = base64.urlsafe_b64decode(b64.encode("ascii"))
        key_stream = _keystream(_KEY, len(encrypted_bytes))
        decrypted_bytes = bytes(b ^ k for b, k in zip(encrypted_bytes, key_stream))
        return json.loads(decrypted_bytes.decode("utf-8"))
    except Exception:
        # 解密失败时返回空字典，避免崩溃
        return {}
