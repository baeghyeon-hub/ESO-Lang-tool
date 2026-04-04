# ESO Lang Tool - 로드맵

이 문서는 **앞으로의 제품 방향과 단계별 계획**만 다룹니다.

- 현재 구현 상태와 완료 여부: `docs/progress.md`
- 수정/버그픽스/리팩터링 내역: `docs/patch_notes.md`
- 실제 사용 방법: `docs/usage.md`

## 프로젝트 목표

ESO(Elder Scrolls Online)의 `.lang` 바이너리 파일을 현대적인 GUI 환경에서 직접 열고,
검색·편집·병합·저장을 한 흐름 안에서 처리하는 한글화 도구를 만드는 것이 목표다.

핵심 방향은 다음과 같다.

- 대용량 `.lang` 파일도 즉시 다룰 수 있는 성능
- 반복 문장과 대량 수정 작업에 강한 편집 UX
- XML 분업, 병합, diff, 세션 복원까지 포함한 작업 안전성
- 용어집과 LLM 파이프라인까지 이어지는 확장성

## 제품 방향

| 영역 | 목표 |
|------|------|
| UI/UX | 오래된 Win32 스타일이 아닌, 대형 데이터 편집에 적합한 모던 다크 UI |
| 검색 | 실시간 검색, 정규식, 상태 필터, 그룹 필터를 함께 쓰는 다중 필터 UX |
| 편집 | 단일 편집, 다중 선택 편집, 일괄 치환, 반복 문자열 빠른 묶음 |
| 안정성 | Undo/Redo, 미저장 가드, 자동 저장, 세션 복원 |
| 협업 | XML export/import, 병합 미리보기, 외부 작업물 재적용 |
| 확장 | 용어집, diff, 번역 자동화, LLM 검수 파이프라인 |

## 목표 워크플로우

1. `.lang` 파일을 연다.
2. 검색, 그룹, 상태 필터를 조합해 번역 대상을 좁힌다.
3. 단일 편집, 다중 선택 편집, 일괄 치환으로 번역을 진행한다.
4. 필요하면 XML로 내보내 외부 도구나 분업 워크플로우에 넘긴다.
5. XML을 다시 불러와 병합한다.
6. 검증 후 `.lang` 파일로 저장한다.
7. 이후 용어집, diff, LLM 보조 번역으로 확장한다.

## 아키텍처 방향

### 데이터 저장

- `SQLite :memory:` 기반 레코드 저장
- 대용량 `.lang` 데이터는 Python 객체 컬렉션이 아니라 DB 쿼리로 접근
- FTS5를 사용한 전문 검색

### 파서 / 빌더

- `.lang` 파서는 빠른 로딩이 우선
- 빌더는 string dedup과 offset 공유를 지원
- 텍스트 코덱 레이어로 파일 저장 형식과 화면 표시 형식을 분리

### 편집 모델

- `core/`는 GUI 독립 로직
- `ui/`는 Qt 위젯과 상호작용에 집중
- Undo/Redo는 diff-patch 방식으로 메모리 상한 내에서 관리

### 확장 레이어

- XML export/import
- 세션 백업/복원
- 용어집
- 비교(diff)
- LLM 번역 및 검수

## 모듈 방향

### `core/`

- `db.py`: 레코드/검색/편집/통계 DB API
- `db_glossary.py`: 용어집 DB mixin
- `db_translation.py`: LLM 번역 파이프라인 DB mixin
- `lang_parser.py`: `.lang` 파싱
- `lang_builder.py`: `.lang` 빌드
- `text_codec.py`: 코덱 추상화
- `undo.py`: Undo/Redo 스택 관리
- `find_replace.py`: 일괄 치환 엔진
- `xml_handler.py`: XML export/import
- `merge.py`: 병합 엔진
- `session.py`: 자동 저장, 세션 복원
- `glossary.py`: 용어집 추출/적용
- `translator.py`: LLM 번역 파이프라인
- `config.py`: 번역 설정 관리
- `llm_providers.py`: LLM 프로바이더 추상화
- `export_import.py`: JSON 내보내기/가져오기
- `mod_tracker.py`: 수정 이력 추적 (사이드카 파일)

