from pathlib import Path

from ui.feedback import FEEDBACK_COLUMNS, load_feedback, save_feedback


def test_feedback_csv_round_trip(tmp_path: Path):
    path = tmp_path / "review_feedback.csv"
    row = {column: "" for column in FEEDBACK_COLUMNS}
    row.update(
        {
            "feedback_id": "qa_001",
            "content_id": "content_001",
            "content_text_clean": "灯光柔和，不刺眼。",
            "feedback_type": "QA链路测试",
            "reviewed_by": "codex_qa",
        }
    )

    save_feedback(row, path)
    loaded = load_feedback(path)

    assert list(loaded.columns) == FEEDBACK_COLUMNS
    assert len(loaded) == 1
    assert loaded.iloc[0]["content_text_clean"] == "灯光柔和，不刺眼。"
    assert loaded.iloc[0]["reviewed_by"] == "codex_qa"
