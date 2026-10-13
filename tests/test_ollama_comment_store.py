import json

from othello_commentator.storage import ollama_comment_store


def test_append_post_uses_elapsed_time_from_start(monkeypatch, tmp_path):
    ticks = iter([100.0, 112.3456])
    monkeypatch.setattr(ollama_comment_store.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(ollama_comment_store, "LOG_PATH", tmp_path / "comments.jsonl")

    ollama_comment_store.reset_start_time()
    ollama_comment_store.append_post(
        move_no=1,
        turn="B",
        move="d3",
        comment="comment",
        move_elapsed_sec=2.5,
        playback_end_elapsed_sec=12.0,
        played_move_eval=3.25,
        alternative_move_evals={"c4": 1.5, "f5": -2.0},
        language="en",
        provider="GPT-OSS 120B Cloud",
    )

    record = json.loads(ollama_comment_store.LOG_PATH.read_text(encoding="utf-8"))
    assert record["ts"] == 12.346
    assert record["move_elapsed_sec"] == 2.5
    assert record["playback_end_elapsed_sec"] == 12.0
    assert record["played_move_eval"] == 3.25
    assert record["alternative_move_evals"] == {"c4": 1.5, "f5": -2.0}
    assert record["language"] == "en"
    assert record["provider"] == "GPT-OSS 120B Cloud"
    assert "raw_text" not in record


def test_explicit_timestamp_is_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_comment_store, "LOG_PATH", tmp_path / "comments.jsonl")

    ollama_comment_store.append_post(
        move_no=1,
        turn="B",
        move="d3",
        comment="comment",
        ts=0,
    )

    record = json.loads(ollama_comment_store.LOG_PATH.read_text(encoding="utf-8"))
    assert record["ts"] == 0
