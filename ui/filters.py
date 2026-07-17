from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.data_loader import split_terms
from ui.source_display import source_file_name


def _options(frame: pd.DataFrame, column: str) -> list[str]:
    if frame.empty or column not in frame.columns:
        return []
    values = frame[column].fillna("").astype(str)
    return sorted(value for value in values.unique().tolist() if value)


def sidebar_filters(frame: pd.DataFrame, key_prefix: str = "global") -> dict:
    with st.sidebar:
        st.divider()
        st.caption("全局筛选")
        filters = {
            "platforms": st.multiselect("平台", _options(frame, "platform"), key=f"{key_prefix}_platforms"),
            "products": st.multiselect("商品", _options(frame, "product_title"), key=f"{key_prefix}_products"),
            "shops": st.multiselect("店铺", _options(frame, "shop_name"), key=f"{key_prefix}_shops"),
            "roles": st.multiselect("评论类型", _options(frame, "content_role"), key=f"{key_prefix}_roles"),
            "levels": st.multiselect("证据等级", ["A", "B", "C", "D", ""], key=f"{key_prefix}_levels"),
            "workbook_sources": st.multiselect("分析文件", _options(frame, "workbook_source"), key=f"{key_prefix}_workbook_sources"),
            "source_files": st.multiselect(
                "来源文件",
                _options(frame, "source_file"),
                format_func=source_file_name,
                key=f"{key_prefix}_sources",
            ),
            "text": st.text_input("全文搜索", key=f"{key_prefix}_text"),
            "keyword": st.text_input("关键词 / SKU", key=f"{key_prefix}_keyword"),
        }
        if "extract_confidence" in frame.columns and not frame.empty:
            max_value = float(max(frame["extract_confidence"].max(), 1))
            filters["confidence"] = st.slider(
                "置信度范围",
                0.0,
                max_value,
                (0.0, max_value),
                key=f"{key_prefix}_confidence",
            )
        else:
            filters["confidence"] = None
    return filters


def apply_filters(frame: pd.DataFrame, filters: dict) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    mapping = {
        "platforms": "platform",
        "products": "product_title",
        "shops": "shop_name",
        "roles": "content_role",
        "levels": "evidence_level",
        "workbook_sources": "workbook_source",
        "source_files": "source_file",
    }
    for filter_key, column in mapping.items():
        values = filters.get(filter_key) or []
        if values and column in result.columns:
            result = result[result[column].fillna("").astype(str).isin(values)]

    text = (filters.get("text") or "").strip().lower()
    if text:
        search_cols = [
            col
            for col in ["content_text_clean", "content_text_raw", "matched_sentence", "parent_text_clean"]
            if col in result.columns
        ]
        if search_cols:
            mask = False
            for col in search_cols:
                mask = mask | result[col].fillna("").astype(str).str.lower().str.contains(text, regex=False)
            result = result[mask]

    keyword = (filters.get("keyword") or "").strip().lower()
    if keyword:
        search_cols = [
            col
            for col in [
                "matched_keywords",
                "pre_purchase_terms",
                "ai_source_terms",
                "ai_action_terms",
                "purchase_context_terms",
                "decision_context_terms",
                "sku",
            ]
            if col in result.columns
        ]
        if search_cols:
            mask = False
            for col in search_cols:
                mask = mask | result[col].fillna("").astype(str).str.lower().str.contains(keyword, regex=False)
            result = result[mask]

    confidence = filters.get("confidence")
    if confidence and "extract_confidence" in result.columns:
        result = result[
            (result["extract_confidence"] >= confidence[0])
            & (result["extract_confidence"] <= confidence[1])
        ]
    return result


def page_boolean_filter(frame: pd.DataFrame, column: str, label: str, key: str) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return frame
    choice = st.radio(label, ["全部", "是", "否"], horizontal=True, key=key)
    if choice == "是":
        return frame[frame[column]]
    if choice == "否":
        return frame[~frame[column]]
    return frame


def keyword_type_filter(frame: pd.DataFrame, key: str) -> pd.DataFrame:
    if frame.empty or "keyword_type" not in frame.columns:
        return frame
    types = sorted(frame["keyword_type"].fillna("").astype(str).unique())
    selected = st.multiselect("关键词类型", [item for item in types if item], key=key)
    if selected:
        return frame[frame["keyword_type"].isin(selected)]
    return frame


def filter_by_term(frame: pd.DataFrame, column: str, term: str) -> pd.DataFrame:
    if frame.empty or not term or column not in frame.columns:
        return frame
    return frame[frame[column].apply(lambda value: term in split_terms(value))]
