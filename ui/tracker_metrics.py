from __future__ import annotations

import pandas as pd


SENTIMENT_LABELS = {
    "P": "积极",
    "N": "消极",
    "M": "褒贬混合",
    "Z": "中性",
}

EVIDENCE_LEVELS = ("A", "B", "C", "D")
REVIEW_ROLES = {"review", "followup"}


def build_brand_overview(content: pd.DataFrame) -> dict:
    frame = content.copy()
    roles = _text_series(frame, "content_role")
    reviews = frame[roles.isin(REVIEW_ROLES)].copy()
    review_sentiment = sentiment_series(reviews)
    evidence = _text_series(reviews, "evidence_level").str.upper()
    sentiment_counts = {
        code: int(review_sentiment.eq(code).sum())
        for code in SENTIMENT_LABELS
    }
    evidence_counts = {
        level: int(evidence.eq(level).sum())
        for level in EVIDENCE_LEVELS
    }
    sentiment_judged = sum(sentiment_counts.values())
    evidence_graded = sum(evidence_counts.values())
    return {
        "total_content_count": len(frame),
        "review_count": len(reviews),
        "question_count": int(roles.eq("question").sum()),
        "answer_count": int(roles.eq("answer").sum()),
        "sentiment_counts": sentiment_counts,
        "sentiment_judged_count": sentiment_judged,
        "sentiment_unjudged_count": max(len(reviews) - sentiment_judged, 0),
        "sentiment_coverage": (
            sentiment_judged / len(reviews) if len(reviews) else 0
        ),
        "evidence_counts": evidence_counts,
        "evidence_graded_count": evidence_graded,
        "evidence_ungraded_count": max(len(reviews) - evidence_graded, 0),
        "ai_candidate_count": int(
            boolean_series(reviews, "ai_candidate").sum()
        ),
        "pre_purchase_count": int(
            boolean_series(reviews, "pre_purchase_decision").sum()
        ),
    }


