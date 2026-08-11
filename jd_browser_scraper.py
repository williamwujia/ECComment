from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urlparse

from utils.dedupe import md5_text


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "output" / "jd_scrapes"
DEFAULT_PROFILE_DIR = PROJECT_DIR / ".browser_profiles" / "jd"
JD_HOST_RE = re.compile(r"(^|\.)jd\.com$", re.IGNORECASE)


@dataclass(frozen=True)
class ScrapeTarget:
    url: str
    count: int


def product_id_from_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query = parse_qs(parsed.query)
    for key in ("sku", "skuId", "id", "wareId"):
        value = query.get(key)
        if value and str(value[0]).isdigit():
            return str(value[0])
    path_match = re.search(r"/(\d+)\.html$", parsed.path)
    if path_match:
        return path_match.group(1)
    return ""


def validate_target(url: str, count: int) -> ScrapeTarget:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not JD_HOST_RE.search(parsed.hostname):
        raise ValueError(f"不是有效的京东商品 URL：{url}")
    if not product_id_from_url(url):
        raise ValueError(f"URL 中未找到京东商品 ID：{url}")
    if count <= 0:
        raise ValueError("评论数量必须大于 0")
    return ScrapeTarget(url=url.strip(), count=count)


def parse_target_line(value: str, default_count: int | None = None) -> ScrapeTarget:
    parts = [part.strip() for part in re.split(r"[,\t]", value.strip())]
    url = parts[0] if parts else ""
    count = int(parts[1]) if len(parts) > 1 and parts[1] else default_count
    if count is None:
        raise ValueError("请在 URL 后填写评论数量，例如：https://item.jd.com/100.html,200")
    return validate_target(url, count)


def load_targets(path: Path, default_count: int | None = None) -> list[ScrapeTarget]:
    targets: list[ScrapeTarget] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            targets.append(parse_target_line(stripped, default_count))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{path} 第 {line_number} 行无效：{exc}") from exc
    if not targets:
        raise ValueError(f"{path} 中没有可抓取的 URL")
    return targets


def prompt_targets(default_count: int | None = None) -> list[ScrapeTarget]:
    print("请输入京东商品 URL 和评论数量，每行一件；直接回车结束。")
    print("示例：https://item.jd.com/100012043978.html,200")
    targets: list[ScrapeTarget] = []
    while True:
        line = input(f"商品 {len(targets) + 1}> ").strip()
        if not line:
            break
        try:
            targets.append(parse_target_line(line, default_count))
        except (ValueError, TypeError) as exc:
            print(f"输入无效：{exc}")
    if not targets:
        raise ValueError("未输入任何商品 URL")
    return targets


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_review(raw: dict[str, Any], target: ScrapeTarget, title: str, order: int) -> dict[str, Any] | None:
    text = _clean(raw.get("text"))
    if not text:
        return None
    time_value = _clean(raw.get("time"))
    date_match = re.search(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}", time_value)
    rating_raw = _clean(raw.get("rating"))
    rating_match = re.search(r"([1-5])", rating_raw)
    product_id = product_id_from_url(target.url)
    sku = _clean(raw.get("sku"))
    digest = md5_text("jd", product_id, text, time_value, sku, _clean(raw.get("user")))
    return {
        "source_file": f"jd_browser_{product_id}",
        "platform": "jd",
        "product_title": _clean(raw.get("product_name")) or title,
        "shop_name": "",
        "product_url": target.url,
        "product_id": product_id,
        "review_order": order,
        "review_text_raw": text,
        "review_text_clean": text,
        "review_time": time_value,
        "review_date": date_match.group(0).replace("/", "-").replace(".", "-") if date_match else "",
        "rating": rating_match.group(1) if rating_match else "",
        "sku": sku,
        "user_name_masked": _clean(raw.get("user")),
        "is_followup": False,
        "followup_text": "",
        "merchant_reply": "",
        "image_count": int(raw.get("image_count") or 0),
        "video_count": int(raw.get("video_count") or 0),
        "like_count": "",
        "review_hash": digest,
        "extract_confidence": 0.9,
    }


