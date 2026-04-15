from __future__ import annotations

import json
import re
import sys
import threading
from dataclasses import dataclass, field
from typing import Optional

from othello_rules import ascii_with_moves, coord, count_bw, winner_from_counts


@dataclass
class RealtimeControlState:
    hand_mp: bool = False
    user_started: bool = False
    preview_turn: str = "B"
    user_started_turn: str = "B"
    sync_turn: Optional[str] = None
    sync_mode: bool = False
    sync_reset_pending: bool = False
    calib_mode: bool = False
    calib_reset_pending: bool = False
    calib_need_corner_reset: bool = False
    hand_lock: threading.Lock = field(default_factory=threading.Lock)
    start_lock: threading.Lock = field(default_factory=threading.Lock)
    sync_lock: threading.Lock = field(default_factory=threading.Lock)
    sync_reset_lock: threading.Lock = field(default_factory=threading.Lock)
    calib_lock: threading.Lock = field(default_factory=threading.Lock)
    calib_reset_lock: threading.Lock = field(default_factory=threading.Lock)
    calib_corner_lock: threading.Lock = field(default_factory=threading.Lock)

    def get_hand_mp(self) -> bool:
        with self.hand_lock:
            return bool(self.hand_mp)

    def set_hand_mp(self, on: bool):
        with self.hand_lock:
            self.hand_mp = bool(on)

    def get_user_started(self) -> bool:
        with self.start_lock:
            return bool(self.user_started)

    def set_started(self, on: bool, turn: str | None = None):
        with self.start_lock:
            self.user_started = bool(on)
            if turn in ("B", "W"):
                self.user_started_turn = turn
                self.preview_turn = turn

    def get_preview_turn(self) -> str:
        with self.start_lock:
            return self.preview_turn

    def set_preview_turn(self, turn: str):
        if turn not in ("B", "W"):
            return
        with self.start_lock:
            self.preview_turn = turn

    def get_user_started_turn(self) -> str:
        with self.start_lock:
            return self.user_started_turn

    def get_sync_turn(self) -> Optional[str]:
        with self.sync_lock:
            return self.sync_turn

    def set_sync_turn(self, turn: Optional[str]):
        if turn not in ("B", "W"):
            return
        with self.sync_lock:
            self.sync_turn = turn

    def set_sync(self, on: bool):
        with self.sync_lock:
            self.sync_mode = bool(on)

    def get_sync(self) -> bool:
        with self.sync_lock:
            return bool(self.sync_mode)

    def set_sync_reset_pending(self, on: bool):
        with self.sync_reset_lock:
            self.sync_reset_pending = bool(on)

    def get_sync_reset_pending(self) -> bool:
        with self.sync_reset_lock:
            return bool(self.sync_reset_pending)

    def set_calib(self, on: bool):
        with self.calib_lock:
            self.calib_mode = bool(on)

    def get_calib(self) -> bool:
        with self.calib_lock:
            return bool(self.calib_mode)

    def set_calib_reset_pending(self, on: bool):
        with self.calib_reset_lock:
            self.calib_reset_pending = bool(on)

    def get_calib_reset_pending(self) -> bool:
        with self.calib_reset_lock:
            return bool(self.calib_reset_pending)

    def set_calib_need_corner_reset(self, on: bool):
        with self.calib_corner_lock:
            self.calib_need_corner_reset = bool(on)

    def get_calib_need_corner_reset(self) -> bool:
        with self.calib_corner_lock:
            return bool(self.calib_need_corner_reset)


def _norm_turn(value: str) -> Optional[str]:
    if not isinstance(value, str):
        return None
    turn = value.strip().upper()
    if turn in ("B", "W"):
        return turn
    return None


def apply_command(msg: str, state: RealtimeControlState):
    if msg == "HAND:ON":
        state.set_hand_mp(True)
    elif msg == "HAND:OFF":
        state.set_hand_mp(False)
    elif msg == "SYNC:ON":
        state.set_sync(True)
        print("[sync] ON", file=sys.stderr, flush=True)
    elif msg == "SYNC:OFF":
        state.set_sync(False)
        state.set_sync_reset_pending(True)
        print("[sync] OFF", file=sys.stderr, flush=True)
    elif msg == "CALIB:ON":
        state.set_calib(True)
        state.set_calib_need_corner_reset(True)
        print("[calib] ON", file=sys.stderr, flush=True)
    elif msg == "CALIB:OFF":
        state.set_calib(False)
        state.set_calib_reset_pending(True)
        print("[calib] OFF", file=sys.stderr, flush=True)
    elif msg.startswith("SYNC:TURN="):
        match = re.search(r"TURN\s*=\s*([BW])", msg, flags=re.IGNORECASE)
        turn = _norm_turn(match.group(1)) if match else None
        if turn:
            state.set_sync_turn(turn)
            state.set_preview_turn(turn)
            print(f"[sync] TURN={turn}", file=sys.stderr, flush=True)
    elif msg == "START":
        state.set_started(True, "B")
    elif msg.startswith("START:"):
        match = re.search(r"TURN\s*=\s*([BW])", msg, flags=re.IGNORECASE)
        turn = _norm_turn(match.group(1)) if match else None
        state.set_started(True, turn or "B")
    elif msg.startswith("PREVIEW:"):
        match = re.search(r"TURN\s*=\s*([BW])", msg, flags=re.IGNORECASE)
        turn = _norm_turn(match.group(1)) if match else None
        if turn:
            state.set_preview_turn(turn)


def start_stdin_reader(state: RealtimeControlState) -> threading.Thread:
    def _stdin_reader():
        for line in sys.stdin:
            apply_command(line.strip(), state)

    thread = threading.Thread(target=_stdin_reader, daemon=True)
    thread.start()
    return thread


def emit_state(
    turn,
    board,
    moves,
    evals=None,
    last_move=None,
    cause_move=None,
    passed_side=None,
    game_over: bool = False,
    end_reason: str | None = None,
    calib_preview: bool = False,
):
    payload = {
        "turn": turn,
        "board": board,
        "ascii": ascii_with_moves(board, moves),
        "moves": [coord(y, x) for y, x in moves],
    }
    if evals is not None:
        payload["evals"] = evals
    if last_move is not None:
        payload["last_move"] = last_move
    if cause_move is not None:
        payload["cause_move"] = cause_move
    if passed_side is not None:
        payload["passed_side"] = passed_side
    if game_over:
        payload["game_over"] = True
    if end_reason is not None:
        payload["end_reason"] = end_reason
    if calib_preview:
        payload["calib_preview"] = True
    print("STATE:" + json.dumps(payload, ensure_ascii=False), flush=True)


def emit_sync_state(board):
    payload = {"board": board}
    print("SYNC_STATE:" + json.dumps(payload, ensure_ascii=False), flush=True)


def emit_end(reason: str, board):
    black, white = count_bw(board)
    winner = winner_from_counts(black, white)
    print(f"END: reason={reason} winner={winner} black={black} white={white}", flush=True)
