from __future__ import annotations

import pandas as pd

from ui.sales_progress import build_sales_progress


def test_first_snapshot_is_only_a_baseline() -> None:
    snapshots = pd.DataFrame(
        [{"snapshot_id": "s1", "item_key": "p1", "capture_time": "2026-08-01"}]
    )
    content = pd.DataFrame(
        [
            {
                "item_key": "p1",
                "content_role": "review",
                "first_seen_snapshot_id": "s1",
            },
            {
                "item_key": "p1",
                "content_role": "question",
                "first_seen_snapshot_id": "s1",
            },
        ]
    )

    result = build_sales_progress(content, snapshots, pd.DataFrame()).iloc[0]

    assert result["tracked_review_count"] == 1
    assert pd.isna(result["new_reviews"])
    assert result["trend"] == "已建立基线"


def test_review_growth_is_normalized_by_update_interval() -> None:
    snapshots = pd.DataFrame(
        [
            {"snapshot_id": "s1", "item_key": "p1", "capture_time": "2026-08-01"},
            {"snapshot_id": "s2", "item_key": "p1", "capture_time": "2026-08-05"},
            {"snapshot_id": "s3", "item_key": "p1", "capture_time": "2026-08-07"},
        ]
    )
    content = pd.DataFrame(
        [
            {
                "item_key": "p1",
                "content_role": "review",
                "first_seen_snapshot_id": snapshot_id,
            }
            for snapshot_id in ["s1", "s2", "s2", "s3", "s3", "s3", "s3"]
        ]
    )
    products = pd.DataFrame(
        [{"item_key": "p1", "product_title_current": "测试商品"}]
    )

    result = build_sales_progress(content, snapshots, products).iloc[0]

    assert result["product_title"] == "测试商品"
    assert result["interval_days"] == 2
    assert result["new_reviews"] == 4
    assert result["reviews_per_day"] == 2
    assert result["previous_reviews_per_day"] == 0.5
    assert result["rate_change"] == 3
    assert result["trend"] == "活跃度上升"


def test_no_new_review_is_reported_without_claiming_no_sales() -> None:
    snapshots = pd.DataFrame(
        [
            {"snapshot_id": "s1", "item_key": "p1", "capture_time": "2026-08-01"},
            {"snapshot_id": "s2", "item_key": "p1", "capture_time": "2026-08-08"},
        ]
    )
    content = pd.DataFrame(
        [
            {
                "item_key": "p1",
                "content_role": "review",
                "first_seen_snapshot_id": "s1",
            }
        ]
    )

    result = build_sales_progress(content, snapshots, pd.DataFrame()).iloc[0]

    assert result["new_reviews"] == 0
    assert result["reviews_per_day"] == 0
    assert result["trend"] == "本期暂无新增评论"
