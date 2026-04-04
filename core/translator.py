"""
LLM 번역 파이프라인 엔진.

GUI 독립적 — QThread 없이 asyncio 기반.
SanityChecker, GlossaryPostProcessor, TranslationBatch, TranslationPipeline.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from core.config import TranslationSettings
from core.db import LangDatabase
from core.glossary import CATEGORY_DESCRIPTION_MAP, get_id_category
from core.llm_providers import LLMProvider, LLMResponse


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TranslationItem:
    rowid: int
    source: str
    reference: str = ""  # 기존 KR 패치 번역
    group_id: int = 0
    category: str = ""


@dataclass
class TranslationResult:
    rowid: int
    source: str
    translation: str
    status: str = "ok"  # "ok" | "failed" | "skipped"
    flags: list[str] = field(default_factory=list)
    model: str = ""
    attempt: int = 1


@dataclass
class TranslationSummary:
    total_items: int = 0
    ok_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    retry_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    applied_count: int = 0  # DB에 실제 반영된 행 수 (중복 전파 포함)


# ---------------------------------------------------------------------------
# Sanity Checker
# ---------------------------------------------------------------------------

_PLACEHOLDER_PATTERN = re.compile(r"<<C?:?\d+>>")
_GENDER_SUFFIX_PATTERN = re.compile(r"\^[FMNfmn]$")
_DOUBLE_SUFFIX_PATTERN = re.compile(r"(\^[FMNfmn])\1+")  # ^F^F, ^M^M 등


def _korean_ratio(text: str) -> float:
    """텍스트 내 한글 문자 비율."""
    if not text:
        return 0.0
    korean = sum(1 for c in text if 0xAC00 <= ord(c) <= 0xD7A3 or 0x3131 <= ord(c) <= 0x318F)
    total = sum(1 for c in text if not c.isspace())
    return korean / total if total > 0 else 0.0


class SanityChecker:
    """번역 결과 품질 검증."""

    def check(self, source: str, translation: str) -> list[str]:
        """실패한 체크 이름 리스트. 빈 리스트 = 통과."""
        flags: list[str] = []

        if not translation.strip():
            flags.append("EMPTY")
            return flags

        # 원문과 동일 (번역 안 됨)
        if translation.strip() == source.strip():
            flags.append("EN_IDENTICAL")
            return flags

        # 한글 비율 낮음 (10자 이상 문자열)
        if len(source) >= 10 and _korean_ratio(translation) < 0.3:
            flags.append("LOW_KOREAN")

        # 길이 비율 이상
        src_len = len(source.strip())
        tgt_len = len(translation.strip())
        if src_len > 5:
            if tgt_len < src_len * 0.2:
                flags.append("TOO_SHORT")
            elif tgt_len > src_len * 3.5:
                flags.append("TOO_LONG")

        # 포맷 코드 불일치
        src_placeholders = sorted(_PLACEHOLDER_PATTERN.findall(source))
        tgt_placeholders = sorted(_PLACEHOLDER_PATTERN.findall(translation))
        if src_placeholders != tgt_placeholders:
            flags.append("PLACEHOLDER_MISMATCH")

        # 성별 마커 중복 (^F^F, ^M^M 등)
        if _DOUBLE_SUFFIX_PATTERN.search(translation):
            flags.append("SUFFIX_DUPLICATED")

        # 성별 마커 불일치 (원문에 ^F 있는데 번역에 ^M으로 바뀜 등)
        src_suffix = _GENDER_SUFFIX_PATTERN.search(source)
        tgt_suffix = _GENDER_SUFFIX_PATTERN.search(translation)
        if src_suffix and not tgt_suffix:
            flags.append("SUFFIX_MISSING")
        elif src_suffix and tgt_suffix and src_suffix.group() != tgt_suffix.group():
            flags.append("SUFFIX_CHANGED")

        return flags

    @staticmethod
    def auto_fix(source: str, translation: str) -> str:
        """자동 수정 가능한 문제를 교정.

        - 성별 마커 중복 제거 (^F^F → ^F)
        - 성별 마커 누락 시 원문에서 복원
        - 이름(원문) 괄호 중복 정리: '한글(한글(English))' → '한글'
        """
        # 1. 마커 중복 제거: ^F^F → ^F, ^M^M^M → ^M
        translation = _DOUBLE_SUFFIX_PATTERN.sub(r"\1", translation)

        # 2. 마커 누락 시 원문에서 복원
        src_suffix = _GENDER_SUFFIX_PATTERN.search(source)
        tgt_suffix = _GENDER_SUFFIX_PATTERN.search(translation)
        if src_suffix and not tgt_suffix:
            translation = translation.rstrip() + src_suffix.group()

        # 3. 이름 중첩 괄호 정리: '베르미나(베르미나(Vaermina))' → '베르미나'
        #    또는 '한글(English)' → '한글' (고유명사에서 괄호 표기 제거)
        nested_paren = re.match(
            r'^(.+?)\(\1\(.*?\)\)(.*)$', translation
        )
        if nested_paren:
            translation = nested_paren.group(1) + nested_paren.group(2)

        return translation


# ---------------------------------------------------------------------------
# Glossary Post-Processor
# ---------------------------------------------------------------------------

class GlossaryPostProcessor:
    """번역 후 용어집 강제 적용."""

    def __init__(self, terms: list[tuple[str, str]]):
        """terms: [(english_term, korean_translation), ...] — 번역된 용어만."""
        # 긴 term부터 정렬 (longest match first)
        self._terms = sorted(terms, key=lambda t: len(t[0]), reverse=True)

    def apply(self, source: str, translation: str) -> str:
        """source에 있는 영어 term이 translation에도 남아있으면 한글로 교체."""
        for eng_term, kor_term in self._terms:
            if eng_term in source and eng_term in translation:
                translation = translation.replace(eng_term, kor_term)
        return translation


# ---------------------------------------------------------------------------
# Translation Batch
# ---------------------------------------------------------------------------

_RESPONSE_PATTERN = re.compile(r"\[(\d+)\]\s*KR:\s*(.*?)(?=\n\[\d+\]\s*KR:|\Z)", re.DOTALL)


class TranslationBatch:
    """LLM에 보낼 번역 배치 단위."""

    def __init__(
        self,
        items: list[TranslationItem],
        glossary_context: list[tuple[str, str, str]] | None = None,
    ):
        self.items = items
        self.glossary_context = glossary_context or []

    def build_system_prompt(self) -> str:
        """ESO 번역 시스템 프롬프트."""
        # 카테고리 결정 (배치 내 가장 많은 카테고리)
        cats = [item.category for item in self.items if item.category]
        category = max(set(cats), key=cats.count) if cats else "UNCLASSIFIED"
        cat_desc = CATEGORY_DESCRIPTION_MAP.get(category, "미분류")

        lines = [
            "You are translating Elder Scrolls Online (ESO) game text from English to Korean.",
            "",
            "Rules:",
            "- Translate naturally for Korean MMO players.",
            "- Keep UI strings concise. Do not add unnecessary honorifics.",
            "- Maintain consistency with the glossary terms below.",
            "",
            "Gender/format suffix rules (CRITICAL):",
            "- Strings may end with a gender suffix: ^F (female), ^M (male), ^N (neutral).",
            "- These suffixes are metadata tags, NOT part of the text to translate.",
            "- Keep the EXACT SAME suffix at the end of your translation. Do NOT duplicate or add extra suffixes.",
            "- Example: 'Silver Knight^M' → '은빛 기사^M' (NOT '은빛 기사^M^M')",
            "",
            "Format code rules:",
            "- Preserve ALL format codes exactly as they appear: <<1>>, <<C:1>>, |cffffff, |r, etc.",
            "- Do not translate, reorder, or duplicate format codes.",
            "",
            "Proper noun rules:",
            "- NPC names, place names, and character names: transliterate phonetically into Korean.",
            "- If a name is a single word with no common meaning (e.g. 'Eloisa', 'Razum-dar'), keep the original English or transliterate.",
            "- Do NOT wrap names in parentheses with both Korean and English like '베르미나(Vaermina)'.",
            "- Just use the Korean transliteration OR the original English name.",
        ]

        if self.glossary_context:
            lines.append("")
            lines.append("Glossary (use these exact translations):")
            for term, translation, _cat in self.glossary_context:
                lines.append(f"- {term} → {translation}")

        lines.append("")
        lines.append(f"Content category: {cat_desc}")

        return "\n".join(lines)

    def build_user_prompt(self) -> str:
        """[N] EN: ... / REF: ... 형식 유저 프롬프트."""
        n = len(self.items)
        lines = [
            f"Translate these {n} strings. For each, output ONLY the translation in the format:",
            "[N] KR: <translation>",
            "",
        ]

        for i, item in enumerate(self.items, 1):
            lines.append(f"[{i}] EN: {item.source}")
            if item.reference:
                lines.append(f"    REF: {item.reference}")

        return "\n".join(lines)

    def parse_response(self, raw: str) -> list[tuple[int, str]]:
        """응답 파싱. → [(item_index_0based, translation), ...]."""
        results: list[tuple[int, str]] = []
        for match in _RESPONSE_PATTERN.finditer(raw):
            idx = int(match.group(1)) - 1  # 1-based → 0-based
            translation = match.group(2).strip()
            if 0 <= idx < len(self.items):
                results.append((idx, translation))
        return results


# ---------------------------------------------------------------------------
# Translation Pipeline
# ---------------------------------------------------------------------------

_UNDO_CHUNK_SIZE = 5000


class TranslationPipeline:
    """번역 파이프라인 — prepare → run."""

    def __init__(
        self,
        db: LangDatabase,
        reference_db: LangDatabase | None,
        provider: LLMProvider,
        settings: TranslationSettings,
        *,
        progress_cb: Callable[[str, int, int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ):
        self._db = db
        self._reference_db = reference_db
        self._provider = provider
        self._settings = settings
        self._progress_cb = progress_cb
        self._cancel_check = cancel_check
        self._checker = SanityChecker()

    def _cancelled(self) -> bool:
        return self._cancel_check is not None and self._cancel_check()

    def _progress(self, stage: str, current: int, total: int) -> None:
        if self._progress_cb:
            self._progress_cb(stage, current, total)

    # ------------------------------------------------------------------
    # Prepare
    # ------------------------------------------------------------------

    def prepare_items(
        self,
        *,
        id_filter: int | None = None,
        where_clause: str = "",
        params: tuple = (),
    ) -> list[TranslationItem]:
        """미번역 고유 source 추출 + reference 매칭."""
        rows = self._db.get_untranslated_unique_sources(
            id_filter=id_filter,
            where_clause=where_clause,
            params=params,
        )
        items: list[TranslationItem] = []
        for rowid, group_id, source in rows:
            reference = ""
            if self._reference_db is not None:
                ref_keys = self._db.get_record_keys_by_source(source)
                if ref_keys:
                    ref_variants = self._reference_db.get_target_variants_for_record_keys(ref_keys)
                    if ref_variants:
                        best = ref_variants[0]["target"]
                        if best != source:
                            reference = best

            category = get_id_category(group_id)
            items.append(TranslationItem(
                rowid=rowid,
                source=source,
                reference=reference,
                group_id=group_id,
                category=category,
            ))
        return items

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self, items: list[TranslationItem]) -> TranslationSummary:
        """전체 파이프라인 실행 (동시 API 호출)."""
        summary = TranslationSummary(total_items=len(items))
        batch_size = self._settings.batch_size
        max_retries = self._settings.max_retries
        concurrency = 5  # 동시 API 호출 수

        # 용어집 후처리기 준비
        glossary_pp = None
        glossary_context_cache: list[tuple[str, str, str]] = []
        if self._settings.glossary_injection:
            all_sources = [item.source for item in items]
            glossary_context_cache = self._db.get_glossary_for_prompt(
                all_sources, max_terms=200,
            )
            translated_terms = [(t, tr) for t, tr, _c in glossary_context_cache if tr]
            if translated_terms:
                glossary_pp = GlossaryPostProcessor(translated_terms)

        # 배치 분할
        batches: list[list[TranslationItem]] = []
        for i in range(0, len(items), batch_size):
            batches.append(items[i:i + batch_size])

        total_batches = len(batches)
        all_results: list[TranslationResult] = []
        retry_queue: list[TranslationItem] = []
        sem = asyncio.Semaphore(concurrency)
        completed = 0

        async def process_batch(batch_items: list[TranslationItem]) -> list[TranslationResult]:
            nonlocal completed
            async with sem:
                if self._cancelled():
                    return []
                batch = TranslationBatch(batch_items, glossary_context_cache[:50])
                results = await self._translate_batch(batch, glossary_pp, summary)
                completed += 1
                self._progress("번역 중", completed, total_batches)
                return results

        # 동시 실행
        tasks = [process_batch(b) for b in batches]
        batch_results_list = await asyncio.gather(*tasks)

        for batch_items, results in zip(batches, batch_results_list):
            for result in results:
                if result.status == "ok":
                    all_results.append(result)
                    summary.ok_count += 1
                elif result.status == "failed":
                    failed_item = next(
                        (it for it in batch_items if it.rowid == result.rowid), None
                    )
                    if failed_item:
                        retry_queue.append(failed_item)

        # 재시도 처리 (순차)
        if retry_queue and not self._cancelled() and max_retries > 0:
            self._progress("재시도 중", 0, len(retry_queue))
            retry_batch_size = max(batch_size // 2, 5)
            retry_completed = 0
            retry_total = (len(retry_queue) + retry_batch_size - 1) // retry_batch_size
            for i in range(0, len(retry_queue), retry_batch_size):
                if self._cancelled():
                    break
                retry_items = retry_queue[i:i + retry_batch_size]
                batch = TranslationBatch(retry_items, glossary_context_cache[:50])
                retry_results = await self._translate_batch(
                    batch, glossary_pp, summary, attempt=2,
                )
                for result in retry_results:
                    if result.status == "ok":
                        all_results.append(result)
                        summary.ok_count += 1
                        summary.retry_count += 1
                    else:
                        summary.failed_count += 1
                retry_completed += 1
                self._progress("재시도 중", retry_completed, retry_total)

        # 남은 실패 카운트
        retried_rowids = {r.rowid for r in all_results if r.attempt > 1}
        not_retried = [it for it in retry_queue if it.rowid not in retried_rowids]
        summary.failed_count += len(not_retried)

        # DB 적용 (배치 최적화)
        if all_results and not self._cancelled():
            self._progress("DB 적용 중", 0, 1)
            applied = self._apply_results(all_results)
            summary.applied_count = applied

        self._progress("완료", total_batches, total_batches)
        return summary

    async def _translate_batch(
        self,
        batch: TranslationBatch,
        glossary_pp: GlossaryPostProcessor | None,
        summary: TranslationSummary,
        attempt: int = 1,
    ) -> list[TranslationResult]:
        """단일 배치 번역."""
        system_prompt = batch.build_system_prompt()
        user_prompt = batch.build_user_prompt()

        try:
            response: LLMResponse = await self._provider.translate(
                system_prompt, user_prompt,
            )
            summary.total_input_tokens += response.input_tokens
            summary.total_output_tokens += response.output_tokens
        except Exception:
            return [
                TranslationResult(
                    rowid=item.rowid,
                    source=item.source,
                    translation="",
                    status="failed",
                    flags=["API_ERROR"],
                    model=self._settings.active_model,
                    attempt=attempt,
                )
                for item in batch.items
            ]

        # 응답 파싱
        parsed = batch.parse_response(response.text)
        parsed_map = dict(parsed)

        results: list[TranslationResult] = []
        for i, item in enumerate(batch.items):
            translation = parsed_map.get(i)
            if translation is None:
                results.append(TranslationResult(
                    rowid=item.rowid,
                    source=item.source,
                    translation="",
                    status="failed",
                    flags=["PARSE_ERROR"],
                    model=response.model,
                    attempt=attempt,
                ))
                continue

            # 용어집 후처리
            if glossary_pp:
                translation = glossary_pp.apply(item.source, translation)

            # 자동 수정 (마커 중복/누락, 괄호 중첩 등)
            translation = SanityChecker.auto_fix(item.source, translation)

            # Sanity check
            flags = self._checker.check(item.source, translation)
            if flags:
                results.append(TranslationResult(
                    rowid=item.rowid,
                    source=item.source,
                    translation=translation,
                    status="failed",
                    flags=flags,
                    model=response.model,
                    attempt=attempt,
                ))
            else:
                results.append(TranslationResult(
                    rowid=item.rowid,
                    source=item.source,
                    translation=translation,
                    status="ok",
                    flags=[],
                    model=response.model,
                    attempt=attempt,
                ))

        return results

    def _apply_results(self, results: list[TranslationResult]) -> int:
        """번역 결과를 DB에 적용 + 중복 전파. 반영된 총 행 수 반환.

        최적화: batch_get_rowids_by_sources (1쿼리) + bulk_update (FTS 생략) + rebuild_fts.
        """
        ok_results = [r for r in results if r.status == "ok" and r.translation]
        if not ok_results:
            return 0

        # 중복 전파: source→rowids 매핑을 한 번에 조회
        if self._settings.auto_apply_duplicates:
            unique_sources = list({r.source for r in ok_results})
            source_to_rowids = self._db.batch_get_rowids_by_sources(unique_sources)
        else:
            source_to_rowids = {}

        # (rowid, translation) 리스트 구성
        seen: set[int] = set()
        updates: list[tuple[int, str]] = []
        for result in ok_results:
            if self._settings.auto_apply_duplicates:
                rowids = source_to_rowids.get(result.source, [result.rowid])
            else:
                rowids = [result.rowid]
            for rid in rowids:
                if rid not in seen:
                    seen.add(rid)
                    updates.append((rid, result.translation))

        if not updates:
            return 0

        # FTS 생략 벌크 업데이트 → 완료 후 FTS 재빌드
        count = self._db.bulk_update_targets_no_fts(updates)
        self._db.rebuild_fts()

        # 번역 진행 상태 업데이트
        progress_updates = [
            (r.rowid, "translated", r.model, r.attempt)
            for r in ok_results
        ]
        if progress_updates:
            self._db.batch_update_translation_progress(progress_updates)

        return count
