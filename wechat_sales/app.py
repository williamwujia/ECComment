"""Isolated HTTP entrypoint for WeChat callback traffic."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import time
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse, Response

from wechat_sales.crypto import (
    WeChatCryptoError,
    build_message_signature,
    decrypt_message,
    encrypt_message,
    verify_message_signature,
    verify_wechat_signature,
)
from wechat_sales.eccomment import ECCommentError, format_wechat_result, query_eccomment
from wechat_sales.estimate_service import EstimateUnavailable, configured_catalog


logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load workbook estimates before the first time-limited WeChat query."""

    try:
        await asyncio.to_thread(configured_catalog().refresh_if_needed)
    except EstimateUnavailable:
        logger.exception("ECComment estimate catalog could not be warmed")
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
MAX_CALLBACK_BYTES = 256 * 1024
TAOBAO_LINK_PATTERN = re.compile(
    r"(?<![A-Za-z0-9-])(?:e\.tb\.cn|item\.taobao\.com|detail\.tmall\.com)"
    r"(?=[:/?#\s]|$)",
    re.IGNORECASE,
)


def _authorized_eccomment_request(request: Request) -> bool:
    expected = os.getenv("ECCOMMENT_ESTIMATE_TOKEN", "").strip()
    authorization = request.headers.get("authorization", "")
    supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def _parse_xml(payload: bytes | str) -> ET.Element:
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("DTD and entities are not allowed")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError) as exc:
        raise ValueError("Invalid XML") from exc
    if root.tag != "xml":
        raise ValueError("Invalid XML root")
    return root


def _xml_text(root: ET.Element, name: str) -> str:
    value = root.findtext(name)
    return value if value is not None else ""


def _build_text_reply(*, to_user: str, from_user: str, content: str, now: int) -> str:
    root = ET.Element("xml")
    ET.SubElement(root, "ToUserName").text = to_user
    ET.SubElement(root, "FromUserName").text = from_user
    ET.SubElement(root, "CreateTime").text = str(now)
    ET.SubElement(root, "MsgType").text = "text"
    ET.SubElement(root, "Content").text = content
    return ET.tostring(root, encoding="unicode", short_empty_elements=False)


def _contains_taobao_link(content: str) -> bool:
    return bool(TAOBAO_LINK_PATTERN.search(content))


def _safe_log_value(value: str, limit: int = 2048) -> str:
    return "".join(char if char >= " " else " " for char in value)[:limit]


def _xml_response(content: str) -> Response:
    return Response(content=content, status_code=200, media_type="application/xml")


@app.get("/wechat/callback", response_class=PlainTextResponse)
async def verify_callback(
    signature: str = Query(""),
    timestamp: str = Query(""),
    nonce: str = Query(""),
    echostr: str = Query(""),
) -> PlainTextResponse:
    """Handle the URL-verification challenge from a WeChat official account."""

    token = os.getenv("WECHAT_TOKEN", "")
    if not echostr or not verify_wechat_signature(
        token=token,
        timestamp=timestamp,
        nonce=nonce,
        signature=signature,
    ):
        logger.warning("Rejected WeChat callback verification request")
        return PlainTextResponse("Forbidden", status_code=403)
    return PlainTextResponse(echostr, status_code=200)


