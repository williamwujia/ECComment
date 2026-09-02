from __future__ import annotations

import asyncio

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from wechat_sales import estimate_service
from wechat_sales.app import app


client = TestClient(app)


def _write_project_workbook(path, *, product_title="测试护眼灯"):
    products = pd.DataFrame(
        [
            {
                "project_id": "project-1",
                "item_key": "tmall:123456789",
                "platform": "tmall",
                "platform_product_id": "123456789",
                "product_title_current": product_title,
                "last_updated_at": "2026-08-31 10:00:00",
            }
        ]
    )
    content = pd.DataFrame(
        [
            {
                "item_key": "tmall:123456789",
                "platform": "tmall",
                "content_role": "review",
                "content_date": "2026-07-03",
            },
            {
                "item_key": "tmall:123456789",
                "platform": "tmall",
                "content_role": "review",
                "content_date": "2026-08-12",
            },
            {
                "item_key": "tmall:123456789",
                "platform": "tmall",
                "content_role": "review",
                "content_date": "",
            },
            {
                "item_key": "tmall:123456789",
                "platform": "tmall",
                "content_role": "qa_question",
                "content_date": "2026-08-20",
            },
        ]
    )
    snapshots = pd.DataFrame(
        [
            {
                "item_key": "tmall:123456789",
                "capture_time": "2026-08-31 09:30:00",
            }
        ]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        products.to_excel(writer, sheet_name="products", index=False)
        content.to_excel(writer, sheet_name="content_master", index=False)
        snapshots.to_excel(writer, sheet_name="snapshots", index=False)


def test_build_catalog_reuses_monthly_sales_contract(tmp_path):
    _write_project_workbook(tmp_path / "project.xlsx")

    records = estimate_service.build_catalog(tmp_path)

    result = records[("tmall", "123456789")].response()
    assert result == {
        "status": "ok",
        "product_name": "测试护眼灯",
        "platform": "tmall",
        "period": "2026-08",
        "estimated_sales": 20,
        "review_count": 1,
        "data_date": "2026-08-31",
        "review_rate": 0.05,
        "date_coverage": 66.7,
    }


def test_resolve_direct_tmall_product_reference():
    result = asyncio.run(
        estimate_service.resolve_product_reference(
            "复制 https://detail.tmall.com/item.htm?id=123456789 查看"
        )
    )

    assert result == ("tmall", "123456789")


def test_catalog_uses_unique_full_title_when_short_link_cannot_be_resolved(
    tmp_path, monkeypatch
):
    product_title = "测试儿童阅读学习专用护眼台灯"
    _write_project_workbook(tmp_path / "project.xlsx", product_title=product_title)
    catalog = estimate_service.EstimateCatalog(tmp_path)

    async def blocked_short_link(_query):
        raise estimate_service.EstimateUnavailable(
            "Taobao short link did not identify a product"
        )

    monkeypatch.setattr(
        estimate_service, "resolve_product_reference", blocked_short_link
    )

    result = asyncio.run(
        catalog.estimate(
            "【淘宝】假一赔四 https://e.tb.cn/h.test "
            f"「{product_title}」 点击链接直接打开"
        )
    )

    assert result["product_name"] == product_title
    assert result["estimated_sales"] == 20


def test_catalog_rejects_ambiguous_full_title_fallback(tmp_path, monkeypatch):
    product_title = "测试儿童阅读学习专用护眼台灯"
    _write_project_workbook(tmp_path / "first.xlsx", product_title=product_title)
    _write_project_workbook(tmp_path / "second.xlsx", product_title=product_title)
    products = pd.read_excel(tmp_path / "second.xlsx", sheet_name="products")
    content = pd.read_excel(tmp_path / "second.xlsx", sheet_name="content_master")
    snapshots = pd.read_excel(tmp_path / "second.xlsx", sheet_name="snapshots")
    products["item_key"] = "tmall:987654321"
    products["platform_product_id"] = "987654321"
    content["item_key"] = "tmall:987654321"
    snapshots["item_key"] = "tmall:987654321"
    with pd.ExcelWriter(tmp_path / "second.xlsx", engine="openpyxl") as writer:
        products.to_excel(writer, sheet_name="products", index=False)
        content.to_excel(writer, sheet_name="content_master", index=False)
        snapshots.to_excel(writer, sheet_name="snapshots", index=False)
    catalog = estimate_service.EstimateCatalog(tmp_path)

    async def blocked_short_link(_query):
        raise estimate_service.EstimateUnavailable("short link blocked")

    monkeypatch.setattr(
        estimate_service, "resolve_product_reference", blocked_short_link
    )

    with pytest.raises(estimate_service.EstimateUnavailable):
        asyncio.run(catalog.estimate(f"https://e.tb.cn/h.test 「{product_title}」"))


def test_catalog_does_not_use_title_fallback_without_short_link(tmp_path, monkeypatch):
    product_title = "测试儿童阅读学习专用护眼台灯"
    _write_project_workbook(tmp_path / "project.xlsx", product_title=product_title)
    catalog = estimate_service.EstimateCatalog(tmp_path)

    async def missing_link(_query):
        raise estimate_service.EstimateUnavailable("No supported product link")

    monkeypatch.setattr(estimate_service, "resolve_product_reference", missing_link)

    with pytest.raises(estimate_service.EstimateUnavailable):
        asyncio.run(catalog.estimate(product_title))


def test_estimate_endpoint_requires_bearer_token(monkeypatch):
    monkeypatch.setenv("ECCOMMENT_ESTIMATE_TOKEN", "private-service-token")

    response = client.post(
        "/api/sales/estimate",
        json={"query": "query", "source": "wechat", "request_id": "msg-1"},
    )

    assert response.status_code == 401
    assert response.json() == {"status": "error", "error": "unauthorized"}


def test_estimate_endpoint_returns_catalog_result(monkeypatch):
    class FakeCatalog:
        async def estimate(self, query):
            assert query == "https://item.taobao.com/item.htm?id=123456789"
            return {
                "status": "ok",
                "product_name": "测试商品",
                "platform": "taobao",
                "period": "2026-08",
                "estimated_sales": 40,
                "review_count": 2,
                "data_date": "2026-08-31",
                "review_rate": 0.05,
                "date_coverage": 100.0,
            }

    monkeypatch.setenv("ECCOMMENT_ESTIMATE_TOKEN", "private-service-token")
    monkeypatch.setattr("wechat_sales.app.configured_catalog", lambda: FakeCatalog())

    response = client.post(
        "/api/sales/estimate",
        headers={"Authorization": "Bearer private-service-token"},
        json={
            "query": "https://item.taobao.com/item.htm?id=123456789",
            "source": "wechat",
            "request_id": "msg-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["estimated_sales"] == 40
