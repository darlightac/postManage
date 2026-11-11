"""自定义数据存储目录与日志输出目录自动化测试"""

import sys
import os
import shutil
import tempfile
from pathlib import Path
import unittest

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.settings import (
    get_app_dir,
    get_default_data_dir,
    get_default_log_dir,
    get_data_dir,
    get_db_path,
    get_log_dir,
    get_log_path,
    _get_bootstrap_path,
    Settings,
)
from app.core.logger import get_logger, reconfigure_logging
from app.core.db import Database
from app.core.models import Collection


class TestCustomPaths(unittest.TestCase):
    """测试自定义存储目录与日志目录体系"""

    def setUp(self):
        # 记录原始路径和配置
        self.orig_settings = Settings()
        self.orig_custom_data = self.orig_settings.custom_data_dir
        self.orig_custom_log = self.orig_settings.custom_log_dir
        self.orig_db_path = Database().db_path

        # 创建临时隔离测试目录
        self.test_dir = Path(tempfile.mkdtemp(prefix="postmanage_test_paths_"))
        self.temp_data_dir = self.test_dir / "custom_data"
        self.temp_log_dir = self.test_dir / "custom_logs"

    def tearDown(self):
        # 恢复原始设置与数据库
        self.orig_settings.set_custom_paths(self.orig_custom_data, self.orig_custom_log)
        Database().switch_database(self.orig_db_path)
        reconfigure_logging()

        # 清理临时目录
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_default_paths_structure(self):
        """测试默认便携路径结构是否正确"""
        app_dir = get_app_dir()
        self.assertTrue(app_dir.exists(), "应用主目录必须存在")

        def_data = get_default_data_dir()
        def_log = get_default_log_dir()

        self.assertEqual(def_data, app_dir / "data", "默认数据目录必须位于应用同级 data")
        self.assertEqual(def_log, app_dir / "data" / "logs", "默认日志目录必须位于应用同级 data/logs")

    def test_set_custom_paths_and_getter(self):
        """测试设置自定义路径并验证 get_data_dir / get_log_dir 正确性"""
        settings = Settings()
        settings.set_custom_paths(str(self.temp_data_dir), str(self.temp_log_dir))

        self.assertEqual(settings.custom_data_dir, str(self.temp_data_dir))
        self.assertEqual(settings.custom_log_dir, str(self.temp_log_dir))
        self.assertFalse(settings.is_default_data_dir)
        self.assertFalse(settings.is_default_log_dir)

        # 验证全局路径解析器返回指定自定义目录
        self.assertEqual(get_data_dir(), self.temp_data_dir.resolve())
        self.assertEqual(get_log_dir(), self.temp_log_dir.resolve())
        self.assertEqual(get_db_path(), (self.temp_data_dir / "requestmanager.db").resolve())
        self.assertEqual(get_log_path(), (self.temp_log_dir / "postmanage.log").resolve())

    def test_switch_database_and_crud(self):
        """测试数据库热切换到新目录并执行增删改查"""
        new_db_path = str(self.temp_data_dir / "requestmanager.db")
        db = Database()
        db.switch_database(new_db_path)

        self.assertEqual(Path(db.db_path).resolve(), Path(new_db_path).resolve())
        self.assertTrue(Path(new_db_path).exists(), "热切换后新数据库文件必须自动创建")

        # 在新数据库中新建一个测试集合
        col = Collection(name="自定义路径测试集合")
        created_col = db.create_collection(col)
        self.assertIsNotNone(created_col.id, "新集合应创建成功且具有 ID")
        self.assertTrue(bool(created_col.id), "新集合 ID 应为非空字符串")

        cols = db.get_collections()
        col_names = [c.name for c in cols]
        self.assertIn("自定义路径测试集合", col_names, "新集合应存在于切换后的新数据库中")

    def test_reconfigure_logging(self):
        """测试日志重定向到自定义日志目录"""
        custom_log_file = self.temp_log_dir / "postmanage.log"
        reconfigure_logging(custom_log_file)

        logger = get_logger("test_custom_paths")
        test_msg = "TEST_LOG_MESSAGE_CUSTOM_PATH_VERIFICATION_12345"
        logger.info(test_msg)

        # 验证日志文件已生成并写入
        self.assertTrue(custom_log_file.exists(), "自定义日志文件必须已生成")
        content = custom_log_file.read_text(encoding="utf-8")
        self.assertIn(test_msg, content, "自定义日志文件中必须包含写入的消息")

    def test_reset_paths_to_default(self):
        """测试一键恢复默认路径"""
        settings = Settings()
        # 先设置为自定义
        settings.set_custom_paths(str(self.temp_data_dir), str(self.temp_log_dir))
        self.assertFalse(settings.is_default_data_dir)

        # 恢复默认
        settings.reset_paths_to_default()
        self.assertTrue(settings.is_default_data_dir, "恢复后应判定为默认数据目录")
        self.assertTrue(settings.is_default_log_dir, "恢复后应判定为默认日志目录")
        self.assertIsNone(settings.custom_data_dir)
        self.assertIsNone(settings.custom_log_dir)


if __name__ == "__main__":
    unittest.main()
