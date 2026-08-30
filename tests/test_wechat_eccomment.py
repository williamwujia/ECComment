from __future__ import annotations

import asyncio

import pytest

from wechat_sales import eccomment


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_query_eccomment_posts_contract_and_bearer_token(monkeypatch):
    captured = {}
    payload = {
        "status": "ok",
        "product_name": "商品",
        "platform": "taobao",
    }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, json, headers):
            captured.update(url=url, json=json, headers=headers)
            return _FakeResponse(payload)

    monkeypatch.setenv("ECCOMMENT_ESTIMATE_URL", "https://eccomment.test/api/sales/estimate")
    monkeypatch.setenv("ECCOMMENT_ESTIMATE_TOKEN", "secret-token")
    monkeypatch.setenv("ECCOMMENT_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setattr(eccomment.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        eccomment.query_eccomment("分享 https://e.tb.cn/demo", request_id="msg-1")
    )

    assert result is payload
    assert captured == {
        "timeout": 3.5,
        "url": "https://eccomment.test/api/sales/estimate",
        "json": {
            "query": "分享 https://e.tb.cn/demo",
            "source": "wechat",
            "request_id": "msg-1",
        },
        "headers": {
            "Accept": "application/json",
            "Authorization": "Bearer secret-token",
        },
    }


def test_query_eccomment_requires_configured_url(monkeypatch):
    monkeypatch.delenv("ECCOMMENT_ESTIMATE_URL", raising=False)

    with pytest.raises(eccomment.ECCommentError):
        asyncio.run(eccomment.query_eccomment("query", request_id="msg-1"))


def test_format_wechat_result_rejects_incomplete_success():
    with pytest.raises(eccomment.ECCommentError):
        eccomment.format_wechat_result({"status": "ok", "product_name": "商品"})
