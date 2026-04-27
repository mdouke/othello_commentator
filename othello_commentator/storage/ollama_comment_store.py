#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

from othello_commentator.storage.paths import ARTIFACTS_DIR, ensure_dir

LOG_PATH = ensure_dir(ARTIFACTS_DIR) / "comments_log_ollama.jsonl"


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
    rec["ts"] = ts or datetime.now().isoformat()
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
    raw_text,
    ts=None,
    elapsed_sec: float | None = None,
):
    """
    着手後実況（post）用 Ollama ログ。
    フィールド順:
    ts, move_no, move, turn, elapsed_sec, comment, raw_text
    """
    rec = {}

    rec["ts"] = ts or datetime.now().isoformat()
    rec["move_no"] = move_no
    rec["move"] = move
    rec["turn"] = turn

    if elapsed_sec is not None:
        rec["elapsed_sec"] = float(elapsed_sec)

    rec["comment"] = comment
    rec["raw_text"] = raw_text

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
        f.write("\n")
