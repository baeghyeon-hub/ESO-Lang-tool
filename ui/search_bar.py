"""
검색/필터 위젯 — FTS5 기반 실시간 검색 + 정규식 + 필터 콤보.

타이핑 300ms 디바운스 → FTS5 MATCH → 결과 rowid를 테이블 모델에 전달.
정규식 모드: DB에서 LIKE 후보 축소 → Python re로 정밀 필터.
"""

import re

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QCheckBox, QComboBox, QLabel,
)

from core.db import LangDatabase


class SearchBar(QWidget):
    """검색바 위젯."""

    search_results = pyqtSignal(object)  # list[int] | None (None = 필터 해제)
    filter_changed = pyqtSignal(str)     # 필터 종류 변경

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db: LangDatabase | None = None
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._do_search)

        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._input = QLineEdit()
        self._input.setPlaceholderText("검색... (FTS5)")
        self._input.setClearButtonEnabled(True)
        self._input.textChanged.connect(self._on_text_changed)

        self._regex_cb = QCheckBox("정규식")
        self._regex_cb.setChecked(False)
        self._regex_cb.toggled.connect(self._on_regex_toggled)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["전체", "미번역만", "번역됨", "수정됨", "기존 번역 있음"])
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)

        self._result_label = QLabel("")

        layout.addWidget(QLabel("검색"))
        layout.addWidget(self._input, stretch=1)
        layout.addWidget(self._regex_cb)
        layout.addWidget(self._filter_combo)
        layout.addWidget(self._result_label)

    def set_db(self, db: LangDatabase):
        self._db = db

    def _on_text_changed(self, text: str):
        self._debounce.start()

    def _on_regex_toggled(self, checked: bool):
        if checked:
            self._input.setPlaceholderText("정규식 검색... (Python re)")
        else:
            self._input.setPlaceholderText("검색... (FTS5)")
        # 현재 검색어가 있으면 재검색
        if self._input.text().strip():
            self._debounce.start()

    def _on_filter_changed(self, text: str):
        self.filter_changed.emit(text)

    def _do_search(self):
        if self._db is None:
            return

        query = self._input.text().strip()
        if not query:
            self._result_label.setText("")
            self.search_results.emit(None)
            return

        if self._regex_cb.isChecked():
            rowids = self._search_regex(query)
        else:
            results = self._db.search_fts(query, limit=5000)
            rowids = [r[0] for r in results]

        self._result_label.setText(f"{len(rowids):,}건")
        self.search_results.emit(rowids)

    def _search_regex(self, pattern: str) -> list[int]:
        """정규식 검색: DB LIKE로 후보 축소 → re로 정밀 필터."""
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            self._result_label.setText("정규식 오류")
            return []

        # 패턴에서 리터럴 부분 추출하여 LIKE 사전 필터
        # 단순 키워드가 있으면 사용, 없으면 전체 스캔
        candidates = self._db.search_like("", limit=0)  # 전체는 너무 느림
        # 대신 FTS나 LIKE로 부분 키워드 검색
        alpha_parts = re.findall(r'[a-zA-Z가-힣]{2,}', pattern)
        if alpha_parts:
            keyword = alpha_parts[0]
            candidates = self._db.search_like(keyword, limit=50000)
        else:
            candidates = self._db.search_like("", limit=50000)

        rowids = []
        for r in candidates:
            # r = (rowid, id, unknown, idx, source, target)
            source = r[4] if r[4] else ""
            target = r[5] if r[5] else ""
            if regex.search(source) or regex.search(target):
                rowids.append(r[0])

        return rowids

    def get_current_filter(self) -> str:
        return self._filter_combo.currentText()

    def current_query(self) -> str:
        return self._input.text()

    def is_regex_enabled(self) -> bool:
        return self._regex_cb.isChecked()

    def focus_input(self):
        """검색 입력창으로 포커스 이동."""
        self._input.setFocus()

    def refresh_search(self):
        """현재 검색어가 있으면 검색 결과를 재계산."""
        if self._input.text().strip():
            self._do_search()

    def clear_search(self):
        self._input.clear()
        self._result_label.setText("")
