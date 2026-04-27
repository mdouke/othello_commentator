from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional
from datetime import datetime
from othello_commentator.ui.board_widget import BoardPanel


class ChatWindow(tk.Tk):
    def __init__(self, providers: dict[str, any]):
        super().__init__()
        self.title("Othello Commentator")
        self.geometry("1200x720")  # 横幅少し広めに

        self._on_start: Optional[Callable[[], None]] = None
        self._on_hand: Optional[Callable[[bool], None]] = None
        self._on_send_prompt: Optional[Callable[[], None]] = None
        self._on_flip_change = None
        self._on_depth_change: Optional[Callable[[int], None]] = None
        self.on_calib = None
        self._on_turn_change: Optional[Callable[[str], None]] = None
        # ★履歴選択UI用
        self._on_pick_snapshot: Optional[Callable[[int], None]] = None
        self._on_calib: Optional[Callable[[bool], None]] = None  # True=CALIB ON, False=CALIB OFF
        self._calib_mode = False

        self.provider_names = list(providers.keys())
        self.current_provider_name = tk.StringVar(value=self.provider_names[0])
        self.style_var = tk.StringVar(value="感情的な実況者のような")

        # 反転トグル（初期値は必要に応じて True/False に）
        # 追加: __init__ 内でロック状態フラグ
        self._flip_locked = False
        self.flip_h_var = tk.BooleanVar(value=True)  # 左右
        self.flip_v_var = tk.BooleanVar(value=True)  # 上下

        self.depth_var = tk.IntVar(value=2)  # 探索深さ

        # グラフ用データ（(move_no, eval) の配列）
        self.eval_points: list[tuple[int, float]] = []
        self.eval_points_turn: list[tuple[int, float]] = []
        self.turn_segments: list[tuple[int, int]] = []
        self.max_moves = 60  # 横軸 0..60 固定

        # ★形成推移をプロンプトに載せるかどうかのフラグ
        self.use_trend_var = tk.BooleanVar(value=False)

        # ★先手/後手（B/W）。デフォルト黒
        self.start_turn_var = tk.StringVar(value="B")

        self._build_ui()
    
    def set_on_depth_change(self, cb: Callable[[int], None]) -> None:
        self._on_depth_change = cb

    def set_on_pick_snapshot(self, cb: Callable[[int], None]) -> None:
        """履歴選択UIで『この盤面で再開』が押されたときに呼ぶ（indexが渡る）"""
        self._on_pick_snapshot = cb

    def set_on_turn_change(self, cb: Callable[[str], None]) -> None:
        """先手/後手トグル変更時に呼ぶ（PREVIEW:TURN=... 用）"""
        self._on_turn_change = cb

    def get_start_turn(self) -> str:
        """START送信時に参照する（START:TURN=... 用）"""
        v = (self.start_turn_var.get() or "B").strip().upper()
        return "W" if v == "W" else "B"

    def _turn_changed(self) -> None:
        if self._on_turn_change is not None:
            self._on_turn_change(self.get_start_turn())

    # --- UI構築（左右2ペイン：左=Notebook / 右=BoardPanel 常設） ---
    def _build_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x")
        # _build_ui 内：チェックボタンを変数に保持
        self.flip_h_cb = ttk.Checkbutton(
            toolbar, text="左右反転", variable=self.flip_h_var, command=self._flip_changed
        )
        self.flip_h_cb.pack(side="left", padx=6, pady=4)

        self.flip_v_cb = ttk.Checkbutton(
            toolbar, text="上下反転", variable=self.flip_v_var, command=self._flip_changed
        )
        self.flip_v_cb.pack(side="left", padx=6, pady=4)

        # === 先読み手数 ===
        depth_box = ttk.Frame(toolbar)
        depth_box.pack(side="left", padx=(0,12))
        ttk.Label(depth_box, text="先読み").pack(side="left")

        spin = tk.Spinbox(
            depth_box, from_=1, to=8, textvariable=self.depth_var, width=3,
            command=self._on_depth_spin_changed,  # ← 矢印操作時に呼ばれる
            wrap=True, state="readonly", justify="center"
        )
        spin.pack(side="left", padx=4)

        # ★形成推移を渡すかどうかのチェックボックス
        chk_trend = ttk.Checkbutton(
            toolbar,
            text="形成推移をLLMに渡す",
            variable=self.use_trend_var
        )
        chk_trend.pack(side="left", padx=4)

        # ★先手/後手トグル（ここを「形成推移をLLMに渡す」の後に置く）
        turn_box = ttk.Frame(toolbar)
        turn_box.pack(side="left", padx=(8, 0))
        ttk.Label(turn_box, text="先手").pack(side="left")

        rb_b = ttk.Radiobutton(
            turn_box, text="黒", value="B",
            variable=self.start_turn_var,
            command=self._turn_changed
        )
        rb_b.pack(side="left", padx=(6, 0))

        rb_w = ttk.Radiobutton(
            turn_box, text="白", value="W",
            variable=self.start_turn_var,
            command=self._turn_changed
        )
        rb_w.pack(side="left", padx=(6, 0))

        # ※直接入力を許すなら readonly を外し、以下のバインドを併用
        spin.bind("<Return>", lambda e: self._on_depth_spin_changed())
        spin.bind("<FocusOut>", lambda e: self._on_depth_spin_changed())

        # 水平ペインで2分割
        self.pane = ttk.Panedwindow(self, orient="horizontal")
        self.pane.pack(fill="both", expand=True)

        # 左ペイン（上下分割用のコンテナ）
        self.left = tk.Frame(self.pane)
        self.pane.add(self.left, weight=3)  # 左を少し広く

        # 左ペイン内：上下に分割する Panedwindow（縦方向）
        self.left_pane = ttk.Panedwindow(self.left, orient="vertical")
        self.left_pane.pack(fill="both", expand=True)

        # 上段（従来のNotebookをここに入れる）
        self.left_top = tk.Frame(self.left_pane)
        self.left_pane.add(self.left_top, weight=3)   # 上を広め

        # 下段（あとでグラフを入れる）
        self.left_bottom = tk.Frame(self.left_pane)
        self.left_pane.add(self.left_bottom, weight=1)  # 下は最初は小さめ

        # 右ペイン（BoardPanel 常設）
        self.right = tk.Frame(self.pane)
        self.pane.add(self.right, weight=2)

        # --- Notebook（左_上段） ---
        self.notebook = ttk.Notebook(self.left_top)
        self.tab_chat = tk.Frame(self.notebook)
        self.tab_logs = tk.Frame(self.notebook)
        self.tab_status = tk.Frame(self.notebook)
        self.notebook.add(self.tab_chat, text="Chat")
        self.notebook.add(self.tab_logs, text="Logs")
        self.notebook.add(self.tab_status, text="Status")
        self.notebook.pack(fill="both", expand=True)

        # --- Chatタブ ---
        self.chat_text = tk.Text(self.tab_chat, wrap="word")
        self.chat_text.pack(fill="both", expand=True, padx=8, pady=8)

        # --- Logsタブ ---
        self.log_text = tk.Text(self.tab_logs, height=20, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

        # --- Statusタブ ---
        s = self.tab_status
        row = 0
        tk.Label(s, text="状態:").grid(row=row, column=0, sticky="w", padx=4, pady=4)
        self.status_var = tk.StringVar(value="待機中 ...")
        tk.Label(s, textvariable=self.status_var).grid(row=row, column=1, sticky="w", padx=4, pady=4)
        row += 1

        tk.Label(s, text="LLM:").grid(row=row, column=0, sticky="e", padx=4, pady=4)
        self.provider_combo = ttk.Combobox(
            s, values=self.provider_names, textvariable=self.current_provider_name, state="readonly"
        )
        self.provider_combo.grid(row=row, column=1, sticky="w", padx=4, pady=4)
        row += 1

        tk.Label(s, text="リアクション文言:").grid(row=row, column=0, sticky="e", padx=4, pady=4)
        tk.Entry(s, textvariable=self.style_var, width=40).grid(row=row, column=1, sticky="w", padx=4, pady=4)
        row += 1

        self.btn_start = tk.Button(s, text="OKで開始", command=self._click_start)
        self.btn_start.grid(row=row, column=0, padx=4, pady=4)

        self.btn_pause = tk.Button(s, text="一時停止", command=lambda: self._click_hand(False))
        self.btn_pause.grid(row=row, column=1, sticky="w", padx=4, pady=4)
        self.btn_resume = tk.Button(s, text="再開", command=lambda: self._click_hand(True))
        self.btn_resume.grid(row=row, column=2, sticky="w", padx=4, pady=4)
        row += 1

        # --- キャリブやり直し（Pause中に調整したいとき） ---
        tk.Label(s, text="キャリブ:").grid(row=row, column=0, sticky="e", padx=4, pady=4)
        self.calib_status_var = tk.StringVar(value="通常")
        tk.Label(s, textvariable=self.calib_status_var).grid(row=row, column=1, sticky="w", padx=4, pady=4)
        row += 1

        self.btn_calib_on = tk.Button(s, text="キャリブやり直し開始", command=lambda: self._click_calib(True))
        self.btn_calib_on.grid(row=row, column=0, sticky="w", padx=4, pady=4)
        self.btn_calib_off = tk.Button(s, text="キャリブ完了（戻る）", command=lambda: self._click_calib(False), state="disabled")
        self.btn_calib_off.grid(row=row, column=1, sticky="w", padx=4, pady=4)
        row += 1

        # =========================
        #  履歴選択UI（Pause中に「再開したい盤面」を選ぶ）
        # =========================
        sep = ttk.Separator(s, orient="horizontal")
        sep.grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=(10, 8))
        row += 1
        tk.Label(s, text="再開する盤面（履歴）:").grid(row=row, column=0, sticky="w", padx=4, pady=(0, 4))
        row += 1

        # Listbox + Scrollbar
        list_frame = tk.Frame(s)
        list_frame.grid(row=row, column=0, columnspan=3, sticky="nsew", padx=4, pady=(0, 6))

        self.snapshot_list = tk.Listbox(list_frame, height=10, exportselection=False)
        sb = tk.Scrollbar(list_frame, orient="vertical", command=self.snapshot_list.yview)
        self.snapshot_list.configure(yscrollcommand=sb.set)

        self.snapshot_list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        row += 1
        # 決定ボタン
        self.btn_pick_snapshot = tk.Button(s, text="この盤面で再開（一致待ち）", command=self._click_pick_snapshot)
        self.btn_pick_snapshot.grid(row=row, column=0, sticky="w", padx=4, pady=(0, 6))

        # 一致状況ラベル
        self.sync_status_var = tk.StringVar(value="（未選択）")
        tk.Label(s, text="一致状況:").grid(row=row, column=1, sticky="e", padx=4, pady=(0, 6))
        tk.Label(s, textvariable=self.sync_status_var).grid(row=row, column=2, sticky="w", padx=4, pady=(0, 6))
        row += 1
        # レイアウト：Statusタブ内でListboxが伸びるように
        # 初期状態のUI反映
        self._apply_calib_ui_state()
        s.grid_rowconfigure(row - 3, weight=1)  # list_frameの行（ざっくり）

        for c in range(3):
            s.grid_columnconfigure(c, weight=1)

        # --- 左 下段：評価履歴（手数, 黒視点評価）
        self.eval_panel = tk.Frame(self.left_bottom)
        self.eval_panel.pack(fill="both", expand=True, padx=8, pady=8)

        # 最新表示
        top_row = tk.Frame(self.eval_panel)
        top_row.pack(fill="x")
        tk.Label(top_row, text="手数:").pack(side="left")
        self.move_count_var = tk.StringVar(value="0")
        tk.Label(top_row, textvariable=self.move_count_var, width=4, anchor="w").pack(side="left", padx=(4, 12))

        tk.Label(top_row, text="黒からみた評価値:").pack(side="left")
        self.last_black_eval_var = tk.StringVar(value="-")
        tk.Label(top_row, textvariable=self.last_black_eval_var, width=10, anchor="w").pack(side="left", padx=(4, 0))

        # グラフキャンバス（0..60 の横軸を固定）
        self.eval_canvas = tk.Canvas(self.eval_panel, height=240, bg="white",
                                    highlightthickness=1, highlightbackground="#cccccc")
        self.eval_canvas.pack(fill="both", expand=True, pady=(8, 0))

        

        # リサイズ時に再描画
        self.eval_canvas.bind("<Configure>", lambda e: self._redraw_eval_graph())

        # 履歴リスト（例: " 12 : +0.45"）
        # self.eval_list = tk.Listbox(self.eval_panel, height=8)
        # self.eval_list.pack(fill="both", expand=True, pady=(8, 0))

        # --- 右ペイン：BoardPanel 常設 ---
        self.board_container = tk.Frame(self.right, bg="#d0d0d0")  # 灰色背景
        self.board_container.pack(fill="both", expand=True)

        # ボード周囲に余白を確保して配置（padで緑が少しはみ出すように）
        self.board_frame = tk.Frame(self.board_container, bg="darkgreen", padx=2, pady=2)
        self.board_frame.pack(expand=True, anchor="center")

        # BoardPanel（盤面本体）
        self.board_panel = BoardPanel(self.board_frame)
        self.board_panel.pack()

        # ウィンドウ全体のリサイズ挙動を少し安定させる（任意）
        self.update_idletasks()
        try:
            # 右ペインの初期幅を盤面が美しく見える程度に
            self.pane.sashpos(0, int(self.winfo_width() * 0.50))
        except Exception:
            pass

        def _enforce_min_width(event=None):
            # 右ペインが狭すぎる場合にサッシュを戻す
            try:
                pos = self.pane.sashpos(0)
                if pos > self.winfo_width() - 520:  # 右が520px未満にならないように
                    self.pane.sashpos(0, self.winfo_width() - 520)
            except Exception:
                pass

        self.pane.bind("<Configure>", _enforce_min_width)

        # === 追加: 右下に情報パネル ===
        self.info_frame = tk.Frame(self.right)
        self.info_frame.pack(fill="x", side="bottom", padx=8, pady=8)

        tk.Label(self.info_frame, text="手番:").grid(row=0, column=0, sticky="w")
        self.turn_var = tk.StringVar(value="-")
        tk.Label(self.info_frame, textvariable=self.turn_var).grid(row=0, column=1, sticky="w", padx=(4, 16))

        tk.Label(self.info_frame, text="手番の盤面評価値:").grid(row=0, column=2, sticky="w")
        self.pos_eval_var = tk.StringVar(value="-")
        tk.Label(self.info_frame, textvariable=self.pos_eval_var, justify="left").grid(row=0, column=3, sticky="w")

        # --- 追加：黒白のコマ数 ---
        tk.Label(self.info_frame, text="黒:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.black_count_var = tk.StringVar(value="-")
        tk.Label(self.info_frame, textvariable=self.black_count_var).grid(row=1, column=1, sticky="w", padx=(4, 16), pady=(6, 0))

        tk.Label(self.info_frame, text="白:").grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.white_count_var = tk.StringVar(value="-")
        tk.Label(self.info_frame, textvariable=self.white_count_var).grid(row=1, column=3, sticky="w", padx=(4, 0), pady=(6, 0))

        for c in range(4):
            self.info_frame.grid_columnconfigure(c, weight=1)
        
    def _on_depth_spin_changed(self):
        # ← 追加：安全に丸めて通知
        try:
            val = int(self.depth_var.get())
        except Exception:
            val = 2
        val = max(1, min(8, val))
        self.depth_var.set(val)
        if self._on_depth_change:
            self._on_depth_change(val)

    # --- 外部から盤面を更新するAPI（main.py から呼ぶ） ---
    def update_board(self, state: dict):
        # state 例: {"turn":"W","board":[...],"moves":["c5","d3"],"evals":{"c5":0.23,"d3":0.60}}
        if not hasattr(self, "board_panel"):
            return

        # 1) BoardPanel へ丸ごと渡す（BoardPanel側で evals を使って描画）
        self.board_panel.update_from_state(state)

        # 2) 右下の情報パネル更新
        turn = state.get("turn")
        if turn in ("B", "W"):
            self.turn_var.set("●(B)" if turn == "B" else "○(W)")
        else:
            self.turn_var.set("-")

        pos_eval = state.get("pos_eval", None)
        if isinstance(pos_eval, (int, float)):
            self.pos_eval_var.set(f"{pos_eval:+.2f}")
        else:
            self.pos_eval_var.set("-")

    def set_piece_counts(self, b: int, w: int) -> None:
        if hasattr(self, "black_count_var"):
            self.black_count_var.set(str(b))
        if hasattr(self, "white_count_var"):
            self.white_count_var.set(str(w))


    # --- コールバック設定 ---
    def set_on_start(self, cb: Callable[[], None]):
        self._on_start = cb

    def set_on_hand(self, cb: Callable[[bool], None]):
        self._on_hand = cb

    def set_on_send_prompt(self, cb: Callable[[], None]):
        self._on_send_prompt = cb

    # --- 内部イベント ---
    def _click_start(self):
        if self._on_start:
            self._on_start()

    def _click_hand(self, on: bool):
        if self._on_hand:
            self._on_hand(on)
    
    def _apply_calib_ui_state(self) -> None:
        """キャリブ中は再開系の操作を事故防止のため無効化する。"""
        if hasattr(self, "btn_pick_snapshot"):
            self.btn_pick_snapshot.configure(state=("disabled" if self._calib_mode else "normal"))
        if hasattr(self, "btn_resume"):
            self.btn_resume.configure(state=("disabled" if self._calib_mode else "normal"))
        if hasattr(self, "btn_calib_on"):
            self.btn_calib_on.configure(state=("disabled" if self._calib_mode else "normal"))
        if hasattr(self, "btn_calib_off"):
            self.btn_calib_off.configure(state=("normal" if self._calib_mode else "disabled"))
        if hasattr(self, "calib_status_var"):
            self.calib_status_var.set("キャリブ中" if self._calib_mode else "通常")

    def _click_calib(self, on: bool):
        # UI先行で切替（callbackが無くても見た目は動く）
        self._calib_mode = bool(on)
        self._apply_calib_ui_state()
        if self._on_calib:
            self._on_calib(bool(on))
    
    def set_on_calib(self, cb):
        """Pause中のキャリブやり直し（CALIB:ON/OFF）"""
        self._on_calib = cb

    # --- 外部API ---
    def append_log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_status(self, text: str):
        self.status_var.set(text)

    # =========================
    #  履歴選択UI：外部API（main.py から使う）
    # =========================
    def set_snapshot_choices(self, labels: list[str], select_index: int | None = None) -> None:
        """
        履歴候補の表示を更新する（Pauseしたタイミングで main から呼ぶ想定）
        labels: Listboxに表示する文字列配列（新しい順/古い順はmain側の方針に合わせる）
        select_index: 初期選択（Noneなら選択しない）
        """
        if not hasattr(self, "snapshot_list"):
            return
        try:
            self.snapshot_list.delete(0, tk.END)
            for t in labels:
                self.snapshot_list.insert(tk.END, t)
            if select_index is not None and 0 <= select_index < len(labels):
                self.snapshot_list.selection_clear(0, tk.END)
                self.snapshot_list.selection_set(select_index)
                self.snapshot_list.see(select_index)
        except Exception:
            pass

    def get_selected_snapshot_index(self) -> int | None:
        if not hasattr(self, "snapshot_list"):
            return None
        try:
            sel = self.snapshot_list.curselection()
            if not sel:
                return None
            return int(sel[0])
        except Exception:
            return None

    def set_sync_status(self, text: str) -> None:
        """一致状況の表示（LOCKED_SYNC中に main から更新する想定）"""
        if hasattr(self, "sync_status_var"):
            self.sync_status_var.set(text)

    def set_resume_enabled(self, enabled: bool) -> None:
        """Resumeボタンの有効/無効（LOCKED_SYNC中は無効化する想定）"""
        try:
            self.btn_resume.configure(state=("normal" if enabled else "disabled"))
        except Exception:
            pass

    def set_pick_enabled(self, enabled: bool) -> None:
        """『この盤面で再開』ボタンの有効/無効（必要に応じてmainから制御）"""
        try:
            self.btn_pick_snapshot.configure(state=("normal" if enabled else "disabled"))
        except Exception:
            pass

    def _click_pick_snapshot(self):
        """
        履歴選択UIの決定ボタン。
        選択indexを main に返す（main側でLOCKED_SYNCへ移行してSYNCを開始する想定）
        """
        if self._on_pick_snapshot is None:
            return
        idx = self.get_selected_snapshot_index()
        if idx is None:
            self.append_log("[ui] 履歴が未選択です。Listから選んでください。")
            return
        self._on_pick_snapshot(idx)

    def add_chat_delta(self, s: str):
        """LLM からのトークンを Chat タブに追記"""
        self.chat_text.configure(state="normal")
        self.chat_text.insert("end", s)
        self.chat_text.see("end")
        self.chat_text.configure(state="disabled")

    def current_provider(self) -> str:
        return self.current_provider_name.get()

    def current_style(self) -> str:
        return self.style_var.get()

    # 送信プロンプトを Chat タブに表示
    def add_chat_prompt(self, provider: str, prompt: str) -> None:
        ts = datetime.now().strftime("[%H:%M]")
        try:
            self.chat_text.configure(state="normal")
            self.chat_text.insert(tk.END, f"{ts} Prompt → {provider}:\n{prompt}\n\n")
            self.chat_text.configure(state="disabled")
            self.chat_text.see(tk.END)
        except Exception:
            pass

    def set_on_flip_change(self, cb):
        """main.pyから注入される反転変更コールバック"""
        self._on_flip_change = cb

    def lock_flip_controls(self):
        """OKで開始後は反転トグルを固定"""
        self._flip_locked = True
        try:
            self.flip_h_cb.configure(state="disabled")
            self.flip_v_cb.configure(state="disabled")
        except Exception:
            pass

    def _flip_changed(self):
        # 開始後は無視（UIガード）
        if getattr(self, "_flip_locked", False):
            # 見かけ上の値が変わってしまった場合に備えて元に戻す
            # （ここでは値を維持するだけで十分。必要なら最後に .set() で巻戻しも可）
            return
        if self._on_flip_change:
            self._on_flip_change(self.flip_h_var.get(), self.flip_v_var.get())
    
    # ChatWindow のメソッドとして追加
    def add_eval_point(self, move_no: int, black_eval: float | None, is_turn_end: bool = False):
        """(手数, 黒視点評価) を履歴に追加/更新し、最新表示＋グラフを更新。
        is_turn_end=True のとき、赤系列（ターン終了）にも同じ手数で反映。
        """
        try:
            # 最新ラベル
            self.move_count_var.set(str(move_no))
            self.last_black_eval_var.set("-" if black_eval is None else f"{black_eval:+.2f}")

            # --- 各手系列（青）を「手数で上書き」 ---
            replaced = False
            for i, (m, _) in enumerate(self.eval_points):
                if m == move_no:
                    self.eval_points[i] = (move_no, black_eval)
                    replaced = True
                    break
            if not replaced:
                self.eval_points.append((move_no, black_eval))
            self.eval_points.sort(key=lambda t: t[0])

            # --- ターン終了系列（赤） ---
            if is_turn_end:
                replaced_t = False
                for i, (m, _) in enumerate(self.eval_points_turn):
                    if m == move_no:
                        self.eval_points_turn[i] = (move_no, black_eval)
                        replaced_t = True
                        break
                if not replaced_t:
                    self.eval_points_turn.append((move_no, black_eval))
                self.eval_points_turn.sort(key=lambda t: t[0])

            # グラフ再描画
            self._redraw_eval_graph()
        except Exception:
            pass


    def add_turn_eval_point(self, move_no: int, black_eval: float | None):
        """１ターンが締まった直後に呼ぶ糖衣。内部的には is_turn_end=True で add_eval_point を再利用。"""
        self.add_eval_point(move_no, black_eval, is_turn_end=True)
    
    def add_turn_segment(self, start_move_no: int, end_move_no: int):
        try:
            if start_move_no is None or end_move_no is None:
                return
            if end_move_no < start_move_no:
                return
            self.turn_segments.append((start_move_no, end_move_no))
            self._redraw_eval_graph()
        except Exception:
            pass

    def clear_eval_history(self):
        """履歴と表示を初期化。"""
        try:
            self.eval_points.clear()
            self.eval_points_turn.clear()   # ← 追加
            self.turn_segments.clear()       # ← 追加
            self.move_count_var.set("0")
            self.last_black_eval_var.set("-")
            self._redraw_eval_graph()
        except Exception:
            pass


    def _redraw_eval_graph(self):
        c = self.eval_canvas
        if not c:
            return
        c.delete("all")

        W = c.winfo_width() or 1
        H = c.winfo_height() or 1

        # 余白とタイトル帯
        pad_l, pad_r, pad_t, pad_b = 40, 12, 16, 28
        title_h = 18
        x0, y0 = pad_l, pad_t + title_h
        x1, y1 = W - pad_r, H - pad_b
        if x1 <= x0 or y1 <= y0:
            return

        # ---- データ整形（青：各手 / 赤：ターン終了）----
        data_blue = []
        for m, v in sorted(self.eval_points, key=lambda t: t[0]):
            data_blue.append((m, None if v is None else float(v)))

        data_red = []
        for m, v in sorted(self.eval_points_turn, key=lambda t: t[0]):
            data_red.append((m, None if v is None else float(v)))

        # yスケール（両系列を合算して決定）
        vals = [v for _, v in data_blue if isinstance(v, (int, float))] + \
               [v for _, v in data_red if isinstance(v, (int, float))]
        max_abs = max([abs(v) for v in vals], default=0.0)
        y_max = max(4.0, (int(max_abs * 10 + 5) // 10) / 1.0)
        y_mid = y0 + (y1 - y0) * 0.5
        y_scale = (y1 - y0) / (2.0 * y_max)

        # 枠とゼロ線
        c.create_rectangle(x0, y0, x1, y1, outline="#dddddd", fill="")
        y_zero = y_mid
        c.create_line(x0, y_zero, x1, y_zero, fill="#cccccc")

        # Y目盛
        tick_specs = [
            (-y_max, y1, f"-{y_max:.1f}"),
            (0,      y_zero, "0"),
            (+y_max, y0 + 2, f"+{y_max:.1f}"),
        ]
        for _, y_off, lbl in tick_specs:
            c.create_line(x0 - 4, y_off, x0, y_off, fill="#666666")
            c.create_text(x0 - 6, y_off, text=lbl, anchor="e", fill="#444444", font=("", 9))

        # X目盛
        max_moves = getattr(self, "max_moves", 60) or 60
        for t in range(0, max_moves + 1, 10):
            x = x0 + (x1 - x0) * (t / max_moves)
            c.create_line(x, y1, x, y1 + 4, fill="#666666")
            c.create_text(x, y1 + 6, text=str(t), anchor="n", fill="#444444", font=("", 9))

        # 座標変換
        def to_px(m, v):
            px = x0 + (x1 - x0) * (max(0, min(max_moves, m)) / max_moves)
            py = y_mid - (v * y_scale)
            return px, py

        # --- 青（各手） ---
        prev = None
        for m, v in data_blue:
            if v is None:
                prev = None
                continue
            px, py = to_px(m, v)
            if prev is not None:
                c.create_line(prev[0], prev[1], px, py, fill="#3366cc", width=2)
            prev = (px, py)
        # 最新点マーカー（青）
        for m, v in reversed(data_blue):
            if v is not None:
                px, py = to_px(m, v)
                c.create_oval(px - 3, py - 3, px + 3, py + 3, fill="#3366cc", outline="")
                break

        # --- 赤（ターン終了の区間を2点で結ぶ） ---
        def to_px(m, v):
            px = x0 + (x1 - x0) * (max(0, min(max_moves, m)) / max_moves)
            py = y_mid - (v * y_scale)
            return px, py

        # 速く引けるように青データを辞書化
        blue_map = {m: v for m, v in data_blue if v is not None}

        for m_start, m_end in self.turn_segments:
            v_start = blue_map.get(m_start)
            v_end   = blue_map.get(m_end)
            if v_start is None or v_end is None:
                continue
            px0, py0 = to_px(m_start, v_start)
            px1, py1 = to_px(m_end,   v_end)
            c.create_line(px0, py0, px1, py1, fill="#cc3333", width=2)
            # 終了点を赤丸で
            c.create_oval(px1 - 3, py1 - 3, px1 + 3, py1 + 3, fill="#cc3333", outline="")

        # タイトル
        c.create_text((x0 + x1) / 2, pad_t, text="黒視点評価推移", anchor="n", fill="#666666", font=("", 12))

        # 凡例（右上）
        lx = x1 - 110; ly = y0 + 6
        c.create_line(lx, ly, lx + 20, ly, fill="#3366cc", width=2)
        c.create_text(lx + 26, ly, text="各手", anchor="w", fill="#444444", font=("", 9))
        ly += 14
        c.create_line(lx, ly, lx + 20, ly, fill="#cc3333", width=2)
        c.create_text(lx + 26, ly, text="ターン終了", anchor="w", fill="#444444", font=("", 9))

    # LLM 用の getter（main 側から参照できるようにする）
    def is_trend_enabled(self) -> bool:
        return self.use_trend_var.get()
    


