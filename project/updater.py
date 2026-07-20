from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

from analysis.ai_keyword_matcher import load_keywords
from analysis.evidence_rules import analyze_ai_related
from analysis.summary import build_summaries
from extractor.html_loader import load_html
from extractor.platform_detect import detect_platform
from extractor.product_meta import extract_product_meta
from extractor.reviews import parse_reviews
from extractor.taobao_qa import parse_taobao_qa
from llm.deepseek_client import DeepSeekClient
from llm.provider_config import load_provider_config
from matching.content_identity import build_identity_keys
from matching.overlap_detector import detect_overlap_boundary
from project.schema import PARSER_VERSION, SHEET_COLUMNS, WORKBOOK_VERSION
from project.workbook import empty_frame, load_sheets, normalize_frame, write_sheets_atomic
from sentiment_pipeline import (
    SentimentPipelineResult,
    process_sentiment_for_comments,
    select_sentiment_targets,
)
from sentiment_rules import try_rule_sentiment


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEYWORDS = ROOT / "config" / "ai_keywords.yaml"
DEFAULT_LLM_CONFIG = ROOT / "config" / "llm_providers.local.json"
SENTIMENT_VERSION = "sentiment_fast_v1"
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _text(value: Any) -> str:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return ""
    return str(value)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).strip().casefold() in {"1", "true", "yes", "y"}


