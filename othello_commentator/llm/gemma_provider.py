# gemma_provider.py
from __future__ import annotations
import logging
from typing import Optional, Callable, Dict, Any, List

from othello_commentator.llm.client_interface import LLMClient, DeltaCallback

log = logging.getLogger(__name__)

# ----------------- lazy import placeholders -----------------
_torch = None
_AutoTokenizer = None
_AutoModelForCausalLM = None


def _ensure_imports():
    """Import torch/transformers on first use."""
    global _torch, _AutoTokenizer, _AutoModelForCausalLM
    if _torch is not None:
        return
    import torch as _t
    from transformers import AutoTokenizer as _AT, AutoModelForCausalLM as _AM
    _torch = _t
    _AutoTokenizer = _AT
    _AutoModelForCausalLM = _AM
    log.info("[Gemma] Imported torch/transformers.")


# ----------------- streaming chunk helper -----------------
def _split_for_stream(text: str, chunk_chars: int = 40):
    lines = text.splitlines(keepends=True)
    for ln in lines:
        if len(ln) <= chunk_chars:
            yield ln
        else:
            for i in range(0, len(ln), chunk_chars):
                yield ln[i:i+chunk_chars]


# ----------------- prompt template -----------------
def build_prompt_from_state_gemma(state: dict) -> str:
    turn_jp = "黒" if state["turn"] == "B" else "白"
    ascii_board = "\n".join(state["ascii"]).replace("P", "E")
    moves_block = "\n".join(f"{m} : " for m in state["moves"])
    return (
        f"次は{turn_jp}の番です。以下のオセロ盤面があります。\n"
        f"各合法手に{turn_jp}が置いたときの<<STYLE>>リアクションを日本語で出力してください。\n"
        "● 出力形式は『c5 : ○○』のように、1手につき1行。\n"
        "● 各リアクションは最低10文字。\n"
        "● 全部の合法手について<<STYLE>>反応を書いてください。\n\n"
        "盤面の表示方法:\n"
        ". : 何もないマス\n"
        "B : 黒のコマがおかれているマス\n"
        "W : 白のコマがおかれているマス\n"
        f"E : {turn_jp}の合法手\n\n"
        "解答形式:\n" \
        "a1 : 'ここに<<STYLE>>リアクションを入れてください'\n"
        "b2 : 'ここに<<STYLE>>リアクションを入れてください'\n"
        "盤面:\n"
        f"{ascii_board}\n\n"
        "出力対象（座標一覧）:\n"
        f"{moves_block}"
    )


# ----------------- lightweight conversation -----------------
class GemmaConversation:
    def __init__(self, system: str | None = None):
        self.messages: List[Dict[str, str]] = []
        if system:
            self.messages.append({"role": "system", "content": system})

    def append(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def build_chat_text(self, tokenizer, add_generation_prompt: bool = True) -> str:
        return tokenizer.apply_chat_template(
            self.messages,
            tokenize=False,
            add_generation_prompt=add_generation_prompt,
        )


# ----------------- global caches -----------------
_MODEL_CACHE: Dict[tuple, Any] = {}
_TOKENIZER_CACHE: Dict[tuple, Any] = {}


def _load_model(model_name: str, device: str, dtype) -> tuple[Any, Any]:
    """
    Return (model, tokenizer) using global caches.
    """
    _ensure_imports()
    key = (model_name, device, dtype)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key], _TOKENIZER_CACHE[key]

    tok = _AutoTokenizer.from_pretrained(model_name)

    # build model
    mdl = _AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=dtype,
        device_map=None,
    )
    mdl = mdl.to(device)

    _MODEL_CACHE[key] = mdl
    _TOKENIZER_CACHE[key] = tok
    return mdl, tok


# ----------------- GemmaClient -----------------
class GemmaClient(LLMClient):
    def __init__(
        self,
        model_name: str = "google/gemma-2-2b-jpn-it",
        device: str = "mps",
        dtype: Any = None,  # set after import
        max_new_tokens: int = 512,
        temperature: float = 1.0,
        top_p: float = 0.9,
        repetition_penalty: float = 1.1,
        system_prompt: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self._dtype_req = dtype  # hold raw; resolved on load
        self.generation_args = dict(
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
        )
        self.conv = GemmaConversation(system_prompt)
        self._model = None
        self._tokenizer = None

    def _ensure_loaded(self):
        if self._model is not None:
            return
        _ensure_imports()
        # resolve dtype default
        dtype = self._dtype_req
        if dtype is None:
            # safe fallback
            try:
                dtype = _torch.float16
            except Exception:
                dtype = _torch.float32
        mdl, tok = _load_model(self.model_name, self.device, dtype)
        self._model = mdl
        self._tokenizer = tok
        log.info("[Gemma] Loaded model %s on %s.", self.model_name, self.device)

    @property
    def tok(self):
        self._ensure_loaded()
        return self._tokenizer

    @property
    def model(self):
        self._ensure_loaded()
        return self._model

    # ----- LLMClient API -----
    def send_chat(
        self,
        user_text: str,
        on_delta: Optional[DeltaCallback] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        self.conv.append("user", user_text)

        tok = self.tok
        mdl = self.model

        chat_txt = self.conv.build_chat_text(tok, add_generation_prompt=True)
        inputs = tok(chat_txt, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        gen_args = dict(self.generation_args)
        if extra_meta:
            gen_args.update(extra_meta)

        with _torch.no_grad():
            out = mdl.generate(
                **inputs,
                pad_token_id=tok.eos_token_id,
                **gen_args,
            )

        # decode only new part
        inp_len = inputs["input_ids"].shape[1]
        gen_txt = tok.decode(out[0][inp_len:], skip_special_tokens=True).strip()

        # pseudo-stream
        if on_delta:
            for chunk in _split_for_stream(gen_txt):
                on_delta(chunk)

        self.conv.append("assistant", gen_txt)
        return gen_txt

    def build_prompt_from_state(self, state: dict) -> str:
        return build_prompt_from_state_gemma(state)