def build_product_comparison(content: pd.DataFrame) -> pd.DataFrame:
    if content.empty:
        return pd.DataFrame(
            columns=[
                "item_key",
                "product_title",
                "review_count",
                "question_count",
                "positive_count",
                "negative_count",
                "mixed_count",
                "neutral_count",
                "ai_candidate_count",
                "a_level_count",
                "b_level_count",
                "c_level_count",
                "d_level_count",
                "sentiment_coverage",
                "ai_candidate_rate",
            ]
        )
    frame = content.copy()
    if "item_key" not in frame.columns:
        frame["item_key"] = ""
    if "product_title" not in frame.columns:
        frame["product_title"] = ""
    rows = []
    for (item_key, product_title), group in frame.groupby(
        ["item_key", "product_title"],
        dropna=False,
    ):
        roles = _text_series(group, "content_role")
        reviews = group[roles.isin(REVIEW_ROLES)].copy()
        sentiments = sentiment_series(reviews)
        evidence = _text_series(reviews, "evidence_level").str.upper()
        judged = int(sentiments.isin(SENTIMENT_LABELS).sum())
        review_count = len(reviews)
        ai_count = int(boolean_series(reviews, "ai_candidate").sum())
        rows.append(
            {
                "item_key": "" if pd.isna(item_key) else str(item_key),
                "product_title": (
                    "" if pd.isna(product_title) else str(product_title)
                ),
                "review_count": review_count,
                "question_count": int(roles.eq("question").sum()),
                "positive_count": int(sentiments.eq("P").sum()),
                "negative_count": int(sentiments.eq("N").sum()),
                "mixed_count": int(sentiments.eq("M").sum()),
                "neutral_count": int(sentiments.eq("Z").sum()),
                "ai_candidate_count": ai_count,
                "a_level_count": int(evidence.eq("A").sum()),
                "b_level_count": int(evidence.eq("B").sum()),
                "c_level_count": int(evidence.eq("C").sum()),
                "d_level_count": int(evidence.eq("D").sum()),
                "sentiment_coverage": (
                    judged / review_count if review_count else 0
                ),
                "ai_candidate_rate": (
                    ai_count / review_count if review_count else 0
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["review_count", "product_title"],
        ascending=[False, True],
    )


def build_month_summary(content: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "review_month",
        "review_count",
        "pre_purchase_decision_count",
        "ai_candidate_count",
        "a_level_count",
        "b_level_count",
        "c_level_count",
        "d_level_count",
        "ai_candidate_rate",
    ]
    if content.empty:
        return pd.DataFrame(columns=columns)
    roles = _text_series(content, "content_role")
    reviews = content[roles.isin(REVIEW_ROLES)].copy()
    if reviews.empty:
        return pd.DataFrame(columns=columns)
    dates = pd.Series("", index=reviews.index, dtype=str)
    for column in ("content_date", "review_date", "content_time"):
        if column not in reviews.columns:
            continue
        values = reviews[column].fillna("").astype(str).str[:10]
        missing = dates.str.strip().eq("")
        dates.loc[missing] = values.loc[missing]
    parsed = pd.to_datetime(dates, errors="coerce")
    reviews = reviews[parsed.notna()].copy()
    if reviews.empty:
        return pd.DataFrame(columns=columns)
    reviews["review_month"] = parsed.loc[reviews.index].dt.strftime("%Y-%m")
    rows = []
    for month, group in reviews.groupby("review_month", dropna=False):
        evidence = _text_series(group, "evidence_level").str.upper()
        ai_count = int(boolean_series(group, "ai_candidate").sum())
        rows.append(
            {
                "review_month": month,
                "review_count": len(group),
                "pre_purchase_decision_count": int(
                    boolean_series(group, "pre_purchase_decision").sum()
                ),
                "ai_candidate_count": ai_count,
                "a_level_count": int(evidence.eq("A").sum()),
                "b_level_count": int(evidence.eq("B").sum()),
                "c_level_count": int(evidence.eq("C").sum()),
                "d_level_count": int(evidence.eq("D").sum()),
                "ai_candidate_rate": (
                    ai_count / len(group) if len(group) else 0
                ),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("review_month")


def build_sentiment_metrics(
    fast: pd.DataFrame,
    detail: pd.DataFrame,
    failures: pd.DataFrame,
) -> dict:
    labels = sentiment_series(fast)
    scores = pd.to_numeric(
        fast.get("sentiment_score", pd.Series(dtype=float)),
        errors="coerce",
    )
    sources = _text_series(fast, "sentiment_source")
    return {
        "total_count": len(fast),
        "average_score": (
            float(scores.mean()) if not scores.empty and scores.notna().any() else 0.0
        ),
        "rule_count": int(sources.eq("rule").sum()),
        "llm_fast_count": int(sources.eq("llm_fast").sum()),
        "detail_count": (
            int(detail["content_id"].fillna("").astype(str).nunique())
            if not detail.empty and "content_id" in detail.columns
            else len(detail)
        ),
        "failed_count": len(failures),
        "sentiment_counts": {
            code: int(labels.eq(code).sum()) for code in SENTIMENT_LABELS
        },
    }


def sentiment_series(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series("", index=frame.index, dtype=str)
    result = pd.Series("", index=frame.index, dtype=str)
    for column in ("sentiment", "sentiment_label"):
        if column in frame.columns:
            values = frame[column].fillna("").astype(str).str.upper()
            missing = result.eq("")
            result.loc[missing] = values.loc[missing]
    if "sentiment_label_cn" in frame.columns:
        reverse = {label: code for code, label in SENTIMENT_LABELS.items()}
        values = (
            frame["sentiment_label_cn"]
            .fillna("")
            .astype(str)
            .map(reverse)
            .fillna("")
        )
        missing = result.eq("")
        result.loc[missing] = values.loc[missing]
    return result


def boolean_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].map(as_bool)


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    return str(value).strip().casefold() in {
        "1",
        "true",
        "yes",
        "y",
    }


def _text_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)
