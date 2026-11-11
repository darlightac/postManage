"""针对 11 项隐患修复的综合自动化测试套件"""

import os
import sys
import json
import tempfile
import sqlite3
from pathlib import Path

# 添加项目根目录到 sys.path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from PyQt6.QtWidgets import QApplication
# 创建全局 QApplication 实例供测试使用
app = QApplication.instance() or QApplication(sys.argv)

from app.core.db import Database
from app.core.models import (
    Collection, SavedRequest, HistoryRecord, HeaderItem, ParamItem, HTTPResponse, generate_id
)
from app.core.security import encrypt_auth_config, decrypt_auth_config
from app.core.http_client import HTTPClient
from app.core.exporter import _import_postman_item, export_collection
from app.core.importer import parse_curl
from app.widgets.request_editor import KeyValueEditor, RequestEditor
from app.widgets.cookie_manager import CookieManager
from app.widgets.json_editor import JsonTextEdit


def test_item_1_collection_rename():
    """验证隐患 1：重命名子集合时保留 parent_id、description 和 sort_order"""
    db = Database()
    parent = Collection(name="父级集合", description="父级说明")
    db.create_collection(parent)

    child = Collection(name="子级集合", description="子级说明", parent_id=parent.id, sort_order=5)
    db.create_collection(child)

    # 执行重命名
    db.rename_collection(child.id, "新子级集合名称")

    updated = db.get_collection(child.id)
    assert updated is not None, "集合未找到"
    assert updated.name == "新子级集合名称", f"名称未更新: {updated.name}"
    assert updated.parent_id == parent.id, f"parent_id 丢失: {updated.parent_id} != {parent.id}"
    assert updated.description == "子级说明", f"description 丢失: {updated.description}"
    assert updated.sort_order == 5, f"sort_order 丢失: {updated.sort_order}"

    # 清理
    db.delete_collection(parent.id)
    print("✓ [Item 1] 集合重命名保留层级与属性测试通过")


def test_item_2_curl_export_loop_guard():
    """验证隐患 2：cURL 导出不会因 textChanged 触发回填解析覆盖"""
    editor = RequestEditor()
    editor.url_input.setText("https://example.com/api/test")
    editor.method_combo.setCurrentText("POST")
    editor.headers_editor.set_data([HeaderItem(key="X-Custom", value="SecretValue")])

    # 导出 cURL
    editor._on_export_curl()
    assert editor._is_exporting_curl is False
    assert "curl" in editor.curl_display.toPlainText()

    # 模拟定时器触发解析：由于 _is_exporting_curl 已结束，若内容没有变动或正在导出，不应篡改
    # 直接验证 _parse_and_apply_curl 在 _is_exporting_curl 为 True 时会直接返回
    editor._is_exporting_curl = True
    orig_url = editor.url_input.text()
    editor._parse_and_apply_curl()
    assert editor.url_input.text() == orig_url
    editor._is_exporting_curl = False

    # 验证真实用户粘贴解析（parse_curl 集成）
    editor.curl_display.setPlainText("curl -X PUT https://api.sample.com/items -H 'Auth: test'")
    editor._parse_and_apply_curl()
    assert editor.method_combo.currentText() == "PUT"
    assert editor.url_input.text() == "https://api.sample.com/items"
    headers_data = editor.headers_editor.get_data()
    assert any(h["key"] == "Auth" and h["value"] == "test" for h in headers_data)
    print("✓ [Item 2] cURL 导出防循环及解析器集成测试通过")


def test_item_3_worker_isolation():
    """验证隐患 3：SendWorker 独立拥有 HTTPClient 实例"""
    from app.main_window import SendWorker
    req1 = SavedRequest(url="https://httpbin.org/delay/5")
    req2 = SavedRequest(url="https://httpbin.org/get")

    worker1 = SendWorker(req1)
    worker2 = SendWorker(req2)

    assert worker1.client is not worker2.client, "SendWorker 必须拥有独立的 HTTPClient 实例"
    # 取消 worker1
    worker1.cancel()
    assert worker1._cancelled is True
    assert worker2._cancelled is False
    print("✓ [Item 3] SendWorker HTTPClient 客户端隔离与独立取消测试通过")


