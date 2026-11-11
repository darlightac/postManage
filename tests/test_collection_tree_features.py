"""自动化测试套件：验证多级文件夹、拖拽与剪贴板、取消发送、日志与界面修复
1. 数据库多级集合移动 move_collection 与循环引用防御
2. 数据库请求移动 move_request 与克隆 clone_request
3. 集合树多级展开/折叠状态保持与剪贴板 (复制/剪切/粘贴)
4. 日志系统 RotatingFileHandler 与路径有效性
5. JSON 格式化按钮尺寸与样式
6. 请求取消即时复位与响应反馈
"""

import os
import sys
import unittest
import tempfile
from pathlib import Path

# 确保控制台输出编码兼容
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 添加项目根目录到 sys.path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from app.core.db import Database
from app.core.models import Collection, SavedRequest, HTTPResponse
from app.core.logger import get_logger
from app.config.settings import get_log_dir, get_log_path
from app.widgets.collection_tree import CollectionTree
from app.widgets.request_editor import RequestEditor
from app.widgets.request_tabs import RequestTabPage, RequestTabBar


class TestCollectionTreeFeatures(unittest.TestCase):

    def setUp(self):
        self.db = Database()
        self._created_collections = []

    def tearDown(self):
        for cid in self._created_collections:
            try:
                self.db.delete_collection(cid)
            except Exception:
                pass

    def test_01_db_move_collection_and_cycle_prevention(self):
        """测试 1：数据库多级文件夹层级移动与祖先防循环检测"""
        # 创建结构: root_a, root_b, child_a1 under root_a, sub_a1_1 under child_a1
        c_a = self.db.create_collection(Collection(name="Folder A"))
        c_b = self.db.create_collection(Collection(name="Folder B"))
        c_a1 = self.db.create_collection(Collection(name="SubFolder A1", parent_id=c_a.id))
        c_a1_1 = self.db.create_collection(Collection(name="SubFolder A1-1", parent_id=c_a1.id))
        self._created_collections.extend([c_a.id, c_b.id])

        # 正常移动：将 SubFolder A1-1 移动到 Folder B 下
        ok = self.db.move_collection(c_a1_1.id, c_b.id)
        self.assertTrue(ok)
        reloaded = self.db.get_collection(c_a1_1.id)
        self.assertEqual(reloaded.parent_id, c_b.id)

        # 防循环移动：尝试将 Folder A 移动到它的子文件夹 SubFolder A1 下，应被安全拦截拒绝（返回 False）
        cycle_result = self.db.move_collection(c_a.id, c_a1.id)
        self.assertFalse(cycle_result)

        # 恢复验证：Folder A 的 parent_id 仍为空
        root_a_check = self.db.get_collection(c_a.id)
        self.assertIsNone(root_a_check.parent_id)
        print("[PASS] Collection move and cycle prevention verified")

    def test_02_db_move_and_clone_request(self):
        """测试 2：数据库请求移动与深拷贝副本克隆"""
        c1 = self.db.create_collection(Collection(name="Col 1"))
        c2 = self.db.create_collection(Collection(name="Col 2"))
        self._created_collections.extend([c1.id, c2.id])

        req = SavedRequest(
            collection_id=c1.id,
            name="Login API",
            method="POST",
            url="https://api.test.com/login",
            body_type="json",
            body_content='{"user": "admin"}',
        )
        saved = self.db.create_request(req)
        self.assertEqual(saved.collection_id, c1.id)

        # 跨集合移动
        ok = self.db.move_request(saved.id, c2.id)
        self.assertTrue(ok)
        moved = self.db.get_request(saved.id)
        self.assertEqual(moved.collection_id, c2.id)

        # 深拷贝克隆到 c1
        cloned = self.db.clone_request(saved.id, c1.id, new_name="Login API (Copy)")
        self.assertIsNotNone(cloned)
        self.assertNotEqual(cloned.id, saved.id)
        self.assertEqual(cloned.collection_id, c1.id)
        self.assertEqual(cloned.name, "Login API (Copy)")
        self.assertEqual(cloned.url, saved.url)
        self.assertEqual(cloned.body_content, saved.body_content)
        print("[PASS] Request move and clone verified")

    def test_03_collection_tree_ui_clipboard_and_actions(self):
        """测试 3：CollectionTree 树形控件多级加载、全部展开/折叠、剪贴板复制/剪切/粘贴"""
        tree_widget = CollectionTree()
        c1 = self.db.create_collection(Collection(name="Main Folder"))
        sub1 = self.db.create_collection(Collection(name="Child Folder", parent_id=c1.id))
        self._created_collections.append(c1.id)
        r1 = self.db.create_request(SavedRequest(collection_id=c1.id, name="Req 1", method="GET", url="http://a.com"))

        tree_widget.refresh_tree()
        self.assertGreater(tree_widget.tree.topLevelItemCount(), 0)

        # 展开/折叠全部
        tree_widget._on_expand_all()
        # 折叠全部
        tree_widget._on_collapse_all()

        # 测试复制与粘贴
        tree_widget._copy_request(r1.id)
        tree_widget._paste_to_collection(sub1.id)

        # 验证 sub1 下已克隆新请求
        sub1_reqs = self.db.get_requests(sub1.id)
        self.assertEqual(len(sub1_reqs), 1)
        self.assertIn("Req 1", sub1_reqs[0].name)

        # 测试剪切与粘贴
        tree_widget._cut_request(r1.id)
        tree_widget._paste_to_collection(sub1.id)

        # 验证 r1 已转移到 sub1 下
        r1_reloaded = self.db.get_request(r1.id)
        self.assertEqual(r1_reloaded.collection_id, sub1.id)
        self.assertIsNone(tree_widget._clipboard_action)
        print("[PASS] CollectionTree clipboard copy/cut/paste verified")

    def test_04_logger_system(self):
        """测试 4：日志系统初始化与文件输出验证"""
        logger = get_logger("test_module")
        test_msg = "PostManage test log line"
        logger.info(test_msg)

        log_path = get_log_path()
        self.assertTrue(log_path.parent.exists())
        self.assertTrue(log_path.exists())

        content = log_path.read_text(encoding="utf-8")
        self.assertIn("test_module", content)
        self.assertIn(test_msg, content)
        print("[PASS] Logger system verified")

    def test_05_json_format_button_dimensions(self):
        """测试 5：格式化 JSON 按钮紧凑尺寸与样式保护（紧凑优雅且完全展示文字）"""
        editor = RequestEditor()
        btn = editor.json_format_btn
        self.assertEqual(btn.height(), 24)
        fm = btn.fontMetrics()
        self.assertGreaterEqual(btn.sizeHint().width(), fm.horizontalAdvance(btn.text()))
        self.assertLessEqual(btn.sizeHint().width(), 110)
        self.assertIn("padding", btn.styleSheet().lower())
        print("[PASS] JSON format button dimensions verified")

    def test_06_cancel_request_behavior(self):
        """测试 6：请求取消即时重置 UI 与响应面板呈现已取消"""
        page = RequestTabPage()
        editor = page.request_editor
        editor.set_sending_state(True)
        self.assertTrue(editor._sending)
        self.assertEqual(editor.send_btn.text(), "取消发送")

        # 模拟取消触发
        editor.set_sending_state(False)
        self.assertFalse(editor._sending)
        self.assertEqual(editor.send_btn.text(), "发送")

        # 响应面板展示已取消
        page.response_viewer.set_response(HTTPResponse(error="请求已取消"))
        self.assertEqual(page.response_viewer._current_error, "请求已取消")
        self.assertIn("请求已取消", page.response_viewer.raw_view.toPlainText())
        print("[PASS] Cancel request instant reset verified")

    def test_07_drag_and_drop_request_safe_persistence(self):
        """测试 7：拖拽接口至目标文件夹，验证 SQLite 与 UI 树双重保留，绝不丢失"""
        from PyQt6.QtCore import QPointF, QMimeData, Qt
        from PyQt6.QtGui import QDropEvent

        c_src = self.db.create_collection(Collection(name="Source Folder"))
        c_dst = self.db.create_collection(Collection(name="Target Folder"))
        self._created_collections.extend([c_src.id, c_dst.id])

        req = self.db.create_request(SavedRequest(
            collection_id=c_src.id,
            name="Drag Test Request",
            method="POST",
            url="http://test.com/api"
        ))

        panel = CollectionTree()
        panel.refresh_tree()

        # 找到源请求节点和目标文件夹节点
        tree = panel.tree
        req_item = None
        dst_item = None
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            t_data = top.data(0, Qt.ItemDataRole.UserRole)
            if t_data and t_data.get("id") == c_dst.id:
                dst_item = top
            for j in range(top.childCount()):
                child = top.child(j)
                c_data = child.data(0, Qt.ItemDataRole.UserRole)
                if c_data and c_data.get("id") == req.id:
                    req_item = child

        self.assertIsNotNone(req_item, "源请求应在树上找到")
        self.assertIsNotNone(dst_item, "目标集合应在树上找到")

        # 模拟设置拖拽数据与目标位置 dropEvent
        tree._dragged_item = req_item
        tree._dragged_data = dict(req_item.data(0, Qt.ItemDataRole.UserRole))
        target_pos = tree.visualItemRect(dst_item).center()

        mime = QMimeData()
        mime.setData("application/x-postmanage-tree-item", b"1")
        drop_ev = QDropEvent(
            QPointF(target_pos),
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )

        tree.dropEvent(drop_ev)

        # 1. 验证 SQLite 数据库中已被转移到目标集合
        reloaded_req = self.db.get_request(req.id)
        self.assertEqual(reloaded_req.collection_id, c_dst.id, "数据库中接口所属集合应为目标集合")

        # 2. 验证 UI 树中目标集合下存在该接口节点且未被删除丢失
        dst_found_in_tree = False
        req_found_in_dst = False
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            t_data = top.data(0, Qt.ItemDataRole.UserRole)
            if t_data and t_data.get("id") == c_dst.id:
                dst_found_in_tree = True
                self.assertTrue(top.isExpanded(), "目标集合刷新后应自动展开")
                for j in range(top.childCount()):
                    child = top.child(j)
                    c_data = child.data(0, Qt.ItemDataRole.UserRole)
                    if c_data and c_data.get("id") == req.id:
                        req_found_in_dst = True
                        break

        self.assertTrue(dst_found_in_tree, "UI 树上目标集合应存在")
        self.assertTrue(req_found_in_dst, "UI 树上目标集合下必须正常展示该接口，严禁丢失！")
        print("[PASS] Drag and drop request safe persistence verified (no loss)")

    def test_08_drag_into_nested_subfolder_ancestor_expansion(self):
        """测试 8：拖拽接口至多级嵌套折叠子文件夹，祖先链全部展开且保证可见"""
        from PyQt6.QtCore import Qt

        root = self.db.create_collection(Collection(name="Root Parent"))
        sub1 = self.db.create_collection(Collection(name="Level 1 Sub", parent_id=root.id))
        sub2 = self.db.create_collection(Collection(name="Level 2 Sub", parent_id=sub1.id))
        self._created_collections.extend([root.id, sub1.id, sub2.id])

        req = self.db.create_request(SavedRequest(
            collection_id=root.id,
            name="Deep Nested Req",
            method="GET",
            url="http://nested.com"
        ))

        # 将请求移至 sub2
        self.db.move_request(req.id, sub2.id)

        panel = CollectionTree()
        # 刷新树并指定展开目标 sub2
        panel.refresh_tree(select_id=req.id, expand_id=sub2.id)
        tree = panel.tree

        # 验证祖先链：root 和 sub1 均必须被自动展开
        root_item = None
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            data = top.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("id") == root.id:
                root_item = top
                break

        self.assertIsNotNone(root_item)
        self.assertTrue(root_item.isExpanded(), "顶级祖先集合必须被展开")

        sub1_item = None
        for i in range(root_item.childCount()):
            child = root_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("id") == sub1.id:
                sub1_item = child
                break

        self.assertIsNotNone(sub1_item)
        self.assertTrue(sub1_item.isExpanded(), "一级父集合必须被展开")

        sub2_item = None
        for i in range(sub1_item.childCount()):
            child = sub1_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("id") == sub2.id:
                sub2_item = child
                break

        self.assertIsNotNone(sub2_item)
        self.assertTrue(sub2_item.isExpanded(), "目标子文件夹自身必须被展开")

        # 当前选中的项目应为 req
        self.assertIsNotNone(tree.currentItem())
        curr_data = tree.currentItem().data(0, Qt.ItemDataRole.UserRole)
        self.assertEqual(curr_data.get("id"), req.id, "移动后应自动滚动高亮选中该接口")
        print("[PASS] Drag into nested subfolder ancestor expansion verified")

    def test_09_drag_hover_overlay_and_clear(self):
        """测试 9：拖拽悬停高亮判定、清除与悬停定时器"""
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QDragMoveEvent, QDragLeaveEvent

        c = self.db.create_collection(Collection(name="Hover Target"))
        self._created_collections.append(c.id)

        panel = CollectionTree()
        panel.refresh_tree()
        panel.show()
        tree = panel.tree

        # 找到目标项
        target_item = None
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            if top.data(0, Qt.ItemDataRole.UserRole).get("id") == c.id:
                target_item = top
                break
        self.assertIsNotNone(target_item)

        # 模拟正在拖拽接口
        tree._dragged_data = {"type": "request", "id": "test_req", "collection_id": "other"}
        pos = tree.visualItemRect(target_item).center()

        move_ev = QDragMoveEvent(
            pos,
            Qt.DropAction.MoveAction,
            None,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        tree.dragMoveEvent(move_ev)
        self.assertEqual(tree._hover_target_item, target_item, "悬停时应锁定目标文件夹")

        # 离开事件
        tree._clear_hover()
        self.assertIsNone(tree._hover_target_item, "离开时悬停高亮目标应清空")
        self.assertFalse(tree._hover_timer.isActive(), "离开时悬停定时器应停止")
        print("[PASS] Drag hover overlay and clear verified")


if __name__ == "__main__":
    unittest.main()
