"""RecordTableModel 필터 조합 단위 테스트 — GUI 없이 모델 로직만 검증."""

import pytest
from PyQt6.QtCore import QCoreApplication
from core.db import LangDatabase
from core.lang_parser import parse_lang
from ui.record_table import RecordTableModel
from tests.conftest import SAMPLE_RECORDS


@pytest.fixture
def model(loaded_db):
    """RecordTableModel (Qt 없이 로직만 테스트)."""
    # Qt 위젯 없이 모델 내부 로직만 검증하기 위해
    # 모델 대신 DB 쿼리를 직접 테스트
    return loaded_db


@pytest.fixture(scope="module")
def qcoreapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


class TestFilterCombination:
    """검색 + 상태 필터 + ID 필터가 AND로 조합되는지 검증."""

    def test_id_filter_only(self, model):
        cnt = model.count_by_filter(id_filter=100)
        assert cnt == 4

    def test_status_filter_untranslated(self, model):
        cnt = model.count_by_filter(where_clause="target = ''")
        assert cnt == len(SAMPLE_RECORDS)  # 초기엔 전부 미번역

    def test_status_filter_after_edit(self, model):
        model.update_target(1, "번역")
        cnt_translated = model.count_by_filter(where_clause="target != ''")
        assert cnt_translated == 1
        cnt_modified = model.count_by_filter(where_clause="modified = 1")
        assert cnt_modified == 1

    def test_id_plus_status_filter(self, model):
        model.update_target(1, "번역")  # rowid=1은 id=100
        cnt = model.count_by_filter(id_filter=100, where_clause="target != ''")
        assert cnt == 1
        cnt = model.count_by_filter(id_filter=200, where_clause="target != ''")
        assert cnt == 0

    def test_search_where_zero_results(self, model):
        """WHERE 0 → 0건."""
        cnt = model.count_by_filter(where_clause="0")
        assert cnt == 0

    def test_combined_search_and_status(self, model):
        """search_where + status_where AND 조합."""
        model.update_target(1, "번역")
        # source에 "Hello"가 있는 것 AND 번역된 것
        cnt = model.count_by_filter(
            where_clause="source LIKE '%Hello%' AND target != ''"
        )
        assert cnt == 1

    def test_empty_source_filter(self, model):
        """빈 source 레코드 필터."""
        cnt = model.count_by_filter(where_clause="source = ''")
        assert cnt == 1  # id=200, idx=3


class TestKrLangFilter:
    """kr.lang 코덱 인식 필터 — has_korean() SQLite 함수 검증."""

    @pytest.fixture
    def kr_db(self):
        """kr.lang 스타일 DB: source에 한글/영어 혼재."""
        db = LangDatabase()
        db.insert_records([
            (100, 0, 1, "트리뷰트 캠페인"),       # 한글 = 기번역
            (100, 0, 2, "Hello World"),            # 영어 = 미번역
            (100, 0, 3, "드래곤"),                 # 한글 = 기번역
            (200, 0, 1, "Fire Breath"),            # 영어 = 미번역
            (200, 0, 2, "불의 숨결"),              # 한글 = 기번역
        ])
        yield db
        db.close()

    def test_untranslated_filter(self, kr_db):
        """미번역만: source에 한글 없고 target 비어있는 레코드."""
        cnt = kr_db.count_by_filter(
            where_clause="target = '' AND NOT has_korean(source)"
        )
        assert cnt == 2  # Hello World, Fire Breath

    def test_translated_filter(self, kr_db):
        """번역됨: source에 한글 있거나 target 채워진 레코드."""
        cnt = kr_db.count_by_filter(
            where_clause="(has_korean(source) OR target != '')"
        )
        assert cnt == 3  # 트리뷰트, 드래곤, 불의 숨결

    def test_translated_after_edit(self, kr_db):
        """사용자가 편집하면 번역됨에 포함."""
        kr_db.update_target(2, "안녕 세계")  # Hello World 번역
        cnt = kr_db.count_by_filter(
            where_clause="(has_korean(source) OR target != '')"
        )
        assert cnt == 4  # 기번역 3 + 사용자 편집 1

    def test_modified_filter(self, kr_db):
        """수정됨: modified = 1 (이번 세션 편집만)."""
        kr_db.update_target(2, "안녕 세계")
        cnt = kr_db.count_by_filter(where_clause="modified = 1")
        assert cnt == 1

    def test_untranslated_excludes_edited(self, kr_db):
        """편집된 레코드는 미번역에서 제외."""
        kr_db.update_target(2, "안녕 세계")  # Hello World → 번역됨
        cnt = kr_db.count_by_filter(
            where_clause="target = '' AND NOT has_korean(source)"
        )
        assert cnt == 1  # Fire Breath만 남음


class TestReloadSafety:
    """재로드 시 DB가 깨끗하게 초기화되는지 검증."""

    def test_fresh_db_after_close(self):
        db = LangDatabase()
        db.insert_records([(1, 0, 1, "test")])
        assert db.record_count() == 1
        db.close()

        db2 = LangDatabase()
        assert db2.record_count() == 0
        db2.close()

    def test_reload_same_file(self, sample_lang_file):
        """같은 파일을 두 번 로드해도 레코드 수가 동일."""
        db1 = LangDatabase()
        parse_lang(sample_lang_file, db1)
        cnt1 = db1.record_count()
        db1.close()

        db2 = LangDatabase()
        parse_lang(sample_lang_file, db2)
        cnt2 = db2.record_count()
        db2.close()

        assert cnt1 == cnt2 == len(SAMPLE_RECORDS)


class TestExactFilterReset:
    """숨은 exact-match 필터가 상태 탭 전환 시 남지 않는지 검증."""

    def test_status_filter_clears_exact_text_focus(self, loaded_db, qcoreapp):
        loaded_db.update_target(1, "번역")

        model = RecordTableModel(loaded_db)
        model.set_exact_text_filter("source", "Hello World")
        assert model.rowCount() == 2

        model.set_status_filter("번역됨")
        assert model.rowCount() == 1

        model.set_status_filter("전체")
        assert model.rowCount() == len(SAMPLE_RECORDS)
