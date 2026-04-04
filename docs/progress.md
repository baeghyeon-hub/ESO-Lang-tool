# ESO Lang Tool - Phase 진행 현황

이 문서는 현재 구현 상태만 기록합니다.

- 장기 계획과 다음 단계: `../ROADMAP.md`
- 수정 / 패치 기록: `patch_notes.md`
- 실제 사용 방법: `usage.md`

기준 시점: `2026-03-29` (세션 4)

## 전체 상태

| Phase | 상태 | 현재 결과 |
|---|---|---|
| Phase 1 | 완료 | `.lang` 파서/빌더, DB, 검색 기반 완료 |
| Phase 2 | 완료 | 기본 GUI, 비동기 로딩, 검색/필터, 코덱 처리 완료 |
| Phase 2.5 | 완료 | 용어집 추출 엔진과 카테고리 분류 완료 |
| Phase 3 | 완료 | 편집, Undo/Redo, 저장, 일괄 치환, 다중 선택 편집 완료 |
| Phase 4 | 미구현 (보류) | XML export/import, merge 미리보기 — 개인 툴이므로 후순위 |
| Phase 5 | 완료 | LLM 번역 파이프라인, JSON 내보내기/가져오기 완료 |
| Phase 6 | 미구현 | diff, 진행률 시각화, 배포 편의 기능 필요 |
| Phase 7 | 완료 | 용어집 UI, en/kr 분리 추출, import/export, 용어 관리 완료 |
| Phase 8 | 미구현 | 자동 저장, 세션 복원, 저장 검증 필요 |

## 현재 완료 모듈

- `core/db.py`
- `core/db_glossary.py`
- `core/db_translation.py`
- `core/lang_parser.py`
- `core/lang_builder.py`
- `core/text_codec.py`
- `core/glossary.py`
- `core/undo.py`
- `core/find_replace.py`
- `core/config.py`
- `core/llm_providers.py`
- `core/translator.py`
- `core/export_import.py`
- `core/mod_tracker.py`
- `ui/main_window.py`
- `ui/secondary_db_mixin.py`
- `ui/reference_mixin.py`
- `ui/find_replace_mixin.py`
- `ui/export_mixin.py`
- `ui/record_table.py`
- `ui/group_tree.py`
- `ui/search_bar.py`
- `ui/editor_panel.py`
- `ui/dialogs.py`
- `ui/workers.py`
- `ui/theme.py`
- `ui/translate_panel.py`
- `ui/glossary_panel.py`

## 아직 남은 모듈

- `core/xml_handler.py`
- `core/merge.py`
- `core/session.py`
- `ui/diff_view.py`

## 테스트 상태

- 전체 테스트: `252 passed`
- 주요 범위
  - parser / builder / codec
  - db / model / glossary
  - undo / find_replace / editor_panel
  - main_window / dialogs
  - config / translator (sanity check, glossary, batch, pipeline)
  - export_import (roundtrip, error handling, modified export, diff export)
  - glossary_panel (en/kr extraction, fill_from_records, clear_existing)
  - mod_tracker (save/load cycle, merge, corrupted file)
  - batch_reference (크로스 매칭, 일괄 적용, 임시 테이블 필터, source text 매칭)

## Phase별 메모

### Phase 1

- `.lang` 파싱 / 빌드 완료
- SQLite in-memory 구조 완료
- FTS5 검색 완료

### Phase 2

- 메인 윈도우, 그룹 트리, 가상화 테이블 완료
- 비동기 로딩 / 저장 워커 완료
- 검색, 그룹, 상태 필터 조합 완료
- Identity / ESO KR Legacy 코덱 처리 완료

### Phase 2.5

- ID 기반 용어집 후보 추출 완료
- 성별 마커 / 문법 마커 처리 완료
- 카테고리 매핑과 집계 완료
- UESP 문서 기반 ID 추가 (SET_BONUS, SKILL_DESC, QUEST_JOURNAL, ZONE, BOOK_TEXT)
- 카테고리 계층 구조 (`CATEGORY_GROUPS`) 정의 완료

### Phase 3

- 단일 편집 / 다중 선택 일괄 편집 완료
- Undo / Redo 완료
- 저장 / 다른 이름으로 저장 완료
- Find / Replace 완료
- 같은 문자열 보기 / 행 모두 선택 완료
- 그룹 트리 카테고리별 계층 구조 (폴더 → 하위 ID) 완료
- 현재 범위 / 전체 기준 번역률 표시 완료
- 기존 번역 보기 조회창 완료
- 기존 KR 패치 + 현재 파일 + `en.lang` 원문 기준 묶음으로 번역 후보 조회 완료
- 조회창에서 선택한 번역문을 같은 `Source` 행 전체에 바로 적용할 수 있는 편집 흐름 완료
- 상태바 고대비 테마 적용 완료

### Phase 5 (LLM 번역 + Export/Import)

- LLM 번역 파이프라인 구현 완료
  - Gemini (`gemini-3-flash-preview`) 메인 프로바이더
  - `SanityChecker`: EMPTY, EN_IDENTICAL, LOW_KOREAN, TOO_SHORT/LONG, PLACEHOLDER_MISMATCH
  - `GlossaryPostProcessor`: 용어집 기반 후처리
  - `TranslationBatch`: 프롬프트 구성 + 응답 파싱
  - `TranslationPipeline`: `asyncio.gather` + `Semaphore(5)` 동시 호출
  - 성능 최적화: `batch_get_rowids_by_sources` (1쿼리), `bulk_update_targets_no_fts` + `rebuild_fts`
