#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import collections
import copy
import sys
import time
from dataclasses import dataclass
from typing import Optional, Protocol

import cv2

from board_tracker import BoardTracker
from engine_log import LOG_H, LOG_W, add_log, render_log_img
from othello_rules import ascii_with_moves, coord, diff_moves, legal_moves
from othello_rules import evaluate_moves_for_board, is_board_full
from realtime_protocol import RealtimeControlState, emit_end, emit_state, emit_sync_state, start_stdin_reader

Board = list[list[str]]
RgbCell = tuple[int, int, int]
RgbGrid = list[list[RgbCell]]


@dataclass(frozen=True)
class EngineConfig:
    eval_depth: int = 2
    hand_stable_n: int = 2
    board_sample_every: int = 8
    waiting_timeout_frames: int = 240
    stable_n: int = 10
    min_stones_start: int = 4
    sync_stable_n: int = 4
    sync_sample_every: int = 3
    sync_emit_min_interval_sec: float = 0.2


@dataclass
class RealtimeLoopState:
    prev_hp: bool = False
    waiting_for_move: bool = False
    consecutive_passes: int = 0
    end_emitted: bool = False
    prev_board: Board | None = None
    confirmed_total: Optional[int] = None
    last_total: Optional[int] = None
    same_frames: int = 0
    waiting_age: int = 0
    prev_logged_tot: Optional[int] = None
    last_cur: Board | None = None
    last_rgb_full: RgbGrid | None = None


@dataclass
class SyncModeState:
    last_key: Optional[tuple] = None
    same_frames: int = 0
    last_tot: Optional[int] = None
    last_emit_ts: float = 0.0


@dataclass
class DisplayState:
    show_rgb: bool = False
    quit_requested: bool = False


@dataclass
class FrameContext:
    force_preview_emit: bool
    color_hand: bool
    hp: bool
    prev_controls: Optional[tuple[int, int, int]]


class TrackerProtocol(Protocol):
    green_margin: int
    delta_L: int
    hand_grid_idx: int

    def read_board(self): ...
    def detect_hand(self, board) -> bool: ...
    def classify_stones(self, board) -> tuple[Board, RgbGrid]: ...
    def hand_mask_8x8(self, board) -> list[list[bool]]: ...
    def show_board_overlay(self, board, labels, rgb_full, show_rgb: bool = False) -> None: ...
    def capture_calib_frame(self): ...
    def select_corners_interactive(self, image): ...
    def apply_corners(self, pts) -> None: ...
    def calibrate(self) -> bool: ...
    def release(self) -> None: ...


@dataclass(frozen=True)
class TurnResolution:
    kind: str
    played: str
    opp: str
    opp_moves: list[tuple[int, int]]
    my_moves: list[tuple[int, int]]
    board_full: bool


def handle_display_input(display_state: DisplayState) -> None:
    key = cv2.waitKey(1) & 0xFF
    if key == 27:
        display_state.quit_requested = True
    elif key == ord("d"):
        display_state.show_rgb = not display_state.show_rgb


def render_board_frame(
    display_state: DisplayState,
    frame,
    tracker=None,
    board: Board | None = None,
    rgb_full: RgbGrid | None = None,
    overlay_labels: Board | None = None,
) -> None:
    vis = frame.copy()
    if tracker is not None and board is not None and rgb_full is not None:
        labels = overlay_labels if overlay_labels is not None else board
        tracker.show_board_overlay(vis, labels, rgb_full, show_rgb=display_state.show_rgb)
    cv2.imshow("board", vis)
    cv2.imshow("log", render_log_img())
    handle_display_input(display_state)


def build_hand_overlay_labels(tracker, frame, board: Board | None) -> Board | None:
    if board is None:
        return None
    labels = copy.deepcopy(board)
    try:
        hm8 = tracker.hand_mask_8x8(frame)
        for y in range(8):
            for x in range(8):
                if hm8[y][x]:
                    labels[y][x] = "H"
    except Exception:
        pass
    return labels


