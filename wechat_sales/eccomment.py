"""Small HTTP adapter for the ECComment estimate endpoint."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import httpx


class ECCommentError(RuntimeError):
    """Raised when ECComment cannot provide a usable result."""


def _required_text(result: Mapping[str, Any], field: str) -> str:
    value = result.get(field)
    if value is None or not str(value).strip():
        raise ECCommentError(f"ECComment result is missing {field}")
    return str(value).strip()


def _non_negative_int(result: Mapping[str, Any], field: str) -> int:
    value = result.get(field)
    if isinstance(value, bool):
        raise ECCommentError(f"ECComment result has invalid {field}")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ECCommentError(f"ECComment result has invalid {field}") from exc
    if number < 0:
        raise ECCommentError(f"ECComment result has invalid {field}")
    return number


def _percentage(value: Any, field: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ECCommentError(f"ECComment result has invalid {field}") from exc
    if not 0 <= number <= 100:
        raise ECCommentError(f"ECComment result has invalid {field}")
    return f"{number:g}%"


async def query_eccomment(query: str, *, request_id: str) -> Mapping[str, Any]:
    """Submit one original WeChat text message to ECComment."""

    url = os.getenv("ECCOMMENT_ESTIMATE_URL", "").strip()
    if not url:
        raise ECCommentError("ECCOMMENT_ESTIMATE_URL is not configured")

    headers = {"Accept": "application/json"}
    token = os.getenv("ECCOMMENT_ESTIMATE_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        timeout = float(os.getenv("ECCOMMENT_TIMEOUT_SECONDS", "4"))
    except ValueError as exc:
        raise ECCommentError("ECCOMMENT_TIMEOUT_SECONDS is invalid") from exc
    if timeout <= 0:
        raise ECCommentError("ECCOMMENT_TIMEOUT_SECONDS is invalid")

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json={"query": query, "source": "wechat", "request_id": request_id},
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ECCommentError("ECComment request failed") from exc

    if not isinstance(result, Mapping) or result.get("status") != "ok":
        raise ECCommentError("ECComment returned an unavailable result")
    return result


def format_wechat_result(result: Mapping[str, Any]) -> str:
    """Turn a validated ECComment result into a compact WeChat text reply."""

    product_name = _required_text(result, "product_name")
    platform = _required_text(result, "platform")
    period = _required_text(result, "period")
    data_date = _required_text(result, "data_date")
    estimated_sales = _non_negative_int(result, "estimated_sales")
    review_count = _non_negative_int(result, "review_count")

    try:
        review_rate = float(result.get("review_rate"))
    except (TypeError, ValueError) as exc:
        raise ECCommentError("ECComment result has invalid review_rate") from exc
    if not 0 < review_rate <= 1:
        raise ECCommentError("ECComment result has invalid review_rate")

    coverage = _percentage(result.get("date_coverage"), "date_coverage")
    platform_label = {"taobao": "淘宝", "tmall": "天猫"}.get(
        platform.lower(), platform
    )
    return "\n".join(
        (
            f"商品：{product_name}",
            f"平台：{platform_label}",
            f"估算销量：约 {estimated_sales:,} 单",
            f"统计周期：{period}",
            f"评论样本：{review_count:,} 条",
            f"数据截至：{data_date}",
            f"评论率假设：{review_rate * 100:g}%",
            f"评论日期覆盖率：{coverage}",
            "仅供市场判断参考，不代表平台真实订单。",
        )
    )
