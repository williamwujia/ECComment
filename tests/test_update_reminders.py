from __future__ import annotations

import pandas as pd

from ui.update_reminders import stale_sku_updates


def test_stale_sku_updates_uses_latest_snapshot_per_sku():
    products = pd.DataFrame(
        [
            {"item_key": "tmall:old", "platform_product_id": "old", "product_title_current": "旧 SKU"},
            {"item_key": "tmall:fresh", "platform_product_id": "fresh", "product_title_current": "新 SKU"},
            {"item_key": "tmall:missing", "platform_product_id": "missing", "product_title_current": "无记录 SKU"},
        ]
    )
    snapshots = pd.DataFrame(
        [
            {"item_key": "tmall:old", "capture_time": "2026-07-01 10:00"},
            {"item_key": "tmall:old", "capture_time": "2026-07-10 10:00"},
            {"item_key": "tmall:fresh", "capture_time": "2026-08-01 10:00"},
        ]
    )

    result = stale_sku_updates(products, snapshots, now="2026-08-11 10:00")

    assert result["sku"].tolist() == ["missing", "old"]
    assert result.loc[1, "last_update_at"] == pd.Timestamp("2026-07-10 10:00")
    assert result.loc[1, "days_since_update"] == 32


def test_stale_sku_updates_does_not_remind_before_two_weeks():
    products = pd.DataFrame(
        [{"item_key": "tmall:recent", "platform_product_id": "recent"}]
    )
    snapshots = pd.DataFrame(
        [{"item_key": "tmall:recent", "capture_time": "2026-07-29"}]
    )

    result = stale_sku_updates(products, snapshots, now="2026-08-11")

    assert result.empty


def test_stale_sku_updates_does_not_remind_at_exactly_two_weeks():
    products = pd.DataFrame(
        [{"item_key": "tmall:exact", "platform_product_id": "exact"}]
    )
    snapshots = pd.DataFrame(
        [{"item_key": "tmall:exact", "capture_time": "2026-07-28"}]
    )

    result = stale_sku_updates(products, snapshots, now="2026-08-11")

    assert result.empty