def reset_loop_state_for_board(loop_state: RealtimeLoopState, cur: Board, rgb_full: RgbGrid, tot: int) -> None:
    loop_state.last_cur, loop_state.last_rgb_full = cur, rgb_full
    loop_state.prev_board = copy.deepcopy(cur)
    loop_state.confirmed_total = tot
    loop_state.waiting_for_move = False
    loop_state.waiting_age = 0
    loop_state.consecutive_passes = 0
    loop_state.end_emitted = False
    loop_state.last_total = None
    loop_state.same_frames = 0


def handle_sync_reset(
    control_state: RealtimeControlState,
    tracker,
    frame,
    hp: bool,
    loop_state: RealtimeLoopState,
    config: EngineConfig,
) -> None:
    if control_state.get_sync() or (not control_state.get_sync_reset_pending()) or hp:
        return

    cur, rgb_full = tracker.classify_stones(frame)
    tot = sum(c in ("B", "W") for r in cur for c in r)
    reset_loop_state_for_board(loop_state, cur, rgb_full, tot)

    turn = control_state.get_sync_turn()
    if turn not in ("B", "W"):
        turn = control_state.get_preview_turn()
    lm = legal_moves(cur, turn)
    evals = evaluate_moves_for_board(cur, turn, depth=config.eval_depth)
    add_log(f"[SYNC_RESET] apply board tot={tot} turn={turn}")
    emit_state(turn, cur, lm, evals=evals)
    control_state.set_sync_reset_pending(False)


def handle_calib_reset(control_state: RealtimeControlState, tracker, frame, hp: bool, loop_state: RealtimeLoopState) -> None:
    if (not control_state.get_calib_reset_pending()) or hp:
        return

    cur, rgb_full = tracker.classify_stones(frame)
    tot = sum(c in ("B", "W") for r in cur for c in r)
    reset_loop_state_for_board(loop_state, cur, rgb_full, tot)

    src = "corner" if control_state.get_calib() else "off"
    add_log(f"[CALIB_RESET:{src}] apply board tot={tot} turn={control_state.get_preview_turn()}")
    control_state.set_calib_reset_pending(False)


def handle_calib_corner_reset(control_state: RealtimeControlState, tracker, color_hand: bool, loop_state: RealtimeLoopState) -> None:
    if (not control_state.get_calib()) or (not control_state.get_calib_need_corner_reset()):
        return

    if color_hand:
        add_log("[CALIB] waiting: hand color detected (remove hand from board)")
        return

    add_log("[CALIB] reselect corners: window will open (press 'c' to freeze, click 4 corners)")
    calib_img = None
    try:
        calib_img = tracker.capture_calib_frame()
    except Exception as e:
        add_log(f"[CALIB] capture_calib_frame failed: {e}")

    if calib_img is None:
        add_log("[CALIB] canceled. (No change) もう一度やるならCALIBをOFF→ONしてください")
        control_state.set_calib_need_corner_reset(False)
        return

    corners = None
    try:
        corners = tracker.select_corners_interactive(calib_img)
    except Exception as e:
        add_log(f"[CALIB] select_corners_interactive failed: {e}")

    if corners is None:
        add_log("[CALIB] corner selection canceled. (No change) もう一度やるならCALIBをOFF→ONしてください")
        control_state.set_calib_need_corner_reset(False)
        return

    try:
        tracker.apply_corners(corners)
        add_log("[CALIB] corners applied")
        control_state.set_calib_reset_pending(True)
        loop_state.last_total = None
        loop_state.same_frames = 0
    except Exception as e:
        add_log(f"[CALIB] apply_corners failed: {e}")
    finally:
        control_state.set_calib_need_corner_reset(False)


def update_hand_state(hp: bool, loop_state: RealtimeLoopState) -> None:
    if loop_state.prev_hp and not hp:
        loop_state.waiting_for_move = True
        loop_state.waiting_age = 0
        print("HAND_OFF", file=sys.stderr, flush=True)
    elif hp and not loop_state.prev_hp:
        loop_state.waiting_for_move = False
        loop_state.waiting_age = 0
        print("HAND_ON", file=sys.stderr, flush=True)
    elif hp:
        loop_state.waiting_for_move = False
        loop_state.waiting_age = 0
    loop_state.prev_hp = hp


