"""
메인 윈도우 — 메뉴, 툴바, 스플리터 레이아웃 + 컨트롤러.

┌──────────────────────────────────────────────────┐
│ [메뉴바] 파일 | 편집 | 보기                         │
├──────────────────────────────────────────────────┤
│ [툴바] 열기 | 검색                                 │
├──────────────────────────────────────────────────┤
│ [검색바]                                          │
├────────────┬─────────────────────────────────────┤
│  그룹 트리  │  레코드 테이블  (Target 더블클릭 편집) │
│  (좌측)    │  (우측, 가상화)                       │
├────────────┴─────────────────────────────────────┤
│  Source (읽기전용)  │  Target (편집)               │
├──────────────────────────────────────────────────┤
│ [상태바] 파일 | 코덱 | 수정 | 번역율 | 레코드       │
└──────────────────────────────────────────────────┘
"""

import functools
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from PyQt6.QtCore import Qt, QPoint, QItemSelection, QModelIndex
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow, QSplitter, QWidget, QVBoxLayout,
    QFileDialog, QProgressDialog, QStatusBar, QLabel,
    QTabWidget, QToolBar, QMessageBox, QMenu,
)

from core.db import LangDatabase
from core.mod_tracker import save_mod_keys, load_mod_keys
from core.undo import UndoManager
from ui.editor_panel import EditorPanel
from ui.export_mixin import ExportImportMixin
from ui.find_replace_mixin import FindReplaceMixin
from ui.group_tree import GroupTreeView
from ui.record_table import RecordTableModel, RecordTableView
from ui.reference_mixin import ReferenceMixin
from ui.secondary_db_mixin import SecondaryDbMixin
from ui.search_bar import SearchBar
from ui.glossary_panel import GlossaryPanel
from ui.translate_panel import TranslatePanel
from ui.workers import LoadWorker, SaveWorker

_WINDOW_WIDTH = 1400
_WINDOW_HEIGHT = 850
_GROUP_TREE_MIN_WIDTH = 180
_GROUP_TREE_MAX_WIDTH = 350
_H_SPLITTER_SIZES = [220, 1180]
_V_SPLITTER_SIZES = [600, 200]
_NAV_HISTORY_LIMIT = 20


@dataclass
class _NavState:
    """뒤로가기용 네비게이션 스냅샷."""
    filter_text: str = "전체"
    search_text: str = ""
    regex_enabled: bool = False
    focus_field: str = ""      # "" | "source" | "target"
    focus_text: str = ""
    selected_rowid: int | None = None  # 복원할 선택 위치


