import json
from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QDialog,
    QTreeWidget, QTreeWidgetItem, QLineEdit, QLabel, QFormLayout,
    QCheckBox, QSpinBox, QDateTimeEdit, QMessageBox,
)
from PyQt6.QtCore import Qt, QDateTime, QObject, pyqtSignal
from PyQt6.QtGui import QIcon


class GlobalCookieStorage(QObject):
    """全局 Cookie 域共享池 - 按照 RFC 6265 域名分发规则在所有 Tab 间共享 Cookie"""

    cookies_changed = pyqtSignal()
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.cookies = {}  # {domain: {path: [cookies]}}
        self._load()

    def _get_storage_file(self) -> Path:
        from app.config.settings import get_data_dir
        return get_data_dir() / "cookies.json"

    def _load(self):
        file_path = self._get_storage_file()
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.cookies = json.load(f)
            except Exception:
                self.cookies = {}

    def _save(self):
        file_path = self._get_storage_file()
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.cookies, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def add_cookie(self, cookie: dict):
        domain = (cookie.get('domain') or 'localhost').strip().lower()
        path = (cookie.get('path') or '/').strip()
        if domain not in self.cookies:
            self.cookies[domain] = {}
        if path not in self.cookies[domain]:
            self.cookies[domain][path] = []
        name = cookie.get('name', '')
        idx = next((i for i, c in enumerate(self.cookies[domain][path]) if c.get('name') == name), None)
        if idx is not None:
            self.cookies[domain][path][idx] = cookie
        else:
            self.cookies[domain][path].append(cookie)
        self._save()
        self.cookies_changed.emit()

    def remove_cookie(self, domain: str, path: str, name: str):
        domain = domain.strip().lower()
        if domain in self.cookies and path in self.cookies[domain]:
            self.cookies[domain][path] = [c for c in self.cookies[domain][path] if c.get('name') != name]
            if not self.cookies[domain][path]:
                del self.cookies[domain][path]
            if not self.cookies[domain]:
                del self.cookies[domain]
            self._save()
            self.cookies_changed.emit()

    def merge_cookies(self, cookies: list, default_domain: str = ""):
        if not cookies:
            return
        changed = False
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get('name') or cookie.get('key') or ''
            if not name:
                continue
            domain = (cookie.get('domain') or default_domain or 'localhost').strip().lower()
            path = (cookie.get('path') or '/').strip()
            val = cookie.get('value', '')
            entry = {
                'name': name,
                'value': val,
                'domain': domain,
                'path': path,
                'expires': cookie.get('expires', ''),
                'secure': cookie.get('secure', False),
                'httponly': cookie.get('httponly', False),
                'samesite': cookie.get('samesite', ''),
            }
            if domain not in self.cookies:
                self.cookies[domain] = {}
            if path not in self.cookies[domain]:
                self.cookies[domain][path] = []
            idx = next((i for i, c in enumerate(self.cookies[domain][path]) if c.get('name') == name), None)
            if idx is not None:
                self.cookies[domain][path][idx] = entry
            else:
                self.cookies[domain][path].append(entry)
            changed = True
        if changed:
            self._save()
            self.cookies_changed.emit()

    def get_all_cookies(self) -> list:
        all_cookies = []
        for domain, paths in self.cookies.items():
            for path, cookies in paths.items():
                all_cookies.extend(cookies)
        return all_cookies

    def set_cookies(self, cookies: list):
        self.cookies = {}
        for cookie in cookies:
            domain = (cookie.get('domain') or 'localhost').strip().lower()
            path = (cookie.get('path') or '/').strip()
            if domain not in self.cookies:
                self.cookies[domain] = {}
            if path not in self.cookies[domain]:
                self.cookies[domain][path] = []
            self.cookies[domain][path].append(cookie)
        self._save()
        self.cookies_changed.emit()

    def get_cookies_for_url(self, url: str) -> list[dict]:
        """根据 URL 的域名及路径获取匹配的所有有效 Cookie（遵循 RFC 6265）"""
        if not url:
            return []
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").strip().lower()
            req_path = parsed.path or "/"
        except Exception:
            return []
        
        if not host:
            return []

        matched = []
        for domain, paths in self.cookies.items():
            domain_clean = domain.strip().lower().lstrip('.')
            domain_matched = False
            if host == domain_clean or host == f"www.{domain_clean}":
                domain_matched = True
            elif host.endswith("." + domain_clean):
                domain_matched = True
            elif domain_clean in ("localhost", "127.0.0.1") and host in ("localhost", "127.0.0.1"):
                domain_matched = True
            
            if not domain_matched:
                continue

            for path, cookies in paths.items():
                if req_path.startswith(path) or path == "/":
                    matched.extend(cookies)
        return matched


