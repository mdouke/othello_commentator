from __future__ import annotations

import threading
import time
from typing import Any, Callable

from othello_commentator.storage.ollama_comment_store import (
    append_post as ollama_append_post,
    elapsed_since_start,
)
from othello_commentator.llm.comment_parser import parse_comment_for_move
from othello_commentator.llm.prompt_builder import (
    build_end_game_prompt,
    build_post_move_prompt,
)
from othello_commentator.app.commentary_settings import normalize_commentary_language
from othello_commentator.app.session_state import RuntimeState
from othello_commentator.domain.board_state import FlipState, transform_state


class CommentaryService:
    def __init__(
        self,
        *,
        app,
        front,
        providers: dict[str, Any],
        speak: Callable[[str, str], None],
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
            final_view = runtime_state.final_view or post_view
            end_elapsed_sec = elapsed_since_start()

            provider = self.app.current_provider()
            style = self.app.current_style()
            language = normalize_commentary_language(
                self.app.current_commentary_language()
                if hasattr(self.app, "current_commentary_language")
                else "ja"
            ).value
            client = self.providers[provider]
            prompt = build_end_game_prompt(
                pre_state=pre_view,
                post_state=post_view,
                end_info=end_info,
                style=style,
                language=language,
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

                    playback_end_elapsed_sec = None
                    if comment:
                        try:
                            self.tk_call(self.front.on_tts_start, comment)
                            self.speak(comment, language)
                        except Exception as exc:
                            self.app.after(0, self.app.append_log, f"[end][warn] speak failed: {exc}")
                        finally:
                            self.tk_call(self.front.on_tts_end)
                            playback_end_elapsed_sec = elapsed_since_start()
                    else:
                        self.app.after(0, self.app.append_log, "[end][warn] no end comment extracted")

                    if provider == "GPT-OSS 120B Cloud":
                        try:
                            ollama_append_post(
                                move_no=final_view.get("move_no"),
                                move="__end__",
                                turn=final_view.get("turn"),
                                elapsed_sec=elapsed,
                                move_elapsed_sec=end_elapsed_sec,
                                playback_end_elapsed_sec=playback_end_elapsed_sec,
                                played_move_eval=None,
                                alternative_move_evals={},
                                comment=comment,
                                language=language,
                                provider=provider,
                            )
                        except Exception as exc:
                            self.app.after(0, self.app.append_log, f"[end][warn] ollama_append_post failed: {exc}")

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
            move_elapsed_sec = elapsed_since_start()

            evaluated_move = last_move
            if last_move == "pass":
                evaluated_move = (post_view.get("cause_move") or "").lower().strip()
            pre_evals = pre_view.get("evals") or {}
            normalized_evals = (
                {str(move).lower(): value for move, value in pre_evals.items()}
                if isinstance(pre_evals, dict)
                else {}
            )
            played_move_eval = normalized_evals.get(evaluated_move)
            alternative_move_evals = {
                move: value
                for move, value in normalized_evals.items()
                if move != evaluated_move
            }

            provider = self.app.current_provider()
            style = self.app.current_style()
            language = normalize_commentary_language(
                self.app.current_commentary_language()
                if hasattr(self.app, "current_commentary_language")
                else "ja"
            ).value
            client = self.providers[provider]
            prompt = build_post_move_prompt(
                pre_state=pre_view,
                post_state=post_view,
                played_move=last_move,
                style=style,
                language=language,
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

                    playback_end_elapsed_sec = None
                    if comment:
                        try:
                            self.tk_call(self.front.on_tts_start, comment)
                            self.speak(comment, language)
                        except Exception as exc:
                            self.app.after(0, self.app.append_log, f"[post][warn] speak failed: {exc}")
                        finally:
                            self.tk_call(self.front.on_tts_end)
                            playback_end_elapsed_sec = elapsed_since_start()
                    else:
                        self.app.after(0, self.app.append_log, f"[post][warn] no comment parsed for {last_move}")

                    if provider == "GPT-OSS 120B Cloud":
                        try:
                            ollama_append_post(
                                move_no=post_view.get("move_no"),
                                move=last_move,
                                turn=post_view.get("turn"),
                                elapsed_sec=elapsed,
                                move_elapsed_sec=move_elapsed_sec,
                                playback_end_elapsed_sec=playback_end_elapsed_sec,
                                played_move_eval=played_move_eval,
                                alternative_move_evals=alternative_move_evals,
                                comment=comment,
                                language=language,
                                provider=provider,
                            )
                        except Exception as exc:
                            self.app.after(0, self.app.append_log, f"[post][warn] ollama_append_post failed: {exc}")

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