def _records(frame: pd.DataFrame) -> list[dict]:
    return [
        {key: ("" if pd.isna(value) else value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _append(frame: pd.DataFrame, rows: list[dict], sheet: str) -> pd.DataFrame:
    if not rows:
        return normalize_frame(sheet, frame)
    additions = pd.DataFrame(rows)
    if frame.empty:
        return normalize_frame(sheet, additions)
    return normalize_frame(
        sheet,
        pd.concat([frame, additions], ignore_index=True),
    )


def create_project(
    workbook_path: str,
    project_id: str,
    project_name: str,
    objective: str = "",
) -> None:
    path = Path(workbook_path).expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"项目工作簿已存在：{path}")
    project_id = project_id.strip()
    if not project_id:
        raise ValueError("project_id 不能为空")
    timestamp = _now()
    sheets = {name: empty_frame(name) for name in SHEET_COLUMNS}
    sheets["project_info"] = pd.DataFrame(
        [
            {
                "project_id": project_id,
                "project_name": project_name.strip() or project_id,
                "objective": objective.strip(),
                "created_at": timestamp,
                "updated_at": timestamp,
                "workbook_version": WORKBOOK_VERSION,
            }
        ]
    )
    rebuild_compatibility_sheets_from_frames(sheets, project_id)
    write_sheets_atomic(path, sheets, create_backup=False)


def create_named_project(
    projects_dir: str | Path,
    project_name: str,
    objective: str = "",
    *,
    project_id: str | None = None,
) -> Path:
    """Create a project workbook with a safe, user-facing file name."""
    name = project_name.strip()
    if not name:
        raise ValueError("项目名称不能为空")
    directory = Path(projects_dir).expanduser().resolve()
    workbook_path = directory / f"{project_filename_stem(name)}.xlsx"
    if workbook_path.exists():
        raise FileExistsError(f"已存在同名项目：{name}")
    identifier = (project_id or f"project_{uuid.uuid4().hex[:12]}").strip()
    create_project(str(workbook_path), identifier, name, objective)
    return workbook_path


def project_filename_stem(project_name: str, max_length: int = 80) -> str:
    """Return a Windows-safe workbook stem while preserving readable Chinese."""
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", project_name)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    stem = stem[:max_length].rstrip(" .")
    if not stem:
        raise ValueError("项目名称不能只包含文件名非法字符")
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem = f"{stem}_项目"
    return stem


def register_product(
    workbook_path: str,
    project_id: str,
    platform: str,
    platform_product_id: str,
    brand_product_id: str | None = None,
    brand: str | None = None,
    model_name: str | None = None,
) -> dict:
    sheets = load_sheets(workbook_path)
    _require_project(sheets, project_id)
    row, created = _register_product_in_frames(
        sheets,
        project_id,
        platform,
        platform_product_id,
        brand_product_id=brand_product_id,
        brand=brand,
        model_name=model_name,
    )
    if created:
        _touch_project(sheets, project_id)
        rebuild_compatibility_sheets_from_frames(sheets, project_id)
        write_sheets_atomic(workbook_path, sheets)
    return row


def _register_product_in_frames(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
    platform: str,
    platform_product_id: str,
    *,
    brand_product_id: str | None = None,
    brand: str | None = None,
    model_name: str | None = None,
    identity_confidence: str = "id_confirmed",
) -> tuple[dict, bool]:
    platform = platform.strip().casefold()
    product_id = platform_product_id.strip()
    if not platform or platform == "unknown":
        raise ValueError("无法确认平台，请使用 --platform 明确指定")
    if not product_id:
        raise ValueError("platform_product_id 不能为空")
    item_key = f"{platform}:{product_id}"
    products = sheets["products"]
    mask = (
        products["project_id"].fillna("").astype(str).eq(project_id)
        & products["item_key"].fillna("").astype(str).eq(item_key)
    )
    if mask.any():
        return _records(products.loc[mask].head(1))[0], False
    timestamp = _now()
    row = {
        "project_id": project_id,
        "item_key": item_key,
        "platform": platform,
        "platform_product_id": product_id,
        "brand_product_id": brand_product_id or "",
        "brand": brand or "",
        "model_name": model_name or "",
        "product_title_current": "",
        "shop_name_current": "",
        "first_added_at": timestamp,
        "last_updated_at": timestamp,
        "status": "active",
        "identity_confidence": identity_confidence,
    }
    sheets["products"] = _append(products, [row], "products")
    return row, True


def extract_page_identity(file_path: str) -> dict:
    path = Path(file_path).expanduser().resolve()
    raw = path.read_bytes()
    html_text = load_html(str(path))
    platform = detect_platform(html_text, str(path))
    soup = BeautifulSoup(html_text, "lxml")
    meta = extract_product_meta(html_text, soup, str(path), platform)
    return {
        "platform": platform,
        "product_id": _text(meta.get("product_id")),
        "title": _text(meta.get("product_title")),
        "shop": _text(meta.get("shop_name")),
        "saved_url": _text(meta.get("product_url")),
        "capture_time": datetime.fromtimestamp(path.stat().st_mtime)
        .replace(microsecond=0)
        .isoformat(sep=" "),
        "file_hash": hashlib.sha256(raw).hexdigest(),
        "source_file": path.name,
        "source_path": str(path),
    }


def extract_contents(file_path: str, platform: str) -> list[dict]:
    html_text = load_html(file_path)
    soup = BeautifulSoup(html_text, "lxml")
    meta = extract_product_meta(html_text, soup, file_path, platform)
    meta["platform"] = platform
    reviews = parse_reviews(html_text, soup, meta)
    qa_pairs = parse_taobao_qa(html_text, soup, meta)
    rows: list[dict] = []
    for review in reviews:
        rows.append(
            {
                "content_role": "followup" if review.get("is_followup") else "review",
                "platform_content_id": review.get("platform_content_id", ""),
                "content_text_raw": review.get("review_text_raw", ""),
                "content_text_clean": review.get("review_text_clean", ""),
                "parent_text_clean": "",
                "user_name_masked": review.get("user_name_masked", ""),
                "content_time": review.get("review_time", ""),
                "content_date": review.get("review_date", ""),
                "sku": review.get("sku", ""),
                "content_order": review.get("review_order", len(rows) + 1),
            }
        )
    for pair in qa_pairs:
        question = {
            "content_role": "question",
            "platform_content_id": pair.get("question_id", ""),
            "content_text_raw": pair.get("question_text_raw", ""),
            "content_text_clean": pair.get("question_text_clean", ""),
            "parent_text_clean": "",
            "user_name_masked": "",
            "content_time": "",
            "content_date": "",
            "sku": "",
            "content_order": len(rows) + 1,
        }
        rows.append(question)
        if pair.get("answer_text_clean"):
            rows.append(
                {
                    "content_role": "answer",
                    "platform_content_id": pair.get("answer_id", ""),
                    "content_text_raw": pair.get("answer_text_raw", ""),
                    "content_text_clean": pair.get("answer_text_clean", ""),
                    "parent_text_clean": pair.get("question_text_clean", ""),
                    "user_name_masked": pair.get("answer_user_status", ""),
                    "content_time": "",
                    "content_date": "",
                    "sku": "",
                    "content_order": len(rows) + 1,
                }
            )
    return rows


def get_latest_snapshot(
    workbook_path: str,
    project_id: str,
    item_key: str,
) -> dict | None:
    sheets = load_sheets(workbook_path)
    return _latest_snapshot_from_frames(sheets, project_id, item_key)


def _latest_snapshot_from_frames(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
    item_key: str,
) -> dict | None:
    frame = sheets["snapshots"]
    subset = frame[
        frame["project_id"].fillna("").astype(str).eq(project_id)
        & frame["item_key"].fillna("").astype(str).eq(item_key)
    ].copy()
    if subset.empty:
        return None
    subset["_capture"] = pd.to_datetime(subset["capture_time"], errors="coerce")
    subset = subset.sort_values(["_capture", "imported_at"], ascending=False)
    return _records(subset.drop(columns=["_capture"]).head(1))[0]


def update_project_item(
    workbook_path: str,
    project_id: str,
    supplied_product_id: str | None,
    file_path: str,
    dry_run: bool = False,
    *,
    platform: str | None = None,
    brand_product_id: str | None = None,
    brand: str | None = None,
    model_name: str | None = None,
    capture_time: str | None = None,
    allow_backfill: bool = False,
    keywords_path: str | None = None,
    enable_sentiment: bool = True,
    sentiment_provider: str = "deepseek",
    sentiment_config_path: str | None = None,
    sentiment_model: str | None = None,
    sentiment_batch_size: int = 50,
    sentiment_detail_limit: int | None = 50,
    sentiment_full_llm: bool = True,
    sentiment_client=None,
) -> dict:
    sheets = load_sheets(workbook_path)
    _require_project(sheets, project_id)
    identity = extract_page_identity(file_path)
    chosen_platform = (platform or identity["platform"]).strip().casefold()
    extracted_product_id = _text(identity["product_id"]).strip()
    if not extracted_product_id:
        raise ValueError(
            f"页面文件 {identity['source_file']} 中未识别到商品 ID，已阻止更新"
        )
    legacy_supplied_id = _text(supplied_product_id).strip()
    id_match = not legacy_supplied_id or legacy_supplied_id == extracted_product_id
    item_key = f"{chosen_platform}:{extracted_product_id}"
    capture_value = _normalize_datetime(capture_time or identity["capture_time"])

    duplicate = sheets["snapshots"]
    duplicate_mask = (
        duplicate["project_id"].fillna("").astype(str).eq(project_id)
        & duplicate["item_key"].fillna("").astype(str).eq(item_key)
        & duplicate["file_hash"].fillna("").astype(str).eq(identity["file_hash"])
    )
    if duplicate_mask.any():
        prior = _records(duplicate.loc[duplicate_mask].head(1))[0]
        result = {
            "project_id": project_id,
            "item_key": item_key,
            "snapshot_id": prior["snapshot_id"],
            "capture_time": capture_value,
            "extracted_product_id": identity["product_id"],
            "supplied_product_id": legacy_supplied_id,
            "product_id_match": id_match,
            "extracted_count": int(prior.get("extracted_count") or 0),
            "new_count": 0,
            "existing_count": int(prior.get("extracted_count") or 0),
            "uncertain_count": 0,
            "boundary_status": "duplicate_file",
            "overlap_length": 0,
            "sentiment_enabled": enable_sentiment,
            "sentiment_target_count": 0,
            "sentiment_rule_count": 0,
            "sentiment_llm_count": 0,
            "sentiment_detail_count": 0,
            "sentiment_failed_count": 0,
            "sentiment_status": "not_run_duplicate",
            "sentiment_model": sentiment_model or "",
            "sentiment_version": SENTIMENT_VERSION,
            "sentiment_strategy": (
                "full_llm" if sentiment_full_llm else "rules_then_llm"
            ),
            "result": "warning",
            "message": "相同快照已导入，内容主表未变",
            "dry_run": dry_run,
            "backup_path": "",
        }
        if not dry_run:
            _append_update_log(sheets, result)
            _touch_project(sheets, project_id)
            result["backup_path"] = str(write_sheets_atomic(workbook_path, sheets) or "")
        return result

    product, created = _register_product_in_frames(
        sheets,
        project_id,
        chosen_platform,
        extracted_product_id,
        brand_product_id=brand_product_id,
        brand=brand,
        model_name=model_name,
        identity_confidence="id_confirmed",
    )
    latest = _latest_snapshot_from_frames(sheets, project_id, item_key)
    is_backfill = bool(
        latest
        and pd.Timestamp(capture_value)
        < pd.Timestamp(_normalize_datetime(_text(latest["capture_time"])))
    )
    if is_backfill and not allow_backfill:
        raise ValueError(
            f"新文件时间 {capture_value} 早于最新快照 {latest['capture_time']}；"
            "如需历史回填，请使用 --allow-backfill"
        )

    contents = extract_contents(file_path, chosen_platform)
    for row in contents:
        row.update(build_identity_keys(row, item_key))
    snapshot_id = _snapshot_id(
        chosen_platform,
        extracted_product_id,
        capture_value,
        identity["file_hash"],
    )

    old_contents = _latest_snapshot_contents(sheets, latest)
    if latest is None:
        boundary = {
            "status": "first_import",
            "overlap_length": 0,
            "new_prefix_end": len(contents),
            "matched_pairs": [],
            "confidence": "high",
        }
    elif is_backfill:
        boundary = {
            "status": "fallback",
            "overlap_length": 0,
            "new_prefix_end": None,
            "matched_pairs": [],
            "confidence": "low",
        }
    else:
        boundary = detect_overlap_boundary(old_contents, contents)

    comparison = _compare_with_master_frames(
        sheets, project_id, item_key, contents
    )
    if latest is None:
        comparison = {"new": contents, "existing": [], "uncertain": []}

    result = {
        "project_id": project_id,
        "item_key": item_key,
        "snapshot_id": snapshot_id,
        "capture_time": capture_value,
        "extracted_product_id": identity["product_id"],
        "supplied_product_id": legacy_supplied_id,
        "product_id_match": id_match,
        "is_first_import": latest is None,
        "is_backfill": is_backfill,
        "latest_snapshot_id": _text(latest.get("snapshot_id")) if latest else "",
        "extracted_count": len(contents),
        "new_count": len(comparison["new"]),
        "existing_count": len(comparison["existing"]),
        "uncertain_count": len(comparison["uncertain"]),
        "boundary_status": boundary["status"],
        "overlap_length": boundary["overlap_length"],
        "boundary_confidence": boundary["confidence"],
        "sentiment_enabled": enable_sentiment,
        "sentiment_target_count": sum(
            row.get("content_role") in {"review", "followup"}
            and bool(str(row.get("content_text_clean") or "").strip())
            for row in comparison["new"]
        ),
        "sentiment_rule_count": 0,
        "sentiment_llm_count": 0,
        "sentiment_detail_count": 0,
        "sentiment_failed_count": 0,
        "sentiment_status": (
            "pending_confirmation" if enable_sentiment else "disabled"
        ),
        "sentiment_model": sentiment_model or "",
        "sentiment_version": SENTIMENT_VERSION,
        "sentiment_strategy": (
            "full_llm" if sentiment_full_llm else "rules_then_llm"
        ),
        "result": "warning" if boundary["status"] == "fallback" or comparison["uncertain"] else "success",
        "message": _result_message(boundary["status"], comparison, is_backfill),
        "dry_run": dry_run,
        "backup_path": "",
    }
    if dry_run:
        return result

    imported_at = _now()
    _apply_master_update(
        sheets,
        project_id,
        item_key,
        chosen_platform,
        extracted_product_id,
        snapshot_id,
        identity["source_file"],
        capture_value,
        comparison,
        is_backfill=is_backfill,
    )
    analysis_rows = analyze_new_contents(
        comparison["new"],
        project_id=project_id,
        item_key=item_key,
        keywords_path=keywords_path,
    )
    sentiment_run = run_incremental_sentiment(
        comparison["new"],
        analysis_rows,
        project_id=project_id,
        item_key=item_key,
        snapshot_id=snapshot_id,
        source_file=identity["source_file"],
        platform=chosen_platform,
        product_title=identity["title"],
        enabled=enable_sentiment,
        provider=sentiment_provider,
        config_path=sentiment_config_path,
        model=sentiment_model,
        batch_size=sentiment_batch_size,
        detail_limit=sentiment_detail_limit,
        full_llm=sentiment_full_llm,
        client=sentiment_client,
    )
    apply_sentiment_to_analysis(
        analysis_rows,
        sentiment_run["pipeline"].fast_rows,
        sentiment_run["pipeline"].detail_rows,
    )
    result.update(
        {
            "sentiment_target_count": sentiment_run["pipeline"].total_count,
            "sentiment_rule_count": sentiment_run["pipeline"].rule_count,
            "sentiment_llm_count": sentiment_run["pipeline"].llm_fast_count,
            "sentiment_detail_count": sentiment_run["pipeline"].detail_count,
            "sentiment_failed_count": sentiment_run["pipeline"].failed_count,
            "sentiment_status": sentiment_run["status"],
            "sentiment_model": sentiment_run["model"],
            "sentiment_version": SENTIMENT_VERSION,
            "sentiment_strategy": sentiment_run["strategy"],
        }
    )
    if sentiment_run["status"] in {"partial", "failed_to_start"}:
        result["result"] = "warning"
        result["message"] = (
            f"{result['message']}；情绪判断 {sentiment_run['status']}："
            f"{sentiment_run['message']}"
        )
    sheets["analysis"] = _append(sheets["analysis"], analysis_rows, "analysis")
    append_sentiment_sheets(
        sheets,
        sentiment_run,
        project_id=project_id,
        item_key=item_key,
        snapshot_id=snapshot_id,
    )
    sheets["snapshot_contents"] = _append(
        sheets["snapshot_contents"],
        [
            {
                "snapshot_id": snapshot_id,
                "project_id": project_id,
                "item_key": item_key,
                **{column: row.get(column, "") for column in SHEET_COLUMNS["snapshot_contents"][3:]},
            }
            for row in contents
        ],
        "snapshot_contents",
    )
    snapshot_row = {
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "item_key": item_key,
        "capture_time": capture_value,
        "imported_at": imported_at,
        "source_file": identity["source_file"],
        "source_path": identity["source_path"],
        "file_hash": identity["file_hash"],
        "extracted_product_id": identity["product_id"],
        "supplied_product_id": legacy_supplied_id,
        "product_id_match": id_match,
        "product_title": identity["title"],
        "shop_name": identity["shop"],
        "extracted_count": len(contents),
        "new_count": len(comparison["new"]),
        "existing_count": len(comparison["existing"]),
        "uncertain_count": len(comparison["uncertain"]),
        "boundary_status": boundary["status"],
        "parser_version": PARSER_VERSION,
        "notes": result["message"],
    }
    sheets["snapshots"] = _append(sheets["snapshots"], [snapshot_row], "snapshots")
    _append_review_queue(
        sheets, project_id, item_key, snapshot_id, comparison["uncertain"]
    )
    result["update_id"] = f"upd_{uuid.uuid4().hex}"
    sentiment_run["run_summary"]["update_id"] = result["update_id"]
    sheets["sentiment_run_summary"] = _append(
        sheets["sentiment_run_summary"],
        [sentiment_run["run_summary"]],
        "sentiment_run_summary",
    )
    _append_update_log(sheets, {**result, "analysis_new_count": len(analysis_rows)})
    _update_product(
        sheets,
        project_id,
        item_key,
        title=identity["title"],
        shop=identity["shop"],
        identity_confidence=product.get("identity_confidence", "id_confirmed"),
    )
    _touch_project(sheets, project_id)
    rebuild_compatibility_sheets_from_frames(sheets, project_id)
    result["backup_path"] = str(write_sheets_atomic(workbook_path, sheets) or "")
    return result


def update_project_files(
    workbook_path: str,
    project_id: str,
    file_paths: list[str],
    dry_run: bool = False,
    **kwargs,
) -> list[dict]:
    """Update multiple SingleFile pages in order, isolating failures per file."""
    if not file_paths:
        raise ValueError("至少需要提供一个页面文件")
    requested_sentiment = bool(kwargs.get("enable_sentiment", True))

    def run_batch(target_workbook: str, simulate: bool) -> list[dict]:
        results: list[dict] = []
        for file_path in file_paths:
            try:
                result = update_project_item(
                    target_workbook,
                    project_id,
                    None,
                    file_path,
                    dry_run=False,
                    **kwargs,
                )
                if simulate:
                    result["dry_run"] = True
                    result["backup_path"] = ""
                    result["sentiment_enabled"] = requested_sentiment
                    result["sentiment_status"] = (
                        "pending_confirmation"
                        if requested_sentiment
                        else "disabled"
                    )
                result["source_file"] = Path(file_path).name
                results.append(result)
            except Exception as exc:
                results.append(
                    {
                        "source_file": Path(file_path).name,
                        "result": "failed",
                        "error": str(exc),
                        "dry_run": simulate,
                    }
                )
        return results

    if not dry_run:
        return run_batch(workbook_path, False)

    source = Path(workbook_path).expanduser().resolve()
    with tempfile.TemporaryDirectory() as temp_dir:
        preview_workbook = Path(temp_dir) / source.name
        shutil.copy2(source, preview_workbook)
        kwargs["enable_sentiment"] = False
        return run_batch(str(preview_workbook), True)


def run_incremental_sentiment(
    new_contents: list[dict],
    analysis_rows: list[dict],
    *,
    project_id: str,
    item_key: str,
    snapshot_id: str,
    source_file: str,
    platform: str,
    product_title: str,
    enabled: bool,
    provider: str,
    config_path: str | None,
    model: str | None,
    batch_size: int,
    detail_limit: int | None,
    full_llm: bool = True,
    client=None,
) -> dict:
    analyzed_at = _now()
    evidence_by_id = {
        _text(row.get("content_id")): row.get("evidence_level", "")
        for row in analysis_rows
    }
    prepared = []
    for content in new_contents:
        row = dict(content)
        row.update(
            {
                "content_hash": content.get("identity_key", ""),
                "source_file": source_file,
                "platform": platform,
                "product_title": product_title,
                "evidence_level": evidence_by_id.get(
                    _text(content.get("content_id")),
                    "",
                ),
            }
        )
        prepared.append(row)
    targets = select_sentiment_targets(prepared)
    pipeline = SentimentPipelineResult(total_count=len(targets))
    selected_model = model or ""
    strategy = "full_llm" if full_llm else "rules_then_llm"
    status = "disabled"
    message = "情绪判断已关闭"

    if enabled and not targets:
        status = "success"
        message = "本次没有新增商品评论，未调用 LLM"
    elif enabled:
        rule_preview = process_sentiment_for_comments(
            comments=targets,
            client=None,
            model_name="",
            batch_size=max(int(batch_size or 1), 1),
            detail_limit=detail_limit,
            dry_run=True,
            use_local_rules=not full_llm,
        )
        try:
            if client is None:
                provider_config = load_provider_config(
                    config_path=config_path or DEFAULT_LLM_CONFIG,
                    provider=provider,
                )
                selected_model = (
                    model
                    or provider_config.default_model
                    or "deepseek-v4-flash"
                )
                api_key_file = provider_config.api_key_file
                if api_key_file and not Path(api_key_file).expanduser().is_absolute():
                    api_key_file = str(ROOT / api_key_file)
                client = DeepSeekClient(
                    api_key_file=api_key_file,
                    base_url=provider_config.base_url or None,
                    default_model=selected_model,
                    timeout=max(int(provider_config.timeout_seconds or 90), 1),
                )
            else:
                selected_model = (
                    model
                    or _text(getattr(client, "default_model", ""))
                    or "injected-model"
                )
            pipeline = process_sentiment_for_comments(
                comments=targets,
                client=client,
                model_name=selected_model,
                batch_size=max(int(batch_size or 1), 1),
                detail_limit=detail_limit,
                dry_run=False,
                use_local_rules=not full_llm,
            )
            status = "success" if pipeline.failed_count == 0 else "partial"
            message = (
                f"策略 {strategy}；目标 {pipeline.total_count}；"
                f"规则 {pipeline.rule_count}；"
                f"LLM 快判 {pipeline.llm_fast_count}；详析 {pipeline.detail_count}；"
                f"失败 {pipeline.failed_count}"
            )
        except Exception as exc:
            pipeline = rule_preview
            llm_needed = [
                row
                for row in targets
                if full_llm or try_rule_sentiment(row) is None
            ]
            pipeline.failure_rows.extend(
                {
                    "stage": "sentiment_start",
                    "content_id": row.get("content_id", ""),
                    "content_hash": row.get("content_hash", ""),
                    "content_text_clean": row.get("content_text_clean", ""),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "raw_response": "",
                }
                for row in llm_needed
            )
            pipeline.failed_count = len(pipeline.failure_rows)
            status = "failed_to_start"
            message = str(exc)

    run_summary = {
        "update_id": "",
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "item_key": item_key,
        "enabled": enabled,
        "status": status,
        "message": message,
        "target_review_count": pipeline.total_count,
        "rule_count": pipeline.rule_count,
        "llm_fast_count": pipeline.llm_fast_count,
        "detail_count": pipeline.detail_count,
        "failed_count": pipeline.failed_count,
        "provider": provider,
        "model": selected_model,
        "sentiment_version": SENTIMENT_VERSION,
        "sentiment_strategy": strategy,
        "batch_size": batch_size,
        "detail_limit": "" if detail_limit is None else detail_limit,
        "elapsed_seconds": pipeline.elapsed_seconds,
        "analyzed_at": analyzed_at,
    }
    return {
        "pipeline": pipeline,
        "status": status,
        "message": message,
        "model": selected_model,
        "strategy": strategy,
        "analyzed_at": analyzed_at,
        "run_summary": run_summary,
    }


def apply_sentiment_to_analysis(
    analysis_rows: list[dict],
    fast_rows: list[dict],
    detail_rows: list[dict],
) -> None:
    fast_by_id = {
        _text(row.get("content_id")): row for row in fast_rows
    }
    detail_by_id = {
        _text(row.get("content_id")): row for row in detail_rows
    }
    for analysis in analysis_rows:
        content_id = _text(analysis.get("content_id"))
        fast = fast_by_id.get(content_id)
        if fast:
            analysis.update(
                {
                    "sentiment": fast.get("sentiment_label", ""),
                    "sentiment_label_cn": fast.get(
                        "sentiment_label_cn",
                        "",
                    ),
                    "sentiment_score": fast.get("sentiment_score", ""),
                    "praise_code": fast.get("praise_code", ""),
                    "praise_cn": fast.get("praise_cn", ""),
                    "complaint_code": fast.get("complaint_code", ""),
                    "complaint_cn": fast.get("complaint_cn", ""),
                    "sentiment_confidence": fast.get(
                        "sentiment_confidence",
                        "",
                    ),
                    "sentiment_source": fast.get("sentiment_source", ""),
                    "sentiment_version": SENTIMENT_VERSION,
                }
            )
        detail = detail_by_id.get(content_id)
        if detail and detail.get("geo_value"):
            analysis["geo_claim"] = detail["geo_value"]


def append_sentiment_sheets(
    sheets: dict[str, pd.DataFrame],
    sentiment_run: dict,
    *,
    project_id: str,
    item_key: str,
    snapshot_id: str,
) -> None:
    pipeline = sentiment_run["pipeline"]
    common = {
        "project_id": project_id,
        "item_key": item_key,
        "snapshot_id": snapshot_id,
        "sentiment_version": SENTIMENT_VERSION,
        "model": sentiment_run["model"],
        "analyzed_at": sentiment_run["analyzed_at"],
    }
    for sheet_name, rows in (
        ("sentiment_fast", pipeline.fast_rows),
        ("sentiment_detail", pipeline.detail_rows),
        ("sentiment_failures", pipeline.failure_rows),
        ("sentiment_timings", pipeline.timing_rows),
        ("sentiment_summary", pipeline.summary_rows),
    ):
        enriched = [{**row, **common} for row in rows]
        sheets[sheet_name] = _append(
            sheets[sheet_name],
            enriched,
            sheet_name,
        )


def compare_with_master(
    workbook_path: str,
    project_id: str,
    item_key: str,
    candidates: list[dict],
) -> dict:
    sheets = load_sheets(workbook_path)
    prepared = []
    for candidate in candidates:
        row = dict(candidate)
        row.update(build_identity_keys(row, item_key))
        prepared.append(row)
    return _compare_with_master_frames(sheets, project_id, item_key, prepared)


def _compare_with_master_frames(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
    item_key: str,
    candidates: list[dict],
) -> dict:
    frame = sheets["content_master"]
    subset = frame[
        frame["project_id"].fillna("").astype(str).eq(project_id)
        & frame["item_key"].fillna("").astype(str).eq(item_key)
    ]
    master = _records(subset)
    strict = {row["strict_key"]: row for row in master if row.get("strict_key")}
    composite = {
        row["composite_key"]: row for row in master if row.get("composite_key")
    }
    by_text: dict[str, list[dict]] = {}
    for row in master:
        by_text.setdefault(_text(row.get("text_key")), []).append(row)
    new_rows: list[dict] = []
    existing: list[dict] = []
    uncertain: list[dict] = []
    for candidate in candidates:
        matched = None
        if candidate.get("strict_key"):
            matched = strict.get(candidate["strict_key"])
        matched = matched or composite.get(candidate.get("composite_key", ""))
        if matched:
            existing.append({"candidate": candidate, "master": matched})
            continue
        same_text = by_text.get(_text(candidate.get("text_key")), [])
        has_auxiliary = any(
            _text(candidate.get(field)).strip()
            for field in ("user_name_masked", "content_time", "sku", "parent_text_clean")
        )
        if same_text and not has_auxiliary:
            uncertain.append(
                {
                    "candidate": candidate,
                    "master": same_text[0],
                    "reason": "文本相同但缺少用户、时间、SKU 等辅助字段",
                }
            )
        else:
            new_rows.append(candidate)
    return {"new": new_rows, "existing": existing, "uncertain": uncertain}


def analyze_new_contents(
    new_contents: list[dict],
    enabled_modules: list[str] | None = None,
    *,
    project_id: str = "",
    item_key: str = "",
    keywords_path: str | None = None,
) -> list[dict]:
    del enabled_modules
    keywords = load_keywords(str(keywords_path or DEFAULT_KEYWORDS))
    analyzed_at = _now()
    rows = []
    for content in new_contents:
        analysis = analyze_ai_related(dict(content), keywords)
        rows.append(
            {
                "content_id": content.get("content_id", ""),
                "project_id": project_id,
                "item_key": item_key,
                "pre_purchase_decision": bool(analysis.get("pre_purchase_decision")),
                "ai_candidate": bool(analysis.get("ai_candidate")),
                "ai_influence_level": analysis.get("ai_influence_level", ""),
                "ai_evidence_type": analysis.get("ai_evidence_type", ""),
                "evidence_level": analysis.get("evidence_level", ""),
                "sentiment": "",
                "topic": "",
                "geo_claim": "",
                "matched_keywords": analysis.get("matched_keywords", ""),
                "match_score": analysis.get("match_score", 0),
                "analysis_version": "ai_rules_v1.4",
                "analyzed_at": analyzed_at,
                "analysis_method": "local_rules",
            }
        )
    return rows


def backfill_project_sentiment(
    workbook_path: str,
    project_id: str,
    *,
    provider: str = "deepseek",
    config_path: str | None = None,
    model: str | None = None,
    batch_size: int = 50,
    detail_limit: int | None = 50,
    limit: int | None = None,
    dry_run: bool = False,
    full_llm: bool = True,
    client=None,
) -> dict:
    """Classify project reviews that do not yet have a fast sentiment result."""
    sheets = load_sheets(workbook_path)
    _require_project(sheets, project_id)
    master = sheets["content_master"]
    project_mask = master["project_id"].fillna("").astype(str).eq(project_id)
    role_mask = (
        master["content_role"]
        .fillna("")
        .astype(str)
        .isin(["review", "followup"])
    )
    text_mask = (
        master["content_text_clean"]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
    )
    candidates = master[project_mask & role_mask & text_mask].copy()

    fast = sheets["sentiment_fast"]
    if fast.empty:
        completed_ids: set[str] = set()
    else:
        fast_project = fast[
            fast["project_id"].fillna("").astype(str).eq(project_id)
        ]
        valid_labels = (
            fast_project["sentiment_label"]
            .fillna("")
            .astype(str)
            .str.upper()
            .isin(["P", "N", "M", "Z"])
        )
        completed_ids = set(
            fast_project.loc[valid_labels, "content_id"]
            .fillna("")
            .astype(str)
        )
    candidates = candidates[
        ~candidates["content_id"].fillna("").astype(str).isin(completed_ids)
    ]
    if limit is not None:
        candidates = candidates.head(max(int(limit), 0))

    rows = _records(candidates)
    rule_target_count = (
        0
        if full_llm
        else sum(try_rule_sentiment(row) is not None for row in rows)
    )
    preview = {
        "project_id": project_id,
        "candidate_count": len(rows),
        "already_completed_count": len(completed_ids),
        "rule_target_count": rule_target_count,
        "llm_target_count": len(rows) - rule_target_count,
        "sentiment_strategy": (
            "full_llm" if full_llm else "rules_then_llm"
        ),
        "dry_run": dry_run,
    }
    if dry_run or not rows:
        return {
            **preview,
            "result": "success",
            "status": "nothing_to_do" if not rows else "preview",
            "backup_path": "",
        }

    analysis_frame = sheets["analysis"]
    analysis_rows = project_frame_records(analysis_frame, project_id)
    analysis_by_id = {
        _text(row.get("content_id")): row for row in analysis_rows
    }
    products = sheets["products"]
    product_rows = products[
        products["project_id"].fillna("").astype(str).eq(project_id)
    ]
    titles = {
        _text(row.get("item_key")): _text(
            row.get("product_title_current")
        )
        for row in _records(product_rows)
    }
    run_id = f"sentiment_backfill_{uuid.uuid4().hex}"
    remaining_detail = detail_limit
    total_rule = 0
    total_llm = 0
    total_detail = 0
    total_failed = 0
    statuses: list[str] = []
    models: set[str] = set()

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(_text(row.get("item_key")), []).append(row)
    for index, (item_key, item_rows) in enumerate(grouped.items(), 1):
        group_analysis = [
            analysis_by_id[content_id]
            for content_id in (
                _text(row.get("content_id")) for row in item_rows
            )
            if content_id in analysis_by_id
        ]
        snapshot_id = f"{run_id}_{index}"
        current_detail_limit = remaining_detail
        sentiment_run = run_incremental_sentiment(
            item_rows,
            group_analysis,
            project_id=project_id,
            item_key=item_key,
            snapshot_id=snapshot_id,
            source_file="historical_sentiment_backfill",
            platform=_text(item_rows[0].get("platform")),
            product_title=titles.get(item_key, ""),
            enabled=True,
            provider=provider,
            config_path=config_path,
            model=model,
            batch_size=batch_size,
            detail_limit=current_detail_limit,
            full_llm=full_llm,
            client=client,
        )
        pipeline = sentiment_run["pipeline"]
        apply_sentiment_to_analysis(
            analysis_rows,
            pipeline.fast_rows,
            pipeline.detail_rows,
        )
        append_sentiment_sheets(
            sheets,
            sentiment_run,
            project_id=project_id,
            item_key=item_key,
            snapshot_id=snapshot_id,
        )
        summary = dict(sentiment_run["run_summary"])
        summary["update_id"] = f"{run_id}_{index}"
        sheets["sentiment_run_summary"] = _append(
            sheets["sentiment_run_summary"],
            [summary],
            "sentiment_run_summary",
        )
        total_rule += pipeline.rule_count
        total_llm += pipeline.llm_fast_count
        total_detail += pipeline.detail_count
        total_failed += pipeline.failed_count
        statuses.append(sentiment_run["status"])
        if sentiment_run["model"]:
            models.add(sentiment_run["model"])
        if remaining_detail is not None:
            remaining_detail = max(remaining_detail - pipeline.detail_count, 0)

    outside = analysis_frame[
        ~analysis_frame["project_id"].fillna("").astype(str).eq(project_id)
    ]
    sheets["analysis"] = normalize_frame(
        "analysis",
        pd.concat(
            [outside, pd.DataFrame(analysis_rows)],
            ignore_index=True,
        ),
    )
    rebuild_compatibility_sheets_from_frames(sheets, project_id)
    _touch_project(sheets, project_id)
    backup = write_sheets_atomic(workbook_path, sheets)
    status = (
        "success"
        if total_failed == 0
        else "partial"
        if total_rule + total_llm
        else "failed"
    )
    return {
        **preview,
        "result": "success" if status == "success" else "warning",
        "status": status,
        "rule_count": total_rule,
        "llm_count": total_llm,
        "detail_count": total_detail,
        "failed_count": total_failed,
        "model": ",".join(sorted(models)),
        "backup_path": str(backup or ""),
    }


def reanalyze_project(
    workbook_path: str,
    project_id: str,
    *,
    module: str = "ai_candidate",
    version: str = "ai_rules_v1.4",
    keywords_path: str | None = None,
    dry_run: bool = False,
) -> dict:
    if module != "ai_candidate":
        raise ValueError("当前 MVP 仅支持重新分析 ai_candidate 模块")
    sheets = load_sheets(workbook_path)
    _require_project(sheets, project_id)
    master = sheets["content_master"]
    subset = master[master["project_id"].fillna("").astype(str).eq(project_id)]
    rows = _records(subset)
    analysis_rows = analyze_new_contents(
        rows,
        project_id=project_id,
        keywords_path=keywords_path,
    )
    for row in analysis_rows:
        row["item_key"] = next(
            (_text(item.get("item_key")) for item in rows if item.get("content_id") == row["content_id"]),
            "",
        )
        row["analysis_version"] = version
    sentiment_fast = project_frame_records(
        sheets["sentiment_fast"],
        project_id,
    )
    sentiment_detail = project_frame_records(
        sheets["sentiment_detail"],
        project_id,
    )
    apply_sentiment_to_analysis(
        analysis_rows,
        sentiment_fast,
        sentiment_detail,
    )
    if dry_run:
        return {"project_id": project_id, "reanalyzed_count": len(analysis_rows), "dry_run": True}
    existing = sheets["analysis"]
    sheets["analysis"] = normalize_frame(
        "analysis",
        pd.concat(
            [
                existing[~existing["project_id"].fillna("").astype(str).eq(project_id)],
                pd.DataFrame(analysis_rows),
            ],
            ignore_index=True,
        ),
    )
    rebuild_compatibility_sheets_from_frames(sheets, project_id)
    _touch_project(sheets, project_id)
    backup = write_sheets_atomic(workbook_path, sheets)
    return {
        "project_id": project_id,
        "reanalyzed_count": len(analysis_rows),
        "dry_run": False,
        "backup_path": str(backup or ""),
    }


def rebuild_compatibility_sheets(
    workbook_path: str,
    project_id: str,
) -> None:
    sheets = load_sheets(workbook_path)
    rebuild_compatibility_sheets_from_frames(sheets, project_id)
    write_sheets_atomic(workbook_path, sheets)


def rebuild_compatibility_sheets_from_frames(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    master = sheets["content_master"]
    master = master[master["project_id"].fillna("").astype(str).eq(project_id)].copy()
    analysis = sheets["analysis"]
    analysis = analysis[analysis["project_id"].fillna("").astype(str).eq(project_id)].copy()
    if not master.empty and not analysis.empty:
        analysis_columns = [
            column for column in analysis.columns if column not in {"project_id", "item_key"}
        ]
        content = master.merge(
            analysis[analysis_columns],
            on="content_id",
            how="left",
            suffixes=("", "_analysis"),
        )
    else:
        content = master.copy()
    products = sheets["products"]
    products = products[products["project_id"].fillna("").astype(str).eq(project_id)]
    if not content.empty and not products.empty:
        content = content.merge(
            products[
                [
                    "item_key",
                    "brand_product_id",
                    "brand",
                    "model_name",
                    "product_title_current",
                    "shop_name_current",
                ]
            ],
            on="item_key",
            how="left",
        )
    if content.empty:
        content = pd.DataFrame()
    else:
        content["source_file"] = content["source_file_last"]
        content["product_title"] = content.get("product_title_current", "")
        content["shop_name"] = content.get("shop_name_current", "")
        content["product_id"] = content["platform_product_id"]
        content["record_type"] = content["content_role"].map(
            {"review": "review", "followup": "review", "question": "qa", "answer": "qa"}
        )
        content["review_time"] = content["content_time"]
        content["review_date"] = content["content_date"]
        content["content_hash"] = content["identity_key"]
        for column, default in (
            ("pre_purchase_decision", False),
            ("ai_candidate", False),
            ("ai_influence_level", ""),
            ("evidence_level", ""),
            ("matched_keywords", ""),
            ("match_score", 0),
        ):
            if column not in content:
                content[column] = default
            content[column] = content[column].where(content[column].notna(), default)
    sheets["content_all"] = content
    sheets["reviews_raw"] = (
        content[content["content_role"].isin(["review", "followup"])].copy()
        if not content.empty
        else pd.DataFrame()
    )
    sheets["qa_pairs_raw"] = (
        content[content["content_role"].isin(["question", "answer"])].copy()
        if not content.empty
        else pd.DataFrame()
    )
    sheets["ai_candidates"] = (
        content[content["ai_candidate"].map(_bool)].copy()
        if not content.empty
        else pd.DataFrame()
    )
    summary_input = _records(content) if not content.empty else []
    candidates = [row for row in summary_input if _bool(row.get("ai_candidate"))]
    summaries = build_summaries(summary_input, candidates)
    sheets["summary_by_product"] = pd.DataFrame(summaries["summary_by_product"])
    sheets["summary_by_keyword"] = pd.DataFrame(summaries["summary_by_keyword"])
    if candidates:
        levels = pd.DataFrame(candidates).groupby("evidence_level", dropna=False).size()
        sheets["summary_by_evidence_level"] = levels.rename("content_count").reset_index()
    else:
        sheets["summary_by_evidence_level"] = pd.DataFrame(
            columns=["evidence_level", "content_count"]
        )
    sheets.setdefault("errors", pd.DataFrame())
    sheets.setdefault("debug_samples", pd.DataFrame())


def _apply_master_update(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
    item_key: str,
    platform: str,
    product_id: str,
    snapshot_id: str,
    source_file: str,
    capture_time: str,
    comparison: dict,
    *,
    is_backfill: bool,
) -> None:
    frame = sheets["content_master"].copy()
    if not is_backfill and not frame.empty:
        item_mask = (
            frame["project_id"].fillna("").astype(str).eq(project_id)
            & frame["item_key"].fillna("").astype(str).eq(item_key)
        )
        frame.loc[item_mask, "is_active"] = False
    for match in comparison["existing"]:
        content_id = _text(match["master"]["content_id"])
        mask = frame["content_id"].fillna("").astype(str).eq(content_id)
        if not is_backfill:
            frame.loc[mask, "last_seen_snapshot_id"] = snapshot_id
            frame.loc[mask, "last_seen_at"] = capture_time
            frame.loc[mask, "source_file_last"] = source_file
            frame.loc[mask, "is_active"] = True
    new_rows = []
    for content in comparison["new"]:
        content_id = f"cnt_{uuid.uuid4().hex}"
        content["content_id"] = content_id
        new_rows.append(
            {
                "content_id": content_id,
                "project_id": project_id,
                "item_key": item_key,
                "platform": platform,
                "platform_product_id": product_id,
                **{column: content.get(column, "") for column in SHEET_COLUMNS["content_master"][5:16]},
                "first_seen_snapshot_id": snapshot_id,
                "first_seen_at": capture_time,
                "last_seen_snapshot_id": snapshot_id,
                "last_seen_at": capture_time,
                "identity_key": content.get("identity_key", ""),
                "strict_key": content.get("strict_key", ""),
                "composite_key": content.get("composite_key", ""),
                "text_key": content.get("text_key", ""),
                "identity_method": content.get("identity_method", ""),
                "identity_confidence": content.get("identity_confidence", ""),
                "is_active": not is_backfill,
                "source_file_first": source_file,
                "source_file_last": source_file,
            }
        )
    sheets["content_master"] = _append(frame, new_rows, "content_master")


def _append_review_queue(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
    item_key: str,
    snapshot_id: str,
    uncertain: list[dict],
) -> None:
    rows = [
        {
            "queue_id": f"queue_{uuid.uuid4().hex}",
            "project_id": project_id,
            "item_key": item_key,
            "snapshot_id": snapshot_id,
            "candidate_text": item["candidate"].get("content_text_clean", ""),
            "possible_existing_content_id": item["master"].get("content_id", ""),
            "match_reason": item["reason"],
            "similarity": 1.0,
            "recommended_action": "inspect",
            "resolved": False,
            "resolved_action": "",
        }
        for item in uncertain
    ]
    sheets["review_queue"] = _append(sheets["review_queue"], rows, "review_queue")


def _append_update_log(sheets: dict[str, pd.DataFrame], result: dict) -> None:
    row = {
        "update_id": result.get("update_id") or f"upd_{uuid.uuid4().hex}",
        "project_id": result["project_id"],
        "item_key": result["item_key"],
        "snapshot_id": result.get("snapshot_id", ""),
        "update_time": _now(),
        "extracted_count": result.get("extracted_count", 0),
        "new_count": result.get("new_count", 0),
        "existing_count": result.get("existing_count", 0),
        "uncertain_count": result.get("uncertain_count", 0),
        "overlap_length": result.get("overlap_length", 0),
        "analysis_new_count": result.get("analysis_new_count", result.get("new_count", 0)),
        "sentiment_target_count": result.get("sentiment_target_count", 0),
        "sentiment_rule_count": result.get("sentiment_rule_count", 0),
        "sentiment_llm_count": result.get("sentiment_llm_count", 0),
        "sentiment_detail_count": result.get("sentiment_detail_count", 0),
        "sentiment_failed_count": result.get("sentiment_failed_count", 0),
        "sentiment_status": result.get("sentiment_status", "disabled"),
        "sentiment_model": result.get("sentiment_model", ""),
        "sentiment_version": result.get("sentiment_version", ""),
        "sentiment_strategy": result.get(
            "sentiment_strategy",
            "full_llm",
        ),
        "result": result.get("result", "success"),
        "message": result.get("message", ""),
    }
    sheets["update_log"] = _append(sheets["update_log"], [row], "update_log")


def _latest_snapshot_contents(
    sheets: dict[str, pd.DataFrame],
    latest: dict | None,
) -> list[dict]:
    if not latest:
        return []
    frame = sheets["snapshot_contents"]
    subset = frame[
        frame["snapshot_id"].fillna("").astype(str).eq(_text(latest["snapshot_id"]))
    ].copy()
    if subset.empty:
        return []
    subset["_order"] = pd.to_numeric(subset["content_order"], errors="coerce")
    return _records(subset.sort_values("_order").drop(columns=["_order"]))


def _update_product(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
    item_key: str,
    *,
    title: str,
    shop: str,
    identity_confidence: str,
) -> None:
    products = sheets["products"]
    mask = (
        products["project_id"].fillna("").astype(str).eq(project_id)
        & products["item_key"].fillna("").astype(str).eq(item_key)
    )
    products.loc[mask, "product_title_current"] = title
    products.loc[mask, "shop_name_current"] = shop
    products.loc[mask, "last_updated_at"] = _now()
    products.loc[mask, "identity_confidence"] = identity_confidence
    sheets["products"] = products


def _touch_project(sheets: dict[str, pd.DataFrame], project_id: str) -> None:
    frame = sheets["project_info"]
    mask = frame["project_id"].fillna("").astype(str).eq(project_id)
    frame.loc[mask, "updated_at"] = _now()
    sheets["project_info"] = frame


def _require_project(sheets: dict[str, pd.DataFrame], project_id: str) -> None:
    projects = sheets["project_info"]["project_id"].fillna("").astype(str)
    if not projects.eq(project_id).any():
        raise ValueError(f"项目不存在：{project_id}")


def project_frame_records(
    frame: pd.DataFrame,
    project_id: str,
) -> list[dict]:
    if frame.empty:
        return []
    if "project_id" not in frame.columns:
        return _records(frame)
    subset = frame[
        frame["project_id"].fillna("").astype(str).eq(project_id)
    ]
    return _records(subset)


def _normalize_datetime(value: str) -> str:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError(f"无法识别时间：{value}")
    return timestamp.to_pydatetime().replace(microsecond=0).isoformat(sep=" ")


def _snapshot_id(platform: str, product_id: str, capture_time: str, file_hash: str) -> str:
    stamp = pd.Timestamp(capture_time).strftime("%Y%m%dT%H%M%S")
    return f"{platform}_{product_id}_{stamp}_{file_hash[:8]}"


def _result_message(status: str, comparison: dict, is_backfill: bool) -> str:
    parts = []
    if is_backfill:
        parts.append("历史回填：不会覆盖最新快照状态")
    if status == "fallback":
        parts.append("未找到可靠连续重叠边界，已使用主表集合比对")
    elif status == "first_import":
        parts.append("首次导入")
    else:
        parts.append("已找到连续重叠边界")
    if comparison["uncertain"]:
        parts.append(f"{len(comparison['uncertain'])} 条低置信记录进入 review_queue")
    return "；".join(parts)
