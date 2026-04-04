"""ui/dialogs.py 단위 테스트."""

import pytest
from PyQt6.QtWidgets import QApplication

from ui.dialogs import SourceTranslationLookupDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestSourceTranslationLookupDialog:
    def test_dialog_handles_empty_variants(self, qapp):
        summary = {
            "source_text": "Hello World",
            "total_rows": 2,
            "translated_rows": 0,
            "untranslated_rows": 2,
            "variant_count": 0,
            "variants": [],
        }

        dialog = SourceTranslationLookupDialog("Hello World", summary)

        assert dialog.selected_translation() == ""
        dialog.deleteLater()

    def test_dialog_prefills_first_variant_selection(self, qapp):
        summary = {
            "source_text": "Hello World",
            "total_rows": 3,
            "translated_rows": 2,
            "untranslated_rows": 1,
            "variant_count": 2,
            "variants": [
                {"target": "안녕", "count": 1},
                {"target": "여보세요", "count": 1},
            ],
        }

        dialog = SourceTranslationLookupDialog("Hello World", summary)

        assert dialog.selected_translation() == "안녕"
        dialog.deleteLater()
