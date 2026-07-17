from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st


FEEDBACK_PATH = Path("output") / "review_feedback.csv"
FEEDBACK_COLUMNS = [
    "feedback_id",
    "content_id",
    "source_file",
    "product_title",
    "platform",
    "content_text_clean",
    "original_pre_purchase_decision",
    "manual_pre_purchase_decision",
    "original_ai_candidate",
    "manual_ai_candidate",
    "original_evidence_level",
    "manual_evidence_level",
    "feedback_type",
    "suggested_keyword",
    "suggested_exclude_pattern",
    "note",
    "reviewed_at",
    "reviewed_by",
]


def load_feedback(path: Path = FEEDBACK_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=FEEDBACK_COLUMNS)
    try:
        frame = pd.read_csv(path)
    except Exception:  # noqa: BLE001 - surfaced as an empty recoverable panel.
        return pd.DataFrame(columns=FEEDBACK_COLUMNS)
    for column in FEEDBACK_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[FEEDBACK_COLUMNS]


def save_feedback(row: dict, path: Path = FEEDBACK_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([row], columns=FEEDBACK_COLUMNS)
    frame.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")


def feedback_form(row: dict | None, key: str = "feedback_form") -> None:
    st.subheader("人工复核")
    if not row:
        st.info("在购前决策页或 AI 候选页复制 content_id 后，可在这里沉淀复核意见。")
        return

    with st.form(key):
        st.caption(f"当前评论：{row.get('content_id', '')} ｜ {row.get('product_title', '')}")
        feedback_type = st.multiselect(
            "复核类型",
            ["判断正确", "购前决策误判", "AI 候选误判", "证据等级需调整", "需要加入排除词", "需要加入关键词"],
            default=["判断正确"],
        )
        manual_pre = st.selectbox(
            "人工判断：购前决策",
            ["保持原判断", "是", "否"],
            index=0,
        )
        manual_ai = st.selectbox("人工判断：AI 候选", ["保持原判断", "是", "否"], index=0)
        manual_level = st.selectbox("人工证据等级", ["保持原等级", "A", "B", "C", "D", ""])
        suggested_keyword = st.text_input("建议加入关键词")
        suggested_exclude = st.text_input("建议加入排除词 / 排除模式")
        note = st.text_area("备注")
        reviewed_by = st.text_input("复核人", value="local_reviewer")
        submitted = st.form_submit_button("保存复核记录")

    if submitted:
        record = {
            "feedback_id": f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{row.get('content_id') or uuid4().hex[:8]}",
            "content_id": row.get("content_id", ""),
            "source_file": row.get("source_file", ""),
            "product_title": row.get("product_title", ""),
            "platform": row.get("platform", ""),
            "content_text_clean": row.get("content_text_clean", ""),
            "original_pre_purchase_decision": row.get("pre_purchase_decision", ""),
            "manual_pre_purchase_decision": _manual_bool(manual_pre, row.get("pre_purchase_decision", "")),
            "original_ai_candidate": row.get("ai_candidate", ""),
            "manual_ai_candidate": _manual_bool(manual_ai, row.get("ai_candidate", "")),
            "original_evidence_level": row.get("evidence_level", ""),
            "manual_evidence_level": row.get("evidence_level", "") if manual_level == "保持原等级" else manual_level,
            "feedback_type": ";".join(feedback_type),
            "suggested_keyword": suggested_keyword,
            "suggested_exclude_pattern": suggested_exclude,
            "note": note,
            "reviewed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "reviewed_by": reviewed_by,
        }
        save_feedback(record)
        st.success("已保存到 output/review_feedback.csv")


def _manual_bool(choice: str, original: object) -> object:
    if choice == "是":
        return True
    if choice == "否":
        return False
    return original