EXTRACT_REVIEWS_JS = r"""
() => {
  const clean = value => (value || '').replace(/\s+/g, ' ').trim();
  const textOf = (root, selectors) => {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      const value = clean(node && (node.innerText || node.textContent));
      if (value) return value;
    }
    return '';
  };
  const candidates = [...document.querySelectorAll([
    '#rateList [class*="_listItem_"]', '#rateList .jdc-pc-rate-card',
    '.comment-item', '[class*="comment-item"]', '[class*="CommentItem"]',
    '[class*="review-item"]', '[class*="ReviewItem"]', '[data-testid*="comment"]'
    , '.comment-root .list > .item', '.comment-list > .item'
  ].join(','))];
  return candidates.map(card => {
    const classText = [...card.querySelectorAll('[class]')].map(n => n.className).join(' ');
    const starClass = (classText.match(/(?:star|score)[-_]?(?:level)?[-_]?([1-5])/i) || [])[1] || '';
    const ariaRating = [...card.querySelectorAll('[aria-label], [title]')]
      .map(n => n.getAttribute('aria-label') || n.getAttribute('title') || '')
      .find(v => /[1-5]\s*(?:星|分)/.test(v)) || '';
    return {
      user: textOf(card, ['.jdc-pc-rate-card-nick', '.nickname', '.user-info', '[class*="userInfo"]', '[class*="user-name"]', '[class*="nickname"]']),
      text: textOf(card, ['.jdc-pc-rate-card-main-desc', '.info', '.comment-con', '[class*="comment-content"]', '[class*="commentContent"]', '[class*="review-content"]', '[class*="content"]']),
      time: textOf(card, ['.date.list', '.comment-time', '[class*="comment-time"]', '[class*="commentTime"]', 'time']),
      sku: textOf(card, ['.jdc-pc-rate-card-info.top .info', '.order-info', '[class*="order-info"]', '[class*="product-info"]', '[class*="sku"]']),
      product_name: textOf(card, ['[class*="product-name"]', '[class*="productName"]']),
      rating: starClass || ariaRating,
      image_count: card.querySelectorAll('img').length,
      video_count: card.querySelectorAll('video').length
    };
  }).filter(row => row.text);
}
"""


def _click_text(page: Any, labels: Iterable[str], timeout_ms: int = 4_000) -> bool:
    for label in labels:
        locator = page.get_by_text(label, exact=True)
        try:
            if locator.count() and locator.first.is_visible():
                locator.first.click(timeout=timeout_ms)
                return True
        except Exception:
            continue
    return False


def _product_title(page: Any) -> str:
    for selector in (".itemInfo-wrap .sku-name", ".sku-name", "[class*='skuName']", "[class*='productName']"):
        try:
            value = _clean(page.locator(selector).first.inner_text(timeout=2_000))
            if value and value != "最小单价计算器":
                return value
        except Exception:
            pass
    title = _clean(page.title())
    title = re.sub(r"【行情\s*报价\s*价格\s*评测】\s*[-—]?\s*京东.*$", "", title)
    title = re.sub(r"\s*[-—]\s*京东(?:JD\.COM)?\s*$", "", title, flags=re.IGNORECASE)
    return title.strip()


def open_reviews(page: Any) -> None:
    page.wait_for_load_state("domcontentloaded")
    try:
        all_button = page.locator(".comment-root .all-btn, .everyone-reviews .all-btn").first
        if all_button.is_visible():
            all_button.click(timeout=4_000)
        else:
            raise RuntimeError
    except Exception:
        _click_text(page, ("买家评价", "商品评价", "评价"))
        page.wait_for_timeout(1_000)
        if not _click_text(page, ("全部评价", "全部")):
            raise RuntimeError("没有找到“全部评价”，请确认商品存在评价并且页面已正常加载")
    page.wait_for_timeout(1_000)
    if not _click_text(page, ("最新", "最新评价", "时间排序")):
        raise RuntimeError("没有找到“最新”排序入口，京东页面结构可能已变化")
    page.wait_for_timeout(1_500)


