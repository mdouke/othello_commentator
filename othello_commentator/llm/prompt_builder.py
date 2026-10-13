from __future__ import annotations

import math
from typing import Any

from othello_commentator.app.commentary_settings import (
    CommentaryLanguage,
    normalize_commentary_language,
)


def _side_name(side: object, language: CommentaryLanguage) -> str:
    value = str(side or "").upper()
    if language == CommentaryLanguage.ENGLISH:
        return "Black" if value == "B" else "White"
    return "黒" if value == "B" else "白"


def _opponent(side: object) -> str:
    return "W" if str(side or "").upper() == "B" else "B"


def _count_stones(board: list[list[str]]) -> tuple[int, int]:
    black = sum(cell == "B" for row in board for cell in row)
    white = sum(cell == "W" for row in board for cell in row)
    return black, white


def _sorted_move_evals(
    moves: list[str], evals: dict[str, Any], played_move: str, language: CommentaryLanguage
) -> str:
    unique_moves = list(dict.fromkeys(str(move).lower() for move in moves if move))
    played = (played_move or "").lower().strip()

    def sort_key(move: str) -> tuple[int, float]:
        value = evals.get(move)
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return 1, 0.0
        return (0, -numeric_value) if math.isfinite(numeric_value) else (1, 0.0)

    suffix = " (played move)" if language == CommentaryLanguage.ENGLISH else " （打たれた手）"
    lines = [
        f"{move}{suffix if move == played else ''}: {evals.get(move)}"
        for move in sorted(unique_moves, key=sort_key)
    ]
    if lines:
        return "\n".join(lines)
    return "None" if language == CommentaryLanguage.ENGLISH else "（なし）"


def _phase(pre_view: dict[str, Any]) -> tuple[str, int]:
    move_no = int(pre_view.get("move_no") or 0)
    next_move_no = max(1, min(60, move_no + 1))
    if next_move_no <= 20:
        return "opening", next_move_no
    if next_move_no <= 40:
        return "midgame", next_move_no
    return "endgame", next_move_no


def _stance(pre_view: dict[str, Any], language: CommentaryLanguage) -> str:
    phase, move_no = _phase(pre_view)
    if language == CommentaryLanguage.ENGLISH:
        if phase == "opening":
            return (
                f"This was approximately move {move_no} of at most 60, in the opening. "
                "Do not overstate the position; focus on the idea, intent, and possible continuation, "
                "with restrained emotion and anticipation."
            )
        if phase == "midgame":
            return (
                f"This was approximately move {move_no} of at most 60, in the midgame. "
                "Briefly convey its intent and risk, with rising excitement."
            )
        return (
            f"This was approximately move {move_no} of at most 60, in the endgame. "
            "Emphasize the tension and importance of the result, but keep the reasoning concise."
        )

    if phase == "opening":
        return (
            f"打たれた手は、最大60手中およそ{move_no}手目で序盤の手です。"
            "形勢はまだ大きく動きにくいので、大袈裟に断定せず、主に構想や狙い、"
            "今後の展開の可能性を語ってください。感情表現はやや抑えめにしつつ、"
            "これから始まる勝負への期待感を演出してください。"
        )
    if phase == "midgame":
        return (
            f"打たれた手は、最大60手中およそ{move_no}手目で中盤の手です。"
            "局面が動きやすいので、狙いとリスクを手短に示しつつ、感情は盛り上げ気味で実況してください。"
        )
    return (
        f"打たれた手は、最大60手中およそ{move_no}手目で終盤の手です。"
        "勝敗に直結しやすいので、結果への緊張感を強めに、ただし根拠は簡潔に実況してください。"
    )


