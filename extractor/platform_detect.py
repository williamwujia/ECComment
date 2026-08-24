from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse


PLATFORM_SIGNALS = {
    "tmall": ("tmall.com", "天猫", "天猫超市", "天猫国际"),
    "taobao": ("taobao.com", "淘宝", "已买到的宝贝", "收藏夹"),
    "jd": ("jd.com", "京东", "京东商城"),
    "pdd": ("pinduoduo.com", "yangkeduo.com", "拼多多"),
    "douyin": ("douyin.com", "抖音商城", "抖音电商"),
}

SINGLEFILE_URL_RE = re.compile(
    r"Page saved with SingleFile\s+url:\s*(https?://[^\s<]+)",
    re.IGNORECASE,
)


def _platform_from_saved_url(html_text: str) -> str:
    match = SINGLEFILE_URL_RE.search(html_text[:20_000])
    if not match:
        return ""
    host = (urlparse(match.group(1)).hostname or "").casefold()
    if host == "tmall.com" or host.endswith(".tmall.com"):
        return "tmall"
    if host == "taobao.com" or host.endswith(".taobao.com"):
        return "taobao"
    if host == "jd.com" or host.endswith(".jd.com"):
        return "jd"
    return ""


def detect_platform(html_text: str, file_path: str) -> str:
    """Detect an ecommerce platform from page content and filename."""
    saved_platform = _platform_from_saved_url(html_text)
    if saved_platform:
        return saved_platform
    sample = f"{Path(file_path).name}\n{html_text[:1_000_000]}".casefold()

    if "问大家".casefold() in sample:
        if any(signal.casefold() in sample for signal in PLATFORM_SIGNALS["tmall"]):
            return "tmall"
        return "taobao"

    scores = {
        platform: sum(signal.casefold() in sample for signal in signals)
        for platform, signals in PLATFORM_SIGNALS.items()
    }
    platform, score = max(scores.items(), key=lambda item: item[1])
    return platform if score else "unknown"
