# llm_iface.py
from __future__ import annotations
from typing import Callable, Iterable, Optional, Protocol, Any, Dict

DeltaCallback = Callable[[str], None]

class LLMClient(Protocol):
    def send_chat(
        self,
        user_text: str,
        on_delta: Optional[DeltaCallback] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """ユーザー発話を送信。ストリーム delta ごとに on_delta を呼ぶ。最終全文を返す。"""
        ...

    def build_prompt_from_state(self, state: dict) -> str:
        """Othello状態からChatGPT向けプロンプト文字列を生成。"""
        ...
