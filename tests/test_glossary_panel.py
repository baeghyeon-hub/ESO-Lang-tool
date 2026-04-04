"""glossary_panel 모듈 테스트."""
import json
import pytest

from core.db import LangDatabase
from core.glossary import extract_glossary, fill_glossary_from_records
from ui.glossary_panel import GlossaryTableModel


@pytest.fixture
def db():
    d = LangDatabase()
    d.insert_records([
        (8290981, 0, 0, "Razum-dar"),       # NPC
        (8290981, 0, 1, "Abnur Tharn"),      # NPC
        (242841733, 0, 0, "Iron Sword"),     # ITEM
        (242841733, 0, 1, "Steel Shield"),   # ITEM
        (52420949, 0, 0, "The Harborage"),   # QUEST_NAME
    ])
    # 일부 target 설정
    d._conn.execute("UPDATE records SET target = '라줌다르' WHERE rowid = 1")
    d._conn.execute("UPDATE records SET target = '아브너 탄' WHERE rowid = 2")
    d._conn.commit()
    extract_glossary(d)
    return d


class TestGlossaryTableModel:
    def test_load_all(self, db):
        model = GlossaryTableModel()
        model.set_db(db)
        model.load()
        assert model.rowCount() > 0

    def test_load_by_category(self, db):
        model = GlossaryTableModel()
        model.set_db(db)
        model.load(category="NPC")
        count_npc = model.rowCount()
        model.load(category="ITEM")
        count_item = model.rowCount()
        model.load()
        count_all = model.rowCount()
        assert count_npc > 0
        assert count_item > 0
        assert count_all == count_npc + count_item  # NPC + ITEM only (QUEST_NAME not in GLOSSARY_CATEGORIES by default)

    def test_search(self, db):
        model = GlossaryTableModel()
        model.set_db(db)
        model.load(keyword="Razum")
        assert model.rowCount() >= 1

    def test_search_with_category(self, db):
        model = GlossaryTableModel()
        model.set_db(db)
        model.load(keyword="Razum", category="NPC")
        assert model.rowCount() >= 1
        model.load(keyword="Razum", category="ITEM")
        assert model.rowCount() == 0

    def test_edit_translation(self, db):
        model = GlossaryTableModel()
        model.set_db(db)
        model.load()

        idx = model.index(0, 1)  # 번역 컬럼
        old_val = model.data(idx)
        model.setData(idx, "새번역")
        assert model.data(idx) == "새번역"

    def test_edit_note(self, db):
        model = GlossaryTableModel()
        model.set_db(db)
        model.load()

        idx = model.index(0, 5)  # 메모 컬럼
        model.setData(idx, "테스트 메모")
        assert model.data(idx) == "테스트 메모"

    def test_readonly_columns(self, db):
        model = GlossaryTableModel()
        model.set_db(db)
        model.load()

        # term, category, gender, usage_count는 편집 불가
        from PyQt6.QtCore import Qt
        for col in (0, 2, 3, 4):
            flags = model.flags(model.index(0, col))
            assert not (flags & Qt.ItemFlag.ItemIsEditable)

    def test_editable_columns(self, db):
        model = GlossaryTableModel()
        model.set_db(db)
        model.load()

        from PyQt6.QtCore import Qt
        for col in (1, 5):  # translation, note
            flags = model.flags(model.index(0, col))
            assert flags & Qt.ItemFlag.ItemIsEditable


class TestGlossaryExportImport:
    def test_export_import_roundtrip(self, db, tmp_path):
        """내보내기 → 번역 수정 → 가져오기 라운드트립."""
        path = tmp_path / "glossary.json"

        # 내보내기
        db.init_glossary()
        rows = db._conn.execute(
            "SELECT term, translation, category, gender, usage_count, note "
            "FROM glossary ORDER BY category, term"
        ).fetchall()

        data = [
            {"term": r[0], "translation": r[1], "category": r[2],
             "gender": r[3], "usage_count": r[4], "note": r[5]}
            for r in rows
        ]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        # 번역 수정
        data_modified = json.loads(path.read_text("utf-8"))
        for item in data_modified:
            if item["term"] == "Iron Sword":
                item["translation"] = "철검"
        path.write_text(json.dumps(data_modified, ensure_ascii=False), encoding="utf-8")

        # 가져오기
        import_data = json.loads(path.read_text("utf-8"))
        updated = 0
        for item in import_data:
            term = item["term"]
            cat = item["category"]
            trans = item["translation"]
            if not trans:
                continue
            existing = db._conn.execute(
                "SELECT rowid FROM glossary WHERE term = ? AND category = ?",
                (term, cat),
            ).fetchone()
            if existing:
                db._conn.execute(
                    "UPDATE glossary SET translation = ? WHERE rowid = ?",
                    (trans, existing[0]),
                )
                updated += 1
        db._conn.commit()

        # 확인
        row = db._conn.execute(
            "SELECT translation FROM glossary WHERE term = 'Iron Sword'"
        ).fetchone()
        assert row[0] == "철검"


