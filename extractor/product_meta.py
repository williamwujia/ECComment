from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from utils.text_cleaner import clean_text


TITLE_NOISE_TERMS = (
    "距结束",
    "距离结束",
    "离结束",
    "商品评价",
    "商品",
    "问大家",
    "买家评价",
    "大家评",
    "店铺",
    "客服",
    "推荐",
    "按图片搜索",
    "优惠前",
    "优惠后",
    "店铺优惠",
    "参数",
    "参数信息",
    "图文详情",
    "本店推荐",
    "看了又看",
)

TITLE_SUFFIX_RE = re.compile(
    r"\s*(?:[-_—|｜]\s*)?(?:淘宝网|天猫|京东|商品详情|价格|报价|评价)\s*$",
    re.IGNORECASE,
)
SINGLEFILE_TIMESTAMP_RE = re.compile(
    r"\s*\(\d{4}[-_]\d{1,2}[-_]\d{1,2}\s+\d{1,2}：\d{1,2}：\d{1,2}\)\s*$"
)
FILENAME_SUFFIX_RE = re.compile(
    r"\s*[-_—|｜]\s*(?:tmall\.com天猫|taobao\.com淘宝|淘宝网|天猫|京东|jd\.com)\s*$",
    re.IGNORECASE,
)


def _meta_content(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        )
        if tag and tag.get("content"):
            return clean_text(tag["content"])
    return ""


def _json_ld_products(soup: BeautifulSoup) -> list[dict]:
    products: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        nodes = payload if isinstance(payload, list) else [payload]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph", [])
            candidates = [node] + (graph if isinstance(graph, list) else [])
            products.extend(
                item
                for item in candidates
                if isinstance(item, dict)
                and str(item.get("@type", "")).casefold() == "product"
            )
    return products


def _clean_title_candidate(text: str) -> str:
    title = clean_text(text)
    while True:
        cleaned = TITLE_SUFFIX_RE.sub("", title).strip()
        if cleaned == title:
            break
        title = cleaned
    return title


def _is_product_title_candidate(text: str) -> bool:
    raw_title = clean_text(text)
    if raw_title in TITLE_NOISE_TERMS:
        return False
    title = _clean_title_candidate(text)
    if len(title) < 2:
        return False
    if any(term in title for term in TITLE_NOISE_TERMS):
        return False
    if re.fullmatch(r"用户评价\s*[·\-\s]*\d+\+?", title):
        return False
    return True


def _first_valid_title(texts: list[str]) -> str:
    for text in texts:
        if _is_product_title_candidate(text):
            return _clean_title_candidate(text)
    return ""


def _title_from_source_file(source_file: str) -> str:
    name = Path(source_file).name
    for suffix in (".u.zip.html", ".zip.html", ".html", ".htm"):
        if name.casefold().endswith(suffix):
            name = name[: -len(suffix)]
            break
    name = SINGLEFILE_TIMESTAMP_RE.sub("", name)
    name = FILENAME_SUFFIX_RE.sub("", name)
    title = _clean_title_candidate(name)
    return title if _is_product_title_candidate(title) else ""


def extract_product_title(
    soup: BeautifulSoup, platform: str, source_file: str = ""
) -> str:
    """Return the page's actual product title, falling back to page title last."""
    if platform in {"taobao", "tmall"}:
        sku_panel_texts = []
        for selector in (
            "#tbpcDetail_SkuPanelBody > div:nth-of-type(1) "
            "> div > div > div:nth-of-type(1) > span",
            "#tbpcDetail_SkuPanelBody > div:nth-of-type(2) "
            "> div > div > div:nth-of-type(1) > span",
        ):
            sku_panel_title = soup.select_one(selector)
            if sku_panel_title:
                sku_panel_texts.extend(
                    [
                        sku_panel_title.get("title", ""),
                        sku_panel_title.get_text(" ", strip=True),
                    ]
                )
        title = _first_valid_title(sku_panel_texts)
        if title:
            return title

    specific_selector_candidates = (
        "[class*='product-title']",
        "[class*='ProductTitle']",
        "[class*='item-title']",
        "[class*='ItemTitle']",
        "[class*='tb-main-title']",
    )
    texts: list[str] = []
    for selector in specific_selector_candidates:
        for node in soup.select(selector):
            texts.append(node.get_text(" ", strip=True))
    title = _first_valid_title(texts)
    if title:
        return title

    products = _json_ld_products(soup)
    json_title = _first_valid_title(
        [str(product.get("name", "")) for product in products]
    )
    if json_title:
        return json_title

    meta_title = _first_valid_title(
        [_meta_content(soup, "og:title", "twitter:title")]
    )
    if meta_title:
        return meta_title

    page_title = _clean_title_candidate(
        soup.title.get_text(" ", strip=True) if soup.title else ""
    )
    if _is_product_title_candidate(page_title):
        return page_title

    file_title = _title_from_source_file(source_file)
    if file_title:
        return file_title

    generic_selector_candidates = (
        "h1",
        "[class*='title']",
        "[class*='Title']",
    )
    generic_texts: list[str] = []
    for selector in generic_selector_candidates:
        for node in soup.select(selector):
            generic_texts.append(node.get_text(" ", strip=True))
    title = _first_valid_title(generic_texts)
    if title:
        return title

    return ""


def _find_product_url(html_text: str, soup: BeautifulSoup) -> str:
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical and canonical.get("href"):
        return canonical["href"].strip()

    url = _meta_content(soup, "og:url")
    if url:
        return url

    match = re.search(
        r"https?://[^\s\"'<>]+(?:item\.taobao|detail\.tmall|item\.jd|yangkeduo|haohuo\.jinritemai)[^\s\"'<>]*",
        html_text,
        re.IGNORECASE,
    )
    return match.group(0) if match else ""


def _product_id(product_url: str, html_text: str) -> str:
    if product_url:
        query = parse_qs(urlparse(product_url).query)
        for key in ("id", "itemId", "item_id", "goods_id", "goodsId"):
            if query.get(key):
                return query[key][0]

    for pattern in (
        r'(?:"itemId"|"item_id"|"goodsId"|"goods_id")\s*[:=]\s*["\']?(\d{5,})',
        r"(?:itemId|item_id|goodsId|goods_id)%22?%3A%22?(\d{5,})",
    ):
        match = re.search(pattern, html_text, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def extract_product_meta(
    html_text: str, soup: BeautifulSoup, source_file: str, platform: str
) -> dict:
    """Extract product metadata without making extraction depend on it."""
    page_title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    products = _json_ld_products(soup)
    product = products[0] if products else {}

    product_title = extract_product_title(soup, platform, source_file)

    brand = product.get("brand", {})
    if isinstance(brand, dict):
        brand = brand.get("name", "")
    shop_name = clean_text(
        product.get("seller", {}).get("name", "")
        if isinstance(product.get("seller"), dict)
        else ""
    )
    if not shop_name:
        for selector in (
            "[class*='shop-name']",
            "[class*='shopName']",
            "[class*='ShopName']",
            "[class*='seller-name']",
        ):
            node = soup.select_one(selector)
            if node:
                shop_name = clean_text(node.get_text(" ", strip=True))
                if shop_name:
                    break
    if not shop_name and isinstance(brand, str):
        shop_name = clean_text(brand)

    product_url = _find_product_url(html_text, soup)
    return {
        "source_file": str(Path(source_file).resolve()),
        "platform": platform,
        "product_title": product_title,
        "shop_name": shop_name,
        "product_url": product_url,
        "product_id": _product_id(product_url, html_text),
        "page_title": page_title,
    }
