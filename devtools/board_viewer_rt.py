# board_viewer_rt.py
from __future__ import annotations
import os, json, threading, subprocess, sys   # ★ os を追加！
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from pathlib import Path
import tkinter as tk
from board_panel import BoardPanel

class RTBoardWindow(tk.Tk):
    def __init__(self, cmd=None):
        super().__init__()
        self.title("Othello Board (STATE watcher)")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.panel = BoardPanel(self)
        self.panel.pack(fill="both", expand=True)

        # --- realtime_othello.py をサブプロセス起動 ---
        if cmd is None:
            # プロジェクト直下の realtime_othello.py を呼び出す
            py = sys.executable
            rt = Path(__file__).resolve().parent.parent / "realtime_othello.py"  # ★ 修正: 上の階層を参照
            cmd = [py, str(rt)]

        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE,
            text=True, bufsize=1, universal_newlines=True
        )

        # 標準出力監視スレッド
        self.t_reader = threading.Thread(target=self._reader, daemon=True)
        self.t_reader.start()

    # ---- サブプロセスの出力を読む ----
    def _reader(self):
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            msg = line.strip()
            if msg.startswith("STATE:"):
                payload = msg[len("STATE:"):].strip()
                try:
                    state = json.loads(payload)
                except Exception:
                    continue
                # GUIスレッドで更新
                self.after(0, self.panel.update_from_state, state)

    def on_close(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
        except Exception:
            pass
        self.destroy()

if __name__ == "__main__":
    app = RTBoardWindow()
    app.mainloop()
