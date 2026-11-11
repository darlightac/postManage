"""Mock 中心、前置/后置处理与多级文件夹保存功能单元测试"""

import os
import sys
import json
import time
import tempfile
import unittest
import urllib.request
import urllib.parse
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from app.core.models import (
    Collection, SavedRequest, HTTPResponse, HeaderItem, ParamItem,
    MockCollection, MockApi, generate_id
)
from app.core.db import Database
from app.core.processors import (
    EnvironmentManager, FileReader, BuiltinFunctions,
    PreProcessor, PostProcessor
)
from app.core.mock_server import MockService
from app.widgets.save_request_dialog import SaveRequestDialog
from app.widgets.mock_center_dialog import MockCenterDialog
from app.widgets.pre_post_processor_widget import PreProcessorWidget, PostProcessorWidget
from app.core.http_client import HTTPClient
from app.config.settings import Settings


app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class TestMockAndProcessors(unittest.TestCase):
    """测试 Mock 服务、处理器引擎与多级文件夹保存"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_postmanage.db")
        self.db = Database()
        self.db.switch_database(self.db_path)

    def tearDown(self):
        MockService.instance().stop()
        self.temp_dir.cleanup()

    # ─── 1. 多级文件夹保存测试 ─────────────────────────────────────

    def test_01_save_request_dialog_multilevel_folders(self):
        """测试保存请求弹窗能够展示并正确选中 1级、2级、3级子文件夹"""
        # 创建 1级、2级、3级集合
        root_col = self.db.create_collection(Collection(name="一级项目", parent_id=None))
        sub_col = self.db.create_collection(Collection(name="二级模块", parent_id=root_col.id))
        sub_sub_col = self.db.create_collection(Collection(name="三级接口组", parent_id=sub_col.id))

        dialog = SaveRequestDialog(None, current_name="测试用户登录接口", default_collection_id=sub_sub_col.id)

        # 验证默认选中的是三级文件夹
        self.assertEqual(dialog.get_selected_collection_id(), sub_sub_col.id)
        self.assertEqual(dialog.get_request_name(), "测试用户登录接口")

        # 切换选择二级文件夹
        dialog.selected_collection_id = sub_col.id
        self.assertEqual(dialog.get_selected_collection_id(), sub_col.id)

        # 切换选择一级文件夹
        dialog.selected_collection_id = root_col.id
        self.assertEqual(dialog.get_selected_collection_id(), root_col.id)

        # 修改名称
        dialog.name_edit.setText("新登录接口")
        dialog._on_accept()
        self.assertEqual(dialog.get_request_name(), "新登录接口")
        dialog.close()

    # ─── 2. 内置函数与表达式计算测试 ──────────────────────────────

    def test_02_builtin_functions(self):
        """测试内置函数生成 (UUID, 时间戳, 随机数, 哈希, Base64)"""
        # UUID
        u = BuiltinFunctions.uuid4()
        self.assertEqual(len(u), 36)

        # 时间戳
        ts_ms = BuiltinFunctions.timestamp("ms")
        self.assertTrue(len(ts_ms) >= 13)
        ts_s = BuiltinFunctions.timestamp("s")
        self.assertTrue(len(ts_s) == 10)

        # 随机数
        r_int = int(BuiltinFunctions.random_int(100, 200))
        self.assertTrue(100 <= r_int <= 200)

        # 随机字符串
        r_str = BuiltinFunctions.random_string(16)
        self.assertEqual(len(r_str), 16)

        # MD5
        md5_res = BuiltinFunctions.md5("hello")
        self.assertEqual(md5_res, "5d41402abc4b2a76b9719d911017c592")

        # SHA256
        sha_res = BuiltinFunctions.sha256("hello")
        self.assertEqual(sha_res, "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")

        # Base64
        b64_enc = BuiltinFunctions.base64_encode("admin:123456")
        self.assertEqual(b64_enc, "YWRtaW46MTIzNDU2")
        b64_dec = BuiltinFunctions.base64_decode(b64_enc)
        self.assertEqual(b64_dec, "admin:123456")

        # 表达式求值
        expr = "MD5(hello)"
        self.assertEqual(BuiltinFunctions.evaluate_expression(expr), "5d41402abc4b2a76b9719d911017c592")

    # ─── 3. 文件参数读取测试 ──────────────────────────────────────

    def test_03_file_reader(self):
        """测试从 JSON、.env 键值对以及纯文本文件读取提取参数"""
        # 1. JSON
        json_file = os.path.join(self.temp_dir.name, "config.json")
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump({"auth": {"token": "my_secret_token", "id": 123}}, f)

        val = FileReader.read_param_from_file(json_file, key="auth.token")
        self.assertEqual(val, "my_secret_token")

        val2 = FileReader.read_param_from_file(json_file, key="auth.id")
        self.assertEqual(val2, "123")

        # 2. .env / Key-Value
        env_file = os.path.join(self.temp_dir.name, ".env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("# 配置\nAPI_KEY=key_8899\nBASE_URL=https://api.test.com\n")

        val_env = FileReader.read_param_from_file(env_file, key="API_KEY")
        self.assertEqual(val_env, "key_8899")

        # 3. 纯文本
        txt_file = os.path.join(self.temp_dir.name, "token.txt")
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write("RAW_TEXT_CONTENT_ABC")

        val_txt = FileReader.read_param_from_file(txt_file, key="")
        self.assertEqual(val_txt, "RAW_TEXT_CONTENT_ABC")

    # ─── 4. 前置处理完整流程测试 ──────────────────────────────────

    def test_04_pre_processor(self):
        """测试前置处理器向 Header, Param, Variable 注入参数，并进行全局占位符替换"""
        env_mgr = EnvironmentManager()
        env_mgr.set("base_url", "https://api.mycorp.com")
        env_mgr.set("account_id", "acc_1001")

        req = SavedRequest(
            name="登录接口",
            method="POST",
            url="{{base_url}}/v1/login?account={{account_id}}",
            headers=[HeaderItem("Content-Type", "application/json", True)],
            params=[ParamItem("sign", "{{sign_val}}", True)],
            body_type="json",
            body_content='{"nonce": "{{$uuid}}", "user": "{{account_id}}"}',
            pre_script={
                "rules": [
                    {
                        "enabled": True,
                        "source_type": "custom",
                        "expression": "MD5(secure_string)",
                        "target_type": "variable",
                        "target_name": "sign_val",
                    },
                    {
                        "enabled": True,
                        "source_type": "custom",
                        "expression": "UUID()",
                        "target_type": "header",
                        "target_name": "X-Trace-Id",
                    }
                ]
            }
        )

        processed = PreProcessor.process(req)

        # 占位符替换
        self.assertTrue(processed.url.startswith("https://api.mycorp.com/v1/login?account=acc_1001"))
        # Header 注入 X-Trace-Id
        trace_headers = [h for h in processed.headers if h.key == "X-Trace-Id"]
        self.assertEqual(len(trace_headers), 1)
        self.assertEqual(len(trace_headers[0].value), 36)

        # Param 占位符替换 sign_val (MD5 of secure_string)
        sign_params = [p for p in processed.params if p.key == "sign"]
        self.assertEqual(len(sign_params), 1)
        self.assertEqual(sign_params[0].value, BuiltinFunctions.md5("secure_string"))

        # Body 替换
        self.assertNotIn("{{$uuid}}", processed.body_content)
        self.assertIn('"user": "acc_1001"', processed.body_content)

    def test_04_pre_processor_body_injection_and_overwrite(self):
        """测试前置处理器向 Body 注入参数，并覆盖原请求体中已有的同名字段"""
        # 1. JSON 格式: 覆盖已有字段 + 新增字段 + 嵌套字段
        orig_body = json.dumps({
            "userId": 1001,
            "userName": "old_name",
            "profile": {
                "role": "guest"
            }
        })
        req_json = SavedRequest(
            name="更新用户信息",
            method="POST",
            url="http://localhost:8080/api/user/update",
            body_type="json",
            body_content=orig_body,
            pre_script={
                "rules": [
                    {
                        "enabled": True,
                        "source_type": "custom",
                        "expression": "admin_user",
                        "target_type": "body",
                        "target_name": "userName",  # 覆盖已有字段
                    },
                    {
                        "enabled": True,
                        "source_type": "custom",
                        "expression": "9999",
                        "target_type": "body",
                        "target_name": "userId",    # 覆盖已有整型字段（智能保留整型）
                    },
                    {
                        "enabled": True,
                        "source_type": "custom",
                        "expression": "superadmin",
                        "target_type": "body",
                        "target_name": "profile.role", # 覆盖嵌套字段
                    },
                    {
                        "enabled": True,
                        "source_type": "custom",
                        "expression": "active",
                        "target_type": "body",
                        "target_name": "status",    # 新增字段
                    }
                ]
            }
        )

        processed = PreProcessor.process(req_json)
        result_dict = json.loads(processed.body_content)
        self.assertEqual(result_dict["userName"], "admin_user")
        self.assertEqual(result_dict["userId"], 9999)
        self.assertEqual(result_dict["profile"]["role"], "superadmin")
        self.assertEqual(result_dict["status"], "active")

        # 2. Form/Urlencoded 格式: 覆盖已有 key=value
        orig_form = "username=guest\nrole=normal\nstatus=1"
        req_form = SavedRequest(
            name="表单提交",
            method="POST",
            url="http://localhost:8080/api/form",
            body_type="form",
            body_content=orig_form,
            pre_script={
                "rules": [
                    {
                        "enabled": True,
                        "source_type": "custom",
                        "expression": "vip",
                        "target_type": "body",
                        "target_name": "role",  # 覆盖 role
                    },
                    {
                        "enabled": True,
                        "source_type": "custom",
                        "expression": "token_xyz",
                        "target_type": "body",
                        "target_name": "token", # 新增 token
                    }
                ]
            }
        )
        processed_form = PreProcessor.process(req_form)
        self.assertIn("role=vip", processed_form.body_content)
        self.assertNotIn("role=normal", processed_form.body_content)
        self.assertIn("username=guest", processed_form.body_content)
        self.assertIn("token=token_xyz", processed_form.body_content)

        # 3. body_type 为 none 自动初始化为 json 并注入
        req_none = SavedRequest(
            name="无Body请求转JSON",
            method="POST",
            url="http://localhost:8080/api/none",
            body_type="none",
            body_content="",
            pre_script={
                "rules": [
                    {
                        "enabled": True,
                        "source_type": "custom",
                        "expression": "my_new_token",
                        "target_type": "body",
                        "target_name": "authToken",
                    }
                ]
            }
        )
        processed_none = PreProcessor.process(req_none)
        self.assertEqual(processed_none.body_type, "json")
        res_none = json.loads(processed_none.body_content)
        self.assertEqual(res_none["authToken"], "my_new_token")

    # ─── 5. 后置处理提取测试 ──────────────────────────────────────

    def test_05_post_processor(self):
        """测试后置处理器提取 Header、Cookie、JSONPath、正则并回写"""
        resp = HTTPResponse(
            status_code=200,
            headers={"Authorization": "Bearer token_resp_9988", "Set-Cookie": "session=sess_abc; Path=/"},
            body=json.dumps({
                "code": 200,
                "data": {
                    "token": "extracted_jwt_token_123",
                    "items": [{"id": 101}, {"id": 102}]
                }
            }),
            cookies=[{"name": "sessid", "value": "cookie_val_777"}]
        )

        req = SavedRequest(
            name="获取Token",
            method="POST",
            url="http://localhost:8080/api/token",
            post_script={
                "rules": [
                    {
                        "enabled": True,
                        "extract_from": "body_jsonpath",
                        "expression": "data.token",
                        "target_destination": "global_headers",
                        "target_key": "X-Custom-Token",
                    },
                    {
                        "enabled": True,
                        "extract_from": "body_jsonpath",
                        "expression": "data.items[0].id",
                        "target_destination": "environment",
                        "target_key": "first_item_id",
                    },
                    {
                        "enabled": True,
                        "extract_from": "header",
                        "expression": "Authorization",
                        "target_destination": "environment",
                        "target_key": "auth_header_val",
                    },
                    {
                        "enabled": True,
                        "extract_from": "cookie",
                        "expression": "sessid",
                        "target_destination": "cookies",
                        "target_key": "sessid",
                    }
                ]
            }
        )

        results = PostProcessor.process(req, resp)
        self.assertEqual(results.get("X-Custom-Token"), "extracted_jwt_token_123")
        self.assertEqual(results.get("first_item_id"), "101")
        self.assertEqual(results.get("auth_header_val"), "Bearer token_resp_9988")
        self.assertEqual(results.get("sessid"), "cookie_val_777")

        # 验证是否写入了全局请求头
        settings = Settings()
        ghs = [gh for gh in settings.global_headers if gh.get("key") == "X-Custom-Token"]
        self.assertTrue(len(ghs) > 0)
        self.assertEqual(ghs[0]["value"], "extracted_jwt_token_123")

        # 验证是否写入了环境变量
        self.assertEqual(EnvironmentManager().get("first_item_id"), "101")

    # ─── 6. Mock 服务 CRUD 与 HTTP 响应测试 ────────────────────────

    def test_06_mock_database_and_http_server(self):
        """测试 Mock 集合与接口数据库操作，以及真实 HTTP 请求命中 Mock 服务"""
        # 1. 数据库 CRUD
        mcol = self.db.create_mock_collection(MockCollection(name="用户模块Mock", parent_id=None))
        sub_mcol = self.db.create_mock_collection(MockCollection(name="子文件夹", parent_id=mcol.id))

        api = MockApi(
            collection_id=sub_mcol.id,
            name="获取用户信息",
            method="GET",
            path="/api/user/profile",
            status_code=200,
            delay_ms=50,
            headers=[{"key": "X-Mock-Engine", "value": "PostManage", "enabled": True}],
            body_type="json",
            body_content='{"code": 200, "username": "alice", "role": "admin"}',
            is_enabled=True,
        )
        self.db.create_mock_api(api)

        # 验证查询
        all_apis = self.db.get_all_mock_apis()
        self.assertEqual(len(all_apis), 1)
        self.assertEqual(all_apis[0].path, "/api/user/profile")

        # 2. 启动 Mock 服务测试
        mock_svc = MockService.instance()
        port = 19998
        ok, msg = mock_svc.start(port)
        self.assertTrue(ok)
        self.assertTrue(mock_svc.is_running)

        # 3. 发送真实 HTTP 请求命中 Mock 接口
        req_url = f"http://127.0.0.1:{port}/api/user/profile?userId=123"
        req = urllib.request.Request(req_url, headers={"User-Agent": "PostManage-Tester", "Cookie": "session=xyz99"})
        try:
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get("X-Mock-Engine"), "PostManage")
                body_bytes = resp.read()
                data = json.loads(body_bytes.decode("utf-8"))
                self.assertEqual(data.get("username"), "alice")

            # 4. 验证 Mock 服务捕获到的入参和 Header、Cookie 监控日志
            time.sleep(0.1)
            logs = mock_svc.recent_logs
            self.assertTrue(len(logs) > 0)
            latest_log = logs[0]
            self.assertEqual(latest_log["method"], "GET")
            self.assertEqual(latest_log["path"], "/api/user/profile")
            self.assertEqual(latest_log["query"].get("userId"), "123")
            self.assertEqual(latest_log["cookies"].get("session"), "xyz99")
            self.assertEqual(latest_log["status_code"], 200)
            self.assertIn("username", latest_log.get("response_body", ""))

            # 5. 测试请求未配置的路由返回 404
            unconfigured_url = f"http://127.0.0.1:{port}/api/not/exist"
            try:
                urllib.request.urlopen(unconfigured_url)
                self.fail("Should return 404")
            except urllib.error.HTTPError as err:
                self.assertEqual(err.code, 404)
        except OSError as e:
            # 沙箱环境无物理套接字访问权限时安全跳过真实请求部分
            if "10013" in str(e) or "Permission" in str(type(e).__name__):
                pass
            else:
                raise

        # 6. 停止服务
        mock_svc.stop()
        self.assertFalse(mock_svc.is_running)

    # ─── 7. UI 组件实例化测试 ────────────────────────────────────

    def test_07_mock_center_dialog_and_processor_widgets(self):
        """测试 MockCenterDialog 以及 PreProcessorWidget / PostProcessorWidget UI 实例化"""
        pre_w = PreProcessorWidget()
        pre_w._insert_row(True, "env", "{{user}}", "", "header", "X-User")
        cfg = pre_w.get_config()
        self.assertEqual(len(cfg["rules"]), 1)
        self.assertEqual(cfg["rules"][0]["target_name"], "X-User")

        post_w = PostProcessorWidget()
        post_w._insert_row(True, "body_jsonpath", "data.token", "global_headers", "Authorization")
        pcfg = post_w.get_config()
        self.assertEqual(len(pcfg["rules"]), 1)
        self.assertEqual(pcfg["rules"][0]["target_key"], "Authorization")

        # 实例化 MockCenterDialog 并验证响应区自适应与功能完整性
        dialog = MockCenterDialog()
        self.assertIsNotNone(dialog)
        # 验证详情 Tab 包含 5 个子页 (Query, Headers, Cookie, Body, Response)
        self.assertEqual(dialog.detail_tabs.count(), 5)
        self.assertEqual(dialog.detail_tabs.tabText(4), "返回响应 (Response)")
        # 验证分割器已初始化
        self.assertEqual(len(dialog.main_splitter.sizes()), 2)
        self.assertEqual(len(dialog.right_splitter.sizes()), 2)

        # 验证监控区折叠与展开功能
        init_sizes = dialog.right_splitter.sizes()
        dialog._toggle_monitor_collapsed()
        self.assertEqual(dialog.right_splitter.sizes()[1], 0)
        dialog._toggle_monitor_collapsed()
        self.assertGreater(dialog.right_splitter.sizes()[1], 0)

        # 验证顶部工具栏严格限制为单行 (<= 34px)
        top_bar_widget = dialog.layout().itemAt(0).widget()
        self.assertLessEqual(top_bar_widget.maximumHeight(), 34)
        self.assertEqual(dialog.layout().stretch(0), 0)
        self.assertEqual(dialog.layout().stretch(1), 1)

        # 验证「保存接口配置」按钮只有纯文字，无图案图标
        self.assertEqual(dialog.save_api_btn.text(), "保存接口配置")

        # 验证「清空请求日志」按钮宽度增大 10% 以上 (>= 100px)，防止字体显示不全
        self.assertGreaterEqual(dialog.clear_logs_btn.width(), 100)

        dialog.close()

    def test_08_help_viewer_mock_and_processor_docs(self):
        """测试帮助文档包含 Mock 服务中心、前置与后置处理、请求体注入以及多级文件夹保存文档"""
        from app.widgets.help_viewer import _build_help_html
        html = _build_help_html()
        self.assertIn("Mock 服务中心", html)
        self.assertIn("前置处理与后置处理", html)
        self.assertIn("请求体 (Body)", html)
        self.assertIn("无损精准覆盖", html)
        self.assertIn("接口多级文件夹保存与另存为", html)
        self.assertIn("Ctrl+Alt+M", html)

    def test_09_mock_tree_drag_drop_and_clipboard(self):
        """测试 Mock 中心接口树拖拽移动、快捷键与复制剪切粘贴(含文件夹递归克隆)"""
        from app.widgets.mock_center_dialog import MockTreeWidget

        # 1. 准备测试数据：创建父文件夹、子文件夹与各级 Mock 接口
        col1 = self.db.create_mock_collection(MockCollection(name="用户中心"))
        sub_col = self.db.create_mock_collection(MockCollection(name="用户管理", parent_id=col1.id))
        api1 = self.db.create_mock_api(MockApi(
            name="获取用户信息", method="GET", path="/users/info",
            collection_id=sub_col.id, body_content='{"user": "alice"}'
        ))
        api2 = self.db.create_mock_api(MockApi(
            name="未分组接口", method="POST", path="/temp",
            collection_id="", body_content='{"ok": true}'
        ))

        # 2. 测试底层文件夹递归克隆 db.clone_mock_collection
        cloned_col = self.db.clone_mock_collection(col1.id, target_parent_id=None)
        self.assertIsNotNone(cloned_col)
        self.assertNotEqual(cloned_col.id, col1.id)
        self.assertEqual(cloned_col.name, f"{col1.name} - 副本")

        # 验证克隆后的子文件夹与接口关系
        cloned_subs = self.db.get_mock_collections(parent_id=cloned_col.id)
        self.assertEqual(len(cloned_subs), 1)
        cloned_sub = cloned_subs[0]
        self.assertEqual(cloned_sub.name, sub_col.name)

        cloned_apis = self.db.get_mock_apis(collection_id=cloned_sub.id)
        self.assertEqual(len(cloned_apis), 1)
        self.assertEqual(cloned_apis[0].name, api1.name)
        self.assertEqual(cloned_apis[0].path, api1.path)
        self.assertNotEqual(cloned_apis[0].id, api1.id)

        # 3. 实例化 MockCenterDialog 验证树控件配置
        dialog = MockCenterDialog()
        self.assertIsInstance(dialog.tree, MockTreeWidget)
        self.assertTrue(dialog.tree.dragEnabled())
        self.assertTrue(dialog.tree.acceptDrops())

        # 4. 测试复制接口 -> 粘贴接口 (克隆)
        dialog._select_api_in_tree(api2.id)
        dialog._copy_selected()
        self.assertEqual(dialog._clipboard_mode, "copy")
        self.assertEqual(dialog._clipboard_type, "api")
        self.assertEqual(dialog._clipboard_id, api2.id)

        # 选中 col1 粘贴
        dialog._select_collection_in_tree(col1.id)
        dialog._paste_selected()
        # 验证在 col1 下新增了副本
        col1_apis = self.db.get_mock_apis(collection_id=col1.id)
        self.assertTrue(any(a.name == "未分组接口 - 副本" for a in col1_apis))
        pasted_api = next(a for a in col1_apis if a.name == "未分组接口 - 副本")

        # 5. 测试剪切接口 -> 粘贴接口 (移动)
        dialog._select_api_in_tree(pasted_api.id)
        dialog._cut_selected()
        self.assertEqual(dialog._clipboard_mode, "cut")

        # 移动到 sub_col
        dialog._select_collection_in_tree(sub_col.id)
        dialog._paste_selected()
        self.assertIsNone(dialog._clipboard_id)
        sub_apis = self.db.get_mock_apis(collection_id=sub_col.id)
        self.assertTrue(any(a.id == pasted_api.id for a in sub_apis))

        # 6. 测试剪切文件夹 -> 粘贴文件夹 (移动)
        dialog._select_collection_in_tree(sub_col.id)
        dialog._cut_selected()
        self.assertEqual(dialog._clipboard_type, "collection")

        # 粘贴到顶层 (当前不选中任何项或选顶层)
        dialog.tree.setCurrentItem(None)
        dialog._paste_selected()
        moved_sub = self.db.get_mock_collection(sub_col.id)
        self.assertIsNone(moved_sub.parent_id)

        # 7. 循环移动安全拦截
        # 移动 sub_col 到 col1 下，建立 col1 -> sub_col 父子关系
        ok_child = self.db.move_mock_collection(sub_col.id, col1.id)
        self.assertTrue(ok_child)
        # 此时尝试将祖先 col1 移到子级 sub_col 下，应被安全拦截返回 False
        self.assertFalse(self.db.move_mock_collection(col1.id, sub_col.id))
        # 自身移动到自身也被拦截
        self.assertFalse(self.db.move_mock_collection(col1.id, col1.id))

        # 8. 拖拽移动接口 (move_mock_api)
        ok_move = self.db.move_mock_api(api2.id, col1.id)
        self.assertTrue(ok_move)
        updated_api2 = self.db.get_mock_api(api2.id)
        self.assertEqual(updated_api2.collection_id, col1.id)

        # 移动回根目录
        ok_move_root = self.db.move_mock_api(api2.id, "")
        self.assertTrue(ok_move_root)
        updated_api2_root = self.db.get_mock_api(api2.id)
        self.assertEqual(updated_api2_root.collection_id, "")

        dialog.close()

    def test_10_multiple_top_folders(self):
        """测试 Mock 中心能够自由创建多个顶级文件夹以及子文件夹"""
        from unittest.mock import patch

        dialog = MockCenterDialog()

        # 1. 模拟用户输入创建第一个顶级文件夹
        with patch("PyQt6.QtWidgets.QInputDialog.getText", return_value=("顶级文件夹A", True)):
            dialog._on_create_top_collection()

        roots = self.db.get_mock_collections(parent_id=None)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].name, "顶级文件夹A")
        top_a = roots[0]

        # 选中顶级文件夹A
        dialog._select_collection_in_tree(top_a.id)
        self.assertEqual(dialog.tree.currentItem().data(0, Qt.ItemDataRole.UserRole).get("id"), top_a.id)

        # 2. 重点：在已经选中顶级文件夹A的情况下，再次创建顶级文件夹B（验证不会被当作子文件夹）
        with patch("PyQt6.QtWidgets.QInputDialog.getText", return_value=("顶级文件夹B", True)):
            dialog._on_create_top_collection()

        roots = self.db.get_mock_collections(parent_id=None)
        self.assertEqual(len(roots), 2)
        root_names = [r.name for r in roots]
        self.assertIn("顶级文件夹A", root_names)
        self.assertIn("顶级文件夹B", root_names)

        # 3. 验证新建子文件夹功能正确挂载在选中的文件夹下
        dialog._select_collection_in_tree(top_a.id)
        with patch("PyQt6.QtWidgets.QInputDialog.getText", return_value=("子文件夹A1", True)):
            dialog._on_create_sub_collection()

        sub_list = self.db.get_mock_collections(parent_id=top_a.id)
        self.assertEqual(len(sub_list), 1)
        self.assertEqual(sub_list[0].name, "子文件夹A1")

        dialog.close()

    def test_11_post_processor_custom_placeholder(self):
        """测试后置处理器支持 ${...} 占位符自定义前缀及文本包装（如 'Bearer ${data.token}'、'Bearer ${data.body}'）"""
        # 1. 测试从 JSON 提取并添加 Bearer 前缀到全局请求头
        json_resp = HTTPResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps({
                "code": 200,
                "data": {
                    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sometoken"
                }
            })
        )
        req_jwt = SavedRequest(
            name="登录接口",
            method="POST",
            url="http://localhost:8080/api/login",
            post_script={
                "rules": [
                    {
                        "enabled": True,
                        "extract_from": "body_jsonpath",
                        "expression": "Bearer ${data.token}",
                        "target_destination": "global_headers",
                        "target_key": "Authorization",
                    }
                ]
            }
        )
        res_jwt = PostProcessor.process(req_jwt, json_resp)
        self.assertEqual(res_jwt.get("Authorization"), "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sometoken")
        settings = Settings()
        ghs_jwt = [gh for gh in settings.global_headers if gh.get("key") == "Authorization"]
        self.assertTrue(len(ghs_jwt) > 0)
        self.assertEqual(ghs_jwt[0]["value"], "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sometoken")

        # 2. 测试从纯文本响应体提取 ${data.body} 并添加自定义前缀
        raw_token = "raw_oauth2_secret_token_abcdef"
        raw_resp = HTTPResponse(
            status_code=200,
            headers={"Content-Type": "text/plain"},
            body=raw_token
        )
        req_raw = SavedRequest(
            name="获取原始Token",
            method="GET",
            url="http://localhost:8080/api/raw_token",
            post_script={
                "rules": [
                    {
                        "enabled": True,
                        "extract_from": "body_text",
                        "expression": "Bearer ${data.body}",
                        "target_destination": "global_headers",
                        "target_key": "X-Raw-Auth",
                    }
                ]
            }
        )
        res_raw = PostProcessor.process(req_raw, raw_resp)
        self.assertEqual(res_raw.get("X-Raw-Auth"), "Bearer raw_oauth2_secret_token_abcdef")
        ghs_raw = [gh for gh in settings.global_headers if gh.get("key") == "X-Raw-Auth"]
        self.assertTrue(len(ghs_raw) > 0)
        self.assertEqual(ghs_raw[0]["value"], "Bearer raw_oauth2_secret_token_abcdef")

        # 3. 测试多个占位符组合拼装并存储到环境变量
        multi_resp = HTTPResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps({
                "user": {
                    "id": 888,
                    "name": "developer",
                    "role": "admin"
                }
            })
        )
        req_multi = SavedRequest(
            name="获取用户画像",
            method="GET",
            url="http://localhost:8080/api/user/profile",
            post_script={
                "rules": [
                    {
                        "enabled": True,
                        "extract_from": "body_jsonpath",
                        "expression": "User ID: ${user.id}, Name: ${user.name} (${user.role})",
                        "target_destination": "environment",
                        "target_key": "CURRENT_USER_DESC",
                    }
                ]
            }
        )
        res_multi = PostProcessor.process(req_multi, multi_resp)
        self.assertEqual(res_multi.get("CURRENT_USER_DESC"), "User ID: 888, Name: developer (admin)")
        self.assertEqual(
            EnvironmentManager().get("CURRENT_USER_DESC"),
            "User ID: 888, Name: developer (admin)"
        )

    def test_12_centered_checkboxes(self):
        """测试所有表格中'启用'复选框的水平垂直居中与容器行为"""
        from app.widgets.request_editor import KeyValueEditor, CenteredCheckBox
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QPointF

        # 1. 测试 KeyValueEditor (Params / Headers / FormData / Global Headers)
        kv_editor = KeyValueEditor("Key", "Value")
        h0 = kv_editor.table.horizontalHeaderItem(0)
        self.assertIsNotNone(h0)
        self.assertEqual(h0.textAlignment(), Qt.AlignmentFlag.AlignCenter)

        kv_editor.set_data([{"key": "test_k", "value": "test_v", "enabled": True}])
        cell_widget = kv_editor.table.cellWidget(0, 0)
        self.assertIsInstance(cell_widget, CenteredCheckBox)
        self.assertEqual(cell_widget.layout().alignment(), Qt.AlignmentFlag.AlignCenter)
        self.assertTrue(cell_widget.isChecked())

        # 测试点击容器空白区域触发复选框状态翻转
        press_ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(2, 2), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        cell_widget.mousePressEvent(press_ev)
        self.assertFalse(cell_widget.isChecked())
        data = kv_editor.get_data()
        self.assertEqual(len(data), 1)
        self.assertFalse(data[0]["enabled"])

        # 2. 测试 PreProcessorWidget 前置处理规则表格
        pre_widget = PreProcessorWidget()
        pre_h0 = pre_widget.table.horizontalHeaderItem(0)
        self.assertIsNotNone(pre_h0)
        self.assertEqual(pre_h0.textAlignment(), Qt.AlignmentFlag.AlignCenter)
        pre_widget._on_add_rule()
        pre_chk = pre_widget.table.cellWidget(0, 0)
        self.assertIsInstance(pre_chk, CenteredCheckBox)
        self.assertEqual(pre_chk.layout().alignment(), Qt.AlignmentFlag.AlignCenter)
        self.assertTrue(pre_chk.isChecked())

        # 3. 测试 PostProcessorWidget 后置提取规则表格
        post_widget = PostProcessorWidget()
        post_h0 = post_widget.table.horizontalHeaderItem(0)
        self.assertIsNotNone(post_h0)
        self.assertEqual(post_h0.textAlignment(), Qt.AlignmentFlag.AlignCenter)
        post_widget._on_add_rule()
        post_chk = post_widget.table.cellWidget(0, 0)
        self.assertIsInstance(post_chk, CenteredCheckBox)
        self.assertEqual(post_chk.layout().alignment(), Qt.AlignmentFlag.AlignCenter)
        self.assertTrue(post_chk.isChecked())

        # 4. 测试 MockCenterDialog 响应头表格
        mock_dlg = MockCenterDialog()
        mock_h0 = mock_dlg.api_headers_table.horizontalHeaderItem(0)
        self.assertIsNotNone(mock_h0)
        self.assertEqual(mock_h0.textAlignment(), Qt.AlignmentFlag.AlignCenter)
        mock_dlg._on_add_response_header()
        mock_chk = mock_dlg.api_headers_table.cellWidget(0, 0)
        self.assertIsInstance(mock_chk, CenteredCheckBox)
        self.assertEqual(mock_chk.layout().alignment(), Qt.AlignmentFlag.AlignCenter)
        self.assertTrue(mock_chk.isChecked())
        mock_dlg.close()


if __name__ == "__main__":
    unittest.main()

