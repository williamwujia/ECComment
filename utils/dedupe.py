from __future__ import annotations

import hashlib
from collections.abc import Iterable


def md5_text(*parts: object) -> str:
    value = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def content_hash(record: dict) -> str:
    identity = record.get("product_id") or record.get("source_file", "")
    return md5_text(
        record.get("platform", ""),
        identity,
        record.get("content_role", ""),
        record.get("content_text_clean", ""),
        record.get("parent_text_clean", ""),
    )


def dedupe_records(records: Iterable[dict]) -> list[dict]:
    """Keep the first record for each content hash."""
    result: list[dict] = []
    seen: set[str] = set()
    for record in records:
        item = dict(record)
        digest = item.get("content_hash") or content_hash(item)
        item["content_hash"] = digest
        if digest in seen:
            continue
        seen.add(digest)
        result.append(item)
    return result

