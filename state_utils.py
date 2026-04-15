from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FlipState:
    flip_h: bool = False  # 左右反転（a<->h）
    flip_v: bool = False  # 上下反転（1<->8）


def transform_coord(coord: str, flip: FlipState) -> str:
    """'e3' のような座標を反転。未知形式はそのまま返す。"""
    if not coord or len(coord) != 2:
        return coord
    files = "abcdefgh"
    ranks = "12345678"
    f, r = coord[0], coord[1]
    if f not in files or r not in ranks:
        return coord
    fi = files.index(f)
    ri = ranks.index(r)
    if flip.flip_h:
        fi = 7 - fi
    if flip.flip_v:
        ri = 7 - ri
    return files[fi] + ranks[ri]


def transform_board(board: list[list[str]] | None, flip: FlipState):
    """
    board: 8x8の二次元配列を想定
      行: rank1 -> rank8
      列: file a -> h
    """
    if not board:
        return board
    matrix = [row[:] for row in board]
    if flip.flip_h:
        matrix = [list(reversed(row)) for row in matrix]
    if flip.flip_v:
        matrix = list(reversed(matrix))
    return matrix


def transform_evals(evals: dict | None, flip: FlipState) -> dict | None:
    if not isinstance(evals, dict):
        return evals
    out = {}
    for k, v in evals.items():
        out[transform_coord(k, flip)] = v
    return out


def transform_state(raw_state: dict, flip: FlipState) -> dict:
    """RAW -> VIEW へ統一変換"""
    if not isinstance(raw_state, dict):
        return raw_state
    view = dict(raw_state)
    if "board" in raw_state:
        view["board"] = transform_board(raw_state["board"], flip)
    if "moves" in raw_state and isinstance(raw_state["moves"], list):
        view["moves"] = [transform_coord(m, flip) for m in raw_state["moves"]]
    if "last_move" in raw_state and isinstance(raw_state["last_move"], str):
        view["last_move"] = transform_coord(raw_state["last_move"], flip)
    if "cause_move" in raw_state and isinstance(raw_state["cause_move"], str):
        view["cause_move"] = transform_coord(raw_state["cause_move"], flip)

    if "passed_side" in raw_state and isinstance(raw_state["passed_side"], str):
        view["passed_side"] = raw_state["passed_side"]

    if "evals" in raw_state:
        view["evals"] = transform_evals(raw_state["evals"], flip)

    if "top_moves" in raw_state and isinstance(raw_state["top_moves"], list):
        view["top_moves"] = [transform_coord(m, flip) for m in raw_state["top_moves"]]

    if "recommendations" in raw_state and isinstance(raw_state["recommendations"], list):
        recs = []
        for rec in raw_state["recommendations"]:
            if isinstance(rec, dict) and "move" in rec and isinstance(rec["move"], str):
                rec = dict(rec)
                rec["move"] = transform_coord(rec["move"], flip)
            recs.append(rec)
        view["recommendations"] = recs

    if "pos_eval" in raw_state:
        view["pos_eval"] = raw_state["pos_eval"]
    if "move_no" in raw_state:
        view["move_no"] = raw_state["move_no"]
    if "turn_history" in raw_state and isinstance(raw_state["turn_history"], list):
        view["turn_history"] = raw_state["turn_history"]

    return view


def normalize_board(board: Any):
    """STATE['board'] が 8行の list[list[str]] でも list[str] でも受け付ける"""
    if not isinstance(board, list) or len(board) != 8:
        return None
    out = []
    for row in board:
        if isinstance(row, str):
            normalized_row = [ch for ch in row.replace(" ", "") if ch in (".", "B", "W")]
            if len(normalized_row) != 8:
                return None
            out.append(normalized_row)
        elif isinstance(row, list):
            if len(row) != 8 or any(ch not in (".", "B", "W") for ch in row):
                return None
            out.append(row[:])
        else:
            return None
    return out


def normalize_turn(turn: Any):
    """'B'/'W' に正規化。無効なら None を返す。"""
    if not isinstance(turn, str) or len(turn) == 0:
        return None
    upper = turn.strip().upper()
    if upper in ("B", "W"):
        return upper
    if upper.startswith("B"):
        return "B"
    if upper.startswith("W"):
        return "W"
    return None


def move_count_from_board(board_2d: list[list[str]] | None) -> int:
    """手数（0開始）を推定: 石の総数 - 4（初期4石）"""
    if not board_2d:
        return 0
    stones = sum(1 for y in range(8) for x in range(8) if board_2d[y][x] in ("B", "W"))
    return max(0, stones - 4)


def count_bw(board: list[list[str]]) -> tuple[int, int]:
    black = sum(1 for row in board for cell in row if cell == "B")
    white = sum(1 for row in board for cell in row if cell == "W")
    return black, white
