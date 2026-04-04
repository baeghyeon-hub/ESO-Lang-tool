"""
기존 번역 레퍼런스 크로스 매칭 테스트.

_build_reference_map, _find_ref_translatable_rowids 로직을
DB 레벨에서 직접 테스트.
"""

import pytest
from core.db import LangDatabase, _has_korean


def _make_db(records: list[tuple[int, int, int, str]]) -> LangDatabase:
    db = LangDatabase()
    db.insert_records(records)
    return db


class TestBuildReferenceMap:
    """레퍼런스 맵 빌드 테스트."""

    def test_basic_map(self):
        ref_db = _make_db([
            (1, 0, 0, "Hello"),
            (2, 0, 0, "World"),
        ])
        rows = ref_db._conn.execute(
            "SELECT id, unknown, idx, source FROM records"
        ).fetchall()
        ref_map = {(r[0], r[1], r[2]): r[3] for r in rows}
        assert ref_map == {(1, 0, 0): "Hello", (2, 0, 0): "World"}
        ref_db.close()


def _is_translatable(source, ref_text):
    """일괄 적용 조건 (main_window 로직과 동일)."""
    return (
        ref_text
        and ref_text != source
        and not _has_korean(source)
        and _has_korean(ref_text)
    )


class TestFindRefTranslatable:
    """레퍼런스 번역이 있는 미번역 rowid 찾기."""

    def test_finds_translatable(self):
        """현재 DB에 영어, 레퍼런스에 한글 → rowid 반환."""
        cur_db = _make_db([
            (1, 0, 0, "Hello"),
            (2, 0, 0, "World"),
            (3, 0, 0, "Sword"),
        ])
        ref_map = {
            (1, 0, 0): "안녕",     # 영→한 → 번역 있음 ✓
            (2, 0, 0): "World",    # 같은 텍스트 → 번역 없음
            (3, 0, 0): "검",       # 영→한 → 번역 있음 ✓
        }

        cur_rows = cur_db._conn.execute(
            "SELECT rowid, id, unknown, idx, source "
            "FROM records WHERE target = ''"
        ).fetchall()

        result = []
        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if _is_translatable(source, ref_text):
                result.append(rowid)

        assert len(result) == 2  # Hello→안녕, Sword→검
        cur_db.close()

    def test_skips_already_translated(self):
        """이미 target이 있는 레코드는 무시."""
        cur_db = _make_db([
            (1, 0, 0, "Hello"),
        ])
        cur_db._conn.execute(
            "UPDATE records SET target = '기존번역' WHERE id = 1"
        )
        cur_db._conn.commit()

        ref_map = {(1, 0, 0): "안녕"}

        cur_rows = cur_db._conn.execute(
            "SELECT rowid, id, unknown, idx, source "
            "FROM records WHERE target = ''"
        ).fetchall()

        result = []
        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if _is_translatable(source, ref_text):
                result.append(rowid)

        assert len(result) == 0
        cur_db.close()

    def test_no_match_in_reference(self):
        """레퍼런스에 해당 키가 없으면 건너뜀."""
        cur_db = _make_db([
            (99, 0, 0, "New Item"),
        ])
        ref_map = {(1, 0, 0): "안녕"}

        cur_rows = cur_db._conn.execute(
            "SELECT rowid, id, unknown, idx, source "
            "FROM records WHERE target = ''"
        ).fetchall()

        result = []
        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if _is_translatable(source, ref_text):
                result.append(rowid)

        assert len(result) == 0
        cur_db.close()

    def test_skips_korean_source_with_english_ref(self):
        """핵심 회귀: 한글 source + 영어 ref → 적용하면 안 됨."""
        cur_db = _make_db([
            (1, 0, 0, "벌레 교단 강령술사^m"),   # 이미 한글 번역된 source
            (2, 0, 0, "Worm Cult Archer^m"),    # 영어 미번역
        ])
        ref_map = {
            (1, 0, 0): "Worm Cult Necromancer^m",  # 영어 (구 한패 미번역)
            (2, 0, 0): "벌레 교단 궁수^m",           # 한글 번역 있음
        }

        cur_rows = cur_db._conn.execute(
            "SELECT rowid, id, unknown, idx, source "
            "FROM records WHERE target = ''"
        ).fetchall()

        result = []
        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if _is_translatable(source, ref_text):
                result.append(rowid)

        # 1번: 한글 source → 영어 ref → 건너뜀
        # 2번: 영어 source → 한글 ref → 적용 ✓
        assert len(result) == 1
        cur_db.close()

    def test_skips_english_ref_without_korean(self):
        """레퍼런스도 영어이면 적용 안 함 (번역이 아님)."""
        cur_db = _make_db([
            (1, 0, 0, "Hello World"),
        ])
        ref_map = {
            (1, 0, 0): "Hello World v2",  # 다르지만 영어 → 번역 아님
        }

        cur_rows = cur_db._conn.execute(
            "SELECT rowid, id, unknown, idx, source "
            "FROM records WHERE target = ''"
        ).fetchall()

        result = []
        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if _is_translatable(source, ref_text):
                result.append(rowid)

        assert len(result) == 0
        cur_db.close()


