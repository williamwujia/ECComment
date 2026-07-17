from __future__ import annotations

SHORT_POSITIVE_KEYWORDS = [
    "很好",
    "不错",
    "满意",
    "挺好",
    "可以",
    "好评",
    "质量不错",
    "孩子喜欢",
    "挺满意",
    "蛮好",
]

SERVICE_KEYWORDS = ["客服", "发货", "物流", "售后", "安装师傅", "服务"]
SERVICE_POSITIVE_KEYWORDS = ["耐心", "负责", "快", "及时", "专业", "态度好"]

MIXED_MARKERS = [
    "但是",
    "不过",
    "就是",
    "唯一",
    "只是",
    "可惜",
    "有点",
    "稍微",
    "如果",
    "虽然",
]

NEGATIVE_KEYWORDS = [
    "不好",
    "失望",
    "后悔",
    "退货",
    "换货",
    "坏了",
    "不亮",
    "刺眼",
    "眩光",
    "反光",
    "太暗",
    "太贵",
    "不值",
    "质量差",
    "做工差",
    "客服差",
    "安装麻烦",
]


def try_rule_sentiment(comment: dict) -> dict | None:
    text = _text(comment)
    compact = "".join(text.split())
    if not compact:
        return None
    if _has_any(compact, MIXED_MARKERS) or _has_any(compact, NEGATIVE_KEYWORDS):
        return None
    if _has_any(compact, SERVICE_KEYWORDS) and _has_any(compact, SERVICE_POSITIVE_KEYWORDS):
        return _result(comment, "P", 8, "V", "-", 3, "rule")
    if len(compact) <= 12 and _has_any(compact, SHORT_POSITIVE_KEYWORDS):
        return _result(comment, "P", 7, "-", "-", 2, "rule")
    return None


def _result(comment: dict, label: str, score: int, praise: str, complaint: str, confidence: int, source: str) -> dict:
    content_id = comment.get("content_id") or comment.get("content_hash") or ""
    return {
        "i": content_id,
        "s": label,
        "sc": score,
        "p": praise,
        "n": complaint,
        "c": confidence,
        "source": source,
    }


def _text(comment: dict) -> str:
    return str(comment.get("content_text_clean") or comment.get("review_text_clean") or "")


def _has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)
