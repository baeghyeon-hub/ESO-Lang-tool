# ESO Lang Tool - 수정 / 패치 노트

이 문서는 버그 수정, 리팩터링, UX 개선만 기록합니다.

- 장기 계획: `../ROADMAP.md`
- 현재 Phase 상태: `progress.md`
- 사용법: `usage.md`

## 2026-03-27

### 편집 UX

- `Shift` / `Ctrl` 다중 선택 편집 추가
- 다중 선택 편집 중 다른 행으로 이동해도 변경이 조용히 버려지지 않도록 자동 커밋 보강
- 같은 `Source` / `Target` 우클릭 포커스와 일괄 선택 추가
- exact 문자열 포커스가 상태 탭 전환과 충돌하지 않도록 해제 흐름 수정

### 검색 / 기존 번역 보기

- `기존 번역 보기` 조회창 추가
- 현재 편집본의 `Target` 번역문 집계 추가
- 기존 KR 패치 참조 집계 추가
- `kr.lang`을 열어둔 상태에서도 `en.lang` 기준 원문 묶음으로 다시 연결해 후보를 찾도록 보강
- 한글 후보가 있으면 원문과 동일한 영어 후보는 우선순위에서 제외
- 조회창에서 선택한 번역문을 현재 편집칸에 넣는 것뿐 아니라 같은 `Source` 행을 자동 선택하도록 연결

### 진행률 / 상태바

- 전체 행 기준 번역률 추가
- 전체 원문 기준 번역률 추가
- 현재 필터 / 그룹 범위 기준 진행률 추가
- 수정 건수와 수정 글자 수 집계 추가
- 상태바 색상을 노란 배경 + 검은 글씨로 변경해 가독성 개선

### 구조 개선

- `main_window.py`에 공용 guard 데코레이터 도입
- `SearchBar`, `LoadWorker`, `RecordTableModel`, `LangDatabase`의 public API 정리
- `db.py` 연결 캡슐화와 타입 힌트 정리
- `undo.py` redo 경로 상한 처리 보강
- `editor_panel.py` 상태를 dataclass로 정리

### 문서 정리

- `ROADMAP.md`: 계획 전용
- `docs/progress.md`: 현재 진행 상태 전용
- `docs/patch_notes.md`: 패치 기록 전용
- `docs/usage.md`: 사용법 전용

### 테스트

- `tests/test_db.py`
  - 진행률 / 중복 번역 요약 / 레코드 키 기반 집계 검증 추가
- `tests/test_dialogs.py`
  - 기존 번역 조회창 기본 동작 검증 추가
- `tests/test_editor_panel.py`
  - 다중 선택 자동 커밋 회귀 테스트 추가
- `tests/test_main_window.py`
  - QAction 인자 처리
  - stale editor reset
  - 기존 번역 조회 요약
  - `kr.lang` + `en.lang` canonical 묶음 조회
  - 조회창 번역 선택 후 같은 `Source` 자동 선택

현재 전체 테스트 기준: `156 passed`

## 2026-03-28

### LLM 번역 파이프라인 (Phase 5)

- `core/config.py` 신규: 번역 설정 관리 (JSON 영속화, 프로바이더별 API 키/모델)
- `core/llm_providers.py` 신규: LLM 프로바이더 추상화 (Gemini 구현, `google-genai` SDK)
- `core/translator.py` 신규: 번역 엔진
  - `SanityChecker` 5종 검증 (EMPTY, EN_IDENTICAL, LOW_KOREAN, TOO_SHORT/LONG, PLACEHOLDER_MISMATCH)
  - `GlossaryPostProcessor` 용어집 후처리 (최장 일치 우선)
  - `TranslationBatch` 프롬프트 구성 + 응답 파싱
  - `TranslationPipeline` 동시 호출 (`asyncio.gather` + `Semaphore(5)`)