def _move_info(
    pre_view: dict[str, Any],
    post_view: dict[str, Any],
    played_move: str,
    language: CommentaryLanguage,
) -> str:
    pre_board = pre_view.get("board")
    post_board = post_view.get("board")
    played = (played_move or "").lower().strip()
    position_eval = pre_view.get("pos_eval")
    missing = "None" if language == CommentaryLanguage.ENGLISH else "（なし）"
    position_eval_text = str(position_eval) if position_eval is not None else missing
    valid = (
        isinstance(pre_board, list)
        and isinstance(post_board, list)
        and len(pre_board) == 8
        and len(post_board) == 8
        and all(isinstance(row, list) and len(row) == 8 for row in pre_board)
        and all(isinstance(row, list) and len(row) == 8 for row in post_board)
        and len(played) == 2
        and played[0] in "abcdefgh"
        and played[1] in "12345678"
    )
    if not valid:
        if language == CommentaryLanguage.ENGLISH:
            return (
                "## Move information\n\n"
                f"- Position evaluation before the move, from the mover's perspective: {position_eval_text}\n"
                "- Directions flipped: unknown\n- Disc-count change: unknown\n- Disc-count situation: unknown"
            )
        return (
            "## 手の情報\n\n"
            f"- 着手前の盤面評価値（手番側視点）：{position_eval_text}\n"
            "- ひっくり返した方向：不明\n- 石数変化：不明\n- 石数の状況：不明"
        )

    move_x = ord(played[0]) - ord("a")
    move_y = int(played[1]) - 1
    mover = str(pre_view.get("turn") or "").upper()
    opponent = _opponent(mover)
    direction_kinds: set[str] = set()
    for y in range(8):
        for x in range(8):
            if pre_board[y][x] != opponent or post_board[y][x] != mover:
                continue
            dx, dy = x - move_x, y - move_y
            if dy == 0:
                direction_kinds.add("horizontal")
            elif dx == 0:
                direction_kinds.add("vertical")
            elif abs(dx) == abs(dy):
                direction_kinds.add("diagonal")

    directions_en = ", ".join(
        item for item in ("horizontal", "vertical", "diagonal") if item in direction_kinds
    ) or "unknown"
    directions_ja = "・".join(
        {"horizontal": "横", "vertical": "縦", "diagonal": "斜め"}[item]
        for item in ("horizontal", "vertical", "diagonal")
        if item in direction_kinds
    ) or "不明"
    position_en = "corner" if played in {"a1", "a8", "h1", "h8"} else (
        "edge" if move_x in (0, 7) or move_y in (0, 7) else "interior"
    )
    position_ja = "角" if position_en == "corner" else "端" if position_en == "edge" else "内側"

    pre_black, pre_white = _count_stones(pre_board)
    post_black, post_white = _count_stones(post_board)
    pre_balance, post_balance = pre_black - pre_white, post_black - post_white
    pre_gap, post_gap = abs(pre_balance), abs(post_balance)
    if pre_balance != 0 and post_balance == 0:
        situation_en, situation_ja = "the score became tied", "同点になった"
    elif pre_balance * post_balance < 0:
        situation_en, situation_ja = "the lead changed hands", "逆転した"
    elif post_gap > pre_gap:
        situation_en, situation_ja = "the gap widened", "差がひろがった"
    elif post_gap < pre_gap:
        situation_en, situation_ja = "the gap narrowed", "差が縮まった"
    else:
        situation_en, situation_ja = "the gap stayed the same", "差は変わらない"

    if language == CommentaryLanguage.ENGLISH:
        return (
            "## Move information\n\n"
            f"- Position evaluation before the move, from the mover's perspective: {position_eval_text}\n"
            f"- Move location: {position_en}\n"
            f"- Directions flipped: {directions_en}\n"
            f"- Disc count changed from Black {pre_black}, White {pre_white} to "
            f"Black {post_black}, White {post_white}\n"
            f"- Disc-count situation: {situation_en}"
        )
    return (
        "## 手の情報\n\n"
        f"- 着手前の盤面評価値（手番側視点）：{position_eval_text}\n"
        f"- 着手位置：{position_ja}\n"
        f"- ひっくり返した方向：{directions_ja}\n"
        f"- 石数変化：黒{pre_black}白{pre_white}から黒{post_black}白{post_white}に変化\n"
        f"- 石数の状況：{situation_ja}"
    )


