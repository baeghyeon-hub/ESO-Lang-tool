"""
.lang 바이너리 빌더 — SQLite → .lang 파일 생성

String Dedup:
  고유 텍스트 558,294개 / 전체 1,167,734개 (중복률 52.2%)
  → 동일 문자열은 같은 offset을 공유

빌드 전략:
  1. DB에서 전체 레코드 추출 (id, unknown, idx, text)
  2. 고유 문자열 수집 → offset map 빌드
  3. 레코드 정렬 (id, unknown, idx)
  4. 헤더 + 레코드 + 텍스트 blob 조립
"""

import struct
from pathlib import Path
from typing import Callable, Optional

from core.db import LangDatabase
from core.text_codec import TextCodec, IdentityCodec

_HEADER_FORMAT = ">II"
_RECORD_FORMAT = ">IIII"


def build_lang(
    db: LangDatabase,
    output_path: str | Path,
    *,
    codec: TextCodec | None = None,
    version: int = 2,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """
    DB 레코드를 .lang 바이너리로 빌드하여 저장.

    Args:
        db: LangDatabase 인스턴스
        output_path: 출력 .lang 파일 경로
        codec: 텍스트 변환 코덱 (None이면 IdentityCodec)
        version: 헤더 버전 (기본 2)
        progress_cb: 진행률 콜백 (current, total)

    Returns:
        빌드 메타데이터 dict
    """
    if codec is None:
        codec = IdentityCodec()

    output_path = Path(output_path)

    # ── 1. DB에서 전체 레코드 추출 (이미 정렬됨) ──
    records = db.get_all_for_build()  # (id, unknown, idx, text)
    record_count = len(records)

    # ── 2. 고유 문자열 수집 + offset map 빌드 (codec.encode 적용) ──
    text_blob, offset_map = _build_text_blob(records, codec)

    # ── 3. 헤더 빌드 ──
    header = struct.pack(_HEADER_FORMAT, version, record_count)

    # ── 4. 레코드 바이너리 빌드 ──
    record_data = bytearray()
    for i, (rec_id, unknown, idx, text) in enumerate(records):
        offset = offset_map[text]
        record_data.extend(struct.pack(_RECORD_FORMAT, rec_id, unknown, idx, offset))
        if progress_cb and (i + 1) % 50_000 == 0:
            progress_cb(i + 1, record_count)

    if progress_cb:
        progress_cb(record_count, record_count)

    # ── 5. 파일 쓰기 ──
    output_path.write_bytes(header + bytes(record_data) + text_blob)

    return {
        "version": version,
        "record_count": record_count,
        "unique_strings": len(offset_map),
        "text_blob_size": len(text_blob),
        "file_size": len(header) + len(record_data) + len(text_blob),
    }


def build_lang_bytes(
    db: LangDatabase,
    *,
    codec: TextCodec | None = None,
    version: int = 2,
) -> bytes:
    """DB 레코드를 .lang 바이너리 bytes로 반환 (테스트/검증용)."""
    if codec is None:
        codec = IdentityCodec()
    records = db.get_all_for_build()
    text_blob, offset_map = _build_text_blob(records, codec)
    header = struct.pack(_HEADER_FORMAT, version, len(records))
    record_data = bytearray()
    for rec_id, unknown, idx, text in records:
        offset = offset_map[text]
        record_data.extend(struct.pack(_RECORD_FORMAT, rec_id, unknown, idx, offset))
    return header + bytes(record_data) + text_blob


def _build_text_blob(
    records: list[tuple],
    codec: TextCodec,
) -> tuple[bytes, dict[str, int]]:
    """
    레코드에서 고유 문자열을 추출하여 텍스트 blob + offset map 빌드.

    원본 .lang의 텍스트 순서를 재현하기 위해:
    - 레코드 순서에서 처음 등장하는 순서를 유지 (첫 출현 순)
    - 이렇게 해야 라운드트립 시 원본과 바이트 동일 가능성 높음

    codec.encode()를 적용하여 DB의 표시용 텍스트를 저장 형식으로 변환.
    """
    # 첫 출현 순서 유지
    seen: dict[str, int] = {}
    ordered_texts: list[str] = []

    for _, _, _, text in records:
        if text not in seen:
            seen[text] = len(ordered_texts)
            ordered_texts.append(text)

    # offset map + blob 빌드 (codec.encode 적용)
    offset_map: dict[str, int] = {}
    blob = bytearray()
    current_offset = 0

    for text in ordered_texts:
        raw_text = codec.encode(text)
        encoded = raw_text.encode("utf-8") + b"\x00"
        offset_map[text] = current_offset
        blob.extend(encoded)
        current_offset += len(encoded)

    return bytes(blob), offset_map
