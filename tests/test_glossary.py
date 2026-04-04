"""용어집 추출 단위 테스트."""

import pytest
from core.db import LangDatabase
from core.glossary import (
    parse_gender_marker,
    strip_grammar_marker,
    extract_glossary,
    get_glossary_stats,
    ID_CATEGORY_MAP,
    GLOSSARY_CATEGORIES,
    get_id_category,
    get_id_category_description,
    _is_valid_term,
)


# ---------------------------------------------------------------------------
# 성별 마커 파싱
# ---------------------------------------------------------------------------

class TestGenderMarker:
    def test_female(self):
        name, gender = parse_gender_marker("Gabrielle Benele^F")
        assert name == "Gabrielle Benele"
        assert gender == "F"

    def test_male(self):
        name, gender = parse_gender_marker("Ugron gro-Thumog^M")
        assert name == "Ugron gro-Thumog"
        assert gender == "M"

    def test_neuter(self):
        name, gender = parse_gender_marker("Rosalie Nurin^N")
        assert name == "Rosalie Nurin"
        assert gender == "N"

    def test_no_marker(self):
        name, gender = parse_gender_marker("Baron Winoc")
        assert name == "Baron Winoc"
        assert gender == ""

    def test_empty(self):
        name, gender = parse_gender_marker("")
        assert name == ""
        assert gender == ""

    def test_grammar_marker_not_gender(self):
        """^p, ^n (소문자)는 성별 마커가 아님."""
        name, gender = parse_gender_marker("shoes^p")
        assert name == "shoes^p"
        assert gender == ""


class TestGrammarMarker:
    def test_strip_lowercase(self):
        assert strip_grammar_marker("shoes^p") == "shoes"
        assert strip_grammar_marker("battle axe^n") == "battle axe"

    def test_no_marker(self):
        assert strip_grammar_marker("Iron Sword") == "Iron Sword"

    def test_gender_marker_preserved(self):
        """대문자 ^F/^M/^N은 문법 마커가 아님."""
        assert strip_grammar_marker("NPC^F") == "NPC^F"


# ---------------------------------------------------------------------------
# 유효성 필터
# ---------------------------------------------------------------------------

class TestValidTerm:
    def test_normal(self):
        assert _is_valid_term("Palomino Horse", "COLLECTIBLE") is True

    def test_too_short(self):
        assert _is_valid_term("A", "ITEM") is False

    def test_empty(self):
        assert _is_valid_term("", "NPC") is False

    def test_dev_text(self):
        assert _is_valid_term("QAT Object", "QUEST_OBJ") is False
        assert _is_valid_term("JUST Apprehend Teleport", "SKILL") is False
        assert _is_valid_term("GM 10m AOE Death Touch", "SKILL") is False
        assert _is_valid_term("Tool - Range", "SKILL") is False

    def test_numbers_only(self):
        assert _is_valid_term("123", "ITEM") is False
        assert _is_valid_term("2", "ITEM") is False

    def test_too_long(self):
        assert _is_valid_term("x" * 201, "LORE") is False
        assert _is_valid_term("x" * 200, "LORE") is True


class TestIdCategoryHelpers:
    def test_known_category(self):
        assert get_id_category(8290981) == "NPC"
        assert get_id_category_description(8290981) == "NPC 이름"

    def test_unknown_category(self):
        assert get_id_category(123456789) == "UNCLASSIFIED"
        assert get_id_category_description(123456789) == "미분류 ID"


# ---------------------------------------------------------------------------
# 추출 통합 테스트 (미니 DB)
# ---------------------------------------------------------------------------

@pytest.fixture
def glossary_db():
    """용어집 테스트용 DB — NPC/ITEM/SKILL/LOCATION 레코드 포함."""
    db = LangDatabase()

    # NPC (ID 8290981)
    npc_records = [
        (8290981, 0, 1, "Gabrielle Benele^F"),
        (8290981, 0, 2, "Ugron gro-Thumog^M"),
        (8290981, 0, 3, "Baron Winoc"),
        (8290981, 0, 4, "Gabrielle Benele^F"),  # 중복 (usage_count 테스트)
        (8290981, 0, 5, ""),  # 빈 텍스트
    ]

    # ITEM (ID 242841733)
    item_records = [
        (242841733, 0, 1, "Iron Sword"),
        (242841733, 0, 2, "shoes^p"),  # 문법 마커
        (242841733, 0, 3, "Iron Sword"),  # 중복
    ]

    # LOCATION (ID 164009093)
    loc_records = [
        (164009093, 0, 1, "Fighters Guild"),
        (164009093, 0, 2, "Shornhelm"),
    ]

    # 비추출 대상 ID (대사 — 매핑에 없음)
    dialogue_records = [
        (149328292, 0, 1, "I hear the Nords don't have warm blood"),
    ]

    all_records = npc_records + item_records + loc_records + dialogue_records
    db.insert_records(all_records)

    yield db
    db.close()


