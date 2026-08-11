from __future__ import annotations

import pandas as pd

from ui.tracker_metrics import (
    build_brand_overview,
    build_month_summary,
    build_product_comparison,
    build_sentiment_metrics,
)


def sample_content() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "item_key": "p1",
                "product_title": "商品一",
                "platform": "tmall",
                "content_role": "review",
                "sentiment_label": "P",
                "evidence_level": "A",
                "ai_candidate": True,
                "pre_purchase_decision": True,
            },
            {
                "item_key": "p1",
                "product_title": "商品一",
                "platform": "taobao",
                "content_role": "followup",
                "sentiment_label": "N",
                "evidence_level": "D",
                "ai_candidate": False,
                "pre_purchase_decision": True,
            },
            {
                "item_key": "p2",
                "product_title": "商品二",
                "platform": "jd",
                "content_role": "review",
                "sentiment_label_cn": "褒贬混合",
                "evidence_level": "B",
                "ai_candidate": "true",
                "pre_purchase_decision": True,
            },
            {
                "item_key": "p2",
                "product_title": "商品二",
                "platform": "jd",
                "content_role": "review",
                "sentiment_label": "Z",
                "evidence_level": "C",
                "ai_candidate": "yes",
                "pre_purchase_decision": True,
            },
            {
                "item_key": "p2",
                "product_title": "商品二",
                "platform": "jd",
                "content_role": "review",
                "sentiment_label": "",
                "evidence_level": "",
                "ai_candidate": False,
                "pre_purchase_decision": False,
            },
            {
                "item_key": "p1",
                "product_title": "商品一",
                "platform": "taobao",
                "content_role": "question",
            },
            {
                "item_key": "p1",
                "product_title": "商品一",
                "platform": "tmall",
                "content_role": "answer",
            },
        ]
    )


def test_brand_overview_counts_viewer_metrics() -> None:
    overview = build_brand_overview(sample_content())

    assert overview["total_content_count"] == 7
    assert overview["review_count"] == 5
    assert overview["question_count"] == 1
    assert overview["answer_count"] == 1
    assert overview["taobao_tmall_review_count"] == 2
    assert overview["taobao_tmall_question_count"] == 1
    assert overview["taobao_tmall_answer_count"] == 1
    assert overview["platform_content_counts"] == {
        "jd": 3,
        "tmall": 2,
        "taobao": 2,
    }
    assert overview["sentiment_counts"] == {
        "P": 1,
        "N": 1,
        "M": 1,
        "Z": 1,
    }
    assert overview["sentiment_unjudged_count"] == 1
    assert overview["evidence_counts"] == {
        "A": 1,
        "B": 1,
        "C": 1,
        "D": 1,
    }
    assert overview["evidence_ungraded_count"] == 1
    assert overview["ai_candidate_count"] == 3


def test_product_comparison_keeps_brand_facing_breakdown() -> None:
    summary = build_product_comparison(sample_content()).set_index("item_key")

    assert summary.loc["p1", "review_count"] == 2
    assert summary.loc["p1", "question_count"] == 1
    assert summary.loc["p1", "positive_count"] == 1
    assert summary.loc["p1", "negative_count"] == 1
    assert summary.loc["p1", "a_level_count"] == 1
    assert summary.loc["p1", "d_level_count"] == 1

    assert summary.loc["p2", "review_count"] == 3
    assert summary.loc["p2", "mixed_count"] == 1
    assert summary.loc["p2", "neutral_count"] == 1
    assert summary.loc["p2", "ai_candidate_count"] == 2
    assert summary.loc["p2", "sentiment_coverage"] == 2 / 3


def test_month_summary_builds_three_stage_trend() -> None:
    content = pd.DataFrame(
        [
            {
                "content_role": "review",
                "content_date": "2026-01-03",
                "pre_purchase_decision": True,
                "ai_candidate": True,
                "evidence_level": "A",
            },
            {
                "content_role": "followup",
                "content_time": "2026-01-18 10:00:00",
                "pre_purchase_decision": False,
                "ai_candidate": False,
                "evidence_level": "",
            },
            {
                "content_role": "review",
                "review_date": "2026-02-01",
                "pre_purchase_decision": True,
                "ai_candidate": True,
                "evidence_level": "C",
            },
            {
                "content_role": "question",
                "content_date": "2026-02-01",
                "pre_purchase_decision": True,
                "ai_candidate": True,
            },
        ]
    )

    summary = build_month_summary(content).set_index("review_month")

    assert summary.loc["2026-01", "review_count"] == 2
    assert summary.loc["2026-01", "pre_purchase_decision_count"] == 1
    assert summary.loc["2026-01", "ai_candidate_count"] == 1
    assert summary.loc["2026-01", "a_level_count"] == 1
    assert summary.loc["2026-02", "review_count"] == 1
    assert summary.loc["2026-02", "c_level_count"] == 1


def test_sentiment_metrics_report_pipeline_sources_and_details() -> None:
    fast = pd.DataFrame(
        [
            {
                "content_id": "1",
                "sentiment_label": "P",
                "sentiment_score": 8,
                "sentiment_source": "rule",
            },
            {
                "content_id": "2",
                "sentiment_label": "M",
                "sentiment_score": 6,
                "sentiment_source": "llm_fast",
            },
        ]
    )
    detail = pd.DataFrame([{"content_id": "2"}])
    failures = pd.DataFrame(columns=["content_id"])

    metrics = build_sentiment_metrics(fast, detail, failures)

    assert metrics["total_count"] == 2
    assert metrics["average_score"] == 7
    assert metrics["rule_count"] == 1
    assert metrics["llm_fast_count"] == 1
    assert metrics["detail_count"] == 1
    assert metrics["failed_count"] == 0
    assert metrics["sentiment_counts"]["P"] == 1
    assert metrics["sentiment_counts"]["M"] == 1
