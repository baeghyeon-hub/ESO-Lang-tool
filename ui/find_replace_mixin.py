"""
일괄 치환 (Find & Replace) mixin.

MainWindow에서 분리된 일괄 치환 관련 로직.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from core.find_replace import FindReplaceConfig, make_replacer
from ui.dialogs import FindReplaceDialog


class FindReplaceMixin:
    """일괄 치환 기능 mixin."""

    def _open_find_replace_dialog(self, checked: bool = False):
        if self._db is None or self._model is None or self._undo_mgr is None:
            return

        dialog = FindReplaceDialog(
            self,
            initial_find=self._search_bar.current_query(),
            initial_regex=self._search_bar.is_regex_enabled(),
        )
        if not dialog.exec():
            return

        result = dialog.get_result()
        scope_id_filter, scope_where, scope_params, scope_label = (
            self._resolve_replace_scope(result.scope)
        )

        try:
            updates = self._collect_find_replace_updates(
                result.config,
                id_filter=scope_id_filter,
                where_clause=scope_where,
                params=scope_params,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "일괄 치환", str(exc))
            return

        if updates is None:
            self._statusbar.showMessage("일괄 치환 취소됨", 3000)
            return
        if not updates:
            QMessageBox.information(
                self,
                "일괄 치환",
                f"{scope_label}에서 치환할 Target 텍스트를 찾지 못했습니다.",
            )
            return

        reply = QMessageBox.question(
            self,
            "일괄 치환 확인",
            f"범위: {scope_label}\n"
            f"치환 대상: {len(updates):,}건\n\n"
            f"찾기: {result.config.find_text}\n"
            f"바꾸기: {result.config.replace_text}\n\n"
            "이대로 적용할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        description = self._build_replace_description(result.config, len(updates))
        changed = self._undo_mgr.edit_batch(updates, description=description)
        if changed <= 0:
            return

        self._dirty = True
        self._model.invalidate_cache()
        self._model.notify_row_changed(0)
        self._update_undo_actions()
        self._update_edit_stats()
        self._search_bar.refresh_search()
        self._sync_editor_after_undo_redo()
        self._update_title()
        self._statusbar.showMessage(
            f"일괄 치환 완료 — {changed:,}건 ({scope_label})",
            5000,
        )

    def _resolve_replace_scope(
        self,
        scope: str,
    ) -> tuple[int | None, str, tuple, str]:
        if self._model is None:
            return None, "", (), "전체 레코드"
        if scope == "all":
            return None, "", (), "전체 레코드"
        id_filter, where, params = self._model.get_filter_context()
        return id_filter, where, params, "현재 필터 결과"

    @staticmethod
    def _append_where(
        where_clause: str,
        params: tuple,
        extra_clause: str,
        extra_params: tuple = (),
    ) -> tuple[str, tuple]:
        parts = []
        bind = list(params)
        if where_clause:
            parts.append(where_clause)
        if extra_clause:
            parts.append(extra_clause)
            bind.extend(extra_params)
        return " AND ".join(parts), tuple(bind)

    def _collect_find_replace_updates(
        self,
        config: FindReplaceConfig,
        *,
        id_filter: int | None,
        where_clause: str,
        params: tuple,
    ) -> list[tuple[int, str]] | None:
        if self._db is None:
            return []
        replacer = make_replacer(config)
        base_where, base_params = self._append_where(
            where_clause,
            params,
            "target != ''",
        )

        candidate_where = base_where
        candidate_params = base_params
        if not config.use_regex:
            candidate_where, candidate_params = self._append_where(
                base_where,
                base_params,
                "instr(target, ?) > 0",
                (config.find_text,),
            )

        total_candidates = self._db.count_by_filter(
            id_filter=id_filter,
            where_clause=candidate_where,
            params=candidate_params,
        )
        if total_candidates == 0:
            return []

        progress = QProgressDialog("치환 대상 검사 중...", "취소", 0, total_candidates, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()

        updates: list[tuple[int, str]] = []
        processed = 0
        try:
            for rowid, target in self._db.iter_target_records(
                id_filter=id_filter,
                where_clause=candidate_where,
                params=candidate_params,
            ):
                new_target = replacer(target)
                if new_target != target:
                    updates.append((rowid, new_target))

                processed += 1
                if processed % 500 == 0 or processed == total_candidates:
                    progress.setValue(processed)
                    progress.setLabelText(
                        f"치환 대상 검사 중... {processed:,} / {total_candidates:,}"
                    )
                    QApplication.processEvents()
                    if progress.wasCanceled():
                        return None
        finally:
            progress.close()

        return updates

    @staticmethod
    def _build_replace_description(
        config: FindReplaceConfig,
        count: int,
    ) -> str:
        find_text = config.find_text
        if len(find_text) > 20:
            find_text = find_text[:17] + "..."
        prefix = "정규식 치환" if config.use_regex else "일괄 치환"
        return f"{prefix}: {find_text} ({count}건)"
