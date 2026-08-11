from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from security.upload_limits import PUBLIC_UPLOAD_LIMITS, UploadLimitError


REQUIRED_COLUMNS = {"platform", "product_id", "review_text_raw"}
INVALID_PRODUCT_TITLES = {"最小单价计算器"}


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def read_review_csv(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if source.stat().st_size > PUBLIC_UPLOAD_LIMITS.max_file_bytes:
        raise UploadLimitError(
            f"{source.name} 超过单文件 "
            f"{PUBLIC_UPLOAD_LIMITS.max_file_bytes // (1024 * 1024)} MB 限制。"
        )
    try:
        frame = pd.read_csv(source, encoding="utf-8-sig", dtype=str).fillna("")
    except UnicodeDecodeError:
        frame = pd.read_csv(source, encoding="gb18030", dtype=str).fillna("")
    frame.columns = [str(column).strip() for column in frame.columns]
    if len(frame) > PUBLIC_UPLOAD_LIMITS.max_csv_rows:
        raise UploadLimitError(
            f"{source.name} 超过 {PUBLIC_UPLOAD_LIMITS.max_csv_rows:,} 行限制。"
        )
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"评论 CSV 缺少必要列：{', '.join(missing)}")
    frame["platform"] = frame["platform"].astype(str).str.strip().str.casefold()
    frame["product_id"] = frame["product_id"].astype(str).str.strip()
    frame["review_text_raw"] = frame["review_text_raw"].astype(str).str.strip()
    frame = frame[
        frame["platform"].ne("")
        & frame["product_id"].ne("")
        & frame["review_text_raw"].ne("")
    ].copy()
    if frame.empty:
        raise ValueError("评论 CSV 中没有有效评论")
    return frame


def split_review_csv(path: str | Path, output_dir: str | Path) -> list[Path]:
    source = Path(path)
    frame = read_review_csv(source)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, ((platform, product_id), group) in enumerate(
        frame.groupby(["platform", "product_id"], sort=False), 1
    ):
        safe_platform = "".join(ch for ch in platform if ch.isalnum() or ch in "_-") or "unknown"
        safe_id = "".join(ch for ch in product_id if ch.isalnum() or ch in "_-")
        target = output / f"{source.stem}__{index}_{safe_platform}_{safe_id}.csv"
        group.to_csv(target, index=False, encoding="utf-8-sig")
        paths.append(target)
    return paths


def extract_csv_identity(path: str | Path) -> dict:
    source = Path(path).expanduser().resolve()
    raw = source.read_bytes()
    frame = read_review_csv(source)
    pairs = frame[["platform", "product_id"]].drop_duplicates()
    if len(pairs) != 1:
        raise ValueError("一个逻辑评论 CSV 必须只包含一个 platform + product_id")
    first = frame.iloc[0]
    return {
        "platform": _text(first.get("platform")),
        "product_id": _text(first.get("product_id")),
        "title": (
            ""
            if _text(first.get("product_title")) in INVALID_PRODUCT_TITLES
            else _text(first.get("product_title"))
        ),
        "shop": _text(first.get("shop_name")),
        "saved_url": _text(first.get("product_url")),
        "capture_time": datetime.fromtimestamp(source.stat().st_mtime)
        .replace(microsecond=0)
        .isoformat(sep=" "),
        "file_hash": hashlib.sha256(raw).hexdigest(),
        "source_file": source.name,
        "source_path": str(source),
    }


def extract_csv_contents(path: str | Path) -> list[dict]:
    frame = read_review_csv(path)
    rows: list[dict] = []
    for order, record in enumerate(frame.to_dict("records"), 1):
        raw_text = _text(record.get("review_text_raw"))
        clean_text = _text(record.get("review_text_clean")) or raw_text
        time_value = _text(record.get("review_time"))
        date_value = _text(record.get("review_date"))
        if not date_value and len(time_value) >= 10:
            candidate = time_value[:10].replace("/", "-").replace(".", "-")
            if candidate[:4].isdigit():
                date_value = candidate
        rows.append(
            {
                "content_role": "review",
                "platform_content_id": _text(record.get("platform_content_id")),
                "content_text_raw": raw_text,
                "content_text_clean": clean_text,
                "parent_text_clean": "",
                "user_name_masked": _text(record.get("user_name_masked")),
                "content_time": time_value,
                "content_date": date_value,
                "sku": _text(record.get("sku")),
                "content_order": order,
            }
        )
    return rows
