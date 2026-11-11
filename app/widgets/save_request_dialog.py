"""保存请求对话框 - 支持多级集合树导航、任意层级子文件夹选择、搜索过滤与就地新建子文件夹"""

from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QInputDialog,
    QMessageBox, QFrame,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QColor

from app.core.db import Database
from app.core.models import Collection
from app.config.themes import ThemeManager
from app.config.i18n import tr


class SaveRequestDialog(QDialog):
    """保存请求对话框（支持多级文件夹层级树选择）"""

    def __init__(self, parent=None, current_collection_id: str = "", default_name: str = "", current_name: str = "", default_collection_id: str = ""):
        super().__init__(parent)
        self.db = Database()
        target_cid = current_collection_id or default_collection_id or ""
        target_name = default_name or current_name or ""
        self.selected_collection_id: Optional[str] = target_cid or None
        self.selected_collection_name: str = ""
        self.request_name: str = target_name

        self.setWindowTitle(tr("save_dialog_title", "保存请求"))
        self.setMinimumSize(480, 520)
        self.resize(520, 580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._init_ui()
        self._load_tree()

    def _init_ui(self):
        t = ThemeManager.current()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # 1. 请求名称输入
        name_layout = QVBoxLayout()
        name_layout.setSpacing(4)
        lbl_name = QLabel(tr("save_request_name", "请求名称:"))
        lbl_name.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.name_edit = QLineEdit(self.request_name)
        self.name_edit.setPlaceholderText(tr("save_name_placeholder", "请输入请求名称，如：用户登录接口"))
        self.name_edit.setFixedHeight(32)
        self.name_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #d1d5db;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 13px;
                background-color: white;
            }
            QLineEdit:focus {
                border: 1.5px solid #3b82f6;
            }
        """)
        name_layout.addWidget(lbl_name)
        name_layout.addWidget(self.name_edit)
        layout.addLayout(name_layout)

        # 2. 文件夹选择标题与搜索过滤
        tree_header = QHBoxLayout()
        tree_header.setSpacing(8)
        lbl_folder = QLabel(tr("save_select_folder", "选择保存到的文件夹（支持任意多级子文件夹）:"))
        lbl_folder.setStyleSheet("font-weight: bold; font-size: 13px;")
        tree_header.addWidget(lbl_folder)
        tree_header.addStretch()

        # 搜索过滤框
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("save_search_placeholder", "🔍 快速搜索文件夹..."))
        self.search_edit.setFixedWidth(160)
        self.search_edit.setFixedHeight(26)
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        self.search_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 12px;
            }
        """)
        tree_header.addWidget(self.search_edit)
        layout.addLayout(tree_header)

        # 3. 多级集合树
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                background-color: #fafafa;
                padding: 4px;
                font-size: 13px;
            }
            QTreeWidget::item {
                padding: 5px 8px;
                border-radius: 4px;
                margin: 1px 2px;
            }
            QTreeWidget::item:hover {
                background-color: #f3f4f6;
            }
            QTreeWidget::item:selected {
                background-color: #e0e7ff;
                color: #3730a3;
                font-weight: 500;
            }
        """)
        self.tree.itemSelectionChanged.connect(self._on_item_selected)
        self.tree.itemDoubleClicked.connect(lambda item, col: self._on_accept())
        layout.addWidget(self.tree, 1)

        # 4. 树底部操作：路径提示 + 新建子文件夹按钮
        sub_bar = QHBoxLayout()
        self.path_label = QLabel(f"{tr('save_selected_folder', '已选文件夹:')} {tr('save_select_prompt', '(请从上方树中点击选择)')}")
        self.path_label.setStyleSheet("color: #4b5563; font-size: 12px;")
        sub_bar.addWidget(self.path_label, 1)

        self.btn_new_sub = QPushButton(tr("save_new_subfolder", "📁 新建子文件夹"))
        self.btn_new_sub.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new_sub.setFixedHeight(28)
        self.btn_new_sub.setStyleSheet("""
            QPushButton {
                background-color: #f3f4f6;
                color: #374151;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 2px 10px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #e5e7eb;
            }
        """)
        self.btn_new_sub.clicked.connect(self._on_new_sub_folder)
        sub_bar.addWidget(self.btn_new_sub)

        self.btn_new_root = QPushButton(tr("save_new_root_folder", "➕ 新建顶级集合"))
        self.btn_new_root.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new_root.setFixedHeight(28)
        self.btn_new_root.setStyleSheet("""
            QPushButton {
                background-color: #f3f4f6;
                color: #374151;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 2px 10px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #e5e7eb;
            }
        """)
        self.btn_new_root.clicked.connect(self._on_new_root_collection)
        sub_bar.addWidget(self.btn_new_root)

        layout.addLayout(sub_bar)

        # 5. 底部按钮条（保存 / 取消）
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.btn_cancel = QPushButton(tr("save_btn_cancel", "取消"))
        self.btn_cancel.setFixedSize(80, 32)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #f3f4f6;
                color: #374151;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #e5e7eb;
            }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_save = QPushButton(tr("save_btn_save", "保存"))
        self.btn_save.setFixedSize(80, 32)
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                font-weight: 500;
                border: none;
                border-radius: 5px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        self.btn_save.clicked.connect(self._on_accept)
        btn_layout.addWidget(self.btn_save)

        layout.addLayout(btn_layout)

    def _load_tree(self, select_id: Optional[str] = None):
        """递归加载多级集合树"""
        target_select = select_id or self.selected_collection_id
        self.tree.clear()

        # 加载所有顶级集合
        root_colls = self.db.get_collections(parent_id=None)
        item_to_select = None

        for coll in root_colls:
            item = self._add_node_recursive(None, coll, target_select)
            if item:
                item_to_select = item

        self.tree.expandAll()
        if item_to_select:
            self.tree.setCurrentItem(item_to_select)
            self.tree.scrollToItem(item_to_select)

    def _add_node_recursive(self, parent_item: Optional[QTreeWidgetItem], collection: Collection,
                            select_id: Optional[str]) -> Optional[QTreeWidgetItem]:
        """递归添加节点"""
        if parent_item is None:
            item = QTreeWidgetItem(self.tree)
        else:
            item = QTreeWidgetItem(parent_item)

        item.setText(0, f"📁 {collection.name}")
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "id": collection.id,
            "name": collection.name,
            "parent_id": collection.parent_id
        })

        found_item = None
        if select_id and collection.id == select_id:
            found_item = item

        # 递归子文件夹
        children = self.db.get_collections(parent_id=collection.id)
        for child in children:
            res = self._add_node_recursive(item, child, select_id)
            if res:
                found_item = res

        return found_item

    def _on_item_selected(self):
        """选中项变化更新路径显示"""
        item = self.tree.currentItem()
        if not item:
            self.selected_collection_id = None
            self.selected_collection_name = ""
            self.path_label.setText("已选文件夹: (未选择)")
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        self.selected_collection_id = data["id"]
        self.selected_collection_name = data["name"]

        # 构建面包屑路径（从根到当前）
        parts = []
        curr = item
        while curr:
            c_data = curr.data(0, Qt.ItemDataRole.UserRole)
            if c_data:
                parts.insert(0, c_data["name"])
            curr = curr.parent()

        full_path = " / ".join(parts)
        self.path_label.setText(f"已选文件夹: 📂 <b style='color:#1d4ed8;'>{full_path}</b>")

    def _on_search_text_changed(self, text: str):
        """搜索过滤节点"""
        kw = text.strip().lower()

        def _filter(item: QTreeWidgetItem) -> bool:
            name = item.text(0).lower()
            matches = kw in name if kw else True
            child_matches = False
            for i in range(item.childCount()):
                child_matches = _filter(item.child(i)) or child_matches
            visible = matches or child_matches
            item.setHidden(not visible)
            if visible and kw:
                item.setExpanded(True)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            _filter(self.tree.topLevelItem(i))

    def _on_new_sub_folder(self):
        """在当前选中的文件夹下新建子文件夹"""
        item = self.tree.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先在上方列表中选中一个作为父级的文件夹。")
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        parent_id = data["id"]
        parent_name = data["name"]

        name, ok = QInputDialog.getText(self, "新建子文件夹", f"在【{parent_name}】下新建子文件夹名称:")
        if ok and name.strip():
            sub = Collection(name=name.strip(), parent_id=parent_id)
            self.db.create_collection(sub)
            self._load_tree(select_id=sub.id)

    def _on_new_root_collection(self):
        """新建顶级集合"""
        name, ok = QInputDialog.getText(self, "新建顶级集合", "顶级集合名称:")
        if ok and name.strip():
            root = Collection(name=name.strip(), parent_id=None)
            self.db.create_collection(root)
            self._load_tree(select_id=root.id)

    def _on_accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入请求名称！")
            self.name_edit.setFocus()
            return

        if not self.selected_collection_id:
            QMessageBox.warning(self, "提示", "请选择要保存到的文件夹（可展开多级子文件夹）！")
            return

        self.request_name = name
        self.accept()

    def get_selected_collection_id(self) -> Optional[str]:
        return self.selected_collection_id

    def get_request_name(self) -> str:
        return self.request_name