class TestExtractWithEnKr:
    """en.lang + kr.lang 분리 추출 테스트."""

    def test_extract_en_kr_mapping(self):
        """en_db에서 영어 term, kr_db에서 한글 translation."""
        en_db = LangDatabase()
        en_db.insert_records([
            (8290981, 0, 0, "Razum-dar"),
            (8290981, 0, 1, "Abnur Tharn^M"),
            (242841733, 0, 0, "Iron Sword"),
        ])

        kr_db = LangDatabase()
        kr_db.insert_records([
            (8290981, 0, 0, "라줌다르"),
            (8290981, 0, 1, "아브너 탄"),
            (242841733, 0, 0, "철검"),
        ])

        # 용어집은 en_db에 저장
        result = extract_glossary(en_db, en_db=en_db, kr_db=kr_db)
        assert result["total_extracted"] >= 3

        # term은 영어, translation은 한글
        row = en_db.execute(
            "SELECT term, translation FROM glossary WHERE term = 'Razum-dar'"
        ).fetchone()
        assert row is not None
        assert row[0] == "Razum-dar"
        assert row[1] == "라줌다르"

        row = en_db.execute(
            "SELECT term, translation FROM glossary WHERE term = 'Iron Sword'"
        ).fetchone()
        assert row is not None
        assert row[1] == "철검"

    def test_extract_en_kr_gender_marker(self):
        """성별 마커가 영어 term에서 제거됨."""
        en_db = LangDatabase()
        en_db.insert_records([
            (8290981, 0, 0, "Abnur Tharn^M"),
        ])

        kr_db = LangDatabase()
        kr_db.insert_records([
            (8290981, 0, 0, "아브너 탄"),
        ])

        extract_glossary(en_db, en_db=en_db, kr_db=kr_db)

        row = en_db.execute(
            "SELECT term, gender, translation FROM glossary WHERE term = 'Abnur Tharn'"
        ).fetchone()
        assert row is not None
        assert row[1] == "M"
        assert row[2] == "아브너 탄"

    def test_extract_clear_existing(self):
        """clear_existing=True로 기존 데이터 삭제 후 재추출."""
        en_db = LangDatabase()
        en_db.insert_records([
            (8290981, 0, 0, "Razum-dar"),
            (242841733, 0, 0, "Iron Sword"),
        ])

        kr_db = LangDatabase()
        kr_db.insert_records([
            (8290981, 0, 0, "라줌다르"),
            (242841733, 0, 0, "철검"),
        ])

        # 먼저 잘못된 데이터로 추출 (한글 term이 들어간 상황 시뮬레이션)
        en_db.init_glossary()
        en_db._conn.execute(
            "INSERT INTO glossary (term, translation, category, gender, usage_count) "
            "VALUES ('라줌다르', '', 'NPC', '', 1)"
        )
        en_db._conn.commit()

        old_count = en_db._conn.execute("SELECT count(*) FROM glossary").fetchone()[0]
        assert old_count == 1

        # clear_existing=True로 재추출
        result = extract_glossary(en_db, en_db=en_db, kr_db=kr_db, clear_existing=True)
        assert result["total_extracted"] >= 2

        # 한글 term은 사라지고, 영어 term이 있어야 함
        old_row = en_db.execute(
            "SELECT * FROM glossary WHERE term = '라줌다르'"
        ).fetchone()
        assert old_row is None

        new_row = en_db.execute(
            "SELECT term, translation FROM glossary WHERE term = 'Razum-dar'"
        ).fetchone()
        assert new_row is not None
        assert new_row[1] == "라줌다르"

    def test_extract_without_en_db_fallback(self):
        """en_db 없이 호출하면 db 자체의 source/target 사용 (레거시)."""
        db = LangDatabase()
        db.insert_records([
            (8290981, 0, 0, "Razum-dar"),
        ])
        db._conn.execute("UPDATE records SET target = '라줌다르' WHERE rowid = 1")
        db._conn.commit()

        result = extract_glossary(db)
        row = db.execute(
            "SELECT term, translation FROM glossary WHERE term = 'Razum-dar'"
        ).fetchone()
        assert row is not None
        assert row[1] == "라줌다르"


class TestFillFromRecords:
    def test_fill_basic(self):
        """records의 기존 번역으로 용어집 빈 항목 채우기."""
        d = LangDatabase()
        d.insert_records([
            (242841733, 0, 0, "Iron Sword"),
            (242841733, 0, 1, "Steel Shield"),
            (8290981, 0, 0, "Razum-dar"),
        ])
        d._conn.execute("UPDATE records SET target = '철검' WHERE rowid = 1")
        d._conn.execute("UPDATE records SET target = '강철 방패' WHERE rowid = 2")
        d._conn.execute("UPDATE records SET target = '라줌다르' WHERE rowid = 3")
        d._conn.commit()

        extract_glossary(d)

        # 추출 직후에는 translation이 이미 채워져 있음 (extract에서 target 반영)
        # translation을 비워서 fill 테스트
        d._conn.execute("UPDATE glossary SET translation = ''")
        d._conn.commit()

        result = fill_glossary_from_records(d)
        assert result["filled"] >= 2  # Iron Sword, Steel Shield 매칭

        # 확인
        row = d._conn.execute(
            "SELECT translation FROM glossary WHERE term = 'Iron Sword'"
        ).fetchone()
        assert row[0] == "철검"

    def test_fill_skips_existing(self):
        """이미 번역이 있는 항목은 건너뜀."""
        d = LangDatabase()
        d.insert_records([
            (242841733, 0, 0, "Iron Sword"),
        ])
        d._conn.execute("UPDATE records SET target = '철검' WHERE rowid = 1")
        d._conn.commit()

        extract_glossary(d)

        # 이미 translation 있는 상태에서 fill
        result = fill_glossary_from_records(d)
        assert result["filled"] == 0  # 이미 채워져 있으므로 0

    def test_fill_no_match(self):
        """records에 번역이 없으면 매칭 실패."""
        d = LangDatabase()
        d.insert_records([
            (242841733, 0, 0, "Iron Sword"),
        ])
        # target 비어있음
        d._conn.commit()

        extract_glossary(d)
        d._conn.execute("UPDATE glossary SET translation = ''")
        d._conn.commit()

        result = fill_glossary_from_records(d)
        assert result["no_match"] >= 1
