"""
.lang 바이너리 파서 — .lang → SQLite :memory: 로드

파일 구조:
  [Header 8 bytes]  → version(4B BE) + record_count(4B BE)
  [Records]         → record_count × 16 bytes (ID, Unknown, Index, Offset – 각 4B BE)
  [Text blob]       → UTF-8, NUL 종단 문자열

파싱 최적화: split(b'\\x00') + offset→string dict 사전 빌드
  → 매 레코드 index() 호출 12.76s → 0.6s
"""

import struct
from pathlib import Path
from typing import Callable, Optional

from core.db import LangDatabase
from core.text_codec import TextCodec, IdentityCodec

# Header: 2개의 Big-Endian unsigned int (version, record_count)
_HEADER_FORMAT = ">II"
_HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)  # 8 bytes

# Record: 4개의 Big-Endian unsigned int (id, unknown, index, offset)
_RECORD_FORMAT = ">IIII"
_RECORD_SIZE = struct.calcsize(_RECORD_FORMAT)  # 16 bytes


def parse_lang(
    filepath: str | Path,
    db: LangDatabase,
    *,
    codec: TextCodec | None = None,
    data: bytes | None = None,
    batch_size: int = 50_000,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> dict:
    """
    .lang 파일을 파싱하여 db에 삽입.

    Args:
        filepath: .lang 파일 경로
        db: LangDatabase 인스턴스
        codec: 텍스트 변환 코덱 (None이면 IdentityCodec)
        data: 미리 읽은 파일 데이터 (None이면 filepath에서 읽음)
        batch_size: DB 삽입 배치 크기
        progress_cb: 진행률 콜백 (current, total)
        cancel_check: 취소 여부 콜백 (True면 중단)

    Returns:
        파싱 메타데이터 dict

    Raises:
        InterruptedError: 취소된 경우
    """
    if codec is None:
        codec = IdentityCodec()

    filepath = Path(filepath)
    if data is None:
        data = filepath.read_bytes()

    # ── 1. 헤더 파싱 ──
    version, record_count = struct.unpack_from(_HEADER_FORMAT, data, 0)

    # ── 2. 레코드 영역 파싱 (iter_unpack) ──
    record_start = _HEADER_SIZE
    record_end = record_start + record_count * _RECORD_SIZE
    records_raw = list(
        struct.iter_unpack(_RECORD_FORMAT, data[record_start:record_end])
    )

    # ── 3. 텍스트 영역: split + offset map 빌드 (codec.decode 적용) ──
    text_blob = data[record_end:]
    offset_map = _build_offset_map(text_blob, codec)

    # ── 4. 레코드 + 텍스트 조립 → DB 삽입 ──
    batch: list[tuple[int, int, int, str]] = []
    inserted = 0

    for rec_id, unknown, idx, offset in records_raw:
        text = offset_map.get(offset, "")
        batch.append((rec_id, unknown, idx, text))

        if len(batch) >= batch_size:
            if cancel_check and cancel_check():
                raise InterruptedError("Cancelled")
            db.insert_records(batch)
            inserted += len(batch)
            batch.clear()
            if progress_cb:
                progress_cb(inserted, record_count)

    if batch:
        db.insert_records(batch)
        inserted += len(batch)
        if progress_cb:
            progress_cb(inserted, record_count)

    return {
        "version": version,
        "record_count": record_count,
        "text_blob_size": len(text_blob),
        "unique_strings": len(offset_map),
        "file_size": len(data),
        "codec": codec.name,
    }


def _build_offset_map(text_blob: bytes, codec: TextCodec) -> dict[int, str]:
    """
    NUL 종단 텍스트 blob을 split으로 분할 후 offset→string 매핑.

    split(b'\\x00')으로 한번에 분할: O(n) 한 번.
    매 레코드 index() 호출 방식 대비 ~20x 빠름.

    codec.decode()를 적용하여 DB에는 표시용 텍스트를 저장.
    """
    parts = text_blob.split(b"\x00")
    offset_map: dict[int, str] = {}
    current_offset = 0

    for part in parts:
        raw_text = part.decode("utf-8", errors="replace")
        text = codec.decode(raw_text)
        offset_map[current_offset] = text
        current_offset += len(part) + 1  # +1 for NUL terminator

    return offset_map
