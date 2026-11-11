"""前置处理与后置处理 UI 组件"""

import os
from typing import Dict, Any, List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QCheckBox, QMessageBox, QFileDialog, QMenu,
    QDialog, QTextEdit,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor, QFont, QIcon

from app.config.i18n import tr
from app.widgets.request_editor import CenteredCheckBox


class PreProcessorWidget(QWidget):
    """接口前置处理设置组件"""

    config_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ─── 顶部工具栏 ───
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.add_btn = QPushButton(tr("pre_add_rule", "+ 添加前置规则"))
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                font-weight: bold;
                padding: 4px 10px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        self.add_btn.clicked.connect(self._on_add_rule)
        toolbar.addWidget(self.add_btn)

        # 内置函数快速模板
        self.func_menu_btn = QPushButton(tr("pre_builtin_funcs", "⚡ 常用内置函数 ▼"))
        self.func_menu = QMenu(self)
        self._init_func_menu()
        self.func_menu_btn.setMenu(self.func_menu)
        toolbar.addWidget(self.func_menu_btn)

        # 本地文件读取
        self.add_file_btn = QPushButton(tr("pre_read_file", "📁 从文件读取参数..."))
        self.add_file_btn.clicked.connect(self._on_add_file_rule)
        toolbar.addWidget(self.add_file_btn)

        # 文件格式样例说明
        self.help_btn = QPushButton(tr("pre_file_help", "💡 文件格式案例与说明"))
        self.help_btn.clicked.connect(self._on_show_file_help)
        toolbar.addWidget(self.help_btn)

        toolbar.addStretch()

        self.clear_btn = QPushButton(tr("pre_clear_rules", "清空规则"))
        self.clear_btn.clicked.connect(self._on_clear_rules)
        toolbar.addWidget(self.clear_btn)

        layout.addLayout(toolbar)

        # ─── 规则表格 ───
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            tr("pre_col_enabled", "启用"),
            tr("pre_col_source", "参数来源"),
            tr("pre_col_expr", "配置/表达式/文件路径"),
            tr("pre_col_file_key", "文件提取Key"),
            tr("pre_col_target", "设置目标"),
            tr("pre_col_target_name", "目标名称"),
            tr("pre_col_action", "操作"),
        ])
        h0 = self.table.horizontalHeaderItem(0)
        if h0:
            h0.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 110)
        self.table.setColumnWidth(5, 120)

        layout.addWidget(self.table)

    def _init_func_menu(self):
        funcs = [
            ("UUID 唯一标识 (UUID())", "UUID()", "header", "X-Request-Id"),
            ("当前毫秒时间戳 (Timestamp(ms))", "Timestamp(ms)", "header", "X-Timestamp"),
            ("当前秒时间戳 (Timestamp(s))", "Timestamp(s)", "header", "X-Timestamp"),
            ("随机4位数字 (RandomInt(1000, 9999))", "RandomInt(1000, 9999)", "param", "code"),
            ("随机6位数字 (RandomInt(100000, 999999))", "RandomInt(100000, 999999)", "param", "verifyCode"),
            ("随机16位字符串 (RandomString(16))", "RandomString(16)", "header", "X-Nonce"),
            ("MD5 计算模板 (MD5(text))", "MD5({{token}})", "header", "X-Sign"),
            ("SHA256 计算模板 (SHA256(text))", "SHA256({{token}})", "header", "X-Sign"),
            ("Base64 编码 (Base64Encode(text))", "Base64Encode({{token}})", "header", "Authorization"),
            ("UUID 到请求体 (UUID())", "UUID()", "body", "traceId"),
            ("时间戳到请求体 (Timestamp(ms))", "Timestamp(ms)", "body", "timestamp"),
            ("随机4位验证码到请求体 (RandomInt)", "RandomInt(1000, 9999)", "body", "verifyCode"),
        ]
        for title, expr, target_type, target_name in funcs:
            act = self.func_menu.addAction(title)
            act.triggered.connect(lambda checked, e=expr, tt=target_type, tn=target_name: self._add_func_rule(e, tt, tn))

    def _add_func_rule(self, expr: str, target_type: str, target_name: str):
        self._insert_row(
            enabled=True,
            source_type="custom",
            expression=expr,
            file_key="",
            target_type=target_type,
            target_name=target_name,
        )

    def _on_add_file_rule(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self, "选择参数文件", "", "数据文件 (*.json *.env *.txt *.properties);;所有文件 (*.*)"
        )
        if not fpath:
            return
        ext = os.path.splitext(fpath)[1].lower()
        default_key = "token" if ext in (".json", ".env", ".properties") else ""
        self._insert_row(
            enabled=True,
            source_type="file",
            expression=fpath,
            file_key=default_key,
            target_type="header",
            target_name="Authorization",
        )

    def _on_show_file_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("前置处理 - 文件格式与使用案例")
        dlg.resize(600, 480)
        vbox = QVBoxLayout(dlg)

        info = QTextEdit()
        info.setReadOnly(True)
        info.setFont(QFont("Consolas", 10))
        info.setHtml("""
            <h3>📁 支持的本地文件格式与使用案例</h3>
            <p>前置处理支持从本地文本文件中动态提取参数并设置到请求头、URL 查询参数或环境变量中：</p>
            
            <h4>1. JSON 格式文件 (.json)</h4>
            <pre style="background: #f3f4f6; padding: 8px; border-radius: 4px;">
{
  "auth": {
    "token": "eyJhbGciOi...",
    "expire": 3600
  },
  "appId": "wx_123456"
}
            </pre>
            <p><b>提取方式：</b> 文件提取 Key 输入 <code>auth.token</code>（支持点号提取多层嵌套字段）或 <code>appId</code>。</p>

            <h4>2. 键值对配置文件 (.env / .properties / .txt)</h4>
            <pre style="background: #f3f4f6; padding: 8px; border-radius: 4px;">
# 配置文件案例
TOKEN=eyJhbGciOi...
API_KEY=my_secret_key_889
BASE_URL=https://api.example.com
            </pre>
            <p><b>提取方式：</b> 文件提取 Key 输入键名，例如 <code>TOKEN</code> 或 <code>API_KEY</code>，引擎将自动提取等号右侧的值。</p>

            <h4>3. 纯文本文件 (.txt)</h4>
            <p><b>提取方式：</b> 若“文件提取 Key”留空，引擎将直接读取文件的全部文本内容作为目标参数值。</p>
        """)
        vbox.addWidget(info)
        btn = QPushButton("我知道了")
        btn.clicked.connect(dlg.accept)
        vbox.addWidget(btn)
        dlg.exec()

    def _on_add_rule(self):
        self._insert_row(
            enabled=True,
            source_type="env",
            expression="{{token}}",
            file_key="",
            target_type="header",
            target_name="Authorization",
        )

    def _insert_row(self, enabled: bool, source_type: str, expression: str, file_key: str, target_type: str, target_name: str):
        row = self.table.rowCount()
        self.table.insertRow(row)

        # 0. 启用（居中放置）
        chk = CenteredCheckBox(enabled)
        chk.stateChanged.connect(lambda: self.config_changed.emit())
        self.table.setCellWidget(row, 0, chk)

        # 1. 来源类型
        src_combo = QComboBox()
        src_combo.addItem(tr("pre_src_env", "环境变量/表达式"), "env")
        src_combo.addItem(tr("pre_src_file", "本地文件"), "file")
        src_combo.addItem(tr("pre_src_custom", "自定义函数/计算"), "custom")
        idx = src_combo.findData(source_type)
        if idx >= 0:
            src_combo.setCurrentIndex(idx)
        src_combo.currentIndexChanged.connect(lambda: self.config_changed.emit())
        self.table.setCellWidget(row, 1, src_combo)

        # 2. 表达式 / 路径
        expr_edit = QLineEdit(expression)
        expr_edit.setPlaceholderText(tr("pre_col_expr_placeholder", "例如 {{token}} 或 UUID() 或 C:/data/token.json"))
        expr_edit.textChanged.connect(lambda: self.config_changed.emit())
        self.table.setCellWidget(row, 2, expr_edit)

        # 3. 文件提取 Key
        key_edit = QLineEdit(file_key)
        key_edit.setPlaceholderText(tr("pre_col_file_key_placeholder", "JSON键/环境变量键"))
        key_edit.textChanged.connect(lambda: self.config_changed.emit())
        self.table.setCellWidget(row, 3, key_edit)

        # 4. 设置目标
        tgt_combo = QComboBox()
        tgt_combo.addItem(tr("pre_tgt_header", "请求头 (Header)"), "header")
        tgt_combo.addItem(tr("pre_tgt_param", "查询参数 (Param)"), "param")
        tgt_combo.addItem(tr("pre_tgt_body", "请求体 (Body)"), "body")
        tgt_combo.addItem(tr("pre_tgt_variable", "环境变量 (Variable)"), "variable")
        tidx = tgt_combo.findData(target_type)
        if tidx >= 0:
            tgt_combo.setCurrentIndex(tidx)
        tgt_combo.currentIndexChanged.connect(lambda: self.config_changed.emit())
        self.table.setCellWidget(row, 4, tgt_combo)

        # 5. 目标名称
        name_edit = QLineEdit(target_name)
        name_edit.setPlaceholderText(tr("pre_col_name_placeholder", "如 Authorization / sign / userId / data.token"))
        name_edit.textChanged.connect(lambda: self.config_changed.emit())
        self.table.setCellWidget(row, 5, name_edit)

        # 6. 删除按钮
        del_btn = QPushButton(tr("btn_delete", "删除"))
        del_btn.setStyleSheet("color: #ef4444; font-size: 11px;")
        del_btn.clicked.connect(lambda checked, r=row: self._delete_row_by_widget(del_btn))
        self.table.setCellWidget(row, 6, del_btn)

        self.config_changed.emit()

    def retranslate_ui(self):
        """动态刷新界面语言"""
        self.add_btn.setText(tr("pre_add_rule", "+ 添加前置规则"))
        self.func_menu_btn.setText(tr("pre_builtin_funcs", "⚡ 常用内置函数 ▼"))
        self.add_file_btn.setText(tr("pre_read_file", "📁 从文件读取参数..."))
        self.help_btn.setText(tr("pre_file_help", "💡 文件格式案例与说明"))
        self.clear_btn.setText(tr("pre_clear_rules", "清空规则"))
        self.table.setHorizontalHeaderLabels([
            tr("pre_col_enabled", "启用"),
            tr("pre_col_source", "参数来源"),
            tr("pre_col_expr", "配置/表达式/文件路径"),
            tr("pre_col_file_key", "文件提取Key"),
            tr("pre_col_target", "设置目标"),
            tr("pre_col_target_name", "目标名称"),
            tr("pre_col_action", "操作"),
        ])
        h0 = self.table.horizontalHeaderItem(0)
        if h0:
            h0.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        for r in range(self.table.rowCount()):
            del_btn = self.table.cellWidget(r, 6)
            if isinstance(del_btn, QPushButton):
                del_btn.setText(tr("btn_delete", "删除"))

    def _delete_row_by_widget(self, btn: QPushButton):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 6) == btn:
                self.table.removeRow(r)
                self.config_changed.emit()
                break

    def _on_clear_rules(self):
        if self.table.rowCount() == 0:
            return
        self.table.setRowCount(0)
        self.config_changed.emit()

    def get_config(self) -> Dict[str, Any]:
        """获取序列化的前置处理规则字典"""
        rules = []
        for r in range(self.table.rowCount()):
            chk: QCheckBox = self.table.cellWidget(r, 0)
            src_combo: QComboBox = self.table.cellWidget(r, 1)
            expr_edit: QLineEdit = self.table.cellWidget(r, 2)
            key_edit: QLineEdit = self.table.cellWidget(r, 3)
            tgt_combo: QComboBox = self.table.cellWidget(r, 4)
            name_edit: QLineEdit = self.table.cellWidget(r, 5)

            rules.append({
                "enabled": chk.isChecked() if chk else True,
                "source_type": src_combo.currentData() if src_combo else "env",
                "expression": expr_edit.text().strip() if expr_edit else "",
                "file_path": expr_edit.text().strip() if expr_edit else "",
                "file_key": key_edit.text().strip() if key_edit else "",
                "file_format": "auto",
                "target_type": tgt_combo.currentData() if tgt_combo else "header",
                "target_name": name_edit.text().strip() if name_edit else "",
            })
        return {"rules": rules}

    def set_config(self, cfg: Any):
        """加载配置"""
        self.table.setRowCount(0)
        if not isinstance(cfg, dict):
            return
        rules = cfg.get("rules", [])
        for r in rules:
            if not isinstance(r, dict):
                continue
            self._insert_row(
                enabled=r.get("enabled", True),
                source_type=r.get("source_type", "env"),
                expression=r.get("expression") or r.get("file_path", ""),
                file_key=r.get("file_key", ""),
                target_type=r.get("target_type", "header"),
                target_name=r.get("target_name", ""),
            )


