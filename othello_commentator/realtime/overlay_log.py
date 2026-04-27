from __future__ import annotations

import collections
from typing import Iterable

LOG_W = 480
LOG_H = 360
LINE_H = 18

_log_buf = collections.deque(maxlen=LOG_H // LINE_H + 20)


def add_log(x: str | Iterable[str]) -> None:
    if isinstance(x, str):
        _log_buf.append(x)
    else:
        _log_buf.extend(x)


def clear_log() -> None:
    _log_buf.clear()


def render_log_img():
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (LOG_W, LOG_H), (255, 255, 255))
    drw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W5.ttc", 16, encoding="utf-8")
    except Exception:
        font = ImageFont.load_default()
    y = 4
    for ln in list(_log_buf)[-LOG_H // LINE_H:]:
        drw.text((5, y), ln, font=font, fill=(0, 0, 0))
        y += LINE_H
    return np.asarray(img)
