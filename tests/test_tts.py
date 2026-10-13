from __future__ import annotations

from othello_commentator.audio import tts


def test_macos_speaker_uses_selected_rate(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(tts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        tts.subprocess,
        "run",
        lambda args, **_kwargs: (
            type("Result", (), {"stdout": "Kyoko                ja_JP    # test\nAlex                 en_US    # test\n"})()
            if args == ["say", "-v", "?"]
            else calls.append(args)
        ),
    )

    speak = tts.build_speaker(rate_provider=lambda: 250)
    speak("テスト")

    assert calls == [["say", "-v", "Kyoko", "-r", "250", "テスト"]]


def test_macos_speaker_clamps_rate(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(tts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        tts.subprocess,
        "run",
        lambda args, **_kwargs: (
            type("Result", (), {"stdout": "Kyoko                ja_JP    # test\n"})()
            if args == ["say", "-v", "?"]
            else calls.append(args)
        ),
    )

    speak = tts.build_speaker(rate_provider=lambda: 999)
    speak("テスト")

    assert calls[0][-2] == "300"


def test_macos_speaker_selects_english_voice(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(tts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        tts.subprocess,
        "run",
        lambda args, **_kwargs: (
            type("Result", (), {"stdout": "Albert               en_US    # effect\nKyoko                ja_JP    # test\nSamantha             en_US    # test\n"})()
            if args == ["say", "-v", "?"]
            else calls.append(args)
        ),
    )

    speak = tts.build_speaker(rate_provider=lambda: 200)
    speak("Great move!", "en")

    assert calls == [["say", "-v", "Samantha", "-r", "200", "Great move!"]]


def test_macos_speaker_accepts_english_voice_override(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(tts.platform, "system", lambda: "Darwin")
    monkeypatch.setenv("OTHELLO_TTS_VOICE_EN", "Daniel")
    monkeypatch.setattr(
        tts.subprocess,
        "run",
        lambda args, **_kwargs: (
            type("Result", (), {"stdout": "Samantha             en_US    # test\nDaniel               en_GB    # test\n"})()
            if args == ["say", "-v", "?"]
            else calls.append(args)
        ),
    )

    speak = tts.build_speaker()
    speak("A steady move.", "en")

    assert calls[0][2] == "Daniel"
