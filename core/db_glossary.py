"""
용어집 DB 쿼리 mixin.

LangDatabase에서 분리된 glossary 테이블 관련 API.
"""


class GlossaryMixin:
    """용어집(glossary) 테이블 CRUD 및 프롬프트용 조회."""

    def glossary_count(self) -> int:
        """용어집 전체 건수."""
        self.init_glossary()
        return self._conn.execute("SELECT count(*) FROM glossary").fetchone()[0]

    def get_glossary_by_category(
        self,
        category: str | None = None,
        *,
        offset: int = 0,
        limit: int = 200,
    ) -> list[tuple]:
        """용어집 조회 (페이징). → (rowid, term, translation, category, gender, usage_count, note)."""
        self.init_glossary()
        sql = "SELECT rowid, term, translation, category, gender, usage_count, note FROM glossary"
        bind: list = []
        if category:
            sql += " WHERE category = ?"
            bind.append(category)
        sql += " ORDER BY usage_count DESC, term LIMIT ? OFFSET ?"
        bind.extend([limit, offset])
        return self._conn.execute(sql, bind).fetchall()

    def search_glossary(self, keyword: str, *, limit: int = 200) -> list[tuple]:
        """용어집 검색 (term LIKE)."""
        self.init_glossary()
        return self._conn.execute(
            "SELECT rowid, term, translation, category, gender, usage_count, note "
            "FROM glossary WHERE term LIKE ? ORDER BY usage_count DESC LIMIT ?",
            (f"%{keyword}%", limit),
        ).fetchall()

    def update_glossary_translation(
        self, rowid: int, translation: str, note: str = ""
    ) -> bool:
        """용어집 항목의 번역/메모 수정."""
        self.init_glossary()
        cur = self._conn.execute(
            "UPDATE glossary SET translation = ?, note = ? WHERE rowid = ?",
            (translation, note, rowid),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_glossary_categories(self) -> list[tuple[str, int]]:
        """용어집 카테고리별 건수."""
        self.init_glossary()
        return self._conn.execute(
            "SELECT category, count(*) FROM glossary GROUP BY category ORDER BY count(*) DESC"
        ).fetchall()

    def get_glossary_for_prompt(
        self,
        source_texts: list[str],
        *,
        max_terms: int = 50,
    ) -> list[tuple[str, str, str]]:
        """source_texts에 등장하는 용어집 항목. → (term, translation, category).

        번역이 있는 항목만 반환. usage_count DESC 정렬.
        """
        self.init_glossary()
        if not source_texts:
            return []

        all_terms = self._conn.execute(
            "SELECT term, translation, category FROM glossary "
            "WHERE translation != '' "
            "ORDER BY usage_count DESC"
        ).fetchall()

        combined = " ".join(source_texts).lower()
        matched = []
        for term, translation, category in all_terms:
            if term.lower() in combined:
                matched.append((term, translation, category))
                if len(matched) >= max_terms:
                    break
        return matched
