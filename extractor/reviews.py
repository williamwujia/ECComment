from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from extractor.generic_blocks import prune_nested, semantic_candidates
from utils.dedupe import md5_text
from utils.text_cleaner import clean_text


REVIEW_CARD_HINT = r"(review|comment|rate-item|feedback|evaluation|评价|评论)"
NOISE_RE = re.compile(
    r"^(?:商品评价|累计评价|全部评价|有图|好评|中评|差评|默认好评|"
    r"该用户未填写评价内容|\d+)$"
)
REVIEW_DATE_RE = re.compile(
    r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?"
)


def extract_review_date(text: str) -> tuple[str, str]:
    """Return the displayed date and a normalized YYYY-MM-DD value."""
    match = REVIEW_DATE_RE.search(text or "")
    if not match:
        return "", ""
    raw_value = match.group(0)
    try:
        normalized = date(*(int(value) for value in match.groups())).isoformat()
    except ValueError:
        return raw_value, ""
    return raw_value, normalized


def _first_text(card: Tag, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        regex = re.compile(pattern, re.IGNORECASE)
        for node in card.find_all(True):
            attrs = " ".join(node.get("class", [])) + " " + str(node.get("id", ""))
            if regex.search(attrs):
                value = clean_text(node.get_text(" ", strip=True))
                if value:
                    return value
    return ""


def _candidate_cards(soup: BeautifulSoup) -> list[Tag]:
    cards: list[Tag] = []
    for selector in (
        "[class*='Comment--']",
        "[class*='review-item']",
        "[class*='ReviewItem']",
        "[class*='comment-item']",
        "[class*='CommentItem']",
        "[class*='rate-item']",
        "[class*='evaluation-item']",
    ):
        cards.extend(soup.select(selector))
    cards.extend(semantic_candidates(soup, REVIEW_CARD_HINT))
    return prune_nested(list(dict.fromkeys(cards)))


def parse_reviews(html_text: str, soup: BeautifulSoup, meta: dict) -> list[dict]:
    """Extract consumer reviews using semantic selectors and safe fallbacks."""
    reviews: list[dict] = []
    seen: set[str] = set()

    for card in _candidate_cards(soup):
        raw_block = clean_text(card.get_text("\n", strip=True))
        if len(raw_block) < 4 or len(raw_block) > 5000:
            continue

        review_text = _first_text(
            card,
            (
                r"^content--",
                r"(review|comment|rate|feedback).*(content|text|body)",
                r"(content|text).*(review|comment|rate|feedback)",
                r"(评价|评论).*(内容|正文)",
            ),
        )
        merchant_reply = _first_text(card, (r"(seller|merchant|shop).*(reply|response)", r"商家.*回复"))
        followup_text = _first_text(card, (r"(append|followup|additional)", r"追评"))
        meta_text = _first_text(card, (r"^meta--",))
        sku = _first_text(card, (r"(sku|variant|spec|property)", r"(规格|型号|款式)"))
        if not sku and "已购：" in meta_text:
            sku = clean_text(meta_text.split("已购：", 1)[1])
        user_name = _first_text(
            card, (r"(user|buyer|member).*(name|nick)", r"(用户名|昵称)")
        )
        if not user_name:
            user_info = card.select_one("[class*='userInfo--']")
            if user_info:
                first_span = user_info.find("span")
                user_name = clean_text(
                    first_span.get_text(" ", strip=True) if first_span else ""
                )

        if not review_text:
            lines = [
                clean_text(line)
                for line in raw_block.splitlines()
                if clean_text(line) and not NOISE_RE.fullmatch(clean_text(line))
            ]
            review_text = max(lines, key=len, default="")

        review_text = clean_text(review_text)
        if (
            len(review_text) < 2
            or NOISE_RE.fullmatch(review_text)
            or review_text in {merchant_reply, followup_text}
        ):
            continue

        review_time, review_date = extract_review_date(meta_text or raw_block)
        rating_match = re.search(r"([1-5](?:\.\d)?)\s*(?:分|星)", raw_block)
        image_count = len(card.find_all("img"))
        video_count = len(card.find_all("video"))
        like_match = re.search(r"(?:有用|点赞|赞)\s*(\d+)", raw_block)
        digest = md5_text(
            meta.get("platform"),
            meta.get("product_id"),
            review_text,
            review_time,
            sku,
        )
        if digest in seen:
            continue
        seen.add(digest)

        base = {key: meta.get(key, "") for key in (
            "source_file", "platform", "product_title", "shop_name",
            "product_url", "product_id",
        )}
        reviews.append(
            {
                **base,
                "review_order": len(reviews) + 1,
                "review_text_raw": review_text,
                "review_text_clean": review_text,
                "review_time": review_time,
                "review_date": review_date,
                "rating": rating_match.group(1) if rating_match else "",
                "sku": sku,
                "user_name_masked": user_name,
                "is_followup": bool(followup_text),
                "followup_text": followup_text,
                "merchant_reply": merchant_reply,
                "image_count": image_count,
                "video_count": video_count,
                "like_count": int(like_match.group(1)) if like_match else "",
                "review_hash": digest,
                "extract_confidence": 0.9 if review_text != raw_block else 0.6,
            }
        )
    return reviews
