from __future__ import annotations

import threading
from bisect import bisect_right
from typing import Any


LABELS = ["とても悪い", "悪い", "普通", "良い", "とても良い"]


class EvalHistoryStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._values: list[float] = []

    def load(self) -> list[float]:
        with self._lock:
            return list(self._values)

    def append_evals(self, evals: dict[Any, Any] | None) -> int:
        values: list[float] = []
        for raw in (evals or {}).values():
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                continue

        if not values:
            return 0

        with self._lock:
            self._values.extend(values)
            return len(values)

    def classify(self, raw_value: Any) -> str:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return "普通"

        with self._lock:
            boundaries = self._boundaries_locked()

        if boundaries is None:
            return "普通"

        return LABELS[bisect_right(boundaries, value)]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            boundaries = self._boundaries_locked()
            return {
                "count": len(self._values),
                "boundaries": boundaries,
                "labels": LABELS[:],
            }

    def _boundaries_locked(self) -> list[float] | None:
        if len(self._values) < 5:
            return None

        values = sorted(self._values)
        n = len(values)
        return [values[min(n - 1, max(0, int(n * ratio) - 1))] for ratio in (0.2, 0.4, 0.6, 0.8)]


eval_history_store = EvalHistoryStore()
