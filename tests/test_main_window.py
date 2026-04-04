"""Tests for ui.main_window."""

from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication

from core.db import LangDatabase
from ui.main_window import MainWindow
from ui.record_table import RecordTableModel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def window(qapp):
    widget = MainWindow()
    yield widget
    widget._db = None
    widget.close()


class TestActionSlots:
    def test_save_file_accepts_qaction_checked_arg(self, window, loaded_db, monkeypatch):
        saved_paths: list[str] = []
        window._db = loaded_db
        window._save_filepath = "out.lang"
        monkeypatch.setattr(window, "_do_save", lambda path: saved_paths.append(path))

        window._save_file(True)

        assert saved_paths == ["out.lang"]

    def test_do_undo_accepts_qaction_checked_arg(self, window):
        window._model = object()
        window._undo_mgr = SimpleNamespace(undo=lambda: None)

        window._do_undo(True)

    def test_do_redo_accepts_qaction_checked_arg(self, window):
        window._model = object()
        window._undo_mgr = SimpleNamespace(redo=lambda: None)

        window._do_redo(True)


class TestSelectionReset:
    def test_group_filter_change_clears_stale_editor_panel(self, window, loaded_db):
        window._db = loaded_db
        window._model = RecordTableModel(loaded_db)
        window._table_view.setModel(window._model)

        window._editor_panel.set_record(1, "Hello World", "")
        assert window._editor_panel.isEnabled()

        window._on_group_selected(100)

        assert not window._editor_panel.isEnabled()


class TestSourceLookupSummary:
    def test_lookup_summary_merges_current_and_reference_variants(
        self,
        window,
        loaded_db,
        monkeypatch,
    ):
        loaded_db.update_target(1, "안녕하세요")
        window._db = loaded_db

        reference_db = LangDatabase()
        reference_db.insert_records([
            (100, 0, 1, "안녕 세상"),
            (100, 0, 2, "트리뷰트 캠페인"),
            (100, 0, 3, "안녕 세상"),
            (100, 1, 1, "IDLE"),
            (200, 0, 1, "드래곤"),
            (200, 0, 2, "화염 숨결"),
            (200, 0, 3, ""),
            (300, 0, 1, "가브리엘 베넬레^F"),
            (300, 0, 2, "우그론 그로-투모그^M"),
            (300, 0, 3, "테스트 NPC^N"),
        ])
        monkeypatch.setattr(window, "_ensure_reference_db", lambda: reference_db)

        try:
            summary = window._build_source_lookup_summary_v2("Hello World")
        finally:
            reference_db.close()

        assert summary["current_match_rows"] == 1
        assert summary["reference_match_rows"] == 2
        assert [variant["target"] for variant in summary["variants"]] == [
            "안녕 세상",
            "안녕하세요",
        ]
        assert summary["variants"][0]["origin_label"] == "기존 KR 패치"

    def test_lookup_summary_falls_back_to_same_text_reference_variant(
        self,
        window,
        loaded_db,
        monkeypatch,
    ):
        window._db = loaded_db

        reference_db = LangDatabase()
        reference_db.insert_records([
            (100, 0, 1, "Hello World"),
            (100, 0, 2, "트리뷰트 캠페인"),
            (100, 0, 3, "Hello World"),
            (100, 1, 1, "IDLE"),
            (200, 0, 1, "Dragon"),
            (200, 0, 2, "Fire Breath"),
            (200, 0, 3, ""),
            (300, 0, 1, "Gabrielle Benele^F"),
            (300, 0, 2, "Ugron gro-Thumog^M"),
            (300, 0, 3, "Test NPC^N"),
        ])
        monkeypatch.setattr(window, "_ensure_reference_db", lambda: reference_db)

        try:
            summary = window._build_source_lookup_summary_v2("Tribute Campaign")
        finally:
            reference_db.close()

        assert summary["reference_match_rows"] == 1
        assert summary["variants"] == [
            {
                "target": "트리뷰트 캠페인",
                "count": 1,
                "origins": ["기존 KR 패치"],
                "origin_label": "기존 KR 패치",
            }
        ]

    def test_lookup_summary_hides_source_text_when_translated_variants_exist(
        self,
        window,
        loaded_db,
        monkeypatch,
    ):
        window._db = loaded_db

        reference_db = LangDatabase()
        reference_db.insert_records([
            (100, 0, 1, "안녕 세상"),
            (100, 0, 2, "트리뷰트 캠페인"),
            (100, 0, 3, "Hello World"),
            (100, 1, 1, "IDLE"),
            (200, 0, 1, "Dragon"),
            (200, 0, 2, "Fire Breath"),
            (200, 0, 3, ""),
            (300, 0, 1, "Gabrielle Benele^F"),
            (300, 0, 2, "Ugron gro-Thumog^M"),
            (300, 0, 3, "Test NPC^N"),
        ])
        monkeypatch.setattr(window, "_ensure_reference_db", lambda: reference_db)

        try:
            summary = window._build_source_lookup_summary_v2("Hello World")
        finally:
            reference_db.close()

        assert summary["reference_match_rows"] == 2
        assert summary["variants"] == [
            {
                "target": "안녕 세상",
                "count": 1,
                "origins": ["기존 KR 패치"],
                "origin_label": "기존 KR 패치",
            }
        ]

    def test_lookup_summary_uses_base_english_group_for_kr_source(
        self,
        window,
        monkeypatch,
    ):
        current_db = LangDatabase()
        current_db.insert_records([
            (90431749, 0, 18, "우그론 그로-투모그"),
            (90431749, 0, 19, "우그론 그로-투모그"),
            (90431749, 0, 20, "우그론 그로-툼목"),
            (90431749, 0, 21, "Ugron gro-Thumog"),
        ])
        base_db = LangDatabase()
        base_db.insert_records([
            (90431749, 0, 18, "Ugron gro-Thumog"),
            (90431749, 0, 19, "Ugron gro-Thumog"),
            (90431749, 0, 20, "Ugron gro-Thumog"),
            (90431749, 0, 21, "Ugron gro-Thumog"),
        ])
        reference_db = LangDatabase()
        reference_db.insert_records([
            (90431749, 0, 18, "우그론 그로-투모그"),
            (90431749, 0, 19, "우그론 그로-투모그"),
            (90431749, 0, 20, "우그론 그로-툼목"),
            (90431749, 0, 21, "Ugron gro-Thumog"),
        ])

        try:
            window._db = current_db
            window._codec_name = "eso_kr_legacy"
            window._model = RecordTableModel(current_db)
            window._table_view.setModel(window._model)
            window._model.set_exact_text_filter("source", "Ugron gro-Thumog")
            window._table_view.selectAll()

            monkeypatch.setattr(window, "_ensure_base_db", lambda: base_db)
            monkeypatch.setattr(window, "_ensure_reference_db", lambda: reference_db)

            summary = window._build_source_lookup_summary_v2("Ugron gro-Thumog")
        finally:
            reference_db.close()
            base_db.close()
            current_db.close()

        assert [variant["target"] for variant in summary["variants"]] == [
            "우그론 그로-투모그",
            "우그론 그로-툼목",
        ]

    def test_apply_source_lookup_translation_selects_same_source_rows(
        self,
        window,
        loaded_db,
    ):
        window._db = loaded_db
        window._model = RecordTableModel(loaded_db)
        window._table_view.setModel(window._model)

        window._apply_source_lookup_translation("Hello World", "안녕하세요")

        assert window._model.rowCount() == 2
        assert window._get_selected_rowids() == [1, 3]
        assert window._editor_panel.isEnabled()


