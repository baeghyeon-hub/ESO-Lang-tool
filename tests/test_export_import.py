"""export_import 모듈 테스트."""
import json
import pytest
from pathlib import Path

from core.db import LangDatabase
from core.export_import import (
    export_records, export_filtered, export_modified, export_diff,
    import_records, ImportResult,
)


@pytest.fixture
def db():
    d = LangDatabase()
    d.insert_records([
        (100, 0, 0, "Hello"),
        (100, 0, 1, "World"),
        (200, 0, 0, "Sword"),
        (200, 0, 1, "Shield"),
    ])
    # target 설정
    d._conn.execute("UPDATE records SET target = '안녕' WHERE rowid = 1")
    d._conn.execute("UPDATE records SET target = '세계' WHERE rowid = 2")
    # rowid 3: target = '' (미번역)
    d._conn.execute("UPDATE records SET target = '방패' WHERE rowid = 4")
    d._conn.commit()
    return d


class TestExport:
    def test_export_basic(self, db, tmp_path):
        path = tmp_path / "out.json"
        count = export_records(db, [1, 2, 3], path)
        assert count == 3

        data = json.loads(path.read_text("utf-8"))
        assert len(data) == 3
        assert all(k in data[0] for k in ("id", "unknown", "idx", "source", "target"))

    def test_export_empty(self, db, tmp_path):
        path = tmp_path / "out.json"
        count = export_records(db, [], path)
        assert count == 0
        assert not path.exists()

    def test_export_preserves_content(self, db, tmp_path):
        path = tmp_path / "out.json"
        export_records(db, [1], path)
        data = json.loads(path.read_text("utf-8"))
        assert data[0]["id"] == 100
        assert data[0]["source"] == "Hello"
        assert data[0]["target"] == "안녕"