class CookieEditorDialog(QDialog):
    """Cookie 编辑对话框"""
    
    def __init__(self, parent=None, cookie_data=None):
        super().__init__(parent)
        self.setWindowTitle("编辑 Cookie")
        self.setMinimumSize(500, 400)
        self.cookie_data = cookie_data or {}
        self._init_ui()
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        form_layout = QFormLayout()
        
        # Name
        self.name_input = QLineEdit()
        self.name_input.setText(self.cookie_data.get('name', ''))
        form_layout.addRow("名称:", self.name_input)
        
        # Value
        self.value_input = QLineEdit()
        self.value_input.setText(self.cookie_data.get('value', ''))
        form_layout.addRow("值:", self.value_input)
        
        # Domain
        self.domain_input = QLineEdit()
        self.domain_input.setText(self.cookie_data.get('domain', ''))
        form_layout.addRow("域名:", self.domain_input)
        
        # Path
        self.path_input = QLineEdit()
        self.path_input.setText(self.cookie_data.get('path', '/'))
        form_layout.addRow("路径:", self.path_input)
        
        # Expires
        expires_layout = QHBoxLayout()
        self.expires_check = QCheckBox("过期时间:")
        self.expires_check.setChecked(bool(self.cookie_data.get('expires')))
        self.expires_date = QDateTimeEdit()
        self.expires_date.setCalendarPopup(True)
        if self.cookie_data.get('expires'):
            self.expires_date.setDateTime(QDateTime.fromString(self.cookie_data['expires'], "yyyy-MM-dd hh:mm:ss"))
        else:
            self.expires_date.setDateTime(QDateTime.currentDateTime().addDays(7))
        self.expires_date.setEnabled(self.expires_check.isChecked())
        self.expires_check.toggled.connect(self.expires_date.setEnabled)
        expires_layout.addWidget(self.expires_check)
        expires_layout.addWidget(self.expires_date)
        form_layout.addRow("", expires_layout)
        
        # Secure
        self.secure_check = QCheckBox("Secure (仅 HTTPS)")
        self.secure_check.setChecked(self.cookie_data.get('secure', False))
        form_layout.addRow("", self.secure_check)
        
        # HttpOnly
        self.httponly_check = QCheckBox("HttpOnly (仅 HTTP)")
        self.httponly_check.setChecked(self.cookie_data.get('httponly', False))
        form_layout.addRow("", self.httponly_check)
        
        # SameSite
        self.samesite_combo = QLineEdit()
        self.samesite_combo.setText(self.cookie_data.get('samesite', ''))
        self.samesite_combo.setPlaceholderText("Strict, Lax, None")
        form_layout.addRow("SameSite:", self.samesite_combo)
        
        layout.addLayout(form_layout)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        
        layout.addLayout(btn_layout)
    
    def get_cookie_data(self) -> dict:
        """获取 Cookie 数据"""
        data = {
            'name': self.name_input.text().strip(),
            'value': self.value_input.text().strip(),
            'domain': self.domain_input.text().strip(),
            'path': self.path_input.text().strip() or '/',
            'secure': self.secure_check.isChecked(),
            'httponly': self.httponly_check.isChecked(),
            'samesite': self.samesite_combo.text().strip(),
        }
        
        if self.expires_check.isChecked():
            data['expires'] = self.expires_date.dateTime().toString("yyyy-MM-dd hh:mm:ss")
        
        return data


