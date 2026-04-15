from __future__ import annotations

import json
import logging
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable

from state_utils import count_bw, normalize_board

log = logging.getLogger(__name__)


@dataclass
class Snapshot:
    """
    “再開候補として選べる盤面” の履歴要素。
    - view: GUI復元用（反転・合法手・evals・move_no 等を含む）
    - board_norm: 一致判定のターゲット用（反転前の正規化8x8）
    - move_no / turn / black_eval: 一覧表示やグラフ復元に使う想定
    """

    view: dict[str, Any]
    board_norm: list[list[str]]
    move_no: int
    turn: str
    black_eval: float | None
    ts: float


class Mode(Enum):
    RUNNING = auto()
    PAUSED = auto()
    PAUSED_CALIB = auto()
    LOCKED_SYNC = auto()
    RESUMABLE = auto()


@dataclass
class ResumeState:
    snapshots: list[Snapshot] = field(default_factory=list)
    last_snapshot_key: tuple[Any, ...] | None = None
    snap_debug_count: int = 0
    snap_choice_map: list[int] = field(default_factory=list)
    resume_target_board: list[list[str]] | None = None
    resume_target_label: str = ""
    sync_ok_streak: int = 0


class ResumeManager:
    def __init__(
        self,
        app,
        send: Callable[[str], None],
        *,
        snapshot_max: int = 120,
        sync_streak_n: int = 8,
        snap_debug_every: int = 5,
        snap_debug_tail: int = 6,
    ) -> None:
        self.app = app
        self.send = send
        self.snapshot_max = snapshot_max
        self.sync_streak_n = sync_streak_n
        self.snap_debug_every = snap_debug_every
        self.snap_debug_tail = snap_debug_tail
        self.state = ResumeState()
        self._mode_lock = threading.Lock()
        self._mode = Mode.RUNNING

    def get_mode(self) -> Mode:
        with self._mode_lock:
            return self._mode

    def set_mode(self, mode: Mode, reason: str = "") -> None:
        with self._mode_lock:
            prev = self._mode
            self._mode = mode
        self._after("set_status", f"{mode.name}" + (f" ({reason})" if reason else ""))
        self._after("append_log", f"[mode] {prev.name} -> {mode.name}" + (f" ({reason})" if reason else ""))
        self._after("set_resume_enabled", mode == Mode.RUNNING)

    def push_snapshot(
        self,
        *,
        view: dict[str, Any],
        board_norm: list[list[str]],
        move_no: int,
        turn: str,
        black_eval: float | None,
    ) -> None:
        if not isinstance(view, dict) or not board_norm:
            return
        key = (int(move_no), str(turn), self._board_key(board_norm))
        if self.state.last_snapshot_key == key:
            return
        self.state.last_snapshot_key = key

        self.state.snapshots.append(
            Snapshot(
                view=view,
                board_norm=[row[:] for row in board_norm],
                move_no=int(move_no),
                turn=str(turn),
                black_eval=None if black_eval is None else float(black_eval),
                ts=time.time(),
            )
        )
        if len(self.state.snapshots) > self.snapshot_max:
            del self.state.snapshots[: len(self.state.snapshots) - self.snapshot_max]

        self.state.snap_debug_count += 1
        if self.snap_debug_every > 0 and (self.state.snap_debug_count % self.snap_debug_every == 0):
            try:
                bcnt, wcnt = count_bw(board_norm)
            except Exception:
                bcnt, wcnt = -1, -1
            be = "-" if black_eval is None else f"{float(black_eval):+.2f}"
            print(
                f"[SNAP] n={len(self.state.snapshots):3d} move_no={int(move_no):2d} turn={turn} "
                f"bw=({bcnt},{wcnt}) black_eval={be}",
                file=sys.stderr,
                flush=True,
            )
            try:
                tail = self.state.snapshots[-self.snap_debug_tail :]
                summary = " | ".join(
                    f"{sn.move_no:02d}{sn.turn}({('-' if sn.black_eval is None else f'{sn.black_eval:+.1f}')})"
                    for sn in tail
                )
                print(f"[SNAP] tail: {summary}", file=sys.stderr, flush=True)
            except Exception:
                pass

    def publish_snapshot_choices_to_gui(self) -> None:
        if not hasattr(self.app, "set_snapshot_choices"):
            return
        if not self.state.snapshots:
            self.app.after(0, self.app.set_snapshot_choices, ["(履歴がまだありません)"], None)
            return

        indices = list(range(len(self.state.snapshots) - 1, -1, -1))
        labels = [self._format_snapshot_label(self.state.snapshots[idx]) for idx in indices]
        self.state.snap_choice_map = indices

        self.app.after(0, self.app.set_snapshot_choices, labels, 0)
        self._after("set_sync_status", "（未選択）")
        self._after("set_resume_enabled", False)
        self._after("set_pick_enabled", True)

    def on_pick_snapshot(self, display_index: int) -> None:
        try:
            if not self.state.snapshots:
                self._after("append_log", "[pick] snapshots empty")
                return

            if display_index < 0 or display_index >= len(self.state.snap_choice_map):
                self._after("append_log", f"[pick] invalid display_index={display_index}")
                return

            real_i = self.state.snap_choice_map[display_index]
            if real_i < 0 or real_i >= len(self.state.snapshots):
                self._after("append_log", f"[pick] invalid real index={real_i}")
                return

            snapshot = self.state.snapshots[real_i]
            self.state.resume_target_board = [row[:] for row in snapshot.board_norm]
            self.state.resume_target_label = self._format_snapshot_label(snapshot)
            self.state.sync_ok_streak = 0

            try:
                self.app.after(0, self.app.update_board, snapshot.view)
            except Exception:
                pass

            self.set_mode(Mode.LOCKED_SYNC, "target_selected")
            self._after("set_sync_status", f"一致待ち 0/{self.sync_streak_n}")
            self._after("set_resume_enabled", False)

            self.send("SYNC:ON")
            self.send(f"SYNC:TURN={snapshot.turn}")
            self._after("append_log", f"[sync] target set {self.state.resume_target_label}")
        except Exception as exc:
            self._after("append_log", f"[pick][fatal] {exc}")

    def on_calib(self, on: bool) -> None:
        cur_mode = self.get_mode()
        if on:
            if cur_mode != Mode.PAUSED:
                self._after("append_log", f"[calib] ignored: mode={cur_mode.name} (need PAUSED)")
                return
            self.set_mode(Mode.PAUSED_CALIB, "calib_on")
            self._after("append_log", "[calib] send CALIB:ON")
            self.send("CALIB:ON")
            self._after("set_resume_enabled", False)
            self._after("set_sync_status", "キャリブ中（再開ターゲット選択は一旦不可）")
            return

        if cur_mode != Mode.PAUSED_CALIB:
            self._after("append_log", f"[calib] ignored: mode={cur_mode.name} (not in calib)")
            return
        self.set_mode(Mode.PAUSED, "calib_off")
        self._after("append_log", "[calib] send CALIB:OFF")
        self.send("CALIB:OFF")
        self.publish_snapshot_choices_to_gui()

    def on_hand(self, on: bool) -> None:
        if not on:
            self.set_mode(Mode.PAUSED, "user_pause")
            self.publish_snapshot_choices_to_gui()
            return

        cur_mode = self.get_mode()
        if cur_mode == Mode.PAUSED:
            self._after("append_log", "[mode] resume blocked: select target & wait for sync match")
            self._after("set_resume_enabled", False)
            return

        if cur_mode == Mode.RESUMABLE:
            self.send("SYNC:OFF")
            self.set_mode(Mode.RUNNING, "resume_after_sync")
            self._after("set_sync_status", "（運転中）")
            return

        if cur_mode == Mode.LOCKED_SYNC:
            self._after("append_log", "[mode] resume blocked: LOCKED_SYNC (need sync match)")

    def handle_sync_state(self, msg: str) -> None:
        try:
            if not msg.startswith("SYNC_STATE:"):
                return
            payload = msg[len("SYNC_STATE:") :].strip()
            data = json.loads(payload)
            board = normalize_board(data.get("board"))
            if board is None or self.state.resume_target_board is None:
                return

            if self._board_equal(board, self.state.resume_target_board):
                self.state.sync_ok_streak += 1
            else:
                self.state.sync_ok_streak = 0

            cur = self.state.sync_ok_streak
            self._after("set_sync_status", f"一致待ち {cur}/{self.sync_streak_n}")

            if cur >= self.sync_streak_n:
                self.set_mode(Mode.RESUMABLE, "sync_matched")
                self.send("SYNC:OFF")
                self._after("set_sync_status", "一致しました（再開できます）")
                self._after("set_resume_enabled", True)
                self._after("append_log", f"[sync] matched: {self.state.resume_target_label}")
        except Exception as exc:
            self._after("append_log", f"[sync][error] {exc}")

    def _after(self, method_name: str, *args) -> None:
        if hasattr(self.app, method_name):
            self.app.after(0, getattr(self.app, method_name), *args)

    def _format_snapshot_label(self, snapshot: Snapshot) -> str:
        try:
            bcnt, wcnt = count_bw(snapshot.board_norm)
        except Exception:
            bcnt, wcnt = -1, -1
        ev = "-" if snapshot.black_eval is None else f"{snapshot.black_eval:+.1f}"
        return f"[{snapshot.move_no:02d}] {snapshot.turn}  bw={bcnt:02d}/{wcnt:02d}  eval={ev}"

    @staticmethod
    def _board_equal(a: list[list[str]] | None, b: list[list[str]] | None) -> bool:
        if a is None or b is None:
            return False
        if len(a) != 8 or len(b) != 8:
            return False
        return all(a[y][x] == b[y][x] for y in range(8) for x in range(8))

    @staticmethod
    def _board_key(board_2d: list[list[str]]) -> tuple[tuple[str, ...], ...]:
        return tuple(tuple(row) for row in board_2d)