- `ui/translate_panel.py` 신규: 큐 기반 번역 UI
  - 테이블 우클릭 → "번역 대상 지정/해제" 컨텍스트 메뉴
  - 번역 탭에서 큐 상태 확인 (미번역 건수, 고유 source 수, 예상 API 호출)
  - 모델/배치/옵션 설정 + API 키 다이얼로그

### 성능 최적화

- API 호출: 순차 → `asyncio.gather` + `Semaphore(5)` 동시 5건 (48배치 10분 → ~2분)
- DB 조회: 개별 `get_rowids_by_source` 950회 → `batch_get_rowids_by_sources` 1회 (temp table JOIN)
- DB 적용: 개별 FTS sync → `bulk_update_targets_no_fts` + `rebuild_fts` 1회 (30분+ → 수초)

### JSON 내보내기/가져오기

- `core/export_import.py` 신규
  - JSON 형식: `[{id, unknown, idx, source, target}, ...]`
  - `export_records()` 선택 행 내보내기
  - `export_filtered()` 현재 필터 전체 내보내기
  - `import_records()` 키 매칭 가져오기 (Undo 지원, 확인 다이얼로그)
- 파일 메뉴: 선택 행 내보내기 (`Ctrl+Shift+E`), 현재 필터 내보내기, 번역 가져오기 (`Ctrl+Shift+I`)
- 우클릭 컨텍스트 메뉴에 "선택 행 내보내기" 추가

### 그룹 트리 계층 구조 개편

- 플랫 리스트 449개 → 카테고리별 폴더 구조
  - 📜 퀘스트, ⚔ 아이템, 👤 NPC, ✦ 스킬, 🗺 장소, ★ 수집품, 🏆 업적, 📖 로어, ⚙ 기타, 미분류
- 폴더 클릭 → 해당 카테고리 전체 ID 필터 (다중 ID 지원)
- UESP 문서 기반 5개 ID 추가: SET_BONUS, SKILL_DESC, QUEST_JOURNAL, ZONE(162658389), BOOK_TEXT
- `core/glossary.py`에 `CATEGORY_GROUPS` 계층 정의 추가
- `core/db.py` `id_filter` 타입을 `int | list[int] | None`으로 확장

### 버그 수정

- FTS5 검색 시 작은따옴표 등 특수문자로 `syntax error` 발생 → 토큰별 큰따옴표 이스케이프 + fallback
- `_update_stats` → `_update_edit_stats` 메서드명 불일치 수정
- QAction `triggered` 시그널의 `checked` 인자 처리 누락 수정
- `group_tree.py` 내부 모델 변수명 변경 후 `main_window.py` 참조 불일치 수정

### 테스트

- `tests/test_config.py` 신규: 설정 roundtrip, 기본값, 손상 파일 복구 (6건)
- `tests/test_translator.py` 신규: SanityChecker, GlossaryPostProcessor, TranslationBatch, Pipeline E2E (23건)
- `tests/test_export_import.py` 신규: export/import roundtrip, 에러 핸들링 (9건)

현재 전체 테스트 기준: `194 passed`

## 2026-03-28 (세션 2)

### 용어집 UI (Phase 7)

- `ui/glossary_panel.py` 신규: 하단 탭 "용어집" 패널
  - `GlossaryTableModel` — 가상화 테이블, 번역/메모 인라인 편집
  - 카테고리 필터 콤보박스 + 검색
  - 용어 수동 추가/삭제
  - 다크 테마 테이블 스타일링 (대체행 색상, 헤더, 선택 색상)
- 용어집 내보내기 형식 선택: 단일 JSON / 카테고리별 폴더 (영>한 쌍번역)
- 용어집 JSON import/export (UPSERT 로직)
- 하단 탭에 "용어집" 탭 추가 (`Ctrl+G`)

### 용어집 추출 개선

- `extract_glossary()` 리팩터링: `en_db` + `kr_db` 분리 파라미터
  - en.lang에서 영어 term 추출, kr.lang에서 한글 translation 매칭
  - `(id, unknown, idx)` 키로 크로스 매칭
  - 레거시 단독 DB 모드 호환 유지
