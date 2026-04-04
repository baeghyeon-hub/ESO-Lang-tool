"""
번역 탭 UI — 에디터 패널 영역의 "번역" 탭.

워크플로우:
1. 테이블에서 행 선택 → 우클릭 → "번역 대상 지정"
2. 번역 탭에서 지정된 대상 확인 → "번역 시작"
3. 완료 후 결과 표시
"""

from __future__ import annotations

import asyncio

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.config import (
    ConfigManager,
    TranslationSettings,
    PROVIDER_LABELS,
    PROVIDER_MODELS,
)
from core.db import LangDatabase
from core.llm_providers import create_provider
from core.translator import TranslationItem, TranslationPipeline, TranslationSummary
from core.undo import UndoManager


# ---------------------------------------------------------------------------
# Translation Worker (QThread)
# ---------------------------------------------------------------------------

class TranslationWorker(QThread):
    """백그라운드 번역 실행."""

    progress = pyqtSignal(str, int, int)  # (stage, current, total)
    finished_signal = pyqtSignal(object)  # TranslationSummary

    def __init__(
        self,
        pipeline: TranslationPipeline,
        items: list[TranslationItem],
        parent=None,
    ):
        super().__init__(parent)
        self._pipeline = pipeline
        self._items = items
        self._cancelled = False

    def run(self):
        try:
            summary = asyncio.run(self._pipeline.run(self._items))
            self.finished_signal.emit(summary)
        except Exception:
            summary = TranslationSummary(total_items=len(self._items))
            summary.failed_count = len(self._items)
            self.finished_signal.emit(summary)

    def cancel(self):
        self._cancelled = True


# ---------------------------------------------------------------------------
# API Key Dialog
# ---------------------------------------------------------------------------

class ApiKeyDialog(QDialog):
    """API 키 설정 다이얼로그."""

    def __init__(self, settings: TranslationSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 키 설정")
        self.setMinimumWidth(420)
        self._settings = settings
        self._key_edits: dict[str, QLineEdit] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        for provider_name in PROVIDER_MODELS:
            label = PROVIDER_LABELS.get(provider_name, provider_name)
            group = QGroupBox(label)
            form = QFormLayout(group)

            key_edit = QLineEdit()
            key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            cfg = self._settings.providers.get(provider_name)
            if cfg and cfg.api_key:
                key_edit.setText(cfg.api_key)
            key_edit.setPlaceholderText("API 키를 입력하세요")
            form.addRow("API Key:", key_edit)
            self._key_edits[provider_name] = key_edit

            layout.addWidget(group)

        # 버튼
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        save_btn = QPushButton("저장")
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn)

        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

    def get_updated_settings(self) -> TranslationSettings:
        """업데이트된 설정 반환."""
        for provider_name, edit in self._key_edits.items():
            key = edit.text().strip()
            if provider_name in self._settings.providers:
                self._settings.providers[provider_name].api_key = key
        return self._settings


# ---------------------------------------------------------------------------
# Translate Panel
# ---------------------------------------------------------------------------

_STYLE_QUEUE_LABEL = (
    "font-size: 14px; font-weight: bold; color: #ffffff; padding: 4px 0;"
)
_STYLE_QUEUE_EMPTY = (
    "font-size: 14px; font-weight: bold; color: #888888; padding: 4px 0;"
)
_STYLE_INFO = "font-size: 12px; color: #cccccc;"
_STYLE_RESULT = "font-size: 12px; color: #d4d4d4; padding: 2px 0;"


