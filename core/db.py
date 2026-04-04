"""
SQLite in-memory DB 스키마 + FTS5 + 쿼리 API

모든 레코드 데이터를 sqlite3 :memory:에 저장.
Python은 DB 커넥션만 보유 → 메모리 최소.
"""

import sqlite3
from collections.abc import Iterator

from core.db_glossary import GlossaryMixin
from core.db_translation import TranslationMixin

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS records (
    id       INTEGER NOT NULL,
    unknown  INTEGER NOT NULL,
    idx      INTEGER NOT NULL,
    source   TEXT    NOT NULL DEFAULT '',
    target   TEXT    NOT NULL DEFAULT '',
    modified INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_id       ON records(id);
CREATE INDEX IF NOT EXISTS ix_compound ON records(id, unknown, idx);
"""

_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
    source, target,
    content=records,
    content_rowid=rowid
);
"""

_GLOSSARY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS glossary (
    term        TEXT    NOT NULL,
    translation TEXT    NOT NULL DEFAULT '',
    category    TEXT    NOT NULL,
    gender      TEXT    NOT NULL DEFAULT '',
    usage_count INTEGER NOT NULL DEFAULT 0,
    source_id   INTEGER NOT NULL DEFAULT 0,
    note        TEXT    NOT NULL DEFAULT '',
    UNIQUE(term, category)
);

CREATE INDEX IF NOT EXISTS ix_glossary_cat  ON glossary(category);
CREATE INDEX IF NOT EXISTS ix_glossary_term ON glossary(term);
"""

_TRANSLATION_PROGRESS_SQL = """
CREATE TABLE IF NOT EXISTS translation_progress (
    record_rowid  INTEGER PRIMARY KEY,
    status        TEXT    NOT NULL DEFAULT 'pending',
    model         TEXT    NOT NULL DEFAULT '',
    attempt       INTEGER NOT NULL DEFAULT 0,
    translated_at TEXT    NOT NULL DEFAULT '',
    reviewed_at   TEXT    NOT NULL DEFAULT ''
);
"""


# ---------------------------------------------------------------------------
# Database class
# ---------------------------------------------------------------------------

def _has_korean(text: str) -> bool:
    """문자열에 한글이 포함되어 있는지 판단 (SQLite 사용자 함수용)."""
    if not text:
        return False
    for ch in text:
        cp = ord(ch)
        if (0xAC00 <= cp <= 0xD7A3 or   # 음절
            0x1100 <= cp <= 0x11FF or     # 자모
            0x3131 <= cp <= 0x318F):      # 호환 자모
            return True
    return False


class LangDatabase(GlossaryMixin, TranslationMixin):
    """ESO Lang 데이터를 관리하는 SQLite in-memory DB."""

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.execute("PRAGMA synchronous=OFF")
        self._conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        self._conn.create_function("has_korean", 1, _has_korean, deterministic=True)
        self._init_schema()
        self._fts_built = False
        self._record_count: int | None = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _id_filter_clause(
        id_filter: "int | list[int] | None",
        conditions: list[str],
        bind: list,
    ) -> None:
        """id_filter를 WHERE 조건에 추가. int, list[int], None 지원."""
        if id_filter is None:
            return
        if isinstance(id_filter, int):
            conditions.append("id = ?")
            bind.append(id_filter)
        elif isinstance(id_filter, list) and len(id_filter) == 1:
            conditions.append("id = ?")
            bind.append(id_filter[0])
        elif isinstance(id_filter, list) and id_filter:
            placeholders = ",".join("?" * len(id_filter))
            conditions.append(f"id IN ({placeholders})")
            bind.extend(id_filter)

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        cur = self._conn.executescript(_SCHEMA_SQL)
        cur.close()

    def init_glossary(self) -> None:
        self._conn.executescript(_GLOSSARY_SCHEMA_SQL)

    def init_translation_progress(self) -> None:
        self._conn.executescript(_TRANSLATION_PROGRESS_SQL)

    # ------------------------------------------------------------------
    # Connection wrappers
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """내부 SQLite execute 래퍼."""
        return self._conn.execute(sql, params)

    def executemany(
        self,
        sql: str,
        seq_of_params: list[tuple] | tuple[tuple, ...],
    ) -> sqlite3.Cursor:
        """내부 SQLite executemany 래퍼."""
        return self._conn.executemany(sql, seq_of_params)

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        """내부 SQLite executescript 래퍼."""
        return self._conn.executescript(sql_script)

    def commit(self) -> None:
        """현재 트랜잭션 커밋."""
        self._conn.commit()

    # ------------------------------------------------------------------
    # Bulk insert (파서에서 호출)
    # ------------------------------------------------------------------

    def insert_records(self, rows: list[tuple[int, int, int, str]]) -> None:
        """(id, unknown, idx, source) 튜플 리스트를 일괄 삽입."""
        self._conn.executemany(
            "INSERT INTO records (id, unknown, idx, source) VALUES (?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        self._record_count = None  # 캐시 무효화

    # ------------------------------------------------------------------
    # FTS5
    # ------------------------------------------------------------------

    def build_fts(self) -> None:
        """FTS5 가상 테이블 생성 + 인덱스 빌드."""
        self._conn.executescript(_FTS_SQL)
        self._conn.execute(
            "INSERT INTO records_fts(records_fts) VALUES('rebuild')"
        )
        self._conn.commit()
        self._fts_built = True

    def rebuild_fts(self) -> None:
        """FTS5 인덱스 재빌드 (편집 후 호출)."""
        if not self._fts_built:
            self.build_fts()
            return
        self._conn.execute(
            "INSERT INTO records_fts(records_fts) VALUES('rebuild')"
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # 쿼리 API
    # ------------------------------------------------------------------

    def record_count(self) -> int:
        if self._record_count is None:
            row = self._conn.execute("SELECT count(*) FROM records").fetchone()
            self._record_count = row[0]
        return self._record_count

    def get_record_by_rowid(self, rowid: int) -> tuple | None:
        """rowid로 단일 레코드 조회 → (id, unknown, idx, source, target, modified)."""
        return self._conn.execute(
            "SELECT id, unknown, idx, source, target, modified "
            "FROM records WHERE rowid = ?",
            (rowid,),
        ).fetchone()

    def get_source_targets_by_rowids(
        self,
        rowids: list[int],
    ) -> list[tuple[int, str, str]]:
        """rowid 목록의 (rowid, source, target)를 입력 순서대로 반환."""
        if not rowids:
            return []

        row_map: dict[int, tuple] = {}
        chunk_size = 500
        for i in range(0, len(rowids), chunk_size):
            chunk = rowids[i : i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT rowid, source, target FROM records "
                f"WHERE rowid IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                row_map[row[0]] = row

        return [row_map[rowid] for rowid in rowids if rowid in row_map]

    def get_records_range(
        self,
        offset: int,
        limit: int,
        *,
        id_filter: "int | list[int] | None" = None,
        where_clause: str = "",
        params: tuple = (),
    ) -> list[tuple]:
        """페이징 조회. (rowid, id, unknown, idx, source, target, modified) 리스트."""
        # where_clause는 내부에서 조합된 trusted SQL fragment만 받는다.
        sql = "SELECT rowid, id, unknown, idx, source, target, modified FROM records"
        conditions = []
        bind: list = []

        self._id_filter_clause(id_filter, conditions, bind)
        if where_clause:
            conditions.append(where_clause)
            bind.extend(params)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY id, unknown, idx LIMIT ? OFFSET ?"
        bind.extend([limit, offset])

        return self._conn.execute(sql, bind).fetchall()

    def get_group_ids(self) -> list[tuple[int, int]]:
        """(id, count) 리스트 – 그룹 트리용."""
        return self._conn.execute(
            "SELECT id, count(*) FROM records GROUP BY id ORDER BY id"
        ).fetchall()

    def count_by_filter(
        self,
        *,
        id_filter: "int | list[int] | None" = None,
        where_clause: str = "",
        params: tuple = (),
    ) -> int:
        """필터 조건에 맞는 레코드 수."""
        # where_clause는 내부에서 조합된 trusted SQL fragment만 받는다.
        sql = "SELECT count(*) FROM records"
        conditions = []
        bind: list = []

        self._id_filter_clause(id_filter, conditions, bind)
        if where_clause:
            conditions.append(where_clause)
            bind.extend(params)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        return self._conn.execute(sql, bind).fetchone()[0]

    # ------------------------------------------------------------------
    # 검색 API
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """사용자 입력을 FTS5-safe 쿼리로 변환.

        각 토큰을 큰따옴표로 감싸서 특수 문자(', ", *, -, OR 등)가
        FTS5 구문으로 해석되지 않도록 한다.
        """
        tokens = query.split()
        if not tokens:
            return query
        safe: list[str] = []
        for tok in tokens:
            # 큰따옴표 내부의 큰따옴표는 두 번 반복하여 이스케이프
            escaped = tok.replace('"', '""')
            safe.append(f'"{escaped}"')
        return " ".join(safe)

    def search_fts(self, query: str, limit: int = 200) -> list[tuple]:
        """FTS5 MATCH 검색 → (rowid, id, unknown, idx, source, target) 리스트."""
        if not self._fts_built:
            return []
        safe_query = self._sanitize_fts_query(query)
        if not safe_query.strip():
            return []
        try:
            return self._conn.execute(
                "SELECT r.rowid, r.id, r.unknown, r.idx, r.source, r.target "
                "FROM records_fts f "
                "JOIN records r ON r.rowid = f.rowid "
                "WHERE records_fts MATCH ? "
                "LIMIT ?",
                (safe_query, limit),
            ).fetchall()
        except Exception:
            return []

    def search_like(
        self, keyword: str, *, id_filter: "int | list[int] | None" = None, limit: int = 200
    ) -> list[tuple]:
        """LIKE 검색 (FTS 미빌드 시 폴백)."""
        sql = (
            "SELECT rowid, id, unknown, idx, source, target FROM records "
            "WHERE (source LIKE ? OR target LIKE ?)"
        )
        bind: list = [f"%{keyword}%", f"%{keyword}%"]

        if id_filter is not None:
            conditions: list[str] = []
            self._id_filter_clause(id_filter, conditions, bind)
            if conditions:
                sql += " AND " + conditions[0]

        sql += " LIMIT ?"
        bind.append(limit)

        return self._conn.execute(sql, bind).fetchall()

    # ------------------------------------------------------------------
    # 편집 API
    # ------------------------------------------------------------------

    def update_target(self, rowid: int, new_target: str) -> str | None:
        """target 업데이트. 이전 값 반환 (undo용). 변경 없으면 None.

        FTS5 외부 콘텐츠 테이블도 동기화.
        """
        row = self._conn.execute(
            "SELECT source, target FROM records WHERE rowid = ?", (rowid,)
        ).fetchone()
        if row is None or row[1] == new_target:
            return None

        old_target = row[1]
        source = row[0]

        self._conn.execute(
            "UPDATE records SET target = ?, modified = 1 WHERE rowid = ?",
            (new_target, rowid),
        )

        # FTS5 외부 콘텐츠 동기화: 기존 행 삭제 후 새 행 삽입
        if self._fts_built:
            self._conn.execute(
                "INSERT INTO records_fts(records_fts, rowid, source, target) "
                "VALUES('delete', ?, ?, ?)",
                (rowid, source, old_target),
            )
            self._conn.execute(
                "INSERT INTO records_fts(rowid, source, target) VALUES(?, ?, ?)",
                (rowid, source, new_target),
            )

        self._conn.commit()
        return old_target

    def batch_update_targets(
        self, updates: list[tuple[int, str]]
    ) -> list[tuple[int, str, str]]:
        """일괄 업데이트. [(rowid, new_target), ...] → [(rowid, old, new), ...] diff 리스트.

        하나의 트랜잭션으로 처리하여 성능 최적화.
        """
        diffs: list[tuple[int, str, str]] = []
        CHUNK = 500  # SQLite 변수 개수 제한 회피

        # 기존 값 일괄 조회 (청크 단위)
        rowids = [r for r, _ in updates]
        existing: dict[int, str] = {}
        for i in range(0, len(rowids), CHUNK):
            chunk = rowids[i : i + CHUNK]
            placeholders = ",".join("?" * len(chunk))
            existing.update(
                self._conn.execute(
                    f"SELECT rowid, target FROM records WHERE rowid IN ({placeholders})",
                    chunk,
                ).fetchall()
            )

        # source도 FTS 동기화용으로 조회
        sources: dict[int, str] = {}
        if self._fts_built:
            for i in range(0, len(rowids), CHUNK):
                chunk = rowids[i : i + CHUNK]
                placeholders = ",".join("?" * len(chunk))
                sources.update(
                    self._conn.execute(
                        f"SELECT rowid, source FROM records WHERE rowid IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )

        for rowid, new_target in updates:
            old_target = existing.get(rowid)
            if old_target is None or old_target == new_target:
                continue

            self._conn.execute(
                "UPDATE records SET target = ?, modified = 1 WHERE rowid = ?",
                (new_target, rowid),
            )

            if self._fts_built:
                source = sources.get(rowid, "")
                self._conn.execute(
                    "INSERT INTO records_fts(records_fts, rowid, source, target) "
                    "VALUES('delete', ?, ?, ?)",
                    (rowid, source, old_target),
                )
                self._conn.execute(
                    "INSERT INTO records_fts(rowid, source, target) VALUES(?, ?, ?)",
                    (rowid, source, new_target),
                )

            diffs.append((rowid, old_target, new_target))

        if diffs:
            self._conn.commit()

        return diffs

    def iter_target_records(
        self,
        *,
        id_filter: "int | list[int] | None" = None,
        where_clause: str = "",
        params: tuple = (),
        contains_text: str | None = None,
        batch_size: int = 5000,
    ) -> Iterator[tuple[int, str]]:
        """치환용 target 레코드 순회. 빈 target은 제외."""
        # where_clause는 내부에서 조합된 trusted SQL fragment만 받는다.
        sql = "SELECT rowid, target FROM records"
        conditions = ["target != ''"]
        bind: list = []

        self._id_filter_clause(id_filter, conditions, bind)
        if where_clause:
            conditions.append(where_clause)
            bind.extend(params)
        if contains_text is not None:
            conditions.append("instr(target, ?) > 0")
            bind.append(contains_text)

        sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY rowid"

        cur = self._conn.execute(sql, bind)
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            yield from rows

    # ------------------------------------------------------------------
    # 통계 API
    # ------------------------------------------------------------------

    @staticmethod
    def _translated_condition(codec_name: str) -> str:
        """코덱별 번역 완료 판정 조건."""
        from core.text_codec import is_kr_codec
        if is_kr_codec(codec_name):
            return "(target != '' OR has_korean(source))"
        return "target != ''"

    @staticmethod
    def _build_stats_where(
        *,
        id_filter: "int | list[int] | None" = None,
        where_clause: str = "",
        params: tuple = (),
        extra_clause: str = "",
    ) -> tuple[str, list]:
        """통계용 WHERE 절과 바인드 목록 조합."""
        conditions: list[str] = []
        bind: list = []
        LangDatabase._id_filter_clause(id_filter, conditions, bind)
        if where_clause:
            conditions.append(where_clause)
            bind.extend(params)
        if extra_clause:
            conditions.append(extra_clause)
        where_sql = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        return where_sql, bind

    def get_stats_by_filter(
        self,
        *,
        codec_name: str = "identity",
        id_filter: "int | list[int] | None" = None,
        where_clause: str = "",
        params: tuple = (),
    ) -> dict:
        """필터 범위 기준 통계 반환."""
        translated_condition = self._translated_condition(codec_name)
        total = self.count_by_filter(
            id_filter=id_filter,
            where_clause=where_clause,
            params=params,
        )
        translated_where, translated_params = self._build_stats_where(
            id_filter=id_filter,
            where_clause=where_clause,
            params=params,
            extra_clause=translated_condition,
        )
        translated = self._conn.execute(
            f"SELECT count(*) FROM records{translated_where}",
            translated_params,
        ).fetchone()[0]
        modified_where, modified_params = self._build_stats_where(
            id_filter=id_filter,
            where_clause=where_clause,
            params=params,
            extra_clause="modified = 1",
        )
        modified = self._conn.execute(
            f"SELECT count(*) FROM records{modified_where}",
            modified_params,
        ).fetchone()[0]
        modified_chars = self._conn.execute(
            f"SELECT COALESCE(sum(length(target)), 0) FROM records{modified_where}",
            modified_params,
        ).fetchone()[0]
        unique_source_where, unique_source_params = self._build_stats_where(
            id_filter=id_filter,
            where_clause=where_clause,
            params=params,
            extra_clause="source != ''",
        )
        unique_source_total = self._conn.execute(
            "SELECT count(*) FROM ("
            f"SELECT source FROM records{unique_source_where} GROUP BY source"
            ")",
            unique_source_params,
        ).fetchone()[0]
        unique_source_translated_where, unique_source_translated_params = (
            self._build_stats_where(
                id_filter=id_filter,
                where_clause=where_clause,
                params=params,
                extra_clause=f"source != '' AND {translated_condition}",
            )
        )
        unique_source_translated = self._conn.execute(
            "SELECT count(*) FROM ("
            "SELECT source FROM records"
            f"{unique_source_translated_where} GROUP BY source"
            ")",
            unique_source_translated_params,
        ).fetchone()[0]
        return {
            "total": total,
            "translated": translated,
            "untranslated": total - translated,
            "modified": modified,
            "modified_chars": modified_chars,
            "progress": translated / total * 100 if total > 0 else 0.0,
            "unique_source_total": unique_source_total,
            "unique_source_translated": unique_source_translated,
            "unique_source_progress": (
                unique_source_translated / unique_source_total * 100
                if unique_source_total > 0 else 0.0
            ),
        }

    def get_stats(self, *, codec_name: str = "identity") -> dict:
        """전체 통계 반환."""
        return self.get_stats_by_filter(codec_name=codec_name)

    def get_source_translation_summary(self, source_text: str) -> dict:
        """같은 source 문자열의 번역 적용 현황과 번역문 종류를 반환."""
        if not source_text:
            return {
                "source_text": "",
                "total_rows": 0,
                "translated_rows": 0,
                "untranslated_rows": 0,
                "variant_count": 0,
                "variants": [],
            }

        total_rows = self._conn.execute(
            "SELECT count(*) FROM records WHERE source = ?",
            (source_text,),
        ).fetchone()[0]
        translated_rows = self._conn.execute(
            "SELECT count(*) FROM records WHERE source = ? AND target != ''",
            (source_text,),
        ).fetchone()[0]
        variants = [
            {"target": target, "count": count}
            for target, count in self._conn.execute(
                "SELECT target, count(*) "
                "FROM records "
                "WHERE source = ? AND target != '' "
                "GROUP BY target "
                "ORDER BY count(*) DESC, target ASC",
                (source_text,),
            ).fetchall()
        ]

        return {
            "source_text": source_text,
            "total_rows": total_rows,
            "translated_rows": translated_rows,
            "untranslated_rows": total_rows - translated_rows,
            "variant_count": len(variants),
            "variants": variants,
        }

    def get_record_keys_by_source(self, source_text: str) -> list[tuple[int, int, int]]:
        """source 문자열이 같은 레코드의 (id, unknown, idx) 키 목록."""
        if not source_text:
            return []
        return self._conn.execute(
            "SELECT id, unknown, idx FROM records WHERE source = ?",
            (source_text,),
        ).fetchall()

    def get_source_variants_for_record_keys(
        self,
        record_keys: list[tuple[int, int, int]],
        *,
        exclude_text: str = "",
    ) -> list[dict]:
        """주어진 레코드 키와 매칭되는 source 변형 문자열을 집계."""
        if not record_keys:
            return []

        values_sql = ",".join("(?, ?, ?)" for _ in record_keys)
        bind: list[int | str] = [
            value
            for record_key in record_keys
            for value in record_key
        ]

        sql = (
            "WITH matched(id, unknown, idx) AS (VALUES "
            f"{values_sql}"
            ") "
            "SELECT records.source, count(*) "
            "FROM records "
            "JOIN matched USING(id, unknown, idx) "
            "WHERE records.source != '' "
        )
        if exclude_text:
            sql += "AND records.source != ? "
            bind.append(exclude_text)
        sql += "GROUP BY records.source ORDER BY count(*) DESC, records.source ASC"

        return [
            {"target": source_text, "count": count}
            for source_text, count in self._conn.execute(sql, tuple(bind)).fetchall()
        ]

    def get_target_variants_for_record_keys(
        self,
        record_keys: list[tuple[int, int, int]],
    ) -> list[dict]:
        """주어진 레코드 키와 매칭되는 target 문자열을 집계."""
        if not record_keys:
            return []

        values_sql = ",".join("(?, ?, ?)" for _ in record_keys)
        bind = [
            value
            for record_key in record_keys
            for value in record_key
        ]
        sql = (
            "WITH matched(id, unknown, idx) AS (VALUES "
            f"{values_sql}"
            ") "
            "SELECT records.target, count(*) "
            "FROM records "
            "JOIN matched USING(id, unknown, idx) "
            "WHERE records.target != '' "
            "GROUP BY records.target "
            "ORDER BY count(*) DESC, records.target ASC"
        )
        return [
            {"target": target_text, "count": count}
            for target_text, count in self._conn.execute(sql, tuple(bind)).fetchall()
        ]

    # ------------------------------------------------------------------
    # 레퍼런스 매칭 API (reference_mixin 지원)
    # ------------------------------------------------------------------

    def get_source_by_key(
        self, id: int, unknown: int, idx: int,
    ) -> str | None:
        """(id, unknown, idx) 키의 source 반환. 없으면 None."""
        row = self._conn.execute(
            "SELECT source FROM records WHERE id=? AND unknown=? AND idx=?",
            (id, unknown, idx),
        ).fetchone()
        return row[0] if row else None

    def get_translated_pairs(self) -> list[tuple[str, str]]:
        """번역된 고유 (source, target) 쌍. target != '' AND target != source."""
        return self._conn.execute(
            "SELECT DISTINCT source, target FROM records "
            "WHERE target != '' AND target != source"
        ).fetchall()

    def get_untranslated_records(self) -> list[tuple]:
        """미번역 레코드. → (rowid, id, unknown, idx, source)."""
        return self._conn.execute(
            "SELECT rowid, id, unknown, idx, source "
            "FROM records WHERE target = ''"
        ).fetchall()

    def get_all_records_keys_sources(self) -> list[tuple]:
        """전체 레코드의 키+source. → (id, unknown, idx, source)."""
        return self._conn.execute(
            "SELECT id, unknown, idx, source FROM records"
        ).fetchall()

    def populate_ref_filter(self, rowids: list[int]) -> None:
        """_ref_filter 임시 테이블에 rowid 목록 저장 (필터용)."""
        self._conn.execute(
            "CREATE TEMP TABLE IF NOT EXISTS _ref_filter "
            "(rowid INTEGER PRIMARY KEY)"
        )
        self._conn.execute("DELETE FROM _ref_filter")
        chunk_size = 500
        for i in range(0, len(rowids), chunk_size):
            chunk = [(r,) for r in rowids[i : i + chunk_size]]
            self._conn.executemany(
                "INSERT INTO _ref_filter VALUES (?)", chunk,
            )

    def bulk_apply_translations(
        self, updates: list[tuple[str, int]],
    ) -> None:
        """일괄 번역 적용. [(translation, rowid), ...]. modified=1 설정."""
        chunk_size = 500
        for i in range(0, len(updates), chunk_size):
            chunk = updates[i : i + chunk_size]
            self._conn.executemany(
                "UPDATE records SET target = ?, modified = 1 WHERE rowid = ?",
                chunk,
            )
        self._conn.commit()

    def get_modified_count(self) -> int:
        """modified=1 레코드 수."""
        row = self._conn.execute(
            "SELECT count(*) FROM records WHERE modified = 1"
        ).fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Export 용 전체 덤프
    # ------------------------------------------------------------------

    def iter_all_records(self):
        """전체 레코드를 (id, unknown, idx, source, target) 순서로 순회."""
        return self._conn.execute(
            "SELECT id, unknown, idx, source, target "
            "FROM records ORDER BY id, unknown, idx"
        )

    def get_all_for_build(self) -> list[tuple]:
        """빌더용: (id, unknown, idx, text) 정렬 리스트. target이 있으면 target 우선."""
        return self._conn.execute(
            "SELECT id, unknown, idx, "
            "CASE WHEN target != '' THEN target ELSE source END "
            "FROM records ORDER BY id, unknown, idx"
        ).fetchall()

    # ------------------------------------------------------------------
    # Lang Diff — 새 .lang 파일과 기존 DB 비교
    # ------------------------------------------------------------------

    def diff_with_lang(
        self,
        new_records: list[tuple[int, int, int, str]],
    ) -> dict:
        """새 .lang 레코드와 기존 DB를 비교하여 차이점을 반환.

        Args:
            new_records: 새 .lang에서 파싱된 (id, unknown, idx, source) 리스트

        Returns:
            {
                "added":    [(id, unknown, idx, source), ...],   # 신규 문자열
                "removed":  [(id, unknown, idx, source), ...],   # 삭제된 문자열
                "changed":  [(id, unknown, idx, old_source, new_source, target), ...],  # 원문 변경
                "unchanged": int,                                 # 변경 없는 수
                "summary": { "added": int, "removed": int, "changed": int, "unchanged": int },
            }
        """
        # 임시 테이블에 새 레코드 삽입
        self._conn.execute(
            "CREATE TEMP TABLE IF NOT EXISTS new_lang ("
            "  id INTEGER NOT NULL, unknown INTEGER NOT NULL, "
            "  idx INTEGER NOT NULL, source TEXT NOT NULL DEFAULT '')"
        )
        self._conn.execute("DELETE FROM new_lang")

        CHUNK = 500
        for i in range(0, len(new_records), CHUNK):
            batch = new_records[i : i + CHUNK]
            self._conn.executemany(
                "INSERT INTO new_lang (id, unknown, idx, source) VALUES (?, ?, ?, ?)",
                batch,
            )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_new_compound ON new_lang(id, unknown, idx)"
        )

        # 신규: 새 lang에는 있지만 기존 DB에 없는 키
        added = self._conn.execute(
            "SELECT n.id, n.unknown, n.idx, n.source "
            "FROM new_lang n "
            "LEFT JOIN records r ON n.id = r.id AND n.unknown = r.unknown AND n.idx = r.idx "
            "WHERE r.rowid IS NULL "
            "ORDER BY n.id, n.unknown, n.idx"
        ).fetchall()

        # 삭제: 기존 DB에는 있지만 새 lang에 없는 키
        removed = self._conn.execute(
            "SELECT r.id, r.unknown, r.idx, r.source "
            "FROM records r "
            "LEFT JOIN new_lang n ON r.id = n.id AND r.unknown = n.unknown AND r.idx = n.idx "
            "WHERE n.rowid IS NULL "
            "ORDER BY r.id, r.unknown, r.idx"
        ).fetchall()

        # 원문 변경: 같은 키인데 source가 다른 것
        changed = self._conn.execute(
            "SELECT r.id, r.unknown, r.idx, r.source, n.source, r.target "
            "FROM records r "
            "INNER JOIN new_lang n ON r.id = n.id AND r.unknown = n.unknown AND r.idx = n.idx "
            "WHERE r.source != n.source "
            "ORDER BY r.id, r.unknown, r.idx"
        ).fetchall()

        # 변경 없음
        unchanged = self._conn.execute(
            "SELECT COUNT(*) "
            "FROM records r "
            "INNER JOIN new_lang n ON r.id = n.id AND r.unknown = n.unknown AND r.idx = n.idx "
            "WHERE r.source = n.source"
        ).fetchone()[0]

        # 임시 테이블 정리
        self._conn.execute("DROP TABLE IF EXISTS new_lang")

        return {
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged": unchanged,
            "summary": {
                "added": len(added),
                "removed": len(removed),
                "changed": len(changed),
                "unchanged": unchanged,
            },
        }

    def merge_new_lang(
        self,
        new_records: list[tuple[int, int, int, str]],
    ) -> dict:
        """새 .lang 파일의 레코드를 기존 DB에 머지.

        - 신규 키: source에 추가 (target 비워둠 → 번역 필요)
        - 삭제된 키: 그대로 유지 (수동 정리용)
        - 원문 변경: source 업데이트, target 유지 (재번역 필요 표시)
        - 변경 없음: 그대로 유지

        Returns:
            diff_with_lang과 동일한 요약 + "merged" 카운트
        """
        diff = self.diff_with_lang(new_records)

        # 신규 레코드 삽입
        if diff["added"]:
            CHUNK = 500
            rows = diff["added"]
            for i in range(0, len(rows), CHUNK):
                batch = rows[i : i + CHUNK]
                self._conn.executemany(
                    "INSERT INTO records (id, unknown, idx, source) VALUES (?, ?, ?, ?)",
                    batch,
                )

        # 원문 변경된 레코드의 source 업데이트
        if diff["changed"]:
            for id_, unknown, idx, _old_src, new_src, _target in diff["changed"]:
                self._conn.execute(
                    "UPDATE records SET source = ? WHERE id = ? AND unknown = ? AND idx = ?",
                    (new_src, id_, unknown, idx),
                )

        if diff["added"] or diff["changed"]:
            self._conn.commit()
            self._record_count = None

        diff["summary"]["merged_added"] = len(diff["added"])
        diff["summary"]["merged_source_updated"] = len(diff["changed"])
        return diff

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()
