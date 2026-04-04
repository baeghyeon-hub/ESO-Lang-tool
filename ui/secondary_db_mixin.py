"""
보조 DB(en.lang, kr.lang) 경로 탐색 + 수명주기 + lazy 로드 mixin.

MainWindow에서 분리된 보조 DB 관리 로직.
"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from core.db import LangDatabase
from core.lang_parser import parse_lang
from ui.workers import LoadWorker


class SecondaryDbMixin:
    """보조 DB(en.lang, kr.lang) 경로 탐색, 로드/해제, lazy 초기화."""

    # ------------------------------------------------------------------
    # 경로 탐색
    # ------------------------------------------------------------------

    def _resolve_reference_lang_path(self) -> Path | None:
        if not self._load_filepath:
            return None

        current_path = Path(self._load_filepath).resolve()
        candidates: list[Path] = []
        if current_path.name.lower() != "kr.lang":
            candidates.append(current_path.with_name("kr.lang"))
        candidates.extend([
            current_path.parent / "기존 ESO 한글패치" / "kr.lang",
            current_path.parent / "기존 ESO 한글패치" / "gamedata" / "lang" / "kr.lang",
            Path.cwd() / "기존 ESO 한글패치" / "kr.lang",
            Path.cwd() / "기존 ESO 한글패치" / "gamedata" / "lang" / "kr.lang",
        ])

        seen: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved == current_path or resolved in seen:
                continue
            seen.add(resolved)
            if candidate.is_file():
                return candidate
        return None

    def _resolve_base_lang_path(self) -> Path | None:
        if not self._load_filepath:
            return None

        current_path = Path(self._load_filepath).resolve()
        candidates = [
            current_path.with_name("en.lang"),
            current_path.parent / "en.lang",
            Path.cwd() / "en.lang",
        ]

        seen: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved == current_path or resolved in seen:
                continue
            seen.add(resolved)
            if candidate.is_file():
                return candidate
        return None

    # ------------------------------------------------------------------
    # DB 로드 / 해제
    # ------------------------------------------------------------------

    def _ensure_reference_db(self) -> LangDatabase | None:
        reference_path = self._resolve_reference_lang_path()
        if reference_path is None:
            return None

        reference_path_str = str(reference_path)
        if (
            self._reference_db is not None
            and self._reference_filepath == reference_path_str
        ):
            return self._reference_db

        self._close_reference_db()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            reference_data = reference_path.read_bytes()
            reference_codec = LoadWorker._detect_codec(reference_data)
            reference_db = LangDatabase()
            parse_lang(
                reference_path,
                reference_db,
                codec=reference_codec,
                data=reference_data,
            )
        except Exception:
            self._close_reference_db()
            return None
        finally:
            QApplication.restoreOverrideCursor()

        self._reference_db = reference_db
        self._reference_filepath = reference_path_str
        self._reference_codec_name = reference_codec.name
        return self._reference_db

    def _ensure_base_db(self) -> LangDatabase | None:
        base_path = self._resolve_base_lang_path()
        if base_path is None:
            return None

        base_path_str = str(base_path)
        if self._base_db is not None and self._base_filepath == base_path_str:
            return self._base_db

        self._close_base_db()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            base_data = base_path.read_bytes()
            base_db = LangDatabase()
            parse_lang(base_path, base_db, data=base_data)
        except Exception:
            self._close_base_db()
            return None
        finally:
            QApplication.restoreOverrideCursor()

        self._base_db = base_db
        self._base_filepath = base_path_str
        return self._base_db

    def _close_base_db(self):
        if self._base_db is not None:
            self._base_db.close()
            self._base_db = None
            self._base_filepath = ""

    def _close_reference_db(self):
        if self._reference_db is not None:
            self._reference_db.close()
            self._reference_db = None
            self._reference_filepath = ""
            self._reference_codec_name = ""

    # ------------------------------------------------------------------
    # Lazy secondary DB 로드
    # ------------------------------------------------------------------

    def _on_bottom_tab_changed(self, index: int):
        """하단 탭 전환 시 lazy DB 로드."""
        self._ensure_secondary_dbs()

    def _ensure_secondary_dbs(self):
        if self._db is None:
            return
        if getattr(self, "_secondary_dbs_loaded", False):
            return
        self._secondary_dbs_loaded = True

        reference_db = self._ensure_reference_db()
        if reference_db is not None:
            self._translate_panel.set_db(
                self._db, self._undo_mgr, reference_db, self._codec_name,
            )

        en_db = self._ensure_base_db()
        if en_db is not None:
            self._glossary_panel.set_db(self._db, en_db=en_db, kr_db=self._db)
