#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import time
from pathlib import Path

from othello_commentator.storage.paths import ARTIFACTS_DIR, ensure_dir

LOG_PATH = ensure_dir(ARTIFACTS_DIR) / "comments_log_ollama.jsonl"
_started_at = time.monotonic()


def reset_start_time() -> None:
    """START操作を基準にログの経過時間をリセットする。"""
    global _started_at
    _started_at = time.monotonic()


def elapsed_since_start() -> float:
    """START操作からの経過秒数を返す。"""
    return round(max(0.0, time.monotonic() - _started_at), 3)


def append(
    *,
    move_no,
    turn,
    moves,
    comments,
    raw_text,
    ts=None,
    elapsed_sec: float | None = None,
):
    """
    Ollama コメントログ専用 JSONL ロガー。
    フィールド順: ts, move_no, turn, moves, elapsed_sec, comments, raw_text
    """
    rec = {}

    # ここで順番を決める
    rec["ts"] = elapsed_since_start() if ts is None else ts
    rec["move_no"] = move_no
    rec["turn"] = turn
    rec["moves"] = moves

    if elapsed_sec is not None:
        rec["elapsed_sec"] = float(elapsed_sec)

    rec["comments"] = comments
    rec["raw_text"] = raw_text

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
        f.write("\n")

def append_post(
    *,
    move_no,
    turn,
    move,
    comment,
    ts=None,
    elapsed_sec: float | None = None,
    move_elapsed_sec: float | None = None,
    playback_end_elapsed_sec: float | None = None,
    played_move_eval: float | None = None,
    alternative_move_evals: dict[str, float | None] | None = None,
):
    """
    着手後実況（post）用 Ollama ログ。
    フィールド順:
    ts, move_no, move, turn, move_elapsed_sec, playback_end_elapsed_sec,
    played_move_eval, alternative_move_evals, elapsed_sec, comment
    """
    rec = {}

    rec["ts"] = elapsed_since_start() if ts is None else ts
    rec["move_no"] = move_no
    rec["move"] = move
    rec["turn"] = turn
    rec["move_elapsed_sec"] = (
        float(move_elapsed_sec) if move_elapsed_sec is not None else None
    )
    rec["playback_end_elapsed_sec"] = (
        float(playback_end_elapsed_sec)
        if playback_end_elapsed_sec is not None
        else None
    )
    rec["played_move_eval"] = (
        float(played_move_eval) if played_move_eval is not None else None
    )
    rec["alternative_move_evals"] = alternative_move_evals or {}

    if elapsed_sec is not None:
        rec["elapsed_sec"] = float(elapsed_sec)

    rec["comment"] = comment

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
        f.write("\n")
