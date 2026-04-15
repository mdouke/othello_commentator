from __future__ import annotations

import threading
import time
from typing import Any, Callable

from comment_logger_ollama import append_post as ollama_append_post
from comments import parse_comment_for_move
from runtime_state import RuntimeState
from state_utils import FlipState, transform_state


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
            style = self.app.current_style()
            client = self.providers[provider]

            if hasattr(client, "build_prompt_end_game"):
                prompt = client.build_prompt_end_game(
                    pre_state=pre_view,
                    post_state=post_view,
                    end_info=end_info,
                    style=style,
                )
            else:
                prompt = (
                    "あなたは感情的なオセロ実況者です。終局の締めコメントを作ってください。\n"
                    "【出力】1行のみ：__end__: <本文>\n"
                    f"reason={reason} winner={winner} black={black} white={white}\n"
                )
                self.app.after(
                    0,
                    self.app.append_log,
                    f"[end][warn] provider '{provider}' has no build_prompt_end_game; fallback used",
                )

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
            style = self.app.current_style()
            client = self.providers[provider]

            if hasattr(client, "build_prompt_post_move"):
                prompt = client.build_prompt_post_move(
                    pre_state=pre_view,
                    post_state=post_view,
                    played_move=last_move,
                    style=style,
                )
            else:
                prompt = client.build_prompt_from_state(dict(post_view)).replace("<<STYLE>>", style)
                self.app.after(
                    0,
                    self.app.append_log,
                    f"[post][warn] provider '{provider}' has no build_prompt_post_move; fallback used",
                )

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
