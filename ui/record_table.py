"""
레코드 테이블 뷰 + 가상화 모델

QAbstractTableModel + SQLite 쿼리 기반.
화면에 보이는 ~50행만 쿼리 → 117만 행 즉시 표시.

필터 구조:
  - id_filter: 그룹 트리에서 선택한 ID (None = 전체)
  - search_where / search_params: 검색 결과 rowid IN (...)
  - status_where: 상태 필터 (미번역/번역됨/수정됨)
  → 세 조건이 AND로 조합됨
"""

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QTableView, QHeaderView, QAbstractItemView

from core.db import LangDatabase

_COLUMNS = ["ID", "Unknown", "Index", "Source", "Target"]
_COL_ID, _COL_UNK, _COL_IDX, _COL_SRC, _COL_TGT = range(5)

_CACHE_PAGE_SIZE = 200


class RecordTableModel(QAbstractTableModel):
    """117만 행 가상화 테이블 모델. SQLite에서 필요한 행만 조회."""

    # (rowid, new_target) — 편집 요청을 외부로 위임
    edit_requested = pyqtSignal(int, str)

    def __init__(self, db: LangDatabase, parent=None):
        super().__init__(parent)
        self._db = db
        self._row_count = 0
        self._id_filter: int | list[int] | None = None
        self._search_where = ""
        self._search_params: tuple = ()
        self._status_where = ""
        self._focus_where = ""
        self._focus_params: tuple = ()
        self._codec_name: str = "identity"
        self._cache: dict[int, list[tuple]] = {}
        self.refresh_count()

    def set_codec(self, codec_name: str):
        """코덱 설정 (kr.lang 필터 분기용)."""
        self._codec_name = codec_name

    # ------------------------------------------------------------------
    # 조합된 WHERE 절 빌드
    # ------------------------------------------------------------------

    def _build_where(self) -> tuple[str, tuple]:
        """검색 + 상태 필터를 AND로 조합."""
        parts = []
        params: list = []
        if self._search_where:
            parts.append(self._search_where)
            params.extend(self._search_params)
        if self._status_where:
            parts.append(self._status_where)
        if self._focus_where:
            parts.append(self._focus_where)
            params.extend(self._focus_params)
        combined = " AND ".join(parts)
        return combined, tuple(params)

    # ------------------------------------------------------------------
    # 필터
    # ------------------------------------------------------------------

    def set_id_filter(self, id_val: "int | list[int] | None"):
        """ID 그룹 필터 설정. 단일 int, list[int] (카테고리), None (전체) 지원."""
        self.beginResetModel()
        self._id_filter = id_val
        self._cache.clear()
        self.refresh_count()
        self.endResetModel()

    def set_search_results(self, rowids: list[int] | None):
        """검색 결과 rowid 리스트로 필터링. 빈 리스트 = 0건 표시, None = 해제."""
        self.beginResetModel()
        if rowids is None:
            self._search_where = ""
            self._search_params = ()
        elif len(rowids) == 0:
            self._search_where = "0"  # 항상 거짓 → 0행
            self._search_params = ()
        else:
            placeholders = ",".join("?" * len(rowids))
            self._search_where = f"rowid IN ({placeholders})"
            self._search_params = tuple(rowids)
        self._cache.clear()
        self.refresh_count()
        self.endResetModel()

    def set_status_filter(self, filter_text: str):
        """상태 필터 설정 (검색 조건과 독립, 코덱 인식).

        kr.lang 특수 처리:
        - 미번역만: source에 한글 없음 (영어 원문) AND target 비어있음
        - 번역됨:  source에 한글 있음 (기번역) OR target 채워짐 (사용자 편집)
        - 수정됨:  modified = 1 (이번 세션 편집)
        """
        self.beginResetModel()
        # 우클릭 exact-match 포커스 필터는 상태 탭 전환 시 자동 해제한다.
        self._focus_where = ""
        self._focus_params = ()
        from core.text_codec import is_kr_codec
        is_kr = is_kr_codec(self._codec_name)
        if filter_text == "미번역만":
            if is_kr:
                self._status_where = "target = '' AND NOT has_korean(source)"
            else:
                self._status_where = "target = ''"
        elif filter_text == "번역됨":
            if is_kr:
                self._status_where = "(has_korean(source) OR target != '')"
            else:
                self._status_where = "target != ''"
        elif filter_text == "수정됨":
            self._status_where = "modified = 1"
        elif filter_text == "기존 번역 있음":
            # 외부에서 _ref_filter 임시 테이블이 미리 채워져 있어야 함
            self._status_where = (
                "rowid IN (SELECT rowid FROM _ref_filter)"
            )
        else:
            self._status_where = ""
        self._cache.clear()
        self.refresh_count()
        self.endResetModel()

    def clear_filters(self):
        """모든 필터 초기화."""
        self.beginResetModel()
        self._id_filter = None
        self._search_where = ""
        self._search_params = ()
        self._status_where = ""
        self._focus_where = ""
        self._focus_params = ()
        self._cache.clear()
        self.refresh_count()
        self.endResetModel()

    def set_exact_text_filter(self, field_name: str | None, text: str = ""):
        """Source/Target exact-match 필터 설정."""
        self.beginResetModel()
        if field_name not in {"source", "target"} or text == "":
            self._focus_where = ""
            self._focus_params = ()
        else:
            self._focus_where = f"{field_name} = ?"
            self._focus_params = (text,)
        self._cache.clear()
        self.refresh_count()
        self.endResetModel()

    def get_filter_context(self) -> tuple[int | None, str, tuple]:
        """현재 적용 중인 ID/검색/상태 필터 조합 반환."""
        where, params = self._build_where()
        return self._id_filter, where, params

    def refresh_count(self):
        where, params = self._build_where()
        self._row_count = self._db.count_by_filter(
            id_filter=self._id_filter,
            where_clause=where,
            params=params,
        )

    # ------------------------------------------------------------------
    # QAbstractTableModel 구현
    # ------------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return self._row_count

    def columnCount(self, parent=QModelIndex()):
        return len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.column() == _COL_TGT:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or index.column() != _COL_TGT:
            return False
        record = self._get_row(index.row())
        if record is None:
            return False
        rowid = record[0]
        new_target = str(value)
        if new_target == record[5]:
            return False  # 변경 없음
        self.edit_requested.emit(rowid, new_target)
        return True

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()
        record = self._get_row(row)

        if record is None:
            return None

        # record = (rowid, id, unknown, idx, source, target, modified)
        if role == Qt.ItemDataRole.DisplayRole:
            if col == _COL_ID:
                return str(record[1])
            elif col == _COL_UNK:
                return str(record[2])
            elif col == _COL_IDX:
                return str(record[3])
            elif col == _COL_SRC:
                return record[4]
            elif col == _COL_TGT:
                return record[5]

        elif role == Qt.ItemDataRole.BackgroundRole:
            if record[6] == 1:  # modified
                return QColor("#1a3a1a")

        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == _COL_TGT and record[5] == "":
                return QColor("#6d6d6d")  # 미번역 흐리게

        elif role == Qt.ItemDataRole.UserRole:
            return record[0]  # rowid

        return None

    # ------------------------------------------------------------------
    # 캐싱
    # ------------------------------------------------------------------

    def _get_row(self, row: int) -> tuple | None:
        page = row // _CACHE_PAGE_SIZE
        if page not in self._cache:
            offset = page * _CACHE_PAGE_SIZE
            where, params = self._build_where()
            self._cache[page] = self._db.get_records_range(
                offset,
                _CACHE_PAGE_SIZE,
                id_filter=self._id_filter,
                where_clause=where,
                params=params,
            )
        local = row % _CACHE_PAGE_SIZE
        page_rows = self._cache[page]
        if local < len(page_rows):
            return page_rows[local]
        return None

    def invalidate_cache(self):
        """캐시 무효화 (편집 후 호출)."""
        self._cache.clear()

    def notify_row_changed(self, rowid: int):
        """특정 rowid가 변경됨을 뷰에 알림. 캐시 무효화 + dataChanged."""
        # 해당 rowid가 속한 캐시 페이지만 무효화
        self._cache.clear()
        # 전체 갱신 (가상화 모델이라 visible 행만 갱신됨)
        top = self.index(0, 0)
        bottom = self.index(self._row_count - 1, len(_COLUMNS) - 1)
        self.dataChanged.emit(top, bottom)

    def get_rowid(self, row: int) -> int | None:
        """뷰 행 번호 → DB rowid."""
        record = self._get_row(row)
        return record[0] if record else None

    def get_record(self, row: int) -> tuple | None:
        """뷰 행 번호 → 현재 보이는 레코드."""
        return self._get_row(row)


