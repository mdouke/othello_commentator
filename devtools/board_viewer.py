# board_viewer.py
import tkinter as tk
from typing import List, Optional

CELL_SIZE = 60
BOARD_SIZE = 8
PADDING = 20


class BoardViewer(tk.Toplevel):
    def __init__(self, master=None):
        super().__init__(master)
        self.title("Othello Board Viewer")
        self.canvas = tk.Canvas(
            self, width=BOARD_SIZE * CELL_SIZE + PADDING * 2,
            height=BOARD_SIZE * CELL_SIZE + PADDING * 2, bg="darkgreen"
        )
        self.canvas.pack()
        self.board_state = [["." for _ in range(8)] for _ in range(8)]
        self.legal_moves: Optional[List[tuple[int, int]]] = None
        self.draw_board()

    def draw_board(self):
        self.canvas.delete("all")

        # マス目を描く
        for i in range(BOARD_SIZE + 1):
            x = PADDING + i * CELL_SIZE
            y = PADDING + i * CELL_SIZE
            self.canvas.create_line(PADDING, y, PADDING + BOARD_SIZE * CELL_SIZE, y, fill="black")
            self.canvas.create_line(x, PADDING, x, PADDING + BOARD_SIZE * CELL_SIZE, fill="black")

        # コマを描く
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                cell = self.board_state[r][c]
                x = PADDING + c * CELL_SIZE + CELL_SIZE / 2
                y = PADDING + r * CELL_SIZE + CELL_SIZE / 2

                if cell == "B":
                    self._draw_disc(x, y, "black")
                elif cell == "W":
                    self._draw_disc(x, y, "white")

        # 合法手を描く（灰色の点）
        if self.legal_moves:
            for (r, c) in self.legal_moves:
                x = PADDING + c * CELL_SIZE + CELL_SIZE / 2
                y = PADDING + r * CELL_SIZE + CELL_SIZE / 2
                self.canvas.create_oval(
                    x - 8, y - 8, x + 8, y + 8, fill="gray60", outline=""
                )

    def _draw_disc(self, x, y, color):
        self.canvas.create_oval(
            x - 25, y - 25, x + 25, y + 25, fill=color, outline="black"
        )

    def update_board(self, board: List[List[str]], legal_moves: Optional[List[tuple[int, int]]] = None):
        """boardは8x8の'.','B','W'の2次元リスト"""
        self.board_state = board
        self.legal_moves = legal_moves
        self.draw_board()


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()  # メインウィンドウ非表示
    viewer = BoardViewer(root)

    # デモ用：中央に白黒を配置し、合法手を3つ表示
    board = [["." for _ in range(8)] for _ in range(8)]
    board[3][3] = "W"
    board[3][4] = "B"
    board[4][3] = "B"
    board[4][4] = "W"
    viewer.update_board(board, legal_moves=[(2, 3), (3, 2), (4, 5)])
    viewer.mainloop()