def prepare_frame_context(
    control_state: RealtimeControlState,
    tracker: TrackerProtocol,
    frame,
    prev_controls: Optional[tuple[int, int, int]],
    hand_hist,
    config: EngineConfig,
) -> FrameContext:
    force_preview_emit = False

    if (not control_state.get_user_started()) or control_state.get_calib():
        controls = (tracker.green_margin, tracker.delta_L, tracker.hand_grid_idx)
        if prev_controls is None:
            prev_controls = controls
        elif controls != prev_controls:
            prev_controls = controls
            force_preview_emit = True
            add_log(f"[CALIB] controls changed: gm={controls[0]} dL={controls[1]} grid={controls[2]}")

    color_hand_raw = tracker.detect_hand(frame)
    hand_hist.append(bool(color_hand_raw))
    color_hand = sum(hand_hist) >= config.hand_stable_n
    hp = bool(control_state.get_hand_mp() or color_hand)

    return FrameContext(
        force_preview_emit=force_preview_emit,
        color_hand=color_hand,
        hp=hp,
        prev_controls=prev_controls,
    )


def handle_sync_mode(
    control_state: RealtimeControlState,
    tracker: TrackerProtocol,
    frame,
    config: EngineConfig,
    frame_i: int,
    hp: bool,
    loop_state: RealtimeLoopState,
    sync_state: SyncModeState,
    display_state: DisplayState,
) -> bool:
    if not control_state.get_sync():
        return False

    if hp:
        render_board_frame(
            display_state,
            frame,
            tracker=tracker if loop_state.last_cur is not None and loop_state.last_rgb_full is not None else None,
            board=loop_state.last_cur,
            rgb_full=loop_state.last_rgb_full,
            overlay_labels=build_hand_overlay_labels(tracker, frame, loop_state.last_cur),
        )
        return True

    if frame_i % config.sync_sample_every != 0:
        if loop_state.last_cur is not None and loop_state.last_rgb_full is not None:
            render_board_frame(display_state, frame, tracker=tracker, board=loop_state.last_cur, rgb_full=loop_state.last_rgb_full)
        else:
            render_board_frame(display_state, frame)
        return True

    cur, rgb_full = tracker.classify_stones(frame)
    loop_state.last_cur, loop_state.last_rgb_full = cur, rgb_full
    tot = sum(c in ("B", "W") for r in cur for c in r)

    update_sync_tracking(sync_state, tot)
    maybe_emit_sync_state(cur, tot, sync_state, config)

    render_board_frame(display_state, frame, tracker=tracker, board=cur, rgb_full=rgb_full)
    return True


def handle_hand_present_mode(
    tracker: TrackerProtocol,
    frame,
    hp: bool,
    loop_state: RealtimeLoopState,
    display_state: DisplayState,
) -> bool:
    if not hp:
        return False

    render_board_frame(
        display_state,
        frame,
        tracker=tracker if loop_state.last_cur is not None and loop_state.last_rgb_full is not None else None,
        board=loop_state.last_cur,
        rgb_full=loop_state.last_rgb_full,
        overlay_labels=build_hand_overlay_labels(tracker, frame, loop_state.last_cur),
    )
    return True


def should_sample_board(
    control_state: RealtimeControlState,
    config: EngineConfig,
    frame_i: int,
    loop_state: RealtimeLoopState,
    force_preview_emit: bool,
) -> bool:
    if (not control_state.get_user_started()) or (loop_state.prev_board is None) or loop_state.waiting_for_move or force_preview_emit:
        return True
    if control_state.get_user_started() and (loop_state.confirmed_total is not None) and (frame_i % config.board_sample_every == 0):
        return True
    return False


