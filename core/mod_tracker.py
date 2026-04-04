"""
수정 이력 추적기.

.lang 파일과 함께 .lang.mod.json 사이드카 파일을 관리하여,
이 툴에서 수정한 레코드의 (id, unknown, idx) 키를 영구 보존.

파일을 다시 열어도 이전 수정 이력이 유지됨.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.db import LangDatabase


def _mod_path(lang_path: str | Path) -> Path:
    """사이드카 파일 경로: foo.lang → foo.lang.mod.json"""
    return Path(lang_path).with_suffix(Path(lang_path).suffix + ".mod.json")


def save_mod_keys(db: LangDatabase, lang_path: str | Path) -> int:
    """DB에서 modified=1인 레코드의 키를 사이드카 파일에 저장.

    기존 사이드카 파일이 있으면 병합(union).
    Returns: 총 저장된 키 수.
    """
    # DB에서 현재 세션에 수정된 키 가져오기
    rows = db._conn.execute(
        "SELECT id, unknown, idx FROM records WHERE modified = 1"
    ).fetchall()
    new_keys = {(r[0], r[1], r[2]) for r in rows}

    if not new_keys:
        # 수정된 것이 없어도 기존 파일은 유지
        mod_file = _mod_path(lang_path)
        if mod_file.exists():
            existing = _load_key_set(mod_file)
            return len(existing)
        return 0

    # 기존 사이드카 파일에서 이전 키 로드 후 병합
    mod_file = _mod_path(lang_path)
    existing = _load_key_set(mod_file) if mod_file.exists() else set()
    merged = existing | new_keys

    # 저장
    data = [[k[0], k[1], k[2]] for k in sorted(merged)]
    mod_file.write_text(
        json.dumps(data, separators=(",", ":")),
        encoding="utf-8",
    )

    return len(merged)


def load_mod_keys(db: LangDatabase, lang_path: str | Path) -> int:
    """사이드카 파일에서 수정 이력을 읽어 DB의 modified 플래그를 복원.

    Returns: 복원된 레코드 수.
    """
    mod_file = _mod_path(lang_path)
    if not mod_file.exists():
        return 0

    keys = _load_key_set(mod_file)
    if not keys:
        return 0

    # 임시 테이블로 일괄 JOIN UPDATE (대량 키에 효율적)
    conn = db._conn
    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS _mod_keys "
        "(id INTEGER, unknown INTEGER, idx INTEGER)"
    )
    conn.execute("DELETE FROM _mod_keys")

    # 청크 단위 삽입
    key_list = list(keys)
    chunk_size = 500
    for i in range(0, len(key_list), chunk_size):
        chunk = key_list[i : i + chunk_size]
        conn.executemany(
            "INSERT INTO _mod_keys (id, unknown, idx) VALUES (?, ?, ?)",
            chunk,
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_mod_keys "
        "ON _mod_keys(id, unknown, idx)"
    )

    # 한 번의 UPDATE로 모든 키 반영
    result = conn.execute(
        "UPDATE records SET modified = 1 "
        "WHERE modified = 0 AND EXISTS ("
        "  SELECT 1 FROM _mod_keys m "
        "  WHERE m.id = records.id AND m.unknown = records.unknown "
        "  AND m.idx = records.idx"
        ")"
    )
    restored = result.rowcount

    conn.execute("DROP TABLE IF EXISTS _mod_keys")

    if restored > 0:
        conn.commit()

    return restored


def get_mod_count(lang_path: str | Path) -> int:
    """사이드카 파일의 수정 키 수 반환 (파일 없으면 0)."""
    mod_file = _mod_path(lang_path)
    if not mod_file.exists():
        return 0
    return len(_load_key_set(mod_file))


def _load_key_set(mod_file: Path) -> set[tuple[int, int, int]]:
    """사이드카 파일에서 키 set 로드."""
    try:
        data = json.loads(mod_file.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return set()
        return {(item[0], item[1], item[2]) for item in data if isinstance(item, list) and len(item) >= 3}
    except (json.JSONDecodeError, OSError, IndexError):
        return set()
