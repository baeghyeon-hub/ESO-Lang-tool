"""
번역 파이프라인 DB 쿼리 mixin.

LangDatabase에서 분리된 translation pipeline 관련 API.
"""


class TranslationMixin:
    """번역 파이프라인용 DB 쿼리 (미번역 추출, 일괄 적용, 진행 추적)."""

    def get_untranslated_unique_sources(
        self,
        *,
        id_filter: "int | list[int] | None" = None,
        where_clause: str = "",
        params: tuple = (),
    ) -> list[tuple[int, int, str]]:
        """고유 미번역 source 추출. → (representative_rowid, group_id, source).

        source별로 하나의 대표 rowid만 반환 (중복 제거).
        """
        sql = "SELECT MIN(rowid), id, source FROM records"
        conditions = ["target = ''", "source != ''"]
        bind: list = []

        self._id_filter_clause(id_filter, conditions, bind)
        if where_clause:
            conditions.append(where_clause)
            bind.extend(params)

        sql += " WHERE " + " AND ".join(conditions)
        sql += " GROUP BY source ORDER BY id, source"
        return self._conn.execute(sql, bind).fetchall()

    def get_rowids_by_source(self, source_text: str) -> list[int]:
        """동일 source의 모든 rowid (중복 전파용)."""
        return [
            row[0]
            for row in self._conn.execute(
                "SELECT rowid FROM records WHERE source = ?",
                (source_text,),
            ).fetchall()
        ]

    def batch_get_rowids_by_sources(
        self, source_texts: list[str],
    ) -> dict[str, list[int]]:
        """여러 source의 rowid를 한 번에 조회. → {source: [rowid, ...]}."""
        if not source_texts:
            return {}
        self._conn.execute(
            "CREATE TEMP TABLE IF NOT EXISTS _tmp_sources (s TEXT)"
        )
        self._conn.execute("DELETE FROM _tmp_sources")
        self._conn.executemany(
            "INSERT INTO _tmp_sources VALUES (?)",
            [(s,) for s in source_texts],
        )
        rows = self._conn.execute(
            "SELECT r.source, r.rowid FROM records r "
            "INNER JOIN _tmp_sources t ON r.source = t.s "
            "ORDER BY r.source"
        ).fetchall()
        self._conn.execute("DELETE FROM _tmp_sources")

        result: dict[str, list[int]] = {}
        for source, rowid in rows:
            result.setdefault(source, []).append(rowid)
        return result

    def bulk_update_targets_no_fts(
        self, updates: list[tuple[int, str]],
    ) -> int:
        """대량 target 업데이트 (FTS 동기화 생략, 후에 rebuild_fts 호출 필요).

        Returns: 변경된 행 수.
        """
        if not updates:
            return 0
        self._conn.executemany(
            "UPDATE records SET target = ?, modified = 1 WHERE rowid = ?",
            [(target, rowid) for rowid, target in updates],
        )
        self._conn.commit()
        count = len(updates)
        self._record_count = None
        return count

    def update_translation_progress(
        self,
        rowid: int,
        status: str,
        model: str,
        attempt: int,
    ) -> None:
        """번역 진행 상태 업데이트 (upsert)."""
        self.init_translation_progress()
        self._conn.execute(
            "INSERT INTO translation_progress (record_rowid, status, model, attempt, translated_at) "
            "VALUES (?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(record_rowid) DO UPDATE SET "
            "status=excluded.status, model=excluded.model, "
            "attempt=excluded.attempt, translated_at=excluded.translated_at",
            (rowid, status, model, attempt),
        )
        self._conn.commit()

    def batch_update_translation_progress(
        self,
        updates: list[tuple[int, str, str, int]],
    ) -> None:
        """번역 진행 일괄 업데이트. [(rowid, status, model, attempt), ...]."""
        if not updates:
            return
        self.init_translation_progress()
        self._conn.executemany(
            "INSERT INTO translation_progress (record_rowid, status, model, attempt, translated_at) "
            "VALUES (?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(record_rowid) DO UPDATE SET "
            "status=excluded.status, model=excluded.model, "
            "attempt=excluded.attempt, translated_at=excluded.translated_at",
            updates,
        )
        self._conn.commit()

    def get_translation_progress_stats(self) -> dict:
        """번역 진행 통계. {'pending': N, 'translated': N, 'failed': N}."""
        self.init_translation_progress()
        rows = self._conn.execute(
            "SELECT status, count(*) FROM translation_progress GROUP BY status"
        ).fetchall()
        stats = {"pending": 0, "translated": 0, "failed": 0}
        for status, cnt in rows:
            stats[status] = cnt
        return stats
