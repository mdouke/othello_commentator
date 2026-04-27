# status_window.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from typing import Optional


class FrontWindow(tk.Toplevel):
    """
    「ユーザーに動いてる感を見せる」専用の別ウィンドウ。
    Tkは1つにして、追加ウィンドウは Toplevel で作る。

    使い方:
        SCALE = 1.0, 1.5, 2.0 ... を変えるだけで全体スケール変更
    """

    # --------------------
    # ★ここを変えるだけ
    # --------------------
    SCALE = 1.5  # 1.0=元サイズ, 1.5=1.5倍, 2.0=2倍 ...

    # ベース（1.0想定）値
    _BASE_W = 520
    _BASE_H = 260
    _BASE_PAD = 12

    _BASE_FONT_MSG = 16
    _BASE_FONT_SECTION = 11
    _BASE_FONT_TEXT = 10  # ttkのデフォに近いサイズ
    _BASE_WRAP = 480

    _BASE_PBAR_START_INTERVAL = 12   # pbar.start(12)
    _BASE_TICK_MS = 200              # after(200, ...)
    _BASE_PBAR_PADY = (10, 8)
    _BASE_SEP_PADY = (10, 8)

    _BASE_RESTORE_IDLE_AFTER_DONE_MS = 800
    _BASE_TTS_HOLD_MS = 600

    def __init__(self, master: tk.Misc):
        super().__init__(master)

        # ---- スケール適用関数 ----
        def s_int(x: float) -> int:
            return int(round(x * float(self.SCALE)))

        def s_tuple2(t: tuple[int, int]) -> tuple[int, int]:
            return (s_int(t[0]), s_int(t[1]))

        # ---- window ----
        self.title("System Status")
        self.geometry(f"{s_int(self._BASE_W)}x{s_int(self._BASE_H)}")
        self.resizable(False, False)

        # 常時表示したいので、×ボタンは「最小化」にする（隠さない）
        self.protocol("WM_DELETE_WINDOW", self.iconify)

        # ---- 内部状態 ----
        self._pending = 0
        self._running = False
        self._t0: Optional[float] = None
        self._token_count = 0
        self._provider = ""
        self._last_error: Optional[str] = None
        self._tick_after_id: Optional[str] = None
        self._idle_msg = "起動中…"
        self._idle_detail = "System booting..."
        self._tts_active = False
        self._tts_pending = False
        self._tts_started_at: Optional[float] = None
        self._restore_after_id: Optional[str] = None

        # ★最低これだけ「コメント再生中…」を見せる（スケールとは独立でOK）
        self._tts_hold_ms = int(self._BASE_TTS_HOLD_MS)

        # ---- スケール済み値（見た目用）----
        pad = s_int(self._BASE_PAD)

        font_msg = ("", s_int(self._BASE_FONT_MSG), "bold")
        font_section = ("", s_int(self._BASE_FONT_SECTION), "bold")
        font_text = ("", s_int(self._BASE_FONT_TEXT))

        wrap_len = s_int(self._BASE_WRAP)

        pbar_pady = s_tuple2(self._BASE_PBAR_PADY)
        sep_pady = s_tuple2(self._BASE_SEP_PADY)

        self._pbar_start_interval = max(1, int(round(self._BASE_PBAR_START_INTERVAL)))  # 見た目の速度は固定でOK
        self._tick_ms = max(50, int(round(self._BASE_TICK_MS)))  # 更新頻度は固定でOK

        self._restore_idle_after_done_ms = int(self._BASE_RESTORE_IDLE_AFTER_DONE_MS)

        # ---- UI ----
        root = ttk.Frame(self, padding=pad)
        root.pack(fill="both", expand=True)

        self.msg_var = tk.StringVar(value="起動中… ")
        self.detail_var = tk.StringVar(value="")
        self.comment_var = tk.StringVar(value="")

        self.msg_label = ttk.Label(root, textvariable=self.msg_var, font=font_msg)
        self.msg_label.pack(anchor="w")

        self.pbar = ttk.Progressbar(root, mode="indeterminate")
        self.pbar.pack(fill="x", pady=pbar_pady)

        self.detail_label = ttk.Label(root, textvariable=self.detail_var, font=font_text)
        self.detail_label.pack(anchor="w")

        # コメント本文（再生中に表示）
        ttk.Separator(root).pack(fill="x", pady=sep_pady)
        ttk.Label(root, text="Comment:", font=font_section).pack(anchor="w")
        self.comment_label = ttk.Label(
            root,
            textvariable=self.comment_var,
            wraplength=wrap_len,
            justify="left",
            font=font_text,
        )
        self.comment_label.pack(anchor="w", fill="x")

        # 起動時は表示しておく（進捗バーは回さない）
        self.show()
        self.detail_var.set("System booting...")

        # アイドル表示として保持
        self._idle_msg = "起動中…"
        self._idle_detail = "System booting..."

    # --------------------
    # public API（main.py から呼ぶ）
    # --------------------
    def on_request_start(self, provider: str, message: str = "生成中…"):
        """プロンプト送信開始"""
        self._pending += 1
        self._provider = provider or ""
        self._last_error = None

        # 既に動いてるなら pending だけ増やして表示更新
        if self._running:
            self._refresh_detail()
            return

        self._running = True
        self._t0 = time.time()
        self._token_count = 0

        self.msg_var.set(message)
        self._refresh_detail()

        self.show()
        self.pbar.start(self._pbar_start_interval)  # くるくる

        self._schedule_tick()

    def on_delta(self, _tok: str):
        """ストリーミング受信（トークン数だけ増やす）"""
        if not self._running:
            return
        self._token_count += 1
        # 毎回描画すると重いので detail は tick 側で更新

    def on_request_end(self, ok: bool, elapsed: float, err: Optional[str] = None):
        """返信受信終了（成功/失敗）"""
        # pending を下げる
        self._pending = max(0, self._pending - 1)

        # まだ他のリクエストが生きているなら終了しない
        if self._pending > 0:
            self._refresh_detail()
            return

        self._running = False
        self._last_error = err

        self.pbar.stop()
        self._cancel_tick()

        # ★成功 & TTS予定なら「完了」を出さず、表示は TTS開始側に任せる
        #   ただし内部的には生成終了なので detail は最終値にする
        if ok and self._tts_pending:
            self.detail_var.set(self._build_detail(elapsed=elapsed, final=True))
            return

        if ok:
            self.msg_var.set("完了")
        else:
            self.msg_var.set("エラー")

        # 最終表示
        self.detail_var.set(self._build_detail(elapsed=elapsed, final=True))

        # すぐ待機に戻すと「動いた感」が弱いので少しだけ見せてから待機表示へ戻す（ウィンドウは消さない）
        self._schedule_restore_idle(self._restore_idle_after_done_ms)

    def on_tts_prepare(self):
        """このリクエストはこのあとTTSを開始する予定、という宣言（restore予約を止める用）"""
        self._tts_pending = True
        # 既存の待機復帰予約があれば潰す
        if self._restore_after_id is not None:
            try:
                self.after_cancel(self._restore_after_id)
            except Exception:
                pass
            self._restore_after_id = None

    def _schedule_restore_idle(self, ms: int):
        # 既存予約を潰してから新規予約
        if self._restore_after_id is not None:
            try:
                self.after_cancel(self._restore_after_id)
            except Exception:
                pass
            self._restore_after_id = None
        self._restore_after_id = self.after(ms, self._restore_idle)

    def _restore_idle(self):
        """生成完了後に待機表示へ戻す（TTS中は上書きしない）"""
        self._restore_after_id = None
        if self._running or self._pending > 0:
            return
        # ★TTS予定（まだ開始してない）でも上書きしない
        if self._tts_pending:
            return
        if self._tts_active:
            return
        self.msg_var.set(self._idle_msg)
        self.detail_var.set(self._idle_detail)

    # --------------------
    # window controls
    # --------------------
    def show(self):
        self.deiconify()
        try:
            self.lift()
            self.attributes("-topmost", True)
            self.after(50, lambda: self.attributes("-topmost", False))
        except Exception:
            pass

    def hide(self):
        self._cancel_tick()
        self.withdraw()

    # --------------------
    # internal helpers
    # --------------------
    def _schedule_tick(self):
        self._cancel_tick()
        self._tick_after_id = self.after(self._tick_ms, self._tick)

    def _cancel_tick(self):
        if self._tick_after_id is not None:
            try:
                self.after_cancel(self._tick_after_id)
            except Exception:
                pass
        self._tick_after_id = None

    def _tick(self):
        if not self._running:
            return
        self._refresh_detail()
        self._schedule_tick()

    def _refresh_detail(self):
        elapsed = 0.0
        if self._t0 is not None:
            elapsed = max(0.0, time.time() - self._t0)
        self.detail_var.set(self._build_detail(elapsed=elapsed, final=False))

    def _build_detail(self, elapsed: float, final: bool) -> str:
        base = f"Provider: {self._provider} | Elapsed: {elapsed:.1f}s"
        tok = f" | Tokens: {self._token_count}"
        if final and self._last_error:
            # 画面が崩れないよう短く
            e = self._last_error.replace("\n", " ").strip()
            if len(e) > 80:
                e = e[:80] + "…"
            return base + tok + f"\nError: {e}"
        return base + tok

    # --------------------
    # boot / ready status
    # --------------------
    def on_boot_complete(self):
        """アプリ起動完了（GUI初期化完了）"""
        self._set_idle_state("待機中", "")
        if not self._running and self._pending == 0 and not self._tts_active:
            self.msg_var.set(self._idle_msg)
            self.detail_var.set(self._idle_detail)

    def on_system_ready(self):
        """READY を受信したとき"""
        self._set_idle_state("次の手を打ってください", "All subsystems are operational")
        # ★TTS予定中/再生中はREADYで上書きしない
        if (not self._running and self._pending == 0
                and (not self._tts_active) and (not self._tts_pending)):
            self.msg_var.set(self._idle_msg)
            self.detail_var.set(self._idle_detail)

    # --------------------
    # TTS / playback status
    # --------------------
    def on_tts_start(self, text: str):
        """コメント再生開始：本文を表示して状態を切り替える"""
        self._tts_pending = False
        self._tts_active = True
        self._tts_started_at = time.time()
        self.show()
        self.msg_var.set("コメント再生中...")
        self.detail_var.set("")
        self.comment_var.set((text or "").strip())
        # 「完了→待機に戻す」予約が残っていたらキャンセル（TTS中にsystem readyへ戻らないように）
        if self._restore_after_id is not None:
            try:
                self.after_cancel(self._restore_after_id)
            except Exception:
                pass
            self._restore_after_id = None

    def on_tts_end(self):
        """コメント再生終了：待機表示へ戻す（ただし生成中なら触らない）"""
        self._tts_active = False
        self._tts_pending = False
        # ★TTSが即終了しても「コメント再生中…」が見えるように最低表示時間を保証
        started = self._tts_started_at
        self._tts_started_at = None
        if started is None:
            self._restore_idle_after_tts()
            return
        elapsed_ms = int(max(0.0, time.time() - started) * 1000)
        remain = max(0, int(self._tts_hold_ms) - elapsed_ms)
        if remain > 0:
            self._schedule_restore_idle_after_tts(remain)
        else:
            self._restore_idle_after_tts()

    def _schedule_restore_idle_after_tts(self, ms: int):
        if self._restore_after_id is not None:
            try:
                self.after_cancel(self._restore_after_id)
            except Exception:
                pass
            self._restore_after_id = None
        self._restore_after_id = self.after(ms, self._restore_idle_after_tts)

    def _restore_idle_after_tts(self):
        """TTS終了後の待機復帰。新しい処理が始まっていれば上書きしない。"""
        self._restore_after_id = None
        if self._running or self._pending > 0:
            return
        if self._tts_active or self._tts_pending:
            return
        self._restore_idle_force()

    def _restore_idle_force(self):
        """強制的に待機表示へ戻す（TTS終了の表示保証用）"""
        # 予約が残っていたら消す
        if self._restore_after_id is not None:
            try:
                self.after_cancel(self._restore_after_id)
            except Exception:
                pass
            self._restore_after_id = None
        self.msg_var.set(self._idle_msg)
        self.detail_var.set(self._idle_detail)
        self.comment_var.set("")

    def _set_idle_state(self, msg: str, detail: str):
        self._idle_msg = msg
        self._idle_detail = detail
