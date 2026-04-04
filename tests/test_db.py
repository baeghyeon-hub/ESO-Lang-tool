"""core/db.py 단위 테스트 — fixture 기반, pytest 호환."""

import pytest
from tests.conftest import SAMPLE_RECORDS


class TestRecordCount:
    def test_empty_db(self, db):
        assert db.record_count() == 0

    def test_loaded_count(self, loaded_db):
        assert loaded_db.record_count() == len(SAMPLE_RECORDS)


class TestGroupIds:
    def test_groups(self, loaded_db):
        groups = loaded_db.get_group_ids()
        ids = [g[0] for g in groups]
        assert 100 in ids
        assert 200 in ids
        assert 300 in ids
        assert len(groups) == 3

    def test_group_counts(self, loaded_db):
        groups = dict(loaded_db.get_group_ids())
        assert groups[100] == 4  # id=100: 4 records
        assert groups[200] == 3  # id=200: 3 records
        assert groups[300] == 3  # id=300: 3 records


class TestRecordQuery:
    def test_get_by_rowid(self, loaded_db):
        rec = loaded_db.get_record_by_rowid(1)
        assert rec is not None
        assert rec[0] == 100  # id
        assert rec[3] == "Hello World"  # source

    def test_get_source_targets_by_rowids_preserves_input_order(self, loaded_db):
        rows = loaded_db.get_source_targets_by_rowids([5, 1, 2])
        assert rows == [
            (5, "Dragon", ""),
            (1, "Hello World", ""),
            (2, "Tribute Campaign", ""),
        ]

    def test_get_range(self, loaded_db):
        rows = loaded_db.get_records_range(0, 5)
        assert len(rows) == 5

    def test_get_range_with_id_filter(self, loaded_db):
        rows = loaded_db.get_records_range(0, 100, id_filter=200)
        assert len(rows) == 3
        assert all(r[1] == 200 for r in rows)

    def test_count_by_filter(self, loaded_db):
        assert loaded_db.count_by_filter(id_filter=100) == 4
        assert loaded_db.count_by_filter(id_filter=200) == 3
        assert loaded_db.count_by_filter(id_filter=999) == 0

    def test_count_with_where(self, loaded_db):
        cnt = loaded_db.count_by_filter(where_clause="source = ''")
        assert cnt == 1  # 빈 텍스트 1건

    def test_count_with_parameterized_where(self, loaded_db):
        cnt = loaded_db.count_by_filter(
            where_clause="source = ?",
            params=("Hello World",),
        )
        assert cnt == 2


class TestSearch:
    def test_fts_search(self, loaded_db_with_fts):
        results = loaded_db_with_fts.search_fts("Dragon")
        assert len(results) >= 1
        sources = [r[4] for r in results]
        assert "Dragon" in sources

    def test_fts_no_match(self, loaded_db_with_fts):
        results = loaded_db_with_fts.search_fts("ZZZZNOTEXIST")
        assert len(results) == 0

    def test_like_search(self, loaded_db):
        results = loaded_db.search_like("Hello")
        assert len(results) >= 1

    def test_like_no_match(self, loaded_db):
        results = loaded_db.search_like("ZZZZNOTEXIST")
        assert len(results) == 0

    def test_fts_before_build(self, loaded_db):
        # FTS 빌드 전에는 빈 결과
        results = loaded_db.search_fts("Dragon")
        assert results == []

    def test_fts_sync_after_edit(self, loaded_db_with_fts):
        """편집 후 FTS가 동기화되는지 검증."""
        db = loaded_db_with_fts
        # "Dragon"이 검색됨
        assert len(db.search_fts("Dragon")) >= 1
        # "번역완료"는 아직 없음
        assert len(db.search_fts("번역완료")) == 0

        # target을 "번역완료"로 편집
        results = db.search_fts("Dragon")
        rowid = results[0][0]
        db.update_target(rowid, "번역완료")

        # FTS에서 "번역완료"가 바로 검색됨
        new_results = db.search_fts("번역완료")
        assert len(new_results) >= 1
        assert new_results[0][5] == "번역완료"  # target

    def test_fts_sync_batch_edit(self, loaded_db_with_fts):
        """batch 편집 후 FTS 동기화."""
        db = loaded_db_with_fts
        assert len(db.search_fts("배치테스트")) == 0

        db.batch_update_targets([(1, "배치테스트"), (2, "배치테스트2")])

        assert len(db.search_fts("배치테스트")) >= 1


