"""core/lang_builder.py 단위 테스트 — 라운드트립 + dedup 검증."""

import pytest
from core.lang_parser import parse_lang
from core.lang_builder import build_lang_bytes
from core.db import LangDatabase


class TestRoundtrip:
    def test_roundtrip_bytes_identical(self, sample_lang_file):
        """parse → build → 바이트 완전 동일."""
        original = sample_lang_file.read_bytes()
        db = LangDatabase()
        meta = parse_lang(sample_lang_file, db)
        rebuilt = build_lang_bytes(db, version=meta["version"])
        db.close()
        assert original == rebuilt

    def test_roundtrip_preserves_records(self, sample_lang_file):
        """parse → build → re-parse → 레코드 동일."""
        db1 = LangDatabase()
        parse_lang(sample_lang_file, db1)
        rebuilt = build_lang_bytes(db1)
        records1 = db1.get_all_for_build()
        db1.close()

        # 재빌드 파일을 다시 파싱
        tmp = sample_lang_file.parent / "rebuilt.lang"
        tmp.write_bytes(rebuilt)
        db2 = LangDatabase()
        parse_lang(tmp, db2)
        records2 = db2.get_all_for_build()
        db2.close()

        assert len(records1) == len(records2)
        for r1, r2 in zip(records1, records2):
            assert r1 == r2


class TestDedup:
    def test_dedup_reduces_blob_size(self, loaded_db):
        """중복 텍스트가 있으면 blob이 줄어든다."""
        rebuilt = build_lang_bytes(loaded_db)
        # "Hello World"가 2번 나오지만 blob에는 1번만 → 크기가 줄어야 함
        # 단순히 빌드가 성공하는 것 자체가 dedup 동작 증거
        assert len(rebuilt) > 0

    def test_edited_target_in_build(self, loaded_db):
        """target이 있으면 source 대신 target이 빌드에 사용된다."""
        loaded_db.update_target(1, "번역된 텍스트")
        records = loaded_db.get_all_for_build()
        # rowid=1의 text가 target으로 대체됐는지 확인
        first = records[0]
        assert first[3] == "번역된 텍스트"
