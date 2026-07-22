from jd_browser_scraper import ScrapeTarget, normalize_review, parse_target_line, product_id_from_url


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
