#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from typing import Any

from ollama import Client

from othello_commentator.llm.client_interface import DeltaCallback, LLMClient

MODEL_NAME = "gpt-oss:120b-cloud"


class OllamaClient(LLMClient):
    """Ollama transport; language-specific prompts are built outside providers."""

    def __init__(self) -> None:
        use_direct = os.environ.get("OLLAMA_DIRECT", "0") == "1"
        if use_direct:
            self.client = Client(
                host="https://ollama.com",
                headers={"Authorization": "Bearer " + os.environ["OLLAMA_API_KEY"]},
            )
            self.model = "gpt-oss:120b"
        else:
            self.client = Client()
            self.model = MODEL_NAME

    def build_prompt_from_state(self, state: dict[str, Any]) -> str:
        """Compatibility method for the existing LLMClient protocol."""
        turn = "Black" if state.get("turn", "B") == "B" else "White"
        last_move = state.get("last_move") or ""
        return f"post-only mode. Previous move={last_move}; next turn={turn}."

    def send_chat(self, prompt: str, callback: DeltaCallback) -> str:
        full_chunks: list[str] = []
        stream = self.client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            think="low",
            options={"temperature": 0.2},
            stream=True,
        )
        for part in stream:
            chunk = part.get("message", {}).get("content", "")
            if chunk:
                full_chunks.append(chunk)
                callback(chunk)
        callback("\n")
        return "".join(full_chunks)
