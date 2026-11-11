"""集合导入/导出功能 - 支持 RequestManager / Postman Collection v2.1 格式"""

import json
from typing import Optional

from app.core.models import Collection, SavedRequest, HeaderItem, ParamItem, generate_id


def export_collection(file_path: str, db, collection_ids: Optional[list[str]] = None):
    """导出集合为 JSON 文件（RequestManager 格式）"""
    if collection_ids is None:
        collections = db.get_collections(parent_id=None)
        collection_ids = [c.id for c in collections]

    export_data = {
        "version": "1.0",
        "format": "requestmanager",
        "collections": [],
    }

    for coll_id in collection_ids:
        coll_data = _export_collection_recursive(coll_id, db)
        if coll_data:
            export_data["collections"].append(coll_data)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)


def _export_collection_recursive(coll_id: str, db) -> dict:
    """递归导出集合及其子集合"""
    collections = db.get_all_collections()
    coll = next((c for c in collections if c.id == coll_id), None)
    if not coll:
        return {}

    data = {
        "name": coll.name,
        "description": coll.description,
        "requests": [],
        "children": [],
    }

    requests = db.get_requests(coll_id)
    for req in requests:
        data["requests"].append({
            "name": req.name,
            "method": req.method,
            "url": req.url,
            "headers": [h.to_dict() for h in req.headers],
            "params": [p.to_dict() for p in req.params],
            "body_type": req.body_type,
            "body_content": req.body_content,
            "auth_type": req.auth_type,
            "auth_config": req.auth_config,
            "timeout": req.timeout,
        })

    sub_collections = db.get_collections(parent_id=coll_id)
    for sub in sub_collections:
        child = _export_collection_recursive(sub.id, db)
        if child:
            data["children"].append(child)

    return data


def import_collection(file_path: str, db):
    """从 JSON 文件导入集合（自动检测格式：PostManage / Postman v2.1）"""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    fmt = data.get("format", "")
    info = data.get("info", {})

    if fmt in ("postmanage", "requestmanager"):
        # RequestManager 原生格式（兼容旧版 postmanage 格式）
        for coll_data in data.get("collections", []):
            _import_pm_recursive(coll_data, db, parent_id=None)
    elif info.get("schema", "").startswith("https://schema.getpostman.com"):
        # Postman Collection v2.1 格式
        _import_postman_collection(data, db)
    else:
        raise ValueError(
            "不支持的导入格式。\n支持: RequestManager JSON / Postman Collection v2.1"
        )


# ─── PostManage 格式导入 ─────────────────────────────────────

def _import_pm_recursive(data: dict, db, parent_id: Optional[str]):
    """递归导入 PostManage 格式集合"""
    coll = Collection(
        name=data.get("name", "导入的集合"),
        description=data.get("description", ""),
        parent_id=parent_id,
    )
    db.create_collection(coll)

    for req_data in data.get("requests", []):
        headers = [HeaderItem.from_dict(h) for h in req_data.get("headers", [])]
        params = [ParamItem.from_dict(p) for p in req_data.get("params", [])]

        req = SavedRequest(
            collection_id=coll.id,
            name=req_data.get("name", "导入的请求"),
            method=req_data.get("method", "GET"),
            url=req_data.get("url", ""),
            headers=headers,
            params=params,
            body_type=req_data.get("body_type", "none"),
            body_content=req_data.get("body_content", ""),
            auth_type=req_data.get("auth_type", "none"),
            auth_config=req_data.get("auth_config", {}),
            timeout=req_data.get("timeout", 30000),
        )
        db.create_request(req)

    for child_data in data.get("children", []):
        _import_pm_recursive(child_data, db, parent_id=coll.id)


# ─── Postman Collection v2.1 导入 ────────────────────────────