def build_post_move_prompt(
    pre_state: dict[str, Any],
    post_state: dict[str, Any],
    played_move: str,
    style: str = "",
    language: object = CommentaryLanguage.JAPANESE,
) -> str:
    lang = normalize_commentary_language(language)
    played = (played_move or "").lower().strip()
    pre_moves = [str(move).lower() for move in (pre_state.get("moves") or [])]
    pre_evals = pre_state.get("evals") or {}
    style_text = style.strip()
    stance = _stance(pre_state, lang)

    if played == "pass":
        cause_move = str(post_state.get("cause_move") or "").lower().strip()
        cause_side = str(pre_state.get("turn") or "B").upper()
        passed_side = str(post_state.get("passed_side") or "").upper()
        if passed_side not in {"B", "W"}:
            passed_side = _opponent(cause_side)
        gain_side = _opponent(passed_side)
        core_move = cause_move or "pass"
        evals_text = _sorted_move_evals([core_move, *pre_moves], pre_evals, core_move, lang)
        if lang == CommentaryLanguage.ENGLISH:
            return f"""{_side_name(cause_side, lang)} played {core_move}, leaving {_side_name(passed_side, lang)} with no legal move and forcing a pass. {_side_name(gain_side, lang)} therefore gets another turn.

## Required content

- Explicitly state that {_side_name(passed_side, lang)} must pass.
- Explicitly state that {_side_name(gain_side, lang)} can move again.
- Convey how the move compared with the alternatives without stating any numeric evaluation.
- Write in this style: {style_text or 'an energetic and emotional sports commentator'}.
- Write 25 to 45 English words.

## Game phase

{stance}

## Legal moves and evaluations (never include the numeric values in the response)

```text
{evals_text}
```

## Output format

Return exactly one line in English:
```text
pass: "comment"
```"""
        return f"""{_side_name(cause_side, lang)}が{core_move}に打った結果、{_side_name(passed_side, lang)}が合法手なしでパスになりました。{_side_name(gain_side, lang)}は連続手番を得ています。

## 必須

- 「{_side_name(passed_side, lang)}がパス」の明示
- 「{_side_name(gain_side, lang)}がもう一度打てる」の明示
- 評価値そのものは書かず、ほかの候補との比較をニュアンスで示す
- 口調：{style_text or '感情的な実況者のような'}
- 70文字前後

## 局面の進行度

{stance}

## 打てた手とその評価値（具体的な値は回答に含めないでください）

```text
{evals_text}
```

## 出力形式

必ず1行のみ：
```text
pass: "コメント"
```"""

    core_move = played
    played_eval = pre_evals.get(core_move)
    missing = "None" if lang == CommentaryLanguage.ENGLISH else "（なし）"
    played_eval_text = str(played_eval) if played_eval is not None else missing
    evals_text = _sorted_move_evals([core_move, *pre_moves], pre_evals, core_move, lang)
    move_info = _move_info(pre_state, post_state, played, lang)
    if lang == CommentaryLanguage.ENGLISH:
        return f"""{_side_name(pre_state.get('turn'), lang)} played {core_move} (evaluation: {played_eval_text}). React like an emotional Othello commentator and convey whether this move was strong or weak compared with the other legal moves. Write 15 to 30 English words in this style: {style_text or 'an energetic and emotional sports commentator'}.

## Game phase

Treat moves 1-20 as the opening, 21-40 as the midgame, and 41-60 as the endgame.
{stance}

{move_info}

## Legal moves and evaluations (never include the numeric values in the response)

```text
{evals_text}
```

## Output format

Return exactly one line in English:
```text
{core_move}: "comment"
```"""
    return f"""オセロをしていて{_side_name(pre_state.get('turn'), lang)}が{core_move}（評価値：{played_eval_text}）に手を打ちました。この手がほかに打てた手と比べて良かったか悪かったかをニュアンスに含め、感情的な実況を40文字程度で生成してください。口調：{style_text or '感情的な実況者のような'}

## 局面の進行度

1〜20手目を序盤、21〜40手目を中盤、41〜60手目を終盤とみなします。
{stance}

{move_info}

## 打てた手とその評価値（具体的な値は回答に含めないでください）

```text
{evals_text}
```

## 出力形式（必ず1行のみ）

```text
{core_move}: "コメント"
```"""


def build_end_game_prompt(
    pre_state: dict[str, Any],
    post_state: dict[str, Any],
    end_info: dict[str, Any],
    style: str = "",
    language: object = CommentaryLanguage.JAPANESE,
) -> str:
    lang = normalize_commentary_language(language)
    reason = str(end_info.get("reason") or "").strip()
    winner = str(end_info.get("winner") or "").strip().upper()
    black, white = end_info.get("black"), end_info.get("white")
    core_move = str(post_state.get("last_move") or "").lower().strip() or "pass"
    next_turn = str(post_state.get("turn") or "").upper()
    played_side = "B" if next_turn == "W" else "W"
    evals = pre_state.get("evals") or {}
    played_eval = evals.get(core_move) if core_move != "pass" else None
    style_text = style.strip()

    if lang == CommentaryLanguage.ENGLISH:
        reason_text = {
            "double_pass": "neither Black nor White had a legal move",
            "board_full": "the board was completely full",
        }.get(reason, reason or "unknown")
        winner_text = "Draw" if winner == "D" else _side_name(winner, lang)
        evaluation_text = str(played_eval) if played_eval is not None else "unavailable"
        return f"""You are an emotional Othello commentator. {_side_name(played_side, lang)} played {core_move} (evaluation: {evaluation_text}), ending the game. Produce an exciting English closing comment.

## Required facts

- Reason the game ended: {reason_text}
- Result: {winner_text}
- Final disc count: Black {black}, White {white}
- Style: {style_text or 'an energetic and emotional sports commentator'}

## Output format

- Return exactly one line in English: `__end__: <comment>`
- Write 30 to 55 English words.
- Do not invent board details or unsupported analysis."""

    reason_text = {
        "double_pass": "黒と白ともに打てる手がない",
        "board_full": "盤面が全て埋まった",
    }.get(reason, reason or "不明")
    winner_text = "引き分け" if winner == "D" else _side_name(winner, lang)
    evaluation_text = str(played_eval) if played_eval is not None else "不明"
    return f"""あなたは感情的なオセロ実況者です。{_side_name(played_side, lang)}が{core_move}（評価値：{evaluation_text}）に手を打って終局しました。最終的な石数と勝者を明示する感情的な締めコメントを生成してください。

## 必須情報

- 終局理由：{reason_text}
- 結果：{winner_text}
- 最終石数：黒{black}、白{white}
- 口調：{style_text or '感情的な実況者のような'}

## 出力形式

- 必ず1行：`__end__: <コメント>`
- 80文字前後
- 盤面の具体や根拠のない分析は書かない"""