- `clear_existing` 파라미터 추가: 초기화 후 재추출 지원
- 추출 버튼 클릭 시 "초기화 후 재추출 / 추가 추출 / 취소" 3가지 선택
- `fill_glossary_from_records()`: records의 기존 target으로 빈 번역 자동 채움

### 수정 이력 영구 추적

- `core/mod_tracker.py` 신규
  - `.lang.mod.json` 사이드카 파일로 수정된 `(id, unknown, idx)` 키 영구 저장
  - 파일 저장 시 자동 기록 (기존 이력과 병합)
  - 파일 로드 시 자동 복원 (상태바에 복원 건수 표시)
  - 임시 테이블 JOIN 방식으로 대량 복원 최적화

### 내보내기 기능 확장

- "내가 수정한 항목만 내보내기" (`Ctrl+Shift+T`)
  - `modified=1` 레코드만 JSON 내보내기
  - en.lang이 있으면 source를 영어 원문으로 교체
  - 수정 이력이 세션 간 보존되므로 이전 작업분도 포함
- "en.lang 비교 내보내기" (`Ctrl+Shift+D`)
  - en source ≠ kr source인 항목 전체 (한패 전체 번역분)
  - target이 있으면 target 우선, 없으면 kr source 사용
- `export_modified()`, `export_diff()` 함수 신규

### 가져오기 모드 선택

- "번역 가져오기" 시 모드 선택 다이얼로그 추가
  - **target 필드 사용**: 일반 번역 가져오기
  - **source 필드 사용**: en.lang 원문을 Target에 덮어쓰기 (한글→영어 복원)
- `import_records()` — `use_source_as_target` 파라미터 추가

### 성능 최적화

- 로딩 시 용어집 자동 추출 제거 (워커에서 `extract_glossary` 호출 삭제)
- `get_source_targets_by_rowids()` — 500개 청크 분할 (SQL 변수 초과 크래시 수정)
- `load_mod_keys()` — 개별 UPDATE → 임시 테이블 JOIN UPDATE
- 에디터 다중 선택 시 최대 500행 제한 (성능 보호)
- `_reset_ui`에서 export/import 메뉴 비활성화 누락 수정

### 버그 수정

- `sqlite3.OperationalError: too many SQL variables` — 대량 선택 시 크래시
- 용어집 테이블 대체행 색상이 다크 테마에서 텍스트 안 보이는 문제 수정
- 용어집 EN 컬럼에 한글이 표시되던 문제 (en_db/kr_db 분리 추출로 해결)
- en.lang에서 내보낸 JSON을 가져올 때 "변경 없음" 되던 문제 (source→target 모드 추가)

### 테스트

- `tests/test_glossary_panel.py`: en/kr 추출, clear_existing, fill_from_records 등 16건
- `tests/test_export_import.py`: modified export, diff export, roundtrip 등 20건
- `tests/test_mod_tracker.py`: save/load cycle, merge, corrupted file 등 8건

현재 전체 테스트 기준: `229 passed`

## 2026-03-28 (세션 3)

### 기존 번역 일괄 적용

- "기존 번역 일괄 적용" 메뉴 추가 (`Ctrl+Shift+R`)
  - 레퍼런스 DB(kr.lang)와 `(id, unknown, idx)` 키로 크로스 매칭
  - 미번역 레코드에만 기존 번역을 Target으로 일괄 복사
  - 이미 Target이 있는 항목은 보존 (덮어쓰기 방지)
  - 적용된 레코드는 `modified=1` 자동 설정
- 필터 "기존 번역 있음" 추가 (검색바 필터 콤보)
  - 레퍼런스에 번역이 존재하는 미번역 레코드만 테이블에 표시
  - 임시 테이블(`_ref_filter`) 기반 효율적 필터링
  - 일괄 적용 전 대상 확인용

