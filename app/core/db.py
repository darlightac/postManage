"""SQLite 数据库操作层"""

import sqlite3
import json
from typing import Optional
from pathlib import Path

from app.core.models import (
    Collection, SavedRequest, HistoryRecord, HeaderItem,
    MockCollection, MockApi,
    generate_id, now_timestamp,
)
from app.config.settings import Settings


class Database:
    """数据库管理类（单例）"""

    _instance: Optional["Database"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        settings = Settings()
        self.db_path = str(settings.db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def switch_database(self, new_db_path: str):
        """切换当前数据库文件路径，并确保新数据库表结构完整"""
        self.db_path = str(new_db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        """初始化数据库表结构"""
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS collections (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    parent_id   TEXT DEFAULT NULL,
                    sort_order  INTEGER DEFAULT 0,
                    created_at  TEXT DEFAULT (datetime('now','localtime')),
                    updated_at  TEXT DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (parent_id) REFERENCES collections(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS requests (
                    id            TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    name          TEXT NOT NULL,
                    method        TEXT NOT NULL DEFAULT 'GET',
                    url           TEXT NOT NULL DEFAULT '',
                    headers       TEXT DEFAULT '[]',
                    params        TEXT DEFAULT '[]',
                    body_type     TEXT DEFAULT 'none',
                    body_content  TEXT DEFAULT '',
                    auth_type     TEXT DEFAULT 'none',
                    auth_config   TEXT DEFAULT '{}',
                    cookies       TEXT DEFAULT '[]',
                    timeout       INTEGER DEFAULT 0,
                    sort_order    INTEGER DEFAULT 0,
                    created_at    TEXT DEFAULT (datetime('now','localtime')),
                    updated_at    TEXT DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS history (
                    id            TEXT PRIMARY KEY,
                    name          TEXT DEFAULT '',
                    method        TEXT NOT NULL,
                    url           TEXT NOT NULL,
                    headers       TEXT DEFAULT '[]',
                    params        TEXT DEFAULT '[]',
                    body_type     TEXT DEFAULT 'none',
                    body_content  TEXT DEFAULT '',
                    status_code   INTEGER,
                    response_time INTEGER,
                    response_size INTEGER,
                    created_at    TEXT DEFAULT (datetime('now','localtime'))
                );

                CREATE TABLE IF NOT EXISTS environments (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    variables   TEXT DEFAULT '{}',
                    is_active   INTEGER DEFAULT 0,
                    created_at  TEXT DEFAULT (datetime('now','localtime')),
                    updated_at  TEXT DEFAULT (datetime('now','localtime'))
                );

                CREATE TABLE IF NOT EXISTS open_tabs (
                    tab_id        TEXT PRIMARY KEY,
                    request_id    TEXT DEFAULT '',
                    collection_id TEXT DEFAULT '',
                    name          TEXT DEFAULT '',
                    method        TEXT NOT NULL DEFAULT 'GET',
                    url           TEXT NOT NULL DEFAULT '',
                    headers       TEXT DEFAULT '[]',
                    params        TEXT DEFAULT '[]',
                    body_type     TEXT DEFAULT 'none',
                    body_content  TEXT DEFAULT '',
                    auth_type     TEXT DEFAULT 'none',
                    auth_config   TEXT DEFAULT '{}',
                    pre_script    TEXT DEFAULT '{}',
                    post_script   TEXT DEFAULT '{}',
                    timeout       INTEGER DEFAULT 0,
                    sort_order    INTEGER DEFAULT 0,
                    created_at    TEXT DEFAULT (datetime('now','localtime'))
                );

                CREATE TABLE IF NOT EXISTS mock_collections (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    parent_id   TEXT DEFAULT NULL,
                    sort_order  INTEGER DEFAULT 0,
                    created_at  TEXT DEFAULT (datetime('now','localtime')),
                    updated_at  TEXT DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (parent_id) REFERENCES mock_collections(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS mock_apis (
                    id            TEXT PRIMARY KEY,
                    collection_id TEXT DEFAULT '',
                    name          TEXT NOT NULL,
                    method        TEXT NOT NULL DEFAULT 'GET',
                    path          TEXT NOT NULL DEFAULT '',
                    status_code   INTEGER DEFAULT 200,
                    delay_ms      INTEGER DEFAULT 0,
                    headers       TEXT DEFAULT '[]',
                    body_type     TEXT DEFAULT 'json',
                    body_content  TEXT DEFAULT '{"code": 200, "message": "success"}',
                    is_enabled    INTEGER DEFAULT 1,
                    sort_order    INTEGER DEFAULT 0,
                    created_at    TEXT DEFAULT (datetime('now','localtime')),
                    updated_at    TEXT DEFAULT (datetime('now','localtime'))
                );

                -- 性能索引
                CREATE INDEX IF NOT EXISTS idx_collections_parent_id ON collections(parent_id);
                CREATE INDEX IF NOT EXISTS idx_requests_collection_id ON requests(collection_id);
                CREATE INDEX IF NOT EXISTS idx_history_created_at ON history(created_at);
                CREATE INDEX IF NOT EXISTS idx_open_tabs_sort_order ON open_tabs(sort_order);
                CREATE INDEX IF NOT EXISTS idx_mock_collections_parent_id ON mock_collections(parent_id);
                CREATE INDEX IF NOT EXISTS idx_mock_apis_collection_id ON mock_apis(collection_id);
            """)
            # 旧版本数据库升级：补齐后来新增的列（CREATE TABLE IF NOT EXISTS 不会修改已有表）
            self._ensure_columns(conn, "requests", [
                ("cookies", "TEXT DEFAULT '[]'"),
                ("pre_script", "TEXT DEFAULT '{}'"),
                ("post_script", "TEXT DEFAULT '{}'"),
                ("proxy", "TEXT DEFAULT '{}'"),
            ])
            self._ensure_columns(conn, "open_tabs", [
                ("pre_script", "TEXT DEFAULT '{}'"),
                ("post_script", "TEXT DEFAULT '{}'"),
                ("cookies", "TEXT DEFAULT '[]'"),
                ("proxy", "TEXT DEFAULT '{}'"),
            ])
            self._ensure_columns(conn, "history", [
                ("name", "TEXT DEFAULT ''"),
                ("params", "TEXT DEFAULT '[]'"),
                ("body_type", "TEXT DEFAULT 'none'"),
                ("body_content", "TEXT DEFAULT ''"),
            ])
            # 兜底清理 NULL 值，防止 json.loads 异常
            conn.execute("UPDATE requests SET headers = '[]' WHERE headers IS NULL")
            conn.execute("UPDATE requests SET params = '[]' WHERE params IS NULL")
            conn.execute("UPDATE requests SET auth_config = '{}' WHERE auth_config IS NULL")
            conn.execute("UPDATE requests SET cookies = '[]' WHERE cookies IS NULL")
            conn.execute("UPDATE history SET headers = '[]' WHERE headers IS NULL")
            conn.execute("UPDATE history SET params = '[]' WHERE params IS NULL")
            # 旧版默认超时 30000ms，迁移为 0（无超时）
            conn.execute("UPDATE requests SET timeout = 0 WHERE timeout = 30000")
            # 修复历史遗留的空 id 行（早期版本曾以空字符串 id 插入，会导致主键冲突）
            for row in conn.execute("SELECT rowid FROM requests WHERE id = '' OR id IS NULL").fetchall():
                conn.execute("UPDATE requests SET id = ? WHERE rowid = ?", (generate_id(), row[0]))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table: str, columns: list[tuple[str, str]]):
        """若表中缺失指定列，则通过 ALTER TABLE 补齐（幂等迁移）"""
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, definition in columns:
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")

    # ─── 集合操作 ───────────────────────────────────────────────

    def get_collections(self, parent_id: Optional[str] = None) -> list[Collection]:
        conn = self._get_conn()
        try:
            if parent_id is None:
                rows = conn.execute(
                    "SELECT * FROM collections WHERE parent_id IS NULL ORDER BY sort_order, name"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM collections WHERE parent_id = ? ORDER BY sort_order, name",
                    (parent_id,),
                ).fetchall()
            return [Collection(**dict(r)) for r in rows]
        finally:
            conn.close()

    def get_all_collections(self) -> list[Collection]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM collections ORDER BY sort_order, name").fetchall()
            return [Collection(**dict(r)) for r in rows]
        finally:
            conn.close()

    def get_collection(self, collection_id: str) -> Optional[Collection]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM collections WHERE id = ?", (collection_id,)).fetchone()
            if row:
                return Collection(**dict(row))
            return None
        finally:
            conn.close()

    def rename_collection(self, collection_id: str, new_name: str):
        """仅修改集合名称，保留 parent_id、description 和 sort_order"""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE collections SET name = ?, updated_at = ? WHERE id = ?",
                (new_name, now_timestamp(), collection_id),
            )
            conn.commit()
        finally:
            conn.close()

    def create_collection(self, collection: Collection) -> Collection:
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO collections (id, name, description, parent_id, sort_order)
                   VALUES (?, ?, ?, ?, ?)""",
                (collection.id, collection.name, collection.description,
                 collection.parent_id, collection.sort_order),
            )
            conn.commit()
            return collection
        finally:
            conn.close()

    def update_collection(self, collection: Collection):
        conn = self._get_conn()
        try:
            conn.execute(
                """UPDATE collections
                   SET name=?, description=?, parent_id=?, sort_order=?, updated_at=?
                   WHERE id=?""",
                (collection.name, collection.description, collection.parent_id,
                 collection.sort_order, now_timestamp(), collection.id),
            )
            conn.commit()
        finally:
            conn.close()

    def move_collection(self, collection_id: str, new_parent_id: Optional[str]) -> bool:
        """移动集合到指定父集合下（为 None 表示移到顶层），自动拦截循环嵌套"""
        if collection_id == new_parent_id:
            return False
        conn = self._get_conn()
        try:
            if new_parent_id:
                # 循环嵌套检测：遍历 new_parent_id 的祖先链，不能包含 collection_id
                curr_id = new_parent_id
                while curr_id:
                    if curr_id == collection_id:
                        return False  # 出现循环嵌套，拦截
                    row = conn.execute("SELECT parent_id FROM collections WHERE id = ?", (curr_id,)).fetchone()
                    curr_id = row[0] if row else None

                # 确保目标父集合存在
                exists = conn.execute("SELECT 1 FROM collections WHERE id = ?", (new_parent_id,)).fetchone()
                if not exists:
                    return False

            conn.execute(
                "UPDATE collections SET parent_id = ?, updated_at = ? WHERE id = ?",
                (new_parent_id, now_timestamp(), collection_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def delete_collection(self, collection_id: str):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
            conn.commit()
        finally:
            conn.close()

    # ─── 请求操作 ───────────────────────────────────────────────

    def get_requests(self, collection_id: str) -> list[SavedRequest]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM requests WHERE collection_id = ? ORDER BY sort_order, name",
                (collection_id,),
            ).fetchall()
            return [SavedRequest.from_db_row(dict(r)) for r in rows]
        finally:
            conn.close()

    def get_request(self, request_id: str) -> Optional[SavedRequest]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
            if row:
                return SavedRequest.from_db_row(dict(row))
            return None
        finally:
            conn.close()

    def create_request(self, req: SavedRequest) -> SavedRequest:
        conn = self._get_conn()
        try:
            if not req.id:
                req.id = generate_id()  # 保底：绝不允许空 id 插入
            cookies_json = json.dumps(req.cookies, ensure_ascii=False)
            proxy_json = req.proxy_json() if hasattr(req, "proxy_json") else "{}"
            conn.execute(
                """INSERT INTO requests
                   (id, collection_id, name, method, url, headers, params,
                    body_type, body_content, auth_type, auth_config, cookies,
                    pre_script, post_script, timeout, sort_order, proxy)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (req.id, req.collection_id, req.name, req.method, req.url,
                 req.headers_json(), req.params_json(),
                 req.body_type, req.body_content, req.auth_type,
                 req.auth_config_json(), cookies_json,
                 req.pre_script_json(), req.post_script_json(),
                 req.timeout, req.sort_order, proxy_json),
            )
            conn.commit()
            return req
        finally:
            conn.close()

    def update_request(self, req: SavedRequest):
        conn = self._get_conn()
        try:
            # collection_id 为空时保留原所属集合（改名等场景不会携带集合信息），
            # 避免把外键写成空字符串导致 FOREIGN KEY 约束失败；
            # 若传入的集合不存在同样回退原值，防止意外破坏外键。
            collection_id = req.collection_id
            if collection_id:
                exists = conn.execute(
                    "SELECT 1 FROM collections WHERE id = ?", (collection_id,)
                ).fetchone()
                if not exists:
                    collection_id = None
            if not collection_id:
                row = conn.execute(
                    "SELECT collection_id FROM requests WHERE id = ?", (req.id,)
                ).fetchone()
                if row:
                    collection_id = row[0]

            cookies_json = json.dumps(req.cookies, ensure_ascii=False)
            proxy_json = req.proxy_json() if hasattr(req, "proxy_json") else "{}"
            conn.execute(
                """UPDATE requests
                   SET collection_id=?, name=?, method=?, url=?, headers=?, params=?,
                       body_type=?, body_content=?, auth_type=?, auth_config=?, cookies=?,
                       pre_script=?, post_script=?, timeout=?, sort_order=?, proxy=?, updated_at=?
                   WHERE id=?""",
                (collection_id, req.name, req.method, req.url,
                 req.headers_json(), req.params_json(),
                 req.body_type, req.body_content, req.auth_type,
                 req.auth_config_json(), cookies_json,
                 req.pre_script_json(), req.post_script_json(),
                 req.timeout, req.sort_order, proxy_json,
                 now_timestamp(), req.id),
            )
            conn.commit()
        finally:
            conn.close()

    def move_request(self, request_id: str, new_collection_id: str) -> bool:
        """移动请求到新集合中"""
        conn = self._get_conn()
        try:
            # 确保目标集合存在
            exists = conn.execute("SELECT 1 FROM collections WHERE id = ?", (new_collection_id,)).fetchone()
            if not exists:
                return False
            conn.execute(
                "UPDATE requests SET collection_id = ?, updated_at = ? WHERE id = ?",
                (new_collection_id, now_timestamp(), request_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def clone_request(
        self, request_id: str, target_collection_id: str, new_name: Optional[str] = None
    ) -> Optional[SavedRequest]:
        """克隆请求到指定集合中（若未提供 new_name，则默认为原名加上' - 副本'）"""
        req = self.get_request(request_id)
        if not req:
            return None
        clone = SavedRequest(
            id=generate_id(),
            collection_id=target_collection_id,
            name=new_name or f"{req.name} - 副本",
            method=req.method,
            url=req.url,
            headers=list(req.headers),
            params=list(req.params),
            body_type=req.body_type,
            body_content=req.body_content,
            auth_type=req.auth_type,
            auth_config=dict(req.auth_config) if req.auth_config else {},
            cookies=list(req.cookies),
            pre_script=dict(req.pre_script) if req.pre_script else {},
            post_script=dict(req.post_script) if req.post_script else {},
            timeout=req.timeout,
            sort_order=req.sort_order + 1,
        )
        return self.create_request(clone)

    def delete_request(self, request_id: str):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM requests WHERE id = ?", (request_id,))
            conn.commit()
        finally:
            conn.close()

    # ─── 历史记录操作 ──────────────────────────────────────────

    def add_history(self, record: HistoryRecord) -> HistoryRecord:
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO history
                   (id, name, method, url, headers, params, body_type, body_content,
                    status_code, response_time, response_size)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.id, record.name, record.method, record.url, record.headers_json(),
                 record.params_json(), record.body_type, record.body_content,
                 record.status_code, record.response_time, record.response_size),
            )
            # 清理超出上限的旧记录
            conn.execute(
                """DELETE FROM history WHERE id IN (
                    SELECT id FROM history ORDER BY created_at DESC LIMIT -1 OFFSET 500
                )"""
            )
            conn.commit()
            return record
        finally:
            conn.close()

    def get_history(self, limit: int = 100) -> list[HistoryRecord]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM history ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [HistoryRecord.from_db_row(dict(r)) for r in rows]
        finally:
            conn.close()

    def clear_history(self):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM history")
            conn.commit()
        finally:
            conn.close()

    def search_history(self, keyword: str, limit: int = 50) -> list[HistoryRecord]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM history
                   WHERE url LIKE ? OR method LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
                (f"%{keyword}%", f"%{keyword}%", limit),
            ).fetchall()
            return [HistoryRecord.from_db_row(dict(r)) for r in rows]
        finally:
            conn.close()

    # ─── 打开标签页操作（临时表） ────────────────────────────────

    def save_open_tab(self, tab_id: str, request_id: str, collection_id: str,
                      name: str, method: str, url: str, headers: str,
                      params: str, body_type: str, body_content: str,
                      auth_type: str, auth_config: str, timeout: int,
                      sort_order: int, pre_script: str = "{}", post_script: str = "{}", proxy: str = "{}"):
        """保存或更新一个打开的标签页"""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO open_tabs
                   (tab_id, request_id, collection_id, name, method, url,
                    headers, params, body_type, body_content,
                    auth_type, auth_config, pre_script, post_script, timeout, sort_order, proxy)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tab_id, request_id, collection_id, name, method, url,
                 headers, params, body_type, body_content,
                 auth_type, auth_config, pre_script, post_script, timeout, sort_order, proxy),
            )
            conn.commit()
        finally:
            conn.close()

    def remove_open_tab(self, tab_id: str):
        """删除一个关闭的标签页"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM open_tabs WHERE tab_id = ?", (tab_id,))
            conn.commit()
        finally:
            conn.close()

    def get_open_tabs(self) -> list[dict]:
        """获取所有未关闭的标签页（按 sort_order 排序）"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM open_tabs ORDER BY sort_order"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def clear_open_tabs(self):
        """清空所有标签页记录"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM open_tabs")
            conn.commit()
        finally:
            conn.close()

    # ─── Mock 集合与接口操作 ───────────────────────────────────────

    def get_mock_collections(self, parent_id: Optional[str] = None) -> list[MockCollection]:
        conn = self._get_conn()
        try:
            if parent_id is None:
                rows = conn.execute(
                    "SELECT * FROM mock_collections WHERE parent_id IS NULL ORDER BY sort_order, name"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM mock_collections WHERE parent_id = ? ORDER BY sort_order, name",
                    (parent_id,),
                ).fetchall()
            return [MockCollection(**dict(r)) for r in rows]
        finally:
            conn.close()

    def get_all_mock_collections(self) -> list[MockCollection]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM mock_collections ORDER BY sort_order, name").fetchall()
            return [MockCollection(**dict(r)) for r in rows]
        finally:
            conn.close()

    def get_mock_collection(self, collection_id: str) -> Optional[MockCollection]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM mock_collections WHERE id = ?", (collection_id,)).fetchone()
            if row:
                return MockCollection(**dict(row))
            return None
        finally:
            conn.close()

    def create_mock_collection(self, collection: MockCollection) -> MockCollection:
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO mock_collections (id, name, parent_id, sort_order)
                   VALUES (?, ?, ?, ?)""",
                (collection.id, collection.name, collection.parent_id, collection.sort_order),
            )
            conn.commit()
            return collection
        finally:
            conn.close()

    def update_mock_collection(self, collection: MockCollection):
        conn = self._get_conn()
        try:
            conn.execute(
                """UPDATE mock_collections
                   SET name=?, parent_id=?, sort_order=?, updated_at=?
                   WHERE id=?""",
                (collection.name, collection.parent_id, collection.sort_order, now_timestamp(), collection.id),
            )
            conn.commit()
        finally:
            conn.close()

    def rename_mock_collection(self, collection_id: str, new_name: str):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE mock_collections SET name = ?, updated_at = ? WHERE id = ?",
                (new_name, now_timestamp(), collection_id),
            )
            conn.commit()
        finally:
            conn.close()

    def move_mock_collection(self, collection_id: str, new_parent_id: Optional[str]) -> bool:
        if collection_id == new_parent_id:
            return False
        conn = self._get_conn()
        try:
            if new_parent_id:
                curr_id = new_parent_id
                while curr_id:
                    if curr_id == collection_id:
                        return False
                    row = conn.execute("SELECT parent_id FROM mock_collections WHERE id = ?", (curr_id,)).fetchone()
                    curr_id = row[0] if row else None
                exists = conn.execute("SELECT 1 FROM mock_collections WHERE id = ?", (new_parent_id,)).fetchone()
                if not exists:
                    return False
            conn.execute(
                "UPDATE mock_collections SET parent_id = ?, updated_at = ? WHERE id = ?",
                (new_parent_id, now_timestamp(), collection_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def delete_mock_collection(self, collection_id: str):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM mock_collections WHERE id = ?", (collection_id,))
            conn.commit()
        finally:
            conn.close()

    def get_mock_apis(self, collection_id: str) -> list[MockApi]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM mock_apis WHERE collection_id = ? ORDER BY sort_order, name",
                (collection_id,),
            ).fetchall()
            return [MockApi.from_db_row(dict(r)) for r in rows]
        finally:
            conn.close()

    def get_mock_api(self, api_id: str) -> Optional[MockApi]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM mock_apis WHERE id = ?", (api_id,)).fetchone()
            if row:
                return MockApi.from_db_row(dict(row))
            return None
        finally:
            conn.close()

    def get_all_mock_apis(self) -> list[MockApi]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM mock_apis ORDER BY sort_order, name").fetchall()
            return [MockApi.from_db_row(dict(r)) for r in rows]
        finally:
            conn.close()

    def create_mock_api(self, api: MockApi) -> MockApi:
        conn = self._get_conn()
        try:
            if not api.id:
                api.id = generate_id()
            conn.execute(
                """INSERT INTO mock_apis
                   (id, collection_id, name, method, path, status_code, delay_ms,
                    headers, body_type, body_content, is_enabled, sort_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (api.id, api.collection_id, api.name, api.method, api.path,
                 api.status_code, api.delay_ms, api.headers_json(),
                 api.body_type, api.body_content, 1 if api.is_enabled else 0,
                 api.sort_order),
            )
            conn.commit()
            return api
        finally:
            conn.close()

    def update_mock_api(self, api: MockApi):
        conn = self._get_conn()
        try:
            conn.execute(
                """UPDATE mock_apis
                   SET collection_id=?, name=?, method=?, path=?, status_code=?,
                       delay_ms=?, headers=?, body_type=?, body_content=?,
                       is_enabled=?, sort_order=?, updated_at=?
                   WHERE id=?""",
                (api.collection_id, api.name, api.method, api.path,
                 api.status_code, api.delay_ms, api.headers_json(),
                 api.body_type, api.body_content, 1 if api.is_enabled else 0,
                 api.sort_order, now_timestamp(), api.id),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_mock_api(self, api_id: str):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM mock_apis WHERE id = ?", (api_id,))
            conn.commit()
        finally:
            conn.close()

    def move_mock_api(self, api_id: str, new_collection_id: str) -> bool:
        conn = self._get_conn()
        try:
            if new_collection_id:
                exists = conn.execute("SELECT 1 FROM mock_collections WHERE id = ?", (new_collection_id,)).fetchone()
                if not exists:
                    return False
            conn.execute(
                "UPDATE mock_apis SET collection_id = ?, updated_at = ? WHERE id = ?",
                (new_collection_id, now_timestamp(), api_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def clone_mock_api(
        self, api_id: str, target_collection_id: str, new_name: Optional[str] = None
    ) -> Optional[MockApi]:
        api = self.get_mock_api(api_id)
        if not api:
            return None
        clone = MockApi(
            id=generate_id(),
            collection_id=target_collection_id,
            name=new_name or f"{api.name} - 副本",
            method=api.method,
            path=api.path,
            status_code=api.status_code,
            delay_ms=api.delay_ms,
            headers=list(api.headers),
            body_type=api.body_type,
            body_content=api.body_content,
            is_enabled=api.is_enabled,
            sort_order=api.sort_order + 1,
        )
        return self.create_mock_api(clone)

    def clone_mock_collection(
        self, collection_id: str, target_parent_id: Optional[str] = None, new_name: Optional[str] = None
    ) -> Optional[MockCollection]:
        """克隆 Mock 文件夹及其内部所有子文件夹和所有包含的 Mock 接口"""
        src = self.get_mock_collection(collection_id)
        if not src:
            return None

        name = new_name or f"{src.name} - 副本"
        new_col = MockCollection(
            id=generate_id(),
            name=name,
            parent_id=target_parent_id,
            sort_order=src.sort_order + 1,
        )
        self.create_mock_collection(new_col)

        # 1. 递归克隆直接属于该集合的所有 Mock 接口
        apis = self.get_mock_apis(collection_id=src.id)
        for api in apis:
            self.clone_mock_api(api.id, target_collection_id=new_col.id, new_name=api.name)

        # 2. 递归克隆所有子文件夹
        sub_cols = self.get_mock_collections(parent_id=src.id)
        for sub in sub_cols:
            self.clone_mock_collection(sub.id, target_parent_id=new_col.id, new_name=sub.name)

        return new_col
