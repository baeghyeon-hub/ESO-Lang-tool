"""
용어집 패널 — 하단 탭의 "용어집" 탭.

기능:
- 카테고리 필터 + 검색
- 용어/번역/메모 인라인 편집
- 용어집 추출 (records → glossary)
- 용어집 JSON import/export
- 용어 추가/삭제
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.db import LangDatabase
from core.glossary import (
    CATEGORY_DESCRIPTION_MAP,
    extract_glossary,
    fill_glossary_from_records,
)

# ---------------------------------------------------------------------------
# 용어집 테이블 모델
# ---------------------------------------------------------------------------

_COLUMNS = ["용어 (EN)", "번역 (KR)", "카테고리", "성별", "사용 수", "메모"]
_COL_TERM = 0
_COL_TRANS = 1
_COL_CAT = 2
_COL_GENDER = 3
_COL_USAGE = 4
_COL_NOTE = 5


class GlossaryTableModel(QAbstractTableModel):
    """용어집 가상화 테이블 모델."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db: LangDatabase | None = None
        self._rows: list[tuple] = []

    def set_db(self, db: LangDatabase | None):
        self.beginResetModel()
        self._db = db
        self._rows = []
        self.endResetModel()

    def load(self, *, category: str | None = None, keyword: str = ""):
        """데이터 새로고침."""
        self.beginResetModel()
        if not self._db:
            self._rows = []
        elif keyword:
            self._rows = self._db.search_glossary(keyword, limit=5000)
            if category:
                self._rows = [r for r in self._rows if r[3] == category]
        else:
            self._rows = self._db.get_glossary_by_category(category, limit=50000)
        self.endResetModel()

    # --- QAbstractTableModel ---

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == _COL_TERM:
                return row[1]
            if col == _COL_TRANS:
                return row[2]
            if col == _COL_CAT:
                return CATEGORY_DESCRIPTION_MAP.get(row[3], row[3])
            if col == _COL_GENDER:
                return row[4]
            if col == _COL_USAGE:
                return row[5]
            if col == _COL_NOTE:
                return row[6]

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == _COL_TRANS:
                return QColor("#666666") if not row[2] else QColor("#4ec9b0")
            if col == _COL_USAGE:
                return QColor("#b5cea8")
            if col == _COL_CAT:
                return QColor("#dcdcaa")

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (_COL_USAGE, _COL_GENDER):
                return Qt.AlignmentFlag.AlignCenter

        return None

    def flags(self, index):
        base = super().flags(index)
        if index.column() in (_COL_TRANS, _COL_NOTE):
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not self._db:
            return False

        row = self._rows[index.row()]
        rowid = row[0]
        col = index.column()

        if col == _COL_TRANS:
            new_trans = str(value).strip()
            self._db.update_glossary_translation(rowid, new_trans, row[6])
            self._rows[index.row()] = (
                row[0], row[1], new_trans, row[3], row[4], row[5], row[6]
            )
            self.dataChanged.emit(index, index)
            return True

        if col == _COL_NOTE:
            new_note = str(value).strip()
            self._db.update_glossary_translation(rowid, row[2], new_note)
            self._rows[index.row()] = (
                row[0], row[1], row[2], row[3], row[4], row[5], new_note
            )
            self.dataChanged.emit(index, index)
            return True

        return False

    def get_rowid(self, row_idx: int) -> int | None:
        if 0 <= row_idx < len(self._rows):
            return self._rows[row_idx][0]
        return None

    def get_row_data(self, row_idx: int) -> tuple | None:
        if 0 <= row_idx < len(self._rows):
            return self._rows[row_idx]
        return None


# ---------------------------------------------------------------------------
# 용어집 패널
# ---------------------------------------------------------------------------

_BTN_STYLE = "QPushButton { background-color: #3c3c3c; padding: 4px 10px; }"
_BTN_PRIMARY = (
    "QPushButton { background-color: #0e639c; font-weight: bold; "
    "padding: 5px 14px; color: #ffffff; }"
)
_STAT_STYLE = "font-size: 12px; color: #cccccc; padding: 2px 0;"


