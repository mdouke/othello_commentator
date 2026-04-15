#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re

# 受け付けるキー：
# - 通常: a1〜h8
# - pass
# - 終局: __end__
_COORD_ANY_RE = re.compile(
    r'^\s*((?:[a-h][1-8])|pass|__end__)\s*:\s*(.+)$',
    re.IGNORECASE
)

def _clean_quoted(s: str) -> str:
    s2 = (s or "").strip()
    if s2.startswith("**") and s2.endswith("**") and len(s2) > 4:
        s2 = s2[2:-2].strip()
    if len(s2) >= 2 and ((s2[0] in ('"', '“', "'") and s2[-1] in ('"', '”', "'"))):
        return s2[1:-1].strip()
    return s2

def parse_comment_for_move(text: str, move: str) -> str | None:
    target = (move or "").lower().strip()
    if not target:
        return None

    got = {}
    for ln in (text or "").splitlines():
        m = _COORD_ANY_RE.match(ln)
        if not m:
            continue
        coord = m.group(1).lower()
        cmt = _clean_quoted(m.group(2))
        got[coord] = cmt

    return got.get(target)
