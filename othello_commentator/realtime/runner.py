#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path
import traceback

# Allow direct execution via `python path/to/runner.py`.
if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from othello_commentator.realtime.engine import main

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
