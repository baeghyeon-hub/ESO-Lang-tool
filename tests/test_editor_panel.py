"""ui/editor_panel.py 단위 테스트 — 단일/다중 선택 전환 커밋 검증."""

import pytest
from PyQt6.QtWidgets import QApplication

from ui.editor_panel import EditorPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def panel(qapp):
    widget = EditorPanel()
    yield widget
    widget.deleteLater()


class TestEditorPanelMultiCommit:
    def test_switching_to_single_autocommits_pending_multi_edit(self, panel):
        calls: list[tuple[list[int], str]] = []
        panel.batch_edit_committed.connect(
            lambda rowids, text: calls.append((list(rowids), text))
        )

        panel.set_multi_records([
            (1, "Alpha", ""),
            (2, "Beta", ""),
        ])
        panel._target_edit.setPlainText("공통 번역")

        panel.set_record(3, "Gamma", "")

        assert calls == [([1, 2], "공통 번역")]

    def test_switching_selection_does_not_apply_blank_for_mixed_targets(self, panel):
        calls: list[tuple[list[int], str]] = []
        panel.batch_edit_committed.connect(
            lambda rowids, text: calls.append((list(rowids), text))
        )

        panel.set_multi_records([
            (1, "Alpha", "번역 A"),
            (2, "Beta", "번역 B"),
        ])

        panel.set_record(3, "Gamma", "")

        assert calls == []
