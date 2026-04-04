"""core/text_codec.py 단위 테스트 — 코덱 변환 + 라운드트립 검증."""

import pytest
from pathlib import Path
from core.text_codec import (
    IdentityCodec, EsoKrLegacyCodec, get_codec, suggest_codec,
)


# ── 실제 kr.lang 파일 경로 ──
KR_LANG_PATH = Path(r"C:\Users\user\project_eso\기존 ESO 한글패치\kr.lang")


class TestIdentityCodec:
    def test_decode_passthrough(self):
        codec = IdentityCodec()
        assert codec.decode("Hello World") == "Hello World"

    def test_encode_passthrough(self):
        codec = IdentityCodec()
        assert codec.encode("Hello World") == "Hello World"

    def test_roundtrip(self):
        codec = IdentityCodec()
        text = "Test 123 !@#"
        assert codec.decode(codec.encode(text)) == text


class TestEsoKrLegacyCodec:
    """EsoKrLegacyCodec 코드포인트 변환 검증."""

    @pytest.fixture
    def codec(self):
        return EsoKrLegacyCodec()

    # ── 한글 음절 (U+AC00~U+D7A3) ──

    def test_encode_hangul_syllable(self, codec):
        """'가' (U+AC00) → U+6E00."""
        encoded = codec.encode("가")
        assert ord(encoded) == 0x6E00

    def test_decode_hangul_syllable(self, codec):
        """U+6E00 → '가' (U+AC00)."""
        decoded = codec.decode(chr(0x6E00))
        assert decoded == "가"

    def test_encode_last_syllable(self, codec):
        """'힣' (U+D7A3) → U+99A3."""
        encoded = codec.encode("힣")
        assert ord(encoded) == 0x99A3

    def test_decode_last_syllable(self, codec):
        """U+99A3 → '힣' (U+D7A3)."""
        decoded = codec.decode(chr(0x99A3))
        assert decoded == "힣"

    def test_encode_common_syllables(self, codec):
        """일상 한글 음절 변환."""
        text = "가나다라마바사"
        encoded = codec.encode(text)
        # 전부 CJK 범위에 있어야 함
        for ch in encoded:
            cp = ord(ch)
            assert 0x6E00 <= cp <= 0x99A3, f"U+{cp:04X} out of range"

    # ── 한글 호환 자모 (U+3131~U+318F) ──

    def test_encode_compat_jamo(self, codec):
        """'ㄱ' (U+3131) → U+5F01."""
        encoded = codec.encode("ㄱ")
        assert ord(encoded) == 0x5F01

    def test_decode_compat_jamo(self, codec):
        """U+5F01 → 'ㄱ' (U+3131)."""
        decoded = codec.decode(chr(0x5F01))
        assert decoded == "ㄱ"

    def test_encode_compat_jamo_last(self, codec):
        """'㆏' (U+318F) → U+5F5F."""
        encoded = codec.encode(chr(0x318F))
        assert ord(encoded) == 0x5F5F

    # ── 한글 자모 (U+1100~U+11FF) ──

    def test_encode_jamo(self, codec):
        """U+1100 → U+5E00."""
        encoded = codec.encode(chr(0x1100))
        assert ord(encoded) == 0x5E00

    def test_decode_jamo(self, codec):
        """U+5E00 → U+1100."""
        decoded = codec.decode(chr(0x5E00))
        assert ord(decoded) == 0x1100

    # ── 비한글 문자 통과 ──

    def test_encode_ascii_passthrough(self, codec):
        """영문/숫자/구두점은 그대로."""
        text = "Hello World 123 !@#"
        assert codec.encode(text) == text

    def test_decode_ascii_passthrough(self, codec):
        text = "Hello World 123 !@#"
        assert codec.decode(text) == text

    def test_encode_gender_markers(self, codec):
        """^F, ^M, ^N 성별 마커는 그대로."""
        text = "^F^M^N"
        assert codec.encode(text) == text

    def test_encode_mixed(self, codec):
        """한글 + 영문 혼합."""
        text = "Hello 세계!"
        encoded = codec.encode(text)
        # "Hello "는 그대로, "세계"는 변환, "!"는 그대로
        assert encoded.startswith("Hello ")
        assert encoded.endswith("!")
        assert len(encoded) == len(text)

    # ── 라운드트립 ──

    def test_roundtrip_encode_decode(self, codec):
        """encode → decode 라운드트립."""
        text = "안녕하세요 Hello World! 가나다 ㄱㄴㄷ"
        assert codec.decode(codec.encode(text)) == text

    def test_roundtrip_decode_encode(self, codec):
        """decode → encode 라운드트립."""
        # CJK로 인코딩된 "가나다" 시뮬레이션
        raw = chr(0x6E00) + chr(0x6E02) + chr(0x6E04)  # 가, 나 근처
        assert codec.encode(codec.decode(raw)) == raw

    def test_roundtrip_full_syllable_range(self, codec):
        """전체 한글 음절 범위 라운드트립."""
        # 처음, 중간, 마지막 음절
        syllables = "가나다힘힣"
        assert codec.decode(codec.encode(syllables)) == syllables

    def test_roundtrip_empty(self, codec):
        assert codec.decode(codec.encode("")) == ""

    def test_roundtrip_only_ascii(self, codec):
        text = "Pure ASCII text 123"
        assert codec.decode(codec.encode(text)) == text


