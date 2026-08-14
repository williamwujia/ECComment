from __future__ import annotations

import pandas as pd


DEFAULT_REVIEW_RATE = 0.05
PLATFORM_LABELS = {
    "tmall": "天猫",
    "taobao": "淘宝",
    "jd": "京东",
}


def build_sales_history(
    content: pd.DataFrame,
    products: pd.DataFrame,
    *,
    review_rate: float = DEFAULT_REVIEW_RATE,
) -> pd.DataFrame:
    """Estimate monthly sales from dated primary reviews."""
    if not 0 < review_rate <= 1:
        raise ValueError("review_rate 必须大于 0 且不超过 1")

    columns = [
        "item_key",
        "product_title",
        "product_display_name",
        "platform",
        "sales_month",
        "review_count",
        "estimated_sales",
        "previous_estimated_sales",
        "sales_change",
        "trend",
    ]
    dated = _dated_primary_reviews(content)
    if dated.empty:
        return pd.DataFrame(columns=columns)

    product_meta = _product_metadata(products, content)
    summary = (
        dated.groupby(["item_key", "sales_month"], as_index=False)
        .size()
        .rename(columns={"size": "review_count"})
        .sort_values(["item_key", "sales_month"])
    )
    summary["product_title"] = summary["item_key"].map(
        lambda key: product_meta.get(key, {}).get("title", "")
    )
    summary["platform"] = summary["item_key"].map(
        lambda key: product_meta.get(key, {}).get("platform", "")
    )
    missing_platform = summary["platform"].eq("")
    summary.loc[missing_platform, "platform"] = summary.loc[
        missing_platform, "item_key"
    ].map(lambda key: key.split(":", 1)[0] if ":" in key else "")
    summary["product_display_name"] = summary.apply(
        lambda row: _display_name(
            row["item_key"], row["product_title"], row["platform"]
        ),
        axis=1,
    )
    summary["estimated_sales"] = summary["review_count"] / review_rate
    summary["previous_estimated_sales"] = summary.groupby("item_key")[
        "estimated_sales"
    ].shift(1)
    summary["sales_change"] = summary.groupby("item_key")[
        "estimated_sales"
    ].pct_change(fill_method=None)
    summary["trend"] = summary.apply(_trend_label, axis=1)
    return summary[columns].reset_index(drop=True)


def build_latest_sales_progress(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return history.copy()
    return (
        history.sort_values(["item_key", "sales_month"])
        .groupby("item_key", as_index=False)
        .tail(1)
        .sort_values("estimated_sales", ascending=False)
        .reset_index(drop=True)
    )


def sales_date_coverage(content: pd.DataFrame) -> dict[str, int | float]:
    roles = _text_series(content, "content_role").str.casefold()
    reviews = content[roles.eq("review")].copy()
    total = len(reviews)
    dated = len(_dated_primary_reviews(reviews))
    return {
        "total_reviews": total,
        "dated_reviews": dated,
        "undated_reviews": max(total - dated, 0),
        "coverage": dated / total if total else 0.0,
    }


def _dated_primary_reviews(content: pd.DataFrame) -> pd.DataFrame:
    if content.empty:
        return pd.DataFrame(columns=["item_key", "sales_month"])
    roles = _text_series(content, "content_role").str.casefold()
    reviews = content[roles.eq("review")].copy()
    if reviews.empty:
        return pd.DataFrame(columns=["item_key", "sales_month"])
    reviews["item_key"] = _text_series(reviews, "item_key")
    dates = pd.Series(pd.NaT, index=reviews.index, dtype="datetime64[ns]")
    for column in ("content_date", "content_time", "review_date"):
        if column not in reviews.columns:
            continue
        dates = dates.fillna(pd.to_datetime(reviews[column], errors="coerce"))
    reviews = reviews[reviews["item_key"].ne("") & dates.notna()].copy()
    reviews["sales_month"] = dates.loc[reviews.index].dt.strftime("%Y-%m")
    return reviews


def _trend_label(row: pd.Series) -> str:
    previous = row["previous_estimated_sales"]
    change = row["sales_change"]
    if pd.isna(previous):
        return "首个有数据月份"
    if change > 0:
        return "销量上升"
    if change < 0:
        return "销量下降"
    return "销量持平"


def _product_metadata(
    products: pd.DataFrame, content: pd.DataFrame
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    if not content.empty and "item_key" in content.columns:
        content_rows = content.copy()
        content_rows["item_key"] = _text_series(content_rows, "item_key")
        content_rows["platform"] = _text_series(content_rows, "platform")
        for key, rows in content_rows.groupby("item_key", sort=False):
            if key:
                platforms = rows["platform"][rows["platform"].ne("")]
                result[key] = {
                    "title": "",
                    "platform": platforms.iloc[-1] if not platforms.empty else "",
                }
    if products.empty or "item_key" not in products.columns:
        return result
    frame = products.copy()
    frame["item_key"] = _text_series(frame, "item_key")
    frame["platform"] = _text_series(frame, "platform")
    frame["product_title_current"] = _text_series(
        frame, "product_title_current"
    )
    frame = frame[frame["item_key"].ne("")].drop_duplicates(
        "item_key", keep="last"
    )
    for _, row in frame.iterrows():
        key = row["item_key"]
        platform = row["platform"] or result.get(key, {}).get("platform", "")
        result[key] = {
            "title": row["product_title_current"],
            "platform": platform,
        }
    return result


def _display_name(item_key: str, title: str, platform: str) -> str:
    normalized = str(platform).strip().casefold()
    if not normalized and ":" in item_key:
        normalized = item_key.split(":", 1)[0].casefold()
    platform_name = PLATFORM_LABELS.get(normalized, normalized.upper() or "未知平台")
    return f"[{platform_name}] {title or item_key}"


def _text_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str).str.strip()
