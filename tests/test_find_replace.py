"""core/find_replace.py 단위 테스트."""

import pytest

from core.find_replace import FindReplaceConfig, make_replacer


class TestPlainReplace:
    def test_plain_replace(self):
        replacer = make_replacer(
            FindReplaceConfig(find_text="Dragon", replace_text="용")
        )
        assert replacer("Dragon Breath") == "용 Breath"

    def test_plain_replace_keeps_non_matching_text(self):
        replacer = make_replacer(
            FindReplaceConfig(find_text="Dragon", replace_text="용")
        )
        assert replacer("Fire Breath") == "Fire Breath"


class TestRegexReplace:
    def test_regex_replace_supports_groups(self):
        replacer = make_replacer(
            FindReplaceConfig(
                find_text=r"^(.*) Breath$",
                replace_text=r"\1 숨결",
                use_regex=True,
            )
        )
        assert replacer("Fire Breath") == "Fire 숨결"

    def test_invalid_regex_raises_value_error(self):
        with pytest.raises(ValueError, match="정규식 오류"):
            make_replacer(
                FindReplaceConfig(find_text="(", replace_text="X", use_regex=True)
            )

    def test_invalid_replacement_raises_value_error(self):
        replacer = make_replacer(
            FindReplaceConfig(find_text=r"(Dragon)", replace_text=r"\2", use_regex=True)
        )
        with pytest.raises(ValueError, match="정규식 치환 오류"):
            replacer("Dragon")


class TestValidation:
    def test_empty_find_text_raises_value_error(self):
        with pytest.raises(ValueError, match="찾을 문자열"):
            make_replacer(FindReplaceConfig(find_text="", replace_text="X"))