### 성능 최적화 (무한 로딩 수정)

- 파일 열기 시 `_ensure_reference_db()`, `_ensure_base_db()`를 **lazy 로드**로 변경
  - 기존: 파일 열기 직후 메인 스레드에서 en.lang/kr.lang 동기 파싱 → UI 멈춤
  - 변경: 번역/용어집 탭 전환 시 또는 기능 사용 시 최초 1회 로드
- `load_mod_keys()` 임시 테이블에 인덱스 추가 (대량 이력 복원 성능 개선)
- LoadWorker에 단계별 디버그 로그 추가 (로딩 병목 진단용)

### 테스트

- `tests/test_batch_reference.py` 신규: 레퍼런스 크로스 매칭, 일괄 적용, 임시 테이블 필터 7건

현재 전체 테스트 기준: `236 passed`

## 2026-03-29

### 기존 번역 일괄 적용 개선

- 2단계 매칭으로 확장: `(id, unknown, idx)` 키 기반 + source text 기반
  - 1단계: 키 직접 매칭 (기존 동작)
  - 2단계: 키 매칭 실패한 미번역 행에 대해 en.lang/kr.lang 텍스트 맵으로 보완
  - en.lang 영어 원문 + kr.lang 한글 번역을 키로 연결해 `영어→한글` 맵 빌드
  - 현재 DB에서 이미 번역된 같은 source의 target도 활용
- "기존 번역 있음" 필터에도 동일한 2단계 매칭 적용

### main_window.py 리팩터링

- `main_window.py` 2214줄 → 1229줄 (44% 축소)
- Mixin 패턴으로 기능 영역별 분리
  - `ui/secondary_db_mixin.py` (~160줄): 보조 DB 경로 탐색, 로드/해제, lazy 초기화
  - `ui/reference_mixin.py` (~350줄): 소스 조회, 크로스 매칭, 일괄 적용
  - `ui/find_replace_mixin.py` (191줄): 일괄 치환 다이얼로그, 업데이트 수집
  - `ui/export_mixin.py` (~230줄): JSON 내보내기/가져오기
- `MainWindow(SecondaryDbMixin, ReferenceMixin, FindReplaceMixin, ExportImportMixin, QMainWindow)` 다중 상속

### db.py 리팩터링

- `core/db.py` 954줄 → ~700줄 (26% 축소)
- Mixin 패턴으로 도메인별 분리
  - `core/db_glossary.py` (~85줄): 용어집 CRUD (glossary_count, get/search/update/categories, get_glossary_for_prompt)
  - `core/db_translation.py` (~120줄): LLM 번역 파이프라인 (unique sources, rowids by source, 배치 처리, 진행 추적)
- `LangDatabase(GlossaryMixin, TranslationMixin)` 다중 상속

### UI 레이어 커플링 제거

- `reference_mixin.py`에서 `_db._conn.execute()` 직접 접근 전부 제거
  - `_build_reference_map` → `ref_db.get_all_records_keys_sources()`
  - `_build_source_text_translation_map` → `self._db.get_source_by_key()`
  - `_apply_reference_filter` → `self._db.populate_ref_filter()`
  - `_batch_apply_reference` → `self._db.bulk_apply_translations()`
- `export_mixin.py`에서 `_db._conn.execute()` 및 `_model._build_where()` 접근 제거
  - `_export_modified` → `self._db.get_modified_count()`
  - `_export_filtered` → `self._model.get_filter_context()`
- `secondary_db_mixin.py`로 DB 수명주기 분리 (경로 탐색, 로드/해제, lazy 초기화)

### 테스트

- `tests/test_batch_reference.py`: source text 매칭 테스트 3건 추가 (13건)
  - 키가 다른 경우 en.lang 경유 매칭
  - 키 매칭 우선순위 확인
  - 현재 DB 기존 번역 활용

현재 전체 테스트 기준: `252 passed`
