"""core/undo.py 단위 테스트 — Undo/Redo 검증."""

import pytest
from core.undo import UndoManager, UndoEntry


class TestSingleEdit:
    def test_edit_and_undo(self, loaded_db):
        mgr = UndoManager(loaded_db)
        assert not mgr.can_undo

        mgr.edit_single(1, "번역A")
        assert mgr.can_undo
        assert loaded_db.get_record_by_rowid(1)[4] == "번역A"

        mgr.undo()
        assert loaded_db.get_record_by_rowid(1)[4] == ""
        assert not mgr.can_undo

    def test_edit_and_redo(self, loaded_db):
        mgr = UndoManager(loaded_db)
        mgr.edit_single(1, "번역A")
        mgr.undo()
        assert mgr.can_redo

        mgr.redo()
        assert loaded_db.get_record_by_rowid(1)[4] == "번역A"
        assert not mgr.can_redo

    def test_no_change_returns_false(self, loaded_db):
        mgr = UndoManager(loaded_db)
        mgr.edit_single(1, "X")
        result = mgr.edit_single(1, "X")  # 같은 값
        assert result is False
        assert len(mgr._undo_stack) == 1  # 추가 안 됨

    def test_new_edit_clears_redo(self, loaded_db):
        mgr = UndoManager(loaded_db)
        mgr.edit_single(1, "A")
        mgr.undo()
        assert mgr.can_redo

        mgr.edit_single(1, "B")  # 새 편집 → redo 스택 삭제
        assert not mgr.can_redo


class TestBatchEdit:
    def test_batch_and_undo(self, loaded_db):
        mgr = UndoManager(loaded_db)
        count = mgr.edit_batch([(1, "번역1"), (2, "번역2"), (3, "번역3")])
        assert count == 3
        assert loaded_db.get_record_by_rowid(1)[4] == "번역1"
        assert loaded_db.get_record_by_rowid(2)[4] == "번역2"

        mgr.undo()
        assert loaded_db.get_record_by_rowid(1)[4] == ""
        assert loaded_db.get_record_by_rowid(2)[4] == ""

    def test_batch_undo_is_single_step(self, loaded_db):
        mgr = UndoManager(loaded_db)
        mgr.edit_batch([(1, "A"), (2, "B"), (3, "C")])
        assert len(mgr._undo_stack) == 1  # 3건이지만 1단계


class TestLimits:
    def test_max_steps(self, loaded_db):
        mgr = UndoManager(loaded_db, max_steps=3)
        for i in range(5):
            mgr.edit_single(1, f"v{i}")

        assert len(mgr._undo_stack) <= 3

    def test_undo_text(self, loaded_db):
        mgr = UndoManager(loaded_db)
        mgr.edit_single(1, "X", description="테스트 편집")
        assert mgr.undo_text == "테스트 편집"

    def test_clear(self, loaded_db):
        mgr = UndoManager(loaded_db)
        mgr.edit_single(1, "X")
        mgr.clear()
        assert not mgr.can_undo
        assert not mgr.can_redo


class TestMultipleUndoRedo:
    def test_multiple_undo_redo(self, loaded_db):
        mgr = UndoManager(loaded_db)
        mgr.edit_single(1, "A")
        mgr.edit_single(1, "B")
        mgr.edit_single(1, "C")

        assert loaded_db.get_record_by_rowid(1)[4] == "C"

        mgr.undo()
        assert loaded_db.get_record_by_rowid(1)[4] == "B"

        mgr.undo()
        assert loaded_db.get_record_by_rowid(1)[4] == "A"

        mgr.redo()
        assert loaded_db.get_record_by_rowid(1)[4] == "B"

        mgr.redo()
        assert loaded_db.get_record_by_rowid(1)[4] == "C"

    def test_redo_keeps_remaining_redo_history(self, loaded_db):
        mgr = UndoManager(loaded_db)
        mgr.edit_single(1, "A")
        mgr.edit_single(1, "B")
        mgr.edit_single(1, "C")

        mgr.undo()
        mgr.undo()

        mgr.redo()
        assert loaded_db.get_record_by_rowid(1)[4] == "B"
        assert mgr.can_redo

        mgr.redo()
        assert loaded_db.get_record_by_rowid(1)[4] == "C"
        assert not mgr.can_redo