class TestNavigation:
    def test_show_exact_text_pushes_nav_state(self, window, loaded_db):
        window._db = loaded_db
        window._model = RecordTableModel(loaded_db)
        window._table_view.setModel(window._model)

        total_before = window._model.rowCount()
        assert len(window._nav_history) == 0

        window._show_exact_text_matches("source", "Hello World")

        assert len(window._nav_history) == 1
        assert window._model.rowCount() == 2  # filtered
        assert window._nav_back_action.isEnabled()

    def test_nav_back_restores_previous_state(self, window, loaded_db):
        window._db = loaded_db
        window._model = RecordTableModel(loaded_db)
        window._table_view.setModel(window._model)

        total_before = window._model.rowCount()
        window._show_exact_text_matches("source", "Hello World")
        assert window._model.rowCount() < total_before

        window._nav_back()

        assert window._model.rowCount() == total_before
        assert not window._nav_back_action.isEnabled()

    def test_nav_state_captures_filter(self, window, loaded_db):
        window._db = loaded_db
        window._model = RecordTableModel(loaded_db)
        window._table_view.setModel(window._model)

        # Set filter state manually
        window._search_bar._filter_combo.blockSignals(True)
        window._search_bar._filter_combo.setCurrentText("수정됨")
        window._search_bar._filter_combo.blockSignals(False)

        state = window._capture_nav_state()
        assert state.filter_text == "수정됨"
        assert state.focus_field == ""
        assert state.search_text == ""

    def test_multiple_nav_back(self, window, loaded_db):
        window._db = loaded_db
        window._model = RecordTableModel(loaded_db)
        window._table_view.setModel(window._model)

        total = window._model.rowCount()
        window._show_exact_text_matches("source", "Hello World")
        window._show_exact_text_matches("target", "")
        assert len(window._nav_history) == 2

        window._nav_back()
        assert len(window._nav_history) == 1

        window._nav_back()
        assert len(window._nav_history) == 0
        assert window._model.rowCount() == total