class PostProcessorWidget(QWidget):
    """接口后置处理设置组件"""

    config_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ─── 顶部工具栏 ───
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.add_btn = QPushButton(tr("post_add_rule", "+ 添加后置提取规则"))
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                font-weight: bold;
                padding: 4px 10px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        self.add_btn.clicked.connect(self._on_add_rule)
        toolbar.addWidget(self.add_btn)

        # 常用模板
        self.template_btn = QPushButton(tr("post_builtin_templates", "⚡ 常用提取模板 ▼"))
        self.template_menu = QMenu(self)
        self._init_template_menu()
        self.template_btn.setMenu(self.template_menu)
        toolbar.addWidget(self.template_btn)

        # 语法说明
        self.help_btn = QPushButton(tr("post_help", "💡 提取规则说明"))
        self.help_btn.clicked.connect(self._on_show_help)
        toolbar.addWidget(self.help_btn)

        toolbar.addStretch()

        self.clear_btn = QPushButton(tr("post_clear_rules", "清空规则"))
        self.clear_btn.clicked.connect(self._on_clear_rules)
        toolbar.addWidget(self.clear_btn)

        layout.addLayout(toolbar)

        # ─── 规则表格 ───
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            tr("post_col_enabled", "启用"),
            tr("post_col_source", "提取来源"),
            tr("post_col_expr", "提取路径/表达式 (支持 ${...} 占位)"),
            tr("post_col_target", "保存目标"),
            tr("post_col_target_key", "目标键名 (Key)"),
            tr("post_col_action", "操作"),
        ])
        h0 = self.table.horizontalHeaderItem(0)
        if h0:
            h0.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(3, 140)
        self.table.setColumnWidth(4, 140)

        layout.addWidget(self.table)

    def _init_template_menu(self):
        templates = [
            ("从响应体提取 token 组装 Bearer Token (Bearer ${data.token})", "body_jsonpath", "Bearer ${data.token}", "global_headers", "Authorization"),
            ("从响应体提取返回体组装 Bearer Token (Bearer ${data.body})", "body_jsonpath", "Bearer ${data.body}", "global_headers", "Authorization"),
            ("从响应头提取 Authorization 到全局请求头", "header", "Authorization", "global_headers", "Authorization"),
            ("从响应体提取 token 到全局请求头", "body_jsonpath", "data.token", "global_headers", "Authorization"),
            ("从响应体提取 token 到环境变量", "body_jsonpath", "data.token", "environment", "token"),
            ("从响应头提取 Set-Cookie 到 Cookie 库", "header", "Set-Cookie", "cookies", "session"),
            ("从响应 Cookie 提取 JSESSIONID", "cookie", "JSESSIONID", "cookies", "JSESSIONID"),
            ("从响应体提取第一项 ID 到环境变量", "body_jsonpath", "data.list[0].id", "environment", "first_id"),
            ("从响应体通过正则提取 Token", "body_regex", r'token="([^"]+)"', "global_headers", "Authorization"),
        ]
        for title, extract_from, expr, dest, key in templates:
            act = self.template_menu.addAction(title)
            act.triggered.connect(lambda checked, ef=extract_from, ep=expr, td=dest, tk=key: self._insert_row(True, ef, ep, td, tk))

    def _on_show_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("后置处理 - 参数提取说明")
        dlg.resize(640, 520)
        vbox = QVBoxLayout(dlg)

        info = QTextEdit()
        info.setReadOnly(True)
        info.setFont(QFont("Consolas", 10))
        info.setHtml("""
            <h3>🔍 后置处理提取与目标写入说明</h3>
            <p>后置处理在请求得到响应结果后自动执行，支持将参数自动写入<b>全局请求头</b>、<b>Cookie 库</b>或<b>环境变量</b>中：</p>
            
            <h4>1. 提取来源 (Extract From)</h4>
            <ul>
                <li><b>响应头 (Header)：</b>输入 Header 键名，如 <code>Set-Cookie</code>、<code>Authorization</code>。</li>
                <li><b>响应 Cookie：</b>输入 Cookie 名，如 <code>token</code>、<code>JSESSIONID</code>。</li>
                <li><b>响应体 JSONPath：</b>例如 <code>data.token</code>、<code>user.id</code>、<code>items[0].name</code>。</li>
                <li><b>响应体 正则 (Regex)：</b>支持正则表达式提取，如 <code>token=([^&]+)</code> 或 <code>"access_token":"(.*?)"</code>（自动捕获括号内的组）。</li>
                <li><b>响应体 纯文本：</b>将响应体全文直接提取。</li>
            </ul>

            <h4>2. 自定义文本包装与占位符提取 (${...})</h4>
            <p>支持用户在表达式中任意添加自定义文本并使用 <code>${...}</code> 占位符进行提取拼装：</p>
            <ul>
                <li><b>提取 Bearer Token：</b>表达式输入 <code>Bearer ${data.token}</code> 或 <code>Bearer ${data.body}</code>，引擎提取出 Token 后自动拼装为完整的 <code>Bearer &lt;token&gt;</code> 写入请求头！</li>
                <li><b>整段返回体：</b>若返回体为纯字符串或需直接带前缀，直接输入 <code>Bearer ${data.body}</code> 或 <code>Bearer ${body}</code> 即可！</li>
                <li><b>自定义包装：</b>支持如 <code>Token ${id}_${user}</code> 任意拼接组合。</li>
            </ul>

            <h4>3. 保存目标 (Target Destination)</h4>
            <ul>
                <li><b>全局请求头 (Global Headers)：</b>自动添加到设置面板的全局请求头中，后续所有请求（包括压测和嗅探）都会自动携带该 Header！</li>
                <li><b>Cookie 库 (Cookie Storage)：</b>自动写入系统全局 Cookie 库，并在对应域名下自动生效。</li>
                <li><b>环境变量 (Environment)：</b>存入当前运行环境变量中，可在后续接口的 URL、Params、Body 中使用 <code>{{var}}</code> 或 <code>${var}</code> 占位符引用。</li>
            </ul>
        """)
        vbox.addWidget(info)
        btn = QPushButton(tr("dialog_confirm", "我知道了"))
        btn.clicked.connect(dlg.accept)
        vbox.addWidget(btn)
        dlg.exec()

    def _on_add_rule(self):
        self._insert_row(
            enabled=True,
            extract_from="body_jsonpath",
            expression="Bearer ${data.token}",
            target_dest="global_headers",
            target_key="Authorization",
        )

    def _insert_row(self, enabled: bool, extract_from: str, expression: str, target_dest: str, target_key: str):
        row = self.table.rowCount()
        self.table.insertRow(row)

        # 0. 启用（居中放置）
        chk = CenteredCheckBox(enabled)
        chk.stateChanged.connect(lambda: self.config_changed.emit())
        self.table.setCellWidget(row, 0, chk)

        # 1. 提取来源
        src_combo = QComboBox()
        src_combo.addItem(tr("post_src_header", "响应头 (Header)"), "header")
        src_combo.addItem(tr("post_src_cookie", "响应 Cookie"), "cookie")
        src_combo.addItem(tr("post_src_body_jsonpath", "响应体 JSONPath"), "body_jsonpath")
        src_combo.addItem(tr("post_src_body_regex", "响应体 正则 (Regex)"), "body_regex")
        src_combo.addItem(tr("post_src_body_text", "响应体 纯文本"), "body_text")
        idx = src_combo.findData(extract_from)
        if idx >= 0:
            src_combo.setCurrentIndex(idx)
        src_combo.currentIndexChanged.connect(lambda: self.config_changed.emit())
        self.table.setCellWidget(row, 1, src_combo)

        # 2. 提取路径 / 表达式 (支持 ${...} 占位符)
        expr_edit = QLineEdit(expression)
        expr_edit.setPlaceholderText(tr("post_placeholder_expression", "如 data.token 或 Bearer ${data.token} 或 Bearer ${data.body}"))
        expr_edit.textChanged.connect(lambda: self.config_changed.emit())
        self.table.setCellWidget(row, 2, expr_edit)

        # 3. 保存目标
        dest_combo = QComboBox()
        dest_combo.addItem(tr("post_tgt_global_headers", "全局请求头"), "global_headers")
        dest_combo.addItem(tr("post_tgt_cookies", "Cookie 库"), "cookies")
        dest_combo.addItem(tr("post_tgt_environment", "环境变量"), "environment")
        didx = dest_combo.findData(target_dest)
        if didx >= 0:
            dest_combo.setCurrentIndex(didx)
        dest_combo.currentIndexChanged.connect(lambda: self.config_changed.emit())
        self.table.setCellWidget(row, 3, dest_combo)

        # 4. 目标键名
        key_edit = QLineEdit(target_key)
        key_edit.setPlaceholderText(tr("post_placeholder_key", "如 Authorization / token"))
        key_edit.textChanged.connect(lambda: self.config_changed.emit())
        self.table.setCellWidget(row, 4, key_edit)

        # 5. 删除按钮
        del_btn = QPushButton(tr("btn_delete", "删除"))
        del_btn.setStyleSheet("color: #ef4444; font-size: 11px;")
        del_btn.clicked.connect(lambda checked, r=row: self._delete_row_by_widget(del_btn))
        self.table.setCellWidget(row, 5, del_btn)

        self.config_changed.emit()

    def retranslate_ui(self):
        """动态刷新界面语言"""
        self.add_btn.setText(tr("post_add_rule", "+ 添加后置提取规则"))
        self.template_btn.setText(tr("post_builtin_templates", "⚡ 常用提取模板 ▼"))
        self.help_btn.setText(tr("post_help", "💡 提取规则说明"))
        self.clear_btn.setText(tr("post_clear_rules", "清空规则"))
        self.table.setHorizontalHeaderLabels([
            tr("post_col_enabled", "启用"),
            tr("post_col_source", "提取来源"),
            tr("post_col_expr", "提取路径/表达式 (支持 ${...} 占位)"),
            tr("post_col_target", "保存目标"),
            tr("post_col_target_key", "目标键名 (Key)"),
            tr("post_col_action", "操作"),
        ])
        h0 = self.table.horizontalHeaderItem(0)
        if h0:
            h0.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        for r in range(self.table.rowCount()):
            del_btn = self.table.cellWidget(r, 5)
            if isinstance(del_btn, QPushButton):
                del_btn.setText(tr("btn_delete", "删除"))

    def _delete_row_by_widget(self, btn: QPushButton):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 5) == btn:
                self.table.removeRow(r)
                self.config_changed.emit()
                break

    def _on_clear_rules(self):
        if self.table.rowCount() == 0:
            return
        self.table.setRowCount(0)
        self.config_changed.emit()

    def get_config(self) -> Dict[str, Any]:
        """获取序列化的后置处理规则字典"""
        rules = []
        for r in range(self.table.rowCount()):
            chk: QCheckBox = self.table.cellWidget(r, 0)
            src_combo: QComboBox = self.table.cellWidget(r, 1)
            expr_edit: QLineEdit = self.table.cellWidget(r, 2)
            dest_combo: QComboBox = self.table.cellWidget(r, 3)
            key_edit: QLineEdit = self.table.cellWidget(r, 4)

            rules.append({
                "enabled": chk.isChecked() if chk else True,
                "extract_from": src_combo.currentData() if src_combo else "body_jsonpath",
                "expression": expr_edit.text().strip() if expr_edit else "",
                "target_destination": dest_combo.currentData() if dest_combo else "global_headers",
                "target_key": key_edit.text().strip() if key_edit else "",
            })
        return {"rules": rules}

    def set_config(self, cfg: Any):
        """加载配置"""
        self.table.setRowCount(0)
        if not isinstance(cfg, dict):
            return
        rules = cfg.get("rules", [])
        for r in rules:
            if not isinstance(r, dict):
                continue
            self._insert_row(
                enabled=r.get("enabled", True),
                extract_from=r.get("extract_from", "body_jsonpath"),
                expression=r.get("expression", ""),
                target_dest=r.get("target_destination", "global_headers"),
                target_key=r.get("target_key", ""),
            )