def handle_idle_or_skip_frame(
    tracker: TrackerProtocol,
    frame,
    need_board: bool,
    loop_state: RealtimeLoopState,
    display_state: DisplayState,
) -> bool:
    if need_board:
        return False

    if loop_state.last_cur is not None and loop_state.last_rgb_full is not None:
        render_board_frame(display_state, frame, tracker=tracker, board=loop_state.last_cur, rgb_full=loop_state.last_rgb_full)
    else:
        render_board_frame(display_state, frame)

    return True


def update_total_tracking(loop_state: RealtimeLoopState, tot: int) -> None:
    if loop_state.prev_logged_tot is None:
        add_log(f"[TOT] init {tot}")
        loop_state.prev_logged_tot = tot
    elif tot != loop_state.prev_logged_tot:
        delta = tot - loop_state.prev_logged_tot
        sign = "+" if delta > 0 else ""
        add_log(f"[TOT] {loop_state.prev_logged_tot} -> {tot} ({sign}{delta})")
        loop_state.prev_logged_tot = tot

    if loop_state.last_total is None:
        loop_state.last_total, loop_state.same_frames = tot, 1
    elif tot == loop_state.last_total:
        loop_state.same_frames += 1
    else:
        loop_state.last_total, loop_state.same_frames = tot, 1


def update_sync_tracking(sync_state: SyncModeState, tot: int) -> None:
    if sync_state.last_tot is None:
        sync_state.last_tot, sync_state.same_frames = tot, 1
    elif tot == sync_state.last_tot:
        sync_state.same_frames += 1
    else:
        sync_state.last_tot, sync_state.same_frames = tot, 1


def maybe_emit_sync_state(cur: Board, tot: int, sync_state: SyncModeState, config: EngineConfig) -> bool:
    if sync_state.same_frames < config.sync_stable_n:
        return False

    try:
        key = tuple(tuple(r) for r in cur)
    except Exception:
        key = None

    emitted = False
    if key is not None:
        now = time.time()
        if (key != sync_state.last_key) or ((now - sync_state.last_emit_ts) >= config.sync_emit_min_interval_sec):
            sync_state.last_key = key
            sync_state.last_emit_ts = now
            emit_sync_state(cur)
            add_log(f"[SYNC_STATE] emit (tot={tot})")
            emitted = True

    sync_state.same_frames = 0
    sync_state.last_tot = None
    return emitted


def resolve_turn_resolution(cur: Board, played: str) -> TurnResolution:
    opp = "W" if played == "B" else "B"
    opp_moves = legal_moves(cur, opp)
    my_moves = legal_moves(cur, played)
    board_full = is_board_full(cur)

    if opp_moves:
        kind = "board_full_after_normal" if board_full else "normal"
    elif board_full:
        kind = "board_full_after_pass"
    elif not my_moves:
        kind = "double_pass"
    else:
        kind = "pass"

    return TurnResolution(
        kind=kind,
        played=played,
        opp=opp,
        opp_moves=opp_moves,
        my_moves=my_moves,
        board_full=board_full,
    )


def handle_preview_emit(
    control_state: RealtimeControlState,
    cur: Board,
    hp: bool,
    tot: int,
    loop_state: RealtimeLoopState,
    config: EngineConfig,
    force_preview_emit: bool,
) -> None:
    if (not hp) and ((not control_state.get_user_started()) or control_state.get_calib()) and (tot >= config.min_stones_start) and (loop_state.same_frames >= config.stable_n or force_preview_emit):
        preview_turn = control_state.get_preview_turn()
        lm = legal_moves(cur, preview_turn)
        evals = evaluate_moves_for_board(cur, preview_turn, depth=config.eval_depth)
        add_log("[PREVIEW] emit STATE for calibration")
        emit_state(preview_turn, cur, lm, evals=evals, calib_preview=control_state.get_calib())
        loop_state.same_frames = 0
        loop_state.last_total = None


