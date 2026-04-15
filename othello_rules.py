# othello_rules.py
from __future__ import annotations
from typing import List, Tuple, Optional, Dict

# ==== 基本定義（サイズ/方向/座標） ====
HW = 8
hw = HW  # 互換エイリアス

DIRS = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]

def inside(y: int, x: int) -> bool:
    return 0 <= y < HW and 0 <= x < HW

def coord(y: int, x: int) -> str:
    return f"{chr(ord('a')+x)}{y+1}"

# --- 盤面表示API ---
def ascii_with_moves(board: List[List[str]], moves: List[Tuple[int,int]]) -> List[str]:
    mset = {(y, x) for y, x in moves}
    lines = ["/ a b c d e f g h"]
    for y in range(HW):
        row = [str(y+1)]
        for x in range(HW):
            row.append("P" if (y, x) in mset else board[y][x])
        lines.append(" ".join(row))
    return lines

# --- 盤面操作API（文字盤面 '.' 'B' 'W'） ---
def legal_moves(board: List[List[str]], player: str) -> List[Tuple[int,int]]:
    opp = "W" if player == "B" else "B"
    ms: List[Tuple[int,int]] = []
    for y in range(HW):
        for x in range(HW):
            if board[y][x] != ".":
                continue
            for dy, dx in DIRS:
                ny, nx = y+dy, x+dx
                seen = False
                while inside(ny, nx) and board[ny][nx] == opp:
                    seen = True
                    ny += dy; nx += dx
                if seen and inside(ny, nx) and board[ny][nx] == player:
                    ms.append((y, x))
                    break
    return ms

def diff_moves(prev_b: List[List[str]], cur_b: List[List[str]]):
    """prev→cur の変化を (打たれた1マス群, 反転群) に分解"""
    mv, fl = [], []
    for y in range(HW):
        for x in range(HW):
            p, c = prev_b[y][x], cur_b[y][x]
            if p == c:
                continue
            (mv if p == "." else fl).append((y, x, c))
    return mv, fl

# =========================
#  終局判定ユーティリティ
# =========================
def count_bw(board: List[List[str]]) -> Tuple[int, int]:
    """盤面上の黒白コマ数を返す (black, white)"""
    b = sum(1 for row in board for c in row if c == "B")
    w = sum(1 for row in board for c in row if c == "W")
    return b, w

def is_board_full(board: List[List[str]]) -> bool:
    """空きマスが無ければ True"""
    return all(c != "." for row in board for c in row)

def winner_from_counts(black_cnt: int, white_cnt: int) -> str:
    """勝者を 'B'/'W'/'D' で返す（D=引き分け）"""
    if black_cnt > white_cnt:
        return "B"
    if white_cnt > black_cnt:
        return "W"
    return "D"

def next_consecutive_passes(cur: int, last_move: str) -> int:
    """
    連続パス数を更新する。
    last_move: "pass" なら +1、それ以外なら 0 に戻す
    """
    mv = (last_move or "").strip().lower()
    if mv == "pass":
        return int(cur) + 1
    return 0

def is_game_over(board: List[List[str]], consecutive_passes: int) -> bool:
    """
    終局条件（今回の仕様）
      - 盤面が埋まる
      - 二重パス（連続2回パス）
    """
    return is_board_full(board) or int(consecutive_passes) >= 2

# ===== 評価エンジン用の定数・重み =====
black, white, legal, vacant = 0, 1, 2, 3

# 評価値のスケーリングと重み
# Cell weights are based on the approach described in:
# https://note.com/nyanyan_cubetech/n/n17c169271832
# https://github.com/Nyanyan/OthelloAI_Textbook/blob/main/cell_evaluation.hpp
SC_W = 64.0
CELL_WEIGHT = [
    [2714,  147,   69,  -18,  -18,   69,  147, 2714],
    [ 147, -577, -186, -153, -153, -186, -577,  147],
    [  69, -186, -379, -122, -122, -379, -186,   69],
    [ -18, -153, -122, -169, -169, -122, -153,  -18],
    [ -18, -153, -122, -169, -169, -122, -153,  -18],
    [  69, -186, -379, -122, -122, -379, -186,   69],
    [ 147, -577, -186, -153, -153, -186, -577,  147],
    [2714,  147,   69,  -18,  -18,   69,  147, 2714],
]

