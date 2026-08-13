from __future__ import annotations

import pandas as pd


REVIEW_ROLES = {"review", "followup"}


def build_sales_progress(
    content: pd.DataFrame,
    snapshots: pd.DataFrame,
    products: pd.DataFrame,
) -> pd.DataFrame:
    """Build a review-growth proxy for recent product sales activity.

    The result deliberately reports review growth instead of converting reviews
    into order counts.  A product's first snapshot is a baseline; only comments
    first observed in later snapshots are treated as interval growth.
    """
    columns = [
        "item_key",
        "product_title",
        "snapshot_count",
        "tracked_review_count",
        "latest_capture_time",
        "interval_days",
        "new_reviews",
        "reviews_per_day",
        "previous_reviews_per_day",
        "rate_change",
        "trend",
    ]
    if snapshots.empty or "item_key" not in snapshots.columns:
        return pd.DataFrame(columns=columns)

    snapshot_rows = snapshots.copy()
    snapshot_rows["item_key"] = _text_series(snapshot_rows, "item_key")
    snapshot_rows["snapshot_id"] = _text_series(snapshot_rows, "snapshot_id")
    snapshot_rows["_capture"] = pd.to_datetime(
        snapshot_rows.get("capture_time"), errors="coerce"
    )
    snapshot_rows = snapshot_rows[
        snapshot_rows["item_key"].ne("") & snapshot_rows["_capture"].notna()
    ].copy()
    if snapshot_rows.empty:
        return pd.DataFrame(columns=columns)

    reviews = content.copy()
    roles = _text_series(reviews, "content_role").str.casefold()
    reviews = reviews[roles.isin(REVIEW_ROLES)].copy()
    reviews["item_key"] = _text_series(reviews, "item_key")
    reviews["first_seen_snapshot_id"] = _text_series(
        reviews, "first_seen_snapshot_id"
    )
    new_by_snapshot = (
        reviews.groupby(["item_key", "first_seen_snapshot_id"]).size()
        if not reviews.empty
        else pd.Series(dtype="int64")
    )
    total_by_item = (
        reviews.groupby("item_key").size()
        if not reviews.empty
        else pd.Series(dtype="int64")
    )
    titles = _product_titles(products)

    rows: list[dict] = []
    for item_key, group in snapshot_rows.groupby("item_key", sort=False):
        history = group.sort_values(["_capture", "snapshot_id"]).drop_duplicates(
            "snapshot_id", keep="last"
        )
        latest = history.iloc[-1]
        snapshot_count = len(history)
        row = {
            "item_key": item_key,
            "product_title": titles.get(item_key, ""),
            "snapshot_count": snapshot_count,
            "tracked_review_count": int(total_by_item.get(item_key, 0)),
            "latest_capture_time": latest["_capture"],
            "interval_days": pd.NA,
            "new_reviews": pd.NA,
            "reviews_per_day": pd.NA,
            "previous_reviews_per_day": pd.NA,
            "rate_change": pd.NA,
            "trend": "已建立基线",
        }
        if snapshot_count >= 2:
            interval = _interval_metrics(history, snapshot_count - 1, new_by_snapshot)
            row.update(interval)
            previous_rate = pd.NA
            if snapshot_count >= 3:
                previous = _interval_metrics(
                    history, snapshot_count - 2, new_by_snapshot
                )
                previous_rate = previous["reviews_per_day"]
            row["previous_reviews_per_day"] = previous_rate
            row["rate_change"] = _rate_change(
                row["reviews_per_day"], previous_rate
            )
            row["trend"] = _trend(
                int(row["new_reviews"]), row["reviews_per_day"], previous_rate
            )
        rows.append(row)

    return pd.DataFrame(rows, columns=columns).sort_values(
        ["reviews_per_day", "tracked_review_count"],
        ascending=[False, False],
        na_position="last",
    )


def _interval_metrics(
    history: pd.DataFrame,
    position: int,
    new_by_snapshot: pd.Series,
) -> dict:
    current = history.iloc[position]
    previous = history.iloc[position - 1]
    elapsed_days = max(
        (current["_capture"] - previous["_capture"]).total_seconds() / 86400,
        0,
    )
    new_reviews = int(
        new_by_snapshot.get((current["item_key"], current["snapshot_id"]), 0)
    )
    return {
        "interval_days": elapsed_days,
        "new_reviews": new_reviews,
        "reviews_per_day": new_reviews / elapsed_days if elapsed_days else pd.NA,
    }


def _rate_change(current: object, previous: object) -> object:
    if pd.isna(current) or pd.isna(previous):
        return pd.NA
    current_value = float(current)
    previous_value = float(previous)
    if previous_value == 0:
        return pd.NA
    return current_value / previous_value - 1


def _trend(new_reviews: int, current: object, previous: object) -> str:
    if pd.isna(current):
        return "更新间隔无效"
    if new_reviews == 0:
        return "本期暂无新增评论"
    if pd.isna(previous):
        return "已有评论增长"
    previous_value = float(previous)
    current_value = float(current)
    if previous_value == 0:
        return "活跃度上升"
    change = current_value / previous_value - 1
    if change >= 0.2:
        return "活跃度上升"
    if change <= -0.2:
        return "活跃度回落"
    return "活跃度平稳"


def _product_titles(products: pd.DataFrame) -> dict[str, str]:
    if products.empty or "item_key" not in products.columns:
        return {}
    frame = products.copy()
    frame["item_key"] = _text_series(frame, "item_key")
    frame["product_title_current"] = _text_series(
        frame, "product_title_current"
    )
    frame = frame[frame["item_key"].ne("")].drop_duplicates(
        "item_key", keep="last"
    )
    return frame.set_index("item_key")["product_title_current"].to_dict()


def _text_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str).str.strip()
