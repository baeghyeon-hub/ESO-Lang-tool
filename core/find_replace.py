"""Target 텍스트용 Find/Replace 유틸리티."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class FindReplaceConfig:
    """일괄 치환 설정."""

    find_text: str
    replace_text: str = ""
    use_regex: bool = False


def make_replacer(config: FindReplaceConfig) -> Callable[[str], str]:
    """문자열 치환 함수를 생성한다."""
    if not config.find_text:
        raise ValueError("찾을 문자열을 입력하세요.")

    if not config.use_regex:
        needle = config.find_text
        replacement = config.replace_text
        return lambda text: text.replace(needle, replacement)

    try:
        pattern = re.compile(config.find_text)
    except re.error as exc:
        raise ValueError(f"정규식 오류: {exc}") from exc

    replacement = config.replace_text

    def _replace(text: str) -> str:
        try:
            return pattern.sub(replacement, text)
        except re.error as exc:
            raise ValueError(f"정규식 치환 오류: {exc}") from exc

    return _replace
