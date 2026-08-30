"""Read-only ECComment sales estimates backed by project workbooks."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from threading import RLock
from urllib.parse import parse_qs, urlsplit

import httpx
import pandas as pd

from ui.sales_progress import DEFAULT_REVIEW_RATE, build_sales_history, sales_date_coverage


SUPPORTED_URL_PATTERN = re.compile(
    r"https?://(?:e\.tb\.cn|item\.taobao\.com|detail\.tmall\.com)/[^\s<>'\"]+",
    re.IGNORECASE,
)
DIRECT_URL_PATTERN = re.compile(
    r"https?://(?:item\.taobao\.com|detail\.tmall\.com)/[^\s<>'\"]+",
    re.IGNORECASE,
)
PRODUCT_ID_PATTERN = re.compile(r"(?:[?&]id=|itemId[\"'=:\s]+)(\d{6,})", re.IGNORECASE)


class EstimateUnavailable(RuntimeError):
    """Raised when the local ECComment data cannot answer a query."""


@dataclass(frozen=True)
class EstimateRecord:
    product_name: str
    platform: str
    period: str
    estimated_sales: int
    review_count: int
    data_date: str
    review_rate: float
    date_coverage: float
    source_mtime_ns: int

    def response(self) -> dict[str, object]:
        result = asdict(self)
        result.pop("source_mtime_ns", None)
        return {"status": "ok", **result}


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _date_text(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def _latest_data_date(
    item_key: str,
    snapshots: pd.DataFrame,
    content: pd.DataFrame,
    product_row: pd.Series,
) -> str:
    if not snapshots.empty and {"item_key", "capture_time"}.issubset(snapshots.columns):
        rows = snapshots[
            snapshots["item_key"].fillna("").astype(str).str.strip().eq(item_key)
        ]
        if not rows.empty:
            values = pd.to_datetime(rows["capture_time"], errors="coerce").dropna()
            if not values.empty:
                return values.max().strftime("%Y-%m-%d")

    item_content = content[
        content.get("item_key", pd.Series("", index=content.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .eq(item_key)
    ]
    for column in ("last_seen_at", "content_date", "content_time"):
        if column in item_content.columns:
            values = pd.to_datetime(item_content[column], errors="coerce").dropna()
            if not values.empty:
                return values.max().strftime("%Y-%m-%d")
    return _date_text(product_row.get("last_updated_at")) or date.today().isoformat()


def _read_workbook(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    try:
        sheets = pd.read_excel(
            path,
            sheet_name=["products", "content_master", "snapshots"],
            dtype=object,
        )
    except (OSError, ValueError) as exc:
        raise EstimateUnavailable(f"Cannot read project workbook: {path.name}") from exc
    return sheets["products"], sheets["content_master"], sheets["snapshots"]


def build_catalog(projects_dir: str | Path) -> dict[tuple[str, str], EstimateRecord]:
    """Build the latest estimate for every Taobao/Tmall item in top-level workbooks."""

    root = Path(projects_dir).expanduser().resolve()
    if not root.is_dir():
        raise EstimateUnavailable("ECComment projects directory is unavailable")

    records: dict[tuple[str, str], EstimateRecord] = {}
    for path in sorted(root.glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        products, content, snapshots = _read_workbook(path)
        if products.empty or content.empty:
            continue
        history = build_sales_history(content, products, review_rate=DEFAULT_REVIEW_RATE)
        if history.empty:
            continue
        latest = history.sort_values(["item_key", "sales_month"]).groupby(
            "item_key", as_index=False
        ).tail(1)
        source_mtime_ns = path.stat().st_mtime_ns
        product_rows = products.copy()
        product_rows["item_key"] = product_rows.get(
            "item_key", pd.Series("", index=product_rows.index)
        ).fillna("").astype(str).str.strip()
        product_rows = product_rows.drop_duplicates("item_key", keep="last").set_index(
            "item_key", drop=False
        )
        for _, row in latest.iterrows():
            item_key = _clean_text(row.get("item_key"))
            if ":" not in item_key or item_key not in product_rows.index:
                continue
            platform, product_id = item_key.split(":", 1)
            platform = platform.casefold()
            if platform not in {"taobao", "tmall"} or not product_id.isdigit():
                continue
            product_row = product_rows.loc[item_key]
            item_content = content[
                content.get("item_key", pd.Series("", index=content.index))
                .fillna("")
                .astype(str)
                .str.strip()
                .eq(item_key)
            ]
            coverage = sales_date_coverage(item_content)
            record = EstimateRecord(
                product_name=_clean_text(product_row.get("product_title_current"))
                or item_key,
                platform=platform,
                period=_clean_text(row.get("sales_month")),
                estimated_sales=int(round(float(row.get("estimated_sales", 0)))),
                review_count=int(row.get("review_count", 0)),
                data_date=_latest_data_date(item_key, snapshots, content, product_row),
                review_rate=DEFAULT_REVIEW_RATE,
                date_coverage=round(float(coverage["coverage"]) * 100, 1),
                source_mtime_ns=source_mtime_ns,
            )
            key = (platform, product_id)
            previous = records.get(key)
            if previous is None or (
                record.data_date,
                record.source_mtime_ns,
            ) > (
                previous.data_date,
                previous.source_mtime_ns,
            ):
                records[key] = record
    return records


def _direct_reference(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url.rstrip("，。！？、；;)]}"))
    host = (parsed.hostname or "").casefold()
    platform = "tmall" if host == "detail.tmall.com" else "taobao"
    product_id = parse_qs(parsed.query).get("id", [""])[0].strip()
    if not product_id:
        match = PRODUCT_ID_PATTERN.search(url)
        product_id = match.group(1) if match else ""
    if product_id.isdigit():
        return platform, product_id
    return None


async def resolve_product_reference(query: str) -> tuple[str, str]:
    match = SUPPORTED_URL_PATTERN.search(query)
    if not match:
        raise EstimateUnavailable("No supported product link")
    original_url = match.group(0)
    host = (urlsplit(original_url).hostname or "").casefold()
    if host != "e.tb.cn":
        direct = _direct_reference(original_url)
        if direct:
            return direct
        raise EstimateUnavailable("Product link has no item id")

    try:
        async with httpx.AsyncClient(timeout=2.5, follow_redirects=True) as client:
            response = await client.get(original_url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise EstimateUnavailable("Taobao short link cannot be resolved") from exc

    candidates = [str(item.url) for item in response.history] + [str(response.url)]
    candidates.extend(DIRECT_URL_PATTERN.findall(response.text[:512_000]))
    for candidate in candidates:
        if (urlsplit(candidate).hostname or "").casefold() in {
            "item.taobao.com",
            "detail.tmall.com",
        }:
            direct = _direct_reference(candidate)
            if direct:
                return direct
    product_id = PRODUCT_ID_PATTERN.search(response.text[:512_000])
    if product_id:
        return "taobao", product_id.group(1)
    raise EstimateUnavailable("Taobao short link did not identify a product")


class EstimateCatalog:
    """Thread-safe, mtime-aware cache for read-only workbook estimates."""

    def __init__(self, projects_dir: str | Path):
        self.projects_dir = Path(projects_dir)
        self._lock = RLock()
        self._records: dict[tuple[str, str], EstimateRecord] = {}
        self._signature: tuple[tuple[str, int, int], ...] = ()

    def _current_signature(self) -> tuple[tuple[str, int, int], ...]:
        root = self.projects_dir.expanduser().resolve()
        if not root.is_dir():
            return ()
        return tuple(
            (path.name, path.stat().st_mtime_ns, path.stat().st_size)
            for path in sorted(root.glob("*.xlsx"))
            if not path.name.startswith("~$")
        )

    def refresh_if_needed(self) -> None:
        signature = self._current_signature()
        with self._lock:
            if self._records and signature == self._signature:
                return
            records = build_catalog(self.projects_dir)
            self._records = records
            self._signature = signature

    async def estimate(self, query: str) -> dict[str, object]:
        platform, product_id = await resolve_product_reference(query)
        await asyncio.to_thread(self.refresh_if_needed)
        with self._lock:
            record = self._records.get((platform, product_id))
            if record is None:
                # Some Taobao shares resolve to a neutral domain while the tracked item is
                # recorded as Tmall. A unique cross-platform product id remains safe to use.
                matches = [
                    value
                    for (candidate_platform, candidate_id), value in self._records.items()
                    if candidate_id == product_id
                ]
                if len(matches) == 1:
                    record = matches[0]
            if record is None:
                raise EstimateUnavailable("Product is not present in ECComment data")
            return record.response()


_catalog: EstimateCatalog | None = None


def configured_catalog() -> EstimateCatalog:
    global _catalog
    projects_dir = os.getenv("ECCOMMENT_PROJECTS_DIR", "projects").strip() or "projects"
    if _catalog is None or str(_catalog.projects_dir) != projects_dir:
        _catalog = EstimateCatalog(projects_dir)
    return _catalog
