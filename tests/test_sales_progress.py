from __future__ import annotations

import pandas as pd

from ui.sales_progress import (
    build_latest_sales_progress,
    build_sales_history,
    sales_date_coverage,
)


def sample_content() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"item_key": "p1", "platform": "tmall", "content_role": "review", "content_date": "2026-06-03"},
            {"item_key": "p1", "content_role": "review", "content_time": "2026-06-20 12:00"},
            {"item_key": "p1", "content_role": "followup", "content_date": "2026-06-25"},
            {"item_key": "p1", "content_role": "review", "content_date": "2026-07-01"},
            {"item_key": "p1", "content_role": "review", "content_date": "2026-07-08"},
            {"item_key": "p1", "content_role": "review", "content_date": "2026-07-12"},
            {"item_key": "p2", "content_role": "review", "content_date": "2026-07-15"},
            {"item_key": "p2", "content_role": "review", "content_date": ""},
            {"item_key": "p2", "content_role": "question", "content_date": "2026-07-16"},
        ]
    )


def test_estimates_monthly_sales_from_review_dates_at_five_percent() -> None:
    products = pd.DataFrame(
        [{"item_key": "p1", "platform": "tmall", "product_title_current": "测试商品"}]
    )
    history = build_sales_history(sample_content(), products)
    p1 = history[history["item_key"].eq("p1")].set_index("sales_month")

    assert p1.loc["2026-06", "review_count"] == 2
    assert p1.loc["2026-06", "estimated_sales"] == 40
    assert p1.loc["2026-07", "review_count"] == 3
    assert p1.loc["2026-07", "estimated_sales"] == 60
    assert p1.loc["2026-07", "sales_change"] == 0.5
    assert p1.loc["2026-07", "trend"] == "销量上升"
    assert p1.loc["2026-07", "product_title"] == "测试商品"
    assert p1.loc["2026-07", "product_display_name"] == "[天猫] 测试商品"
    assert p1.loc["2026-07", "platform"] == "tmall"


def test_excludes_followups_questions_and_undated_reviews() -> None:
    history = build_sales_history(sample_content(), pd.DataFrame())
    coverage = sales_date_coverage(sample_content())

    assert history["review_count"].sum() == 6
    assert coverage == {
        "total_reviews": 7,
        "dated_reviews": 6,
        "undated_reviews": 1,
        "coverage": 6 / 7,
    }


def test_latest_progress_uses_latest_month_for_each_product() -> None:
    latest = build_latest_sales_progress(
        build_sales_history(sample_content(), pd.DataFrame())
    ).set_index("item_key")

    assert latest.loc["p1", "sales_month"] == "2026-07"
    assert latest.loc["p1", "estimated_sales"] == 60
    assert latest.loc["p2", "estimated_sales"] == 20


def test_review_rate_must_be_valid() -> None:
    try:
        build_sales_history(sample_content(), pd.DataFrame(), review_rate=0)
    except ValueError as exc:
        assert "review_rate" in str(exc)
    else:
        raise AssertionError("zero review rate should be rejected")


def test_custom_review_rate_recalculates_estimated_sales() -> None:
    history = build_sales_history(
        sample_content(),
        pd.DataFrame(),
        review_rate=0.10,
    )
    p1 = history[history["item_key"].eq("p1")].set_index("sales_month")

    assert p1.loc["2026-06", "estimated_sales"] == 20
    assert p1.loc["2026-07", "estimated_sales"] == 30
    assert p1.loc["2026-07", "sales_change"] == 0.5


def test_product_name_marks_jd_platform_from_item_key() -> None:
    content = pd.DataFrame(
        [
            {
                "item_key": "jd:123",
                "content_role": "review",
                "content_date": "2026-07-01",
            }
        ]
    )

    row = build_sales_history(content, pd.DataFrame()).iloc[0]

    assert row["product_display_name"] == "[京东] jd:123"
    assert row["platform"] == "jd"
