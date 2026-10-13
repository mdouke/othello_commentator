#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import atexit
import platform
import queue
import subprocess
import threading
import logging
from typing import Callable, Tuple

log = logging.getLogger(__name__)

DEFAULT_SPEECH_RATE = 200


def build_speaker(rate_provider: Callable[[], int] | None = None):
    """
    OS を判定して共通の speak(text:str)->None を返す。
    - macOS: 'say'
    - Win/Linux: pyttsx3（未導入なら no-op）
    speak() は「その発話が終わるまでブロック」する設計。
    （FrontWindowの on_tts_end() を正しいタイミングで呼ぶため）
    """
    is_mac = platform.system() == "Darwin"

    def current_rate() -> int:
        if rate_provider is None:
            return DEFAULT_SPEECH_RATE
        try:
            return max(100, min(300, int(rate_provider())))
        except (TypeError, ValueError):
            return DEFAULT_SPEECH_RATE

    if is_mac:
        def speak(text: str) -> None:
            t = (text or "").strip()
            if t:
                try:
                    # ★完了まで待つ（ブロッキング）
                    subprocess.run(
                        ["say", "-r", str(current_rate()), t],
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
    Item = Tuple[str, int, threading.Event]
    q: queue.Queue[Item | None] = queue.Queue()
    eng = pyttsx3.init()
    eng.setProperty("rate", DEFAULT_SPEECH_RATE)

    def _worker() -> None:
        while True:
            t = q.get()
            if t is None:
                break
            text, rate, done_event = t
            try:
                eng.setProperty("rate", rate)
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
            q.put((t, current_rate(), done))
            # ★完了まで待つ（ブロッキング）
            # 無限待ちが嫌なら timeout=XXX にしてもOK
            done.wait()

    return speak
