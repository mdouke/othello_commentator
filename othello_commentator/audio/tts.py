#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import atexit
import platform
import queue
import subprocess
import threading
import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)

def build_speaker():
    """
    OS を判定して共通の speak(text:str)->None を返す。
    - macOS: 'say'
    - Win/Linux: pyttsx3（未導入なら no-op）
    speak() は「その発話が終わるまでブロック」する設計。
    （FrontWindowの on_tts_end() を正しいタイミングで呼ぶため）
    """
    is_mac = platform.system() == "Darwin"

    if is_mac:
        def speak(text: str) -> None:
            t = (text or "").strip()
            if t:
                try:
                    # ★完了まで待つ（ブロッキング）
                    subprocess.run(
                        ["say", "-r", "200", t],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    log.exception("macOS say failed")
        return speak

    # Windows/Linux
    try:
        import pyttsx3  # type: ignore
    except ImportError:
        pyttsx3 = None
        log.warning("pyttsx3 未導入 → 読み上げ無効 (no-op)")

    if not pyttsx3:
        def speak(_text: str) -> None:
            pass
        return speak

    # ★(text, done_event) を流して、worker完了で done_event を set する
    Item = Tuple[str, threading.Event]
    q: queue.Queue[Item | None] = queue.Queue()
    eng = pyttsx3.init()
    eng.setProperty("rate", 200)

    def _worker() -> None:
        while True:
            t = q.get()
            if t is None:
                break
            text, done_event = t
            try:
                eng.say(text)
                eng.runAndWait()
            except Exception:
                log.exception("TTS error")
            finally:
                # ★必ず解除（エラーでも speak() 側が固まらない）
                try:
                    done_event.set()
                except Exception:
                    pass

    th = threading.Thread(target=_worker, daemon=True)
    th.start()

    @atexit.register
    def _bye() -> None:
        try:
            q.put(None)
        except Exception:
            pass

    def speak(text: str) -> None:
        t = (text or "").strip()
        if t:
            done = threading.Event()
            q.put((t, done))
            # ★完了まで待つ（ブロッキング）
            # 無限待ちが嫌なら timeout=XXX にしてもOK
            done.wait()

    return speak
