#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from othello_commentator.storage.paths import ARTIFACTS_DIR, SUMMARY_DIR, ensure_dir

# ログの場所＆出力先
LOG_PATH = ensure_dir(ARTIFACTS_DIR) / "temporary.jsonl"
OUT_PATH = ensure_dir(SUMMARY_DIR) / "comments_summary.txt"

# move_no を 0始まりで保存している場合は True（1始まりなら False）
MOVE_NO_IS_ZERO_BASED = False


def load_records() -> List[Dict[str, Any]]:
    """JSONL を全部読む（壊れた行はスキップ）"""
    records: List[Dict[str, Any]] = []
    if not LOG_PATH.exists():
        print(f"[WARN] {LOG_PATH} が見つかりません。")
        return records

    with LOG_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception as e:
                print(f"[WARN] JSON parse error: {e} line={line[:80]!r}")
                continue
            if isinstance(rec, dict):
                records.append(rec)
            else:
                print(f"[WARN] JSON is not object: {type(rec)} line={line[:80]!r}")
    return records


def safe_str(x: Any, default: str = "") -> str:
    if x is None:
        return default
    return str(x)


def safe_float(x: Any) -> Optional[float]:
    if isinstance(x, (int, float)):
        return float(x)
    return None


def main():
    records = load_records()
    if not records:
        print("コメントが見つかりませんでした。")
        return

    output_lines: List[str] = []

    # ===== ヘッダ行 =====
    header = (
        "timestamp                  手数  手番  着手  生成秒数[s]  文字数  コメント"
    )
    sep = "-" * len(header)
    output_lines.append(header)
    output_lines.append(sep)

    # 統計用
    total_rows = 0
    total_chars = 0
    total_elapsed = 0.0
    elapsed_count = 0

    # move_no順→ts順に軽く整列（欠損は末尾）
    def sort_key(rec: Dict[str, Any]):
        mv = rec.get("move_no")
        mv_key = mv if isinstance(mv, int) else 10**9
        ts = safe_str(rec.get("ts", ""))
        return (mv_key, ts)

    for rec in sorted(records, key=sort_key):
        ts = safe_str(rec.get("ts", ""))
        move_no = rec.get("move_no", "")
        if MOVE_NO_IS_ZERO_BASED and isinstance(move_no, int):
            move_no = move_no + 1

        turn = safe_str(rec.get("turn", "?"))
        move = safe_str(rec.get("move", rec.get("coord", "")))  # 念のため別名も許容
        comment = safe_str(rec.get("comment", ""))
        elapsed = safe_float(rec.get("elapsed_sec"))

        # 文字数
        c_len = len(comment)
        total_chars += c_len
        total_rows += 1

        # 時間
        if elapsed is not None:
            total_elapsed += elapsed
            elapsed_count += 1
            elapsed_disp = f"{elapsed:>10.3f}"
        else:
            elapsed_disp = f"{0.0:>10.3f}"

        # ===== 1行サマリ（コメントは長いと見づらいので軽く切る） =====
        comment_one_line = comment.replace("\n", " ").strip()
        if len(comment_one_line) > 60:
            comment_one_line = comment_one_line[:57] + "..."

        meta_line = (
            f"{ts:<26}  "
            f"{str(move_no):>3}  "
            f"{turn:^3}  "
            f"{move:<3}  "
            f"{elapsed_disp}  "
            f"{c_len:>6}  "
            f"{comment_one_line}"
        )
        output_lines.append(meta_line)

        # ===== 詳細（raw_text も欲しければここで出す）=====
        # raw_text = safe_str(rec.get("raw_text", ""))
        # if raw_text:
        #     output_lines.append(f"    raw_text: {raw_text}")

    # ===== 統計情報 =====
    output_lines.append("")
    output_lines.append("=== 統計情報 ===")
    output_lines.append(f"総行数（=総コメント手数）    : {total_rows} 行")
    output_lines.append(f"コメント総文字数            : {total_chars} 文字")
    if total_rows > 0:
        output_lines.append(f"コメント1手あたり平均文字数: {total_chars / total_rows:.1f} 文字")

    if elapsed_count > 0:
        output_lines.append(f"生成にかかった総時間        : {total_elapsed:.3f} 秒")
        output_lines.append(f"平均生成時間（1手あたり）   : {total_elapsed / elapsed_count:.3f} 秒")

    # ===== TXT に書き出し =====
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    print(f"出力しました → {OUT_PATH.absolute()}")


if __name__ == "__main__":
    main()