class TestImport:
    def test_import_basic(self, db, tmp_path):
        # 내보내기 후 target 수정 → 가져오기
        path = tmp_path / "data.json"
        data = [
            {"id": 100, "unknown": 0, "idx": 0, "source": "Hello", "target": "헬로"},
            {"id": 200, "unknown": 0, "idx": 0, "source": "Sword", "target": "검"},
        ]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        updates, result = import_records(db, path)
        assert result.total_rows == 2
        assert result.matched == 2
        assert result.changed == 2  # 둘 다 target 변경됨
        assert len(updates) == 2

        # updates 적용 확인
        rowids = {u[0] for u in updates}
        targets = {u[1] for u in updates}
        assert "헬로" in targets
        assert "검" in targets

    def test_import_no_change(self, db, tmp_path):
        # 동일 target → 변경 없음
        path = tmp_path / "data.json"
        data = [{"id": 100, "unknown": 0, "idx": 0, "source": "Hello", "target": "안녕"}]
        path.write_text(json.dumps(data), encoding="utf-8")

        updates, result = import_records(db, path)
        assert result.matched == 1
        assert result.changed == 0
        assert len(updates) == 0

    def test_import_no_match(self, db, tmp_path):
        path = tmp_path / "data.json"
        data = [{"id": 999, "unknown": 0, "idx": 0, "source": "X", "target": "Y"}]
        path.write_text(json.dumps(data), encoding="utf-8")

        updates, result = import_records(db, path)
        assert result.skipped_no_match == 1
        assert result.changed == 0

    def test_import_invalid_json(self, db, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")

        updates, result = import_records(db, path)
        assert len(result.errors) == 1
        assert "JSON" in result.errors[0]

    def test_import_missing_key(self, db, tmp_path):
        path = tmp_path / "data.json"
        data = [{"id": 100, "source": "Hello", "target": "헬로"}]  # missing unknown, idx
        path.write_text(json.dumps(data), encoding="utf-8")

        updates, result = import_records(db, path)
        assert len(result.errors) == 1

    def test_roundtrip(self, db, tmp_path):
        """내보내기 → target 수정 → 가져오기 라운드트립."""
        path = tmp_path / "roundtrip.json"
        export_records(db, [1, 2, 3, 4], path)

        # target 수정
        data = json.loads(path.read_text("utf-8"))
        for item in data:
            item["target"] = item["target"] + "_수정"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        updates, result = import_records(db, path)
        assert result.total_rows == 4
        assert result.matched == 4
        assert result.changed == 4
        assert all("_수정" in u[1] for u in updates)


class TestExportTranslated:
    """번역된 항목만 내보내기 테스트."""

    def test_export_translated_only(self, db, tmp_path):
        """translated_only=True이면 target이 있는 항목만 내보냄."""
        path = tmp_path / "translated.json"
        count = export_filtered(db, path, translated_only=True)
        data = json.loads(path.read_text("utf-8"))

        # db fixture: rowid 1='안녕', 2='세계', 4='방패' — 3건 번역됨
        assert count == 3
        for item in data:
            assert item["target"] != ""
            assert item["target"] != item["source"]

    def test_export_translated_empty(self, tmp_path):
        """번역이 없으면 빈 배열."""
        d = LangDatabase()
        d.insert_records([(100, 0, 0, "Hello")])

        path = tmp_path / "empty.json"
        count = export_filtered(d, path, translated_only=True)
        assert count == 0

        data = json.loads(path.read_text("utf-8"))
        assert data == []

    def test_export_translated_excludes_source_equals_target(self, tmp_path):
        """source == target인 경우 제외."""
        d = LangDatabase()
        d.insert_records([(100, 0, 0, "Hello")])
        d._conn.execute("UPDATE records SET target = 'Hello' WHERE rowid = 1")
        d._conn.commit()

        path = tmp_path / "same.json"
        count = export_filtered(d, path, translated_only=True)
        assert count == 0


class TestExportModified:
    """modified=1인 항목만 내보내기 테스트."""

    def test_export_modified_only(self, tmp_path):
        """modified=1인 항목만 내보냄."""
        d = LangDatabase()
        d.insert_records([
            (100, 0, 0, "Hello"),
            (100, 0, 1, "World"),
            (200, 0, 0, "Sword"),
        ])
        # rowid 1만 수정
        d.update_target(1, "안녕하세요")  # modified=1 설정됨

        path = tmp_path / "modified.json"
        count = export_modified(d, path)
        assert count == 1

        data = json.loads(path.read_text("utf-8"))
        assert data[0]["target"] == "안녕하세요"
        assert data[0]["id"] == 100

    def test_export_modified_with_en_db(self, tmp_path):
        """en_db가 있으면 source를 영어 원문으로 교체."""
        en_db = LangDatabase()
        en_db.insert_records([(100, 0, 0, "Hello")])

        kr_db = LangDatabase()
        kr_db.insert_records([(100, 0, 0, "기존한글")])
        kr_db.update_target(1, "새번역")

        path = tmp_path / "modified.json"
        export_modified(kr_db, path, en_db=en_db)

        data = json.loads(path.read_text("utf-8"))
        assert data[0]["source"] == "Hello"     # en.lang 원문
        assert data[0]["target"] == "새번역"     # 수정된 값

    def test_export_modified_none(self, tmp_path):
        """수정 없으면 빈 배열."""
        d = LangDatabase()
        d.insert_records([(100, 0, 0, "Hello")])

        path = tmp_path / "empty.json"
        count = export_modified(d, path)
        assert count == 0

    def test_export_modified_import_roundtrip(self, tmp_path):
        """수정분 내보내기 → 다른 DB에 가져오기."""
        kr_db = LangDatabase()
        kr_db.insert_records([(100, 0, 0, "기존"), (100, 0, 1, "기존2")])
        kr_db.update_target(1, "새번역")
        kr_db.update_target(2, "새번역2")

        en_db = LangDatabase()
        en_db.insert_records([(100, 0, 0, "Hello"), (100, 0, 1, "World")])

        path = tmp_path / "modified.json"
        export_modified(kr_db, path, en_db=en_db)

        # 받는 쪽
        receiver = LangDatabase()
        receiver.insert_records([(100, 0, 0, "기존"), (100, 0, 1, "기존2")])

        updates, result = import_records(receiver, path)
        assert result.matched == 2
        assert result.changed == 2


class TestExportDiff:
    """en.lang 비교 내보내기 테스트."""

    def test_diff_basic(self, tmp_path):
        """en source ≠ kr source인 항목만 내보냄."""
        en_db = LangDatabase()
        en_db.insert_records([
            (100, 0, 0, "Hello"),
            (100, 0, 1, "World"),
            (200, 0, 0, "Sword"),
        ])

        kr_db = LangDatabase()
        kr_db.insert_records([
            (100, 0, 0, "안녕하세요"),   # 번역됨
            (100, 0, 1, "World"),        # 미번역 (영어 그대로)
            (200, 0, 0, "검"),            # 번역됨
        ])

        path = tmp_path / "diff.json"
        count = export_diff(kr_db, en_db, path)
        assert count == 2

        data = json.loads(path.read_text("utf-8"))
        sources = {d["source"] for d in data}
        targets = {d["target"] for d in data}
        assert "Hello" in sources
        assert "Sword" in sources
        assert "안녕하세요" in targets
        assert "검" in targets

    def test_diff_target_priority(self, tmp_path):
        """kr target이 있으면 kr source 대신 target 사용."""
        en_db = LangDatabase()
        en_db.insert_records([(100, 0, 0, "Hello")])

        kr_db = LangDatabase()
        kr_db.insert_records([(100, 0, 0, "안녕")])
        kr_db._conn.execute("UPDATE records SET target = '안녕하세요' WHERE rowid = 1")
        kr_db._conn.commit()

        path = tmp_path / "diff.json"
        export_diff(kr_db, en_db, path)

        data = json.loads(path.read_text("utf-8"))
        assert len(data) == 1
        assert data[0]["source"] == "Hello"
        assert data[0]["target"] == "안녕하세요"  # target 우선

    def test_diff_import_roundtrip(self, tmp_path):
        """diff 내보내기 → 다른 DB에 가져오기 라운드트립."""
        en_db = LangDatabase()
        en_db.insert_records([
            (100, 0, 0, "Hello"),
            (100, 0, 1, "World"),
        ])

        kr_db = LangDatabase()
        kr_db.insert_records([
            (100, 0, 0, "안녕"),
            (100, 0, 1, "세계"),
        ])

        # diff 내보내기
        path = tmp_path / "diff.json"
        export_diff(kr_db, en_db, path)

        # 받는 쪽: en.lang 기반 DB에 가져오기
        receiver_db = LangDatabase()
        receiver_db.insert_records([
            (100, 0, 0, "Hello"),
            (100, 0, 1, "World"),
        ])

        updates, result = import_records(receiver_db, path)
        assert result.matched == 2
        assert result.changed == 2

        # 적용
        for rowid, new_target in updates:
            receiver_db._conn.execute(
                "UPDATE records SET target = ? WHERE rowid = ?",
                (new_target, rowid),
            )
        receiver_db._conn.commit()

        # 검증
        row = receiver_db._conn.execute(
            "SELECT target FROM records WHERE rowid = 1"
        ).fetchone()
        assert row[0] == "안녕"

    def test_diff_no_en_match_skipped(self, tmp_path):
        """en.lang에 없는 레코드는 건너뜀."""
        en_db = LangDatabase()
        en_db.insert_records([(100, 0, 0, "Hello")])

        kr_db = LangDatabase()
        kr_db.insert_records([
            (100, 0, 0, "안녕"),
            (999, 0, 0, "없는ID"),  # en.lang에 없음
        ])

        path = tmp_path / "diff.json"
        count = export_diff(kr_db, en_db, path)
        assert count == 1  # 999는 건너뜀
