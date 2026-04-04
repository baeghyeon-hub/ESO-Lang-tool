"""
Phase 1 통합 테스트: 파싱 + 빌드 + 라운드트립 + FTS5

en.lang 실제 파일 기반 — 파일 없으면 자동 스킵.
직접 실행도 가능: python tests/test_parser.py
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import LangDatabase
from core.lang_parser import parse_lang
from core.lang_builder import build_lang_bytes

LANG_FILE = Path(__file__).resolve().parent.parent / "en.lang"

_skip = pytest.mark.skipif(
    not LANG_FILE.exists(),
    reason=f"{LANG_FILE.name} 파일 없음 — 실파일 통합 테스트 스킵",
)


@pytest.fixture(scope="module")
def en_db():
    """en.lang 파싱 → DB + 메타 (모듈 단위 공유)."""
    db = LangDatabase()
    meta = parse_lang(LANG_FILE, db)
    yield db, meta
    db.close()


@pytest.fixture(scope="module")
def en_db_with_fts(en_db):
    """en_db에 FTS5 빌드 완료."""
    db, meta = en_db
    db.build_fts()
    return db, meta


@_skip
class TestEnLangParse:
    def test_record_count(self, en_db):
        db, meta = en_db
        assert db.record_count() == meta["record_count"]

    def test_group_count(self, en_db):
        db, _ = en_db
        groups = db.get_group_ids()
        assert len(groups) == 449

    def test_sample_record(self, en_db):
        db, _ = en_db
        rec = db.get_record_by_rowid(1)
        assert rec is not None
        assert len(rec[3]) > 0  # source 비어있지 않음


@_skip
class TestEnLangFts:
    def test_fts_search(self, en_db_with_fts):
        db, _ = en_db_with_fts
        results = db.search_fts("Tribute")
        assert len(results) > 0

    def test_fts_vs_like(self, en_db_with_fts):
        db, _ = en_db_with_fts
        fts = db.search_fts("dragon")
        like = db.search_like("dragon")
        assert len(fts) > 0
        assert len(like) > 0


@_skip
class TestEnLangRoundtrip:
    def test_bytes_identical(self, en_db):
        db, meta = en_db
        original = LANG_FILE.read_bytes()
        rebuilt = build_lang_bytes(db, version=meta["version"])
        assert original == rebuilt


@_skip
class TestEnLangEdit:
    def test_update_and_revert(self, en_db):
        db, _ = en_db
        old = db.update_target(1, "테스트 번역")
        assert old is not None or old == ""
        rec = db.get_record_by_rowid(1)
        assert rec[4] == "테스트 번역"

        # 원복
        db.update_target(1, "")

    def test_duplicate_returns_none(self, en_db):
        db, _ = en_db
        db.update_target(1, "TEST")
        result = db.update_target(1, "TEST")
        assert result is None
        db.update_target(1, "")  # 원복

    def test_batch_update(self, en_db):
        db, _ = en_db
        diffs = db.batch_update_targets([(1, "A"), (2, "B"), (3, "C")])
        assert len(diffs) >= 1
        # 원복
        for rowid, old_val, _ in diffs:
            db.update_target(rowid, old_val)


@_skip
class TestEnLangStats:
    def test_initial_stats(self, en_db):
        db, _ = en_db
        stats = db.get_stats()
        assert stats["total"] > 1_000_000
        assert stats["progress"] == 0.0


# ── 직접 실행용 ──

if __name__ == "__main__":
    if not LANG_FILE.exists():
        print(f"ERROR: {LANG_FILE} 파일이 없습니다.")
        sys.exit(1)

    total_start = time.perf_counter()

    db = LangDatabase()

    # 파싱
    print("=" * 60)
    print("  TEST 1: 파싱 (.lang → DB)")
    print("=" * 60)
    t0 = time.perf_counter()
    meta = parse_lang(LANG_FILE, db)
    print(f"  레코드: {meta['record_count']:,}건, 시간: {time.perf_counter()-t0:.2f}s")

    # FTS5
    print("=" * 60)
    print("  TEST 2: FTS5 검색")
    print("=" * 60)
    t0 = time.perf_counter()
    db.build_fts()
    print(f"  FTS5 빌드: {time.perf_counter()-t0:.2f}s")
    results = db.search_fts("Tribute")
    print(f"  'Tribute' 검색: {len(results)}건")

    # 라운드트립
    print("=" * 60)
    print("  TEST 3: 라운드트립")
    print("=" * 60)
    original = LANG_FILE.read_bytes()
    t0 = time.perf_counter()
    rebuilt = build_lang_bytes(db, version=meta["version"])
    print(f"  빌드: {time.perf_counter()-t0:.2f}s")
    print(f"  바이트 동일: {original == rebuilt}")

    # 편집
    print("=" * 60)
    print("  TEST 4: 편집 API")
    print("=" * 60)
    db.update_target(1, "테스트")
    rec = db.get_record_by_rowid(1)
    print(f"  편집 결과: {rec[4]}")
    db.update_target(1, "")

    total = time.perf_counter() - total_start
    print(f"\n  총 소요: {total:.2f}s")
    db.close()