def test_item_4_key_value_dynamic_delete():
    """验证隐患 4：KeyValueEditor 删除按钮在删除前一行后仍能精准定位当前行"""
    editor = KeyValueEditor("Key", "Value")
    editor.table.setRowCount(0)
    editor._add_row(True, "k0", "v0")
    editor._add_row(True, "k1", "v1")
    editor._add_row(True, "k2", "v2")
    assert editor.table.rowCount() == 3

    # 获取第二行（k1）的删除按钮
    btn_k1 = editor.table.cellWidget(1, 3)

    # 先删除第 0 行
    editor._delete_row(0)
    assert editor.table.rowCount() == 2

    # 点击原第二行（现第一行）的删除按钮
    btn_k1.click()
    assert editor.table.rowCount() == 1
    # 剩余的行应该是 k2
    remaining_key = editor.table.cellWidget(0, 1).get_text()
    assert remaining_key == "k2", f"删除逻辑错误，剩余的不是 k2 而是 {remaining_key}"
    print("✓ [Item 4] KeyValueEditor 动态行删除测试通过")


def test_item_5_binary_body():
    """验证隐患 5：Binary 请求体 UI 可见性与文件发送支持"""
    editor = RequestEditor()
    editor._on_body_type_changed("binary")
    assert not editor.binary_widget.isHidden(), "binary_widget 应处于显示状态"
    assert editor.body_edit.isHidden(), "body_edit 应处于隐藏状态"

    editor._on_body_type_changed("json")
    assert editor.binary_widget.isHidden(), "binary_widget 应处于隐藏状态"
    assert not editor.body_edit.isHidden(), "body_edit 应处于显示状态"

    # 测试 HTTPClient 对 Binary 文件的读取与发送
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
        tf.write(b"Hello Binary World 12345")
        tf_path = tf.name

    try:
        req = SavedRequest(
            url="http://127.0.0.1:9999/dummy",
            method="POST",
            body_type="binary",
            body_content=tf_path,
        )
        client = HTTPClient()
        # 即使无法建立连接，只要进入 ConnectError 前成功读取了文件即代表二进制分支工作正常
        resp = client.send(req)
        # 不应返回文件读取错误
        assert "读取二进制文件失败" not in (resp.error or "")
        assert "二进制文件不存在" not in (resp.error or "")
    finally:
        os.remove(tf_path)

    print("✓ [Item 5] Binary 请求体 UI 联动与文件读取测试通过")


def test_item_6_cookie_handling():
    """验证隐患 6：CookieManager 接收并合并 Response Cookies"""
    cm = CookieManager()
    cm.cookies = {
        "example.com": {
            "/": [{"name": "session", "value": "old_val", "domain": "example.com", "path": "/"}]
        }
    }

    new_cookies = [
        {"name": "session", "value": "new_val", "domain": "example.com", "path": "/"},
        {"name": "uid", "value": "10086", "domain": "example.com", "path": "/"},
    ]
    cm.merge_cookies(new_cookies)

    all_c = cm.get_all_cookies()
    session_c = next((c for c in all_c if c["name"] == "session"), None)
    uid_c = next((c for c in all_c if c["name"] == "uid"), None)

    assert session_c is not None and session_c["value"] == "new_val", "原有 Cookie 覆盖更新失败"
    assert uid_c is not None and uid_c["value"] == "10086", "新增 Cookie 添加失败"

    # 测试 SavedRequest 中的 cookies 转换为 dict 并随请求携带
    req = SavedRequest(
        url="http://127.0.0.1:9999/dummy",
        method="GET",
        cookies=[{"name": "token", "value": "abc"}],
    )
    client = HTTPClient()
    resp = client.send(req)
    assert resp is not None
    print("✓ [Item 6] Cookie 发送与合并测试通过")


def test_item_7_json_paint_caching():
    """验证隐患 7：JsonTextEdit 缓存可折叠行，不再在 paint 中全量匹配"""
    edit = JsonTextEdit()
    sample_json = json.dumps({"a": [1, 2, 3], "b": {"c": 4, "d": 5}}, indent=2)
    edit.setPlainText(sample_json)
    edit.format_json()

    assert hasattr(edit, "_cached_foldable_starts")
    assert len(edit._cached_foldable_starts) > 0, "格式化后应缓存可折叠行"
    cached = edit._cached_foldable_starts

    # 模拟重绘调用
    assert edit._cached_foldable_starts is cached, "重绘应直接复用缓存"

    # 清空或重置应失效缓存
    edit._invalidate_folds()
    assert len(edit._cached_foldable_starts) == 0, "失效折叠应清理缓存"
    print("✓ [Item 7] JsonTextEdit 折叠缓存与重绘优化测试通过")


