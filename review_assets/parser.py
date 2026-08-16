from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote_to_bytes

from bs4 import BeautifulSoup, Tag

from extractor.html_loader import _decode_html
from extractor.platform_detect import detect_platform
from extractor.product_meta import extract_product_meta
from extractor.reviews import _first_text, extract_review_date
from review_assets.models import ParsedFile, ParsedImage, ParsedReview
from utils.text_cleaner import clean_text


DATA_URI_RE = re.compile(
    r"^data:(image/[a-z0-9.+-]+)(?:;[^,]*)?,(.*)$", re.IGNORECASE | re.DOTALL
)
BACKGROUND_DATA_RE = re.compile(r"url\([\"']?(data:image/[^)\"']+)[\"']?\)", re.IGNORECASE)
ID_ATTRS = (
    "data-comment-id", "data-review-id", "data-rate-id", "commentid",
    "comment-id", "rateid", "rate-id", "reviewid", "review-id",
)
IMAGE_SOURCE_ATTRS = ("src", "data-src", "data-original", "data-lazy-src")
NOISE_IMAGE_RE = re.compile(
    r"avatar|head|user.*(?:pic|image)|icon|logo|sprite|emoji|badge|shop|seller|"
    r"recommend|product|goods|detail|banner|advert|qrcode|vip|credit|medal|member|level|"
    r"二维码|头像|主图|商品图",
    re.IGNORECASE,
)
APPEND_RE = re.compile(r"append|followup|additional|追加|追评", re.IGNORECASE)
CARD_RE = re.compile(
    r"(?:^|\s)Comment--[A-Za-z0-9_]|"
    r"(?:review|comment|rate|feedback|evaluation).{0,12}(?:item|card)|"
    r"(?:item|card).{0,12}(?:review|comment|rate|feedback|evaluation)|"
    r"_listItem_|评价项|评论项",
    re.IGNORECASE,
)


def _read_singlefile_html(raw: bytes) -> str:
    buffer = io.BytesIO(raw)
    if zipfile.is_zipfile(buffer):
        with zipfile.ZipFile(buffer) as archive:
            if any(info.flag_bits & 0x1 for info in archive.infolist()):
                raise ValueError("不接受加密压缩 HTML")
            entry = next(
                (name for name in archive.namelist() if name.casefold() == "index.html"),
                next(
                    (name for name in archive.namelist() if name.casefold().endswith((".html", ".htm"))),
                    "",
                ),
            )
            if not entry:
                raise ValueError("压缩 SingleFile 中没有 HTML 入口")
            return _decode_html(archive.read(entry))
    return _decode_html(raw)


