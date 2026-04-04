"""대화상자 모음."""

from __future__ import annotations

import re
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.find_replace import FindReplaceConfig


@dataclass(frozen=True)
class FindReplaceDialogResult:
    """일괄 치환 요청."""

    config: FindReplaceConfig
    scope: str  # "filtered" | "all"


class FindReplaceDialog(QDialog):
    """Target 컬럼용 찾기/치환 대화상자."""

    def __init__(
        self,
        parent=None,
        *,
        initial_find: str = "",
        initial_regex: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("찾기 / 일괄 치환")
        self.resize(460, 220)
        self._setup_ui(initial_find=initial_find, initial_regex=initial_regex)

    def _setup_ui(self, *, initial_find: str, initial_regex: bool):
        layout = QVBoxLayout(self)

        help_label = QLabel(
            "Target 컬럼의 비어있지 않은 텍스트만 치환합니다.\n"
            "현재 필터 결과 또는 전체 레코드 범위에 적용할 수 있습니다."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        form = QFormLayout()

        self._find_edit = QLineEdit(initial_find)
        self._find_edit.setPlaceholderText("찾을 문자열 또는 정규식")
        form.addRow("찾기", self._find_edit)

        self._replace_edit = QLineEdit()
        self._replace_edit.setPlaceholderText("바꿀 문자열")
        form.addRow("바꾸기", self._replace_edit)

        self._regex_cb = QCheckBox("정규식 사용")
        self._regex_cb.setChecked(initial_regex)
        form.addRow("", self._regex_cb)

        self._scope_combo = QComboBox()
        self._scope_combo.addItem("현재 필터 결과", "filtered")
        self._scope_combo.addItem("전체 레코드", "all")
        form.addRow("적용 범위", self._scope_combo)

        layout.addLayout(form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("치환")
        self._buttons.accepted.connect(self._validate_and_accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _validate_and_accept(self):
        find_text = self._find_edit.text()
        if not find_text:
            QMessageBox.warning(self, "일괄 치환", "찾을 문자열을 입력하세요.")
            self._find_edit.setFocus()
            return

        if self._regex_cb.isChecked():
            try:
                re.compile(find_text)
            except re.error as exc:
                QMessageBox.warning(self, "일괄 치환", f"정규식 오류: {exc}")
                self._find_edit.setFocus()
                return

        self.accept()

    def get_result(self) -> FindReplaceDialogResult:
        return FindReplaceDialogResult(
            config=FindReplaceConfig(
                find_text=self._find_edit.text(),
                replace_text=self._replace_edit.text(),
                use_regex=self._regex_cb.isChecked(),
            ),
            scope=self._scope_combo.currentData(),
        )


class SourceTranslationLookupDialog(QDialog):
    """같은 Source 문자열에 쓰인 기존 번역문을 보여주는 대화상자."""

    def __init__(self, source_text: str, summary: dict, parent=None):
        super().__init__(parent)
        self._source_text = source_text
        self._summary = summary
        self._selected_translation = ""
        self.setWindowTitle("기존 번역 보기")
        self.resize(680, 420)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        source_label = QLabel(f"원문: {self._source_text}")
        source_label.setWordWrap(True)
        source_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(source_label)

        translated_rows = self._summary["translated_rows"]
        total_rows = self._summary["total_rows"]
        suggestion_rows = self._summary.get("suggestion_rows", translated_rows)
        current_match_rows = self._summary.get("current_match_rows", translated_rows)
        reference_match_rows = self._summary.get("reference_match_rows", 0)
        reference_label = self._summary.get("reference_label", "기존 KR 패치")

        info_parts = [
            f"총 출현: {total_rows:,}건",
            f"현재 편집 번역: {current_match_rows:,}건",
            f"미번역: {self._summary['untranslated_rows']:,}건",
            f"추천 번역문 종류: {self._summary['variant_count']:,}개",
        ]
        if reference_match_rows > 0:
            info_parts.append(f"{reference_label} 참고: {reference_match_rows:,}건")
        info_label = QLabel(" | ".join(info_parts))
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self._table = QTableWidget(len(self._summary["variants"]), 4)
        self._table.setHorizontalHeaderLabels(["번역문", "사용 건수", "비율", "출처"])
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.itemDoubleClicked.connect(self._accept_selected_translation)
        layout.addWidget(self._table)

        for row, variant in enumerate(self._summary["variants"]):
            target_text = variant["target"]
            count = variant["count"]
            ratio = (count / suggestion_rows * 100) if suggestion_rows > 0 else 0.0
            self._table.setItem(row, 0, QTableWidgetItem(target_text))
            self._table.setItem(row, 1, QTableWidgetItem(f"{count:,}"))
            self._table.setItem(row, 2, QTableWidgetItem(f"{ratio:.1f}%"))
            self._table.setItem(
                row,
                3,
                QTableWidgetItem(variant.get("origin_label", "현재 편집")),
            )

        if self._summary["variants"]:
            self._table.selectRow(0)
        else:
            empty_label = QLabel("같은 Source에 연결된 번역문이 아직 없습니다.")
            empty_label.setWordWrap(True)
            layout.addWidget(empty_label)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._apply_button = self._buttons.addButton(
            "선택 번역 입력",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._apply_button.clicked.connect(self._accept_selected_translation)
        self._apply_button.setEnabled(bool(self._summary["variants"]))
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _accept_selected_translation(self):
        translation = self.selected_translation()
        if not translation:
            return
        self._selected_translation = translation
        self.accept()

    def selected_translation(self) -> str:
        indexes = self._table.selectionModel().selectedRows()
        if not indexes:
            return ""
        row = indexes[0].row()
        return self._summary["variants"][row]["target"]