def scrape_target(
    page: Any,
    target: ScrapeTarget,
    max_stale_rounds: int = 10,
    checkpoint: Callable[[list[dict[str, Any]]], None] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    print(f"\n打开 {target.url}，目标 {target.count} 条")
    page.goto(target.url, wait_until="domcontentloaded", timeout=60_000)
    title = _product_title(page)
    open_reviews(page)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    stale_rounds = 0
    while len(rows) < target.count and stale_rounds < max_stale_rounds:
        before = len(rows)
        for raw in page.evaluate(EXTRACT_REVIEWS_JS):
            row = normalize_review(raw, target, title, len(rows) + 1)
            if row and row["review_hash"] not in seen:
                seen.add(row["review_hash"])
                rows.append(row)
                if len(rows) >= target.count:
                    break
        if len(rows) > before and checkpoint is not None:
            checkpoint(rows)
        print(f"已采集 {len(rows)}/{target.count} 条", end="\r", flush=True)
        stale_rounds = stale_rounds + 1 if len(rows) == before else 0
        page.evaluate(r"""
        () => {
          const known = document.querySelector('#rateList [class*="_rateListContainer_"], .jdc-page-overlay [class*="_rateListContainer_"]');
          if (known) {
            known.scrollBy(0, Math.max(known.clientHeight * 0.8, 500));
            return true;
          }
          const card = document.querySelector('.comment-item, [class*="CommentItem"], .comment-root .list > .item, .comment-list > .item');
          let node = card && card.parentElement;
          while (node && node !== document.body) {
            const style = getComputedStyle(node);
            if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 20) {
              node.scrollBy(0, Math.max(node.clientHeight * 0.8, 500));
              return true;
            }
            node = node.parentElement;
          }
          return false;
        }
        """)
        page.wait_for_timeout(1_200)
    print()
    if len(rows) < target.count:
        print(f"警告：连续 {max_stale_rounds} 轮没有新评论，仅获得 {len(rows)} 条。")
    return rows[: target.count], title


def write_results(
    rows: list[dict[str, Any]],
    output_dir: Path,
    stamp: str | None = None,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"jd_reviews_{stamp}.json"
    csv_path = output_dir / f"jd_reviews_{stamp}.csv"
    json_tmp = json_path.with_suffix(".json.tmp")
    csv_tmp = csv_path.with_suffix(".csv.tmp")
    json_tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    columns = list(rows[0]) if rows else ["platform", "product_url", "product_id", "review_text_raw"]
    with csv_tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    json_tmp.replace(json_path)
    csv_tmp.replace(csv_path)
    return json_path, csv_path


def merge_review_rows(destination: list[dict[str, Any]], rows: Iterable[dict[str, Any]]) -> int:
    known = {str(row.get("review_hash") or "") for row in destination}
    added = 0
    for row in rows:
        digest = str(row.get("review_hash") or "")
        if not digest or digest in known:
            continue
        known.add(digest)
        destination.append(row)
        added += 1
    return added


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用可见浏览器抓取京东最新商品评价")
    parser.add_argument("--targets", type=Path, help="UTF-8 文本，每行 URL,数量")
    parser.add_argument("--count", type=int, help="未逐行填写数量时使用的默认数量")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--headless", action="store_true", help="仅用于已有有效登录会话的调试")
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    targets = load_targets(args.targets, args.count) if args.targets else None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 Playwright。请运行：python -m pip install -r requirements.txt", file=sys.stderr)
        return 2

    all_rows: list[dict[str, Any]] = []
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def save_checkpoint(current_rows: list[dict[str, Any]]) -> None:
        merge_review_rows(all_rows, current_rows)
        paths = write_results(all_rows, args.output, run_stamp)
        print(f"\n已保存中途检查点：{paths[1]}")

    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(args.profile.resolve()), channel="chrome", headless=args.headless,
                viewport={"width": 1440, "height": 960}, locale="zh-CN",
                chromium_sandbox=True,
            )
        except Exception as exc:
            print(f"无法启动 Chrome：{exc}\n请先运行：python -m playwright install chromium", file=sys.stderr)
            return 2
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://passport.jd.com/new/login.aspx", wait_until="domcontentloaded")
        if not args.headless:
            input("请在弹出的 Chrome 中完成京东登录；登录成功后回到这里按回车开始抓取……")
        if targets is None:
            targets = prompt_targets(args.count)
        for target in targets:
            try:
                rows, _ = scrape_target(page, target, checkpoint=save_checkpoint)
                merge_review_rows(all_rows, rows)
            except Exception as exc:
                print(f"抓取 {target.url} 失败：{exc}", file=sys.stderr)
            finally:
                if all_rows:
                    paths = write_results(all_rows, args.output, run_stamp)
                    print(f"已保存检查点：{paths[1]}")
        context.close()
    if not all_rows:
        print("没有采集到评论。", file=sys.stderr)
        return 1
    json_path, csv_path = write_results(all_rows, args.output, run_stamp)
    print(f"完成，共 {len(all_rows)} 条\nJSON：{json_path}\nCSV：{csv_path}")
    return 0


def main() -> int:
    try:
        return run(parse_args())
    except (ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