class TestExtractGlossary:
    def test_basic_extraction(self, glossary_db):
        result = extract_glossary(glossary_db)
        assert result["total_extracted"] > 0
        assert "NPC" in result["categories"]
        assert "ITEM" in result["categories"]
        assert "LOCATION" in result["categories"]

    def test_npc_count(self, glossary_db):
        result = extract_glossary(glossary_db)
        # Gabrielle Benele, Ugron gro-Thumog, Baron Winoc = 3 고유 NPC
        assert result["categories"]["NPC"] == 3

    def test_npc_gender_extracted(self, glossary_db):
        extract_glossary(glossary_db)
        rows = glossary_db.execute(
            "SELECT term, gender FROM glossary WHERE category = 'NPC' ORDER BY term"
        ).fetchall()
        gender_map = {term: gender for term, gender in rows}
        assert gender_map["Gabrielle Benele"] == "F"
        assert gender_map["Ugron gro-Thumog"] == "M"
        assert gender_map["Baron Winoc"] == ""

    def test_item_grammar_marker_stripped(self, glossary_db):
        extract_glossary(glossary_db)
        rows = glossary_db.execute(
            "SELECT term FROM glossary WHERE category = 'ITEM' ORDER BY term"
        ).fetchall()
        terms = [r[0] for r in rows]
        assert "Iron Sword" in terms
        assert "shoes" in terms
        assert "shoes^p" not in terms

    def test_dedup(self, glossary_db):
        """같은 term+category는 한 번만 저장."""
        extract_glossary(glossary_db)
        count = glossary_db.execute(
            "SELECT count(*) FROM glossary WHERE term = 'Iron Sword'"
        ).fetchone()[0]
        assert count == 1

    def test_npc_dedup(self, glossary_db):
        """NPC 중복 (성별 마커 제거 후 같은 이름)."""
        extract_glossary(glossary_db)
        count = glossary_db.execute(
            "SELECT count(*) FROM glossary WHERE term = 'Gabrielle Benele'"
        ).fetchone()[0]
        assert count == 1

    def test_dialogue_not_extracted(self, glossary_db):
        """매핑에 없는 ID는 추출하지 않음."""
        extract_glossary(glossary_db)
        count = glossary_db.glossary_count()
        # NPC 3 + ITEM 2 + LOCATION 2 = 7
        assert count == 7

    def test_empty_source_skipped(self, glossary_db):
        """빈 source는 건너뜀."""
        extract_glossary(glossary_db)
        empty = glossary_db.execute(
            "SELECT count(*) FROM glossary WHERE term = ''"
        ).fetchone()[0]
        assert empty == 0

    def test_usage_count(self, glossary_db):
        """중복 레코드의 usage_count 반영."""
        extract_glossary(glossary_db)
        row = glossary_db.execute(
            "SELECT usage_count FROM glossary WHERE term = 'Gabrielle Benele'"
        ).fetchone()
        assert row[0] == 2  # 원본 2건

    def test_cancel(self, glossary_db):
        """cancel_check 시 조기 중단."""
        call_count = 0

        def cancel_after_one():
            nonlocal call_count
            call_count += 1
            return call_count > 1

        result = extract_glossary(glossary_db, cancel_check=cancel_after_one)
        # 일부만 추출됨
        total = glossary_db.glossary_count()
        assert total < 7  # 전체보다 적음


class TestGlossaryStats:
    def test_stats(self, glossary_db):
        extract_glossary(glossary_db)
        stats = get_glossary_stats(glossary_db)
        assert stats["total"] == 7
        assert stats["translated"] == 0  # 번역 없음
        assert "NPC" in stats["categories"]


class TestGlossaryQueryAPI:
    def test_get_by_category(self, glossary_db):
        extract_glossary(glossary_db)
        rows = glossary_db.get_glossary_by_category("NPC")
        assert len(rows) == 3

    def test_get_all(self, glossary_db):
        extract_glossary(glossary_db)
        rows = glossary_db.get_glossary_by_category()
        assert len(rows) == 7

    def test_search(self, glossary_db):
        extract_glossary(glossary_db)
        rows = glossary_db.search_glossary("Sword")
        assert len(rows) == 1
        assert rows[0][1] == "Iron Sword"

    def test_update_translation(self, glossary_db):
        extract_glossary(glossary_db)
        row = glossary_db.execute(
            "SELECT rowid FROM glossary WHERE term = 'Iron Sword'"
        ).fetchone()
        ok = glossary_db.update_glossary_translation(row[0], "철 검", "무기")
        assert ok is True
        updated = glossary_db.execute(
            "SELECT translation, note FROM glossary WHERE term = 'Iron Sword'"
        ).fetchone()
        assert updated == ("철 검", "무기")

    def test_categories_list(self, glossary_db):
        extract_glossary(glossary_db)
        cats = glossary_db.get_glossary_categories()
        cat_names = [c[0] for c in cats]
        assert "NPC" in cat_names
        assert "ITEM" in cat_names
