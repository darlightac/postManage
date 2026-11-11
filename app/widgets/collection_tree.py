"""集合树组件 - 左侧面板的请求集合管理 (支持多级文件夹、展开折叠、拖拽移动、右键剪贴板复制/剪切/粘贴/克隆)"""

from typing import Optional, Set
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QHBoxLayout, QMenu, QInputDialog, QMessageBox, QLabel,
    QToolTip,
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QPoint, QRect, QTimer, QMimeData, QEvent
from PyQt6.QtGui import (
    QIcon, QAction, QColor, QKeySequence, QDrag, QPainter,
    QPen, QBrush, QPixmap, QFontMetrics, QCursor,
)

from app.core.db import Database
from app.core.models import Collection, SavedRequest
from app.config.themes import get_method_color, ThemeManager
from app.widgets.request_tabs import AddTabButton, create_method_badge_icon
from app.core.logger import get_logger
from app.config.i18n import tr

logger = get_logger("collection_tree")


class CustomCollectionTreeWidget(QTreeWidget):
    """支持内部拖拽、悬停高亮动画、自动悬停展开与标准快捷键的集合树控件"""

    def __init__(self, parent_panel):
        super().__init__(parent_panel)
        self.parent_panel = parent_panel
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)

        # 拖拽内部状态
        self._dragged_item: Optional[QTreeWidgetItem] = None
        self._dragged_data: Optional[dict] = None
        self._hover_target_item: Optional[QTreeWidgetItem] = None

        # 悬停 500ms 自动展开文件夹动画计时器
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(500)
        self._hover_timer.timeout.connect(self._on_hover_timeout)

        # 主题强调色 (默认紫色)
        self._accent_color = QColor("#7c3aed")

        # 鼠标移动感知与悬停超过 1 秒展示完整接口名称
        self.setMouseTracking(True)
        self._fullname_tooltip_timer = QTimer(self)
        self._fullname_tooltip_timer.setSingleShot(True)
        self._fullname_tooltip_timer.setInterval(1000)
        self._fullname_tooltip_timer.timeout.connect(self._show_hover_fullname_tooltip)
        self._last_hovered_item: Optional[QTreeWidgetItem] = None
        self._hover_global_pos: Optional[QPoint] = None

    def set_accent_color(self, color_str: str):
        """设置拖拽高亮强调色"""
        self._accent_color = QColor(color_str)

    def _on_hover_timeout(self):
        """悬停达到阈值后自动展开目标文件夹"""
        if self._hover_target_item and not self._hover_target_item.isExpanded():
            data = self._hover_target_item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "collection":
                self._hover_target_item.setExpanded(True)
                name = data.get("name", "")
                self._hover_target_item.setText(0, f"📂 {name}")
                self.viewport().update()

    def _clear_hover(self):
        """清除高亮与悬停展开计时器"""
        self._hover_timer.stop()
        if self._hover_target_item is not None:
            self._hover_target_item = None
            self.viewport().update()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        item = self.itemAt(event.position().toPoint())
        if item != self._last_hovered_item:
            self._fullname_tooltip_timer.stop()
            QToolTip.hideText()
            self._last_hovered_item = item
            if item:
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data and data.get("type") == "request":
                    self._hover_global_pos = event.globalPosition().toPoint()
                    self._fullname_tooltip_timer.start(1000)
        else:
            if item and self._fullname_tooltip_timer.isActive():
                self._hover_global_pos = event.globalPosition().toPoint()

    def leaveEvent(self, event):
        self._fullname_tooltip_timer.stop()
        QToolTip.hideText()
        self._last_hovered_item = None
        super().leaveEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            # 屏蔽 Qt 自带短延迟 ToolTip，完全由 1 秒稳定悬停计时器接管
            return True
        return super().viewportEvent(event)

    def _show_hover_fullname_tooltip(self):
        """光标在接口项上停留满 1 秒时，弹出完整接口名称提示"""
        item = self._last_hovered_item
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("type") != "request":
            return

        name = data.get("name") or "未命名请求"
        url = data.get("url") or ""
        method = data.get("method") or "GET"

        tip_lines = [
            f"📌 接口全称: {name}",
            f"🏷️ 请求方法: {method}",
        ]
        if url:
            tip_lines.append(f"🔗 接口 URL: {url}")
        tip_text = "\n".join(tip_lines)

        pos = self._hover_global_pos or QCursor.pos()
        QToolTip.showText(pos, tip_text, self)

    def startDrag(self, supportedActions):
        """启动拖拽：记录拖拽源，生成精美徽章预览浮层，坚决不触发 Qt 底层 clearOrRemove 误删"""
        item = self.currentItem()
        if not item:
            selected = self.selectedItems()
            if selected:
                item = selected[0]
        if not item:
            return

        d_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not d_data:
            return

        self._dragged_item = item
        self._dragged_data = dict(d_data)

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-postmanage-tree-item", b"1")
        drag.setMimeData(mime)

        pixmap = self._create_drag_pixmap(item, d_data)
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(15, 12))

        try:
            # 采用 MoveAction，严禁调用 super().startDrag()！
            # 避免 Qt 底层 QAbstractItemView::startDrag 的 d->clearOrRemove() 误删新树节点！
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._clear_hover()
            self._dragged_item = None
            self._dragged_data = None

    def _create_drag_pixmap(self, item: QTreeWidgetItem, data: dict) -> QPixmap:
        """生成拖拽时的半透明圆角徽章预览图"""
        item_type = data.get("type", "request")
        name = data.get("name", "") or (data.get("url", "") if item_type == "request" else "未命名")
        if len(name) > 22:
            name = name[:20] + "…"

        prefix = f"[{data.get('method', 'GET')}] " if item_type == "request" else "📁 "
        text = prefix + name

        font = self.font()
        font.setPointSize(9)
        font.setBold(True)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(text)
        w = max(110, text_w + 24)
        h = 26

        pix = QPixmap(w, h)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 胶囊圆角阴影背景
        bg_color = QColor(self._accent_color)
        bg_color.setAlpha(210)
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(QColor(255, 255, 255, 120), 1))
        painter.drawRoundedRect(1, 1, w - 2, h - 2, 6, 6)

        # 文字
        painter.setPen(QColor("#ffffff"))
        painter.setFont(font)
        painter.drawText(QRect(10, 0, w - 16, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.end()
        return pix

    def dragEnterEvent(self, event):
        if (event.source() is None or event.source() == self) and self._dragged_data:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if (event.source() is not None and event.source() != self) or not self._dragged_data:
            event.ignore()
            return

        target_item = self.itemAt(event.position().toPoint())
        d_data = self._dragged_data
        d_type = d_data.get("type")

        target_folder_item = None
        valid_target = False

        if d_type == "request":
            if target_item:
                t_data = target_item.data(0, Qt.ItemDataRole.UserRole)
                if t_data and t_data.get("type") == "collection":
                    target_folder_item = target_item
                    valid_target = True
                elif t_data and t_data.get("type") == "request":
                    target_folder_item = target_item.parent()
                    valid_target = True
        elif d_type == "collection":
            if target_item is None:
                # 拖到空白区域：移为顶级集合
                valid_target = True
            else:
                t_data = target_item.data(0, Qt.ItemDataRole.UserRole)
                if t_data and t_data.get("type") == "collection":
                    # 循环嵌套安全检测
                    curr = target_item
                    is_descendant = False
                    dragged_id = d_data.get("id")
                    while curr:
                        c_data = curr.data(0, Qt.ItemDataRole.UserRole)
                        if c_data and c_data.get("id") == dragged_id:
                            is_descendant = True
                            break
                        curr = curr.parent()
                    if not is_descendant and t_data.get("id") != dragged_id:
                        target_folder_item = target_item
                        valid_target = True

        # 更新目标悬停高亮与展开计时器
        if target_folder_item != self._hover_target_item:
            self._hover_target_item = target_folder_item
            self.viewport().update()
            if self._hover_target_item and not self._hover_target_item.isExpanded():
                self._hover_timer.start()
            else:
                self._hover_timer.stop()

        if valid_target:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._clear_hover()
        super().dragLeaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        # 绘制目标文件夹悬停高亮框与直观的「移入 ↵」徽章
        if self._hover_target_item:
            rect = self.visualItemRect(self._hover_target_item)
            if rect.isValid() and not rect.isEmpty():
                painter = QPainter(self.viewport())
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                # 绘制高亮强调色微光背景 (Alpha 45)
                glow_color = QColor(self._accent_color)
                glow_color.setAlpha(45)
                painter.setBrush(QBrush(glow_color))

                # 绘制高亮圆角边框
                border_color = QColor(self._accent_color)
                border_color.setAlpha(210)
                painter.setPen(QPen(border_color, 1.5, Qt.PenStyle.SolidLine))

                draw_rect = rect.adjusted(2, 1, -2, -1)
                painter.drawRoundedRect(draw_rect, 4, 4)

                # 右侧绘制直观的指示徽章
                badge_w = 48
                badge_h = 16
                badge_x = draw_rect.right() - badge_w - 6
                badge_y = draw_rect.top() + (draw_rect.height() - badge_h) // 2
                badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)

                painter.setBrush(QBrush(border_color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(badge_rect, 3, 3)

                painter.setPen(QColor("#ffffff"))
                font = self.font()
                font.setPointSize(8)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "移入 ↵")

                painter.end()

    def dropEvent(self, event):
        self._clear_hover()
        d_data = self._dragged_data
        if not d_data:
            selected = self.selectedItems()
            if selected:
                d_data = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if not d_data:
            event.ignore()
            return

        target_item = self.itemAt(event.position().toPoint())
        t_data = target_item.data(0, Qt.ItemDataRole.UserRole) if target_item else None

        if d_data.get("type") == "request":
            target_coll_id = None
            if t_data and t_data.get("type") == "collection":
                target_coll_id = t_data["id"]
            elif t_data and t_data.get("type") == "request":
                target_coll_id = t_data.get("collection_id")
            elif target_item and target_item.parent():
                p_data = target_item.parent().data(0, Qt.ItemDataRole.UserRole)
                if p_data and p_data.get("type") == "collection":
                    target_coll_id = p_data["id"]

            if target_coll_id and target_coll_id != d_data.get("collection_id"):
                ok = self.parent_panel.db.move_request(d_data["id"], target_coll_id)
                if ok:
                    logger.info(f"拖拽接口 [{d_data.get('name')}] 到集合 ID={target_coll_id}")
                    self.parent_panel.refresh_tree(select_id=d_data["id"], expand_id=target_coll_id)
                    self.parent_panel.collection_changed.emit()
                    event.acceptProposedAction()
                    return

        elif d_data.get("type") == "collection":
            new_parent_id = None
            if target_item and t_data and t_data.get("type") == "collection":
                new_parent_id = t_data["id"]

            if new_parent_id != d_data["id"]:
                ok = self.parent_panel.db.move_collection(d_data["id"], new_parent_id)
                if ok:
                    logger.info(f"拖拽集合 [{d_data.get('name')}] 到新父集合 ID={new_parent_id}")
                    self.parent_panel.refresh_tree(select_id=d_data["id"], expand_id=new_parent_id)
                    self.parent_panel.collection_changed.emit()
                    event.acceptProposedAction()
                    return

        event.ignore()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.parent_panel._copy_selected()
            event.accept()
        elif event.matches(QKeySequence.StandardKey.Cut):
            self.parent_panel._cut_selected()
            event.accept()
        elif event.matches(QKeySequence.StandardKey.Paste):
            self.parent_panel._paste_to_selected()
            event.accept()
        elif event.key() == Qt.Key.Key_Delete:
            self.parent_panel._delete_selected()
            event.accept()
        else:
            super().keyPressEvent(event)


class CollectionTree(QWidget):
    """左侧集合树面板（多级文件夹、展开折叠、拖拽移动、剪贴板操作）"""

    # 信号：选中了一个保存的请求
    request_selected = pyqtSignal(str)  # request_id
    # 信号：请求列表变化
    collection_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.db = Database()
        # 内部剪贴板状态
        self._clipboard_action: Optional[str] = None  # "copy" 或 "cut"
        self._clipboard_request_id: Optional[str] = None

        self._init_ui()
        # 性能优化：启动时不阻塞主窗口瞬间呈现，在首帧空闲事件循环中异步加载集合树
        QTimer.singleShot(0, self.refresh_tree)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 标题栏
        header = QHBoxLayout()
        header.setContentsMargins(4, 4, 4, 2)
        header.setSpacing(4)

        self.title_label = QLabel(tr("tab_collections", "📁 集合"))
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(self.title_label)
        header.addStretch()

        # 展开全部按钮
        self.btn_expand_all = QPushButton("📂")
        self.btn_expand_all.setFixedSize(24, 24)
        self.btn_expand_all.setToolTip(tr("tree_expand_all", "展开全部文件夹"))
        self.btn_expand_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_expand_all.setStyleSheet("border: none; background: transparent; font-size: 13px;")
        self.btn_expand_all.clicked.connect(self._on_expand_all)
        header.addWidget(self.btn_expand_all)

        # 折叠全部按钮
        self.btn_collapse_all = QPushButton("📁")
        self.btn_collapse_all.setFixedSize(24, 24)
        self.btn_collapse_all.setToolTip(tr("tree_collapse_all", "折叠全部文件夹"))
        self.btn_collapse_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_collapse_all.setStyleSheet("border: none; background: transparent; font-size: 13px;")
        self.btn_collapse_all.clicked.connect(self._on_collapse_all)
        header.addWidget(self.btn_collapse_all)

        # 新建集合按钮
        self.btn_add = AddTabButton()
        self.btn_add.setFixedSize(24, 24)
        self.btn_add.setToolTip(tr("tree_new_top_collection", "新建顶级集合"))
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(self._on_add_collection)
        header.addWidget(self.btn_add)

        layout.addLayout(header)

        # 自定义可拖拽树控件
        self.tree = CustomCollectionTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(38, 18))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemCollapsed.connect(self._on_item_collapsed)
        layout.addWidget(self.tree)

    def retranslate_ui(self):
        """动态刷新界面语言"""
        if hasattr(self, 'title_label'):
            self.title_label.setText(tr("tab_collections", "📁 集合"))
        if hasattr(self, 'btn_expand_all'):
            self.btn_expand_all.setToolTip(tr("tree_expand_all", "展开全部文件夹"))
        if hasattr(self, 'btn_collapse_all'):
            self.btn_collapse_all.setToolTip(tr("tree_collapse_all", "折叠全部文件夹"))
        if hasattr(self, 'btn_add'):
            self.btn_add.setToolTip(tr("tree_new_top_collection", "新建顶级集合"))

    def _on_expand_all(self):
        self.tree.expandAll()

    def _on_collapse_all(self):
        self.tree.collapseAll()

    def _on_item_expanded(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "collection":
            name = data.get("name", "")
            item.setText(0, f"📂 {name}")

    def _on_item_collapsed(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "collection":
            name = data.get("name", "")
            item.setText(0, f"📁 {name}")

    def apply_theme(self, t):
        """应用主题"""
        if hasattr(self.tree, "set_accent_color"):
            self.tree.set_accent_color(getattr(t, "primary", "#7c3aed"))
        self.title_label.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {t.text_primary};")
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                border: none;
                font-size: 13px;
                background-color: {t.bg_sidebar};
                color: {t.text_primary};
            }}
            QTreeWidget::item {{
                padding: 4px 6px;
                border-radius: 4px;
                margin: 1px 4px;
            }}
            QTreeWidget::item:selected {{
                background-color: {t.bg_selected};
                border-radius: 4px;
                color: {t.text_primary};
            }}
            QTreeWidget::item:hover {{
                background-color: {t.bg_hover};
                border-radius: 4px;
            }}
        """)
        # 刷新所有请求节点的方法图标和文字颜色
        is_dark = (t.name == "dark")
        def _update_items(parent_item):
            count = parent_item.childCount() if parent_item else self.tree.topLevelItemCount()
            for i in range(count):
                child = parent_item.child(i) if parent_item else self.tree.topLevelItem(i)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                if data and data.get("type") == "request":
                    method = data.get("method", "GET")
                    child.setIcon(0, create_method_badge_icon(method, is_dark))
                    child.setForeground(0, QColor(t.text_primary))
                elif data and data.get("type") == "collection":
                    _update_items(child)
        _update_items(None)

    def refresh_tree(self, select_id: Optional[str] = None, expand_id: Optional[str] = None):
        """刷新集合树（保留所有多级嵌套已有集合的展开/折叠状态，且确保目标及其祖先链全部展开可见）"""
        # 递归记录当前所有已展开的集合 id
        expanded_ids: Set[str] = set()

        def _collect_expanded(item: QTreeWidgetItem):
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "collection" and item.isExpanded():
                expanded_ids.add(data["id"])
            for idx in range(item.childCount()):
                _collect_expanded(item.child(idx))

        for i in range(self.tree.topLevelItemCount()):
            _collect_expanded(self.tree.topLevelItem(i))

        # 向上追溯祖先集合链辅助函数，保证目标文件夹及其所有父级文件夹全部处于展开状态
        def _add_ancestors(coll_id: Optional[str]):
            curr_id = coll_id
            while curr_id:
                expanded_ids.add(curr_id)
                coll = self.db.get_collection(curr_id)
                if coll and coll.parent_id:
                    curr_id = coll.parent_id
                else:
                    break

        if expand_id:
            _add_ancestors(expand_id)

        if select_id:
            # 若选中的是集合，展开其祖先链；若是请求，展开其所属集合及其祖先链
            coll_candidate = self.db.get_collection(select_id)
            if coll_candidate:
                _add_ancestors(select_id)
            else:
                req = self.db.get_request(select_id)
                if req and req.collection_id:
                    _add_ancestors(req.collection_id)

        self.tree.clear()
        collections = self.db.get_collections(parent_id=None)
        item_to_select = None

        for coll in collections:
            found = self._add_collection_node(None, coll, expanded_ids, select_id)
            if found:
                item_to_select = found

        if item_to_select:
            self.tree.setCurrentItem(item_to_select)
            self.tree.scrollToItem(item_to_select)

    def _add_collection_node(
        self,
        parent_item: Optional[QTreeWidgetItem],
        collection: Collection,
        expanded_ids: Set[str],
        select_id: Optional[str] = None
    ) -> Optional[QTreeWidgetItem]:
        """递归添加集合与多级子文件夹节点"""
        if parent_item is None:
            item = QTreeWidgetItem(self.tree)
        else:
            item = QTreeWidgetItem(parent_item)

        # 判断是否展开
        is_expanded = (collection.id in expanded_ids) if expanded_ids else True
        icon_char = "📂" if is_expanded else "📁"
        item.setText(0, f"{icon_char} {collection.name}")
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "type": "collection",
            "id": collection.id,
            "name": collection.name,
            "parent_id": collection.parent_id
        })
        item.setToolTip(0, f"文件夹: {collection.name}")
        item.setExpanded(is_expanded)

        found_item = None
        if select_id and collection.id == select_id:
            found_item = item

        # 添加该集合下的所有请求
        is_dark = (ThemeManager.current().name == "dark")
        t = ThemeManager.current()
        requests = self.db.get_requests(collection.id)
        for req in requests:
            req_item = QTreeWidgetItem(item)
            method = req.method
            title = req.name if req.name else req.url
            badge_icon = create_method_badge_icon(method, is_dark)
            req_item.setIcon(0, badge_icon)
            req_item.setText(0, title)
            req_item.setForeground(0, QColor(t.text_primary))
            req_item.setToolTip(0, f"[{method}] {title}\n{req.url}")
            req_item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "request",
                "id": req.id,
                "name": req.name,
                "method": method,
                "collection_id": collection.id,
                "url": req.url
            })
            if select_id and req.id == select_id:
                found_item = req_item

        # 递归添加多级子文件夹
        sub_collections = self.db.get_collections(parent_id=collection.id)
        for sub_coll in sub_collections:
            sub_found = self._add_collection_node(item, sub_coll, expanded_ids, select_id)
            if sub_found:
                found_item = sub_found

        return found_item

    def _on_add_collection(self):
        """新建顶级集合"""
        name, ok = QInputDialog.getText(self, "新建集合", "集合名称:")
        if ok and name.strip():
            coll = Collection(name=name.strip())
            self.db.create_collection(coll)
            logger.info(f"创建顶级集合: {name.strip()}")
            self.refresh_tree(expand_id=coll.id)
            self.collection_changed.emit()

    def _on_add_sub_collection(self, parent_id: str):
        """新建子文件夹"""
        name, ok = QInputDialog.getText(self, "新建子文件夹", "文件夹名称:")
        if ok and name.strip():
            coll = Collection(name=name.strip(), parent_id=parent_id)
            self.db.create_collection(coll)
            logger.info(f"创建子文件夹: {name.strip()} (父级: {parent_id})")
            self.refresh_tree(expand_id=parent_id)
            self.collection_changed.emit()

    def _on_add_request(self, collection_id: str):
        """新建请求"""
        name, ok = QInputDialog.getText(self, "新建请求", "请求名称:")
        if ok and name.strip():
            req = SavedRequest(collection_id=collection_id, name=name.strip())
            self.db.create_request(req)
            logger.info(f"在集合 {collection_id} 下创建请求: {name.strip()}")
            self.refresh_tree(select_id=req.id, expand_id=collection_id)
            self.collection_changed.emit()

    def _on_context_menu(self, pos):
        """右键上下文菜单（支持复制、剪切、粘贴、重命名、删除与展开折叠）"""
        item = self.tree.itemAt(pos)
        menu = QMenu(self)

        has_clipboard = bool(self._clipboard_request_id)
        clipboard_desc = f" ({self._clipboard_action})" if has_clipboard else ""

        if item is None:
            # 空白处右键
            act_new = menu.addAction(tr("tree_new_top_collection", "📁 新建顶级集合"))
            act_new.triggered.connect(self._on_add_collection)

            menu.addSeparator()
            act_exp = menu.addAction(tr("tree_expand_all", "📂 展开全部文件夹"))
            act_exp.triggered.connect(self._on_expand_all)
            act_col = menu.addAction(tr("tree_collapse_all", "📁 折叠全部文件夹"))
            act_col.triggered.connect(self._on_collapse_all)

        else:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            item_type = data.get("type")

            if item_type == "collection":
                coll_id = data["id"]
                act_sub = menu.addAction(tr("tree_new_subfolder", "📁 新建子文件夹"))
                act_sub.triggered.connect(lambda: self._on_add_sub_collection(coll_id))

                act_req = menu.addAction(tr("tree_new_request", "➕ 新建请求"))
                act_req.triggered.connect(lambda: self._on_add_request(coll_id))

                menu.addSeparator()

                # 粘贴接口
                act_paste = menu.addAction(f"{tr('tree_paste_request', '📋 粘贴接口')}{clipboard_desc}\tCtrl+V")
                act_paste.setEnabled(has_clipboard)
                act_paste.triggered.connect(lambda: self._paste_to_collection(coll_id))

                menu.addSeparator()

                # 展开 / 折叠当前文件夹子树
                act_exp_sub = menu.addAction(tr("tree_expand_sub", "📂 展开该文件夹下所有项"))
                act_exp_sub.triggered.connect(lambda: self._expand_item_recursive(item, True))
                act_col_sub = menu.addAction(tr("tree_collapse_sub", "📁 折叠该文件夹下所有项"))
                act_col_sub.triggered.connect(lambda: self._expand_item_recursive(item, False))

                menu.addSeparator()

                act_rename = menu.addAction(f"{tr('tree_rename_collection', '✏️ 修改名称 (重命名)')}\tF2")
                act_rename.triggered.connect(lambda: self._on_rename_collection(coll_id, item))

                act_del = menu.addAction(f"{tr('tree_delete_folder', '🗑️ 删除文件夹')}\tDel")
                act_del.triggered.connect(lambda: self._on_delete_collection(coll_id))

            elif item_type == "request":
                req_id = data["id"]
                coll_id = data.get("collection_id")

                # 复制 / 剪切 / 粘贴
                act_copy = menu.addAction(f"{tr('tree_copy_request', '📋 复制接口')}\tCtrl+C")
                act_copy.triggered.connect(lambda: self._copy_request(req_id))

                act_cut = menu.addAction(f"{tr('tree_cut_request', '✂️ 剪切接口')}\tCtrl+X")
                act_cut.triggered.connect(lambda: self._cut_request(req_id))

                act_paste = menu.addAction(f"{tr('tree_paste_request', '📋 粘贴接口')}{clipboard_desc}\tCtrl+V")
                act_paste.setEnabled(has_clipboard)
                act_paste.triggered.connect(lambda: self._paste_to_collection(coll_id))

                act_clone = menu.addAction(f"{tr('tree_clone_request', '📄 克隆接口')}\tCtrl+D")
                act_clone.triggered.connect(lambda: self._clone_request_here(req_id, coll_id))

                menu.addSeparator()

                act_rename = menu.addAction(f"{tr('tree_rename', '✏️ 重命名')}\tF2")
                act_rename.triggered.connect(lambda: self._on_rename_request(req_id))

                act_del = menu.addAction(f"{tr('tree_delete_request', '🗑️ 删除接口')}\tDel")
                act_del.triggered.connect(lambda: self._on_delete_request(req_id))

        menu.exec(self.tree.mapToGlobal(pos))

    def _expand_item_recursive(self, item: QTreeWidgetItem, expand: bool):
        """递归展开或折叠子项"""
        item.setExpanded(expand)
        for i in range(item.childCount()):
            self._expand_item_recursive(item.child(i), expand)

    # ─── 剪贴板操作 (复制 / 剪切 / 粘贴 / 克隆) ───────────────────

    def _copy_request(self, request_id: str):
        self._clipboard_action = "copy"
        self._clipboard_request_id = request_id
        req = self.db.get_request(request_id)
        name = req.name if req else request_id
        logger.info(f"复制接口到剪贴板: [{name}]")

    def _cut_request(self, request_id: str):
        self._clipboard_action = "cut"
        self._clipboard_request_id = request_id
        req = self.db.get_request(request_id)
        name = req.name if req else request_id
        logger.info(f"剪切接口到剪贴板: [{name}]")

    def _paste_to_collection(self, target_collection_id: str):
        if not self._clipboard_request_id or not target_collection_id:
            return

        req_id = self._clipboard_request_id
        action = self._clipboard_action

        if action == "copy":
            cloned = self.db.clone_request(req_id, target_collection_id)
            if cloned:
                logger.info(f"粘贴(克隆)接口 [{cloned.name}] 到集合 {target_collection_id}")
                self.refresh_tree(select_id=cloned.id, expand_id=target_collection_id)
                self.collection_changed.emit()
        elif action == "cut":
            ok = self.db.move_request(req_id, target_collection_id)
            if ok:
                logger.info(f"粘贴(移动)接口 ID={req_id} 到集合 {target_collection_id}")
                self._clipboard_action = None
                self._clipboard_request_id = None
                self.refresh_tree(select_id=req_id, expand_id=target_collection_id)
                self.collection_changed.emit()

    def _clone_request_here(self, request_id: str, collection_id: str):
        """原地创建接口副本"""
        cloned = self.db.clone_request(request_id, collection_id)
        if cloned:
            logger.info(f"创建接口副本: [{cloned.name}]")
            self.refresh_tree(select_id=cloned.id, expand_id=collection_id)
            self.collection_changed.emit()

    def _copy_selected(self):
        item = self.tree.currentItem()
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "request":
            self._copy_request(data["id"])

    def _cut_selected(self):
        item = self.tree.currentItem()
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "request":
            self._cut_request(data["id"])

    def _paste_to_selected(self):
        item = self.tree.currentItem()
        if not item or not self._clipboard_request_id:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data["type"] == "collection":
            self._paste_to_collection(data["id"])
        elif data["type"] == "request":
            self._paste_to_collection(data.get("collection_id"))

    def _delete_selected(self):
        item = self.tree.currentItem()
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data["type"] == "collection":
            self._on_delete_collection(data["id"])
        elif data["type"] == "request":
            self._on_delete_request(data["id"])

    # ─── 改名与删除 ───────────────────────────────────────────

    def _on_rename_collection(self, collection_id: str, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        old_name = data.get("name", "") if data else item.text(0)[2:].strip()
        new_name, ok = QInputDialog.getText(self, tr("tree_rename_collection_title", "修改集合名称"), tr("tree_rename_collection_prompt", "新名称:"), text=old_name)
        if ok and new_name.strip():
            self.db.rename_collection(collection_id, new_name.strip())
            logger.info(f"重命名集合 {collection_id} -> {new_name.strip()}")
            self.refresh_tree(select_id=collection_id)
            self.collection_changed.emit()

    def _on_rename_request(self, request_id: str):
        req = self.db.get_request(request_id)
        if req:
            new_name, ok = QInputDialog.getText(self, tr("tree_rename_request_title", "重命名请求"), tr("tree_rename_request_prompt", "新名称:"), text=req.name)
            if ok and new_name.strip():
                req.name = new_name.strip()
                self.db.update_request(req)
                logger.info(f"重命名请求 {request_id} -> {new_name.strip()}")
                self.refresh_tree(select_id=request_id)

    def _on_delete_collection(self, collection_id: str):
        reply = QMessageBox.question(
            self, "删除文件夹",
            "确定删除该文件夹及其包含的所有子文件夹与接口？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_collection(collection_id)
            logger.info(f"删除集合及其级联内容: ID={collection_id}")
            self.refresh_tree()
            self.collection_changed.emit()

    def _on_delete_request(self, request_id: str):
        reply = QMessageBox.question(
            self, "删除请求",
            "确定删除该请求？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_request(request_id)
            logger.info(f"删除请求: ID={request_id}")
            self.refresh_tree()
            self.collection_changed.emit()

    def _on_item_double_clicked(self, item: QTreeWidgetItem):
        """双击处理：双击请求打开详情，双击集合文件夹修改名称"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        item_type = data.get("type")
        if item_type == "request":
            self.request_selected.emit(data["id"])
        elif item_type == "collection":
            self._on_rename_collection(data["id"], item)
