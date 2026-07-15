from __future__ import annotations

import threading
import time
from typing import Any, Callable

from othello_commentator.storage.ollama_comment_store import append_post as ollama_append_post
from othello_commentator.llm.comment_parser import parse_comment_for_move
from othello_commentator.app.session_state import RuntimeState
from othello_commentator.domain.board_state import FlipState, transform_state
from othello_commentator.storage.eval_history_store import eval_history_store


COMMENT_MODE_INSTRUCTIONS = {
    "実況コメント": "通常のオセロ実況として、局面の熱量と重要点を自然に伝えてください。",
    "常に優しいコメント": "常に大げさなくらい褒め称える口調にしてください。手だけでなく、勇気、発想、粘り、勝負勘、人柄まで肯定し、どんな局面でも称賛を中心にしてください。",
    "常にきついコメント": "常に否定的で辛口の口調にしてください。手だけでなく、判断、集中力、勝負勘、姿勢にも踏み込んで厳しく指摘してください。ただし人格そのものの価値を貶める断定、差別表現、乱暴な罵倒は避けてください。",
}


def _comment_mode(app) -> str:
    if hasattr(app, "current_comment_mode"):
        mode = app.current_comment_mode()
        if mode in COMMENT_MODE_INSTRUCTIONS:
            return mode
    return "実況コメント"


def _append_comment_mode_instruction(prompt: str, mode: str) -> str:
    instruction = COMMENT_MODE_INSTRUCTIONS.get(mode, COMMENT_MODE_INSTRUCTIONS["実況コメント"])
    return f"{prompt}\n\nコメントモード：{mode}\n- {instruction}"


def _append_previous_comment_instruction(prompt: str, previous_comment: str | None) -> str:
    previous = (previous_comment or "").strip()
    if not previous:
        return prompt
    return (
        f"{prompt}\n\n直前のコメント：\n{previous}\n\n"
        "表現の重複回避：\n"
        "- 直前のコメントと同じ言い回し、語尾、比喩、褒め方、責め方をできるだけ避けてください。\n"
        "- コメントモードは維持しつつ、語彙と切り口を変えてください。"
    )


