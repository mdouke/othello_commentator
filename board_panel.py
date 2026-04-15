# board_panel.py
import tkinter as tk
from typing import List, Optional, Iterable

CELL = 60
PAD = 20
N = 8

class BoardPanel(tk.Frame):
    """8x8 盤面を描画するだけの純粋なウィジェット（評価値オーバーレイ対応）"""
    def __init__(self, master=None):
        super().__init__(master, bg="darkgreen")
        w = h = N * CELL + PAD * 2
        self.canvas = tk.Canvas(self, width=w, height=h, bg="darkgreen", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.board = [["." for _ in range(N)] for _ in range(N)]
        self.legal: list[tuple[int, int]] = []
        self.evals: dict[str, float] = {}  # ← 追加: 合法手の評価値 {'c5': 0.23, ...}

        self._draw_grid()
        self.redraw()

    # ========== public API ==========
    def set_board(self, board: List[List[str]]) -> None:
        self.board = board
        self.redraw()

    def set_legal(self, legal: Optional[Iterable[tuple[int, int]]]) -> None:
        self.legal = list(legal or [])
        self.redraw()

    def update_from_state(self, state: dict) -> None:
        """STATE: の JSON をそのまま渡せる柔軟なアップデータ"""
        if "board" in state:
            self.board = state["board"]

        # 合法手は "moves"（例: ["c3","d3"]）でも、(r,c) の配列でも対応
        legal = []
        if "moves" in state:
            for m in state["moves"]:
                if isinstance(m, str) and len(m) >= 2 and m[0].isalpha() and m[1].isdigit():
                    r, c = self._coord_to_rc(m)
                    if 0 <= r < 8 and 0 <= c < 8:
                        legal.append((r, c))
                elif isinstance(m, (list, tuple)) and len(m) == 2:
                    legal.append((int(m[0]), int(m[1])))
                elif isinstance(m, dict) and "r" in m and "c" in m:
                    legal.append((int(m["r"]), int(m["c"])))
        self.legal = legal

        # ★ 追加: 評価値（辞書）を受け取る
        #   例 {"c5": 0.23, "d3": 0.60, "f2": -1.29}
        raw_evals = state.get("evals", {}) or {}
        self.evals = {str(k).lower(): v for (k, v) in raw_evals.items()}

        self.redraw()

    # ========== drawing ==========
    def _draw_grid(self):
        self.canvas.delete("grid")
        self.canvas.delete("coord")

        # 盤面背景（濃い緑）
        self.canvas.create_rectangle(PAD, PAD, PAD + N*CELL, PAD + N*CELL,
                                     fill="#2e7d32", outline="", tags="grid")

        # マス目
        for i in range(N + 1):
            x = PAD + i * CELL
            y = PAD + i * CELL
            self.canvas.create_line(PAD, y, PAD + N * CELL, y, fill="#0d3b20", tags="grid")
            self.canvas.create_line(x, PAD, x, PAD + N * CELL, fill="#0d3b20", tags="grid")

        # === 座標（上: a-h / 左: 1-8）===
        label_font_size = max(10, int(CELL * 0.28))
        label_font = ("Menlo", label_font_size, "bold")
        label_fill = "#e8f5e9"

        # 列ラベル（a-h）: 上余白の「上下中央」
        top_y = PAD / 2
        for c in range(N):
            x = PAD + c * CELL + CELL / 2
            ch = chr(ord('a') + c)
            self.canvas.create_text(
                x, top_y, text=ch,
                fill=label_fill, font=label_font, tags="coord"
            )

        # 行ラベル（1-8）: 左余白の「左右中央」
        left_x = PAD / 2
        for r in range(N):
            y = PAD + r * CELL + CELL / 2
            self.canvas.create_text(
                left_x, y, text=str(r + 1),
                fill=label_fill, font=label_font, tags="coord"
            )


    def redraw(self):
        self.canvas.delete("stone")
        self.canvas.delete("legal")
        self.canvas.delete("eval")
        self.canvas.delete("eval_bg")

        # stones
        for r in range(N):
            for c in range(N):
                v = self.board[r][c]
                if v not in ("B", "W"):
                    continue
                x, y = self._cell_center(r, c)
                r_outer = int(CELL * 0.40)
                r_inner = int(CELL * 0.36)
                # 影
                self.canvas.create_oval(x - r_outer, y - r_outer + 1, x + r_outer, y + r_outer + 1,
                        fill="#222222", outline="", tags="stone")

                # 石本体
                fill = "#111" if v == "B" else "#eee"
                self.canvas.create_oval(x-r_outer, y-r_outer, x+r_outer, y+r_outer,
                                        fill=fill, outline="#222", tags="stone")
                # 白石に軽いハイライト
                if v == "W":
                    self.canvas.create_oval(x-r_inner, y-r_inner, x+r_inner, y+r_inner,
                                            outline="#fff", width=1, tags="stone")

        # legal moves + eval overlays
        font_size = max(9, int(CELL * 0.28))   # セル比で文字サイズ
        halo_pad  = max(2, int(CELL * 0.10))   # 背景帯の余白
        pin_r     = max(3, int(CELL * 0.12))   # 合法手ピン半径

        for (r, c) in self.legal:
            x, y = self._cell_center(r, c)

            # ① 合法手マーカー（小さいピン）
            self.canvas.create_oval(x - pin_r, y - pin_r, x + pin_r, y + pin_r,
                                    fill="#88ccff", outline="", tags="legal")

            # ② 評価値テキスト（あれば描く）
            sq = self._rc_to_coord(r, c)  # "c5" 形式へ
            val = self.evals.get(sq) if self.evals else None
            if val is None:
                self.canvas.create_oval(x-6, y-6, x+6, y+6, fill="#ffeb3b", outline="", tags="legal")
                continue

            # カラーリング（今は同色。好みで色分け可）
            color = "#444444"

            text = f"{val:+.2f}"
            tx, ty = x, y + CELL * 0.30  # セル中心の少し下に配置

            # 背景ハイライト（帯）のために bbox を計測
            tmp_id = self.canvas.create_text(tx, ty, text=text, font=("Menlo", font_size, "bold"),
                                             fill=color, state="hidden")
            bbox = self.canvas.bbox(tmp_id)
            self.canvas.delete(tmp_id)

            if bbox:
                x0, y0, x1, y1 = bbox
                x0 -= halo_pad; x1 += halo_pad
                y0 -= int(halo_pad * 0.6); y1 += int(halo_pad * 0.6)
                self.canvas.create_rectangle(x0, y0, x1, y1,
                                             fill="#ffffff", outline="#dddddd", tags=("eval_bg",))

            # テキスト本体（背景の上に）
            self.canvas.create_text(tx, ty, text=text, fill=color,
                                    font=("Menlo", font_size, "bold"), tags="eval")

    # ========== utils ==========
    def _cell_center(self, r: int, c: int):
        x = PAD + c * CELL + CELL/2
        y = PAD + r * CELL + CELL/2
        return x, y

    @staticmethod
    def _coord_to_rc(move: str) -> tuple[int, int]:
        # "a1".."h8" 前提だが、列は1文字/行は残り全部を読む
        col_ch = move[0].lower()
        row_str = move[1:]           # ← 2桁にも対応
        col = ord(col_ch) - ord("a")
        row = int(row_str) - 1
        return row, col

    @staticmethod
    def _rc_to_coord(r: int, c: int) -> str:
        return f"{chr(ord('a') + c)}{r + 1}"  # 小文字固定
