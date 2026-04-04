"""
좌측 그룹 트리 — 카테고리별 계층 구조 + 레코드 수 표시.

구조:
  All (1,170,000)
  ├─ 📜 퀘스트 (120,000)
  │   ├─ QUEST_NAME · 52420949 (5,000)
  │   ├─ QUEST_STEP · 7949764 (37,000)
  │   └─ ...
  ├─ ⚔ 아이템 (180,000)
  │   └─ ...
  ├─ 미분류 (300,000)
  │   ├─ 12345678 (1,200)
  │   └─ ...
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QColor, QFont
from PyQt6.QtWidgets import QTreeView, QAbstractItemView

from core.db import LangDatabase
from core.glossary import (
    get_id_category,
    get_id_category_description,
    CATEGORY_GROUPS,
    CATEGORY_DESCRIPTION_MAP,
    _GROUPED_CATEGORIES,
)


# UserRole+1 에 filter 값 저장 (int, list[int], 또는 None)
_ROLE_FILTER = Qt.ItemDataRole.UserRole


class GroupTreeView(QTreeView):
    """ID 그룹 트리 뷰. 클릭 시 해당 그룹 필터 적용."""

    group_selected = pyqtSignal(object)  # int | list[int] | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tree_model = QStandardItemModel()
        self._tree_model.setHorizontalHeaderLabels(["그룹"])
        self.setModel(self._tree_model)
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setIndentation(16)
        self.clicked.connect(self._on_clicked)

    def load_groups(self, db: LangDatabase):
        """DB에서 그룹 목록을 로드하여 계층 트리에 표시."""
        self._tree_model.clear()
        self._tree_model.setHorizontalHeaderLabels(["그룹"])

        groups = db.get_group_ids()  # [(id, count), ...]
        total = sum(cnt for _, cnt in groups)
        id_count_map = {gid: cnt for gid, cnt in groups}

        # ── 카테고리별로 ID 분류 ──
        # category_name → [(group_id, count), ...]
        cat_ids: dict[str, list[tuple[int, int]]] = {}
        unclassified: list[tuple[int, int]] = []

        for group_id, count in groups:
            category = get_id_category(group_id)
            if category == "UNCLASSIFIED":
                unclassified.append((group_id, count))
            else:
                cat_ids.setdefault(category, []).append((group_id, count))

        # ── All 항목 ──
        all_item = QStandardItem(f"전체  ({total:,})")
        all_item.setData(None, _ROLE_FILTER)
        all_item.setForeground(QColor("#569cd6"))
        font = all_item.font()
        font.setBold(True)
        all_item.setFont(font)
        self._tree_model.appendRow(all_item)

        # ── 카테고리 그룹 폴더 ──
        for group_label, icon, cat_list in CATEGORY_GROUPS:
            # 이 그룹에 속하는 ID 수집
            folder_ids: list[int] = []
            folder_count = 0
            child_items: list[QStandardItem] = []

            for cat_name in cat_list:
                if cat_name not in cat_ids:
                    continue
                for gid, cnt in cat_ids[cat_name]:
                    folder_ids.append(gid)
                    folder_count += cnt
                    desc = CATEGORY_DESCRIPTION_MAP.get(cat_name, cat_name)
                    child = QStandardItem(f"{desc}  ({cnt:,})")
                    child.setData(gid, _ROLE_FILTER)
                    child.setForeground(QColor("#d4d4d4"))
                    child.setToolTip(
                        f"{desc}\n"
                        f"카테고리: {cat_name}\n"
                        f"ID: {gid}\n"
                        f"레코드: {cnt:,}"
                    )
                    child_items.append(child)

            if not child_items:
                continue

            # 폴더 항목
            folder = QStandardItem(f"{icon} {group_label}  ({folder_count:,})")
            folder.setForeground(QColor("#dcdcaa"))
            font = folder.font()
            font.setBold(True)
            folder.setFont(font)
            # 폴더 클릭 시 해당 카테고리의 모든 ID로 필터
            folder.setData(folder_ids, _ROLE_FILTER)
            folder.setToolTip(f"{group_label} — {len(child_items)}개 하위 그룹")

            for child in child_items:
                folder.appendRow(child)

            self._tree_model.appendRow(folder)

        # ── 미분류 폴더 ──
        if unclassified:
            unc_count = sum(cnt for _, cnt in unclassified)
            unc_ids = [gid for gid, _ in unclassified]

            unc_folder = QStandardItem(f"미분류  ({unc_count:,})")
            unc_folder.setForeground(QColor("#808080"))
            font = unc_folder.font()
            font.setBold(True)
            unc_folder.setFont(font)
            unc_folder.setData(unc_ids, _ROLE_FILTER)
            unc_folder.setToolTip(f"미분류 ID — {len(unclassified)}개 그룹")

            for gid, cnt in unclassified:
                child = QStandardItem(f"{gid}  ({cnt:,})")
                child.setData(gid, _ROLE_FILTER)
                child.setForeground(QColor("#808080"))
                unc_folder.appendRow(child)

            self._tree_model.appendRow(unc_folder)

        # All 항목 선택
        self.setCurrentIndex(self._tree_model.index(0, 0))

    def _on_clicked(self, index):
        item = self._tree_model.itemFromIndex(index)
        if item:
            filter_val = item.data(_ROLE_FILTER)
            self.group_selected.emit(filter_val)
