from __future__ import annotations

import pandas as pd

from ui.update_reminders import platform_display_name, stale_sku_updates


def test_platform_display_name_uses_chinese_labels_and_safe_fallbacks():
    assert platform_display_name("tmall") == "天猫"
    assert platform_display_name(" Taobao ") == "淘宝"
    assert platform_display_name("JD") == "京东"
    assert platform_display_name("amazon") == "amazon"
    assert platform_display_name("") == "未标明"


def test_stale_sku_updates_uses_latest_snapshot_per_sku():
    products = pd.DataFrame(
        [
            {"item_key": "tmall:old", "platform": "tmall", "platform_product_id": "old", "product_title_current": "旧 SKU"},
            {"item_key": "tmall:fresh", "platform": "tmall", "platform_product_id": "fresh", "product_title_current": "新 SKU"},
            {"item_key": "jd:missing", "platform": "jd", "platform_product_id": "missing", "product_title_current": "无记录 SKU"},
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
    assert result["platform"].tolist() == ["jd", "tmall"]
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