class GlossaryPanel(QWidget):
    """용어집 탭 위젯."""

    glossary_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db: LangDatabase | None = None
        self._en_db: LangDatabase | None = None  # en.lang 영어 원문 DB
        self._kr_db: LangDatabase | None = None  # kr.lang 한글 번역 DB
        self._model = GlossaryTableModel(self)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        # ── 상단: 카테고리 + 검색 + 버튼 ──
        top = QHBoxLayout()
        top.setSpacing(8)

        top.addWidget(QLabel("카테고리:"))
        self._cat_combo = QComboBox()
        self._cat_combo.setMinimumWidth(140)
        self._cat_combo.addItem("전체", None)
        self._cat_combo.currentIndexChanged.connect(self._on_filter_changed)
        top.addWidget(self._cat_combo)

        top.addWidget(QLabel("검색:"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("용어 검색...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_filter_changed)
        self._search_input.setMinimumWidth(180)
        top.addWidget(self._search_input, stretch=1)

        self._extract_btn = QPushButton("용어 추출")
        self._extract_btn.setStyleSheet(_BTN_PRIMARY)
        self._extract_btn.setToolTip("현재 로드된 데이터에서 용어집 후보를 추출합니다")
        self._extract_btn.clicked.connect(self._extract_glossary)
        top.addWidget(self._extract_btn)

        self._fill_btn = QPushButton("기존 번역 채우기")
        self._fill_btn.setStyleSheet(
            "QPushButton { background-color: #0e639c; padding: 5px 14px; color: #ffffff; }"
        )
        self._fill_btn.setToolTip(
            "records의 기존 번역(target)으로 비어있는 용어집 번역을 자동 채움"
        )
        self._fill_btn.clicked.connect(self._fill_from_records)
        top.addWidget(self._fill_btn)

        self._import_btn = QPushButton("가져오기")
        self._import_btn.setStyleSheet(_BTN_STYLE)
        self._import_btn.clicked.connect(self._import_glossary)
        top.addWidget(self._import_btn)

        self._export_btn = QPushButton("내보내기")
        self._export_btn.setStyleSheet(_BTN_STYLE)
        self._export_btn.clicked.connect(self._export_glossary)
        top.addWidget(self._export_btn)

        layout.addLayout(top)

        # ── 테이블 ──
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableView { "
            "  color: #d4d4d4; "
            "  background-color: #1e1e1e; "
            "  alternate-background-color: #2a2a2a; "
            "  gridline-color: #3c3c3c; "
            "  selection-background-color: #264f78; "
            "} "
            "QTableView::item { padding: 2px 4px; } "
            "QHeaderView::section { "
            "  background-color: #2d2d2d; "
            "  color: #cccccc; "
            "  border: 1px solid #3c3c3c; "
            "  padding: 4px; "
            "}"
        )
        self._table.verticalHeader().setDefaultSectionSize(24)
        self._table.verticalHeader().hide()
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSortingEnabled(False)
        layout.addWidget(self._table, stretch=1)

        # 컬럼 너비 기본값
        header = self._table.horizontalHeader()
        header.resizeSection(_COL_TERM, 220)
        header.resizeSection(_COL_TRANS, 220)
        header.resizeSection(_COL_CAT, 120)
        header.resizeSection(_COL_GENDER, 50)
        header.resizeSection(_COL_USAGE, 70)

        # ── 하단: 통계 + 추가/삭제 ──
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        self._stat_label = QLabel("")
        self._stat_label.setStyleSheet(_STAT_STYLE)
        bottom.addWidget(self._stat_label, stretch=1)

        self._delete_btn = QPushButton("선택 삭제")
        self._delete_btn.setStyleSheet(_BTN_STYLE)
        self._delete_btn.clicked.connect(self._delete_selected)
        bottom.addWidget(self._delete_btn)

        self._add_btn = QPushButton("용어 추가")
        self._add_btn.setStyleSheet(_BTN_STYLE)
        self._add_btn.clicked.connect(self._add_term)
        bottom.addWidget(self._add_btn)

        layout.addLayout(bottom)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_db(
        self,
        db: LangDatabase | None,
        en_db: LangDatabase | None = None,
        kr_db: LangDatabase | None = None,
    ):
        """DB 설정.

        Args:
            db: 용어집이 저장되는 메인 DB
            en_db: en.lang 영어 원문 DB (용어 추출 시 영어 term 소스)
            kr_db: kr.lang 한글 번역 DB (용어 추출 시 한글 translation 소스)
        """
        self._db = db
        self._en_db = en_db
        self._kr_db = kr_db
        self._model.set_db(db)
        self._refresh_categories()
        self._reload()

    # ------------------------------------------------------------------
    # 필터
    # ------------------------------------------------------------------

    def _on_filter_changed(self):
        self._reload()

    def _reload(self):
        cat = self._cat_combo.currentData()
        keyword = self._search_input.text().strip()
        self._model.load(category=cat, keyword=keyword)
        self._update_stats()

    def _refresh_categories(self):
        """카테고리 콤보박스 갱신."""
        self._cat_combo.blockSignals(True)
        self._cat_combo.clear()
        self._cat_combo.addItem("전체", None)

        if self._db:
            cats = self._db.get_glossary_categories()
            for cat_code, count in cats:
                desc = CATEGORY_DESCRIPTION_MAP.get(cat_code, cat_code)
                self._cat_combo.addItem(f"{desc} ({count:,})", cat_code)

        self._cat_combo.blockSignals(False)

    def _update_stats(self):
        if not self._db:
            self._stat_label.setText("")
            return

        total = self._model.rowCount()
        translated = sum(
            1 for i in range(total)
            if (d := self._model.get_row_data(i)) and d[2]
        )
        self._stat_label.setText(
            f"표시: {total:,}건 · 번역 완료: {translated:,}건"
        )

    # ------------------------------------------------------------------
    # 용어 추출
    # ------------------------------------------------------------------

    def _extract_glossary(self):
        if not self._db:
            return

        if not self._en_db:
            QMessageBox.warning(
                self,
                "용어 추출",
                "en.lang 파일이 필요합니다.\n"
                "같은 폴더에 en.lang 파일을 배치해 주세요.",
            )
            return

        clear_first = False
        existing = self._db.glossary_count()
        if existing > 0:
            msg = QMessageBox(self)
            msg.setWindowTitle("용어 추출")
            msg.setText(
                f"기존 용어집 {existing:,}건이 있습니다.\n"
                f"어떻게 처리하시겠습니까?"
            )
            btn_clear = msg.addButton("초기화 후 재추출", QMessageBox.ButtonRole.DestructiveRole)
            btn_add = msg.addButton("추가 추출 (기존 유지)", QMessageBox.ButtonRole.AcceptRole)
            msg.addButton("취소", QMessageBox.ButtonRole.RejectRole)
            msg.exec()

            clicked = msg.clickedButton()
            if clicked == btn_clear:
                clear_first = True
            elif clicked == btn_add:
                clear_first = False
            else:
                return

        result = extract_glossary(
            self._db,
            en_db=self._en_db,
            kr_db=self._kr_db,
            clear_existing=clear_first,
        )
        self._refresh_categories()
        self._reload()
        self.glossary_changed.emit()

        QMessageBox.information(
            self,
            "용어 추출 완료",
            f"추출된 용어: {result['total_extracted']:,}건\n\n"
            + "\n".join(
                f"  {CATEGORY_DESCRIPTION_MAP.get(c, c)}: {n:,}"
                for c, n in sorted(result["categories"].items(), key=lambda x: -x[1])
            ),
        )

    def _fill_from_records(self):
        """records의 기존 번역으로 용어집 빈 항목을 자동 채움."""
        if not self._db:
            return

        result = fill_glossary_from_records(self._db)
        self._reload()
        self.glossary_changed.emit()

        QMessageBox.information(
            self,
            "기존 번역 채우기 완료",
            f"채워진 항목: {result['filled']:,}건\n"
            f"매칭 실패 (번역 없음): {result['no_match']:,}건",
        )

    # ------------------------------------------------------------------
    # 용어 추가 / 삭제
    # ------------------------------------------------------------------

    def _add_term(self):
        """빈 용어 항목 추가."""
        if not self._db:
            return

        self._db.init_glossary()
        self._db._conn.execute(
            "INSERT INTO glossary (term, translation, category, gender, usage_count, note) "
            "VALUES ('', '', 'CUSTOM', '', 0, '')",
        )
        self._db._conn.commit()
        self._reload()
        self._table.scrollToBottom()

    def _delete_selected(self):
        """선택된 행 삭제."""
        if not self._db:
            return

        sel = self._table.selectionModel()
        if sel is None:
            return
        indexes = sel.selectedRows()
        if not indexes:
            return

        rowids = []
        for idx in indexes:
            rid = self._model.get_rowid(idx.row())
            if rid is not None:
                rowids.append(rid)

        if not rowids:
            return

        reply = QMessageBox.question(
            self,
            "용어 삭제",
            f"{len(rowids):,}건의 용어를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        placeholders = ",".join("?" * len(rowids))
        self._db._conn.execute(
            f"DELETE FROM glossary WHERE rowid IN ({placeholders})", rowids
        )
        self._db._conn.commit()
        self._refresh_categories()
        self._reload()
        self.glossary_changed.emit()

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def _export_glossary(self):
        """용어집 내보내기 — 형식 선택."""
        if not self._db:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("용어집 내보내기")
        msg.setText("내보내기 형식을 선택하세요.")
        btn_json = msg.addButton("단일 JSON (전체)", QMessageBox.ButtonRole.AcceptRole)
        btn_cat = msg.addButton("카테고리별 JSON (폴더)", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == btn_json:
            self._export_glossary_single()
        elif clicked == btn_cat:
            self._export_glossary_by_category()

    def _export_glossary_single(self):
        """용어집을 단일 JSON으로 내보내기."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "용어집 내보내기",
            str(Path.cwd() / "glossary.json"),
            "JSON 파일 (*.json);;모든 파일 (*)",
        )
        if not path:
            return

        self._db.init_glossary()
        rows = self._db._conn.execute(
            "SELECT term, translation, category, gender, usage_count, note "
            "FROM glossary ORDER BY category, term"
        ).fetchall()

        data = [
            {
                "term": r[0],
                "translation": r[1],
                "category": r[2],
                "gender": r[3],
                "usage_count": r[4],
                "note": r[5],
            }
            for r in rows
        ]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        QMessageBox.information(
            self, "내보내기 완료", f"{len(data):,}건 → {path}"
        )

    def _export_glossary_by_category(self):
        """카테고리별로 영>한 쌍번역 JSON 파일을 폴더에 내보내기."""
        from PyQt6.QtWidgets import QFileDialog as _QFD

        out_dir = _QFD.getExistingDirectory(
            self, "용어집 카테고리별 내보내기 — 폴더 선택", str(Path.cwd()),
        )
        if not out_dir:
            return

        out_path = Path(out_dir)

        self._db.init_glossary()
        rows = self._db._conn.execute(
            "SELECT term, translation, category "
            "FROM glossary WHERE translation != '' "
            "ORDER BY category, term"
        ).fetchall()

        # 카테고리별 그룹핑
        from collections import defaultdict
        cat_data: dict[str, list[dict]] = defaultdict(list)
        for term, translation, category in rows:
            cat_data[category].append({
                "en": term,
                "kr": translation,
            })

        if not cat_data:
            QMessageBox.information(self, "내보내기", "번역된 용어가 없습니다.")
            return

        total = 0
        file_list: list[str] = []
        for cat_code, entries in sorted(cat_data.items()):
            desc = CATEGORY_DESCRIPTION_MAP.get(cat_code, cat_code)
            filename = f"glossary_{cat_code.lower()}.json"
            filepath = out_path / filename

            export_data = {
                "category": cat_code,
                "description": desc,
                "count": len(entries),
                "terms": entries,
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)

            total += len(entries)
            file_list.append(f"  {desc} ({cat_code}): {len(entries):,}건")

        QMessageBox.information(
            self,
            "카테고리별 내보내기 완료",
            f"총 {total:,}건 → {len(cat_data)}개 파일\n\n"
            + "\n".join(file_list),
        )

    def _import_glossary(self):
        """JSON에서 용어집 가져오기."""
        if not self._db:
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "용어집 가져오기",
            str(Path.cwd()),
            "JSON 파일 (*.json);;모든 파일 (*)",
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            QMessageBox.warning(self, "가져오기 오류", str(e))
            return

        if not isinstance(data, list):
            QMessageBox.warning(self, "가져오기 오류", "JSON 루트가 배열이 아닙니다.")
            return

        self._db.init_glossary()

        imported = 0
        updated = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term", "")).strip()
            if not term:
                continue

            translation = str(item.get("translation", ""))
            category = str(item.get("category", "CUSTOM"))
            gender = str(item.get("gender", ""))
            usage_count = int(item.get("usage_count", 0))
            note = str(item.get("note", ""))

            # UPSERT: 기존 항목 있으면 번역/메모만 갱신
            existing = self._db._conn.execute(
                "SELECT rowid FROM glossary WHERE term = ? AND category = ?",
                (term, category),
            ).fetchone()

            if existing:
                if translation:
                    self._db._conn.execute(
                        "UPDATE glossary SET translation = ?, note = ? WHERE rowid = ?",
                        (translation, note, existing[0]),
                    )
                    updated += 1
            else:
                self._db._conn.execute(
                    "INSERT INTO glossary (term, translation, category, gender, usage_count, note) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (term, translation, category, gender, usage_count, note),
                )
                imported += 1

        self._db._conn.commit()
        self._refresh_categories()
        self._reload()
        self.glossary_changed.emit()

        QMessageBox.information(
            self,
            "가져오기 완료",
            f"신규: {imported:,}건\n갱신: {updated:,}건",
        )
