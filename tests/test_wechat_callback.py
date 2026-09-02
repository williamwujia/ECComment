from __future__ import annotations

import base64
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from wechat_sales.app import app
from wechat_sales.crypto import (
    build_message_signature,
    build_wechat_signature,
    decrypt_message,
    encrypt_message,
    verify_message_signature,
    verify_wechat_signature,
)
from wechat_sales.eccomment import ECCommentError, format_wechat_result


client = TestClient(app)


def test_signature_uses_sorted_token_timestamp_and_nonce():
    signature = build_wechat_signature("token-b", "1700000000", "nonce-a")

    assert signature == "6bae090b9fe2ab46d6feb7015ec8b61b192ea578"
    assert verify_wechat_signature(
        token="token-b",
        timestamp="1700000000",
        nonce="nonce-a",
        signature=signature,
    )


def test_get_callback_returns_echostr_as_plain_text(monkeypatch):
    token = "local-test-token"
    timestamp = "1700000001"
    nonce = "abc123"
    echostr = "challenge-value"
    signature = build_wechat_signature(token, timestamp, nonce)
    monkeypatch.setenv("WECHAT_TOKEN", token)

    response = client.get(
        "/wechat/callback",
        params={
            "signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
            "echostr": echostr,
        },
    )

    assert response.status_code == 200
    assert response.text == echostr
    assert response.headers["content-type"].startswith("text/plain")


def test_get_callback_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("WECHAT_TOKEN", "local-test-token")

    response = client.get(
        "/wechat/callback",
        params={
            "signature": "invalid",
            "timestamp": "1700000001",
            "nonce": "abc123",
            "echostr": "must-not-be-returned",
        },
    )

    assert response.status_code == 403
    assert response.text == "Forbidden"


def test_get_callback_rejects_when_token_is_not_configured(monkeypatch):
    monkeypatch.delenv("WECHAT_TOKEN", raising=False)

    response = client.get(
        "/wechat/callback",
        params={
            "signature": build_wechat_signature("", "1700000001", "abc123"),
            "timestamp": "1700000001",
            "nonce": "abc123",
            "echostr": "must-not-be-returned",
        },
    )

    assert response.status_code == 403


def test_get_callback_rejects_missing_verification_parameters(monkeypatch):
    monkeypatch.setenv("WECHAT_TOKEN", "local-test-token")

    response = client.get("/wechat/callback")

    assert response.status_code == 403


def _message_xml(
    *, content: str = "hello", msg_type: str = "text", to_user: str = "official-account"
) -> str:
    root = ET.Element("xml")
    ET.SubElement(root, "ToUserName").text = to_user
    ET.SubElement(root, "FromUserName").text = "user-open-id"
    ET.SubElement(root, "CreateTime").text = "1700000000"
    ET.SubElement(root, "MsgType").text = msg_type
    ET.SubElement(root, "Content").text = content
    ET.SubElement(root, "MsgId").text = "123456789"
    return ET.tostring(root, encoding="unicode")


def _post_plaintext(monkeypatch, xml: str):
    token = "local-test-token"
    timestamp = "1700000001"
    nonce = "abc123"
    monkeypatch.setenv("WECHAT_TOKEN", token)
    return client.post(
        "/wechat/callback",
        params={
            "signature": build_wechat_signature(token, timestamp, nonce),
            "timestamp": timestamp,
            "nonce": nonce,
        },
        content=xml.encode("utf-8"),
        headers={"content-type": "application/xml"},
    )


def test_post_plaintext_prompts_for_taobao_link_and_swaps_users(monkeypatch, caplog):
    with caplog.at_level("INFO", logger="uvicorn.error"):
        response = _post_plaintext(monkeypatch, _message_xml())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(response.content)
    assert root.findtext("ToUserName") == "user-open-id"
    assert root.findtext("FromUserName") == "official-account"
    assert root.findtext("MsgType") == "text"
    assert root.findtext("Content") == "请发送淘宝商品链接"
    assert root.findtext("CreateTime", "").isdigit()
    assert "MsgType=text" in caplog.text
    assert "FromUserName=user-open-id" in caplog.text
    assert "Content=hello" in caplog.text


def test_post_plaintext_non_link_does_not_call_eccomment(monkeypatch):
    async def unexpected_call(*args, **kwargs):
        raise AssertionError("ECComment must not be called for non-link text")

    monkeypatch.setattr("wechat_sales.app.query_eccomment", unexpected_call)
    response = _post_plaintext(monkeypatch, _message_xml(content="a < b & c"))

    assert response.status_code == 200
    assert ET.fromstring(response.content).findtext("Content") == "请发送淘宝商品链接"


def _estimate_result():
    return {
        "status": "ok",
        "product_name": "示例商品",
        "platform": "taobao",
        "period": "2026-08",
        "estimated_sales": 2460,
        "review_count": 123,
        "data_date": "2026-08-31",
        "review_rate": 0.05,
        "date_coverage": 96.5,
    }


def test_post_plaintext_taobao_link_calls_eccomment_and_formats_result(monkeypatch):
    calls = []

    async def fake_query(query, *, request_id):
        calls.append((query, request_id))
        return _estimate_result()

    monkeypatch.setattr("wechat_sales.app.query_eccomment", fake_query)
    content = "分享商品 https://e.tb.cn/h.test 请查看"

    response = _post_plaintext(monkeypatch, _message_xml(content=content))

    assert response.status_code == 200
    assert calls == [(content, "123456789")]
    reply = ET.fromstring(response.content).findtext("Content", "")
    assert reply == format_wechat_result(_estimate_result())
    assert "商品：示例商品" in reply
    assert "估算销量：约 2,460 单" in reply


