"""core/translator.py 테스트."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from core.db import LangDatabase
from core.config import TranslationSettings
from core.llm_providers import LLMProvider, LLMResponse
from core.translator import (
    GlossaryPostProcessor,
    SanityChecker,
    TranslationBatch,
    TranslationItem,
    TranslationPipeline,
)


# ---------------------------------------------------------------------------
# MockProvider
# ---------------------------------------------------------------------------

class MockProvider(LLMProvider):
    """테스트용 가짜 프로바이더."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.call_count = 0

    async def translate(self, system_prompt, user_prompt, **kw) -> LLMResponse:
        self.call_count += 1
        text = self._responses.pop(0) if self._responses else ""
        return LLMResponse(text=text, model="mock-model", input_tokens=100, output_tokens=50)

    async def validate_key(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# SanityChecker
# ---------------------------------------------------------------------------

class TestSanityChecker:
    def setup_method(self):
        self.checker = SanityChecker()

    def test_pass(self):
        flags = self.checker.check("Hello world", "안녕하세요 세계")
        assert flags == []

    def test_empty(self):
        flags = self.checker.check("Hello", "")
        assert "EMPTY" in flags

    def test_en_identical(self):
        flags = self.checker.check("Hello world", "Hello world")
        assert "EN_IDENTICAL" in flags

    def test_low_korean(self):
        flags = self.checker.check(
            "This is a long test string",
            "This is a long test 문자열",
        )
        assert "LOW_KOREAN" in flags

    def test_too_short(self):
        flags = self.checker.check(
            "This is a fairly long sentence that should have a reasonable translation",
            "짧음",
        )
        assert "TOO_SHORT" in flags

    def test_too_long(self):
        flags = self.checker.check(
            "Short",
            "이것은 매우 매우 매우 매우 매우 매우 매우 매우 매우 매우 매우 매우 긴 번역입니다 "
            "이것은 정말 너무 길어서 원문의 3.5배를 초과합니다",
        )
        # "Short"는 5자 이하라 길이 체크 안 함
        assert "TOO_LONG" not in flags

    def test_too_long_triggers(self):
        source = "Hello, how are you doing today?"
        translation = "안녕" * 100  # 매우 긴 번역
        flags = self.checker.check(source, translation)
        assert "TOO_LONG" in flags

    def test_placeholder_mismatch(self):
        flags = self.checker.check(
            "You need <<1>> gold.",
            "골드가 필요합니다.",
        )
        assert "PLACEHOLDER_MISMATCH" in flags

    def test_placeholder_preserved(self):
        flags = self.checker.check(
            "You need <<1>> gold.",
            "<<1>> 골드가 필요합니다.",
        )
        assert "PLACEHOLDER_MISMATCH" not in flags

    def test_short_source_skips_length_check(self):
        """5자 이하 source는 길이 체크 건너뜀."""
        flags = self.checker.check("Hi", "안녕하세요 반갑습니다")
        assert "TOO_LONG" not in flags

    def test_suffix_duplicated(self):
        """^F^F 같은 마커 중복 감지."""
        flags = self.checker.check("Eloisa^F", "엘로이사^F^F")
        assert "SUFFIX_DUPLICATED" in flags

    def test_suffix_missing(self):
        """원문에 ^M 있는데 번역에 누락."""
        flags = self.checker.check("Knight^M", "기사")
        assert "SUFFIX_MISSING" in flags

    def test_suffix_changed(self):
        """^F → ^M으로 바뀜."""
        flags = self.checker.check("Dancer^F", "무용수^M")
        assert "SUFFIX_CHANGED" in flags

    def test_suffix_preserved(self):
        """마커가 정상 보존된 경우."""
        flags = self.checker.check("Silver Knight^M", "은빛 기사^M")
        assert "SUFFIX_DUPLICATED" not in flags
        assert "SUFFIX_MISSING" not in flags
        assert "SUFFIX_CHANGED" not in flags


class TestAutoFix:
    """SanityChecker.auto_fix 자동 수정 테스트."""

    def test_fix_double_suffix(self):
        """^F^F → ^F 중복 제거."""
        result = SanityChecker.auto_fix("Eloisa^F", "엘로이사^F^F")
        assert result == "엘로이사^F"

    def test_fix_triple_suffix(self):
        """^N^N^N → ^N."""
        result = SanityChecker.auto_fix("Nata^N", "나타^N^N^N")
        assert result == "나타^N"

    def test_fix_missing_suffix(self):
        """마커 누락 시 원문에서 복원."""
        result = SanityChecker.auto_fix("Knight^M", "기사")
        assert result == "기사^M"

    def test_fix_nested_parens(self):
        """'베르미나(베르미나(Vaermina))^F' → '베르미나^F'."""
        result = SanityChecker.auto_fix(
            "Vaermina^F",
            "베르미나(베르미나(Vaermina))^F",
        )
        assert result == "베르미나^F"

    def test_no_change_when_ok(self):
        """정상 번역은 변경 없음."""
        result = SanityChecker.auto_fix("Silver Knight^M", "은빛 기사^M")
        assert result == "은빛 기사^M"

    def test_no_suffix_source(self):
        """원문에 마커 없으면 안 건드림."""
        result = SanityChecker.auto_fix("Hello World", "안녕 세계")
        assert result == "안녕 세계"


# ---------------------------------------------------------------------------
# GlossaryPostProcessor
# ---------------------------------------------------------------------------

class TestGlossaryPostProcessor:
    def test_basic_replacement(self):
        pp = GlossaryPostProcessor([
            ("Tamriel", "탐리엘"),
            ("Gold", "골드"),
        ])
        result = pp.apply(
            "Welcome to Tamriel, you need Gold.",
            "Welcome to Tamriel, Gold가 필요합니다.",
        )
        assert "탐리엘" in result
        assert "골드" in result
        assert "Tamriel" not in result
        assert "Gold" not in result

    def test_no_replacement_if_not_in_source(self):
        """source에 없는 용어는 교체 안 함."""
        pp = GlossaryPostProcessor([("Dragon", "드래곤")])
        result = pp.apply(
            "Hello world",
            "Dragon이 있습니다",
        )
        assert "Dragon" in result  # source에 없으므로 교체 안 함

    def test_longest_match_first(self):
        """긴 term이 먼저 교체됨."""
        pp = GlossaryPostProcessor([
            ("Dark Brotherhood", "어둠의 형제단"),
            ("Dark", "어둠"),
        ])
        result = pp.apply(
            "Join the Dark Brotherhood",
            "Dark Brotherhood에 가입하세요",
        )
        assert "어둠의 형제단" in result


# ---------------------------------------------------------------------------
# TranslationBatch
# ---------------------------------------------------------------------------

class TestTranslationBatch:
    def test_build_user_prompt(self):
        items = [
            TranslationItem(rowid=1, source="Hello", reference="안녕", group_id=100, category="NPC"),
            TranslationItem(rowid=2, source="World", group_id=100, category="NPC"),
        ]
        batch = TranslationBatch(items)
        prompt = batch.build_user_prompt()
        assert "[1] EN: Hello" in prompt
        assert "REF: 안녕" in prompt
        assert "[2] EN: World" in prompt

    def test_build_system_prompt_with_glossary(self):
        items = [TranslationItem(rowid=1, source="Hello", group_id=100, category="NPC")]
        glossary = [("Tamriel", "탐리엘", "LOCATION")]
        batch = TranslationBatch(items, glossary)
        prompt = batch.build_system_prompt()
        assert "Tamriel → 탐리엘" in prompt
        assert "NPC" in prompt

    def test_parse_response(self):
        items = [
            TranslationItem(rowid=1, source="Hello", group_id=100, category="NPC"),
            TranslationItem(rowid=2, source="World", group_id=100, category="NPC"),
            TranslationItem(rowid=3, source="Goodbye", group_id=100, category="NPC"),
        ]
        batch = TranslationBatch(items)
        raw = "[1] KR: 안녕하세요\n[2] KR: 세계\n[3] KR: 안녕히 가세요"
        parsed = batch.parse_response(raw)
        assert len(parsed) == 3
        assert parsed[0] == (0, "안녕하세요")
        assert parsed[1] == (1, "세계")
        assert parsed[2] == (2, "안녕히 가세요")

    def test_parse_response_partial(self):
        """일부만 파싱된 경우."""
        items = [
            TranslationItem(rowid=1, source="A", group_id=100, category="NPC"),
            TranslationItem(rowid=2, source="B", group_id=100, category="NPC"),
        ]
        batch = TranslationBatch(items)
        raw = "[1] KR: 가"
        parsed = batch.parse_response(raw)
        assert len(parsed) == 1
        assert parsed[0] == (0, "가")

    def test_parse_response_out_of_range(self):
        """범위 밖 인덱스는 무시."""
        items = [TranslationItem(rowid=1, source="A", group_id=100, category="NPC")]
        batch = TranslationBatch(items)
        raw = "[1] KR: 가\n[5] KR: 나"
        parsed = batch.parse_response(raw)
        assert len(parsed) == 1


# ---------------------------------------------------------------------------
# Pipeline (end-to-end with MockProvider)
# ---------------------------------------------------------------------------

class TestPipeline:
    def _make_db_with_records(self) -> LangDatabase:
        db = LangDatabase()
        db.insert_records([
            (100, 0, 0, "Hello"),
            (100, 0, 1, "Hello"),  # 중복
            (100, 0, 2, "World"),
            (200, 0, 0, "Goodbye"),
        ])
        return db

    def test_prepare_items_dedup(self):
        """중복 source가 하나로 합쳐지는지."""
        db = self._make_db_with_records()
        settings = TranslationSettings()
        provider = MockProvider([])
        pipeline = TranslationPipeline(db, None, provider, settings)

        items = pipeline.prepare_items()
        sources = [item.source for item in items]
        assert "Hello" in sources
        assert "World" in sources
        assert "Goodbye" in sources
        assert len(items) == 3  # "Hello" 중복 제거
        db.close()

    def test_pipeline_end_to_end(self):
        """MockProvider로 전체 파이프라인 실행."""
        db = self._make_db_with_records()
        settings = TranslationSettings()
        settings.batch_size = 10
        settings.glossary_injection = False

        mock_response = "[1] KR: 안녕하세요\n[2] KR: 세계\n[3] KR: 안녕히 가세요"
        provider = MockProvider([mock_response])

        pipeline = TranslationPipeline(db, None, provider, settings)
        items = pipeline.prepare_items()

        summary = asyncio.run(pipeline.run(items))

        assert summary.ok_count == 3
        assert summary.failed_count == 0
        assert summary.applied_count > 0
        assert provider.call_count == 1

        # DB에 반영 확인
        record = db.get_record_by_rowid(1)
        assert record[4] == "안녕하세요"  # target

        # 중복 전파 확인 (rowid 1과 2 모두 같은 source "Hello")
        record2 = db.get_record_by_rowid(2)
        assert record2[4] == "안녕하세요"

        db.close()

    def test_pipeline_api_error(self):
        """API 오류 시 전부 실패 처리."""
        db = self._make_db_with_records()
        settings = TranslationSettings()
        settings.batch_size = 10
        settings.max_retries = 0
        settings.glossary_injection = False

        class ErrorProvider(LLMProvider):
            async def translate(self, *a, **kw):
                raise RuntimeError("API down")
            async def validate_key(self):
                return False

        pipeline = TranslationPipeline(db, None, ErrorProvider(), settings)
        items = pipeline.prepare_items()
        summary = asyncio.run(pipeline.run(items))

        assert summary.ok_count == 0
        assert summary.failed_count == 3
        db.close()

    def test_pipeline_sanity_check_failure(self):
        """Sanity check 실패 시 failed 처리."""
        db = self._make_db_with_records()
        settings = TranslationSettings()
        settings.batch_size = 10
        settings.max_retries = 0
        settings.glossary_injection = False

        # 원문과 동일하게 반환 → EN_IDENTICAL
        mock_response = "[1] KR: Hello\n[2] KR: World\n[3] KR: Goodbye"
        provider = MockProvider([mock_response])

        pipeline = TranslationPipeline(db, None, provider, settings)
        items = pipeline.prepare_items()
        summary = asyncio.run(pipeline.run(items))

        assert summary.ok_count == 0
        assert summary.failed_count == 3
        db.close()

    def test_pipeline_cancellation(self):
        """취소 시 조기 종료."""
        db = self._make_db_with_records()
        settings = TranslationSettings()
        settings.batch_size = 1  # 아이템당 1배치
        settings.glossary_injection = False

        provider = MockProvider([
            "[1] KR: 안녕하세요",
            "[1] KR: 세계",
            "[1] KR: 안녕히 가세요",
        ])

        call_count = 0
        def cancel_after_one():
            nonlocal call_count
            call_count += 1
            return call_count > 1

        pipeline = TranslationPipeline(
            db, None, provider, settings,
            cancel_check=cancel_after_one,
        )
        items = pipeline.prepare_items()
        summary = asyncio.run(pipeline.run(items))

        # 첫 배치만 처리됨
        assert summary.ok_count == 1
        assert provider.call_count == 1
        db.close()