### `ui/`

- `main_window.py`: 메인 윈도우, 전체 흐름 제어
- `secondary_db_mixin.py`: 보조 DB 경로 탐색, 로드/해제, lazy 초기화
- `reference_mixin.py`: 소스 조회, 기존 번역 크로스 매칭, 일괄 적용
- `find_replace_mixin.py`: 일괄 치환 기능
- `export_mixin.py`: JSON 내보내기/가져오기
- `record_table.py`: 가상화 테이블 + 필터 모델
- `group_tree.py`: 그룹/카테고리 트리
- `search_bar.py`: 검색/필터 UI
- `editor_panel.py`: 단일/다중 편집 패널
- `dialogs.py`: 치환/병합/설정 대화상자
- `workers.py`: 로드/저장 백그라운드 워커
- `diff_view.py`: 비교 화면
- `glossary_panel.py`: 용어집 UI
- `translate_panel.py`: 번역 자동화 UI
- `theme.py`: 테마와 스타일시트

## 단계별 계획

### Phase 1: Core 엔진

목표:

- `.lang` 파싱/빌드
- DB 스키마와 검색 API
- 라운드트립 검증

완료 기준:

- 실제 `.lang` 파일을 로드하고 다시 저장할 수 있다.
- 검색과 편집용 DB API가 준비되어 있다.

### Phase 2: 기본 GUI + 파일 로딩 + 검색

목표:

- 메인 윈도우, 그룹 트리, 테이블, 검색바 구성
- 비동기 파일 로딩과 취소
- 검색/필터 조합

완료 기준:

- `.lang` 파일을 앱에서 열고, 검색/필터링하며 탐색할 수 있다.

### Phase 2.5: 용어집 추출 엔진

목표:

- ID 기반 자동 용어 추출
- 성별/문법 마커 정리
- 카테고리 분류와 집계

완료 기준:

- 로딩된 데이터에서 용어집 후보를 빠르게 생성할 수 있다.

### Phase 3: 편집 + Undo

목표:

- 테이블 인라인 편집
- 하단 편집 패널
- 다중 선택 편집
- 일괄 치환
- 저장과 Undo/Redo
- 기존 번역 참조 및 일괄 적용

완료 기준:

- 앱 안에서 실사용 가능한 번역 편집 흐름이 완성된다.

### Phase 4: XML 입출력 + 병합

목표:

- XML export/import
- 단일/분할 내보내기
- 병합 엔진과 미리보기

완료 기준:

- 외부 작업물을 XML로 주고받고, 충돌 여부를 보고 병합할 수 있다.

### Phase 5: LLM 번역 + Export/Import ✅ 완료

목표:

- LLM 번역 파이프라인 (Gemini 메인)
- Sanity Check + 용어집 후처리
- 큐 기반 번역 워크플로우
- JSON 내보내기/가져오기

완료 기준:

- 선택 행을 큐에 넣어 LLM 번역을 실행하고, JSON으로 내보내/가져올 수 있다.

### Phase 6: 고급 기능

목표:

- `.lang` diff 뷰
- 그룹별 진행률 시각화
- 북마크/메모
- 단축키 커스터마이즈
- 배포 패키징

완료 기준:

- 실전 작업 편의성과 배포성이 강화된다.

### Phase 7: 용어집 UI + 적용 기능 ✅ 완료

목표:

- 용어집 조회/검색/수정 UI
- 용어집 import/export
- en.lang + kr.lang 분리 추출
- 수정 이력 영구 추적

완료 기준:

- 추출된 용어집을 실제 편집 워크플로우 안에서 관리하고 재사용할 수 있다.

### Phase 8: 안전장치

목표:

- 저장 후 검증
- 자동 저장
- 세션 복원

완료 기준:

- 비정상 종료나 저장 실패 상황에서도 작업을 복원하거나 검증할 수 있다.

## 후속 우선순위

로드맵 기준으로 다음 큰 마일스톤은 아래 순서다.

1. Phase 6: diff, 시각화, 배포
2. Phase 8: 자동 저장과 세션 복원
3. Phase 4: XML 입출력과 병합 (보류 — 개인 툴이므로 후순위)
