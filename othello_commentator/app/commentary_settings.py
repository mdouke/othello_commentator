from __future__ import annotations

from enum import Enum


class CommentaryLanguage(str, Enum):
    JAPANESE = "ja"
    ENGLISH = "en"


DEFAULT_COMMENTARY_LANGUAGE = CommentaryLanguage.JAPANESE


def normalize_commentary_language(value: object) -> CommentaryLanguage:
    if isinstance(value, CommentaryLanguage):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"en", "english", "英語"}:
        return CommentaryLanguage.ENGLISH
    return CommentaryLanguage.JAPANESE
