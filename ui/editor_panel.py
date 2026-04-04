"""
Source / Target 편집 패널 — 테이블 아래에 배치.

테이블에서 행 선택 → Source(읽기전용) + Target(편집) 표시.
Target 편집 완료 시 edit_committed 시그널로 MainWindow에 위임.
"""

from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QLabel, QSplitter, QPushButton, QHBoxLayout,
)


_PREVIEW_MAX_LEN = 72


@dataclass
class _EditorState:
    mode: str = "empty"
    rowid: int | None = None
    rowids: list[int] = field(default_factory=list)
    source_text: str = ""
    original_target: str = ""
    batch_original_target: str | None = None


class EditorPanel(QWidget):
    """Source/Target 편집 패널."""

    # (rowid, new_target) — 편집 완료 시 발생
    edit_committed = pyqtSignal(int, str)
    # (rowids, new_target) — 다중 선택 일괄 편집
    batch_edit_committed = pyqtSignal(list, str)
    # (source_text) — 같은 원문의 기존 번역 조회 요청
    source_lookup_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = _EditorState()
        self._updating = False  # 프로그래밍적 변경 시 시그널 차단
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Source 패널 (읽기전용)
        source_widget = QWidget()
        source_layout = QVBoxLayout(source_widget)
        source_layout.setContentsMargins(4, 2, 2, 4)
        source_layout.setSpacing(2)

        source_header = QHBoxLayout()
        source_header.setContentsMargins(0, 0, 0, 0)

        source_label = QLabel("Source (원문)")
        source_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        source_header.addWidget(source_label)
        source_header.addStretch(1)

        self._lookup_button = QPushButton("기존 번역 보기")
        self._lookup_button.clicked.connect(self._request_source_lookup)
        self._lookup_button.setVisible(False)
        source_header.addWidget(self._lookup_button)
        source_layout.addLayout(source_header)

        self._source_edit = QTextEdit()
        self._source_edit.setReadOnly(True)
        self._source_edit.setPlaceholderText("행을 선택하세요")
        self._source_edit.setTabChangesFocus(True)
        source_layout.addWidget(self._source_edit)

        # Target 패널 (편집 가능)
        target_widget = QWidget()
        target_layout = QVBoxLayout(target_widget)
        target_layout.setContentsMargins(2, 2, 4, 4)
        target_layout.setSpacing(2)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)

        self._target_label = QLabel("Target (번역)")
        self._target_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        header_row.addWidget(self._target_label)
        header_row.addStretch(1)

        self._apply_button = QPushButton("선택 항목에 적용")
        self._apply_button.clicked.connect(self._apply_multi_edit)
        self._apply_button.setVisible(False)
        header_row.addWidget(self._apply_button)

        target_layout.addLayout(header_row)

        self._target_edit = QTextEdit()
        self._target_edit.setPlaceholderText("번역을 입력하세요")
        self._target_edit.setTabChangesFocus(True)
        self._target_edit.setAcceptRichText(False)
        target_layout.addWidget(self._target_edit)

        splitter.addWidget(source_widget)
        splitter.addWidget(target_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

        # eventFilter로 포커스 아웃 감지 (인스턴스 메서드 덮어쓰기 대신)
        self._target_edit.installEventFilter(self)

        self.setEnabled(False)

    def eventFilter(self, obj, event):
        """Target 편집기의 포커스 아웃 시 커밋."""
        if (obj is self._target_edit and
                event.type() == QEvent.Type.FocusOut and
                self._state.mode != "multi"):
            self._commit_if_changed()
        return super().eventFilter(obj, event)

    def set_record(self, rowid: int, source: str, target: str):
        """선택된 레코드를 패널에 표시."""
        self._commit_if_changed()
        self._updating = True
        self._state = _EditorState(
            mode="single",
            rowid=rowid,
            rowids=[rowid],
            source_text=source,
            original_target=target,
        )
        self._source_edit.setPlainText(source)
        self._target_edit.setPlainText(target)
        self._target_edit.setPlaceholderText("번역을 입력하세요")
        self._target_label.setText(f"Target (번역) — rowid: {rowid}")
        self._apply_button.setVisible(False)
        self._lookup_button.setVisible(bool(source.strip()))
        self._updating = False
        self.setEnabled(True)

    def set_multi_records(self, records: list[tuple[int, str, str]]):
        """다중 선택 레코드를 패널에 표시하고 같은 Target을 일괄 적용."""
        self._commit_if_changed()
        self._updating = True

        rowids = [rowid for rowid, _, _ in records]
        count = len(rowids)

        preview_lines = [f"{count:,}개 행 선택됨", ""]
        for rowid, source, _ in records[:5]:
            preview = " ".join(source.split())
            if len(preview) > _PREVIEW_MAX_LEN:
                preview = preview[:_PREVIEW_MAX_LEN - 3] + "..."
            preview_lines.append(f"{rowid}: {preview}")
        if count > 5:
            preview_lines.append(f"... 외 {count - 5:,}개")
        self._source_edit.setPlainText("\n".join(preview_lines))

        targets = {target for _, _, target in records}
        if len(targets) == 1:
            common_target = targets.pop()
            self._target_edit.setPlainText(common_target)
        else:
            self._target_edit.clear()
            common_target = None

        self._target_edit.setPlaceholderText(
            "선택한 행들에 공통으로 적용할 번역을 입력하세요"
        )
        self._state = _EditorState(
            mode="multi",
            rowids=rowids,
            batch_original_target=common_target,
        )
        self._target_label.setText(f"Target (일괄 편집) — {count:,}개 선택")
        self._apply_button.setText(f"{count:,}개에 적용")
        self._apply_button.setVisible(True)
        self._lookup_button.setVisible(False)
        self._updating = False
        self.setEnabled(True)

    def clear_record(self):
        """패널 초기화."""
        self._commit_if_changed()
        self._updating = True
        self._state = _EditorState()
        self._source_edit.clear()
        self._target_edit.clear()
        self._target_edit.setPlaceholderText("번역을 입력하세요")
        self._target_label.setText("Target (번역)")
        self._apply_button.setVisible(False)
        self._lookup_button.setVisible(False)
        self._updating = False
        self.setEnabled(False)

    def update_target_text(self, text: str):
        """외부에서 target 텍스트 갱신 (undo/redo 후)."""
        self._updating = True
        self._target_edit.setPlainText(text)
        self._state.original_target = text
        self._state.batch_original_target = text
        self._updating = False

    def set_suggested_target_text(self, text: str):
        """조회 창에서 고른 번역문을 현재 편집기에 입력."""
        self._updating = True
        self._target_edit.setPlainText(text)
        self._updating = False

    def focus_target(self):
        """Target 편집기에 포커스."""
        self._target_edit.setFocus()

    def _request_source_lookup(self):
        """현재 source 문자열의 기존 번역 조회 요청."""
        if self._state.mode != "single" or not self._state.source_text.strip():
            return
        self.source_lookup_requested.emit(self._state.source_text)

    def _apply_multi_edit(self):
        """다중 선택 항목에 같은 target 텍스트 적용."""
        if self._updating or self._state.mode != "multi" or len(self._state.rowids) <= 1:
            return
        new_text = self._target_edit.toPlainText()
        if (
            self._state.batch_original_target is not None
            and new_text == self._state.batch_original_target
        ):
            return
        self.batch_edit_committed.emit(self._state.rowids.copy(), new_text)
        self._state.batch_original_target = new_text

    def _has_pending_multi_change(self, new_text: str) -> bool:
        """다중 선택 상태에서 자동 커밋할 변경이 있는지 확인."""
        if self._state.mode != "multi" or len(self._state.rowids) <= 1:
            return False
        if self._state.batch_original_target is None:
            return new_text != ""
        return new_text != self._state.batch_original_target

    def _commit_if_changed(self):
        """현재 편집 내용이 변경되었으면 커밋."""
        if self._updating:
            return
        new_text = self._target_edit.toPlainText()
        if self._state.rowid is not None:
            if new_text != self._state.original_target:
                self.edit_committed.emit(self._state.rowid, new_text)
                self._state.original_target = new_text
            return
        if self._has_pending_multi_change(new_text):
            self.batch_edit_committed.emit(self._state.rowids.copy(), new_text)
            self._state.batch_original_target = new_text