def handle_game_init(
    control_state: RealtimeControlState,
    cur: Board,
    tot: int,
    loop_state: RealtimeLoopState,
    config: EngineConfig,
) -> bool:
    if not (control_state.get_user_started() and loop_state.prev_board is None and loop_state.same_frames >= config.stable_n and tot >= config.min_stones_start):
        return False

    loop_state.prev_board = copy.deepcopy(cur)
    loop_state.confirmed_total = tot
    loop_state.waiting_for_move = False
    loop_state.waiting_age = 0
    loop_state.consecutive_passes = 0
    loop_state.end_emitted = False
    started_turn = control_state.get_user_started_turn()
    lm = legal_moves(loop_state.prev_board, started_turn)
    evals = evaluate_moves_for_board(loop_state.prev_board, started_turn, depth=config.eval_depth)
    who = "黒" if started_turn == "B" else "白"
    add_log(f"[INIT] 石 {tot} 個 - {who}番開始")
    add_log(ascii_with_moves(loop_state.prev_board, lm))
    emit_state(started_turn, loop_state.prev_board, lm, evals=evals)
    loop_state.same_frames = 0
    return True


def handle_move_confirmation(cur: Board, tot: int, loop_state: RealtimeLoopState, config: EngineConfig) -> None:
    if (not loop_state.waiting_for_move) and (loop_state.confirmed_total is not None) and (tot == loop_state.confirmed_total + 1):
        loop_state.waiting_for_move = True
        loop_state.waiting_age = 0
        add_log("[FAILSAFE] tot+1 detected without HAND_OFF; treating as waiting_for_move")

    if loop_state.waiting_for_move and loop_state.confirmed_total is not None:
        loop_state.waiting_age += 1
        if loop_state.waiting_age >= config.waiting_timeout_frames:
            add_log("[FAILSAFE] waiting_for_move timeout -> reset")
            loop_state.waiting_for_move = False
            loop_state.waiting_age = 0
            loop_state.same_frames = 0
            loop_state.last_total = None

        if loop_state.same_frames >= config.stable_n and tot == loop_state.confirmed_total + 1:
            mv, fl = diff_moves(loop_state.prev_board, cur)

            played_move_str = None
            for y, x, c in mv:
                m = coord(y, x).lower()
                if played_move_str is None:
                    played_move_str = m
                add_log(f"[MOVE] {m} に {c}")
                print("MOVE:" + m, flush=True)

            for y, x, c in fl:
                add_log(f"[FLIP] {coord(y,x)} → {c}")

            if mv:
                played = mv[0][2]
                resolution = resolve_turn_resolution(cur, played)
                opp = resolution.opp
                opp_moves = resolution.opp_moves

                if opp_moves:
                    loop_state.consecutive_passes = 0
                    sym = "●" if opp == "B" else "○"
                    add_log(f"[TURN] 次は {sym} ({opp})")
                    add_log(ascii_with_moves(cur, opp_moves))
                    evals = evaluate_moves_for_board(cur, opp, depth=config.eval_depth)
                    emit_state(opp, cur, opp_moves, evals=evals, last_move=played_move_str)

                    if (not loop_state.end_emitted) and resolution.kind == "board_full_after_normal":
                        loop_state.end_emitted = True
                        add_log("[END] board_full")
                        emit_end("board_full", cur)
                else:
                    symp = "●" if opp == "B" else "○"
                    symt = "●" if played == "B" else "○"
                    my_moves = resolution.my_moves

                    add_log(f"[PASS] {symp} ({opp}) パス")
                    add_log(f"[TURN] 次も {symt} ({played})")
                    add_log(ascii_with_moves(cur, my_moves))

                    evals = evaluate_moves_for_board(cur, played, depth=config.eval_depth)

                    if (not loop_state.end_emitted) and resolution.kind == "board_full_after_pass":
                        emit_state(
                            opp,
                            cur,
                            opp_moves,
                            evals=evals,
                            last_move=played_move_str,
                            game_over=True,
                            end_reason="board_full",
                        )
                        loop_state.end_emitted = True
                        add_log("[END] board_full")
                        emit_end("board_full", cur)
                    elif (not loop_state.end_emitted) and resolution.kind == "double_pass":
                        emit_state(
                            played,
                            cur,
                            my_moves,
                            evals=evals,
                            last_move=played_move_str,
                            game_over=True,
                            end_reason="double_pass",
                        )
                        loop_state.end_emitted = True
                        add_log("[END] double_pass")
                        emit_end("double_pass", cur)
                    else:
                        loop_state.consecutive_passes += 1
                        emit_state(
                            played,
                            cur,
                            my_moves,
                            evals=evals,
                            last_move="pass",
                            cause_move=played_move_str,
                            passed_side=opp,
                        )
            loop_state.prev_board = copy.deepcopy(cur)
            loop_state.confirmed_total = tot
            loop_state.waiting_for_move = False
            loop_state.waiting_age = 0
            loop_state.same_frames = 0


