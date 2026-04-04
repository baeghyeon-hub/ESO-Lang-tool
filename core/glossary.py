"""
용어집 추출 엔진

.lang 레코드에서 용어집을 자동 추출:
- ID 기반 카테고리 분류 (NPC, ITEM, SKILL, LOCATION 등)
- 성별 마커 파싱 (^F, ^M, ^N → gender 컬럼)
- 중복 제거 (term+category UNIQUE)
- usage_count 집계

사용법:
    extract_glossary(db)  # records 테이블 → glossary 테이블
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.db import LangDatabase


# ---------------------------------------------------------------------------
# ID → 카테고리 매핑
# ---------------------------------------------------------------------------

# en.lang 실측 데이터 기반. 용어집에 적합한 "이름" 성격의 ID만 포함.
# 설명문/대사/저널 등 긴 텍스트 ID는 제외.
ID_CATEGORY_MAP: dict[int, str] = {
    # ── NPC 이름 (77k) — 성별 마커 포함 ──
    8290981: "NPC",
    90431749: "NPC",

    # ── 아이템 이름 (155k) — 장비명, 무기명 ──
    242841733: "ITEM",

    # 아이템 설명 (27k)
    228378404: "ITEM_DESC",

    # 세트 이름 (UESP 문서)
    38727365: "SET_BONUS",

    # ── 스킬/어빌리티 이름 (150k) — 내부명 혼재, 필터 필요 ──
    198758357: "SKILL",

    # 스킬 이름 (정제, 399건) — 얼티밋/액티브 스킬
    17915077: "SKILL",
    96962005: "SKILL_LINE",
    61854549: "PASSIVE",

    # 어빌리티 설명 (UESP 문서)
    132143172: "SKILL_DESC",

    # ── 퀘스트 ──
    87370069: "QUEST_OBJ",
    52420949: "QUEST_NAME",
    267697733: "QUEST_ITEM",
    7949764: "QUEST_STEP",
    265851556: "QUEST_JOURNAL",

    # ── 장소/POI 이름 (14k) ──
    164009093: "LOCATION",
    10860933: "PLACE",
    28666901: "WAYSHRINE",
    267200725: "ZONE",
    162658389: "ZONE",         # UESP 문서
    81344020: "POI",
    39619172: "OBJECT",

    # ── 수집품 이름 (12k) — 탈것, 펫, 의상 ──
    18173141: "COLLECTIBLE",
    96069573: "PET",

    # 수집품 카테고리 이름 (13k)
    112701171: "COLLECTIBLE_CAT",

    # 수집품 설명 (12k)
    211640654: "COLLECTIBLE_DESC",

    # ── 업적 이름 (10k) ──
    172030117: "ACHIEVEMENT",
    12529189: "ACHIEVEMENT",

    # ── 로어북 (UESP 문서) ──
    51188213: "LORE",
    21337012: "BOOK_TEXT",

    # ── 인터랙션 동사 (12k) — Enter, Search, Talk 등 ──
    74865733: "INTERACTION",

    # ── 염료 이름 (418) ──
    208337109: "DYE",

    # ── 보물 지도 (477) ──
    39160885: "TREASURE_MAP",

    # ── 칭호 / 보상 ──
    5759525: "TITLE",
    191189508: "REWARD",

    # ===================================================================
    # 대화/대사 (NPC 대화, 선택지, NPC 대사 스크립트 등)
    # ===================================================================
    149328292: "DIALOGUE",      # 60k — NPC 잡담/아이들 대사
    204987124: "DIALOGUE",      # 58k — NPC 대화 응답
    200879108: "DIALOGUE",      # 53k — NPC 대화 본문
    55049764: "DIALOGUE",       # 43k — NPC 대화
    115740052: "DIALOGUE",      # 40k — NPC 스크립트 대사 ("says:" 포함)
    228103012: "DIALOGUE",      # 28k — 플레이어 대화 선택지
    165399380: "DIALOGUE",      # 6k — NPC 인사/잡담
    3952276: "DIALOGUE",        # 7k — 퀘스트 제공 대사
    20958740: "DIALOGUE",       # 7k — 대화 수락/거절
    116521668: "DIALOGUE",      # 4k — NPC 대사
    249936564: "DIALOGUE",      # 4k — NPC 대사
    66848564: "DIALOGUE",       # 2k — NPC 대사
    75236676: "DIALOGUE",       # 2k — 이하 NPC 앰비언트 반응 대사
    75237444: "DIALOGUE",
    75238212: "DIALOGUE",
    75240772: "DIALOGUE",
    75241540: "DIALOGUE",
    75242308: "DIALOGUE",
    75244868: "DIALOGUE",
    75245636: "DIALOGUE",
    75246404: "DIALOGUE",
    75248964: "DIALOGUE",
    75249732: "DIALOGUE",
    75250500: "DIALOGUE",
    75253060: "DIALOGUE",
    75253828: "DIALOGUE",
    75254596: "DIALOGUE",
    75257156: "DIALOGUE",
    75257924: "DIALOGUE",
    75258692: "DIALOGUE",
    75261252: "DIALOGUE",
    75262020: "DIALOGUE",
    75262788: "DIALOGUE",
    75265348: "DIALOGUE",
    75266116: "DIALOGUE",
    75266884: "DIALOGUE",
    149979604: "DIALOGUE",
    149983700: "DIALOGUE",
    149987796: "DIALOGUE",
    149991892: "DIALOGUE",
    149995988: "DIALOGUE",
    150000084: "DIALOGUE",
    150004180: "DIALOGUE",
    150008276: "DIALOGUE",
    150045140: "DIALOGUE",
    150049236: "DIALOGUE",
    150053332: "DIALOGUE",
    150057428: "DIALOGUE",
    150061524: "DIALOGUE",
    150065620: "DIALOGUE",
    150069716: "DIALOGUE",
    150073812: "DIALOGUE",
    150962644: "DIALOGUE",
    150966740: "DIALOGUE",
    150970836: "DIALOGUE",
    150974932: "DIALOGUE",
    150979028: "DIALOGUE",
    150983124: "DIALOGUE",
    150987220: "DIALOGUE",
    150991316: "DIALOGUE",

    # ===================================================================
    # 퀘스트 관련 (저널 텍스트, 목표, 대화 분기)
    # ===================================================================
    103224356: "QUEST_DESC",     # 25k — 퀘스트 단계 설명/저널
    232026500: "QUEST_DESC",     # 4k — 퀘스트 설명
    121487972: "QUEST_DESC",     # 4k — 퀘스트 목표 텍스트
    108566804: "QUEST_DESC",     # 579 — 퀘스트 완료 요약
    129979412: "QUEST_DESC",     # 570 — 퀘스트 목표 요약
    63937076: "QUEST_DESC",      # 311 — 퀘스트 단계 설명
    66737390: "QUEST_DESC",      # 455 — 퀘스트 시작 안내
    39248996: "QUEST_DESC",      # 739 — 퀘스트 태스크 추적

    # ===================================================================
    # 게임 시스템 / UI 텍스트
    # ===================================================================
    108533454: "UI_ACTION",      # 7k — 액션 프롬프트 (Collecting..., Opening...)
    162946485: "UI_SYSTEM",      # 19k — 얼라이언스/PvP 조건 텍스트
    139139780: "UI_SYSTEM",      # 5k — 오브젝트 설명
    168675493: "UI_SYSTEM",      # 5k — 이벤트/인카운터 이름
    188155806: "UI_SYSTEM",      # 4k — 업적 조건 텍스트
    206046340: "UI_SYSTEM",      # 3k — 상태효과 설명
    239939829: "UI_SYSTEM",      # 2k — 내부 템플릿
    26811173: "UI_SYSTEM",       # 1k — 시길/오브젝트 이름
    41714900: "UI_SYSTEM",       # 1k — 요구사항/조건 텍스트
    255457492: "UI_SYSTEM",      # 323 — 사용 프롬프트
    37288388: "UI_SYSTEM",       # 177 — 전투 조작 안내
    224768149: "UI_SYSTEM",      # 175 — 전투 상태 텍스트

    # ===================================================================
    # 크라운 스토어 / 상점
    # ===================================================================
    171157587: "CROWN_STORE",    # 10k — 수집품 검색 태그
    52183620: "CROWN_STORE",     # 2k — 수집품 획득 방법
    70328405: "CROWN_STORE",     # 676 — 코스튬 팩 이름
    263796174: "CROWN_STORE",    # 646 — 코스튬 팩 설명
    217086453: "CROWN_STORE",    # 474 — 스토어 배너/공지
    123229230: "CROWN_STORE",    # 469 — 스토어 설명
    88890974: "CROWN_STORE",     # 220 — 어시스턴트 설명
    247756773: "CROWN_STORE",    # 220 — 어시스턴트 이름
    173340693: "CROWN_STORE",    # 216 — 스토어 카테고리
    79246725: "CROWN_STORE",     # 144 — 스토어 섹션
    99281989: "CROWN_STORE",     # 62 — 스토어 이벤트 배너

    # ===================================================================
    # 던전 / 인스턴스
    # ===================================================================
    268015829: "DUNGEON",        # 666 — 던전 이름
    40552436: "DUNGEON",         # 579 — 던전/탐험 힌트
    180959717: "DUNGEON",        # 92 — 던전 변형 이름

    # ===================================================================
    # PvP / 시로딜
    # ===================================================================
    19398485: "PVP",             # 4k — 포탈/길드홀
    106474997: "PVP",            # 346 — 트랜시터스 네트워크
    155022052: "PVP",            # 342 — 트랜시터스 설명
    160227428: "PVP",            # 153 — 트랜시터스 설명 변형
    157886597: "PVP",            # 118 — 요새 이름
    238195765: "PVP",            # 136 — 얼라이언스 데이터
    121975845: "PVP",            # 133 — 얼라이언스 이름
    257983733: "PVP",            # 125 — PvP 관련 이름
    58548677: "PVP",             # 72 — PvP 업적/킬 카운트

    # ===================================================================
    # 이벤트
    # ===================================================================
    125518133: "EVENT",          # 666 — 이벤트 이름 (New Life Festival 등)
    108965317: "EVENT",          # 693 — 이벤트 목표 템플릿
    150586484: "EVENT",          # 693 — 이벤트 목표 설명

    # ===================================================================
    # 제작 / 재료
    # ===================================================================
    200697509: "CRAFTING",       # 3k — 재료 이름 (Dagger, Axe 등)
    99527054: "CRAFTING",        # 3k — 제작 직업명
    214390738: "CRAFTING",       # 1k — 재료명 (문법 마커 포함)
    41983653: "CRAFTING",        # 693 — 재료명
    61533042: "CRAFTING",        # 680 — 재료명 (문법 마커)
    241484741: "CRAFTING",       # 592 — 장비 무게 (Light, Medium, Heavy)
    76200101: "CRAFTING",        # 90 — 제작 직업 이름
    102906708: "CRAFTING",       # 86 — 인챈트/특성 효과

    # ===================================================================
    # 튜토리얼 / 도움말
    # ===================================================================
    86601028: "TUTORIAL",        # 673 — 전투 튜토리얼
    235850260: "TUTORIAL",       # 129 — 스킬 포인트 안내
    131421317: "TUTORIAL",       # 68 — 도움말 카테고리
    51540085: "TUTORIAL",        # 116 — 보상 선택지

    # ===================================================================
    # 에모트 / 커맨드
    # ===================================================================
    151638485: "EMOTE",          # 650 — 슬래시 커맨드 (/torch 등)
    139475237: "EMOTE",          # 733 — 에모트 설명
    3427285: "EMOTE",            # 204 — 에모트/아이들 이름

    # ===================================================================
    # 하우징
    # ===================================================================
    169578494: "HOUSING",        # 216 — 주택 설명
    60008005: "HOUSING",         # 217 — 주택 상태
    11547061: "HOUSING",         # 170 — 주택 방 이름
    41262789: "HOUSING",         # 66 — 가구 카테고리

    # ===================================================================
    # 로어 수집
    # ===================================================================
    236931909: "LORE_CAT",       # 208 — 로어 카테고리명
    8379076: "LORE_CAT",         # 202 — 로어 수집 설명

    # ===================================================================
    # 업적 관련 (추가)
    # ===================================================================
    87522148: "ACHIEVEMENT",     # 317 — 업적 칭호 조합
    186232436: "ACHIEVEMENT",    # 317 — 업적 칭호 조합
    215700677: "ACHIEVEMENT",    # 317 — 업적 이름
    221887989: "ACHIEVEMENT",    # 317 — 업적 이름

    # ===================================================================
    # 컴패니언
    # ===================================================================
    167432014: "COMPANION",      # 64 — 컴패니언 호감도 텍스트

    # ===================================================================
    # 지역 설명
    # ===================================================================
    70901198: "ZONE_DESC",       # 1k — 지역 설명문

    # ===================================================================
    # 스크라이빙
    # ===================================================================
    135139941: "SCRIBING",       # 67 — 스크라이빙 데미지 타입
    236900164: "SCRIBING",       # 67 — 스크라이빙 효과 설명
    168238324: "SCRIBING",       # 67 — 스크라이빙 획득 방법
    72660740: "SCRIBING",        # 319 — 스크라이빙 스킬 효과
    192403557: "SCRIBING",       # 104 — 스크라이빙 스킬 이름
    151931684: "SCRIBING",       # 60 — 스크라이빙 보너스

    # ===================================================================
    # NPC 관련 추가
    # ===================================================================
    191999749: "NPC",            # 849 — NPC 직업/역할 (Imperial Soldier 등)
    251649717: "NPC",            # 250 — NPC 이름 (성별 마커 포함)

    # ===================================================================
    # 기타 식별 가능 ID
    # ===================================================================
    224875171: "CROWN_STORE",    # 2k — 탈것 태그
    33425332: "UI_SYSTEM",       # 2k
    219317028: "UI_SYSTEM",      # 2k
    15453358: "UI_SYSTEM",       # 2k
    256430276: "UI_SYSTEM",      # 1k
    146361138: "UI_SYSTEM",      # 1k
    263004526: "UI_SYSTEM",      # 1k
    184479092: "UI_SYSTEM",      # 264 — 음표/음악 기호
    152988005: "UI_SYSTEM",      # 237 — 국가명 (지역 설정)
    115337253: "UI_SYSTEM",      # 218 — UI 탭 이름
    260523861: "UI_SYSTEM",      # 141 — POI 종류 이름
    98383029: "UI_SYSTEM",       # 150 — 종족 이름
    42041397: "UI_SYSTEM",       # 119 — 뱀파이어/늑대인간 관련
    129382708: "UI_SYSTEM",      # 118 — 뱀파이어/늑대인간 설명
    68561141: "UI_SYSTEM",       # 504 — 빈 플레이스홀더
    77659573: "UI_SYSTEM",       # 412 — 테스트/QA 텍스트
    148355781: "UI_SYSTEM",      # 396
    196014052: "UI_SYSTEM",      # 378
    211899940: "UI_SYSTEM",      # 433
    205344756: "UI_SYSTEM",      # 340
    225762485: "UI_SYSTEM",      # 334
    40741187: "UI_SYSTEM",       # 990
    8158238: "UI_SYSTEM",        # 780
    50040644: "UI_SYSTEM",       # 752
    73074773: "UI_SYSTEM",       # 743
    187173764: "UI_SYSTEM",      # 710
    150525940: "UI_SYSTEM",      # 482
    62156964: "UI_SYSTEM",       # 470
    51188660: "UI_SYSTEM",       # 3k — 템플릿 변수
    70307621: "UI_SYSTEM",       # 2k
    12912341: "UI_SYSTEM",       # 2k

    # ===================================================================
    # 수집품/스토어 추가
    # ===================================================================
    54595589: "CROWN_STORE",     # 59 — 크라운 아이템
    249464990: "CROWN_STORE",    # 53 — 스토어 이벤트 설명
    68494373: "CRAFTING",        # 235 — 아이템 종류 태그
}

CATEGORY_DESCRIPTION_MAP: dict[str, str] = {
    "NPC": "NPC 이름",
    "ITEM": "아이템 이름",
    "ITEM_DESC": "아이템 설명",
    "SET_BONUS": "세트 장비 이름",
    "SKILL": "스킬/어빌리티",
    "SKILL_LINE": "스킬 라인",
    "SKILL_DESC": "어빌리티 설명",
    "PASSIVE": "패시브 설명",
    "QUEST_OBJ": "퀘스트 오브젝트 이름",
    "QUEST_STEP": "퀘스트 단계/목표",
    "QUEST_NAME": "퀘스트 이름",
    "QUEST_ITEM": "퀘스트 아이템",
    "QUEST_JOURNAL": "퀘스트 저널",
    "QUEST_DESC": "퀘스트 설명/요약",
    "LOCATION": "장소/길드/시설 이름",
    "PLACE": "세부 장소 이름",
    "WAYSHRINE": "웨이슈라인",
    "ZONE": "지역/존 이름",
    "ZONE_DESC": "지역 설명",
    "POI": "주요 지점(POI)",
    "OBJECT": "오브젝트/상호작용 물체",
    "COLLECTIBLE": "탈것/의상 등 수집품",
    "COLLECTIBLE_CAT": "수집품 카테고리",
    "COLLECTIBLE_DESC": "수집품 설명",
    "PET": "펫 이름",
    "ACHIEVEMENT": "업적 이름/문구",
    "LORE": "로어북/책 제목",
    "BOOK_TEXT": "책 본문",
    "LORE_CAT": "로어 카테고리",
    "INTERACTION": "대화/상호작용 프롬프트",
    "DYE": "염료 이름",
    "TREASURE_MAP": "보물 지도",
    "TITLE": "칭호",
    "REWARD": "보상 이름",
    "DIALOGUE": "NPC 대사/대화",
    "UI_ACTION": "액션 프롬프트",
    "UI_SYSTEM": "시스템/UI 텍스트",
    "CROWN_STORE": "크라운 스토어",
    "DUNGEON": "던전/인스턴스",
    "PVP": "PvP/시로딜",
    "EVENT": "이벤트",
    "CRAFTING": "제작/재료",
    "TUTORIAL": "튜토리얼/도움말",
    "EMOTE": "에모트/커맨드",
    "HOUSING": "하우징/가구",
    "COMPANION": "컴패니언",
    "SCRIBING": "스크라이빙",
    "UNCLASSIFIED": "미분류 ID",
}

# ---------------------------------------------------------------------------
# 카테고리 → 상위 그룹 (트리 계층 구조)
# ---------------------------------------------------------------------------

# 순서대로 표시됨
CATEGORY_GROUPS: list[tuple[str, str, list[str]]] = [
    ("대화", "💬", [
        "DIALOGUE",
    ]),
    ("퀘스트", "📜", [
        "QUEST_NAME", "QUEST_STEP", "QUEST_OBJ", "QUEST_ITEM",
        "QUEST_JOURNAL", "QUEST_DESC",
    ]),
    ("아이템", "⚔", [
        "ITEM", "ITEM_DESC", "SET_BONUS", "TREASURE_MAP",
    ]),
    ("NPC", "👤", [
        "NPC", "COMPANION",
    ]),
    ("스킬", "✦", [
        "SKILL", "SKILL_LINE", "SKILL_DESC", "PASSIVE", "SCRIBING",
    ]),
    ("장소", "🗺", [
        "ZONE", "ZONE_DESC", "LOCATION", "PLACE", "WAYSHRINE", "POI", "OBJECT",
        "DUNGEON",
    ]),
    ("수집품", "★", [
        "COLLECTIBLE", "COLLECTIBLE_CAT", "COLLECTIBLE_DESC", "PET", "DYE",
    ]),
    ("업적", "🏆", [
        "ACHIEVEMENT", "TITLE", "REWARD",
    ]),
    ("로어", "📖", [
        "LORE", "BOOK_TEXT", "LORE_CAT",
    ]),
    ("제작", "🔨", [
        "CRAFTING",
    ]),
    ("크라운 스토어", "👑", [
        "CROWN_STORE",
    ]),
    ("PvP", "⚔", [
        "PVP",
    ]),
    ("하우징", "🏠", [
        "HOUSING",
    ]),
    ("시스템", "⚙", [
        "INTERACTION", "UI_ACTION", "UI_SYSTEM", "TUTORIAL",
        "EMOTE", "EVENT",
    ]),
]

# 그룹에 속하지 않는 분류된 카테고리는 "기타"로
_GROUPED_CATEGORIES: set[str] = set()
for _, _, cats in CATEGORY_GROUPS:
    _GROUPED_CATEGORIES.update(cats)

# 용어집 추출 대상 카테고리 (짧은 이름 위주)
# DESC류와 긴 텍스트는 기본 추출에서 제외
GLOSSARY_CATEGORIES = {
    "NPC", "ITEM", "SKILL", "QUEST_OBJ", "LOCATION",
    "COLLECTIBLE", "ACHIEVEMENT", "LORE", "INTERACTION",
    "DYE", "TREASURE_MAP",
}


# ---------------------------------------------------------------------------
# 성별 마커 파싱
# ---------------------------------------------------------------------------

_GENDER_PATTERN = re.compile(r"\^([FMN])$")

# 아이템에 사용되는 ^p, ^n 등은 성별이 아니라 문법 마커
_ITEM_GRAMMAR_PATTERN = re.compile(r"\^[a-z]$")


def parse_gender_marker(text: str) -> tuple[str, str]:
    """텍스트에서 성별 마커를 분리.

    Returns:
        (clean_name, gender) — gender는 "F"/"M"/"N"/""
    """
    m = _GENDER_PATTERN.search(text)
    if m:
        return text[: m.start()], m.group(1)
    return text, ""


def strip_grammar_marker(text: str) -> str:
    """아이템명의 문법 마커(^p, ^n 등) 제거."""
    m = _ITEM_GRAMMAR_PATTERN.search(text)
    if m:
        return text[: m.start()]
    return text


# ---------------------------------------------------------------------------
# 추출 필터
# ---------------------------------------------------------------------------

def _is_valid_term(text: str, category: str) -> bool:
    """용어집에 포함할 만한 텍스트인지 판단."""
    if not text or len(text) < 2:
        return False

    # 내부 개발용 텍스트 제외
    if text.startswith(("QAT ", "JUST ", "GM ", "Tool - ", "DEBUG")):
        return False
    if text.startswith("This ") and category in ("QUEST_STEP",):
        # "This appears in the quest tracker..." 같은 메타 설명 제외
        return False

    # 순수 숫자/기호
    if text.strip("0123456789 .-+") == "":
        return False

    # 너무 긴 텍스트는 용어가 아님 (200자 초과)
    if len(text) > 200:
        return False

    return True


# ---------------------------------------------------------------------------
# 메인 추출
# ---------------------------------------------------------------------------

def extract_glossary(
    db: "LangDatabase",
    *,
    en_db: "LangDatabase | None" = None,
    kr_db: "LangDatabase | None" = None,
    categories: set[str] | None = None,
    cancel_check: callable = None,
    clear_existing: bool = False,
) -> dict:
    """용어집을 추출하여 glossary 테이블에 저장.

    두 가지 모드:
    1. en_db + kr_db 제공: en.lang에서 영어 term, kr.lang에서 한글 translation
       (id, unknown, idx) 키로 매칭
    2. en_db/kr_db 없음: db 자체에서 source=term, target=translation (레거시)

    Args:
        db: 용어집을 저장할 LangDatabase
        en_db: 영어 원문 DB (en.lang). None이면 db를 영어 원본으로 사용
        kr_db: 한글 번역 DB (kr.lang). None이면 db를 번역 소스로 사용
        categories: 추출할 카테고리 집합 (None이면 GLOSSARY_CATEGORIES 사용)
        cancel_check: 취소 확인 콜백
        clear_existing: True이면 기존 용어집을 삭제 후 재추출

    Returns:
        {"total_extracted": int, "categories": dict[str, int]}
    """
    db.init_glossary()

    if clear_existing:
        db.execute("DELETE FROM glossary")
        db.commit()

    source_db = en_db or db
    trans_db = kr_db or db

    target_cats = categories or GLOSSARY_CATEGORIES

    target_ids = [
        (rid, cat) for rid, cat in ID_CATEGORY_MAP.items()
        if cat in target_cats
    ]

    if not target_ids:
        return {"total_extracted": 0, "categories": {}}

    # kr_db에서 (id, unknown, idx) → source(한글) 매핑 빌드
    # (en_db와 kr_db가 다른 DB인 경우에만 필요)
    kr_map: dict[tuple[int, int, int], str] | None = None
    if en_db is not None and trans_db is not en_db:
        kr_map = {}
        for record_id, _ in target_ids:
            rows = trans_db.execute(
                "SELECT id, unknown, idx, source FROM records "
                "WHERE id = ? AND source != ''",
                (record_id,),
            ).fetchall()
            for rid, unk, idx, kr_source in rows:
                kr_map[(rid, unk, idx)] = kr_source

    cat_counts: dict[str, int] = {}
    term_data: dict[tuple[str, str], dict] = {}

    for record_id, category in target_ids:
        if cancel_check and cancel_check():
            break

        # 영어 원문 DB에서 조회
        rows = source_db.execute(
            "SELECT rowid, id, unknown, idx, source FROM records "
            "WHERE id = ? AND source != ''",
            (record_id,),
        ).fetchall()

        for rowid, rid, unk, idx, en_source in rows:
            if cancel_check and cancel_check():
                break

            # 성별 마커 처리
            if category == "NPC":
                term, gender = parse_gender_marker(en_source)
            elif category == "ITEM":
                term = strip_grammar_marker(en_source)
                gender = ""
            else:
                term = en_source
                gender = ""

            term = term.strip()

            if not _is_valid_term(term, category):
                continue

            # 한글 번역 찾기
            translation = ""
            if kr_map is not None:
                translation = kr_map.get((rid, unk, idx), "")
            else:
                # 레거시: db 자체의 target 사용
                target_row = source_db.execute(
                    "SELECT target FROM records WHERE rowid = ?", (rowid,)
                ).fetchone()
                if target_row:
                    translation = target_row[0] or ""

            key = (term, category)
            if key in term_data:
                term_data[key]["usage_count"] += 1
                # 더 나은 번역이 있으면 갱신 (비어있던 것 → 있는 것)
                if translation and not term_data[key]["translation"]:
                    term_data[key]["translation"] = translation
            else:
                term_data[key] = {
                    "gender": gender,
                    "usage_count": 1,
                    "source_id": rowid,
                    "translation": translation,
                }
                cat_counts[category] = cat_counts.get(category, 0) + 1

    # 일괄 삽입
    if term_data:
        batch = [
            (term, d["translation"], cat, d["gender"], d["usage_count"], d["source_id"])
            for (term, cat), d in term_data.items()
        ]
        db.executemany(
            "INSERT OR IGNORE INTO glossary "
            "(term, translation, category, gender, usage_count, source_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            batch,
        )
        db.commit()

    total = sum(cat_counts.values())
    return {"total_extracted": total, "categories": cat_counts}


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def get_glossary_stats(db: "LangDatabase") -> dict:
    """용어집 통계 반환."""
    db.init_glossary()
    total = db.execute("SELECT count(*) FROM glossary").fetchone()[0]
    translated = db.execute(
        "SELECT count(*) FROM glossary WHERE translation != ''"
    ).fetchone()[0]
    categories = db.execute(
        "SELECT category, count(*) FROM glossary GROUP BY category ORDER BY count(*) DESC"
    ).fetchall()
    return {
        "total": total,
        "translated": translated,
        "categories": dict(categories),
    }


def fill_glossary_from_records(db: "LangDatabase") -> dict:
    """records 테이블의 기존 번역(target)으로 용어집 translation을 채움.

    glossary.term과 records.source가 일치하는 항목 중
    records.target이 비어있지 않은 것을 용어집 translation에 반영.
    이미 translation이 있는 항목은 건너뜀.

    Returns:
        {"filled": int, "skipped_existing": int, "no_match": int}
    """
    db.init_glossary()

    # 번역이 비어있는 용어집 항목만 가져옴
    empty_terms = db.execute(
        "SELECT rowid, term, category FROM glossary WHERE translation = ''"
    ).fetchall()

    if not empty_terms:
        return {"filled": 0, "skipped_existing": 0, "no_match": 0}

    filled = 0
    no_match = 0

    # term → records.source 매칭하여 target 가져오기
    # 카테고리별 ID를 알고 있으므로 해당 ID의 records만 조회
    for rowid, term, category in empty_terms:
        # 해당 카테고리의 ID 목록
        cat_ids = [rid for rid, cat in ID_CATEGORY_MAP.items() if cat == category]

        best_target = ""
        if cat_ids:
            # 해당 ID의 records에서 source가 term과 일치 (또는 term+성별마커)하는 것 탐색
            placeholders = ",".join("?" * len(cat_ids))
            rows = db.execute(
                f"SELECT target FROM records "
                f"WHERE id IN ({placeholders}) AND target != '' "
                f"AND (source = ? OR source LIKE ?)"
                f"ORDER BY length(target) DESC LIMIT 1",
                (*cat_ids, term, f"{term}^%"),
            ).fetchall()
            if rows:
                best_target = rows[0][0]

        if not best_target:
            # 카테고리 무관하게 source = term인 번역 찾기
            row = db.execute(
                "SELECT target FROM records WHERE source = ? AND target != '' LIMIT 1",
                (term,),
            ).fetchone()
            if row:
                best_target = row[0]

        if best_target:
            db.execute(
                "UPDATE glossary SET translation = ? WHERE rowid = ?",
                (best_target, rowid),
            )
            filled += 1
        else:
            no_match += 1

    db.commit()

    skipped = db.execute(
        "SELECT count(*) FROM glossary WHERE translation != ''"
    ).fetchone()[0] - filled

    return {"filled": filled, "skipped_existing": max(0, skipped), "no_match": no_match}


def get_id_category(record_id: int) -> str:
    """ID의 카테고리 코드를 반환."""
    return ID_CATEGORY_MAP.get(record_id, "UNCLASSIFIED")


def get_id_category_description(record_id: int) -> str:
    """ID의 사용자용 카테고리 설명을 반환."""
    category = get_id_category(record_id)
    return CATEGORY_DESCRIPTION_MAP.get(category, "미분류 ID")
