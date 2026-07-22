#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import math
from typing import List, Dict, Any
from ollama import Client
from othello_commentator.llm.client_interface import LLMClient, DeltaCallback

MODEL_NAME = "gpt-oss:120b-cloud"


def _count_stones(board: list[list[str]]) -> tuple[int, int]:
    black = sum(cell == "B" for row in board for cell in row)
    white = sum(cell == "W" for row in board for cell in row)
    return black, white


def _sorted_move_evals(moves: list[str], evals: dict, played_move: str) -> str:
    """候補手を重複なく、数値評価の高い順（評価なしは末尾）に整形する。"""
    unique_moves = list(dict.fromkeys(move.lower() for move in moves if move))
    played = (played_move or "").lower().strip()

    def sort_key(move: str) -> tuple[int, float]:
        value = evals.get(move)
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return 1, 0.0
        if not math.isfinite(numeric_value):
            return 1, 0.0
        return 0, -numeric_value

    sorted_moves = sorted(unique_moves, key=sort_key)
    lines = [
        f"{move} （打たれた手）: {evals.get(move)}"
        if move == played
        else f"{move} : {evals.get(move)}"
        for move in sorted_moves
    ]
    return "\n".join(lines) if lines else "（なし）"


def _build_move_info(pre_view: dict, post_view: dict, played_move: str) -> str:
    """盤面をプロンプトへ載せず、着手による変化だけを要約する。"""
    pre_board = pre_view.get("board")
    post_board = post_view.get("board")
    played = (played_move or "").lower().strip()
    position_eval = pre_view.get("pos_eval")
    position_eval_txt = str(position_eval) if position_eval is not None else "（なし）"

    if not (
        isinstance(pre_board, list)
        and isinstance(post_board, list)
        and len(pre_board) == 8
        and len(post_board) == 8
        and all(isinstance(row, list) and len(row) == 8 for row in pre_board)
        and all(isinstance(row, list) and len(row) == 8 for row in post_board)
        and len(played) == 2
        and played[0] in "abcdefgh"
        and played[1] in "12345678"
    ):
        return (
            "## 手の情報\n\n"
            f"- 着手前の盤面評価値（手番側視点）：{position_eval_txt}\n"
            "- ひっくり返した方向：不明\n"
            "- 石数変化：不明\n"
            "- 石数の状況：不明"
        )

    move_x = ord(played[0]) - ord("a")
    move_y = int(played[1]) - 1
    mover = (pre_view.get("turn") or "").upper()
    opponent = "W" if mover == "B" else "B"
    direction_kinds: set[str] = set()

    if mover in ("B", "W"):
        for y in range(8):
            for x in range(8):
                if pre_board[y][x] != opponent or post_board[y][x] != mover:
                    continue
                dx, dy = x - move_x, y - move_y
                if dy == 0:
                    direction_kinds.add("横")
                elif dx == 0:
                    direction_kinds.add("縦")
                elif abs(dx) == abs(dy):
                    direction_kinds.add("斜め")

    direction_order = ("横", "縦", "斜め")
    directions = "・".join(item for item in direction_order if item in direction_kinds) or "不明"

    if played in {"a1", "a8", "h1", "h8"}:
        position_info = "- 着手位置：角\n"
    elif move_x in (0, 7) or move_y in (0, 7):
        position_info = "- 着手位置：端\n"
    else:
        position_info = ""

    pre_black, pre_white = _count_stones(pre_board)
    post_black, post_white = _count_stones(post_board)
    pre_balance = pre_black - pre_white
    post_balance = post_black - post_white
    pre_gap = abs(pre_black - pre_white)
    post_gap = abs(post_black - post_white)
    if pre_balance != 0 and post_balance == 0:
        gap_change = "同点になった"
    elif pre_balance * post_balance < 0:
        gap_change = "逆転した"
    elif post_gap > pre_gap:
        gap_change = "差がひろがった"
    elif post_gap < pre_gap:
        gap_change = "差が縮まった"
    else:
        gap_change = "差は変わらない"

    return (
        "## 手の情報\n\n"
        f"- 着手前の盤面評価値（手番側視点）：{position_eval_txt}\n"
        f"{position_info}"
        f"- ひっくり返した方向：{directions}\n"
        f"- 石数変化：黒{pre_black}白{pre_white}から黒{post_black}白{post_white}に変化\n"
        f"- 石数の状況：{gap_change}"
    )