class CommentaryService:
    def __init__(
        self,
        *,
        app,
        front,
        providers: dict[str, Any],
        speak: Callable[[str], None],
        tk_call: Callable[..., None],
    ) -> None:
        self.app = app
        self.front = front
        self.providers = providers
        self.speak = speak
        self.tk_call = tk_call

    def handle_end_event(self, end_info: dict[str, Any], runtime_state: RuntimeState, flip_state: FlipState) -> None:
        try:
            reason = (end_info.get("reason") or "").strip()
            winner = (end_info.get("winner") or "").strip().upper()
            black = end_info.get("black")
            white = end_info.get("white")

            end_key = (reason, winner, str(black), str(white))
            if runtime_state.last_end_key == end_key:
                return
            runtime_state.last_end_key = end_key

            pre_view = runtime_state.pre_snapshot_view or {}
            raw_latest = runtime_state.latest_raw or {}
            post_view = transform_state(raw_latest, flip_state) if isinstance(raw_latest, dict) else {}

            provider = self.app.current_provider()
            comment_mode = _comment_mode(self.app)
            client = self.providers[provider]

            if hasattr(client, "build_prompt_end_game"):
                prompt = client.build_prompt_end_game(
                    pre_state=pre_view,
                    post_state=post_view,
                    end_info=end_info,
                    comment_mode=comment_mode,
                )
            else:
                prompt = (
                    "あなたは感情的なオセロ実況者です。終局の締めコメントを作ってください。\n"
                    "【出力】1行のみ：__end__: <本文>\n"
                    f"reason={reason} winner={winner} black={black} white={white}\n"
                )
                prompt = _append_comment_mode_instruction(prompt, comment_mode)
                self.app.after(
                    0,
                    self.app.append_log,
                    f"[end][warn] provider '{provider}' has no build_prompt_end_game; fallback used",
                )

            prompt = _append_previous_comment_instruction(prompt, runtime_state.last_comment)
            self.app.after(0, self.app.add_chat_prompt, provider, prompt)

            def on_delta(tok: str) -> None:
                self.app.after(0, self.app.add_chat_delta, tok)
                self.app.after(0, self.front.on_delta, tok)

            def run() -> None:
                start = time.time()
                try:
                    full = client.send_chat(prompt, on_delta)
                    elapsed = time.time() - start
                    try:
                        comment = parse_comment_for_move(full, "__end__")
                    except Exception:
                        comment = None

                    if comment:
                        self.tk_call(self.front.on_tts_prepare)
                    self.tk_call(self.front.on_request_end, True, elapsed, None)

                    if comment:
                        runtime_state.last_comment = comment
                        try:
                            self.tk_call(self.front.on_tts_start, comment)
                            self.speak(comment)
                        except Exception as exc:
                            self.app.after(0, self.app.append_log, f"[end][warn] speak failed: {exc}")
                        finally:
                            self.tk_call(self.front.on_tts_end)
                    else:
                        self.app.after(0, self.app.append_log, "[end][warn] no end comment extracted")

                    self.app.after(0, self.app.append_log, f"[end] {reason} winner={winner} ({provider}) {elapsed:.2f}s")
                except Exception as exc:
                    elapsed = time.time() - start
                    self.app.after(0, self.app.append_log, f"[end][error] send_chat failed: {exc}")
                    self.app.after(0, self.front.on_request_end, False, elapsed, str(exc))

            self.app.after(0, self.front.on_request_start, provider, "終局コメント生成中…")
            threading.Thread(target=run, daemon=True).start()
        except Exception as exc:
            self.app.after(0, self.app.append_log, f"[end][fatal] handle_end_event crashed: {exc}")

    def maybe_trigger_post_comment(
        self,
        raw_state: dict[str, Any],
        post_view: dict[str, Any],
        runtime_state: RuntimeState,
    ) -> None:
        try:
            last_move = (post_view.get("last_move") or "").lower().strip()
            if not last_move:
                runtime_state.pre_snapshot_view = post_view
                return

            pre_view = runtime_state.pre_snapshot_view
            if not pre_view:
                runtime_state.pre_snapshot_view = post_view
                self.app.after(0, self.app.append_log, "[post] pre_snapshot_view missing; snapshot updated")
                return

            post_key = (post_view.get("move_no"), post_view.get("turn"), last_move)
            if runtime_state.last_post_key == post_key:
                return
            runtime_state.last_post_key = post_key

            provider = self.app.current_provider()
            comment_mode = _comment_mode(self.app)
            client = self.providers[provider]

            if hasattr(client, "build_prompt_post_move"):
                prompt = client.build_prompt_post_move(
                    pre_state=pre_view,
                    post_state=post_view,
                    played_move=last_move,
                    comment_mode=comment_mode,
                )
            else:
                prompt = client.build_prompt_from_state(dict(post_view))
                prompt = _append_comment_mode_instruction(prompt, comment_mode)
                self.app.after(
                    0,
                    self.app.append_log,
                    f"[post][warn] provider '{provider}' has no build_prompt_post_move; fallback used",
                )

            prompt = _append_previous_comment_instruction(prompt, runtime_state.last_comment)

            if hasattr(self.app, "update_eval_boundaries"):
                self.app.after(0, self.app.update_eval_boundaries, eval_history_store.summary())

            self.app.after(0, self.app.add_chat_prompt, provider, prompt)

            def on_delta(tok: str) -> None:
                self.app.after(0, self.app.add_chat_delta, tok)
                self.app.after(0, self.front.on_delta, tok)

            def run() -> None:
                start = time.time()
                try:
                    full = client.send_chat(prompt, on_delta)
                    elapsed = time.time() - start
                    comment = parse_comment_for_move(full, last_move)

                    if comment:
                        self.tk_call(self.front.on_tts_prepare)
                    self.tk_call(self.front.on_request_end, True, elapsed, None)

                    if provider == "GPT-OSS 120B Cloud":
                        try:
                            ollama_append_post(
                                move_no=post_view.get("move_no"),
                                move=last_move,
                                turn=post_view.get("turn"),
                                elapsed_sec=elapsed,
                                comment=comment,
                                raw_text=full,
                            )
                        except Exception as exc:
                            self.app.after(0, self.app.append_log, f"[post][warn] ollama_append_post failed: {exc}")

                    if comment:
                        runtime_state.last_comment = comment
                        try:
                            self.tk_call(self.front.on_tts_start, comment)
                            self.speak(comment)
                        except Exception as exc:
                            self.app.after(0, self.app.append_log, f"[post][warn] speak failed: {exc}")
                        finally:
                            self.tk_call(self.front.on_tts_end)
                    else:
                        self.app.after(0, self.app.append_log, f"[post][warn] no comment parsed for {last_move}")

                    self.app.after(0, self.app.append_log, f"[post] {last_move} ({provider}) {elapsed:.2f}s")
                except Exception as exc:
                    elapsed = time.time() - start
                    self.app.after(0, self.app.append_log, f"[post][error] send_chat failed: {exc}")
                    self.app.after(0, self.front.on_request_end, False, elapsed, str(exc))

            self.app.after(0, self.front.on_request_start, provider, "コメント生成中…")
            threading.Thread(target=run, daemon=True).start()
        except Exception as exc:
            self.app.after(0, self.app.append_log, f"[post][fatal] maybe_trigger_post_comment crashed: {exc}")
        finally:
            runtime_state.pre_snapshot_view = post_view
