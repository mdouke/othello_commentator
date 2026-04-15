from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from commentary_service import CommentaryService
from gui import ChatWindow
from front_gui import FrontWindow
from ipc import RealtimeProcessClient
from message_router import MessageRouter
from providers import build_providers
from resume_manager import Mode, ResumeManager
from runtime_state import EvalSettings, RuntimeState, TurnCycleState, UiControlState
from state_processor import StateProcessor
from state_utils import FlipState, transform_state
from tts import build_speaker
from ui_feedback import UiFeedbackCoordinator


@dataclass
class BootstrappedApp:
    app: ChatWindow
    ipc_client: RealtimeProcessClient
    message_router: MessageRouter
    ui_feedback: UiFeedbackCoordinator


def bootstrap_application(script_path: Path, logger: logging.Logger) -> BootstrappedApp:
    providers = build_providers()
    speak = build_speaker()
    ipc_client = RealtimeProcessClient(script_path)

    app = ChatWindow(providers)
    front = FrontWindow(app)

    def tk_call(fn, *args):
        ev = threading.Event()

        def _wrap():
            try:
                fn(*args)
            finally:
                ev.set()

        app.after(0, _wrap)
        ev.wait(timeout=10.0)

    def send(msg: str):
        try:
            ipc_client.send(msg)
        except Exception as exc:
            logger.warning(f"failed to send to child: {exc}")

    resume_manager = ResumeManager(app, send)
    commentary_service = CommentaryService(
        app=app,
        front=front,
        providers=providers,
        speak=speak,
        tk_call=tk_call,
    )

    runtime_state = RuntimeState()
    cycle = TurnCycleState()
    ui_state = UiControlState()
    eval_settings = EvalSettings()
    flip_state = FlipState(
        flip_h=bool(getattr(app, "flip_h_var").get()),
        flip_v=bool(getattr(app, "flip_v_var").get()),
    )
    ui_feedback = UiFeedbackCoordinator(
        app=app,
        front=front,
        flip_state=flip_state,
        logger=logger,
    )
    ui_feedback.on_boot_complete()

    state_processor = StateProcessor(
        app=app,
        commentary_service=commentary_service,
        resume_manager=resume_manager,
        runtime_state=runtime_state,
        cycle_state=cycle,
        ui_state=ui_state,
        eval_settings=eval_settings,
        flip_state=flip_state,
        logger=logger,
    )
    message_router = MessageRouter(
        resume_manager=resume_manager,
        state_processor=state_processor,
        commentary_service=commentary_service,
        ui_feedback=ui_feedback,
        runtime_state=runtime_state,
        ui_state=ui_state,
        flip_state=flip_state,
        logger=logger,
    )

    def on_start():
        turn = app.get_start_turn() if hasattr(app, "get_start_turn") else "B"
        send(f"START:TURN={turn}")
        ui_feedback.append_system_log("START sent")

        if resume_manager.get_mode() != Mode.RUNNING:
            resume_manager.set_mode(Mode.RUNNING, "start")

        if not ui_state.flip_locked:
            ui_state.flip_locked = True
            if hasattr(app, "lock_flip_controls"):
                app.lock_flip_controls()

        if not ui_state.prompt_gate_open:
            ui_state.prompt_gate_open = True
            raw0 = runtime_state.latest_raw
            if isinstance(raw0, dict):
                view0 = transform_state(raw0, flip_state)
                runtime_state.pre_snapshot_view = view0

    def on_turn_change(turn: str):
        t = (turn or "B").strip().upper()
        t = "W" if t == "W" else "B"
        send(f"PREVIEW:TURN={t}")
        ui_feedback.append_system_log(f"PREVIEW turn set to {t}")

    def on_flip_changed(fh: bool, fv: bool):
        if ui_state.flip_locked:
            logger.info("flip toggles are locked after START; change ignored.")
            return
        flip_state.flip_h = fh
        flip_state.flip_v = fv
        raw = runtime_state.latest_raw
        if raw is None:
            return
        view = transform_state(raw, flip_state)
        app.update_board(view)

    def on_depth_change(n: int):
        logger.info(f"Eval depth set to {n}")
        if resume_manager.get_mode() != Mode.RUNNING:
            return
        state_processor.recompute_current_state(n)

    def on_close():
        try:
            ipc_client.terminate()
        except Exception:
            pass
        app.destroy()

    if hasattr(app, "set_on_pick_snapshot"):
        app.set_on_pick_snapshot(resume_manager.on_pick_snapshot)
    if hasattr(app, "set_on_calib"):
        app.set_on_calib(resume_manager.on_calib)
    app.set_on_start(on_start)
    if hasattr(app, "set_on_hand"):
        app.set_on_hand(resume_manager.on_hand)
    if hasattr(app, "set_on_turn_change"):
        app.set_on_turn_change(on_turn_change)
    if hasattr(app, "set_on_flip_change"):
        app.set_on_flip_change(on_flip_changed)
    app.set_on_depth_change(on_depth_change)
    app.protocol("WM_DELETE_WINDOW", on_close)

    send("PREVIEW:TURN=B")

    return BootstrappedApp(
        app=app,
        ipc_client=ipc_client,
        message_router=message_router,
        ui_feedback=ui_feedback,
    )
