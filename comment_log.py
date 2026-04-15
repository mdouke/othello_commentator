# comment_log.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import json

from project_paths import ARTIFACTS_DIR, ensure_dir


# 1行分のレコード
@dataclass
class CommentRecord:
    ts: str                 # タイムスタンプ
    move_no: int            # 何手目か（0開始 or 1開始、どちらでも可）
    turn: str               # "B" or "W" など
    moves: List[str]        # その局面での合法手リスト（あれば）
    comments: Dict[str, str]  # "e3": "〜〜〜" のような座標→コメント
    raw_text: str           # LLMが返した生テキスト（必要なければ消してOK）


class CommentLogger:
    def __init__(self, path: Path):
        self.path = path

    def append(
        self,
        *,
        move_no: Optional[int],
        turn: Optional[str],
        moves: Optional[List[str]],
        comments: Dict[str, str],
        raw_text: str,
    ) -> None:
        rec = CommentRecord(
            ts=datetime.now().isoformat(),
            move_no=int(move_no) if move_no is not None else -1,
            turn=turn or "?",
            moves=moves or [],
            comments=comments or {},
            raw_text=raw_text,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            json.dump(asdict(rec), f, ensure_ascii=False)
            f.write("\n")


# 生成ログは artifacts/ 配下へまとめる
_comment_log_path = ensure_dir(ARTIFACTS_DIR) / "comments_log.jsonl"
comment_logger = CommentLogger(_comment_log_path)
