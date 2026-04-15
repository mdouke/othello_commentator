from __future__ import annotations

import json
import logging
from typing import Any

from othello_rules import evaluate_moves_for_board, evaluate_position
from runtime_state import EvalSettings, RuntimeState, TurnCycleState, UiControlState
from state_utils import (
    FlipState,
    count_bw,
    move_count_from_board,
    normalize_board,
    normalize_turn,
    transform_state,
)


class StateProcessor:
    def __init__(
        self,
        *,
        app,
        commentary_service,
        resume_manager,
        runtime_state: RuntimeState,
        cycle_state: TurnCycleState,
        ui_state: UiControlState,
        eval_settings: EvalSettings,
        flip_state: FlipState,
        logger: logging.Logger,
    ) -> None:
        self.app = app
        self.commentary_service = commentary_service
        self.resume_manager = resume_manager
        self.runtime_state = runtime_state
        self.cycle_state = cycle_state
        self.ui_state = ui_state
        self.eval_settings = eval_settings
        self.flip_state = flip_state
        self.log = logger

    def handle_calib_preview_state(self, msg: str) -> bool:
        if not msg.startswith("STATE:"):
            return False

        payload = msg[6:].strip()
        try:
            raw = json.loads(payload)
        except Exception as exc:
            self.log.warning(f"STATE JSON parse error (calib): {exc}")
            return True

        if not raw.get("calib_preview"):
            self.app.after(0, self.app.append_log, "[gate] ignored normal STATE while PAUSED_CALIB")
            return True

        board = normalize_board(raw.get("board"))
        turn = normalize_turn(raw.get("turn"))
        if board is None:
            return True

        raw["board"] = board
        if turn is not None:
            raw["turn"] = turn
        view = transform_state(raw, self.flip_state)

        self._publish_piece_counts(board)
        self.app.after(0, self.app.update_board, view)
        return True

    def handle_running_state(self, msg: str) -> bool:
        if not msg.startswith("STATE:"):
            return False

        payload = msg[6:].strip()
        try:
            raw = json.loads(payload)
        except Exception as exc:
            self.log.warning(f"STATE JSON parse error: {exc}")
            return True

        board = normalize_board(raw.get("board"))
        turn = normalize_turn(raw.get("turn"))
        if board is not None:
            raw["board"] = board
        if turn is not None:
            raw["turn"] = turn

        raw["pos_eval"] = self._safe_position_eval(board, turn if turn in ("B", "W") else "B", "pos_eval")
        black_eval = self._safe_position_eval(board, "B", "black_eval")

        try:
            with self.eval_settings.lock:
                depth = self.eval_settings.depth
            raw["evals"] = evaluate_moves_for_board(board, turn or "B", depth=depth) if board else {}
        except Exception as exc:
            self.log.warning(f"evaluate_moves_for_board failed: {exc}")
            raw["evals"] = {}

        move_no = move_count_from_board(board) if board else 0
        raw["move_no"] = move_no
        raw["turn_history"] = self.runtime_state.turn_history

        self.runtime_state.latest_raw = raw
        view = transform_state(raw, self.flip_state)

        if board is not None and turn in ("B", "W"):
            self.resume_manager.push_snapshot(
                view=view,
                board_norm=board,
                move_no=move_no,
                turn=turn,
                black_eval=black_eval,
            )

        self._publish_piece_counts(board)
        self.app.after(0, self.app.update_board, view)
        if hasattr(self.app, "add_eval_point"):
            self.app.after(0, self.app.add_eval_point, move_no, black_eval)

        if self.ui_state.prompt_gate_open:
            if raw.get("game_over"):
                self.runtime_state.final_view = view
                self.app.after(0, self.app.append_log, f"[state] final state received end_reason={raw.get('end_reason')}")
            else:
                self.commentary_service.maybe_trigger_post_comment(raw, view, self.runtime_state)
        else:
            self.runtime_state.pre_snapshot_view = view

        self._update_turn_cycle(turn, move_no, raw, black_eval)
        return True

    def recompute_current_state(self, depth: int) -> None:
        with self.eval_settings.lock:
            self.eval_settings.depth = depth

        raw = self.runtime_state.latest_raw
        if not isinstance(raw, dict):
            return

        board = raw.get("board")
        turn = raw.get("turn") or "B"
        if not board or not isinstance(board, list):
            return

        try:
            raw["evals"] = evaluate_moves_for_board(board, turn, depth=depth)
            black_eval = self._safe_position_eval(board, "B", "black_eval")

            view = transform_state(raw, self.flip_state)
            self.app.after(0, self.app.update_board, view)
            if hasattr(self.app, "update_eval_table"):
                self.app.after(0, self.app.update_eval_table, view.get("evals", {}), depth)
            if hasattr(self.app, "add_eval_point"):
                move_no = move_count_from_board(board)
                self.app.after(0, self.app.add_eval_point, move_no, black_eval)
        except Exception as exc:
            self.log.warning(f"re-evaluate on depth change failed: {exc}")

    def _safe_position_eval(self, board, turn: str, label: str) -> float | None:
        try:
            return float(evaluate_position(board, turn)) if board else None
        except Exception as exc:
            self.log.warning(f"{label} failed: {exc}")
            return None

    def _publish_piece_counts(self, board: list[list[str]] | None) -> None:
        if board and hasattr(self.app, "set_piece_counts"):
            bcnt, wcnt = count_bw(board)
            self.app.after(0, self.app.set_piece_counts, bcnt, wcnt)

    def _update_turn_cycle(
        self,
        turn: str | None,
        move_no: int,
        raw: dict[str, Any],
        black_eval: float | None,
    ) -> None:
        cycle = self.cycle_state
        turn_history = self.runtime_state.turn_history

        if cycle.anchor is None and turn in ("B", "W"):
            cycle.anchor = turn
            cycle.start_move_no = move_no

        pass_happened = (
            cycle.prev_turn is not None
            and cycle.prev_turn != turn
            and isinstance(cycle.prev_moves_len, int)
            and cycle.prev_moves_len == 0
            and isinstance(cycle.prev_move_no, int)
            and move_no == cycle.prev_move_no
        )

        if cycle.anchor is not None and turn == cycle.anchor:
            if (cycle.start_move_no is not None and move_no != cycle.start_move_no) or pass_happened:
                if hasattr(self.app, "add_turn_segment"):
                    self.app.after(0, self.app.add_turn_segment, cycle.start_move_no, move_no)
                if hasattr(self.app, "add_turn_eval_point"):
                    self.app.after(0, self.app.add_turn_eval_point, move_no, black_eval)

                if black_eval is not None:
                    turn_index = len(turn_history) + 1
                    turn_history.append(
                        {
                            "turn_index": turn_index,
                            "side": cycle.anchor,
                            "end_move_no": move_no,
                            "black_eval": float(black_eval),
                        }
                    )

                cycle.start_move_no = move_no

        cycle.prev_turn = turn
        curr_moves_len = len(raw.get("moves") or []) if isinstance(raw.get("moves"), list) else None
        cycle.prev_moves_len = curr_moves_len
        cycle.prev_move_no = move_no