- 큐 기반 번역 워크플로우 완료
  - 테이블 우클릭 → "번역 대상 지정/해제"
  - 번역 탭에서 큐 확인 → 번역 시작
  - 미번역 건수, 고유 source 수, 예상 API 호출 수 표시
- JSON 내보내기/가져오기 완료
  - 선택 행 내보내기 (`Ctrl+Shift+E`)
  - 현재 필터 내보내기
  - 내가 수정한 항목만 내보내기 (`Ctrl+Shift+T`) — `modified=1` 플래그 기반
  - en.lang 비교 내보내기 (`Ctrl+Shift+D`) — 전체 번역분 (en source ≠ kr source)
  - 번역 가져오기 (`Ctrl+Shift+I`) — 모드 선택 (target 필드 / source 필드)
  - 우클릭 컨텍스트 메뉴에서도 내보내기 가능
- FTS5 검색 특수문자 오류 수정 (쿼리 이스케이프)
- DB 다중 ID 필터 지원 (`id_filter: int | list[int] | None`)

### Phase 7 (용어집 UI)

- `ui/glossary_panel.py` 신규: 하단 탭 "용어집" 패널
  - `GlossaryTableModel` — 가상화 테이블, 인라인 편집 (번역/메모)
  - 카테고리 필터 + 검색
  - 용어 추출 (en.lang + kr.lang 분리 매칭)
  - 초기화 후 재추출 / 추가 추출 선택 가능
  - 기존 번역 채우기 (records target → glossary translation)
  - 용어집 JSON import/export (UPSERT 로직)
  - 용어 수동 추가/삭제
  - 다크 테마 테이블 스타일링
- `core/glossary.py` 수정
  - `extract_glossary()` — en_db/kr_db 분리 파라미터, clear_existing 옵션
  - en.lang에서 영어 term, kr.lang에서 한글 translation 매칭 (`(id, unknown, idx)` 키)
  - 레거시 단독 DB 모드 호환
- LLM 번역 시 용어집 `translation` 필드가 프롬프트에 포함됨

### 수정 이력 추적

- `core/mod_tracker.py` 신규: 수정 이력 영구 보존
  - `.lang.mod.json` 사이드카 파일로 수정된 `(id, unknown, idx)` 키 저장
  - 파일 저장 시 자동 기록, 파일 로드 시 자동 복원
  - 세션 간 이력 병합 (union)
  - 임시 테이블 JOIN 방식으로 대량 복원 최적화

### 기존 번역 일괄 적용

- "기존 번역 일괄 적용" (`Ctrl+Shift+R`)
  - 2단계 매칭: `(id, unknown, idx)` 키 기반 + source text 기반
  - 키 매칭 실패 시 en.lang/kr.lang 기반 영어→한글 텍스트 맵으로 보완
  - 미번역 레코드에 기존 번역을 Target으로 일괄 복사
  - 이미 Target이 있는 항목은 보존
- 필터 "기존 번역 있음" — 레퍼런스에 번역이 있는 미번역 행만 표시
  - 임시 테이블(`_ref_filter`) 기반 필터링

### 성능 최적화

- 파일 열기 시 참조 DB(en.lang/kr.lang) lazy 로드 (탭 전환 또는 기능 사용 시 최초 1회)
- 로딩 시 용어집 자동 추출 제거 (사용자 수동 추출로 변경)
- `get_source_targets_by_rowids()` — 500개 청크 분할로 SQL 변수 초과 방지
- `load_mod_keys()` — 개별 UPDATE → 임시 테이블 JOIN UPDATE + 인덱스
- 에디터 다중 선택 — 최대 500행 제한 (성능 보호)
- LoadWorker 단계별 디버그 로그 추가 (로딩 병목 진단용)

### main_window.py 리팩터링

- `main_window.py` 2214줄 → 1229줄 (44% 축소)
- Mixin 패턴으로 기능 영역별 분리
  - `ui/secondary_db_mixin.py` (~160줄): 보조 DB 경로 탐색, 로드/해제, lazy 초기화
  - `ui/reference_mixin.py` (~350줄): 소스 조회, 기존 번역 크로스 매칭, 일괄 적용
  - `ui/find_replace_mixin.py` (191줄): 일괄 치환 다이얼로그, 스코프 관리, 업데이트 수집
  - `ui/export_mixin.py` (~230줄): JSON 내보내기/가져오기 (선택/필터/수정/비교/가져오기)

### db.py 리팩터링

- `core/db.py` 954줄 → ~700줄 (26% 축소)
- Mixin 패턴으로 도메인별 분리
  - `core/db_glossary.py` (~85줄): 용어집 CRUD + 프롬프트용 조회
  - `core/db_translation.py` (~120줄): LLM 번역 파이프라인용 쿼리 (진행 추적, 배치 처리)
- UI 레이어 `_conn` 직접 접근 제거
  - `reference_mixin.py`, `export_mixin.py`에서 `_db._conn.execute()` 호출을 공용 API로 교체
  - 추가된 공용 API: `get_source_by_key`, `get_translated_pairs`, `get_untranslated_records`, `get_all_records_keys_sources`, `populate_ref_filter`, `bulk_apply_translations`, `get_modified_count`
  - `_model._build_where()` → `_model.get_filter_context()` 공용 API로 교체

## 다음 우선순위

1. Phase 6: diff / 시각화 / 배포
2. Phase 8: 자동 저장 + 세션 복원
3. Phase 4: XML export/import + merge (보류)