def _phase_and_stance(pre_view: dict) -> tuple[str, str, int, str, str]:
    """共通：進行度（phase/stance）と手番表記を作る"""
    turn = pre_view.get("turn")
    turn_jp = "黒" if turn == "B" else "白"

    move_no = int(pre_view.get("move_no") or 0)
    next_move_no = max(1, min(60, move_no + 1))

    if next_move_no <= 20:
        phase = "序盤"
        stance = (
            f"打たれた手は、最大60手中およそ{next_move_no}手目で序盤の手です。"
            f"形勢はまだ大きく動きにくいので、大袈裟に断定せず、主に構想や狙い、今後の展開の可能性を語ってください。"
            f"感情表現はやや抑えめにしつつ、これから始まる勝負への期待感を演出してください。"
        )
    elif next_move_no <= 40:
        phase = "中盤"
        stance = (
            f"打たれた手は、最大60手中およそ{next_move_no}手目で中盤の手です。"
            f"局面が動きやすいので、狙いとリスクを手短に示しつつ、感情は盛り上げ気味で実況してください。"
        )
    else:
        phase = "終盤"
        stance = (
            f"打たれた手は、最大60手中およそ{next_move_no}手目で終盤の手です。"
            f"勝敗に直結しやすいので、結果への緊張感を強めに、ただし根拠は簡潔に実況してください。"
        )

    return phase, stance, next_move_no, turn, turn_jp


def _common_post_prompt(
    head: str,
    stance: str,
    move_info: str,
    others_txt: str,
    output_key: str,
) -> str:
    """共通：プロンプト本文を組み立て"""
    return f"""{head}

## 局面の進行度

1〜20手目を序盤、21〜40手目を中盤、41〜60手目を終盤とみなします。
{stance}

{move_info}

## 打てた手とその評価値（この評価値の具体的な値は回答に含めないでください）

```text
{others_txt}
```

## 出力形式(必ず1行のみ)

```text
{output_key} : ""
```
"""


def build_post_move_prompt_normal(pre_view: dict, post_view: dict, played_move: str) -> str:
    """通常手用（played_move が a1-h8）"""
    phase, stance, next_move_no, turn, turn_jp = _phase_and_stance(pre_view)

    played = played_move.lower()
    pre_moves = [m.lower() for m in (pre_view.get("moves") or [])]
    pre_evals = pre_view.get("evals") or {}

    core_move = played
    played_eval = pre_evals.get(core_move)
    played_eval_txt = str(played_eval) if played_eval is not None else "（なし）"

    others_txt = _sorted_move_evals([core_move, *pre_moves], pre_evals, core_move)
    move_info = _build_move_info(pre_view, post_view, played)

    head = (
        f"オセロをしていて{turn_jp}が{core_move}（評価値：{played_eval_txt}）に手を打ちました。"
        f"この手が他に打てた手と比べて良かったのか悪かったのかニュアンスに含めながら、感情的な実況者のようなリアクションを生成してください。"
        f"また局面の進行度（序盤/中盤/終盤）を考慮した上で、出力形式に合わせて40文字程度になるようにしてください。"
    )

    return _common_post_prompt(
        head=head,
        stance=stance,
        move_info=move_info,
        others_txt=others_txt,
        output_key=played,  # 通常は "d6" など
    )