class othello:
    """evaluate_moves_for_board から呼ぶ最小限の評価エンジン"""

    def __init__(self):
        # 盤面 0:黒 1:白 2:合法手 3:空き
        self.grid = [[vacant for _ in range(HW)] for _ in range(HW)]
        self.player = black  # 直後に上書きされる想定

    # 合法手を grid 上にマーキング（legal）し、少なくとも1手あるか返す
    def check_legal(self) -> bool:
        # 既存マークを消す
        for y in range(HW):
            for x in range(HW):
                if self.grid[y][x] == legal:
                    self.grid[y][x] = vacant

        have_legal = False
        me = self.player
        for y in range(HW):
            for x in range(HW):
                if self.grid[y][x] != vacant:
                    continue
                ok = False
                for dy, dx in DIRS:
                    ny, nx = y + dy, x + dx
                    seen_opp = False
                    while inside(ny, nx) and self.grid[ny][nx] not in (vacant, legal):
                        if self.grid[ny][nx] != me:
                            seen_opp = True
                            ny += dy; nx += dx
                        else:
                            if seen_opp:
                                ok = True
                            break
                if ok:
                    self.grid[y][x] = legal
                    have_legal = True
        return have_legal

    def legal_moves(self):
        return [(y, x) for y in range(HW) for x in range(HW) if self.grid[y][x] == legal]

    def move(self, y: int, x: int) -> bool:
        if not inside(y, x) or self.grid[y][x] != legal:
            return False
        me = self.player
        flipped_any = False
        # 8方向に反転
        for dy, dx in DIRS:
            ny, nx = y + dy, x + dx
            path = []
            while inside(ny, nx) and self.grid[ny][nx] not in (vacant, legal):
                if self.grid[ny][nx] != me:
                    path.append((ny, nx))
                    ny += dy; nx += dx
                else:
                    if path:
                        for py, px in path:
                            self.grid[py][px] = me
                        flipped_any = True
                    break
        # 着手を置く
        self.grid[y][x] = me
        # 手番交代
        self.player = white if me == black else black
        return flipped_any

    def evaluate(self) -> float:
        # 盤面スコア（黒プラス、白マイナス）
        s = 0
        for y in range(HW):
            for x in range(HW):
                if self.grid[y][x] == black:
                    s += CELL_WEIGHT[y][x]
                elif self.grid[y][x] == white:
                    s -= CELL_WEIGHT[y][x]
        # 手番視点に合わせる
        if self.player == white:
            s = -s
        s = s / 256.0
        # クリップ
        if s > SC_W: s = SC_W
        if s < -SC_W: s = -SC_W
        return float(s)

    def _negamax_value(self, pos: "othello", depth: int) -> float:
        if depth <= 0:
            return pos.evaluate()

        pos.check_legal()
        mv = pos.legal_moves()
        if not mv:
            # パス処理
            import copy
            passed = copy.deepcopy(pos)
            passed.player = white if pos.player == black else black
            passed.check_legal()
            if not passed.legal_moves():
                return pos.evaluate()  # 終局相当
            return - self._negamax_value(passed, depth - 1)

        best = float("-inf")
        import copy
        for (y, x) in mv:
            nxt = copy.deepcopy(pos)
            nxt.move(y, x)  # 手番入れ替わる
            val = - self._negamax_value(nxt, depth - 1)
            if val > best:
                best = val
        return best

    def evaluate_if_play_depth(self, y: int, x: int, depth: int = 2) -> float | None:
        if not inside(y, x) or self.grid[y][x] != legal:
            return None
        import copy
        tmp = copy.deepcopy(self)
        if not tmp.move(y, x):
            return None
        d = max(1, int(depth))
        return - self._negamax_value(tmp, d - 1)

# --- 追加API: 文字盤面 + 手番 を受け取り、各合法手の評価値を返す ---
def evaluate_moves_for_board(board: List[List[str]], player_chr: str, depth: int = 2):
    """
    入力:
      board: 8x8 の文字盤面 [['.', 'B', 'W', ...], ...]
      player_chr: 'B' or 'W' （いま打つ側）
      depth: 先読みの深さ（>=1）
    出力:
      dict: {"c3": +0.23, "f2": -1.29, ...}  （現手番視点で大きいほど良い）
    """
    chr_to_cell = {'.': vacant, 'B': black, 'W': white}
    pos = othello()
    # 文字盤面 -> 数値盤面へ
    for y in range(HW):
        for x in range(HW):
            pos.grid[y][x] = chr_to_cell.get(board[y][x], vacant)
    pos.player = black if player_chr == 'B' else white

    pos.check_legal()
    moves = pos.legal_moves()
    if not moves:
        return {}

    results = {}
    for (y, x) in moves:
        val = pos.evaluate_if_play_depth(y, x, depth=max(1, depth))
        results[coord(y, x)] = round(val, 2) if val is not None else None
    return results

def evaluate_position(board: List[List[str]], player_chr: str) -> float:
    """現在局面を手番視点で評価（+良い / -悪い）。"""
    chr_to_cell = {'.': vacant, 'B': black, 'W': white}
    pos = othello()
    for y in range(HW):
        for x in range(HW):
            pos.grid[y][x] = chr_to_cell.get(board[y][x], vacant)
    pos.player = black if player_chr == 'B' else white
    return float(pos.evaluate())
