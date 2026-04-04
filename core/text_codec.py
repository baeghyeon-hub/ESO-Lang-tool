"""
텍스트 코덱 — .lang 파일의 문자열 변환 계층.

ESO 한글패치에는 두 가지 방식이 있다:

1. Legacy (CJK 우회): 한글을 CJK 코드포인트로 치환하여 저장하고,
   커스텀 폰트로 CJK → 한글 렌더링하는 구조.
2. Native (한글 직접): 순수 한글 유니코드로 직접 저장하고,
   한글 폰트 애드온으로 ESO 클라이언트에서 렌더링.

이 모듈은 파일 저장 형식과 앱 표시 형식을 분리하는 codec 레이어.

흐름:
  .lang raw text → decode(codec) → 앱 표시 → 편집 → encode(codec) → .lang 저장

코드포인트 매핑 (EsoKR.lua con2CNKR() 기반, Legacy만 해당):
  Encode (한글 → CJK 저장):
    U+1100~U+11FF (한글 자모)        → +0x4D00 → U+5E00~U+5EFF
    U+3131~U+318F (한글 호환 자모)    → +0x2DD0 → U+5F01~U+5F5F
    U+AC00~U+D7A3 (한글 음절)        → -0x3E00 → U+6E00~U+99A3

  Decode (CJK 저장 → 한글):
    U+5E00~U+5EFF → -0x4D00 → U+1100~U+11FF
    U+5F01~U+5F5F → -0x2DD0 → U+3131~U+318F
    U+6E00~U+99A3 → +0x3E00 → U+AC00~U+D7A3
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class TextCodec(ABC):
    """텍스트 변환 코덱 인터페이스."""

    name: str

    @abstractmethod
    def decode(self, text: str) -> str:
        """저장 형식(raw) → 표시 형식(display)."""

    @abstractmethod
    def encode(self, text: str) -> str:
        """표시 형식(display) → 저장 형식(raw)."""


class IdentityCodec(TextCodec):
    """변환 없음 — en.lang 등 일반 파일용."""

    name = "identity"

    def decode(self, text: str) -> str:
        return text

    def encode(self, text: str) -> str:
        return text


class EsoKrLegacyCodec(TextCodec):
    """ESO 기존 한글패치 코덱 — CJK ↔ 한글 코드포인트 치환.

    EsoKR.lua의 con2CNKR() 로직을 코드포인트 레벨로 변환.
    Lua는 UTF-8 바이트 concat 후 산술 연산하지만,
    Python에서는 str.translate()로 코드포인트 단위 변환 (훨씬 빠름).
    """

    name = "eso_kr_legacy"

    def __init__(self):
        # str.translate()용 변환 테이블 사전 빌드
        self._decode_table = self._build_decode_table()
        self._encode_table = self._build_encode_table()

    @staticmethod
    def _build_decode_table() -> dict[int, int]:
        """CJK 저장 → 한글 표시 변환 테이블."""
        table: dict[int, int] = {}

        # U+5E00~U+5EFF → -0x4D00 → U+1100~U+11FF (한글 자모)
        for cp in range(0x5E00, 0x5F00):
            table[cp] = cp - 0x4D00

        # U+5F01~U+5F5F → -0x2DD0 → U+3131~U+318F (한글 호환 자모)
        for cp in range(0x5F01, 0x5F60):
            table[cp] = cp - 0x2DD0

        # U+6E00~U+99A3 → +0x3E00 → U+AC00~U+D7A3 (한글 음절)
        for cp in range(0x6E00, 0x99A4):
            table[cp] = cp + 0x3E00

        return table

    @staticmethod
    def _build_encode_table() -> dict[int, int]:
        """한글 표시 → CJK 저장 변환 테이블."""
        table: dict[int, int] = {}

        # U+1100~U+11FF → +0x4D00 → U+5E00~U+5EFF (한글 자모)
        for cp in range(0x1100, 0x1200):
            table[cp] = cp + 0x4D00

        # U+3131~U+318F → +0x2DD0 → U+5F01~U+5F5F (한글 호환 자모)
        for cp in range(0x3131, 0x3190):
            table[cp] = cp + 0x2DD0

        # U+AC00~U+D7A3 → -0x3E00 → U+6E00~U+99A3 (한글 음절)
        for cp in range(0xAC00, 0xD7A4):
            table[cp] = cp - 0x3E00

        return table

    def decode(self, text: str) -> str:
        """CJK 저장 문자열 → 한글 표시 문자열."""
        return text.translate(self._decode_table)

    def encode(self, text: str) -> str:
        """한글 표시 문자열 → CJK 저장 문자열."""
        return text.translate(self._encode_table)


class EsoKrNativeCodec(TextCodec):
    """ESO 한글 네이티브 코덱 — 순수 한글 유니코드 직접 저장.

    한글 폰트 애드온으로 ESO 클라이언트에서 직접 렌더링하는 방식.
    텍스트 변환 없이 한글 유니코드를 그대로 저장/표시한다.
    필터 로직은 eso_kr_legacy와 동일 (has_korean 기반 미번역 판정).
    """

    name = "eso_kr_native"

    def decode(self, text: str) -> str:
        return text

    def encode(self, text: str) -> str:
        return text


# ── 코덱 레지스트리 ──

_CODECS: dict[str, type[TextCodec]] = {
    "identity": IdentityCodec,
    "eso_kr_legacy": EsoKrLegacyCodec,
    "eso_kr_native": EsoKrNativeCodec,
}


def get_codec(name: str) -> TextCodec:
    """이름으로 코덱 인스턴스 생성."""
    cls = _CODECS.get(name)
    if cls is None:
        raise ValueError(f"Unknown codec: {name!r}")
    return cls()


def is_kr_codec(codec_name: str) -> bool:
    """한글 kr.lang 계열 코덱인지 판별.

    eso_kr_legacy와 eso_kr_native 모두 has_korean() 기반
    미번역 판정을 사용하는 한글 코덱이다.
    """
    return codec_name in ("eso_kr_legacy", "eso_kr_native")


def suggest_codec(sample_texts: list[str], sample_size: int = 2000) -> str:
    """샘플 텍스트를 분석하여 코덱을 추천.

    ESO KR legacy 패치의 특징:
    - 한글 문자가 거의 없음 (0%)
    - U+6E00~U+99A3 범위 CJK 문자가 비정상적으로 높음
    - 영문, 숫자, 구두점은 그대로 존재

    ESO KR native 패치의 특징:
    - 순수 한글 유니코드(U+AC00~U+D7A3) 비율이 높음
    - CJK 치환 문자 없음
    - 한글 폰트 애드온으로 직접 렌더링

    Returns:
        추천 코덱 이름 ("identity", "eso_kr_legacy", "eso_kr_native")
    """
    kr_cjk_count = 0
    hangul_count = 0
    total_chars = 0

    for text in sample_texts[:sample_size]:
        for ch in text:
            cp = ord(ch)
            total_chars += 1

            # ESO KR legacy 인코딩 범위
            if (0x5E00 <= cp <= 0x5EFF
                    or 0x5F01 <= cp <= 0x5F5F
                    or 0x6E00 <= cp <= 0x99A3):
                kr_cjk_count += 1
            # 일반 한글 범위
            elif (0xAC00 <= cp <= 0xD7A3
                    or 0x3131 <= cp <= 0x318F
                    or 0x1100 <= cp <= 0x11FF):
                hangul_count += 1

    if total_chars == 0:
        return "identity"

    cjk_ratio = kr_cjk_count / total_chars
    hangul_ratio = hangul_count / total_chars

    # CJK 변환 범위 비율이 5% 이상이고 한글이 거의 없으면 legacy codec
    if cjk_ratio > 0.05 and hangul_count == 0:
        return "eso_kr_legacy"

    # 한글 비율이 5% 이상이고 CJK 치환이 없으면 native codec
    if hangul_ratio > 0.05 and kr_cjk_count == 0:
        return "eso_kr_native"

    return "identity"