def test_post_plaintext_accepts_supported_taobao_and_tmall_domains(monkeypatch):
    calls = []

    async def fake_query(query, *, request_id):
        calls.append(query)
        return _estimate_result()

    monkeypatch.setattr("wechat_sales.app.query_eccomment", fake_query)

    for domain in ("item.taobao.com", "detail.tmall.com"):
        response = _post_plaintext(
            monkeypatch, _message_xml(content=f"https://{domain}/item.htm?id=1")
        )
        assert response.status_code == 200

    assert len(calls) == 2


def test_post_plaintext_rejects_domain_prefix_spoof(monkeypatch):
    async def unexpected_call(*args, **kwargs):
        raise AssertionError("spoofed domain must not reach ECComment")

    monkeypatch.setattr("wechat_sales.app.query_eccomment", unexpected_call)
    response = _post_plaintext(
        monkeypatch, _message_xml(content="https://e.tb.cn.evil.example/item")
    )

    assert response.status_code == 200
    assert ET.fromstring(response.content).findtext("Content") == "请发送淘宝商品链接"


def test_post_plaintext_eccomment_failure_returns_safe_message_and_logs(
    monkeypatch, caplog
):
    async def failed_query(query, *, request_id):
        raise ECCommentError("internal downstream detail")

    monkeypatch.setattr("wechat_sales.app.query_eccomment", failed_query)

    with caplog.at_level("ERROR", logger="uvicorn.error"):
        response = _post_plaintext(
            monkeypatch, _message_xml(content="https://item.taobao.com/item.htm?id=1")
        )

    assert response.status_code == 200
    assert ET.fromstring(response.content).findtext("Content") == "查询失败，请稍后重试"
    assert "ECComment query failed request_id=123456789" in caplog.text


def test_post_non_text_message_returns_success(monkeypatch, caplog):
    with caplog.at_level("INFO", logger="uvicorn.error"):
        response = _post_plaintext(
            monkeypatch, _message_xml(content="", msg_type="image")
        )

    assert response.status_code == 200
    assert response.text == "success"
    assert "MsgType=image" in caplog.text


def test_post_plaintext_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("WECHAT_TOKEN", "local-test-token")

    response = client.post(
        "/wechat/callback",
        params={"signature": "invalid", "timestamp": "1700000001", "nonce": "abc"},
        content=_message_xml(),
    )

    assert response.status_code == 403


def test_post_safe_mode_decrypts_and_encrypts_reply(monkeypatch):
    token = "local-test-token"
    timestamp = "1700000001"
    nonce = "abc123"
    app_id = "wx1234567890"
    aes_key = base64.b64encode(bytes(range(32))).decode("ascii").rstrip("=")
    monkeypatch.setenv("WECHAT_TOKEN", token)
    monkeypatch.setenv("WECHAT_ENCODING_AES_KEY", aes_key)
    monkeypatch.setenv("WECHAT_APP_ID", app_id)
    encrypted = encrypt_message(
        _message_xml(),
        encoding_aes_key=aes_key,
        app_id=app_id,
        random_bytes=b"0123456789abcdef",
    )
    outer = f"<xml><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>"
    request_signature = build_message_signature(token, timestamp, nonce, encrypted)

    response = client.post(
        "/wechat/callback",
        params={
            "encrypt_type": "aes",
            "msg_signature": request_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        content=outer,
        headers={"content-type": "application/xml"},
    )

    assert response.status_code == 200
    response_outer = ET.fromstring(response.content)
    response_encrypted = response_outer.findtext("Encrypt", "")
    assert verify_message_signature(
        token=token,
        timestamp=response_outer.findtext("TimeStamp", ""),
        nonce=response_outer.findtext("Nonce", ""),
        encrypted=response_encrypted,
        signature=response_outer.findtext("MsgSignature", ""),
    )
    reply = ET.fromstring(
        decrypt_message(response_encrypted, encoding_aes_key=aes_key, app_id=app_id)
    )
    assert reply.findtext("ToUserName") == "user-open-id"
    assert reply.findtext("FromUserName") == "official-account"
    assert reply.findtext("Content") == "请发送淘宝商品链接"


def test_post_safe_mode_rejects_wrong_app_id(monkeypatch):
    token = "local-test-token"
    timestamp = "1700000001"
    nonce = "abc123"
    aes_key = base64.b64encode(bytes(range(32))).decode("ascii").rstrip("=")
    encrypted = encrypt_message(
        _message_xml(),
        encoding_aes_key=aes_key,
        app_id="wx-right",
        random_bytes=b"0123456789abcdef",
    )
    monkeypatch.setenv("WECHAT_TOKEN", token)
    monkeypatch.setenv("WECHAT_ENCODING_AES_KEY", aes_key)
    monkeypatch.setenv("WECHAT_APP_ID", "wx-wrong")

    response = client.post(
        "/wechat/callback",
        params={
            "encrypt_type": "aes",
            "msg_signature": build_message_signature(token, timestamp, nonce, encrypted),
            "timestamp": timestamp,
            "nonce": nonce,
        },
        content=f"<xml><Encrypt>{encrypted}</Encrypt></xml>",
    )

    assert response.status_code == 403


def test_post_rejects_dtd(monkeypatch):
    response = _post_plaintext(
        monkeypatch,
        '<!DOCTYPE xml [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><xml></xml>',
    )

    assert response.status_code == 400


def test_health_endpoint_is_available():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.text == "ok"