class CookieManager(QWidget):
    """Cookie 管理器 - 树状展示，接入全局 Cookie 共享池"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.storage = GlobalCookieStorage.get_instance()
        self.storage.cookies_changed.connect(self._refresh_tree)
        self._init_ui()
        self._refresh_tree()

    @property
    def cookies(self):
        return self.storage.cookies

    @cookies.setter
    def cookies(self, val):
        self.storage.cookies = val
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 工具栏
        toolbar = QHBoxLayout()
        
        self.add_btn = QPushButton("+ 添加 Cookie")
        self.add_btn.clicked.connect(self._on_add_cookie)
        toolbar.addWidget(self.add_btn)

        self.global_headers_btn = QPushButton("🌐 全局请求头")
        self.global_headers_btn.setToolTip("管理在所有请求中生效的全局请求头（单请求同名 Header 优先覆盖）")
        self.global_headers_btn.clicked.connect(self._on_open_global_headers)
        toolbar.addWidget(self.global_headers_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        # 树形视图
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称", "值", "域名", "路径", "过期时间"])
        self.tree.setColumnWidth(0, 120)
        self.tree.setColumnWidth(1, 150)
        self.tree.setColumnWidth(2, 150)
        self.tree.setColumnWidth(3, 80)
        self.tree.setColumnWidth(4, 150)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.tree.itemDoubleClicked.connect(self._on_edit_cookie)
        layout.addWidget(self.tree)
        
    def _on_add_cookie(self):
        """添加 Cookie"""
        dialog = CookieEditorDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            cookie = dialog.get_cookie_data()
            if not cookie['name']:
                QMessageBox.warning(self, "警告", "Cookie 名称不能为空")
                return
            self.storage.add_cookie(cookie)
    
    def _on_edit_cookie(self, item: QTreeWidgetItem, column: int):
        """编辑 Cookie"""
        if not item.parent():  # 点击的是 domain 或 path 节点
            return
        
        domain_item = item.parent().parent() or item.parent()
        path_item = item.parent()
        
        domain = domain_item.text(0)
        path = path_item.text(0)
        
        for cookie in self.storage.cookies.get(domain, {}).get(path, []):
            if cookie['name'] == item.text(0):
                dialog = CookieEditorDialog(self, cookie)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    new_cookie = dialog.get_cookie_data()
                    self.storage.add_cookie(new_cookie)
                break
    
    def _on_delete_cookie(self):
        """删除选中的 Cookie"""
        selected_items = self.tree.selectedItems()
        if not selected_items:
            return
        
        for item in selected_items:
            if not item.parent():
                continue
            
            domain_item = item.parent().parent() or item.parent()
            path_item = item.parent()
            
            domain = domain_item.text(0)
            path = path_item.text(0)
            name = item.text(0)
            self.storage.remove_cookie(domain, path, name)
    
    def _refresh_tree(self):
        """刷新树形视图"""
        self.tree.clear()
        
        sorted_domains = sorted(self.storage.cookies.keys())
        for domain in sorted_domains:
            domain_item = QTreeWidgetItem([domain, "", domain, "", ""])
            domain_item.setIcon(0, QIcon.fromTheme("folder"))
            
            paths = self.storage.cookies[domain]
            sorted_paths = sorted(paths.keys(), key=lambda p: (p != '/', p))
            
            for path in sorted_paths:
                path_item = QTreeWidgetItem(["", "", "", path, ""])
                path_item.setIcon(0, QIcon.fromTheme("folder-open"))
                
                cookies = paths[path]
                for cookie in cookies:
                    val_str = str(cookie.get('value', ''))
                    cookie_item = QTreeWidgetItem([
                        cookie.get('name', ''),
                        val_str[:30] + ('...' if len(val_str) > 30 else ''),
                        domain,
                        path,
                        cookie.get('expires', '')
                    ])
                    path_item.addChild(cookie_item)
                
                domain_item.addChild(path_item)
            
            self.tree.addTopLevelItem(domain_item)
        
        self.tree.expandAll()
    
    def get_all_cookies(self) -> list:
        return self.storage.get_all_cookies()
    
    def set_cookies(self, cookies: list):
        self.storage.set_cookies(cookies)

    def merge_cookies(self, cookies: list, default_domain: str = ""):
        self.storage.merge_cookies(cookies, default_domain=default_domain)

    def _on_open_global_headers(self):
        """打开全局请求头（优先直接切换到编辑器全局请求头 Tab）"""
        parent = self.parent()
        while parent:
            if hasattr(parent, 'switch_to_global_headers_tab'):
                parent.switch_to_global_headers_tab()
                return
            parent = parent.parent()
        from app.widgets.global_headers_dialog import GlobalHeadersDialog
        dialog = GlobalHeadersDialog(self)
        dialog.exec()

    def apply_theme(self, t):
        """应用主题"""
        if hasattr(self, 'add_btn'):
            self.add_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t.bg_input};
                    color: {t.text_primary};
                    border: 1px solid {t.border};
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: {t.bg_hover};
                }}
            """)
        if hasattr(self, 'global_headers_btn'):
            self.global_headers_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t.bg_input};
                    color: {t.text_primary};
                    border: 1px solid {t.border};
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: {t.bg_hover};
                }}
            """)
        if hasattr(self, 'tree'):
            self.tree.setStyleSheet(f"""
                QTreeWidget {{
                    background-color: {t.bg_input};
                    color: {t.text_primary};
                    border: 1px solid {t.border_light};
                    border-radius: 4px;
                }}
                QTreeWidget::item:selected {{
                    background-color: {t.bg_selected};
                    color: {t.text_primary};
                }}
            """)
