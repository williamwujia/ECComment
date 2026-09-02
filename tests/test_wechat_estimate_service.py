from __future__ import annotations

import asyncio

import pandas as pd
from fastapi.testclient import TestClient

from wechat_sales import estimate_service
from wechat_sales.app import app


client = TestClient(app)


def _write_project_workbook(path):
    products = pd.DataFrame(
        [
            {
                "project_id": "project-1",
                "item_key": "tmall:123456789",
                "platform": "tmall",
                "platform_product_id": "123456789",
                "product_title_current": "测试护眼灯",
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