def _import_postman_collection(data: dict, db):
    """导入 Postman Collection v2.1 格式"""
    info = data.get("info", {})
    coll_name = info.get("name", "Postman 导入集合")

    coll = Collection(name=coll_name, description=info.get("description", ""))
    db.create_collection(coll)

    for item in data.get("item", []):
        _import_postman_item(item, db, coll.id)


def _import_postman_item(item: dict, db, collection_id: str, parent_folder_id: Optional[str] = None):
    """递归导入 Postman item（可能是文件夹或请求）"""
    sub_items = item.get("item")

    if sub_items is not None:
        # 这是一个文件夹
        folder = Collection(
            name=item.get("name", "文件夹"),
            parent_id=parent_folder_id or collection_id,
        )
        db.create_collection(folder)

        for sub_item in sub_items:
            _import_postman_item(sub_item, db, collection_id, parent_folder_id=folder.id)
    else:
        # 这是一个请求
        request_data = item.get("request", {})
        if isinstance(request_data, str):
            return  # 跳过字符串引用

        method = request_data.get("method", "GET")
        url_obj = request_data.get("url", {})
        if isinstance(url_obj, str):
            url = url_obj
            raw_url = url_obj
        else:
            raw_parts = url_obj.get("raw", "")
            url = raw_parts.split("?")[0] if "?" in raw_parts else raw_parts

        # Headers
        headers = []
        for h in request_data.get("header", []):
            headers.append(HeaderItem(key=h.get("key", ""), value=h.get("value", ""), enabled=not h.get("disabled", False)))

        # Query params
        params = []
        if isinstance(url_obj, dict):
            for p in url_obj.get("query", []):
                params.append(ParamItem(key=p.get("key", ""), value=p.get("value", ""), enabled=not p.get("disabled", False)))

        # Body
        body_type = "none"
        body_content = ""
        body_data = request_data.get("body")
        if body_data:
            pm_mode = body_data.get("mode", "")
            if pm_mode == "raw":
                body_content = body_data.get("raw", "")
                raw_opts = body_data.get("options", {})
                lang = raw_opts.get("raw", {}).get("language", "")
                if lang == "json" or body_content.strip().startswith("{"):
                    body_type = "json"
                else:
                    body_type = "raw"
            elif pm_mode == "urlencoded":
                body_type = "urlencoded"
                lines = []
                for entry in body_data.get("urlencoded", []):
                    lines.append(f"{entry.get('key', '')}={entry.get('value', '')}")
                body_content = "\n".join(lines)
            elif pm_mode == "formdata":
                body_type = "form"
                lines = []
                for entry in body_data.get("formdata", []):
                    lines.append(f"{entry.get('key', '')}={entry.get('value', '')}")
                body_content = "\n".join(lines)

        # Auth
        auth_type = "none"
        auth_config = {}
        auth_data = request_data.get("auth")
        if auth_data:
            pm_auth_type = auth_data.get("type", "")
            if pm_auth_type == "basic":
                auth_type = "basic"
                for entry in auth_data.get("basic", []):
                    if entry.get("key") == "username":
                        auth_config["username"] = entry.get("value", "")
                    elif entry.get("key") == "password":
                        auth_config["password"] = entry.get("value", "")
            elif pm_auth_type == "bearer":
                auth_type = "bearer"
                for entry in auth_data.get("bearer", []):
                    if entry.get("key") == "token":
                        auth_config["token"] = entry.get("value", "")
            elif pm_auth_type == "apikey":
                auth_type = "apikey"
                for entry in auth_data.get("apikey", []):
                    k = entry.get("key", "")
                    v = entry.get("value", "")
                    if k == "key":
                        auth_config["key"] = v
                    elif k == "value":
                        auth_config["value"] = v

        req = SavedRequest(
            collection_id=parent_folder_id or collection_id,
            name=item.get("name", "Postman 请求"),
            method=method,
            url=url,
            headers=headers,
            params=params,
            body_type=body_type,
            body_content=body_content,
            auth_type=auth_type,
            auth_config=auth_config,
        )
        db.create_request(req)
