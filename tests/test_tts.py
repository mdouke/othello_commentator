from __future__ import annotations

from othello_commentator.audio import tts


def test_macos_speaker_uses_selected_rate(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(tts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        tts.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args),
    )

    speak = tts.build_speaker(rate_provider=lambda: 250)
    speak("テスト")

    assert calls == [["say", "-r", "250", "テスト"]]


def test_macos_speaker_clamps_rate(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(tts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        tts.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args),
    )

    speak = tts.build_speaker(rate_provider=lambda: 999)
    speak("テスト")

    assert calls[0][2] == "300"