def _sha256(*values: str) -> str:
    payload = "\x1f".join(clean_text(value).casefold() for value in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decode_data_uri(value: str) -> tuple[str, bytes | None, str]:
    match = DATA_URI_RE.match(value.strip())
    if not match:
        return "", None, "图片未保存在 SingleFile 中"
    mime_type, payload = match.groups()
    try:
        if ";base64," in value[: value.find(",") + 1].casefold():
            return mime_type.casefold(), base64.b64decode(payload, validate=True), ""
        return mime_type.casefold(), unquote_to_bytes(payload), ""
    except (ValueError, binascii.Error):
        return mime_type.casefold(), None, "图片数据无法解码"


def _node_signature(node: Tag) -> str:
    values = [str(node.get("id", "")), " ".join(node.get("class", []))]
    for parent in list(node.parents)[:3]:
        if isinstance(parent, Tag):
            values.extend((str(parent.get("id", "")), " ".join(parent.get("class", []))))
    return " ".join(values)


def _candidate_review_cards(soup: BeautifulSoup) -> list[Tag]:
    candidates: list[Tag] = []
    for node in soup.find_all(("div", "li", "article", "section")):
        own_signature = f"{node.get('id', '')} {' '.join(node.get('class', []))}"
        if CARD_RE.search(own_signature):
            candidates.append(node)
    if not candidates:
        for selector in ("[data-comment-id]", "[data-review-id]", "[data-rate-id]"):
            candidates.extend(soup.select(selector))
    unique = list(dict.fromkeys(candidates))
    identities = {id(node) for node in unique}
    return [
        node for node in unique
        if not any(id(child) in identities for child in node.find_all(("div", "li", "article", "section")))
    ]


def _is_review_asset(node: Tag) -> bool:
    signature = _node_signature(node)
    if NOISE_IMAGE_RE.search(signature):
        return False
    alt = clean_text(str(node.get("alt", "")))
    if NOISE_IMAGE_RE.search(alt):
        return False
    try:
        width = int(re.sub(r"\D", "", str(node.get("width", ""))) or 0)
        height = int(re.sub(r"\D", "", str(node.get("height", ""))) or 0)
        if width and height and width <= 48 and height <= 48:
            return False
    except ValueError:
        pass
    return True


def _image_sources(card: Tag) -> list[tuple[Tag, str]]:
    found: list[tuple[Tag, str]] = []
    for node in card.find_all(True):
        if not _is_review_asset(node):
            continue
        if node.name in {"img", "source"}:
            values = [str(node.get(attr, "")).strip() for attr in IMAGE_SOURCE_ATTRS if node.get(attr)]
            value = next((item for item in values if item.casefold().startswith("data:image/")), values[0] if values else "")
            if value:
                found.append((node, value))
        for match in BACKGROUND_DATA_RE.finditer(str(node.get("style", ""))):
            found.append((node, match.group(1)))
    return found


def _platform_review_id(card: Tag) -> str:
    for node in (card, *card.find_all(True)):
        for attr in ID_ATTRS:
            value = str(node.get(attr, "")).strip()
            if value and re.fullmatch(r"[A-Za-z0-9_-]{4,128}", value):
                return value
    text = str(card)[:10000]
    match = re.search(r'["\'](?:commentId|rateId|reviewId)["\']\s*[:=]\s*["\']?([A-Za-z0-9_-]{4,128})', text)
    return match.group(1) if match else ""


def _parse_card(card: Tag, platform: str, product_id: str) -> ParsedReview | None:
    raw_block = clean_text(card.get_text("\n", strip=True))
    review_text = _first_text(card, (
        r"^content--", r"(review|comment|rate|feedback).*(content|text|body)",
        r"(content|text).*(review|comment|rate|feedback)", r"(评价|评论).*(内容|正文)",
    ))
    append_text = _first_text(card, (r"(append|followup|additional).*(content|text)?", r"追评"))
    meta_text = _first_text(card, (r"^meta--", r"(review|comment|rate).*(meta|info)"))
    sku = _first_text(card, (r"(sku|variant|spec|property)", r"(规格|型号|款式)"))
    reviewer = _first_text(card, (r"(user|buyer|member).*(name|nick)", r"(用户名|昵称)"))
    if not review_text:
        lines = [clean_text(line) for line in raw_block.splitlines() if len(clean_text(line)) >= 2]
        lines = [line for line in lines if line != append_text and not APPEND_RE.fullmatch(line)]
        review_text = max(lines, key=len, default="")
    review_text = clean_text(review_text)
    append_text = clean_text(append_text)
    if len(review_text) < 2:
        return None
    review_time, _ = extract_review_date(meta_text or raw_block)
    append_time = ""
    for node in card.find_all(True):
        if APPEND_RE.search(_node_signature(node)):
            append_time, _ = extract_review_date(clean_text(node.get_text(" ", strip=True)))
            if append_time:
                break
    fingerprint = _sha256(platform, product_id, reviewer, review_time, sku, review_text)
    images: list[ParsedImage] = []
    indexes = {"review": 0, "append": 0}
    seen_sources: set[tuple[str, str]] = set()
    for node, source in _image_sources(card):
        stage = "append" if APPEND_RE.search(_node_signature(node)) else "review"
        mime_type, data, warning = _decode_data_uri(source)
        identity = hashlib.sha256(data).hexdigest() if data else _sha256(source)
        if (stage, identity) in seen_sources:
            continue
        seen_sources.add((stage, identity))
        indexes[stage] += 1
        images.append(ParsedImage(
            stage=stage,
            index=indexes[stage],
            source_ref=source[:512] if not source.startswith("data:") else "embedded:data-uri",
            mime_type=mime_type,
            data=data,
            extract_status="extracted" if data else "missing",
            content_sha256=identity,
            warning=warning,
        ))
    return ParsedReview(
        platform_review_id=_platform_review_id(card),
        reviewer_display_name=reviewer,
        sku=sku,
        review_time=review_time,
        append_time=append_time,
        review_text=review_text,
        append_text=append_text,
        review_fingerprint=fingerprint,
        images=images,
    )


def parse_singlefile(raw: bytes, file_name: str) -> ParsedFile:
    source_sha256 = hashlib.sha256(raw).hexdigest()
    html_text = _read_singlefile_html(raw)
    soup = BeautifulSoup(html_text, "html.parser")
    platform = detect_platform(html_text, file_name)
    meta = extract_product_meta(html_text, soup, file_name, platform)
    product_id = clean_text(str(meta.get("product_id", "")))
    parsed = ParsedFile(
        source_file_name=Path(file_name).name,
        source_file_sha256=source_sha256,
        platform=platform if platform in {"taobao", "tmall", "jd"} else "unknown",
        product_id=product_id,
        product_title=clean_text(str(meta.get("product_title", ""))),
    )
    cards = _candidate_review_cards(soup)
    for card in cards:
        review = _parse_card(card, parsed.platform, product_id)
        if review:
            parsed.reviews.append(review)
            parsed.warnings.extend(image.warning for image in review.images if image.warning)
    if not parsed.reviews:
        parsed.errors.append("评论区完全无法解析，文件未入库")
    if parsed.platform == "unknown":
        parsed.errors.append("平台无法自动识别，请在预览中修正")
    if not product_id:
        parsed.errors.append("商品 ID 无法自动识别，请在预览中修正")
    return parsed