class TestGetCodec:
    def test_get_identity(self):
        codec = get_codec("identity")
        assert isinstance(codec, IdentityCodec)

    def test_get_eso_kr_legacy(self):
        codec = get_codec("eso_kr_legacy")
        assert isinstance(codec, EsoKrLegacyCodec)

    def test_get_eso_kr_native(self):
        from core.text_codec import EsoKrNativeCodec
        codec = get_codec("eso_kr_native")
        assert isinstance(codec, EsoKrNativeCodec)

    def test_get_unknown(self):
        with pytest.raises(ValueError):
            get_codec("nonexistent")


class TestSuggestCodec:
    def test_empty_texts(self):
        assert suggest_codec([]) == "identity"

    def test_english_texts(self):
        texts = ["Hello World", "Dragon", "Quest completed"]
        assert suggest_codec(texts) == "identity"

    def test_korean_texts(self):
        """일반 한글 텍스트 → eso_kr_native (한글 직접 저장 방식)."""
        texts = ["안녕하세요", "세계", "퀘스트 완료"]
        assert suggest_codec(texts) == "eso_kr_native"

    def test_mixed_english_korean_below_threshold(self):
        """한글 비율이 5% 미만이면 identity."""
        texts = ["Hello World", "Dragon", "Quest completed", "한"]
        assert suggest_codec(texts) == "identity"

    def test_legacy_kr_texts(self):
        """CJK 인코딩된 한글 → eso_kr_legacy."""
        codec = EsoKrLegacyCodec()
        # 한글 텍스트를 인코딩하여 legacy 형태로 만듦
        raw_texts = [
            codec.encode("안녕하세요"),
            codec.encode("드래곤"),
            codec.encode("퀘스트 완료"),
        ]
        assert suggest_codec(raw_texts) == "eso_kr_legacy"


class TestIsKrCodec:
    def test_identity_is_not_kr(self):
        from core.text_codec import is_kr_codec
        assert not is_kr_codec("identity")

    def test_legacy_is_kr(self):
        from core.text_codec import is_kr_codec
        assert is_kr_codec("eso_kr_legacy")

    def test_native_is_kr(self):
        from core.text_codec import is_kr_codec
        assert is_kr_codec("eso_kr_native")


class TestEsoKrNativeCodec:
    def test_decode_is_identity(self):
        codec = get_codec("eso_kr_native")
        text = "안녕하세요 Hello 123"
        assert codec.decode(text) == text

    def test_encode_is_identity(self):
        codec = get_codec("eso_kr_native")
        text = "안녕하세요 Hello 123"
        assert codec.encode(text) == text

    def test_roundtrip(self):
        codec = get_codec("eso_kr_native")
        text = "트리뷰트 캠페인"
        assert codec.decode(codec.encode(text)) == text


class TestKrLangRoundtrip:
    """실제 kr.lang 파일로 라운드트립 검증.

    kr.lang이 없으면 스킵.
    코덱 자동 감지 후 해당 코덱으로 라운드트립.
    """

    @pytest.fixture
    def kr_lang_texts(self):
        if not KR_LANG_PATH.exists():
            pytest.skip("kr.lang 파일 없음")
        import struct
        data = KR_LANG_PATH.read_bytes()
        version, count = struct.unpack_from(">II", data, 0)
        record_end = 8 + count * 16
        text_blob = data[record_end:]
        parts = text_blob.split(b"\x00")
        return [p.decode("utf-8", errors="replace") for p in parts if p]

    def test_parse_and_codec_roundtrip(self, kr_lang_texts):
        """kr.lang parse → decode → encode → 원본 텍스트 동일."""
        detected = suggest_codec(kr_lang_texts)
        codec = get_codec(detected)

        mismatches = 0
        for raw_text in kr_lang_texts[:10000]:
            decoded = codec.decode(raw_text)
            re_encoded = codec.encode(decoded)
            if re_encoded != raw_text:
                mismatches += 1

        assert mismatches == 0, f"라운드트립 실패: {mismatches}건 / {min(len(kr_lang_texts), 10000)}건"

    def test_decode_produces_korean(self, kr_lang_texts):
        """decode 후 한글 문자가 나타나는지 확인."""
        detected = suggest_codec(kr_lang_texts)
        codec = get_codec(detected)

        hangul_count = 0
        for raw_text in kr_lang_texts[:5000]:
            decoded = codec.decode(raw_text)
            for ch in decoded:
                cp = ord(ch)
                if 0xAC00 <= cp <= 0xD7A3:
                    hangul_count += 1

        assert hangul_count > 1000, f"한글 {hangul_count}자 — 디코딩 실패 의심"

    def test_suggest_detects_kr_lang(self, kr_lang_texts):
        """suggest_codec이 kr.lang을 KR 코덱(legacy 또는 native)으로 감지."""
        from core.text_codec import is_kr_codec
        result = suggest_codec(kr_lang_texts)
        assert is_kr_codec(result), f"KR 코덱이 아님: {result}"
