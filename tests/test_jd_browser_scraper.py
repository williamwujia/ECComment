import json

from jd_browser_scraper import (
    ScrapeTarget,
    merge_review_rows,
    normalize_review,
    parse_target_line,
    product_id_from_url,
    write_results,
)


def test_product_id_from_standard_and_query_urls():
    assert product_id_from_url("https://item.jd.com/100012043978.html") == "100012043978"
    assert product_id_from_url("https://item.m.jd.com/product/100.html?sku=9988") == "9988"


def test_parse_target_line():
    target = parse_target_line("https://item.jd.com/100012043978.html, 25")
    assert target == ScrapeTarget("https://item.jd.com/100012043978.html", 25)


def test_normalize_review_maps_required_fields():
    target = ScrapeTarget("https://item.jd.com/123456.html", 10)
    row = normalize_review(
        {
            "user": "j***8",
            "rating": "star5",
            "time": "2026-07-21 12:30",
            "sku": "黑色 256GB",
            "text": "  很好用，运行流畅。 ",
            "product_name": "测试手机",
        },
        target,
        "页面标题",
        1,
    )
    assert row is not None
    assert row["platform"] == "jd"
    assert row["product_id"] == "123456"
    assert row["user_name_masked"] == "j***8"
    assert row["rating"] == "5"
    assert row["review_date"] == "2026-07-21"
    assert row["product_title"] == "测试手机"
    assert row["review_text_clean"] == "很好用，运行流畅。"


def test_merge_review_rows_deduplicates_checkpoints():
    destination = [{"review_hash": "a", "review_text_raw": "第一条"}]
    added = merge_review_rows(
        destination,
        [
            {"review_hash": "a", "review_text_raw": "第一条"},
            {"review_hash": "b", "review_text_raw": "第二条"},
        ],
    )
    assert added == 1
    assert [row["review_hash"] for row in destination] == ["a", "b"]


def test_write_results_reuses_checkpoint_files(tmp_path):
    first = [{"review_hash": "a", "review_text_raw": "第一条"}]
    second = [*first, {"review_hash": "b", "review_text_raw": "第二条"}]

    json_path, csv_path = write_results(first, tmp_path, "checkpoint")
    same_json_path, same_csv_path = write_results(second, tmp_path, "checkpoint")

    assert same_json_path == json_path
    assert same_csv_path == csv_path
    assert len(json.loads(json_path.read_text(encoding="utf-8"))) == 2
    assert not list(tmp_path.glob("*.tmp"))