class RecordTableView(QTableView):
    """레코드 테이블 뷰 위젯."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(False)
        self.setShowGrid(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(26)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def apply_column_widths(self):
        """컬럼 너비 설정."""
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        self.setColumnWidth(_COL_ID, 110)
        self.setColumnWidth(_COL_UNK, 60)
        self.setColumnWidth(_COL_IDX, 70)
        header.setSectionResizeMode(_COL_SRC, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_TGT, QHeaderView.ResizeMode.Stretch)

    def keyPressEvent(self, event):
        """Ctrl+C로 선택 행 클립보드 복사."""
        if event.matches(QKeySequence.StandardKey.Copy):
            self._copy_selection()
            return
        super().keyPressEvent(event)

    def _copy_selection(self):
        """선택된 행을 탭 구분 텍스트로 클립보드에 복사."""
        sel = self.selectionModel()
        if sel is None:
            return

        indexes = sel.selectedRows()
        if not indexes:
            return

        model = self.model()
        if model is None:
            return

        # 헤더
        headers = []
        for col in range(model.columnCount()):
            h = model.headerData(col, Qt.Orientation.Horizontal)
            headers.append(str(h) if h else "")

        lines = ["\t".join(headers)]

        # 행 데이터
        for idx in sorted(indexes, key=lambda i: i.row()):
            row_data = []
            for col in range(model.columnCount()):
                cell = model.data(model.index(idx.row(), col))
                row_data.append(str(cell) if cell is not None else "")
            lines.append("\t".join(row_data))

        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