def build_post_move_prompt_pass(pre_view: dict, post_view: dict) -> str:
    """パス用（played_move == 'pass' のとき）"""
    phase, stance, next_move_no, turn, turn_jp = _phase_and_stance(pre_view)

    # ★PASS専用：指示が埋もれないようにスタンス文を短縮
    if phase == "序盤":
        stance = f"次はおよそ{next_move_no}手目の序盤。断定しすぎず、構想と期待感を中心に実況。"

    pre_moves = [m.lower() for m in (pre_view.get("moves") or [])]
    pre_evals = pre_view.get("evals") or {}

    cause_move = (post_view.get("cause_move") or "").lower().strip()
    passed_side = (post_view.get("passed_side") or "").strip()  # "B" or "W" が来る想定

    def _jp(side: str) -> str:
        return "黒" if side == "B" else "白"

    def _opp(side: str) -> str:
        return "W" if side == "B" else "B"

    # 原因手を打った側（=着手前手番）
    cause_side = pre_view.get("turn")  # "B" or "W"

    # passed_side が来てない場合の保険：原因手を打った側の反対がパス側
    if passed_side not in ("B", "W"):
        passed_side = _opp(cause_side)

    # 連続手番を得た側（= パスした側の反対 = cause側と一致するはず）
    gain_side = _opp(passed_side)

    # PASS時の評価対象は「原因手」
    core_move = cause_move if cause_move else "pass"
    played_eval = pre_evals.get(core_move)
    played_eval_txt = str(played_eval) if played_eval is not None else "（なし）"

    others_txt = _sorted_move_evals([core_move, *pre_moves], pre_evals, core_move)

    # 事実の2行（黒/白どちらでも動く）
    pass_intro = (
        f"{_jp(cause_side)}が{core_move}に打った結果、{_jp(passed_side)}が合法手なしでパスになりました。\n"
        f"{_jp(gain_side)}は連続手番を得ています。"
    )

    # ★必須条件も「黒/白」を直書きせず、変数で作る
    must_pass = f"「{_jp(passed_side)}がパス」"
    must_gain = f"「{_jp(gain_side)}がもう一度打てる（連続手番）」"

    head = f"""{pass_intro}

## 必須（コメント内に必ず入れる）

- {must_pass} の明示（同じ意味なら言い換え可）
- {must_gain} の明示（同じ意味なら言い換え可）

## 狙い

原因手（{core_move}）が他候補と比べて最善かはニュアンスで触れてください。
ただし「{_jp(passed_side)}をパスに追い込み、{_jp(gain_side)}が連続手番で主導権を取った」意味合いは必ず入れてください（表現は任せます）。

## 文字数

70文字前後

## 出力ルール

- 出力は必ず1行のみ
- 形式は厳守：pass : "..."
- 必須2点が欠けたら作り直し"""

    return _common_post_prompt(
        head=head,
        stance=stance,
        move_info="",
        others_txt=others_txt,
        output_key="pass",
    )


def build_post_move_prompt(pre_view: dict, post_view: dict, played_move: str) -> str:
    """入口：通常/パスを振り分け"""
    played = (played_move or "").lower().strip()
    if played == "pass":
        return build_post_move_prompt_pass(pre_view, post_view)
    return build_post_move_prompt_normal(pre_view, post_view, played_move)

def build_prompt_end_game(
    pre_state: Dict[str, Any],
    post_state: Dict[str, Any],
    end_info: Dict[str, Any],
    style: str,
) -> str:
    """
    main.py から END: を受け取ったときに呼ばれる想定。
    end_info:
      {"reason":"double_pass"|"board_full", "winner":"B"|"W"|"D", "black":34, "white":30}

    返すプロンプトは必ず __end__: 1行だけ出させる。
    """
    reason = (end_info.get("reason") or "").strip()
    winner = (end_info.get("winner") or "").strip().upper()
    black = end_info.get("black")
    white = end_info.get("white")

    # reason_txt はコード側で固定（ユーザー指定）
    if reason == "double_pass":
        reason_txt = "黒と白ともに打てる手がない"
    elif reason == "board_full":
        reason_txt = "盤面が全て埋まった"
    else:
        reason_txt = reason or "不明"

    # core_move は「終局直前の最後の着手」(post_state 側にある想定)
    core_move = (post_state.get("last_move") or "").lower().strip() or "pass"

    # 終局した手を打った側：post_state['turn'] は「次の手番」なので逆
    next_turn = (post_state.get("turn") or "").upper().strip()
    played_side = "B" if next_turn == "W" else "W"
    turn_jp = "黒" if played_side == "B" else "白"

    # 評価値：着手前(pre_state)の evals から core_move を拾う（pass は "—"）
    played_eval_txt = "—" if core_move == "pass" else "不明"
    if core_move != "pass":
        evals = pre_state.get("evals") or {}
        if isinstance(evals, dict) and (core_move in evals) and (evals.get(core_move) is not None):
            played_eval_txt = str(evals.get(core_move))

    # スタイル（将来拡張用）：今回は文面は固定で、最後に口調ヒントだけ軽く付ける
    style_hint = f"\n\n## 口調\n\n- {style}" if style else ""

    prompt = f"""あなたは感情的なオセロ実況者です。{turn_jp}が{core_move}（評価値：{played_eval_txt}）に手を打って終局しました。黒と白の最終的なコマ数と勝者を明示する感情的なコメントお願いします。。

## 終局情報

- 終局理由：{reason_txt}の明示（同じ意味で可能な限り言い換える）
- 勝者：{winner}の明示（引き分けの場合は「引き分け」）
- 黒のコマ数：{black}の明示
- 白のコマ数：{white}の明示

## 出力形式

- 1行のみ、必ずこの形：
  `__end__: <本文>`
- 本文は合計80字前後
- 盤面の具体（角、辺、手順、どこに置いた等）は言わない。根拠のない分析は禁止。
- 代わりに抽象的に盛り上げる（「粘り勝ち」「逃げ切り」「最後まで拮抗」など）{style_hint}
"""
    # 将来のための置換（今回テンプレに<<STYLE>>は無いが一応）
    return prompt.replace("<<STYLE>>", style)

