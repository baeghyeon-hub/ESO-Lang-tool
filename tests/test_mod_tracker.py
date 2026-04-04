"""mod_tracker 수정 이력 추적 테스트."""
import json
import pytest

from core.db import LangDatabase
from core.mod_tracker import save_mod_keys, load_mod_keys, get_mod_count, _mod_path


@pytest.fixture
def db():
    d = LangDatabase()
    d.insert_records([
        (100, 0, 0, "Hello"),
        (100, 0, 1, "World"),
        (200, 0, 0, "Sword"),
    ])
    return d


class TestModTracker:
    def test_mod_path(self):
        """사이드카 파일 경로 생성."""
        assert _mod_path("test.lang").name == "test.lang.mod.json"
        assert _mod_path("/foo/bar.lang").name == "bar.lang.mod.json"

    def test_save_and_load_cycle(self, db, tmp_path):
        """수정 → 저장 → 새 DB에 복원."""
        lang_path = tmp_path / "test.lang"
        lang_path.touch()

        # 수정
        db.update_target(1, "안녕")
        db.update_target(2, "세계")

        # 저장
        count = save_mod_keys(db, lang_path)
        assert count == 2
        assert (tmp_path / "test.lang.mod.json").exists()

        # 새 DB에 복원
        db2 = LangDatabase()
        db2.insert_records([
            (100, 0, 0, "Hello"),
            (100, 0, 1, "World"),
            (200, 0, 0, "Sword"),
        ])

        restored = load_mod_keys(db2, lang_path)
        assert restored == 2

        # modified 플래그 확인
        mod_rows = db2._conn.execute(
            "SELECT id, unknown, idx FROM records WHERE modified = 1"
        ).fetchall()
        assert len(mod_rows) == 2
        keys = {(r[0], r[1], r[2]) for r in mod_rows}
        assert (100, 0, 0) in keys
        assert (100, 0, 1) in keys

    def test_merge_keys(self, db, tmp_path):
        """기존 사이드카와 병합."""
        lang_path = tmp_path / "test.lang"
        lang_path.touch()

        # 첫 번째 세션: rowid 1 수정
        db.update_target(1, "안녕")
        save_mod_keys(db, lang_path)

        # 두 번째 세션: 새 DB에서 rowid 3 수정
        db2 = LangDatabase()
        db2.insert_records([
            (100, 0, 0, "Hello"),
            (100, 0, 1, "World"),
            (200, 0, 0, "Sword"),
        ])
        db2.update_target(3, "검")
        count = save_mod_keys(db2, lang_path)
        assert count == 2  # (100,0,0) + (200,0,0) 병합

    def test_no_modifications(self, db, tmp_path):
        """수정 없으면 파일 생성 안 함."""
        lang_path = tmp_path / "test.lang"
        lang_path.touch()

        count = save_mod_keys(db, lang_path)
        assert count == 0
        assert not (tmp_path / "test.lang.mod.json").exists()

    def test_load_no_file(self, db, tmp_path):
        """사이드카 파일 없으면 0."""
        lang_path = tmp_path / "test.lang"
        restored = load_mod_keys(db, lang_path)
        assert restored == 0

    def test_get_mod_count(self, db, tmp_path):
        lang_path = tmp_path / "test.lang"
        lang_path.touch()

        assert get_mod_count(lang_path) == 0

        db.update_target(1, "안녕")
        save_mod_keys(db, lang_path)
        assert get_mod_count(lang_path) == 1

    def test_corrupted_file(self, db, tmp_path):
        """손상된 사이드카 파일 → 빈 결과."""
        lang_path = tmp_path / "test.lang"
        mod_file = tmp_path / "test.lang.mod.json"
        mod_file.write_text("not valid json", encoding="utf-8")

        restored = load_mod_keys(db, lang_path)
        assert restored == 0

    def test_load_skips_already_modified(self, db, tmp_path):
        """이미 modified=1인 레코드는 중복 카운트 안 함."""
        lang_path = tmp_path / "test.lang"
        lang_path.touch()

        db.update_target(1, "안녕")
        save_mod_keys(db, lang_path)

        # 이미 modified=1인 상태에서 다시 로드
        restored = load_mod_keys(db, lang_path)
        assert restored == 0  # 이미 modified=1이라 변경 없음
