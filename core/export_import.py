"""
레코드 내보내기 / 가져오기 유틸.

내보내기 형식 (JSON):
[
  {"id": 242841564, "unknown": 0, "idx": 0, "source": "Hello", "target": "안녕"},
  ...
]

가져오기:
  동일 형식의 JSON을 읽어 (id, unknown, idx) 키로 매칭하여 target 업데이트.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.db import LangDatabase

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_records(
    db: LangDatabase,
    rowids: list[int],
    path: Path,
    *,
    encoding: str = "utf-8",
) -> int:
    """rowid 목록의 레코드를 JSON 파일로 내보내기. 내보낸 행 수 반환."""
    if not rowids:
        return 0

    records: list[dict] = []
    chunk_size = 500
    for i in range(0, len(rowids), chunk_size):
        chunk = rowids[i : i + chunk_size]
        placeholders = ",".join("?" * len(chunk))
        rows = db._conn.execute(
            f"SELECT id, unknown, idx, source, target "
            f"FROM records WHERE rowid IN ({placeholders})",
            chunk,
        ).fetchall()
        for row in rows:
            records.append({
                "id": row[0],
                "unknown": row[1],
                "idx": row[2],
                "source": row[3],
                "target": row[4],
            })

    with open(path, "w", encoding=encoding) as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    return len(records)


def export_filtered(
    db: LangDatabase,
    path: Path,
    *,
    id_filter: "int | list[int] | None" = None,
    where_clause: str = "",
    params: tuple = (),
    translated_only: bool = False,
    encoding: str = "utf-8",
) -> int:
    """현재 필터 조건에 맞는 레코드를 JSON으로 내보내기.

    Args:
        translated_only: True이면 target이 비어있지 않은 항목만 내보냄
    """
    sql = "SELECT id, unknown, idx, source, target FROM records"
    conditions: list[str] = []
    bind: list = []

    db._id_filter_clause(id_filter, conditions, bind)
    if where_clause:
        conditions.append(where_clause)
        bind.extend(params)

    if translated_only:
        conditions.append("target != '' AND target != source")

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    rows = db._conn.execute(sql, bind).fetchall()
    records = [
        {
            "id": r[0],
            "unknown": r[1],
            "idx": r[2],
            "source": r[3],
            "target": r[4],
        }
        for r in rows
    ]

    with open(path, "w", encoding=encoding) as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    return len(records)


def export_modified(
    db: LangDatabase,
    path: Path,
    *,
    en_db: "LangDatabase | None" = None,
    encoding: str = "utf-8",
) -> int:
    """이 툴에서 수정한 항목(modified=1)만 JSON으로 내보내기.

    en_db가 있으면 source를 영어 원문으로 교체하여,
    받는 쪽에서 import_records()로 바로 적용 가능.
    en_db가 없으면 현재 DB의 source를 그대로 사용.

    출력 형식:
    [
      {"id": 100, "unknown": 0, "idx": 0,
       "source": "English text",   ← en.lang 원문 (있으면)
       "target": "수정된 번역"      ← 이 툴에서 수정한 값
      }, ...
    ]
    """
    # en.lang 매핑 빌드
    en_map: dict[tuple[int, int, int], str] = {}
    if en_db is not None:
        en_rows = en_db._conn.execute(
            "SELECT id, unknown, idx, source FROM records"
        ).fetchall()
        en_map = {(r[0], r[1], r[2]): r[3] for r in en_rows}

    rows = db._conn.execute(
        "SELECT id, unknown, idx, source, target FROM records WHERE modified = 1"
    ).fetchall()

    records: list[dict] = []
    for rec_id, unk, idx, source, target in rows:
        # en.lang 원문이 있으면 source를 교체
        en_source = en_map.get((rec_id, unk, idx), source)
        records.append({
            "id": rec_id,
            "unknown": unk,
            "idx": idx,
            "source": en_source,
            "target": target,
        })

    with open(path, "w", encoding=encoding) as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    return len(records)


def export_diff(
    kr_db: LangDatabase,
    en_db: LangDatabase,
    path: Path,
    *,
    id_filter: "int | list[int] | None" = None,
    encoding: str = "utf-8",
) -> int:
    """en.lang과 비교하여 번역된(=source가 다른) 항목을 JSON으로 내보내기.

    kr.lang의 source가 en.lang의 source와 다르면 → 번역된 것으로 판단.
    target이 있으면 target을 우선 사용, 없으면 kr source를 번역 결과로 기록.

    출력 형식:
    [
      {"id": 100, "unknown": 0, "idx": 0,
       "source": "English text",      ← en.lang 원문
       "target": "한글 번역"           ← kr source 또는 kr target
      }, ...
    ]

    받는 쪽에서 import_records()로 바로 적용 가능.
    """
    # en.lang에서 (id, unknown, idx) → source 매핑 빌드
    en_rows = en_db._conn.execute(
        "SELECT id, unknown, idx, source FROM records"
    ).fetchall()
    en_map: dict[tuple[int, int, int], str] = {
        (r[0], r[1], r[2]): r[3] for r in en_rows
    }

    # kr.lang 레코드 조회
    sql = "SELECT id, unknown, idx, source, target FROM records"
    conditions: list[str] = []
    bind: list = []

    kr_db._id_filter_clause(id_filter, conditions, bind)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    kr_rows = kr_db._conn.execute(sql, bind).fetchall()

    records: list[dict] = []
    for kr_id, kr_unk, kr_idx, kr_source, kr_target in kr_rows:
        key = (kr_id, kr_unk, kr_idx)
        en_source = en_map.get(key)

        if en_source is None:
            # en.lang에 없는 레코드는 건너뜀
            continue

        # kr에서 target이 수정됐으면 target 우선, 아니면 kr source가 번역 결과
        translated_text = kr_target if kr_target else kr_source

        # 영어 원문과 같으면 미번역
        if translated_text == en_source or not translated_text:
            continue

        records.append({
            "id": kr_id,
            "unknown": kr_unk,
            "idx": kr_idx,
            "source": en_source,
            "target": translated_text,
        })

    with open(path, "w", encoding=encoding) as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    return len(records)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class ImportResult:
    """가져오기 결과."""

    __slots__ = ("total_rows", "matched", "changed", "skipped_no_match", "errors")

    def __init__(self) -> None:
        self.total_rows: int = 0
        self.matched: int = 0
        self.changed: int = 0
        self.skipped_no_match: int = 0
        self.errors: list[str] = []


def import_records(
    db: LangDatabase,
    path: Path,
    *,
    use_source_as_target: bool = False,
    encoding: str = "utf-8",
) -> tuple[list[tuple[int, str]], ImportResult]:
    """JSON 파일을 읽어 (id, unknown, idx) 키로 매칭.

    Args:
        use_source_as_target: True이면 JSON의 source 필드를 target 값으로 사용.
            en.lang 원문을 kr.lang target에 덮어쓸 때 유용.

    Returns:
        (updates, result)
        - updates: [(rowid, new_target), ...] — UndoManager.edit_batch()에 전달용
        - result: 통계 정보
    """
    result = ImportResult()
    updates: list[tuple[int, str]] = []

    with open(path, "r", encoding=encoding) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            result.errors.append(f"JSON 파싱 오류: {e}")
            return updates, result

    if not isinstance(data, list):
        result.errors.append("JSON 루트가 배열이 아닙니다.")
        return updates, result

    for i, item in enumerate(data):
        result.total_rows += 1

        if not isinstance(item, dict):
            result.errors.append(f"항목 {i}: 딕셔너리가 아닙니다")
            continue

        # 필수 키 확인
        try:
            rec_id = int(item["id"])
            rec_unknown = int(item["unknown"])
            rec_idx = int(item["idx"])
            if use_source_as_target:
                new_target = str(item.get("source", ""))
            else:
                new_target = str(item.get("target", ""))
        except (KeyError, ValueError, TypeError) as e:
            result.errors.append(f"항목 {i}: {e}")
            continue

        # DB에서 매칭
        db_row = db._conn.execute(
            "SELECT rowid, target FROM records "
            "WHERE id = ? AND unknown = ? AND idx = ?",
            (rec_id, rec_unknown, rec_idx),
        ).fetchone()

        if db_row is None:
            result.skipped_no_match += 1
            continue

        result.matched += 1
        rowid, old_target = db_row

        if new_target != old_target:
            updates.append((rowid, new_target))
            result.changed += 1

    return updates, result
