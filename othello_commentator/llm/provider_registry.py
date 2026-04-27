#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

def build_providers() -> dict[str, object]:
    """
    既存 main.py と同等のプロバイダ初期化を行い、辞書で返す。
    キーは UI で表示されるプロバイダ名。
    """
    env_path = Path(__file__).resolve().parents[2] / ".env"

    providers: dict[str, object] = {}

    def register_provider(name: str, factory) -> None:
        try:
            providers[name] = factory()
        except Exception as e:
            log.warning("%s unavailable: %s", name, e)

    def build_chatgpt():
        from othello_commentator.llm.openai_provider import ChatGPTClient

        return ChatGPTClient(env_path=env_path, model="gpt-4o")

    def build_gemini():
        from othello_commentator.llm.gemini_provider import GeminiClient

        return GeminiClient(env_path=env_path)

    def build_ollama():
        from othello_commentator.llm.ollama_provider import OllamaClient

        return OllamaClient()

    def build_gemma():
        from othello_commentator.llm.gemma_provider import GemmaClient

        return GemmaClient(
            model_name="google/gemma-2-2b-jpn-it",
            device="mps",
        )

    register_provider(
        "ChatGPT 4o",
        build_chatgpt,
    )
    register_provider(
        "Gemini 2.5 Pro",
        build_gemini,
    )
    register_provider(
        "GPT-OSS 120B Cloud",
        build_ollama,
    )

    # Gemma はオプション（torch 未導入環境でも他が動くように try）
    register_provider(
        "Gemma 2.2b",
        build_gemma,
    )

    if not providers:
        raise RuntimeError("利用可能な LLM プロバイダがありません。.env やローカル実行環境を確認してください。")

    log.info("LLM providers ready: %s", ", ".join(providers.keys()))
    return providers