class TestBatchApply:
    """일괄 적용 로직 테스트."""

    def test_batch_update(self):
        """미번역(영어) 레코드에 한글 번역을 일괄 적용."""
        cur_db = _make_db([
            (1, 0, 0, "Hello"),
            (2, 0, 0, "World"),
            (3, 0, 0, "Sword"),
        ])
        ref_map = {
            (1, 0, 0): "안녕",
            (2, 0, 0): "세계",
            (3, 0, 0): "Sword",  # 같으면 적용 안 함
        }

        cur_rows = cur_db._conn.execute(
            "SELECT rowid, id, unknown, idx, source "
            "FROM records WHERE target = ''"
        ).fetchall()

        updates = []
        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if _is_translatable(source, ref_text):
                updates.append((ref_text, rowid))

        cur_db._conn.executemany(
            "UPDATE records SET target = ?, modified = 1 WHERE rowid = ?",
            updates,
        )
        cur_db._conn.commit()

        rows = cur_db._conn.execute(
            "SELECT id, target, modified FROM records ORDER BY id"
        ).fetchall()
        assert rows[0] == (1, "안녕", 1)
        assert rows[1] == (2, "세계", 1)
        assert rows[2] == (3, "", 0)  # 같은 텍스트라 적용 안 됨
        cur_db.close()

    def test_does_not_overwrite_existing_target(self):
        """기존 target이 있는 레코드는 건드리지 않음."""
        cur_db = _make_db([
            (1, 0, 0, "Hello"),
            (2, 0, 0, "World"),
        ])
        cur_db._conn.execute(
            "UPDATE records SET target = '수동번역' WHERE id = 1"
        )
        cur_db._conn.commit()

        ref_map = {
            (1, 0, 0): "안녕",
            (2, 0, 0): "세계",
        }

        cur_rows = cur_db._conn.execute(
            "SELECT rowid, id, unknown, idx, source "
            "FROM records WHERE target = ''"
        ).fetchall()

        updates = []
        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if _is_translatable(source, ref_text):
                updates.append((ref_text, rowid))

        assert len(updates) == 1  # World만

        cur_db._conn.executemany(
            "UPDATE records SET target = ?, modified = 1 WHERE rowid = ?",
            updates,
        )
        cur_db._conn.commit()

        rows = cur_db._conn.execute(
            "SELECT id, target FROM records ORDER BY id"
        ).fetchall()
        assert rows[0] == (1, "수동번역")  # 기존 유지
        assert rows[1] == (2, "세계")      # 새로 적용
        cur_db.close()

    def test_does_not_reverse_apply_english_to_korean_source(self):
        """핵심 회귀: 한글 source에 영어 ref를 적용하면 안 됨."""
        cur_db = _make_db([
            (1, 0, 0, "벌레 교단 강령술사^m"),
            (2, 0, 0, "벌레 교단 강령술사^f"),
            (3, 0, 0, "Worm Cult Archer^m"),
        ])
        ref_map = {
            (1, 0, 0): "Worm Cult Necromancer^m",  # 영어 → 적용 안 함
            (2, 0, 0): "Worm Cult Necromancer^f",  # 영어 → 적용 안 함
            (3, 0, 0): "벌레 교단 궁수^m",           # 한글 → 적용 ✓
        }

        cur_rows = cur_db._conn.execute(
            "SELECT rowid, id, unknown, idx, source "
            "FROM records WHERE target = ''"
        ).fetchall()

        updates = []
        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if _is_translatable(source, ref_text):
                updates.append((ref_text, rowid))

        cur_db._conn.executemany(
            "UPDATE records SET target = ?, modified = 1 WHERE rowid = ?",
            updates,
        )
        cur_db._conn.commit()

        rows = cur_db._conn.execute(
            "SELECT id, source, target, modified FROM records ORDER BY id"
        ).fetchall()
        # 1, 2: 한글 source → 영어 ref → 적용 안 됨
        assert rows[0] == (1, "벌레 교단 강령술사^m", "", 0)
        assert rows[1] == (2, "벌레 교단 강령술사^f", "", 0)
        # 3: 영어 source → 한글 ref → 적용됨
        assert rows[2] == (3, "Worm Cult Archer^m", "벌레 교단 궁수^m", 1)
        cur_db.close()


