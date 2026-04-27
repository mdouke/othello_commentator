#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import threading
from pathlib import Path

import tkinter as tk  # Tkの初期化順を安定させるために残す

from othello_commentator.app.bootstrap import bootstrap_application

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    boot = bootstrap_application(
        Path(__file__).resolve().parent / "othello_commentator" / "realtime" / "runner.py",
        log,
    )

    def reader():
        for line in boot.ipc_client.iter_output():
            try:
                msg = line.strip()
                if not msg:
                    continue
                boot.message_router.handle_line(msg)
            except Exception as exc:
                boot.ui_feedback.report_reader_error(exc)
                log.exception("reader crashed")
                continue

    threading.Thread(target=reader, daemon=True).start()
    boot.app.mainloop()


if __name__ == "__main__":
    main()
