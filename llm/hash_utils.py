from __future__ import annotations

import hashlib


def build_input_hash(comment: dict, prompt_version: str) -> str:
    raw = "|".join(
        [
            str(comment.get("content_hash") or comment.get("review_hash") or comment.get("content_id") or ""),
            str(comment.get("product_title") or ""),
            str(comment.get("sku") or ""),
            str(comment.get("content_text_clean") or comment.get("review_text_clean") or ""),
            str(prompt_version or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

