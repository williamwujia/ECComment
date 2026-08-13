from __future__ import annotations

from datetime import timedelta

import pandas as pd


REMINDER_AFTER_DAYS = 14


def stale_sku_updates(
    products: pd.DataFrame,
    snapshots: pd.DataFrame,
    *,
    now: object | None = None,
    reminder_after_days: int = REMINDER_AFTER_DAYS,
) -> pd.DataFrame:
    """Return SKUs whose latest update record is older than the threshold."""
    columns = [
        "item_key",
        "sku",
        "product_title_current",
        "last_update_at",
        "days_since_update",
    ]
    if products.empty or "item_key" not in products.columns:
        return pd.DataFrame(columns=columns)

    reference_time = pd.Timestamp.now() if now is None else pd.Timestamp(now)
    if pd.isna(reference_time):
        raise ValueError("now must be a valid date/time")
    if reference_time.tzinfo is not None:
        reference_time = reference_time.tz_localize(None)

    product_rows = products.copy()
    product_rows["item_key"] = product_rows["item_key"].fillna("").astype(str)
    product_rows = product_rows[product_rows["item_key"].ne("")].drop_duplicates(
        "item_key", keep="last"
    )

    latest_by_item = pd.Series(dtype="datetime64[ns]")
    if not snapshots.empty and {"item_key", "capture_time"}.issubset(snapshots.columns):
        snapshot_rows = snapshots[["item_key", "capture_time"]].copy()
        snapshot_rows["item_key"] = snapshot_rows["item_key"].fillna("").astype(str)
        snapshot_rows["capture_time"] = pd.to_datetime(
            snapshot_rows["capture_time"], errors="coerce"
        )
        latest_by_item = snapshot_rows.groupby("item_key")["capture_time"].max()

    result = product_rows[["item_key"]].copy()
    result["last_update_at"] = result["item_key"].map(latest_by_item)
    result["days_since_update"] = (reference_time - result["last_update_at"]).dt.days
    overdue = result["last_update_at"].isna() | (
        result["last_update_at"] < reference_time - timedelta(days=reminder_after_days)
    )
    result = result.loc[overdue].copy()
    if result.empty:
        return pd.DataFrame(columns=columns)

    details = product_rows.set_index("item_key")
    result["sku"] = details.get("platform_product_id", pd.Series(dtype=str)).reindex(
        result["item_key"]
    ).fillna("").astype(str).to_numpy()
    result["product_title_current"] = details.get(
        "product_title_current", pd.Series(dtype=str)
    ).reindex(result["item_key"]).fillna("").astype(str).to_numpy()
    result["days_since_update"] = result["days_since_update"].astype("Int64")
    return result.sort_values(
        ["last_update_at", "item_key"], na_position="first"
    ).reset_index(drop=True)[columns]
