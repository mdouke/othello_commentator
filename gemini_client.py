# gemini_client.py
from __future__ import annotations
import os
import time
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv
from llm_iface import LLMClient, DeltaCallback

# テキスト特化モデル (軽量高速)
_MODEL_NAME = "gemini-2.5-pro"

class GeminiClient(LLMClient):
    def __init__(
        self,
        model_name: str = _MODEL_NAME,
        env_path: Path | None = None,
    ) -> None:
        load_dotenv(env_path)
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY が .env に見つかりません")

        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model_name)

    # --- LLMClient 実装 --------------------------------------------------
    def send_chat(
        self,
        user_text: str,
        on_delta: DeltaCallback | None = None,
        extra_meta=None,
    ) -> str:
        """
        Gemini は ChatGPT と違い `start_chat` で session を作り、
        .send_message(..) でストリームが取れる。
        """
        chat = self._model.start_chat(history=[])
        full = []

        rsp = chat.send_message(user_text, stream=True)
        for chunk in rsp:
            # text プロパティが無い / Parts が空のチャンクをスキップ
            try:
                delta = chunk.text
            except ValueError:
                continue          # finish_reason=STOP など、実テキストの無いチャンク
            if not delta:
                continue
            full.append(delta)
            if on_delta:
                on_delta(delta)
            # Gemini の stream は rate‑limit のため sleep が必要な場合あり
            time.sleep(0.01)

        return "".join(full)

    def build_prompt_from_state(self, state: dict) -> str:
        """
        ChatGPT 版と共通で良ければファイルを import して流用。
        例では簡易に直接書く。
        """
        turn_jp = "黒" if state["turn"] == "B" else "白"
        ascii_board = "\n".join(state["ascii"]).replace("P", "E")
        moves_block = "\n".join(f"{m} :" for m in state["moves"])
        return (
            f"オセロをしていて{turn_jp}の番で、盤面は以下の通りです。"
            f"差し手がそれぞれの合法手に置いたときの<<STYLE>>"
            f"リアクションを出力形式に合わせて答えてください。またそれぞれの手へのリアクションが40文字程度になるようにしてください。\n\n"
            "ASCHII形式での表示方法\n"
            ". : 何もないマス\n"
            "B : 黒のコマがおかれているマス\n"
            "W : 白のコマがおかれているマス\n"
            f"E : {turn_jp}の合法手\n\n"
            "解答形式:\n" \
            "a1 : ここに<<STYLE>>リアクションを入れてください\n"
            "b2 : ここに<<STYLE>>リアクションを入れてください\n"
            "盤面\n"
            f"{ascii_board}\n\n"
            "出力形式\n"
            f"{moves_block}"
        )