@app.post("/wechat/callback")
async def receive_callback(
    request: Request,
    signature: str = Query(""),
    msg_signature: str = Query(""),
    timestamp: str = Query(""),
    nonce: str = Query(""),
    encrypt_type: str = Query(""),
) -> Response:
    """Reply synchronously to official-account text messages."""

    token = os.getenv("WECHAT_TOKEN", "")
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > MAX_CALLBACK_BYTES:
        return PlainTextResponse("Payload Too Large", status_code=413)
    body = await request.body()
    if len(body) > MAX_CALLBACK_BYTES:
        return PlainTextResponse("Payload Too Large", status_code=413)

    try:
        outer = _parse_xml(body)
    except ValueError:
        logger.warning("Rejected malformed WeChat callback XML")
        return PlainTextResponse("Bad Request", status_code=400)

    encrypted = _xml_text(outer, "Encrypt")
    safe_mode = encrypt_type.lower() == "aes" or bool(msg_signature or encrypted)
    if safe_mode:
        encoding_aes_key = os.getenv("WECHAT_ENCODING_AES_KEY", "")
        app_id = os.getenv("WECHAT_APP_ID", "")
        if not verify_message_signature(
            token=token,
            timestamp=timestamp,
            nonce=nonce,
            encrypted=encrypted,
            signature=msg_signature,
        ):
            logger.warning("Rejected WeChat encrypted callback signature")
            return PlainTextResponse("Forbidden", status_code=403)
        try:
            message_root = _parse_xml(
                decrypt_message(
                    encrypted,
                    encoding_aes_key=encoding_aes_key,
                    app_id=app_id,
                )
            )
        except (ValueError, WeChatCryptoError):
            logger.warning("Rejected invalid WeChat encrypted callback")
            return PlainTextResponse("Forbidden", status_code=403)
    else:
        if not verify_wechat_signature(
            token=token,
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
        ):
            logger.warning("Rejected WeChat plaintext callback signature")
            return PlainTextResponse("Forbidden", status_code=403)
        message_root = outer

    msg_type = _xml_text(message_root, "MsgType")
    from_user = _xml_text(message_root, "FromUserName")
    content = _xml_text(message_root, "Content")
    logger.info(
        "Received WeChat message MsgType=%s FromUserName=%s Content=%s",
        _safe_log_value(msg_type),
        _safe_log_value(from_user),
        _safe_log_value(content),
    )
    if msg_type != "text":
        return PlainTextResponse("success", status_code=200)

    to_user = _xml_text(message_root, "ToUserName")
    if not to_user or not from_user:
        return PlainTextResponse("Bad Request", status_code=400)
    if not _contains_taobao_link(content):
        reply_content = "请发送淘宝商品链接"
    else:
        request_id = _xml_text(message_root, "MsgId") or (
            f"wechat-{_xml_text(message_root, 'CreateTime')}-{secrets.token_hex(4)}"
        )
        try:
            result = await query_eccomment(content, request_id=request_id)
            reply_content = format_wechat_result(result)
        except ECCommentError:
            logger.exception(
                "ECComment query failed request_id=%s", _safe_log_value(request_id)
            )
            reply_content = "查询失败，请稍后重试"
    reply_xml = _build_text_reply(
        to_user=from_user,
        from_user=to_user,
        content=reply_content,
        now=int(time.time()),
    )
    if not safe_mode:
        return _xml_response(reply_xml)

    encrypted_reply = encrypt_message(
        reply_xml,
        encoding_aes_key=encoding_aes_key,
        app_id=app_id,
    )
    response_timestamp = str(int(time.time()))
    response_nonce = secrets.token_hex(8)
    response_root = ET.Element("xml")
    ET.SubElement(response_root, "Encrypt").text = encrypted_reply
    ET.SubElement(response_root, "MsgSignature").text = build_message_signature(
        token, response_timestamp, response_nonce, encrypted_reply
    )
    ET.SubElement(response_root, "TimeStamp").text = response_timestamp
    ET.SubElement(response_root, "Nonce").text = response_nonce
    return _xml_response(ET.tostring(response_root, encoding="unicode"))


@app.post("/api/sales/estimate", include_in_schema=False)
async def estimate_sales(request: Request) -> JSONResponse:
    """Serve the authenticated, read-only ECComment estimate contract."""

    if not _authorized_eccomment_request(request):
        return JSONResponse({"status": "error", "error": "unauthorized"}, status_code=401)
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"status": "error", "error": "invalid_request"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"status": "error", "error": "invalid_request"}, status_code=400)
    query = str(payload.get("query", "")).strip()
    source = str(payload.get("source", "")).strip()
    request_id = str(payload.get("request_id", "")).strip()
    if not query or len(query) > 4096 or source != "wechat" or not request_id:
        return JSONResponse({"status": "error", "error": "invalid_request"}, status_code=400)
    try:
        result = await configured_catalog().estimate(query)
    except EstimateUnavailable:
        logger.info("ECComment estimate unavailable request_id=%s", _safe_log_value(request_id))
        return JSONResponse({"status": "error", "error": "unavailable"})
    except Exception:
        logger.exception("ECComment estimate failed request_id=%s", _safe_log_value(request_id))
        return JSONResponse({"status": "error", "error": "internal_error"}, status_code=500)
    return JSONResponse(result)


@app.get("/health", response_class=PlainTextResponse, include_in_schema=False)
async def health() -> PlainTextResponse:
    """Expose a private health check for the reverse proxy and systemd checks."""

    return PlainTextResponse("ok", status_code=200)