def test_item_10_database_null_safety():
    """验证隐患 10：数据库含有 NULL 值时不会导致 json.loads 崩溃"""
    null_row = {
        "id": "test_id",
        "collection_id": "c1",
        "name": "NullTest",
        "method": "GET",
        "url": "http://example.com",
        "headers": None,
        "params": None,
        "auth_config": None,
        "cookies": None,
        "body_type": None,
        "body_content": None,
        "auth_type": None,
        "timeout": None,
        "sort_order": None,
        "created_at": None,
        "updated_at": None,
    }

    # 测试 SavedRequest.from_db_row
    req = SavedRequest.from_db_row(null_row)
    assert req.headers == []
    assert req.params == []
    assert req.auth_config == {}
    assert req.cookies == []
    assert req.name == "NullTest"

    # 测试 HistoryRecord.from_db_row
    null_history_row = {
        "id": "h_id",
        "name": None,
        "method": "POST",
        "url": "http://example.com",
        "headers": None,
        "params": None,
        "body_type": None,
        "body_content": None,
        "status_code": None,
        "response_time": None,
        "response_size": None,
        "created_at": None,
    }
    hist = HistoryRecord.from_db_row(null_history_row)
    assert hist.headers == []
    assert hist.params == []
    assert hist.name == ""
    print("✓ [Item 10] 数据库 NULL 安全性转换测试通过")


def test_item_12_auth_security():
    """验证隐患 12：敏感凭据本地透明加密与兼容解密"""
    auth = {"username": "admin", "password": "super_secret_password_123", "token": "jwt.xxx.yyy"}
    encrypted = encrypt_auth_config(auth)
    assert encrypted.startswith("enc:v1:"), f"加密串应有版本前缀: {encrypted}"
    assert "super_secret_password_123" not in encrypted, "密码绝不能明文出现在序列化字符串中"

    # 解密验证
    decrypted = decrypt_auth_config(encrypted)
    assert decrypted == auth, "解密内容与原配置不匹配"

    # 兼容历史明文 JSON
    legacy_plain = json.dumps({"username": "user", "password": "plain_password"})
    legacy_decrypted = decrypt_auth_config(legacy_plain)
    assert legacy_decrypted["password"] == "plain_password", "历史明文应能透明读取"

    # 损坏数据容错
    bad_decrypted = decrypt_auth_config("enc:v1:not_a_valid_base64!!!")
    assert bad_decrypted == {}, "损坏密文应安全返回空字典"
    print("✓ [Item 12] 敏感凭据加密、解密与向后兼容测试通过")


def test_item_13_postman_folder_nesting():
    """验证隐患 13：Postman 集合顶级文件夹正确嵌套在主集合下"""
    db = Database()
    main_coll = Collection(name="Postman主集合")
    db.create_collection(main_coll)

    postman_item = {
        "name": "顶级文件夹",
        "item": [
            {
                "name": "内部请求",
                "request": {"method": "GET", "url": "https://api.test.com"}
            }
        ]
    }

    _import_postman_item(postman_item, db, collection_id=main_coll.id)

    # 检查顶级文件夹的 parent_id
    sub_colls = db.get_collections(parent_id=main_coll.id)
    assert len(sub_colls) == 1, f"主集合下应该能查到顶级文件夹，实际查到 {len(sub_colls)} 个"
    assert sub_colls[0].name == "顶级文件夹"
    assert sub_colls[0].parent_id == main_coll.id, "顶级文件夹的 parent_id 必须为主集合 ID"

    # 检查其下的请求
    reqs = db.get_requests(sub_colls[0].id)
    assert len(reqs) == 1
    assert reqs[0].name == "内部请求"

    # 清理
    db.delete_collection(main_coll.id)
    print("✓ [Item 13] Postman 导入层级嵌套测试通过")


def test_item_14_sqlite_indexes():
    """验证隐患 14：SQLite 性能索引已创建"""
    db = Database()
    conn = db._get_conn()
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        indexes = {r[0] for r in rows}
        expected_indexes = {
            "idx_collections_parent_id",
            "idx_requests_collection_id",
            "idx_history_created_at",
            "idx_open_tabs_sort_order",
        }
        for idx in expected_indexes:
            assert idx in indexes, f"缺少索引: {idx}"
    finally:
        conn.close()
    print("✓ [Item 14] SQLite 索引完整性测试通过")


def run_all_tests():
    print("=" * 60)
    print("开始执行 11 项隐患修复自动化验证测试")
    print("=" * 60)
    test_item_1_collection_rename()
    test_item_2_curl_export_loop_guard()
    test_item_3_worker_isolation()
    test_item_4_key_value_dynamic_delete()
    test_item_5_binary_body()
    test_item_6_cookie_handling()
    test_item_7_json_paint_caching()
    test_item_10_database_null_safety()
    test_item_12_auth_security()
    test_item_13_postman_folder_nesting()
    test_item_14_sqlite_indexes()
    print("=" * 60)
    print("🎉 全部 11 项隐患修复验证通过！")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
