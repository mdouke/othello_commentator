from __future__ import annotations

import time
import wave

import pytest

from othello_commentator.storage.audio_recorder import MicrophoneRecorder


class FakeRawInputStream:
    def __init__(self, *, callback, **kwargs) -> None:
        self.callback = callback

    def __enter__(self):
        self.callback((b"\x01\x00\x02\x00") * 128, 128, None, None)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FakeSoundDevice:
    RawInputStream = FakeRawInputStream
    default = type("Default", (), {"device": [None, 1]})()

    def query_devices(self, device=None, kind=None):
        if device is None and kind is None:
            return [
                {
                    "name": "Output Only",
                    "max_input_channels": 0,
                    "default_samplerate": 48000,
                },
                {
                    "name": "Test Mic",
                    "max_input_channels": 1,
                    "default_samplerate": 16000,
                },
            ]
        assert kind == "input"
        return {
            "name": "Test Mic",
            "max_input_channels": 1,
            "default_samplerate": 16000,
        }


def test_records_microphone_audio_to_wav(tmp_path) -> None:
    recorder = MicrophoneRecorder(tmp_path, sounddevice_module=FakeSoundDevice())

    path = recorder.start()
    time.sleep(0.1)
    recorder.stop()

    assert path.exists()
    with wave.open(str(path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.getnframes() > 0


def test_lists_input_microphone_devices(tmp_path) -> None:
    recorder = MicrophoneRecorder(tmp_path, sounddevice_module=FakeSoundDevice())

    devices = recorder.list_input_devices()

    assert len(devices) == 1
    assert devices[0].index == 1
    assert devices[0].name == "Test Mic"
    assert devices[0].is_default is True


def test_reports_missing_sounddevice(tmp_path) -> None:
    recorder = MicrophoneRecorder(tmp_path, sounddevice_module=None)
    recorder._sd = None

    with pytest.raises(RuntimeError, match="sounddevice"):
        recorder.start()
