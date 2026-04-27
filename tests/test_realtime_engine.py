from __future__ import annotations

from unittest.mock import patch

from othello_commentator.realtime.engine import (
    EngineConfig,
    RealtimeLoopState,
    SyncModeState,
    handle_game_init,
    maybe_emit_sync_state,
    resolve_turn_resolution,
    should_sample_board,
    update_hand_state,
    update_sync_tracking,
    update_total_tracking,
)
from othello_commentator.realtime.control_protocol import RealtimeControlState


def test_should_sample_board_when_waiting_for_move() -> None:
    control_state = RealtimeControlState()
    loop_state = RealtimeLoopState(waiting_for_move=True)

    assert should_sample_board(control_state, EngineConfig(), 1, loop_state, False) is True


def test_should_sample_board_when_periodic_sampling_hits() -> None:
    control_state = RealtimeControlState()
    control_state.set_started(True, "B")
    loop_state = RealtimeLoopState(prev_board=[["."] * 8 for _ in range(8)], confirmed_total=5)
    config = EngineConfig(board_sample_every=4)

    assert should_sample_board(control_state, config, 8, loop_state, False) is True
    assert should_sample_board(control_state, config, 7, loop_state, False) is False


def test_update_total_tracking_initializes_and_increments_stable_counter() -> None:
    loop_state = RealtimeLoopState()

    update_total_tracking(loop_state, 6)
    assert loop_state.prev_logged_tot == 6
    assert loop_state.last_total == 6
    assert loop_state.same_frames == 1

    update_total_tracking(loop_state, 6)
    assert loop_state.last_total == 6
    assert loop_state.same_frames == 2


def test_update_hand_state_switches_waiting_state() -> None:
    loop_state = RealtimeLoopState(prev_hp=True, waiting_for_move=False, waiting_age=10)

    update_hand_state(False, loop_state)
    assert loop_state.waiting_for_move is True
    assert loop_state.waiting_age == 0

    update_hand_state(True, loop_state)
    assert loop_state.waiting_for_move is False
    assert loop_state.prev_hp is True


def test_handle_game_init_sets_initial_board_and_emits_state() -> None:
    control_state = RealtimeControlState()
    control_state.set_started(True, "B")
    board = [["."] * 8 for _ in range(8)]
    board[3][3] = "W"
    board[3][4] = "B"
    board[4][3] = "B"
    board[4][4] = "W"
    loop_state = RealtimeLoopState(same_frames=10)
    config = EngineConfig(stable_n=10, min_stones_start=4)

    with patch("othello_commentator.realtime.engine.emit_state") as emit_state_mock:
        initialized = handle_game_init(control_state, board, 4, loop_state, config)

    assert initialized is True
    assert loop_state.prev_board == board
    assert loop_state.confirmed_total == 4
    emit_state_mock.assert_called_once()


def test_update_sync_tracking_and_emit_sync_state() -> None:
    sync_state = SyncModeState()
    config = EngineConfig(sync_stable_n=2)
    board = [["."] * 8 for _ in range(8)]

    update_sync_tracking(sync_state, 4)
    assert sync_state.same_frames == 1

    update_sync_tracking(sync_state, 4)
    assert sync_state.same_frames == 2

    with patch("othello_commentator.realtime.engine.emit_sync_state") as emit_sync_mock:
        emitted = maybe_emit_sync_state(board, 4, sync_state, config)

    assert emitted is True
    emit_sync_mock.assert_called_once_with(board)
    assert sync_state.same_frames == 0
    assert sync_state.last_tot is None


def test_resolve_turn_resolution_normal_case() -> None:
    board = [["."] * 8 for _ in range(8)]
    board[3][3] = "W"
    board[3][4] = "B"
    board[4][3] = "B"
    board[4][4] = "W"

    resolution = resolve_turn_resolution(board, "B")

    assert resolution.kind == "normal"
    assert resolution.opp == "W"
    assert resolution.board_full is False


def test_resolve_turn_resolution_double_pass_case() -> None:
    board = [["B"] * 8 for _ in range(8)]

    resolution = resolve_turn_resolution(board, "B")

    assert resolution.kind == "board_full_after_pass"
    assert resolution.opp_moves == []
    assert resolution.my_moves == []
