from __future__ import annotations

import logging

from state_utils import FlipState, transform_coord


class UiFeedbackCoordinator:
    def __init__(self, *, app, front, flip_state: FlipState, logger: logging.Logger) -> None:
        self.app = app
        self.front = front
        self.flip_state = flip_state
        self.log = logger

    def on_boot_complete(self) -> None:
        self.app.after(0, self.front.on_boot_complete)

    def on_system_ready(self, *, log_ready: bool = False) -> None:
        if hasattr(self.app, "set_status"):
            self.app.after(0, self.app.set_status, "準備完了")
        self.app.after(0, self.front.on_system_ready)
        if log_ready:
            self.log.info("READY")

    def append_log(self, message: str) -> None:
        self.app.after(0, self.app.append_log, message)

    def append_system_log(self, message: str) -> None:
        self.append_log(f"[system] {message}")

    def append_gate_ignored(self, mode_name: str, msg: str) -> None:
        self.append_log(f"[gate] ignored while {mode_name}: {msg[:120]}")

    def highlight_move(self, coord_raw: str) -> None:
        if coord_raw.upper() == "PASS":
            return
        coord_view = transform_coord(coord_raw, self.flip_state)
        if hasattr(self.app, "highlight_move"):
            self.app.after(0, self.app.highlight_move, coord_view)

    def report_reader_error(self, exc: Exception) -> None:
        self.append_log(f"[reader][fatal] {exc}")