class TranslatePanel(QWidget):
    """번역 탭 위젯 — 큐 기반 워크플로우."""

    translation_completed = pyqtSignal(int)  # 변경된 행 수

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db: LangDatabase | None = None
        self._undo_mgr: UndoManager | None = None
        self._reference_db: LangDatabase | None = None
        self._codec_name: str = "identity"
        self._worker: TranslationWorker | None = None
        self._config_mgr = ConfigManager()
        self._settings = self._config_mgr.load()

        # 번역 대상 큐 (rowid 집합)
        self._queue: set[int] = set()

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # ── 상단: 큐 상태 + 모델/옵션 ──
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        # 큐 상태 (좌측)
        queue_section = QVBoxLayout()
        queue_section.setSpacing(4)
        self._queue_label = QLabel("번역 대상: 0건")
        self._queue_label.setStyleSheet(_STYLE_QUEUE_EMPTY)
        queue_section.addWidget(self._queue_label)

        self._queue_info = QLabel(
            "테이블에서 행을 선택하고 우클릭 → '번역 대상 지정'으로 추가하세요"
        )
        self._queue_info.setStyleSheet(_STYLE_INFO)
        self._queue_info.setWordWrap(True)
        queue_section.addWidget(self._queue_info)

        clear_btn = QPushButton("대상 초기화")
        clear_btn.setFixedWidth(100)
        clear_btn.setStyleSheet(
            "QPushButton { background-color: #3c3c3c; padding: 4px 8px; }"
        )
        clear_btn.clicked.connect(self._clear_queue)
        queue_section.addWidget(clear_btn)

        top_row.addLayout(queue_section, stretch=2)

        # 모델 선택 (중앙)
        model_group = QGroupBox("모델")
        model_layout = QFormLayout(model_group)
        model_layout.setSpacing(4)
        self._provider_combo = QComboBox()
        for name in PROVIDER_MODELS:
            self._provider_combo.addItem(PROVIDER_LABELS.get(name, name), name)
        idx = list(PROVIDER_MODELS.keys()).index(self._settings.active_provider) \
            if self._settings.active_provider in PROVIDER_MODELS else 0
        self._provider_combo.setCurrentIndex(idx)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        model_layout.addRow("Provider:", self._provider_combo)

        self._model_combo = QComboBox()
        self._populate_models()
        model_layout.addRow("Model:", self._model_combo)

        self._batch_spin = QSpinBox()
        self._batch_spin.setRange(5, 100)
        self._batch_spin.setValue(self._settings.batch_size)
        model_layout.addRow("배치 크기:", self._batch_spin)
        top_row.addWidget(model_group, stretch=1)

        # 옵션 (우측)
        option_group = QGroupBox("옵션")
        option_layout = QVBoxLayout(option_group)
        option_layout.setSpacing(4)
        self._glossary_cb = QCheckBox("용어집 주입")
        self._glossary_cb.setChecked(self._settings.glossary_injection)
        option_layout.addWidget(self._glossary_cb)
        self._dedup_cb = QCheckBox("중복 전파")
        self._dedup_cb.setChecked(self._settings.auto_apply_duplicates)
        option_layout.addWidget(self._dedup_cb)
        option_layout.addStretch(1)
        top_row.addWidget(option_group, stretch=1)

        layout.addLayout(top_row)

        # ── 진행률 ──
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet(_STYLE_RESULT)
        self._progress_label.setVisible(False)
        layout.addWidget(self._progress_label)

        # ── 하단 버튼 ──
        btn_row = QHBoxLayout()
        self._api_key_btn = QPushButton("API 키 설정")
        self._api_key_btn.setStyleSheet(
            "QPushButton { background-color: #3c3c3c; padding: 5px 12px; }"
        )
        self._api_key_btn.clicked.connect(self._open_api_key_dialog)
        btn_row.addWidget(self._api_key_btn)

        btn_row.addStretch(1)

        self._start_btn = QPushButton("번역 시작")
        self._start_btn.setStyleSheet(
            "QPushButton { background-color: #0e639c; font-weight: bold; "
            "padding: 6px 20px; color: #ffffff; }"
            "QPushButton:disabled { background-color: #2d2d2d; color: #666; }"
        )
        self._start_btn.clicked.connect(self._start_translation)
        self._start_btn.setEnabled(False)
        btn_row.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("취소")
        self._cancel_btn.setStyleSheet(
            "QPushButton { background-color: #3c3c3c; padding: 5px 12px; }"
        )
        self._cancel_btn.clicked.connect(self._cancel_translation)
        self._cancel_btn.setEnabled(False)
        btn_row.addWidget(self._cancel_btn)

        layout.addLayout(btn_row)
        layout.addStretch(1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_db(
        self,
        db: LangDatabase | None,
        undo_mgr: UndoManager | None,
        reference_db: LangDatabase | None,
        codec_name: str,
    ) -> None:
        self._db = db
        self._undo_mgr = undo_mgr
        self._reference_db = reference_db
        self._codec_name = codec_name
        self._queue.clear()
        self._update_queue_display()

    def add_to_queue(self, rowids: list[int]) -> None:
        """번역 대상 큐에 rowid 추가."""
        self._queue.update(rowids)
        self._update_queue_display()

    def remove_from_queue(self, rowids: list[int]) -> None:
        """번역 대상 큐에서 rowid 제거."""
        self._queue.difference_update(rowids)
        self._update_queue_display()

    def is_in_queue(self, rowid: int) -> bool:
        return rowid in self._queue

    def queue_count(self) -> int:
        return len(self._queue)

    # ------------------------------------------------------------------
    # Queue display
    # ------------------------------------------------------------------

    def _update_queue_display(self):
        count = len(self._queue)
        if count == 0:
            self._queue_label.setText("번역 대상: 0건")
            self._queue_label.setStyleSheet(_STYLE_QUEUE_EMPTY)
            self._queue_info.setText(
                "테이블에서 행을 선택하고 우클릭 → '번역 대상 지정'으로 추가하세요"
            )
            self._start_btn.setEnabled(False)
        else:
            self._queue_label.setText(f"번역 대상: {count:,}건 지정됨")
            self._queue_label.setStyleSheet(_STYLE_QUEUE_LABEL)
            batch_size = self._batch_spin.value()

            # 미번역 건수 추산 (큐 중 target이 비어있는 것만)
            if self._db:
                untranslated = self._count_untranslated_in_queue()
                unique = self._count_unique_sources_in_queue()
                api_calls = (unique + batch_size - 1) // batch_size if unique > 0 else 0
                self._queue_info.setText(
                    f"미번역 {untranslated:,}건 · 고유 source {unique:,}개 "
                    f"· ~{api_calls:,} API 호출"
                )
            else:
                self._queue_info.setText(f"{count:,}건 지정됨")
            self._start_btn.setEnabled(self._db is not None)

    def _count_untranslated_in_queue(self) -> int:
        """큐 내 미번역 건수."""
        if not self._db or not self._queue:
            return 0
        rowids = list(self._queue)
        placeholders = ",".join("?" * len(rowids))
        row = self._db._conn.execute(
            f"SELECT count(*) FROM records WHERE rowid IN ({placeholders}) "
            f"AND target = '' AND source != ''",
            rowids,
        ).fetchone()
        return row[0] if row else 0

    def _count_unique_sources_in_queue(self) -> int:
        """큐 내 고유 source 수 (미번역만)."""
        if not self._db or not self._queue:
            return 0
        rowids = list(self._queue)
        placeholders = ",".join("?" * len(rowids))
        row = self._db._conn.execute(
            f"SELECT count(DISTINCT source) FROM records "
            f"WHERE rowid IN ({placeholders}) AND target = '' AND source != ''",
            rowids,
        ).fetchone()
        return row[0] if row else 0

    def _clear_queue(self):
        self._queue.clear()
        self._update_queue_display()

    # ------------------------------------------------------------------
    # Model UI
    # ------------------------------------------------------------------

    def _populate_models(self):
        self._model_combo.clear()
        provider = self._provider_combo.currentData()
        if provider and provider in PROVIDER_MODELS:
            for model in PROVIDER_MODELS[provider]:
                self._model_combo.addItem(model)
            cfg = self._settings.providers.get(provider)
            if cfg and cfg.model:
                idx = self._model_combo.findText(cfg.model)
                if idx >= 0:
                    self._model_combo.setCurrentIndex(idx)

    def _on_provider_changed(self):
        self._populate_models()

    # ------------------------------------------------------------------
    # API Key
    # ------------------------------------------------------------------

    def _open_api_key_dialog(self):
        dialog = ApiKeyDialog(self._settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._settings = dialog.get_updated_settings()
            self._config_mgr.save(self._settings)

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def _start_translation(self):
        if self._db is None or self._undo_mgr is None:
            return
        if self._worker is not None:
            return
        if not self._queue:
            QMessageBox.information(self, "번역 대상 없음", "번역 대상이 지정되지 않았습니다.")
            return

        provider_name = self._provider_combo.currentData()
        model_name = self._model_combo.currentText()

        # API 키 확인
        cfg = self._settings.providers.get(provider_name)
        if not cfg or not cfg.api_key:
            QMessageBox.warning(
                self, "API 키 필요",
                f"{PROVIDER_LABELS.get(provider_name, provider_name)}의 API 키를 설정해주세요.",
            )
            self._open_api_key_dialog()
            return

        # 설정 업데이트
        self._settings.active_provider = provider_name
        if cfg:
            cfg.model = model_name
        self._settings.batch_size = self._batch_spin.value()
        self._settings.glossary_injection = self._glossary_cb.isChecked()
        self._settings.auto_apply_duplicates = self._dedup_cb.isChecked()
        self._config_mgr.save(self._settings)

        # Provider 생성
        try:
            provider = create_provider(provider_name, cfg.api_key, model_name)
        except ValueError as exc:
            QMessageBox.critical(self, "프로바이더 오류", str(exc))
            return

        # 큐 기반 rowid WHERE 절 구성
        queue_rowids = list(self._queue)
        placeholders = ",".join("?" * len(queue_rowids))
        queue_where = f"rowid IN ({placeholders})"
        queue_params = tuple(queue_rowids)

        pipeline = TranslationPipeline(
            db=self._db,
            reference_db=self._reference_db,
            provider=provider,
            settings=self._settings,
            progress_cb=self._on_pipeline_progress,
            cancel_check=lambda: self._worker is not None and self._worker._cancelled,
        )

        items = pipeline.prepare_items(
            where_clause=queue_where,
            params=queue_params,
        )

        if not items:
            QMessageBox.information(self, "번역 대상 없음", "지정된 범위에 미번역 항목이 없습니다.")
            return

        # 확인
        count = len(items)
        batch_size = self._settings.batch_size
        api_calls = (count + batch_size - 1) // batch_size
        reply = QMessageBox.question(
            self, "번역 시작",
            f"{count:,}개 고유 문자열, ~{api_calls:,} API 호출.\n시작하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # UI 상태 전환
        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._progress_bar.setVisible(True)
        self._progress_bar.setMaximum(api_calls)
        self._progress_bar.setValue(0)
        self._progress_label.setVisible(True)
        self._progress_label.setText("준비 중...")

        # Worker 시작
        self._worker = TranslationWorker(pipeline, items, self)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.finished_signal.connect(self._on_worker_finished)
        self._worker.start()

    def _cancel_translation(self):
        if self._worker:
            self._worker.cancel()
            self._cancel_btn.setEnabled(False)
            self._progress_label.setText("취소 중...")

    def _on_pipeline_progress(self, stage: str, current: int, total: int):
        if self._worker:
            self._worker.progress.emit(stage, current, total)

    def _on_worker_progress(self, stage: str, current: int, total: int):
        self._progress_bar.setMaximum(max(total, 1))
        self._progress_bar.setValue(current)
        self._progress_label.setText(f"{stage}  {current:,} / {total:,}")

    def _on_worker_finished(self, summary: TranslationSummary):
        self._worker = None
        self._start_btn.setEnabled(bool(self._queue))
        self._cancel_btn.setEnabled(False)

        msg = (
            f"완료: 성공 {summary.ok_count:,}  실패 {summary.failed_count:,}  "
            f"재시도 {summary.retry_count:,}\n"
            f"DB 적용: {summary.applied_count:,}건  |  "
            f"토큰: 입력 {summary.total_input_tokens:,} / 출력 {summary.total_output_tokens:,}"
        )
        self._progress_label.setText(msg)

        if summary.applied_count > 0:
            # 번역 완료된 항목은 큐에서 제거
            self._queue.clear()
            self._update_queue_display()
            self.translation_completed.emit(summary.applied_count)

        QMessageBox.information(self, "번역 완료", msg)