class TestEdit:
    def test_update_target(self, loaded_db):
        old = loaded_db.update_target(1, "안녕하세요")
        assert old is not None  # 이전 값 (빈 문자열)
        rec = loaded_db.get_record_by_rowid(1)
        assert rec[4] == "안녕하세요"  # target
        assert rec[5] == 1  # modified

    def test_update_same_value(self, loaded_db):
        loaded_db.update_target(1, "TEST")
        result = loaded_db.update_target(1, "TEST")
        assert result is None  # 동일 값 → None

    def test_batch_update(self, loaded_db):
        diffs = loaded_db.batch_update_targets([
            (1, "번역1"),
            (2, "번역2"),
            (3, "번역3"),
        ])
        assert len(diffs) == 3

    def test_update_nonexistent(self, loaded_db):
        result = loaded_db.update_target(99999, "X")
        assert result is None

    def test_iter_target_records_skips_empty_targets(self, loaded_db):
        loaded_db.update_target(1, "번역1")
        loaded_db.update_target(2, "번역2")

        rows = list(loaded_db.iter_target_records())

        assert rows == [(1, "번역1"), (2, "번역2")]

    def test_iter_target_records_respects_filters(self, loaded_db):
        loaded_db.update_target(1, "Hello 번역")
        loaded_db.update_target(2, "Tribute 번역")
        loaded_db.update_target(5, "Dragon 번역")

        rows = list(
            loaded_db.iter_target_records(
                id_filter=100,
                where_clause="instr(target, ?) > 0",
                params=("번역",),
            )
        )

        assert rows == [(1, "Hello 번역"), (2, "Tribute 번역")]


class TestStats:
    def test_initial_stats(self, loaded_db):
        stats = loaded_db.get_stats()
        assert stats["total"] == len(SAMPLE_RECORDS)
        assert stats["translated"] == 0
        assert stats["modified"] == 0
        assert stats["progress"] == 0.0

    def test_stats_after_edit(self, loaded_db):
        loaded_db.update_target(1, "번역됨")
        stats = loaded_db.get_stats()
        assert stats["translated"] == 1
        assert stats["modified"] == 1
        assert stats["progress"] > 0

    def test_stats_include_unique_source_progress_and_modified_chars(self, loaded_db):
        loaded_db.update_target(1, "안녕")
        stats = loaded_db.get_stats()

        assert stats["unique_source_total"] == 8
        assert stats["unique_source_translated"] == 1
        assert stats["unique_source_progress"] == pytest.approx(12.5)
        assert stats["modified_chars"] == len("안녕")

    def test_kr_legacy_progress_counts_korean_source_as_translated(self, db):
        db.insert_records([
            (100, 0, 1, "트리뷰트 캠페인"),
            (100, 0, 2, "Hello World"),
            (100, 0, 3, "드래곤"),
            (200, 0, 1, "Fire Breath"),
            (200, 0, 2, "불의 숨결"),
        ])

        stats = db.get_stats(codec_name="eso_kr_legacy")

        assert stats["translated"] == 3
        assert stats["unique_source_total"] == 5
        assert stats["unique_source_translated"] == 3
        assert stats["unique_source_progress"] == pytest.approx(60.0)


class TestSourceTranslationSummary:
    def test_scoped_stats_follow_group_filter(self, loaded_db):
        loaded_db.update_target(1, "안녕")

        stats = loaded_db.get_stats_by_filter(id_filter=100)

        assert stats["total"] == 4
        assert stats["translated"] == 1
        assert stats["unique_source_total"] == 3
        assert stats["unique_source_translated"] == 1

    def test_summary_groups_existing_translations(self, loaded_db):
        loaded_db.update_target(1, "안녕")
        loaded_db.update_target(3, "안녕")
        loaded_db.update_target(2, "공물")

        summary = loaded_db.get_source_translation_summary("Hello World")

        assert summary["source_text"] == "Hello World"
        assert summary["total_rows"] == 2
        assert summary["translated_rows"] == 2
        assert summary["untranslated_rows"] == 0
        assert summary["variant_count"] == 1
        assert summary["variants"] == [{"target": "안녕", "count": 2}]

    def test_summary_returns_empty_variants_when_not_translated(self, loaded_db):
        summary = loaded_db.get_source_translation_summary("Dragon")

        assert summary["total_rows"] == 1
        assert summary["translated_rows"] == 0
        assert summary["untranslated_rows"] == 1
        assert summary["variant_count"] == 0
        assert summary["variants"] == []

    def test_record_keys_and_reference_variants_follow_same_keys(self, loaded_db):
        keys = loaded_db.get_record_keys_by_source("Hello World")

        reference_db = loaded_db.__class__()
        reference_db.insert_records([
            (100, 0, 1, "안녕 세상"),
            (100, 0, 2, "트리뷰트 캠페인"),
            (100, 0, 3, "안녕 세상"),
            (100, 1, 1, "IDLE"),
        ])
        try:
            variants = reference_db.get_source_variants_for_record_keys(
                keys,
                exclude_text="Hello World",
            )
        finally:
            reference_db.close()

        assert variants == [{"target": "안녕 세상", "count": 2}]
