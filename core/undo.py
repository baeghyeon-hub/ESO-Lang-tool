"""
Undo/Redo 관리자 — diff-patch 방식.

각 편집 동작을 (rowid, old_target, new_target) diff로 기록.
단일 편집과 일괄 편집(Find/Replace) 모두 하나의 UndoEntry로 묶임.

제한:
  - max_steps: 최대 200단계
  - max_memory_bytes: 최대 ~100MB (대략적 문자열 크기 추정)
"""

from __future__ import annotations

from dataclasses import dataclass

from core.db import LangDatabase


@dataclass
class UndoEntry:
    """하나의 undo 단위. 여러 행 편집도 하나의 entry로 묶임."""
    description: str
    diffs: list[tuple[int, str, str]]  # [(rowid, old_target, new_target), ...]

    @property
    def estimated_bytes(self) -> int:
        return sum(len(old) + len(new) for _, old, new in self.diffs) * 4


class UndoManager:
    """Undo/Redo 스택 관리."""

    def __init__(
        self,
        db: LangDatabase,
        *,
        max_steps: int = 200,
        max_memory_bytes: int = 100 * 1024 * 1024,
    ):
        self._db = db
        self._max_steps = max_steps
        self._max_memory = max_memory_bytes
        self._undo_stack: list[UndoEntry] = []
        self._redo_stack: list[UndoEntry] = []
        self._total_bytes = 0

    def _trim_undo_history(self) -> None:
        """undo 스택이 제한을 넘으면 가장 오래된 항목부터 제거."""
        while (
            len(self._undo_stack) > self._max_steps
            or self._total_bytes > self._max_memory
        ) and len(self._undo_stack) > 1:
            removed = self._undo_stack.pop(0)
            self._total_bytes -= removed.estimated_bytes

    def _append_undo_entry(self, entry: UndoEntry, *, clear_redo: bool) -> None:
        """undo 스택에 entry를 추가하고 필요 시 redo 스택을 비움."""
        if not entry.diffs:
            return
        if clear_redo:
            self._redo_stack.clear()
        self._undo_stack.append(entry)
        self._total_bytes += entry.estimated_bytes
        self._trim_undo_history()

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    @property
    def undo_text(self) -> str:
        if self._undo_stack:
            return self._undo_stack[-1].description
        return ""

    @property
    def redo_text(self) -> str:
        if self._redo_stack:
            return self._redo_stack[-1].description
        return ""

    def push(self, entry: UndoEntry) -> None:
        """편집 결과를 undo 스택에 추가."""
        self._append_undo_entry(entry, clear_redo=True)

    def edit_single(self, rowid: int, new_target: str, description: str = "") -> bool:
        """단일 행 편집 + undo 기록. 변경 있으면 True."""
        old = self._db.update_target(rowid, new_target)
        if old is None:
            return False

        desc = description or f"편집 (rowid={rowid})"
        self.push(UndoEntry(
            description=desc,
            diffs=[(rowid, old, new_target)],
        ))
        return True

    def edit_batch(
        self,
        updates: list[tuple[int, str]],
        description: str = "",
    ) -> int:
        """일괄 편집 + undo 기록. 변경된 행 수 반환."""
        diffs = self._db.batch_update_targets(updates)
        if not diffs:
            return 0

        desc = description or f"일괄 편집 ({len(diffs)}건)"
        self.push(UndoEntry(description=desc, diffs=diffs))
        return len(diffs)

    def undo(self) -> UndoEntry | None:
        """마지막 편집을 취소. 취소된 entry 반환."""
        if not self._undo_stack:
            return None

        entry = self._undo_stack.pop()
        self._total_bytes -= entry.estimated_bytes

        # DB에 old 값 복원
        restore = [(rowid, old) for rowid, old, _ in entry.diffs]
        self._db.batch_update_targets(restore)

        # redo 스택에 추가 (같은 diffs 유지 — old/new 방향 보존)
        self._redo_stack.append(entry)

        return entry

    def redo(self) -> UndoEntry | None:
        """마지막 undo를 다시 적용. 적용된 entry 반환."""
        if not self._redo_stack:
            return None

        entry = self._redo_stack.pop()

        # DB에 new 값 적용 (diffs의 old→new 방향 그대로)
        apply = [(rowid, new) for rowid, _, new in entry.diffs]
        self._db.batch_update_targets(apply)

        # undo 스택에 복원하되, 남아 있는 redo 이력은 유지한다.
        self._append_undo_entry(entry, clear_redo=False)
        return entry

    def clear(self) -> None:
        """모든 히스토리 초기화."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._total_bytes = 0
