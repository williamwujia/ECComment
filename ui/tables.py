from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.export import csv_bytes, timestamp
from ui.i18n import column_label, rename_columns_for_display


def download_csv(frame: pd.DataFrame, label: str, prefix: str, key: str) -> None:
    st.download_button(
        label,
        data=csv_bytes(frame),
        file_name=f"{prefix}_{timestamp()}.csv",
        mime="text/csv",
        key=key,
    )


def show_table(frame: pd.DataFrame, columns: list[str] | None = None, height: int = 480) -> pd.DataFrame:
    if columns:
        visible = [column for column in columns if column in frame.columns]
        shown = frame[visible].copy() if visible else frame.copy()
    else:
        shown = frame.copy()
    shown = shown.rename(columns=rename_columns_for_display(list(shown.columns)))
    st.dataframe(shown, use_container_width=True, height=height, hide_index=True)
    return shown


def detail_lookup(frame: pd.DataFrame, key: str) -> None:
    if frame.empty or "content_id" not in frame.columns:
        return
    content_id = st.text_input("输入 content_id 查看详情", key=key)
    if not content_id:
        return
    matched = frame[frame["content_id"].fillna("").astype(str) == content_id.strip()]
    if matched.empty:
        st.warning("没有找到这个 content_id。")
    else:
        detail = {
            column_label(column): value
            for column, value in matched.iloc[0].to_dict().items()
        }
        st.json(detail, expanded=False)
