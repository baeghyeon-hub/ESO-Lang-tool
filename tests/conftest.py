"""pytest 공용 fixture."""

import struct
import pytest
from pathlib import Path

from core.db import LangDatabase
from core.lang_parser import parse_lang


# ---------------------------------------------------------------------------
# 작은 .lang fixture 생성 (실파일 불필요)
# ---------------------------------------------------------------------------

def _build_mini_lang(records: list[tuple[int, int, int, str]]) -> bytes:
    """테스트용 최소 .lang 바이너리 생성.

    records: [(id, unknown, idx, text), ...]
    """
    # 텍스트 blob: 첫 출현 순서로 dedup
    seen: dict[str, int] = {}
    ordered: list[str] = []
    for _, _, _, text in records:
        if text not in seen:
            seen[text] = len(ordered)
            ordered.append(text)

    blob = bytearray()
    offset_map: dict[str, int] = {}
    cur = 0
    for text in ordered:
        encoded = text.encode("utf-8") + b"\x00"
        offset_map[text] = cur
        blob.extend(encoded)
        cur += len(encoded)

    # 헤더
    header = struct.pack(">II", 2, len(records))

    # 레코드
    rec_data = bytearray()
    for rid, unk, idx, text in records:
        rec_data.extend(struct.pack(">IIII", rid, unk, idx, offset_map[text]))

    return header + bytes(rec_data) + bytes(blob)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RECORDS = [
    (100, 0, 1, "Hello World"),
    (100, 0, 2, "Tribute Campaign"),
    (100, 0, 3, "Hello World"),       # 중복 텍스트
    (100, 1, 1, "IDLE"),
    (200, 0, 1, "Dragon"),
    (200, 0, 2, "Fire Breath"),
    (200, 0, 3, ""),                   # 빈 텍스트
    (300, 0, 1, "Gabrielle Benele^F"),
    (300, 0, 2, "Ugron gro-Thumog^M"),
    (300, 0, 3, "Test NPC^N"),
]


@pytest.fixture
def sample_lang_file(tmp_path) -> Path:
    """테스트용 최소 .lang 파일."""
    data = _build_mini_lang(SAMPLE_RECORDS)
    p = tmp_path / "test.lang"
    p.write_bytes(data)
    return p


@pytest.fixture
def db() -> LangDatabase:
    """빈 LangDatabase."""
    d = LangDatabase()
    yield d
    d.close()


@pytest.fixture
def loaded_db(sample_lang_file) -> LangDatabase:
    """샘플 .lang이 로드된 LangDatabase."""
    d = LangDatabase()
    parse_lang(sample_lang_file, d)
    yield d
    d.close()


@pytest.fixture
def loaded_db_with_fts(loaded_db) -> LangDatabase:
    """FTS5까지 빌드된 LangDatabase."""
    loaded_db.build_fts()
    return loaded_db
