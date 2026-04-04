"""
소스 조회 + 기존 번역 크로스 매칭 + 일괄 적용 mixin.

SecondaryDbMixin이 제공하는 _ensure_reference_db / _ensure_base_db를 사용.
DB 내부(_conn)에 직접 접근하지 않고 LangDatabase 공용 API만 사용.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.db import _has_korean
from ui.dialogs import SourceTranslationLookupDialog


class ReferenceMixin:
    """소스 번역 조회 + 레퍼런스 크로스 매칭 + 일괄 적용."""

    # ------------------------------------------------------------------
    # 소스 번역 조회
    # ------------------------------------------------------------------

    def _build_source_lookup_summary(self, source_text: str) -> dict:
        if self._db is None:
            return {}
        summary = self._db.get_source_translation_summary(source_text)
        merged_variants: dict[str, dict] = {}

        for variant in summary["variants"]:
            merged_variants[variant["target"]] = {
                "target": variant["target"],
                "count": variant["count"],
                "origins": ["현재 편집"],
            }

        reference_match_rows = 0
        reference_db = self._ensure_reference_db()
        if reference_db is not None:
            record_keys = self._db.get_record_keys_by_source(source_text)
            reference_variants = reference_db.get_source_variants_for_record_keys(
                record_keys,
            )
            preferred_reference_variants = [
                variant
                for variant in reference_variants
                if variant["target"] != source_text
            ]
            if preferred_reference_variants:
                reference_variants = preferred_reference_variants
            reference_match_rows = sum(
                variant["count"] for variant in reference_variants
            )
            for variant in reference_variants:
                target_text = variant["target"]
                if target_text in merged_variants:
                    merged_variant = merged_variants[target_text]
                    merged_variant["count"] += variant["count"]
                    if "기존 KR 패치" not in merged_variant["origins"]:
                        merged_variant["origins"].append("기존 KR 패치")
                    continue
                merged_variants[target_text] = {
                    "target": target_text,
                    "count": variant["count"],
                    "origins": ["기존 KR 패치"],
                }

        variants = sorted(
            merged_variants.values(),
            key=lambda item: (-item["count"], item["target"]),
        )
        for variant in variants:
            variant["origin_label"] = " + ".join(variant["origins"])

        return {
            **summary,
            "variants": variants,
            "variant_count": len(variants),
            "suggestion_rows": sum(variant["count"] for variant in variants),
            "current_match_rows": summary["translated_rows"],
            "reference_match_rows": reference_match_rows,
            "reference_label": "기존 KR 패치",
        }

    def _build_source_lookup_summary_v2(self, source_text: str) -> dict:
        if self._db is None:
            return {}
        summary = self._db.get_source_translation_summary(source_text)
        canonical_source, record_keys = self._resolve_lookup_context_v2(source_text)
        merged_variants: dict[str, dict] = {}

        def merge_variants(variants: list[dict], origin_label: str) -> None:
            for variant in variants:
                target_text = variant["target"]
                if not target_text:
                    continue
                if target_text in merged_variants:
                    merged_variant = merged_variants[target_text]
                    merged_variant["count"] += variant["count"]
                    if origin_label not in merged_variant["origins"]:
                        merged_variant["origins"].append(origin_label)
                    continue
                merged_variants[target_text] = {
                    "target": target_text,
                    "count": variant["count"],
                    "origins": [origin_label],
                }

        merge_variants(
            self._db.get_target_variants_for_record_keys(record_keys),
            "현재 편집",
        )
        merge_variants(
            self._db.get_source_variants_for_record_keys(record_keys),
            "현재 파일",
        )

        reference_match_rows = 0
        reference_db = self._ensure_reference_db()
        if reference_db is not None:
            reference_variants = reference_db.get_source_variants_for_record_keys(
                record_keys,
            )
            reference_match_rows = sum(
                variant["count"] for variant in reference_variants
            )
            merge_variants(reference_variants, "기존 KR 패치")

        preferred_variants = [
            variant
            for variant in merged_variants.values()
            if variant["target"] != canonical_source
        ]
        variants = preferred_variants or list(merged_variants.values())
        variants.sort(key=lambda item: (-item["count"], item["target"]))
        for variant in variants:
            variant["origin_label"] = " + ".join(variant["origins"])

        return {
            **summary,
            "variants": variants,
            "variant_count": len(variants),
            "suggestion_rows": sum(variant["count"] for variant in variants),
            "current_match_rows": summary["translated_rows"],
            "reference_match_rows": reference_match_rows,
            "reference_label": "기존 KR 패치",
        }

    def _resolve_lookup_context_v2(
        self,
        source_text: str,
    ) -> tuple[str, list[tuple[int, int, int]]]:
        if self._db is None:
            return source_text, []
        default_keys = self._db.get_record_keys_by_source(source_text)
        from core.text_codec import is_kr_codec
        if not is_kr_codec(self._codec_name):
            return source_text, default_keys

        rowids = self._get_selected_rowids() if self._model is not None else []
        if not rowids:
            return source_text, default_keys

        record = self._db.get_record_by_rowid(rowids[0])
        if record is None:
            return source_text, default_keys

        base_db = self._ensure_base_db()
        if base_db is None:
            return source_text, default_keys

        base_source = base_db.get_source_by_key(record[0], record[1], record[2])
        if not base_source:
            return source_text, default_keys

        canonical_keys = base_db.get_record_keys_by_source(base_source)
        return base_source, canonical_keys or default_keys

    def _open_source_translation_lookup(self, source_text: str):
        source_text = source_text.strip()
        if not source_text:
            return

        summary = self._build_source_lookup_summary_v2(source_text)
        dialog = SourceTranslationLookupDialog(source_text, summary, self)
        if not dialog.exec():
            return

        selected_translation = dialog.selected_translation()
        if not selected_translation:
            return

        self._apply_source_lookup_translation(source_text, selected_translation)
        self._statusbar.showMessage(
            f"기존 번역문을 편집기에 입력했습니다. ({summary['total_rows']:,}건 중 "
            f"{summary['translated_rows']:,}건 번역됨)",
            5000,
        )

    def _apply_source_lookup_translation(
        self,
        source_text: str,
        selected_translation: str,
    ):
        if self._model is None:
            return
        self._select_exact_text_matches("source", source_text)
        self._editor_panel.set_suggested_target_text(selected_translation)
        self._editor_panel.focus_target()

    # ------------------------------------------------------------------
    # 기존 번역 크로스 매칭
    # ------------------------------------------------------------------

    def _build_reference_map(self) -> dict[tuple, str] | None:
        """레퍼런스 DB에서 (id, unknown, idx) → source 맵 빌드."""
        if self._db is None:
            return None
        ref_db = self._ensure_reference_db()
        if ref_db is None:
            return None
        ref_rows = ref_db.get_all_records_keys_sources()
        return {(r[0], r[1], r[2]): r[3] for r in ref_rows}

    def _build_source_text_translation_map(
        self, ref_map: dict[tuple, str]
    ) -> dict[str, str]:
        """en.lang + kr.lang 기반 영어 source → 한글 번역 맵 빌드."""
        if self._db is None:
            return {}
        en_to_kr: dict[str, str] = {}

        # 1단계: en.lang 기반 매핑
        base_db = self._ensure_base_db()
        if base_db is not None:
            base_rows = base_db.get_all_records_keys_sources()
            base_map = {(r[0], r[1], r[2]): r[3] for r in base_rows}
            for key, ref_text in ref_map.items():
                if _has_korean(ref_text):
                    en_source = base_map.get(key)
                    if en_source and not _has_korean(en_source) and en_source != ref_text:
                        en_to_kr.setdefault(en_source, ref_text)

        # 2단계: ref_map에서 현재 DB 키 매칭으로 영어→한글 쌍 추출
        for key, ref_text in ref_map.items():
            if _has_korean(ref_text):
                cur_source = self._db.get_source_by_key(*key)
                if cur_source and not _has_korean(cur_source) and cur_source != ref_text:
                    en_to_kr.setdefault(cur_source, ref_text)

        # 3단계: 현재 DB에서 이미 번역된 source→target 쌍
        for src, tgt in self._db.get_translated_pairs():
            if not _has_korean(src) and _has_korean(tgt):
                en_to_kr.setdefault(src, tgt)

        return en_to_kr

    def _find_ref_translatable_rowids(
        self, ref_map: dict[tuple, str]
    ) -> list[int]:
        """미번역 레코드 중 레퍼런스 번역이 존재하는 rowid 목록 (2단계 매칭)."""
        if self._db is None:
            return []
        cur_rows = self._db.get_untranslated_records()

        result = []
        unmatched_rows = []

        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if (
                ref_text
                and ref_text != source
                and not _has_korean(source)
                and _has_korean(ref_text)
            ):
                result.append(rowid)
            elif source and not _has_korean(source):
                unmatched_rows.append((rowid, source))

        if unmatched_rows:
            en_to_kr = self._build_source_text_translation_map(ref_map)
            for rowid, source in unmatched_rows:
                kr_text = en_to_kr.get(source)
                if kr_text and kr_text != source:
                    result.append(rowid)

        return result

    # ------------------------------------------------------------------
    # 필터 + 일괄 적용
    # ------------------------------------------------------------------

    def _apply_reference_filter(self):
        """'기존 번역 있음' 필터."""
        if self._db is None or self._model is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ref_map = self._build_reference_map()
            if ref_map is None:
                QApplication.restoreOverrideCursor()
                QMessageBox.information(
                    self, "알림",
                    "레퍼런스 DB(kr.lang)를 찾을 수 없습니다.\n"
                    "같은 폴더 또는 '기존 ESO 한글패치' 폴더에 kr.lang이 필요합니다.",
                )
                self._search_bar._filter_combo.setCurrentText("전체")
                return

            rowids = self._find_ref_translatable_rowids(ref_map)
            if not rowids:
                QApplication.restoreOverrideCursor()
                QMessageBox.information(
                    self, "알림",
                    "기존 번역이 적용 가능한 미번역 레코드가 없습니다.",
                )
                self._search_bar._filter_combo.setCurrentText("전체")
                return

            self._db.populate_ref_filter(rowids)
            self._model.set_status_filter("기존 번역 있음")
            self._statusbar.showMessage(
                f"기존 번역 있음: {len(rowids):,}건 필터됨", 5000,
            )
        finally:
            QApplication.restoreOverrideCursor()

    def _batch_apply_reference(self, _checked=False):
        """기존 번역을 일괄 적용."""
        if self._db is None or self._model is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ref_map = self._build_reference_map()
        finally:
            QApplication.restoreOverrideCursor()

        if ref_map is None:
            QMessageBox.information(
                self, "알림",
                "레퍼런스 DB(kr.lang)를 찾을 수 없습니다.\n"
                "같은 폴더 또는 '기존 ESO 한글패치' 폴더에 kr.lang이 필요합니다.",
            )
            return

        cur_rows = self._db.get_untranslated_records()
        updates = []
        unmatched_rows = []

        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if (
                ref_text
                and ref_text != source
                and not _has_korean(source)
                and _has_korean(ref_text)
            ):
                updates.append((ref_text, rowid))
            elif source and not _has_korean(source):
                unmatched_rows.append((rowid, source))

        if unmatched_rows:
            en_to_kr = self._build_source_text_translation_map(ref_map)
            for rowid, source in unmatched_rows:
                kr_text = en_to_kr.get(source)
                if kr_text and kr_text != source:
                    updates.append((kr_text, rowid))

        if not updates:
            QMessageBox.information(
                self, "결과",
                "적용 가능한 기존 번역이 없습니다.\n"
                "(미번역 레코드 중 레퍼런스에 번역이 존재하는 항목이 없음)",
            )
            return

        reply = QMessageBox.question(
            self, "기존 번역 일괄 적용",
            f"레퍼런스 DB에서 {len(updates):,}건의 기존 번역을 "
            f"Target에 적용하시겠습니까?\n\n"
            f"• 미번역 레코드만 대상 (이미 Target이 있는 항목은 건너뜀)\n"
            f"• 적용 후 Ctrl+Z로 개별 취소 불가 (일괄 작업)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._db.bulk_apply_translations(updates)
        finally:
            QApplication.restoreOverrideCursor()

        self._model.invalidate_cache()
        self._db.rebuild_fts()
        self._update_edit_stats()
        self._dirty = True
        self._update_title()
        self._statusbar.showMessage(
            f"기존 번역 {len(updates):,}건 적용 완료", 5000,
        )
        QMessageBox.information(
            self, "완료",
            f"기존 번역 {len(updates):,}건이 Target에 적용되었습니다.",
        )
