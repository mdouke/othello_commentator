#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import atexit
import os
import platform
import queue
import subprocess
import threading
import logging
import re
from typing import Callable, Tuple

from othello_commentator.app.commentary_settings import normalize_commentary_language

log = logging.getLogger(__name__)

DEFAULT_SPEECH_RATE = 200

_MACOS_VOICE_PREFERENCES = {
    "ja": ("Kyoko", "Otoya"),
    "en": ("Samantha", "Alex", "Daniel", "Karen", "Moira"),
}


def _pick_macos_voice(
    available: list[tuple[str, str]], language: str
) -> str | None:
    """Prefer normal narrator voices and avoid novelty voices such as Albert."""
    lang = normalize_commentary_language(language).value
    candidates = [name for name, locale in available if locale.startswith(lang + "_")]
    if not candidates:
        return None

    override = os.environ.get(f"OTHELLO_TTS_VOICE_{lang.upper()}", "").strip()
    if override:
        exact = next((name for name in candidates if name.casefold() == override.casefold()), None)
        if exact:
            return exact
        log.warning(
            "configured macOS voice '%s' is not installed for language '%s'",
            override,
            lang,
        )

    for preferred in _MACOS_VOICE_PREFERENCES[lang]:
        exact = next((name for name in candidates if name.casefold() == preferred.casefold()), None)
        if exact:
            return exact
    return candidates[0]


def _macos_voices() -> dict[str, str]:
    """Return one installed macOS voice for each supported language."""
    try:
        result = subprocess.run(
            ["say", "-v", "?"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        log.exception("failed to list macOS voices")
        return {}

    available: list[tuple[str, str]] = []
    for line in (result.stdout or "").splitlines():
        match = re.match(r"^(.+?)\s+([a-z]{2}_[A-Z]{2})\s+#", line)
        if not match:
            continue
        name, locale = match.groups()
        available.append((name.strip(), locale))
    return {
        language: voice
        for language in ("ja", "en")
        if (voice := _pick_macos_voice(available, language)) is not None
    }


def _pyttsx3_voice_for_language(engine, language: str) -> str | None:
    target = normalize_commentary_language(language).value
    try:
        voices = engine.getProperty("voices") or []
    except Exception:
        return None
    for voice in voices:
        values = getattr(voice, "languages", None) or []
        for raw in values:
            if isinstance(raw, bytes):
                value = raw.decode("utf-8", errors="ignore")
            else:
                value = str(raw)
            if target in value.lower():
                return getattr(voice, "id", None)
    return None


def build_speaker(rate_provider: Callable[[], int] | None = None):
    """
    OS を判定して共通の speak(text: str, language: str = "ja")->None を返す。
    - macOS: 'say'
    - Win/Linux: pyttsx3（未導入なら no-op）
    language は ja/en を受け取り、利用可能なら対応する音声を選ぶ。
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
        voices: dict[str, str] | None = None

        def speak(text: str, language: str = "ja") -> None:
            nonlocal voices
            t = (text or "").strip()
            if t:
                try:
                    if voices is None:
                        voices = _macos_voices()
                    lang = normalize_commentary_language(language).value
                    voice = voices.get(lang)
                    args = ["say"]
                    if voice:
                        args.extend(["-v", voice])
                    else:
                        log.warning("macOS voice for language '%s' not found; using default", lang)
                    args.extend(["-r", str(current_rate()), t])
                    # ★完了まで待つ（ブロッキング）
                    subprocess.run(
                        args,
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
        def speak(_text: str, _language: str = "ja") -> None:
            pass
        return speak

    # ★(text, done_event) を流して、worker完了で done_event を set する
    Item = Tuple[str, int, str | None, threading.Event]
    q: queue.Queue[Item | None] = queue.Queue()
    eng = pyttsx3.init()
    eng.setProperty("rate", DEFAULT_SPEECH_RATE)

    def _worker() -> None:
        while True:
            t = q.get()
            if t is None:
                break
            text, rate, voice_id, done_event = t
            try:
                eng.setProperty("rate", rate)
                if voice_id:
                    eng.setProperty("voice", voice_id)
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

    voice_cache: dict[str, str | None] = {}

    def speak(text: str, language: str = "ja") -> None:
        t = (text or "").strip()
        if t:
            lang = normalize_commentary_language(language).value
            if lang not in voice_cache:
                voice_cache[lang] = _pyttsx3_voice_for_language(eng, lang)
                if voice_cache[lang] is None:
                    log.warning("TTS voice for language '%s' not found; using default", lang)
            done = threading.Event()
            q.put((t, current_rate(), voice_cache[lang], done))
            # ★完了まで待つ（ブロッキング）
            # 無限待ちが嫌なら timeout=XXX にしてもOK
            done.wait()

    return speak
