from __future__ import annotations

import logging

from othello_commentator.app.resume_controller import Mode
from othello_commentator.app.session_state import RuntimeState, UiControlState
from othello_commentator.domain.board_state import FlipState


class MessageRouter:
    def __init__(
        self,
        *,
        resume_manager,
        state_processor,
        commentary_service,
        ui_feedback,
        runtime_state: RuntimeState,
        ui_state: UiControlState,
        flip_state: FlipState,
        logger: logging.Logger,
    ) -> None:
        self.resume_manager = resume_manager
        self.state_processor = state_processor
        self.commentary_service = commentary_service
        self.ui_feedback = ui_feedback
        self.runtime_state = runtime_state
        self.ui_state = ui_state
        self.flip_state = flip_state
        self.log = logger

    def handle_line(self, msg: str) -> None:
        cur_mode = self.resume_manager.get_mode()

        if cur_mode == Mode.PAUSED_CALIB:
            self._handle_paused_calib(msg, cur_mode)
            return

        if cur_mode == Mode.PAUSED:
            self._handle_paused(msg, cur_mode)
            return

        if cur_mode == Mode.LOCKED_SYNC:
            self._handle_locked_sync(msg, cur_mode)
            return

        if cur_mode == Mode.RESUMABLE:
            self._handle_resumable(msg)
            return

        self._handle_running(msg)

    def _handle_paused_calib(self, msg: str, cur_mode: Mode) -> None:
        if self._handle_ready(msg):
            return
        if self.state_processor.handle_calib_preview_state(msg):
            return
        if msg.startswith(("MOVE:", "END:")) or msg.startswith("SYNC_STATE:"):
            self.ui_feedback.append_gate_ignored(cur_mode.name, msg)

    def _handle_paused(self, msg: str, cur_mode: Mode) -> None:
        if self._handle_ready(msg):
            return
        if msg.startswith(("STATE:", "MOVE:", "END:")):
            self.ui_feedback.append_gate_ignored(cur_mode.name, msg)

    def _handle_locked_sync(self, msg: str, cur_mode: Mode) -> None:
        if self._handle_ready(msg):
            return
        if msg.startswith("SYNC_STATE:"):
            self.resume_manager.handle_sync_state(msg)
            return
        if msg.startswith(("STATE:", "MOVE:", "END:")):
            self.ui_feedback.append_gate_ignored(cur_mode.name, msg)

    def _handle_resumable(self, msg: str) -> None:
        self._handle_ready(msg)

    def _handle_running(self, msg: str) -> None:
        if self._handle_ready(msg, log_ready=True):
            return
        if self.state_processor.handle_running_state(msg):
            return
        if msg.startswith("MOVE:"):
            self._handle_move(msg)
            return
        if msg.startswith("END:"):
            self._handle_end(msg)
            return
        self.ui_feedback.append_log(msg)

    def _handle_move(self, msg: str) -> None:
        coord_raw = msg[5:].strip()
        self.ui_feedback.highlight_move(coord_raw)

    def _handle_end(self, msg: str) -> None:
        self.ui_feedback.append_system_log(msg)
        if self.ui_state.prompt_gate_open:
            end_info = self._parse_end_kv(msg)
            self.commentary_service.handle_end_event(end_info, self.runtime_state, self.flip_state)
            return
        self.ui_feedback.append_log("[end][info] ignored END because prompt_gate is closed")

    def _handle_ready(self, msg: str, *, log_ready: bool = False) -> bool:
        if not msg.startswith("READY"):
            return False
        self.ui_feedback.on_system_ready(log_ready=log_ready)
        return True

    @staticmethod
    def _parse_end_kv(msg: str) -> dict[str, str]:
        s = msg.strip()
        if s.startswith("END:"):
            s = s[4:].strip()
            out: dict[str, str] = {}
            for part in s.split():
                if "=" not in part:
                    continue
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
            return out
        return {}
