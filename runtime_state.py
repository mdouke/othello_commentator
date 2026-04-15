from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeState:
    latest_raw: dict[str, Any] | None = None
    turn_history: list[dict[str, Any]] = field(default_factory=list)
    pre_snapshot_view: dict[str, Any] | None = None
    last_post_key: tuple[Any, ...] | None = None
    last_end_key: tuple[Any, ...] | None = None
    final_view: dict[str, Any] | None = None


@dataclass
class TurnCycleState:
    anchor: str | None = None
    start_move_no: int | None = None
    prev_turn: str | None = None
    prev_moves_len: int | None = None
    prev_move_no: int | None = None


@dataclass
class UiControlState:
    flip_locked: bool = False
    prompt_gate_open: bool = False


@dataclass
class EvalSettings:
    depth: int = 2
    lock: threading.Lock = field(default_factory=threading.Lock)