class OllamaClient(LLMClient):
    def __init__(self):
        # 環境変数 OLLAMA_DIRECT=1 ならクラウドAPI、なければローカルの ollama デーモン
        use_direct = os.environ.get("OLLAMA_DIRECT", "0") == "1"

        if use_direct:
            self.client = Client(
                host="https://ollama.com",
                headers={"Authorization": "Bearer " + os.environ["OLLAMA_API_KEY"]},
            )
            self.model = "gpt-oss:120b"
        else:
            self.client = Client()  # 既定: http://localhost:11434
            self.model = MODEL_NAME

    def build_prompt_from_state(self, state: Dict[str, Any]) -> str:
        # post-only運用では基本使わない。万一呼ばれた時の保険。
        turn = state.get("turn", "B")
        turn_jp = "黒" if turn == "B" else "白"
        lm = (state.get("last_move") or "")
        return (
            f"post-only mode. 直前手={lm} / 次手番={turn_jp}。\n"
            "このメソッドは通常使われません。"
        )

    def send_chat(self, prompt: str, callback: DeltaCallback) -> str:
        """
        main.py 側からは full = client.send_chat(prompt, on_delta) の形で呼ばれる想定。
        - prompt: すでに <<STYLE>> 置換済み
        - callback: 逐次トークンを GUI に流す関数
        戻り値: 生成された全文テキスト
        """
        full_chunks: list[str] = []

        stream = self.client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            think='low',
            options={"temperature": 0.2},
            stream=True,
        )

        for part in stream:
            chunk = part.get("message", {}).get("content", "")
            if chunk:
                full_chunks.append(chunk)
                callback(chunk)

        # 行末を整えるための軽い改行（必要に応じて削ってOK）
        callback("\n")

        return "".join(full_chunks)
    
    def build_prompt_post_move(
        self,
        pre_state: Dict[str, Any],
        post_state: Dict[str, Any],
        played_move: str,
        style: str,
    ) -> str:
        # ここで「着手後実況」テンプレを組む
        p = build_post_move_prompt(pre_state, post_state, played_move)

        # <<STYLE>> が出てくる可能性があるならここで置換（今のテンプレには無いけど将来のため）
        return p.replace("<<STYLE>>", style)
    
    def build_prompt_end_game(
       self,
        pre_state: Dict[str, Any],
        post_state: Dict[str, Any],
        end_info: Dict[str, Any],
        style: str,
    ) -> str:
        # main.py から client.build_prompt_end_game(...) で呼ばれるため、メソッドとして生やす
        p = build_prompt_end_game(
            pre_state=pre_state,
            post_state=post_state,
            end_info=end_info,
            style=style,
        )
        return p.replace("<<STYLE>>", style)
