"""
백그라운드 워커 스레드 — 파일 로딩 / 저장.
"""

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from core.db import LangDatabase
from core.lang_builder import build_lang
from core.lang_parser import parse_lang
from core.text_codec import TextCodec, IdentityCodec, get_codec, suggest_codec


class LoadWorker(QThread):
    """백그라운드 .lang 파일 로딩 + FTS5 빌드."""

    progress = pyqtSignal(str, int, int)  # (단계명, current, total)

    def __init__(self, filepath: str, db: LangDatabase, *, force_codec: str | None = None):
        super().__init__()
        self._filepath = filepath
        self._db = db
        self._force_codec = force_codec
        self._cancelled = False
        self.meta: dict | None = None
        self.error_msg: str | None = None
        self.codec_name: str = "identity"
        self.glossary_result: dict | None = None

    def cancel(self):
        self._cancelled = True

    @property
    def was_cancelled(self) -> bool:
        return self._cancelled

    def run(self):
        try:
            import time as _time
            t0 = _time.perf_counter()
            print(f"[LoadWorker] 파일 읽기 시작: {self._filepath}")

            file_data = Path(self._filepath).read_bytes()
            print(f"[LoadWorker] 파일 읽기 완료: {len(file_data):,} bytes ({_time.perf_counter()-t0:.2f}s)")

            if self._force_codec:
                codec = get_codec(self._force_codec)
            else:
                self.progress.emit("코덱 감지 중...", 0, 0)
                codec = self._detect_codec(file_data)
            self.codec_name = codec.name
            print(f"[LoadWorker] 코덱: {codec.name} ({_time.perf_counter()-t0:.2f}s)")

            self.meta = parse_lang(
                self._filepath,
                self._db,
                codec=codec,
                data=file_data,
                progress_cb=self._on_parse_progress,
                cancel_check=lambda: self._cancelled,
            )
            print(f"[LoadWorker] 파싱 완료: {self.meta.get('record_count', '?'):,} records ({_time.perf_counter()-t0:.2f}s)")
            if self._cancelled:
                return

            self.progress.emit("FTS5 인덱스 빌드 중...", 0, 0)
            self._db.build_fts()
            print(f"[LoadWorker] FTS5 빌드 완료 ({_time.perf_counter()-t0:.2f}s)")

        except InterruptedError:
            self._cancelled = True
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error_msg = str(e)

    @staticmethod
    def _detect_codec(data: bytes) -> TextCodec:
        """파일 텍스트 샘플로 코덱 자동 감지."""
        import struct

        if len(data) < 8:
            return IdentityCodec()
        _, count = struct.unpack_from(">II", data, 0)
        record_end = 8 + count * 16
        if record_end >= len(data):
            return IdentityCodec()

        text_blob = data[record_end:]
        parts = text_blob.split(b"\x00")
        sample_texts = [
            p.decode("utf-8", errors="replace")
            for p in parts[:2000]
            if p
        ]

        codec_name = suggest_codec(sample_texts)
        return get_codec(codec_name)

    def _on_parse_progress(self, current: int, total: int):
        if self._cancelled:
            return
        self.progress.emit("레코드 로딩", current, total)


class SaveWorker(QThread):
    """백그라운드 .lang 파일 저장."""

    progress = pyqtSignal(str, int, int)

    def __init__(self, db: LangDatabase, output_path: str, *, codec_name: str = "identity"):
        super().__init__()
        self._db = db
        self._output_path = output_path
        self._codec_name = codec_name
        self.error_msg: str | None = None
        self.build_meta: dict | None = None

    def run(self):
        try:
            codec = get_codec(self._codec_name)
            self.progress.emit("빌드 중...", 0, 0)
            self.build_meta = build_lang(
                self._db,
                self._output_path,
                codec=codec,
                progress_cb=self._on_progress,
            )
        except Exception as e:
            self.error_msg = str(e)

    def _on_progress(self, current: int, total: int):
        self.progress.emit("레코드 빌드", current, total)
