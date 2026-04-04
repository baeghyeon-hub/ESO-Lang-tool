"""
JSON 내보내기 / 가져오기 mixin.

MainWindow에서 분리된 export/import 관련 로직.
"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from core.export_import import (
    export_records, export_filtered, export_modified, export_diff, import_records,
)


class ExportImportMixin:
    """JSON 내보내기/가져오기 기능 mixin."""

    def _export_selected(self, _checked=False):
        """선택된 행을 JSON으로 내보내기."""
        if self._db is None or self._model is None:
            return
        rowids = self._get_selected_rowids()
        if not rowids:
            QMessageBox.information(self, "내보내기", "먼저 행을 선택하세요.")
            return
        self._export_rowids(rowids)

    def _export_rowids(self, rowids: list[int]):
        """주어진 rowid 목록을 JSON으로 내보내기."""
        if self._db is None or self._model is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "내보내기",
            str(Path.cwd() / "export.json"),
            "JSON 파일 (*.json);;모든 파일 (*)",
        )
        if not path:
            return

        count = export_records(self._db, rowids, Path(path))
        self._statusbar.showMessage(f"내보내기 완료: {count:,}건 → {path}", 5000)

    def _export_filtered(self, _checked=False):
        """현재 필터/그룹에 표시된 행을 JSON으로 내보내기."""
        if self._db is None or self._model is None:
            return
        id_filter, where, params = self._model.get_filter_context()
        total = self._model.rowCount()

        if total <= 0:
            QMessageBox.information(self, "내보내기", "내보낼 레코드가 없습니다.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            f"현재 필터 내보내기 ({total:,}건)",
            str(Path.cwd() / "export.json"),
            "JSON 파일 (*.json);;모든 파일 (*)",
        )
        if not path:
            return

        count = export_filtered(
            self._db,
            Path(path),
            id_filter=id_filter,
            where_clause=where,
            params=params,
        )
        self._statusbar.showMessage(f"내보내기 완료: {count:,}건 → {path}", 5000)

    def _export_modified(self, _checked=False):
        """이 툴에서 수정한 항목(modified=1)만 JSON으로 내보내기."""
        if self._db is None or self._model is None:
            return
        modified_count = self._db.get_modified_count()

        if modified_count == 0:
            QMessageBox.information(
                self, "내보내기",
                "수정된 항목이 없습니다.\n"
                "이 툴에서 번역을 수정하면 자동으로 추적됩니다."
            )
            return

        en_db = self._ensure_base_db()

        path, _ = QFileDialog.getSaveFileName(
            self,
            f"수정된 항목 내보내기 ({modified_count:,}건)",
            str(Path.cwd() / "modified_export.json"),
            "JSON 파일 (*.json);;모든 파일 (*)",
        )
        if not path:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            count = export_modified(self._db, Path(path), en_db=en_db)
        finally:
            QApplication.restoreOverrideCursor()

        self._statusbar.showMessage(
            f"수정된 항목 내보내기 완료: {count:,}건 → {path}", 5000
        )

    def _export_diff(self, _checked=False):
        """en.lang과 비교하여 번역된 모든 항목을 JSON으로 내보내기."""
        if self._db is None or self._model is None:
            return
        en_db = self._ensure_base_db()
        if en_db is None:
            QMessageBox.warning(
                self,
                "비교 내보내기",
                "en.lang 파일이 필요합니다.\n"
                "같은 폴더에 en.lang 파일을 배치해 주세요.",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "en.lang 비교 — 번역된 항목 내보내기",
            str(Path.cwd() / "diff_export.json"),
            "JSON 파일 (*.json);;모든 파일 (*)",
        )
        if not path:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            count = export_diff(self._db, en_db, Path(path))
        finally:
            QApplication.restoreOverrideCursor()

        self._statusbar.showMessage(
            f"비교 내보내기 완료: {count:,}건 → {path}", 5000
        )
        QMessageBox.information(
            self,
            "비교 내보내기 완료",
            f"en.lang과 비교하여 번역된 항목: {count:,}건\n\n"
            f"파일: {path}\n\n"
            f"이 파일을 다른 사용자가 '번역 가져오기'로\n"
            f"자신의 kr.lang에 적용할 수 있습니다.",
        )

    def _import_translations(self, _checked=False):
        """JSON 파일에서 번역 가져오기."""
        if self._db is None or self._model is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "번역 가져오기",
            str(Path.cwd()),
            "JSON 파일 (*.json);;모든 파일 (*)",
        )
        if not path:
            return

        # 가져오기 모드 선택
        msg = QMessageBox(self)
        msg.setWindowTitle("가져오기 모드")
        msg.setText(
            "JSON의 어떤 필드를 Target에 적용할까요?\n\n"
            "• target 필드 사용: 일반 번역 가져오기\n"
            "• source 필드 사용: 영어 원문을 Target에 덮어쓰기\n"
            "  (en.lang에서 내보낸 파일로 한글→영어 복원 시)"
        )
        btn_target = msg.addButton("target 필드 사용", QMessageBox.ButtonRole.AcceptRole)
        btn_source = msg.addButton("source 필드 사용", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == btn_target:
            use_source = False
        elif clicked == btn_source:
            use_source = True
        else:
            return

        updates, result = import_records(
            self._db, Path(path), use_source_as_target=use_source,
        )

        if result.errors:
            error_msg = "\n".join(result.errors[:10])
            if len(result.errors) > 10:
                error_msg += f"\n... 외 {len(result.errors) - 10}건"
            QMessageBox.warning(self, "가져오기 경고", error_msg)

        mode_desc = "source→target" if use_source else "target→target"
        if not updates:
            QMessageBox.information(
                self,
                "가져오기",
                f"모드: {mode_desc}\n"
                f"파일: {result.total_rows:,}건 읽음\n"
                f"매칭: {result.matched:,}건\n"
                f"변경 사항 없음",
            )
            return

        reply = QMessageBox.question(
            self,
            "가져오기 확인",
            f"모드: {mode_desc}\n"
            f"파일: {result.total_rows:,}건 읽음\n"
            f"매칭: {result.matched:,}건\n"
            f"변경 예정: {result.changed:,}건\n"
            f"매칭 실패: {result.skipped_no_match:,}건\n\n"
            f"{result.changed:,}건을 적용하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        changed = self._undo_mgr.edit_batch(updates, description=f"번역 가져오기 ({result.changed}건)")
        self._model.invalidate_cache()
        self._update_edit_stats()
        self._dirty = True
        self._update_title()
        self._update_undo_actions()
        self._statusbar.showMessage(
            f"가져오기 완료: {changed:,}건 적용 ({mode_desc})", 5000,
        )