class TestSourceTextMatching:
    """source text 기반 매칭 테스트 (키가 달라도 같은 원문이면 번역 매칭)."""

    def test_finds_translation_by_source_text(self):
        """키가 다르지만 같은 source text를 가진 레코드에서 번역 발견."""
        # 현재 DB: id=99 "Drodarmathra^m" 미번역
        cur_db = _make_db([
            (99, 0, 0, "Drodarmathra^m"),
        ])
        # 레퍼런스 DB: id=1 "드로다르마트라^m" (키가 다름)
        ref_db = _make_db([
            (1, 0, 0, "드로다르마트라^m"),
        ])
        # en.lang DB: id=1 "Drodarmathra^m" (같은 원문)
        en_db = _make_db([
            (1, 0, 0, "Drodarmathra^m"),
        ])

        # 키 기반 ref_map
        ref_map = {(1, 0, 0): "드로다르마트라^m"}

        # 1단계: 키 매칭 실패 (id=99 vs id=1)
        cur_rows = cur_db._conn.execute(
            "SELECT rowid, id, unknown, idx, source "
            "FROM records WHERE target = ''"
        ).fetchall()

        key_matched = []
        unmatched = []
        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if ref_text and ref_text != source and not _has_korean(source) and _has_korean(ref_text):
                key_matched.append(rowid)
            elif source and not _has_korean(source):
                unmatched.append((rowid, source))

        assert len(key_matched) == 0  # 키 매칭 실패
        assert len(unmatched) == 1    # 미매칭 1건

        # 2단계: en.lang 기반 source text 매핑
        base_rows = en_db._conn.execute(
            "SELECT id, unknown, idx, source FROM records"
        ).fetchall()
        base_map = {(r[0], r[1], r[2]): r[3] for r in base_rows}

        en_to_kr = {}
        for key, ref_text in ref_map.items():
            if _has_korean(ref_text):
                en_source = base_map.get(key)
                if en_source and not _has_korean(en_source) and en_source != ref_text:
                    en_to_kr.setdefault(en_source, ref_text)

        assert en_to_kr == {"Drodarmathra^m": "드로다르마트라^m"}

        # source text 매칭으로 번역 찾기
        text_matched = []
        for rowid, source in unmatched:
            kr_text = en_to_kr.get(source)
            if kr_text and kr_text != source:
                text_matched.append((kr_text, rowid))

        assert len(text_matched) == 1
        assert text_matched[0][0] == "드로다르마트라^m"

        cur_db.close()
        ref_db.close()
        en_db.close()

    def test_key_match_takes_priority(self):
        """키 매칭과 source text 매칭이 둘 다 가능하면 키 매칭 우선."""
        cur_db = _make_db([
            (1, 0, 0, "Hello"),
        ])
        ref_map = {
            (1, 0, 0): "안녕하세요",  # 키 매칭 가능
        }

        cur_rows = cur_db._conn.execute(
            "SELECT rowid, id, unknown, idx, source "
            "FROM records WHERE target = ''"
        ).fetchall()

        key_matched = []
        unmatched = []
        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if ref_text and ref_text != source and not _has_korean(source) and _has_korean(ref_text):
                key_matched.append(rowid)
            elif source and not _has_korean(source):
                unmatched.append((rowid, source))

        assert len(key_matched) == 1  # 키 매칭 성공
        assert len(unmatched) == 0    # unmatched에 안 들어감
        cur_db.close()

    def test_source_text_match_from_current_db(self):
        """현재 DB에 이미 번역된 같은 source가 있으면 그것도 활용."""
        cur_db = _make_db([
            (1, 0, 0, "Sword"),
            (2, 0, 0, "Sword"),  # 같은 source, 다른 id
        ])
        # id=1만 이미 번역됨
        cur_db._conn.execute(
            "UPDATE records SET target = '검' WHERE id = 1"
        )
        cur_db._conn.commit()

        ref_map = {}  # 레퍼런스에는 없음

        # 미번역 행
        cur_rows = cur_db._conn.execute(
            "SELECT rowid, id, unknown, idx, source "
            "FROM records WHERE target = ''"
        ).fetchall()

        unmatched = []
        for rowid, rid, unk, idx, source in cur_rows:
            ref_text = ref_map.get((rid, unk, idx))
            if not (ref_text and ref_text != source
                    and not _has_korean(source) and _has_korean(ref_text)):
                if source and not _has_korean(source):
                    unmatched.append((rowid, source))

        # 현재 DB의 번역된 source→target 맵
        translated = cur_db._conn.execute(
            "SELECT DISTINCT source, target FROM records "
            "WHERE target != '' AND target != source"
        ).fetchall()
        en_to_kr = {}
        for src, tgt in translated:
            if not _has_korean(src) and _has_korean(tgt):
                en_to_kr.setdefault(src, tgt)

        assert en_to_kr == {"Sword": "검"}

        text_matched = []
        for rowid, source in unmatched:
            kr_text = en_to_kr.get(source)
            if kr_text and kr_text != source:
                text_matched.append((kr_text, rowid))

        assert len(text_matched) == 1
        cur_db.close()


class TestRefFilterTempTable:
    """_ref_filter 임시 테이블 기반 필터 테스트."""

    def test_temp_table_filter(self):
        """임시 테이블에 rowid 저장 후 필터 쿼리."""
        db = _make_db([
            (1, 0, 0, "Hello"),
            (2, 0, 0, "World"),
            (3, 0, 0, "Sword"),
        ])

        # rowid 1, 3만 필터
        target_rowids = [1, 3]
        conn = db._conn
        conn.execute(
            "CREATE TEMP TABLE IF NOT EXISTS _ref_filter "
            "(rowid INTEGER PRIMARY KEY)"
        )
        conn.executemany(
            "INSERT INTO _ref_filter VALUES (?)",
            [(r,) for r in target_rowids],
        )

        filtered = conn.execute(
            "SELECT id FROM records "
            "WHERE rowid IN (SELECT rowid FROM _ref_filter) "
            "ORDER BY id"
        ).fetchall()
        assert [r[0] for r in filtered] == [1, 3]
        db.close()
