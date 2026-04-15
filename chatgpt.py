from __future__ import annotations
import os, json, logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Dict, Any, List

from dotenv import load_dotenv
from openai import OpenAI
from llm_iface import LLMClient, DeltaCallback
from project_paths import ARTIFACTS_DIR, ensure_dir

log = logging.getLogger(__name__)

# ========== 会話ログ ==========
class ConversationLog:
    def __init__(self, path: Path):
        self.path = path
        self.messages: List[Dict[str, str]] = [
            {"role": "system", "content": "You are a helpful assistant."}
        ]

    def append(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            json.dump(
                {"ts": datetime.now().isoformat(), "role": role, "content": content},
                f,
                ensure_ascii=False,
            )
            f.write("\n")


# ========== Prompt生成（VIEW前提でASCIIを自前生成） ==========
def build_prompt_from_state_chatgpt(state: dict) -> str:
    turn = state.get("turn", "B")
    turn_jp = "黒" if turn == "B" else "白"

    board = state.get("board") or [["."] * 8 for _ in range(8)]
    moves: list[str] = state.get("moves", []) or []
    evals: dict[str, float] = state.get("evals") or {}

        # --- 手数と序盤/中盤/終盤 ---
    raw_move_no = state.get("move_no")
    move_info_text = ""
    if isinstance(raw_move_no, (int, float)):
        # 0開始の手数（これまでに指された手数）
        move_no_0 = int(raw_move_no)
        move_no_0 = max(0, min(60, move_no_0))

        # ★ これから指される次の1手が何手目か（1〜60にクリップ）
        next_move_no = max(1, min(60, move_no_0 + 1))

        # ★ フェーズ判定は「次の1手」が属する区間で行う
        if 1 <= next_move_no <= 20:
            phase_jp = "序盤"
            stance_text = (
                "形勢はまだ大きく動きにくいので、大袈裟に断定せず、"
                "主に構想や狙い、今後の展開の可能性を語ってください。"
                "感情表現はやや抑えめにしつつ、これから始まる勝負への期待感を演出してください。"
            )
        elif 21 <= next_move_no <= 40:
            phase_jp = "中盤"
            stance_text = (
                "可動域（打てる手の多さ）や形勢の変化をしっかり言語化し、"
                "辺や隅を巡る攻防などこの局面ならではのテーマを強調してください。"
                "感情表現は中程度〜やや強めにして、勝負の分岐点になりそうな緊張感を演出してください。"
            )
        else:
            phase_jp = "終盤"
            stance_text = (
                "残り手数が少なく勝敗に直結する局面として、1手の重みや読みの正確さを強調してください。"
                "どの程度勝敗に影響しうる手かをはっきり述べ、感情表現は強めにしてクライマックス感や"
                "逆転のドラマ性を演出してください。"
            )

        move_info_text = (
            "1〜20手目を序盤、21〜40手目を中盤、41〜60手目を終盤とみなします。\n"
            f"次に指される手は、最大60手中およそ{next_move_no}手目で{phase_jp}の手です。"
            f"{stance_text}\n\n"
        )
    else:
        move_info_text = (
            "この局面が序盤・中盤・終盤のどこにあたるかは、石数や空きマス数から推測し、"
            "1〜20手目を序盤、21〜40手目を中盤、41〜60手目を終盤とみなして解説してください。\n"
            "序盤では形勢を断定しすぎず構想や狙いを中心に、感情は抑えめで期待感を演出してください。"
            "中盤では可動域や形勢の変化、攻防のテーマを言語化し、やや強めの感情表現で勝負の分岐点を描写してください。"
            "終盤では読みの精度と1手の重み、勝敗への直結を強調し、感情を強く出してクライマックス感を演出してください。\n\n"
        )


    # --- 形勢推移（1ターンごとの履歴） ---
    history = state.get("turn_history") or []
    history_text = ""
    if isinstance(history, list) and history:
        recent = history
        lines: list[str] = []
        start_idx = len(history) - len(recent) + 1

        for offset, entry in enumerate(recent):
            if not isinstance(entry, dict):
                continue
            idx = start_idx + offset
            end_move_no = entry.get("end_move_no")
            beval = entry.get("black_eval")
            side = entry.get("side", "B")

            if beval is None or end_move_no is None:
                continue
            try:
                beval_f = float(beval)
                end_move_no = int(end_move_no)
            except Exception:
                continue

            side_jp = "黒" if side == "B" else "白"
            human_move_no = max(0, min(60, end_move_no))
            lines.append(
                f"第{idx}ターン終了時（{side_jp}の手番が再び巡ってきた局面・手数{human_move_no}手付近）:"
                f" 黒視点評価 {beval_f:+.2f}"
            )

        if lines:
            history_text = (
                "ここまでの1ターンごとの形勢推移（黒視点）の概要です。\n"
                "プラスなら黒有利、マイナスなら白有利とみなしてください。\n"
                + "\n".join(lines)
                + "\n\n"
            )

    # ★ 形勢推移をプロンプトに含めるかどうか（turn_history が無い/空なら使わない）
    trend_phrase = "そしてこれまでの形勢推移を参考に、" if history_text else ""

    # --- ASCII 盤面 ---
    ascii_board = ascii_from_board(board, moves)

    # --- 各手の評価値 ---
    eval_lines: list[str] = []
    for m in moves:
        v = evals.get(m)
        if v is None:
            continue
        try:
            fv = float(v)
        except Exception:
            continue
        eval_lines.append(f"{m} : {fv:+.2f}")

    if eval_lines:
        eval_block = "\n".join(eval_lines)
        eval_header = (
            "各手の評価値（現在の手番である"
            f"{turn_jp}から見た評価値。数値が大きいほど{turn_jp}に有利とみなしてください）\n\n"
        )
        eval_text = eval_header + eval_block + "\n\n"
    else:
        eval_text = "各手の評価値は利用できませんでした。\n\n"

    # --- 出力フォーマット ---
    moves_block = "\n".join(f"{m} : \"\"" for m in moves)

    return (
        f"オセロをしていて{turn_jp}の番で、盤面は以下の通りです。"
        f"差し手がそれぞれの合法手に置いたときの<<STYLE>>"
        "リアクションを、各手の評価値と局面の進行度（序盤/中盤/終盤）、"
        f"{trend_phrase}"
        "出力形式に合わせて答えてください。"
        "またそれぞれの手へのリアクションが40文字程度になるようにしてください。\n\n"
        f"{move_info_text}"
        f"{history_text}"
        "ASCHII形式での表示方法\n"
        ". : 何もないマス\n"
        "B : 黒のコマがおかれているマス\n"
        "W : 白のコマがおかれているマス\n"
        f"E : {turn_jp}の合法手\n\n"
        "盤面\n"
        f"{ascii_board}\n\n"
        f"{eval_text}"
        "出力形式\n"
        f"{moves_block}"
    )

# ========== ChatGPTクライアント ==========
class ChatGPTClient(LLMClient):
    def __init__(
        self,
        env_path: Path,
        model: str = "gpt-4o",
        conv_log_path: Path = ensure_dir(ARTIFACTS_DIR) / "conversation.jsonl",
        sys_prompt: str = "You are a helpful assistant.",
    ) -> None:
        load_dotenv(env_path)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not found in .env")
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.conv = ConversationLog(conv_log_path)
        if sys_prompt != self.conv.messages[0]["content"]:
            self.conv.messages[0]["content"] = sys_prompt

    def send_chat(self, user_text: str, on_delta: Optional[DeltaCallback] = None, extra_meta: Optional[Dict[str, Any]] = None) -> str:
        messages = self.conv.messages + [{"role": "user", "content": user_text}]
        params = dict(model=self.model, messages=messages, stream=bool(on_delta))
        full_text = []
        try:
            if on_delta:
                stream = self.client.chat.completions.create(**params)
                for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        full_text.append(delta)
                        on_delta(delta)
            else:
                res = self.client.chat.completions.create(**params)
                text = res.choices[0].message.content
                full_text.append(text)
        except Exception:
            log.exception("OpenAI error")
        self.conv.append("user", user_text)
        if full_text:
            self.conv.append("assistant", "".join(full_text))
        return "".join(full_text)

    def build_prompt_from_state(self, state: dict) -> str:
        return build_prompt_from_state_chatgpt(state)
    
# ========== ヘルパー：座標とASCII生成 ==========
_FILES = "abcdefgh"
_RANKS = "12345678"

def coord_to_rc(coord: str) -> tuple[int, int] | None:
    """'c5' → (row_idx, col_idx) 0-based に変換。無効ならNone。"""
    if not coord or len(coord) != 2:
        return None
    f, r = coord[0], coord[1]
    if f not in _FILES or r not in _RANKS:
        return None
    col = _FILES.index(f)
    row = _RANKS.index(r)
    return (row, col)

def ascii_from_board(board: list[list[str]], moves: list[str] | None = None) -> str:
    """
    board: 8x8, 各セルは 'B' / 'W' / '.' を想定（★ここはVIEW済みを受け取る）
    moves: ['c5', 'e3', ...] （VIEW座標）
    戻り値: 
    例のヘッダーを含めたASCIIブロック
      / a b c d e f g h
      1 . . . . . . . .
      ...
    """
    # 盤面コピー（合法手上書き用）
    grid = [row[:] for row in board] if board else [["."] * 8 for _ in range(8)]

    # 合法手を 'E' で上書き（VIEW座標そのまま）
    if moves:
        for m in moves:
            rc = coord_to_rc(m)
            if rc:
                r, c = rc
                # 盤外/不正値チェック
                if 0 <= r < 8 and 0 <= c < 8:
                    grid[r][c] = "E"

    # 表示行を組み立て
    lines = []
    lines.append("/ " + " ".join(_FILES))
    for i in range(8):
        row_label = _RANKS[i]
        row_cells = " ".join(grid[i])
        lines.append(f"{row_label} {row_cells}")
    return "\n".join(lines)
