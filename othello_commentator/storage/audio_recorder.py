from __future__ import annotations

import queue
import sys
import threading
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import sounddevice as sd
except ImportError:
    sd = None


@dataclass(frozen=True)
class MicrophoneDevice:
    index: int
    name: str
    max_input_channels: int
    default_samplerate: int
    is_default: bool = False


class MicrophoneRecorder:
    """Record microphone audio to a WAV file while the app is running."""

    def __init__(
        self,
        output_dir: Path,
        *,
        device: int | str | None = None,
        sample_rate: int | None = None,
        channels: int = 1,
        sounddevice_module: Any | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self._sd = sounddevice_module if sounddevice_module is not None else sd
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._stop_event = threading.Event()
        self._started_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._path: Path | None = None
        self._error: Exception | None = None

    def list_input_devices(self) -> list[MicrophoneDevice]:
        if self._sd is None:
            raise RuntimeError(
                "sounddevice がインストールされていません。"
                " `pip install -r requirements.txt` を実行してください。"
            )

        default_input_index = self._get_default_input_index()
        devices = []
        for index, info in enumerate(self._sd.query_devices()):
            max_input_channels = int(info.get("max_input_channels", 0))
            if max_input_channels <= 0:
                continue
            devices.append(
                MicrophoneDevice(
                    index=index,
                    name=str(info.get("name", f"Input Device {index}")),
                    max_input_channels=max_input_channels,
                    default_samplerate=int(info.get("default_samplerate", 0)),
                    is_default=index == default_input_index,
                )
            )
        return devices

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def is_recording(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> Path:
        if self.is_recording:
            if self._path is None:
                raise RuntimeError("録音ファイルの保存先が未設定です。")
            return self._path
        if self._sd is None:
            raise RuntimeError(
                "sounddevice がインストールされていません。"
                " `pip install -r requirements.txt` を実行してください。"
            )

        self._error = None
        self._started_event.clear()
        self._stop_event.clear()
        self._queue = queue.Queue()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.output_dir / datetime.now().strftime("audio_%Y%m%d_%H%M%S.wav")
        self._thread = threading.Thread(target=self._record_loop, name="microphone-recorder", daemon=True)
        self._thread.start()
        self._started_event.wait(2.0)
        if self._error is not None:
            raise RuntimeError(f"マイク録音を開始できません: {self._error}") from self._error
        return self._path

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if self._error is not None:
            raise RuntimeError(f"録音を停止できません: {self._error}") from self._error

    def _record_loop(self) -> None:
        assert self._sd is not None
        assert self._path is not None

        try:
            device_info = self._sd.query_devices(self.device, "input")
            max_input_channels = int(device_info["max_input_channels"])
            if self.channels > max_input_channels:
                raise RuntimeError(
                    f"選択中の入力デバイス「{device_info['name']}」は"
                    f"{max_input_channels}ch入力として認識されています。"
                )
            actual_sample_rate = self.sample_rate or int(device_info["default_samplerate"])

            with wave.open(str(self._path), "wb") as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(2)
                wav_file.setframerate(actual_sample_rate)

                with self._sd.RawInputStream(
                    samplerate=actual_sample_rate,
                    blocksize=1024,
                    device=self.device,
                    channels=self.channels,
                    dtype="int16",
                    callback=self._callback,
                ):
                    self._started_event.set()
                    while not self._stop_event.wait(0.05):
                        self._flush_audio(wav_file)
                    self._flush_audio(wav_file)
        except Exception as exc:
            self._error = exc
            self._started_event.set()
            if self._path.exists() and self._path.stat().st_size <= 44:
                self._path.unlink()

    def _callback(self, indata: bytes, frames: int, time_info: object, status: object) -> None:
        if status:
            print(f"録音警告: {status}", file=sys.stderr)
        self._queue.put(bytes(indata))

    def _flush_audio(self, wav_file: wave.Wave_write) -> None:
        while True:
            try:
                wav_file.writeframes(self._queue.get_nowait())
            except queue.Empty:
                return

    def _get_default_input_index(self) -> int | None:
        default_device = getattr(self._sd, "default", None)
        default_value = getattr(default_device, "device", None)
        if isinstance(default_value, (list, tuple)) and len(default_value) >= 2:
            try:
                return int(default_value[1])
            except (TypeError, ValueError):
                return None
        return None