def handle_board_update_mode(
    control_state: RealtimeControlState,
    tracker: TrackerProtocol,
    frame,
    hp: bool,
    loop_state: RealtimeLoopState,
    display_state: DisplayState,
    config: EngineConfig,
    force_preview_emit: bool,
) -> bool:
    cur, rgb_full = tracker.classify_stones(frame)
    loop_state.last_cur, loop_state.last_rgb_full = cur, rgb_full
    tot = sum(c in ("B", "W") for r in cur for c in r)

    update_total_tracking(loop_state, tot)
    handle_preview_emit(control_state, cur, hp, tot, loop_state, config, force_preview_emit)

    if control_state.get_calib():
        render_board_frame(display_state, frame, tracker=tracker, board=cur, rgb_full=rgb_full)
        return True

    if handle_game_init(control_state, cur, tot, loop_state, config):
        return True

    handle_move_confirmation(cur, tot, loop_state, config)

    render_board_frame(display_state, frame, tracker=tracker, board=cur, rgb_full=rgb_full)

    return True


def run_engine_loop(
    control_state: RealtimeControlState,
    tracker: TrackerProtocol,
    loop_state: RealtimeLoopState,
    display_state: DisplayState,
    sync_state: SyncModeState,
    config: EngineConfig,
) -> None:
    prev_controls = None
    hand_hist = collections.deque(maxlen=config.hand_stable_n)
    frame_i = 0

    while True:
        frame = tracker.read_board()
        if frame is None:
            break
        frame_i += 1

        frame_ctx = prepare_frame_context(control_state, tracker, frame, prev_controls, hand_hist, config)
        prev_controls = frame_ctx.prev_controls
        force_preview_emit = frame_ctx.force_preview_emit
        color_hand = frame_ctx.color_hand
        hp = frame_ctx.hp

        handle_sync_reset(control_state, tracker, frame, hp, loop_state, config)
        handle_calib_reset(control_state, tracker, frame, hp, loop_state)
        handle_calib_corner_reset(control_state, tracker, color_hand, loop_state)
        update_hand_state(hp, loop_state)

        if handle_sync_mode(control_state, tracker, frame, config, frame_i, hp, loop_state, sync_state, display_state):
            if display_state.quit_requested:
                break
            continue

        if handle_hand_present_mode(tracker, frame, hp, loop_state, display_state):
            if display_state.quit_requested:
                break
            continue

        need_board = should_sample_board(control_state, config, frame_i, loop_state, force_preview_emit)

        if handle_idle_or_skip_frame(tracker, frame, need_board, loop_state, display_state):
            if display_state.quit_requested:
                break
            continue

        handle_board_update_mode(
            control_state,
            tracker,
            frame,
            hp,
            loop_state,
            display_state,
            config,
            force_preview_emit,
        )
        if display_state.quit_requested:
            break


def main():
    control_state = RealtimeControlState()
    start_stdin_reader(control_state)
    tracker: TrackerProtocol = BoardTracker(cam_id=0)
    tracker.calibrate()
    print("[i] 準備完了。Esc で終了", flush=True)
    print("READY", flush=True)

    loop_state = RealtimeLoopState()
    display_state = DisplayState()
    sync_state = SyncModeState()
    config = EngineConfig()

    cv2.namedWindow("log")
    cv2.resizeWindow("log", LOG_W, LOG_H)

    run_engine_loop(control_state, tracker, loop_state, display_state, sync_state, config)

    tracker.release()
    cv2.destroyAllWindows()