def _require_model(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if self._model is None:
            return
        return func(self, *args, **kwargs)

    return wrapper


def _require_db(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if self._db is None:
            return
        return func(self, *args, **kwargs)

    return wrapper


def _require_db_model(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if self._db is None or self._model is None:
            return
        return func(self, *args, **kwargs)

    return wrapper


def _require_undo(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if self._undo_mgr is None:
            return
        return func(self, *args, **kwargs)

    return wrapper


class MainWindow(
    SecondaryDbMixin, ReferenceMixin, FindReplaceMixin, ExportImportMixin,
    QMainWindow,
):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESO Lang Tool")
        self.resize(_WINDOW_WIDTH, _WINDOW_HEIGHT)

        self._db: LangDatabase | None = None
        self._model: RecordTableModel | None = None
        self._undo_mgr: UndoManager | None = None
        self._worker: LoadWorker | None = None
        self._save_worker: SaveWorker | None = None
        self._base_db: LangDatabase | None = None
        self._base_filepath: str = ""
        self._reference_db: LangDatabase | None = None
        self._reference_filepath: str = ""
        self._reference_codec_name: str = ""
        self._progress: QProgressDialog | None = None
        self._codec_name: str = "identity"
        self._save_filepath: str = ""
        self._load_filepath: str = ""
        self._force_codec: str | None = None
        self._dirty = False  # 미저장 변경 추적
        self._nav_history: list[_NavState] = []
        self._restoring_nav = False  # 네비게이션 복원 중 재진입 방지

        self._nav_back_action = QAction("← 뒤로", self)
        self._nav_back_action.setShortcut(QKeySequence("Alt+Left"))
        self._nav_back_action.setToolTip("이전 보기로 돌아가기 (Alt+Left)")
        self._nav_back_action.setEnabled(False)
        self._nav_back_action.triggered.connect(self._nav_back)

        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._connect_signals()

    # ==================================================================
    # UI 구성
    # ==================================================================

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._search_bar = SearchBar()
        self._search_bar.setEnabled(False)
        layout.addWidget(self._search_bar)

        # 좌우: 그룹 트리 + 테이블
        self._h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._group_tree = GroupTreeView()
        self._group_tree.setMinimumWidth(_GROUP_TREE_MIN_WIDTH)
        self._group_tree.setMaximumWidth(_GROUP_TREE_MAX_WIDTH)
        self._table_view = RecordTableView()
        self._table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._h_splitter.addWidget(self._group_tree)
        self._h_splitter.addWidget(self._table_view)
        self._h_splitter.setStretchFactor(0, 0)
        self._h_splitter.setStretchFactor(1, 1)
        self._h_splitter.setSizes(_H_SPLITTER_SIZES)

        # 상하: 테이블 + 하단 탭 (편집/번역)
        self._v_splitter = QSplitter(Qt.Orientation.Vertical)
        self._bottom_tabs = QTabWidget()
        self._editor_panel = EditorPanel()
        self._translate_panel = TranslatePanel()
        self._glossary_panel = GlossaryPanel()
        self._bottom_tabs.addTab(self._editor_panel, "편집")
        self._bottom_tabs.addTab(self._translate_panel, "번역")
        self._bottom_tabs.addTab(self._glossary_panel, "용어집")
        self._v_splitter.addWidget(self._h_splitter)
        self._v_splitter.addWidget(self._bottom_tabs)
        self._v_splitter.setStretchFactor(0, 3)
        self._v_splitter.setStretchFactor(1, 1)
        self._v_splitter.setSizes(_V_SPLITTER_SIZES)

        layout.addWidget(self._v_splitter, stretch=1)

    def _setup_menu(self):
        menubar = self.menuBar()

        # ── 파일 ──
        file_menu = menubar.addMenu("파일(&F)")

        open_action = QAction("열기(&O)...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_file)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        self._save_action = QAction("저장(&S)...", self)
        self._save_action.setShortcut(QKeySequence.StandardKey.Save)
        self._save_action.setEnabled(False)
        self._save_action.triggered.connect(self._save_file)
        file_menu.addAction(self._save_action)

        self._save_as_action = QAction("다른 이름으로 저장(&A)...", self)
        self._save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._save_as_action.setEnabled(False)
        self._save_as_action.triggered.connect(self._save_file_as)
        file_menu.addAction(self._save_as_action)

        file_menu.addSeparator()

        self._export_action = QAction("선택 행 내보내기(&E)...", self)
        self._export_action.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self._export_action.setEnabled(False)
        self._export_action.triggered.connect(self._export_selected)
        file_menu.addAction(self._export_action)

        self._export_filtered_action = QAction("현재 필터 내보내기...", self)
        self._export_filtered_action.setEnabled(False)
        self._export_filtered_action.triggered.connect(self._export_filtered)
        file_menu.addAction(self._export_filtered_action)

        self._export_modified_action = QAction("내가 수정한 항목만 내보내기...", self)
        self._export_modified_action.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self._export_modified_action.setEnabled(False)
        self._export_modified_action.triggered.connect(self._export_modified)
        file_menu.addAction(self._export_modified_action)

        self._export_diff_action = QAction("en.lang 비교 내보내기 (전체 번역분)...", self)
        self._export_diff_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self._export_diff_action.setEnabled(False)
        self._export_diff_action.triggered.connect(self._export_diff)
        file_menu.addAction(self._export_diff_action)

        self._import_action = QAction("번역 가져오기(&I)...", self)
        self._import_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self._import_action.setEnabled(False)
        self._import_action.triggered.connect(self._import_translations)
        file_menu.addAction(self._import_action)

        file_menu.addSeparator()

        exit_action = QAction("종료(&X)", self)
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # ── 편집 ──
        edit_menu = menubar.addMenu("편집(&E)")

        self._undo_action = QAction("실행 취소(&Z)", self)
        self._undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self._undo_action.setEnabled(False)
        self._undo_action.triggered.connect(self._do_undo)
        edit_menu.addAction(self._undo_action)

        self._redo_action = QAction("다시 실행(&Y)", self)
        self._redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self._redo_action.setEnabled(False)
        self._redo_action.triggered.connect(self._do_redo)
        edit_menu.addAction(self._redo_action)

        edit_menu.addSeparator()

        self._replace_action = QAction("찾기/치환(&H)...", self)
        self._replace_action.setShortcut(QKeySequence("Ctrl+H"))
        self._replace_action.setEnabled(False)
        self._replace_action.triggered.connect(self._open_find_replace_dialog)
        edit_menu.addAction(self._replace_action)

        edit_menu.addSeparator()

        next_untrans = QAction("다음 미번역으로(&N)", self)
        next_untrans.setShortcut(QKeySequence("F3"))
        next_untrans.triggered.connect(self._jump_next_untranslated)
        edit_menu.addAction(next_untrans)

        # ── 보기 ──
        view_menu = menubar.addMenu("보기(&V)")

        view_menu.addAction(self._nav_back_action)
        view_menu.addSeparator()

        clear_filter = QAction("필터 초기화", self)
        clear_filter.setShortcut(QKeySequence("Ctrl+Shift+F"))
        clear_filter.triggered.connect(self._clear_filters)
        view_menu.addAction(clear_filter)

        view_menu.addSeparator()

        codec_menu = QMenu("텍스트 코덱", self)
        self._codec_auto_action = QAction("자동 감지 (기본)", self)
        self._codec_auto_action.setCheckable(True)
        self._codec_auto_action.setChecked(True)
        self._codec_auto_action.triggered.connect(
            lambda: self._reload_with_codec(None)
        )
        codec_menu.addAction(self._codec_auto_action)
        codec_menu.addSeparator()

        self._codec_identity_action = QAction("Identity (변환 없음)", self)
        self._codec_identity_action.setCheckable(True)
        self._codec_identity_action.triggered.connect(
            lambda: self._reload_with_codec("identity")
        )
        codec_menu.addAction(self._codec_identity_action)

        self._codec_kr_action = QAction("ESO KR Legacy (CJK→한글)", self)
        self._codec_kr_action.setCheckable(True)
        self._codec_kr_action.triggered.connect(
            lambda: self._reload_with_codec("eso_kr_legacy")
        )
        codec_menu.addAction(self._codec_kr_action)

        self._codec_kr_native_action = QAction("ESO KR Native (한글 직접)", self)
        self._codec_kr_native_action.setCheckable(True)
        self._codec_kr_native_action.triggered.connect(
            lambda: self._reload_with_codec("eso_kr_native")
        )
        codec_menu.addAction(self._codec_kr_native_action)
        view_menu.addMenu(codec_menu)

        # ── 번역 ──
        translate_menu = menubar.addMenu("번역(&T)")

        self._translate_action = QAction("LLM 번역 실행(&T)...", self)
        self._translate_action.setShortcut(QKeySequence("Ctrl+T"))
        self._translate_action.setEnabled(False)
        self._translate_action.triggered.connect(self._start_translation_tab)
        translate_menu.addAction(self._translate_action)

        self._translate_settings_action = QAction("API 키 설정(&S)...", self)
        self._translate_settings_action.triggered.connect(
            self._translate_panel._open_api_key_dialog
        )
        translate_menu.addAction(self._translate_settings_action)

        translate_menu.addSeparator()

        self._batch_ref_action = QAction("기존 번역 일괄 적용(&R)...", self)
        self._batch_ref_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self._batch_ref_action.setEnabled(False)
        self._batch_ref_action.triggered.connect(self._batch_apply_reference)
        translate_menu.addAction(self._batch_ref_action)

        translate_menu.addSeparator()

        self._glossary_action = QAction("용어집(&G)...", self)
        self._glossary_action.setShortcut(QKeySequence("Ctrl+G"))
        self._glossary_action.setEnabled(False)
        self._glossary_action.triggered.connect(self._open_glossary_tab)
        translate_menu.addAction(self._glossary_action)

    def _setup_toolbar(self):
        toolbar = QToolBar("메인")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_btn = QAction("열기", self)
        open_btn.triggered.connect(self._open_file)
        toolbar.addAction(open_btn)

        toolbar.addSeparator()

        toolbar.addAction(self._nav_back_action)

        toolbar.addSeparator()

        focus_search = QAction("검색 (Ctrl+F)", self)
        focus_search.setShortcut(QKeySequence.StandardKey.Find)
        focus_search.triggered.connect(self._search_bar.focus_input)
        toolbar.addAction(focus_search)

    def _setup_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        self._status_records = QLabel("  파일을 열어주세요 (파일 > 열기)")
        self._status_progress = QLabel("")
        self._status_source_progress = QLabel("")
        self._status_scope_progress = QLabel("")
        self._status_modified = QLabel("")
        self._status_file = QLabel("")
        self._status_codec = QLabel("")

        self._statusbar.addWidget(self._status_file, stretch=1)
        self._statusbar.addPermanentWidget(self._status_codec)
        self._statusbar.addPermanentWidget(self._status_modified)
        self._statusbar.addPermanentWidget(self._status_scope_progress)
        self._statusbar.addPermanentWidget(self._status_source_progress)
        self._statusbar.addPermanentWidget(self._status_progress)
        self._statusbar.addPermanentWidget(self._status_records)

    def _connect_signals(self):
        self._group_tree.group_selected.connect(self._on_group_selected)
        self._search_bar.search_results.connect(self._on_search_results)
        self._search_bar.filter_changed.connect(self._on_filter_changed)
        self._editor_panel.edit_committed.connect(self._on_edit_committed)
        self._editor_panel.batch_edit_committed.connect(self._on_batch_edit_committed)
        self._editor_panel.source_lookup_requested.connect(
            self._open_source_translation_lookup
        )
        self._table_view.customContextMenuRequested.connect(
            self._open_table_context_menu
        )
        self._translate_panel.translation_completed.connect(
            self._on_translation_completed
        )
        self._bottom_tabs.currentChanged.connect(self._on_bottom_tab_changed)

    # ==================================================================
    # 파일 로딩
    # ==================================================================

    def _open_file(self, checked: bool = False):
        if self._worker is not None:
            return
        if not self._confirm_discard():
            return
        filepath, _ = QFileDialog.getOpenFileName(
            self, "ESO .lang 파일 열기", "",
            "Lang Files (*.lang);;All Files (*)"
        )
        if filepath:
            self._load_file(filepath)

    def _reset_ui(self):
        if self._model:
            self._table_view.setModel(None)
            self._model = None
        self._undo_mgr = None
        self._dirty = False
        self._secondary_dbs_loaded = False
        self._editor_panel.clear_record()
        self._search_bar.clear_search()
        self._search_bar.setEnabled(False)
        self._search_bar.set_db(None)
        self._group_tree._tree_model.clear()
        self._save_action.setEnabled(False)
        self._save_as_action.setEnabled(False)
        self._undo_action.setEnabled(False)
        self._redo_action.setEnabled(False)
        self._replace_action.setEnabled(False)
        self._status_file.setText("")
        self._status_codec.setText("")
        self._status_modified.setText("")
        self._status_scope_progress.setText("")
        self._status_source_progress.setText("")
        self._status_progress.setText("")
        self._status_records.setText("  파일을 열어주세요 (파일 > 열기)")
        self._export_action.setEnabled(False)
        self._export_filtered_action.setEnabled(False)
        self._export_modified_action.setEnabled(False)
        self._export_diff_action.setEnabled(False)
        self._import_action.setEnabled(False)
        self._batch_ref_action.setEnabled(False)
        self._glossary_panel.set_db(None)
        self._glossary_action.setEnabled(False)
        self._nav_history.clear()
        self._nav_back_action.setEnabled(False)
        self._update_title()

    def _load_file(self, filepath: str, *, force_codec: str | None = None):
        if self._db:
            self._db.close()
            self._db = None
        self._close_base_db()
        self._close_reference_db()
        self._reset_ui()

        self._db = LangDatabase()
        self._force_codec = force_codec

        self._progress = QProgressDialog("파일 로딩 준비 중...", "취소", 0, 100, self)
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)
        self._progress.canceled.connect(self._on_load_cancelled)
        self._progress.show()

        self._load_filepath = filepath
        self._worker = LoadWorker(filepath, self._db, force_codec=force_codec)
        self._worker.progress.connect(self._on_load_progress)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_load_progress(self, stage: str, current: int, total: int):
        if self._progress is None:
            return
        if total > 0:
            pct = min(int(current / total * 95), 95)
            self._progress.setValue(pct)
            self._progress.setLabelText(f"{stage}... {current:,} / {total:,}")
        else:
            self._progress.setValue(96)
            self._progress.setLabelText(stage)

    def _on_load_cancelled(self):
        if self._worker:
            self._worker.cancel()

    def _on_worker_finished(self):
        print("[Main] _on_worker_finished 호출됨")
        worker = self._worker
        self._worker = None

        if self._progress:
            self._progress.close()
            self._progress = None

        if worker is None:
            return

        filepath = self._load_filepath

        if worker.was_cancelled:
            if self._db:
                self._db.close()
                self._db = None
            self._reset_ui()
            self._status_records.setText("  로딩 취소됨")
            worker.deleteLater()
            return

        if worker.error_msg:
            if self._db:
                self._db.close()
                self._db = None
            self._reset_ui()
            QMessageBox.critical(
                self, "로드 실패",
                f"파일을 로드하는 중 오류가 발생했습니다.\n\n"
                f"파일: {filepath}\n오류: {worker.error_msg}"
            )
            self._status_records.setText("  로드 실패")
            worker.deleteLater()
            return

        meta = worker.meta
        self._codec_name = worker.codec_name
        worker.deleteLater()

        if meta is None:
            return

        try:
            self._setup_after_load(filepath, meta)
        except Exception as e:
            QMessageBox.critical(
                self, "초기화 오류",
                f"파일 로드 후 초기화 중 오류:\n{e}"
            )

    def _setup_after_load(self, filepath: str, meta: dict):
        """파일 로드 완료 후 UI 초기화. _on_worker_finished에서 호출."""
        import time as _time
        t0 = _time.perf_counter()
        print(f"[Setup] UI 초기화 시작")

        self._undo_mgr = UndoManager(self._db)
        self._model = RecordTableModel(self._db)
        self._model.set_codec(self._codec_name)
        self._model.edit_requested.connect(self._on_edit_committed)
        self._table_view.setModel(self._model)
        self._table_view.apply_column_widths()
        print(f"[Setup] 모델/테이블 설정 ({_time.perf_counter()-t0:.2f}s)")

        sel_model = self._table_view.selectionModel()
        sel_model.selectionChanged.connect(self._on_table_selection_changed)

        self._group_tree.load_groups(self._db)
        print(f"[Setup] 그룹 트리 로드 ({_time.perf_counter()-t0:.2f}s)")

        self._search_bar.setEnabled(True)
        self._search_bar.set_db(self._db)
        self._save_action.setEnabled(True)
        self._save_as_action.setEnabled(True)
        self._replace_action.setEnabled(True)
        self._translate_action.setEnabled(True)
        self._export_action.setEnabled(True)
        self._export_filtered_action.setEnabled(True)
        self._export_modified_action.setEnabled(True)
        self._export_diff_action.setEnabled(True)
        self._import_action.setEnabled(True)
        self._batch_ref_action.setEnabled(True)
        # 번역/용어집 패널은 None으로 초기 설정 → 탭 전환 시 lazy 로드
        self._translate_panel.set_db(
            self._db, self._undo_mgr, None, self._codec_name,
        )
        self._glossary_panel.set_db(self._db, en_db=None, kr_db=self._db)
        self._glossary_action.setEnabled(True)
        self._secondary_dbs_loaded = False

        # 수정 이력 복원 (사이드카 파일에서)
        try:
            mod_restored = load_mod_keys(self._db, filepath)
            if mod_restored > 0:
                self._statusbar.showMessage(
                    f"이전 수정 이력 {mod_restored:,}건 복원됨", 3000
                )
            print(f"[Setup] 수정 이력 복원 ({_time.perf_counter()-t0:.2f}s)")
        except Exception:
            print(f"[Setup] 수정 이력 복원 실패 ({_time.perf_counter()-t0:.2f}s)")

        stats = self._db.get_stats(codec_name=self._codec_name)
        fname = Path(filepath).name
        self._status_file.setText(f"  {fname}")
        self._status_records.setText(f"레코드: {stats['total']:,}  ")
        codec_display = {
            "identity": "",
            "eso_kr_legacy": "KR Legacy",
            "eso_kr_native": "KR Native",
        }
        codec_text = codec_display.get(self._codec_name, self._codec_name)
        self._status_codec.setText(f"  {codec_text}  " if codec_text else "")
        self._update_edit_stats()
        self._update_codec_menu()
        self._update_title()
        print(f"[Setup] UI 초기화 완료 ({_time.perf_counter()-t0:.2f}s)")



    # ==================================================================
    # 네비게이션 히스토리
    # ==================================================================

    def _capture_nav_state(self) -> _NavState:
        """현재 필터/검색/선택 상태를 스냅샷으로 캡처."""
        selected_rowid = None
        if self._model is not None:
            current = self._table_view.currentIndex()
            if current.isValid():
                selected_rowid = self._model.get_rowid(current.row())

        focus_field = ""
        focus_text = ""
        if self._model is not None:
            if self._model._focus_where and self._model._focus_params:
                if "source" in self._model._focus_where:
                    focus_field = "source"
                elif "target" in self._model._focus_where:
                    focus_field = "target"
                if self._model._focus_params:
                    focus_text = self._model._focus_params[0]

        return _NavState(
            filter_text=self._search_bar.get_current_filter(),
            search_text=self._search_bar.current_query(),
            regex_enabled=self._search_bar.is_regex_enabled(),
            focus_field=focus_field,
            focus_text=focus_text,
            selected_rowid=selected_rowid,
        )

    def _push_nav_state(self):
        """현재 상태를 히스토리에 저장."""
        if self._restoring_nav:
            return
        state = self._capture_nav_state()
        self._nav_history.append(state)
        if len(self._nav_history) > _NAV_HISTORY_LIMIT:
            self._nav_history = self._nav_history[-_NAV_HISTORY_LIMIT:]
        self._nav_back_action.setEnabled(True)

    def _nav_back(self, checked: bool = False):
        """이전 네비게이션 상태로 복원."""
        if not self._nav_history or self._model is None:
            return

        state = self._nav_history.pop()
        self._nav_back_action.setEnabled(bool(self._nav_history))
        self._restoring_nav = True
        try:
            self._restore_nav_state(state)
        finally:
            self._restoring_nav = False

    def _restore_nav_state(self, state: _NavState):
        """네비게이션 상태 복원."""
        if self._model is None:
            return

        # 1. focus 필터 해제
        if state.focus_field and state.focus_text:
            self._model.set_exact_text_filter(state.focus_field, state.focus_text)
        else:
            self._model.set_exact_text_filter(None)

        # 2. 상태 필터 복원 (시그널 차단하여 재진입 방지)
        self._search_bar._filter_combo.blockSignals(True)
        self._search_bar._filter_combo.setCurrentText(state.filter_text)
        self._search_bar._filter_combo.blockSignals(False)
        if state.filter_text == "기존 번역 있음":
            self._apply_reference_filter()
        else:
            self._model.set_status_filter(state.filter_text)
            # set_status_filter가 focus를 지우므로 다시 설정
            if state.focus_field and state.focus_text:
                self._model.set_exact_text_filter(
                    state.focus_field, state.focus_text,
                )

        # 3. 검색어 복원
        self._search_bar._input.blockSignals(True)
        self._search_bar._input.setText(state.search_text)
        self._search_bar._input.blockSignals(False)
        if state.search_text:
            self._search_bar.refresh_search()
        else:
            self._model.set_search_results(None)

        self._update_status_count()

        # 4. 선택 위치 복원
        if state.selected_rowid is not None:
            self._scroll_to_rowid(state.selected_rowid)
        else:
            self._reset_selection_context_after_filter_change()

        self._statusbar.showMessage("이전 보기로 돌아감", 3000)

    @_require_model
    def _scroll_to_rowid(self, rowid: int):
        """특정 rowid가 있는 행으로 스크롤하고 선택."""
        total = self._model.rowCount()
        # 현재 필터 내에서 rowid 위치 찾기
        for row in range(total):
            row_rowid = self._model.get_rowid(row)
            if row_rowid == rowid:
                idx = self._model.index(row, 0)
                self._table_view.setCurrentIndex(idx)
                self._table_view.scrollTo(idx)
                return
        # rowid를 못 찾으면 첫 행으로
        if total > 0:
            first = self._model.index(0, 0)
            self._table_view.setCurrentIndex(first)
            self._table_view.scrollTo(first)

    # ==================================================================
    # 그룹 / 검색 / 필터
    # ==================================================================

    @_require_model
    def _on_group_selected(self, group_id):
        self._model.set_id_filter(group_id)
        self._reset_selection_context_after_filter_change()
        self._update_status_count()

    @_require_model
    def _on_search_results(self, rowids: list[int] | None):
        self._model.set_search_results(rowids)
        self._reset_selection_context_after_filter_change()
        self._update_status_count()

    @_require_model
    def _on_filter_changed(self, filter_text: str):
        if filter_text == "기존 번역 있음":
            self._apply_reference_filter()
        else:
            self._model.set_status_filter(filter_text)
        self._reset_selection_context_after_filter_change()
        self._update_status_count()

    @_require_model
    def _clear_filters(self, checked: bool = False):
        self._search_bar.clear_search()
        self._model.clear_filters()
        self._group_tree.setCurrentIndex(
            self._group_tree.model().index(0, 0)
        )
        self._reset_selection_context_after_filter_change()
        self._update_status_count()

    @_require_model
    def _reset_selection_context_after_filter_change(self):
        sel_model = self._table_view.selectionModel()
        if sel_model is not None:
            sel_model.clearSelection()
        self._table_view.setCurrentIndex(QModelIndex())
        self._editor_panel.clear_record()

    @_require_db_model
    def _update_status_count(self):
        count = self._model.rowCount()
        total = self._db.record_count()
        if count == total:
            self._status_records.setText(f"레코드: {total:,}  ")
        else:
            self._status_records.setText(f"레코드: {count:,} / {total:,}  ")
        self._update_scope_progress()

    @staticmethod
    def _shorten_text(text: str, *, limit: int = 42) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[:limit - 3] + "..."

    @_require_db_model
    def _open_table_context_menu(self, pos: QPoint):
        index = self._table_view.indexAt(pos)
        if not index.isValid():
            return

        rowid = self._model.get_rowid(index.row())
        if rowid is None:
            return
        record = self._db.get_record_by_rowid(rowid)
        if record is None:
            return

        source_text = record[3] or ""
        target_text = record[4] or ""

        menu = QMenu(self)

        if source_text:
            src_label = self._shorten_text(source_text)
            menu.addAction(
                f"같은 Source 번역 현황 보기: {src_label}",
                partial(self._open_source_translation_lookup, source_text),
            )
            menu.addSeparator()
            menu.addAction(
                f"같은 Source만 보기: {src_label}",
                partial(self._show_exact_text_matches, "source", source_text),
            )
            menu.addAction(
                f"같은 Source 행 모두 선택: {src_label}",
                partial(self._select_exact_text_matches, "source", source_text),
            )

        if target_text:
            if source_text:
                menu.addSeparator()
            tgt_label = self._shorten_text(target_text)
            menu.addAction(
                f"같은 Target만 보기: {tgt_label}",
                partial(self._show_exact_text_matches, "target", target_text),
            )
            menu.addAction(
                f"같은 Target 행 모두 선택: {tgt_label}",
                partial(self._select_exact_text_matches, "target", target_text),
            )

        if menu.isEmpty():
            return

        menu.addSeparator()
        menu.addAction("문자열 필터 해제", self._clear_exact_text_filter)

        # ── 번역 대상 지정/해제 ──
        menu.addSeparator()
        selected_rowids = self._get_selected_rowids()
        if not selected_rowids:
            selected_rowids = [rowid]

        # 선택된 행 중 큐에 포함된 수로 라벨 결정
        in_queue = sum(
            1 for r in selected_rowids if self._translate_panel.is_in_queue(r)
        )
        count = len(selected_rowids)

        if in_queue < count:
            menu.addAction(
                f"번역 대상 지정 ({count:,}건)",
                partial(self._add_to_translate_queue, selected_rowids),
            )
        if in_queue > 0:
            menu.addAction(
                f"번역 대상 해제 ({in_queue:,}건)",
                partial(self._remove_from_translate_queue, selected_rowids),
            )

        # ── 내보내기 ──
        menu.addSeparator()
        menu.addAction(
            f"선택 행 내보내기 ({count:,}건)...",
            partial(self._export_rowids, selected_rowids),
        )

        menu.exec(self._table_view.viewport().mapToGlobal(pos))

    def _add_to_translate_queue(self, rowids: list[int]):
        """선택된 행을 번역 대상 큐에 추가."""
        self._translate_panel.add_to_queue(rowids)
        self._statusbar.showMessage(
            f"번역 대상 {len(rowids):,}건 추가 (총 {self._translate_panel.queue_count():,}건)",
            3000,
        )

    def _remove_from_translate_queue(self, rowids: list[int]):
        """선택된 행을 번역 대상 큐에서 제거."""
        self._translate_panel.remove_from_queue(rowids)
        self._statusbar.showMessage(
            f"번역 대상에서 제거 (남은 대상: {self._translate_panel.queue_count():,}건)",
            3000,
        )

    @_require_db_model
    def _show_exact_text_matches(self, field_name: str, text: str):
        self._push_nav_state()
        self._search_bar.clear_search()
        self._model.set_exact_text_filter(field_name, text)
        self._update_status_count()
        count = self._model.rowCount()
        if count <= 0:
            QMessageBox.information(self, "같은 문자열 보기", "일치하는 행이 없습니다.")
            return

        first_idx = self._model.index(0, 0)
        self._table_view.clearSelection()
        self._table_view.setCurrentIndex(first_idx)
        self._table_view.scrollTo(first_idx)

        label = "Source" if field_name == "source" else "Target"
        self._statusbar.showMessage(
            f"같은 {label}만 표시 중 — {count:,}건 (Ctrl+Shift+F로 해제)",
            5000,
        )

    @_require_model
    def _select_exact_text_matches(self, field_name: str, text: str):
        self._show_exact_text_matches(field_name, text)
        if self._model.rowCount() <= 0:
            return

        self._table_view.selectAll()
        self._refresh_editor_from_selection()
        self._editor_panel.focus_target()

        label = "Source" if field_name == "source" else "Target"
        self._statusbar.showMessage(
            f"같은 {label} 행 {self._model.rowCount():,}건 선택됨",
            5000,
        )

    @_require_model
    def _clear_exact_text_filter(self):
        self._model.set_exact_text_filter(None)
        self._update_status_count()
        self._statusbar.showMessage("문자열 필터 해제됨", 3000)

    # ==================================================================
    # 편집 / Undo / Redo
    # ==================================================================

    @_require_model
    def _get_selected_rowids(self) -> list[int]:
        sel_model = self._table_view.selectionModel()
        if sel_model is None:
            return []
        indexes = sorted(sel_model.selectedRows(), key=lambda idx: idx.row())
        rowids: list[int] = []
        for index in indexes:
            rowid = self._model.get_rowid(index.row())
            if rowid is not None:
                rowids.append(rowid)
        return rowids

    @_require_db_model
    def _refresh_editor_from_selection(self):
        rowids = self._get_selected_rowids()
        if not rowids:
            self._editor_panel.clear_record()
            return

        if len(rowids) == 1:
            rowid = rowids[0]
            record = self._db.get_record_by_rowid(rowid)
            if record is None:
                self._editor_panel.clear_record()
                return
            self._editor_panel.set_record(rowid, record[3], record[4])
            return

        # 너무 많은 선택은 에디터에 표시하지 않음 (성능 보호)
        MAX_EDITOR_ROWS = 500
        display_rowids = rowids[:MAX_EDITOR_ROWS]
        records = self._db.get_source_targets_by_rowids(display_rowids)
        if not records:
            self._editor_panel.clear_record()
            return
        self._editor_panel.set_multi_records(records)

    def _on_table_selection_changed(
        self,
        selected: QItemSelection,
        deselected: QItemSelection,
    ):
        self._refresh_editor_from_selection()

    @_require_model
    @_require_undo
    def _on_edit_committed(self, rowid: int, new_target: str):
        changed = self._undo_mgr.edit_single(rowid, new_target)
        if changed:
            self._dirty = True
            self._model.notify_row_changed(rowid)
            self._update_undo_actions()
            self._update_edit_stats()
            self._search_bar.refresh_search()
            if len(self._get_selected_rowids()) <= 1:
                self._editor_panel.update_target_text(new_target)
            else:
                self._refresh_editor_from_selection()
            self._update_title()

    @_require_db_model
    @_require_undo
    def _on_batch_edit_committed(self, rowids: list[int], new_target: str):
        if not rowids:
            return

        records = self._db.get_source_targets_by_rowids(rowids)
        updates = [
            (rowid, new_target)
            for rowid, _, current_target in records
            if current_target != new_target
        ]
        if not updates:
            return

        description = f"선택 행 일괄 편집 ({len(updates)}건)"
        changed = self._undo_mgr.edit_batch(updates, description=description)
        if changed <= 0:
            return

        self._dirty = True
        self._model.invalidate_cache()
        self._model.notify_row_changed(0)
        self._update_undo_actions()
        self._update_edit_stats()
        self._search_bar.refresh_search()
        self._refresh_editor_from_selection()
        self._update_title()
        self._statusbar.showMessage(
            f"선택한 {changed:,}건에 같은 번역을 적용했습니다.",
            5000,
        )

    @_require_model
    @_require_undo
    def _do_undo(self, checked: bool = False):
        entry = self._undo_mgr.undo()
        if entry:
            self._model.invalidate_cache()
            self._model.notify_row_changed(0)
            self._update_undo_actions()
            self._update_edit_stats()
            self._search_bar.refresh_search()
            self._sync_editor_after_undo_redo()

    @_require_model
    @_require_undo
    def _do_redo(self, checked: bool = False):
        entry = self._undo_mgr.redo()
        if entry:
            self._model.invalidate_cache()
            self._model.notify_row_changed(0)
            self._update_undo_actions()
            self._update_edit_stats()
            self._search_bar.refresh_search()
            self._sync_editor_after_undo_redo()

    def _sync_editor_after_undo_redo(self):
        self._refresh_editor_from_selection()

    def _update_undo_actions(self):
        if self._undo_mgr is None:
            self._undo_action.setEnabled(False)
            self._redo_action.setEnabled(False)
            return
        self._undo_action.setEnabled(self._undo_mgr.can_undo)
        self._redo_action.setEnabled(self._undo_mgr.can_redo)
        undo_text = self._undo_mgr.undo_text
        redo_text = self._undo_mgr.redo_text
        self._undo_action.setText(
            f"실행 취소: {undo_text}(&Z)" if undo_text else "실행 취소(&Z)"
        )
        self._redo_action.setText(
            f"다시 실행: {redo_text}(&Y)" if redo_text else "다시 실행(&Y)"
        )

    @_require_db
    def _update_edit_stats(self):
        stats = self._db.get_stats(codec_name=self._codec_name)
        self._status_progress.setText(
            f"행 기준: {stats['translated']:,} / {stats['total']:,} "
            f"({stats['progress']:.1f}%)  "
        )
        self._status_source_progress.setText(
            f"원문 기준: {stats['unique_source_translated']:,} / "
            f"{stats['unique_source_total']:,} "
            f"({stats['unique_source_progress']:.1f}%)  "
        )
        if stats['modified'] > 0 or stats['modified_chars'] > 0:
            self._status_modified.setText(
                f"수정: {stats['modified']:,}건 / {stats['modified_chars']:,}자  "
            )
        else:
            self._status_modified.setText("")
        if self._model is not None:
            self._update_scope_progress()

    @_require_db_model
    def _update_scope_progress(self):
        id_filter, where_clause, params = self._model.get_filter_context()
        if id_filter is None and where_clause == "":
            self._status_scope_progress.setText("")
            return

        stats = self._db.get_stats_by_filter(
            codec_name=self._codec_name,
            id_filter=id_filter,
            where_clause=where_clause,
            params=params,
        )
        if stats["total"] <= 0:
            self._status_scope_progress.setText("현재 범위: 0건  ")
            return

        self._status_scope_progress.setText(
            f"현재 범위: 원문 {stats['unique_source_translated']:,} / "
            f"{stats['unique_source_total']:,} ({stats['unique_source_progress']:.1f}%), "
            f"행 {stats['translated']:,} / {stats['total']:,} "
            f"({stats['progress']:.1f}%)  "
        )

    # ==================================================================
    # F3 — 다음 미번역
    # ==================================================================

    def _is_untranslated(self, record: tuple) -> bool:
        """레코드가 미번역인지 판단.

        - identity (en.lang): target 비어있으면 미번역
        - eso_kr_legacy/eso_kr_native (kr.lang): target 비어있고 source에 한글 없으면 미번역
        """
        from core.text_codec import is_kr_codec
        if record[5]:  # target 채워져 있음
            return False
        if is_kr_codec(self._codec_name):
            source = record[4]
            if not source:
                return False
            for ch in source:
                cp = ord(ch)
                if (0xAC00 <= cp <= 0xD7A3 or
                    0x1100 <= cp <= 0x11FF or
                    0x3131 <= cp <= 0x318F):
                    return False
            return True
        return True

    @_require_model
    def _jump_next_untranslated(self, checked: bool = False):
        current_row = self._table_view.currentIndex().row()
        start = current_row + 1 if current_row >= 0 else 0
        total = self._model.rowCount()

        for row in range(start, total):
            record = self._model.get_record(row)
            if record and self._is_untranslated(record):
                idx = self._model.index(row, 0)
                self._table_view.setCurrentIndex(idx)
                self._table_view.scrollTo(idx)
                self._editor_panel.focus_target()
                return

        for row in range(0, start):
            record = self._model.get_record(row)
            if record and self._is_untranslated(record):
                idx = self._model.index(row, 0)
                self._table_view.setCurrentIndex(idx)
                self._table_view.scrollTo(idx)
                self._editor_panel.focus_target()
                return

    # ==================================================================
    # 저장
    # ==================================================================

    @_require_db
    def _save_file(self, checked: bool = False):
        if not self._save_filepath:
            self._save_file_as()
            return
        self._do_save(self._save_filepath)

    @_require_db
    def _save_file_as(self, checked: bool = False):
        default_name = ""
        if self._load_filepath:
            p = Path(self._load_filepath)
            default_name = str(p.parent / f"{p.stem}_out{p.suffix}")

        filepath, _ = QFileDialog.getSaveFileName(
            self, "다른 이름으로 저장", default_name,
            "Lang Files (*.lang);;All Files (*)"
        )
        if not filepath:
            return
        self._save_filepath = filepath
        self._do_save(filepath)

    @_require_db
    def _do_save(self, filepath: str):
        self._editor_panel._commit_if_changed()

        from core.text_codec import is_kr_codec
        if self._codec_name == "eso_kr_legacy":
            reply = QMessageBox.information(
                self, "KR Legacy 코덱 저장",
                "KR Legacy 코덱이 적용됩니다.\n"
                "한글 텍스트가 CJK 코드포인트로 인코딩되어 저장됩니다.\n\n"
                "또한 문자열 중복 제거(dedup)가 적용되어 원본과 파일 크기가 "
                "다를 수 있으나 기능적으로 동일합니다.",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
        elif self._codec_name == "eso_kr_native":
            reply = QMessageBox.information(
                self, "KR Native 코덱 저장",
                "KR Native 코덱이 적용됩니다.\n"
                "한글 텍스트가 유니코드 그대로 저장됩니다.\n"
                "한글 폰트 애드온이 필요합니다.\n\n"
                "문자열 중복 제거(dedup)가 적용되어 원본과 파일 크기가 "
                "다를 수 있으나 기능적으로 동일합니다.",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return

        self._progress = QProgressDialog("저장 준비 중...", None, 0, 100, self)
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setCancelButton(None)
        self._progress.setValue(0)
        self._progress.show()

        self._save_worker = SaveWorker(
            self._db, filepath, codec_name=self._codec_name
        )
        self._save_worker.progress.connect(self._on_save_progress)
        self._save_worker.finished.connect(self._on_save_finished)
        self._save_worker.start()

    def _on_save_progress(self, stage: str, current: int, total: int):
        if self._progress is None:
            return
        if total > 0:
            pct = min(int(current / total * 100), 100)
            self._progress.setValue(pct)
            self._progress.setLabelText(f"{stage}... {current:,} / {total:,}")
        else:
            self._progress.setLabelText(stage)

    def _on_save_finished(self):
        worker = self._save_worker
        self._save_worker = None

        if self._progress:
            self._progress.close()
            self._progress = None

        if worker is None:
            return

        if worker.error_msg:
            QMessageBox.critical(
                self, "저장 실패",
                f"파일 저장 중 오류가 발생했습니다.\n\n{worker.error_msg}"
            )
            worker.deleteLater()
            return

        meta = worker.build_meta
        worker.deleteLater()

        self._dirty = False
        self._update_title()

        # 수정 이력 사이드카 파일 저장
        save_path = self._save_filepath or self._load_filepath
        if save_path:
            mod_count = save_mod_keys(self._db, save_path)
            if mod_count > 0:
                self._statusbar.showMessage(
                    f"수정 이력 {mod_count:,}건 저장됨", 2000
                )

        if meta:
            size_mb = meta['file_size'] / (1024 * 1024)
            self._statusbar.showMessage(
                f"저장 완료 — {meta['record_count']:,}건, "
                f"{meta['unique_strings']:,} 고유 문자열, "
                f"{size_mb:.1f}MB",
                5000,
            )

    # ==================================================================
    # 코덱 override
    # ==================================================================

    def _reload_with_codec(self, codec_name: str | None):
        if not self._load_filepath or self._worker is not None:
            return

        from core.text_codec import is_kr_codec

        # 자동 감지로 전환
        if codec_name is None:
            self._load_file(self._load_filepath, force_codec=None)
            return

        # KR 코덱 간 전환 (legacy ↔ native): 메모리 텍스트가 이미 한글이므로
        # 파일 리로드 없이 코덱만 전환. 저장 시 인코딩 방식만 달라진다.
        if (is_kr_codec(self._codec_name) and is_kr_codec(codec_name)
                and codec_name != self._codec_name):
            self._codec_name = codec_name
            self._force_codec = codec_name
            if self._model is not None:
                self._model.set_codec(codec_name)
            codec_display = {
                "eso_kr_legacy": "KR Legacy",
                "eso_kr_native": "KR Native",
            }
            self._status_codec.setText(
                f"  {codec_display.get(codec_name, codec_name)}  "
            )
            self._update_codec_menu()
            self._statusbar.showMessage(
                f"저장 코덱 변경: {codec_display.get(codec_name, codec_name)} "
                f"(리로드 없이 적용됨)",
                5000,
            )
            return

        self._load_file(self._load_filepath, force_codec=codec_name)

    def _update_codec_menu(self):
        is_auto = self._force_codec is None
        self._codec_auto_action.setChecked(is_auto)
        self._codec_identity_action.setChecked(
            not is_auto and self._codec_name == "identity"
        )
        self._codec_kr_action.setChecked(
            not is_auto and self._codec_name == "eso_kr_legacy"
        )
        self._codec_kr_native_action.setChecked(
            not is_auto and self._codec_name == "eso_kr_native"
        )

    # ==================================================================
    # Dirty-state 가드 + 타이틀
    # ==================================================================

    def _update_title(self):
        """윈도우 타이틀에 파일명 + dirty 표시."""
        title = "ESO Lang Tool"
        if self._load_filepath:
            fname = Path(self._load_filepath).name
            title = f"{fname} — {title}"
        if self._dirty:
            title = f"● {title}"
        self.setWindowTitle(title)

    def _confirm_discard(self) -> bool:
        """미저장 변경이 있으면 저장 확인. 계속 진행하면 True."""
        if not self._dirty:
            return True
        reply = QMessageBox.warning(
            self, "저장되지 않은 변경",
            "수정 사항이 저장되지 않았습니다.\n계속하면 변경 사항이 사라집니다.",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if reply == QMessageBox.StandardButton.Save:
            self._save_file()
            return not self._dirty  # 저장 성공 시 dirty=False
        if reply == QMessageBox.StandardButton.Discard:
            return True
        return False  # Cancel

    # ==================================================================
    # 번역 탭 연동
    # ==================================================================

    def _start_translation_tab(self, checked: bool = False):
        """메뉴에서 번역 시작 → 번역 탭으로 전환."""
        self._bottom_tabs.setCurrentWidget(self._translate_panel)

    def _open_glossary_tab(self, checked: bool = False):
        """메뉴에서 용어집 탭으로 전환."""
        self._bottom_tabs.setCurrentWidget(self._glossary_panel)

    @_require_db_model
    def _on_translation_completed(self, changed_count: int):
        """번역 완료 시 UI 갱신."""
        self._model.invalidate_cache()
        self._update_edit_stats()
        self._dirty = True
        self._update_title()
        self._update_undo_actions()
        self._statusbar.showMessage(
            f"LLM 번역 완료: {changed_count:,}건 적용", 5000,
        )

    # ==================================================================
    # 종료
    # ==================================================================

    def closeEvent(self, event):
        if not self._confirm_discard():
            event.ignore()
            return
        if self._worker:
            self._worker.cancel()
            self._worker.wait(3000)
        if self._save_worker:
            self._save_worker.wait(5000)
        if self._db:
            self._db.close()
        self._close_base_db()
        self._close_reference_db()
        super().closeEvent(event)
