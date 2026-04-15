from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterator


class RealtimeProcessClient:
    def __init__(self, script_path: Path):
        self.script_path = script_path
        self.proc = subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

    def send(self, msg: str) -> None:
        if self.proc.poll() is not None:
            return
        if not msg.endswith("\n"):
            msg += "\n"
        assert self.proc.stdin is not None
        self.proc.stdin.write(msg)
        self.proc.stdin.flush()
        if msg.startswith(("SYNC:", "CALIB:")):
            print(f"[MAIN->CHILD] {msg.strip()}", file=sys.stderr, flush=True)

    def terminate(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()

    def iter_output(self) -> Iterator[str]:
        assert self.proc.stdout is not None
        yield from self.proc.stdout
