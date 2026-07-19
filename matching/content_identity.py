from __future__ import annotations

import hashlib
import re
from typing import Any


def _normalize(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _digest(*parts: Any) -> str:
    payload = "\x1f".join(_normalize(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_identity_keys(content: dict, item_key: str) -> dict:
    native_id = _normalize(content.get("platform_content_id"))
    role = _normalize(content.get("content_role"))
    text = _normalize(content.get("content_text_clean"))
    parent = _normalize(content.get("parent_text_clean"))
    user = _normalize(content.get("user_name_masked"))
    content_time = _normalize(content.get("content_time") or content.get("review_time"))
    sku = _normalize(content.get("sku"))

    strict_key = f"native:{item_key}:{role}:{native_id}" if native_id else ""
    composite_key = "composite:" + _digest(
        item_key, role, text, parent, user, content_time, sku
    )
    text_key = "text:" + _digest(item_key, role, text, parent)
    has_auxiliary = bool(user or content_time or sku or parent)
    if strict_key:
        identity_key = strict_key
        method = "native_id"
        confidence = "high"
    elif has_auxiliary:
        identity_key = composite_key
        method = "composite"
        confidence = "high" if sum(bool(value) for value in (user, content_time, sku)) >= 2 else "medium"
    else:
        identity_key = text_key
        method = "low_confidence"
        confidence = "low"
    return {
        "strict_key": strict_key,
        "composite_key": composite_key,
        "text_key": text_key,
        "identity_key": identity_key,
        "identity_method": method,
        "identity_confidence": confidence,
    }


def match_pair(left: dict, right: dict) -> tuple[bool, bool, str]:
    if left.get("strict_key") and left.get("strict_key") == right.get("strict_key"):
        return True, True, "native_id"
    if left.get("composite_key") and left.get("composite_key") == right.get("composite_key"):
        return True, True, "composite"
    if left.get("text_key") != right.get("text_key"):
        return False, False, ""
    auxiliary_fields = ("user_name_masked", "content_time", "sku")
    comparable = [
        field
        for field in auxiliary_fields
        if str(left.get(field) or "").strip() and str(right.get(field) or "").strip()
    ]
    if comparable and all(
        _normalize(left.get(field)) == _normalize(right.get(field)) for field in comparable
    ):
        return True, False, "text_with_auxiliary"
    return False, False, ""
