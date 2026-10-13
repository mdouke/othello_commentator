from __future__ import annotations

from othello_commentator.llm.prompt_builder import (
    build_end_game_prompt,
    build_post_move_prompt,
)


def _states() -> tuple[dict, dict]:
    pre_board = [["."] * 8 for _ in range(8)]
    pre_board[3][3] = "W"
    pre_board[3][4] = "B"
    pre_board[4][3] = "B"
    pre_board[4][4] = "W"
    post_board = [row[:] for row in pre_board]
    post_board[2][3] = "B"
    post_board[3][3] = "B"
    pre = {
        "turn": "B",
        "move_no": 0,
        "board": pre_board,
        "moves": ["d3", "c4"],
        "evals": {"d3": 1.5, "c4": 0.5},
        "pos_eval": 0.0,
    }
    post = {"turn": "W", "board": post_board, "last_move": "d3"}
    return pre, post


def test_english_normal_move_prompt_is_english_and_keeps_parse_key() -> None:
    pre, post = _states()

    prompt = build_post_move_prompt(pre, post, "d3", language="en")

    assert "Return exactly one line in English" in prompt
    assert 'd3: "comment"' in prompt
    assert "15 to 30 English words" in prompt
    assert "序盤" not in prompt


def test_english_pass_prompt_names_passed_side_and_repeat_turn() -> None:
    pre, post = _states()
    post.update({"cause_move": "d3", "passed_side": "W"})

    prompt = build_post_move_prompt(pre, post, "pass", language="en")

    assert "White must pass" in prompt
    assert "Black can move again" in prompt
    assert 'pass: "comment"' in prompt


def test_english_end_prompt_contains_result_and_counts() -> None:
    pre, post = _states()

    prompt = build_end_game_prompt(
        pre,
        post,
        {"reason": "board_full", "winner": "B", "black": 40, "white": 24},
        language="en",
    )

    assert "the board was completely full" in prompt
    assert "Result: Black" in prompt
    assert "Black 40, White 24" in prompt
    assert "__end__: <comment>" in prompt


def test_japanese_remains_default() -> None:
    pre, post = _states()

    prompt = build_post_move_prompt(pre, post, "d3")

    assert "序盤" in prompt
    assert 'd3: "コメント"' in prompt
