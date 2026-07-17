from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.styles import badge, esc, level_badge
from ui.i18n import column_label
from ui.source_display import source_file_name


def _first(row: pd.Series, *columns: str) -> str:
    for column in columns:
        value = row.get(column, "")
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except TypeError:
            pass
        text = str(value).strip()
        if text:
            return text
    return ""


def _source_name(value: object) -> str:
    return source_file_name(value)


def _sentiment_badge(row: pd.Series) -> str:
    label = _first(row, "sentiment_label_cn", "sentiment_label")
    if not label:
        return ""
    code = _first(row, "sentiment_label")
    kind = {"P": "green", "N": "red", "M": "c", "Z": "gray"}.get(code, "gray")
    score = _first(row, "sentiment_score")
    return badge(f"情感分类：{label}{' ' + score if score else ''}", kind)


def review_card(row: pd.Series, index: int, show_feedback: bool = True) -> None:
    title = _first(row, "product_title") or "未命名商品"
    platform = _first(row, "platform") or "未知平台"
    sku = _first(row, "sku")
    text = _first(row, "content_text_clean", "content_text_raw")
    sentence = _first(row, "matched_sentence")
    level = _first(row, "evidence_level")
    strong = " strong" if level == "A" else ""
    tags = [
        badge("购前决策：是" if bool(row.get("pre_purchase_decision", False)) else "购前决策：否", "green" if bool(row.get("pre_purchase_decision", False)) else "gray"),
        badge("AI候选：是" if bool(row.get("ai_candidate", False)) else "AI候选：否", "a" if bool(row.get("ai_candidate", False)) else "gray"),
        level_badge(level),
        badge(platform, "gray"),
    ]
    sentiment_tag = _sentiment_badge(row)
    if sentiment_tag:
        tags.append(sentiment_tag)
    st.markdown(
        f"""
        <div class="review-card{strong}">
          <div class="review-title">{esc(title)} <span class="muted">{esc(sku)}</span></div>
          <div class="tag-row">{''.join(tags)}</div>
          <div class="review-text">{esc(text)}</div>
          <div class="meta-text">命中句子：{esc(sentence or "未记录")}</div>
          <div class="meta-text">购前理由：{esc(_first(row, "pre_purchase_reason"))}</div>
          <div class="meta-text">关键词：{esc(_first(row, "matched_keywords", "pre_purchase_terms"))}</div>
          <div class="meta-text">情感分类构成：{esc(_first(row, "sentiment_label_cn") or "未接入")} ｜ 夸法：{esc(_first(row, "praise_cn") or "无")} ｜ 吐槽：{esc(_first(row, "complaint_cn") or "无")}</div>
          <div class="meta-text">来源：{esc(_source_name(row.get("source_file", "")))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("展开追溯与复制", expanded=False):
        st.text_area("原文", text, height=120, key=f"copy_text_{index}", label_visibility="collapsed")
        detail_row(row)
        if show_feedback and st.button("设为复核对象", key=f"feedback_target_{index}"):
            st.session_state["feedback_target"] = row.to_dict()
            st.success("已设为复核对象，可到“复核记录”页保存意见。")


def ai_candidate_card(row: pd.Series, index: int) -> None:
    level = _first(row, "evidence_level")
    text = _first(row, "content_text_clean", "content_text_raw")
    report = report_case_text(row)
    st.markdown(
        f"""
        <div class="review-card{' strong' if level == 'A' else ''}">
          <div class="tag-row">
            {level_badge(level)}
            {badge('match_score ' + esc(_first(row, 'match_score') or '0'), 'gray')}
            {badge(esc(_first(row, 'platform') or '未知平台'), 'gray')}
            {_sentiment_badge(row)}
          </div>
          <div class="review-text">{esc(text)}</div>
          <div class="meta-text">命中句子：{esc(_first(row, "matched_sentence") or "未记录")}</div>
          <div class="meta-text">AI 来源词：{esc(_first(row, "ai_source_terms") or "无")}</div>
          <div class="meta-text">AI 行为词：{esc(_first(row, "ai_action_terms") or "无")}</div>
          <div class="meta-text">购买动作词：{esc(_first(row, "purchase_context_terms", "decision_context_terms") or "无")}</div>
          <div class="meta-text">证据理由：{esc(_first(row, "evidence_reason", "ai_level_reason") or "未记录")}</div>
          <div class="meta-text">情感分类构成：{esc(_first(row, "sentiment_label_cn") or "未接入")} ｜ 夸法：{esc(_first(row, "praise_cn") or "无")} ｜ 吐槽：{esc(_first(row, "complaint_cn") or "无")}</div>
          <div class="meta-text">商品：{esc(_first(row, "product_title"))} ｜ SKU：{esc(_first(row, "sku"))}</div>
          <div class="meta-text">来源：{esc(_source_name(row.get("source_file", "")))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("复制为报告案例", expanded=False):
        st.text_area("报告案例文本", report, height=120, key=f"report_case_{index}")
        detail_row(row)
        if st.button("设为复核对象", key=f"ai_feedback_target_{index}"):
            st.session_state["feedback_target"] = row.to_dict()
            st.success("已设为复核对象，可到“复核记录”页保存意见。")


def detail_row(row: pd.Series | dict) -> None:
    data = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    important = [
        "content_id",
        "product_title",
        "platform",
        "source_file",
        "content_role",
        "sku",
        "pre_purchase_decision",
        "ai_candidate",
        "evidence_level",
        "matched_keywords",
        "matched_sentence",
        "evidence_reason",
        "exclude_reason",
        "sentiment_label_cn",
        "sentiment_score",
        "praise_cn",
        "complaint_cn",
        "sentiment_confidence",
        "sentiment_source",
        "sentiment_evidence",
        "sentiment_reason",
        "geo_value",
    ]
    rows = {}
    for key in important:
        if key not in data:
            continue
        rows[column_label(key)] = _source_name(data.get(key, "")) if key == "source_file" else data.get(key, "")
    st.dataframe(pd.DataFrame([rows]), width="stretch", hide_index=True)


def report_case_text(row: pd.Series | dict) -> str:
    data = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    level = _clean(data.get("evidence_level", ""))
    sentence = _clean(data.get("matched_sentence")) or _clean(data.get("content_text_clean"))
    parts = [
        f"【{level} 级案例】用户原文提到“{sentence}”。",
    ]
    ai_source_terms = _clean(data.get("ai_source_terms"))
    if ai_source_terms:
        parts.append(f"该评论命中 AI 来源词 {ai_source_terms}。")
    action_bits = [_clean(data.get("ai_action_terms")), _clean(data.get("purchase_context_terms"))]
    action_bits = [bit for bit in action_bits if bit]
    if action_bits:
        parts.append(f"并出现 {' / '.join(action_bits)} 等决策动作。")
    parts.append("可作为 AI 介入购买决策链路的候选证据。")
    product = _clean(data.get("product_title"))
    platform = _clean(data.get("platform"))
    if product or platform:
        parts.append(f"商品：{product}，平台：{platform}。")
    return "".join(parts)


def _clean(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()
