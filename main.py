from __future__ import annotations

import argparse
import re
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from tqdm import tqdm

from analysis.ai_keyword_matcher import load_keywords
from analysis.evidence_rules import analyze_ai_related
from analysis.summary import build_summaries
from extractor.content_builder import build_content_all
from extractor.html_loader import iter_html_files, load_html
from extractor.platform_detect import detect_platform
from extractor.product_meta import extract_product_meta
from extractor.reviews import parse_reviews
from extractor.taobao_qa import parse_taobao_qa
from llm.comment_analysis_service import LLMBatchResult, LLMCommentAnalysisService
from llm.deepseek_client import DeepSeekClient
from llm.prompt_builder import PromptBuilder
from llm.provider_config import load_provider_config
from llm.validator import LLMResultValidator
from sentiment_pipeline import SentimentPipelineResult, process_sentiment_for_comments, select_sentiment_targets
from utils.excel_writer import write_excel
from utils.logger import setup_logger

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = PROJECT_DIR / "input_html"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "output"
LLM_TARGET_CONTENT_COUNT = 500
LLM_TARGET_SECONDS = 120


def build_timestamped_output_path(
    output_path: str | Path,
    run_name: str = "",
    now: datetime | None = None,
) -> Path:
    """Build an output workbook name from a run name and timestamp."""
    path = Path(output_path).expanduser().resolve()
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    output_dir = path.parent if path.suffix.casefold() == ".xlsx" else path
    fallback = path.stem if path.suffix.casefold() == ".xlsx" else "未命名运行"
    safe_name = sanitize_run_name(run_name or fallback)
    return output_dir / f"{safe_name}_{timestamp}.xlsx"


def sanitize_run_name(value: str, max_length: int = 80) -> str:
    """Return a Windows-safe filename stem for a human-readable run name."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip()
    name = re.sub(r"\s+", " ", name).strip(" ._")
    if not name:
        name = "未命名运行"
    return name[:max_length].strip(" ._") or "未命名运行"


def infer_run_name_from_first_file(file_path: str | Path) -> str:
    """Use the first input file's product title as the default run name."""
    try:
        html_text = load_html(file_path)
        platform = detect_platform(html_text, file_path)
        soup = BeautifulSoup(html_text, "lxml")
        meta = extract_product_meta(html_text, soup, file_path, platform)
    except Exception:
        return Path(file_path).stem
    return meta.get("product_title") or Path(file_path).stem


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="离线提取 SingleFile 电商页面中的评论、问大家和 AI 相关候选"
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT_DIR),
        help="包含 HTML 文件的输入目录，默认 ./input_html",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help="输出目录，或兼容旧写法传入 .xlsx 路径；运行时自动按运行名和时间戳命名",
    )
    parser.add_argument(
        "--run-name",
        default="",
        help="本次运行名称；默认取第一个输入文件的商品标题",
    )
    parser.add_argument(
        "--keywords",
        default=str(PROJECT_DIR / "config" / "ai_keywords.yaml"),
        help="AI 关键词 YAML 文件",
    )
    parser.add_argument("--recursive", action="store_true", help="递归读取子目录")
    parser.add_argument(
        "--debug",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="输出低置信度 debug 样本",
    )
    parser.add_argument("--max-files", type=int, help="最多处理文件数")
    parser.add_argument(
        "--llm-analyze",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Run legacy detailed LLM evidence analysis. Disabled by default; use the fast sentiment pipeline for normal runs.",
    )
    parser.add_argument(
        "--llm-limit",
        default=None,
        help="Maximum content rows to analyze, or all. Defaults to all content rows.",
    )
    parser.add_argument(
        "--llm-model",
        default="",
        help="Optional LLM model override. Defaults to the selected provider config.",
    )
    parser.add_argument(
        "--llm-provider",
        default="deepseek",
        help="LLM provider name from the provider config.",
    )
    parser.add_argument(
        "--llm-config",
        default=str(PROJECT_DIR / "config" / "llm_providers.local.json"),
        help="Local provider config file. This file can point each provider at its own key file.",
    )
    parser.add_argument(
        "--llm-api-key-file",
        default=None,
        help="Optional API key file override for the selected provider.",
    )
    parser.add_argument(
        "--prompt-version",
        default="v1",
        help="LLM prompt version.",
    )
    parser.add_argument(
        "--llm-only-new",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reserved safety flag. The offline Excel workflow only analyzes this run's rows.",
    )
    parser.add_argument(
        "--llm-include-updated",
        action="store_true",
        help="Reserved for the database workflow; the offline Excel workflow has no updated rows.",
    )
    parser.add_argument(
        "--llm-skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip duplicate input_hash values within this run.",
    )
    parser.add_argument(
        "--llm-dry-run",
        action="store_true",
        help="Count target content rows without calling DeepSeek.",
    )
    parser.add_argument(
        "--enable-sentiment",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run fast sentiment labeling plus limited high-value detail analysis.",
    )
    parser.add_argument(
        "--sentiment-only",
        action="store_true",
        help="Reserved for database workflow. In this offline workflow, sentiment runs after HTML extraction.",
    )
    parser.add_argument(
        "--sentiment-limit",
        default="all",
        help="Maximum review rows to process in the fast sentiment pipeline, or all. Defaults to all.",
    )
    parser.add_argument(
        "--detail-limit",
        default=50,
        help="Maximum high-value rows to send to sentiment detail analysis, or all.",
    )
    parser.add_argument(
        "--sentiment-batch-size",
        type=int,
        default=50,
        help="Rows per fast sentiment JSONL request.",
    )
    parser.add_argument(
        "--detail-batch-size",
        type=int,
        default=10,
        help="Rows per detail sentiment JSONL request.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extraction and local sentiment rules without calling sentiment LLM.",
    )
    parser.add_argument(
        "--force-reprocess-sentiment",
        action="store_true",
        help="Reserved for database workflow. Offline runs only process the current workbook rows.",
    )
    parser.add_argument(
        "--llm-timeout",
        type=int,
        default=None,
        help="Override per-request LLM timeout in seconds. Defaults to the selected provider/model config.",
    )
    parser.add_argument(
        "--llm-batch-size",
        type=int,
        default=None,
        help=(
            "Override content rows per LLM request. "
            "Default comes from the selected provider/model capacity config."
        ),
    )
    parser.add_argument(
        "--llm-retry-delays",
        default="1,3",
        help="Comma-separated retry sleep seconds. Defaults to two retries after 1 and 3 seconds.",
    )
    parser.add_argument(
        "--llm-backfill",
        action="store_true",
        help="Reserved for an explicit database backfill; never scans history in this offline workflow.",
    )
    return parser.parse_args()


def select_llm_review_targets(contents: list[dict], limit: int | None = None) -> list[dict]:
    """Return all analyzable content rows from this run, preserving workbook order."""
    targets = [row for row in contents if str(row.get("content_text_clean") or "").strip()]
    if limit is not None:
        targets = targets[: max(limit, 0)]
    return targets


def parse_retry_delays(value: str) -> tuple[int, ...]:
    delays: list[int] = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        delay = int(item)
        if delay < 0:
            raise ValueError("LLM retry delays must be non-negative")
        delays.append(delay)
    return tuple(delays)


def parse_limit(value: object, name: str) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() == "all":
        return None
    limit = int(text)
    if limit < 0:
        raise ValueError(f"{name} must be non-negative or all")
    return limit


def resolve_llm_batch_size(args: argparse.Namespace, provider_config) -> tuple[int, str]:
    if args.llm_batch_size is not None:
        return max(int(args.llm_batch_size), 1), "command line override: --llm-batch-size"
    batch_size = max(int(provider_config.default_batch_size or 1), 1)
    note = provider_config.capacity_note or (
        f"provider/model capacity config for target: "
        f"{provider_config.target_content_count} rows in {provider_config.target_total_seconds}s end-to-end"
    )
    return batch_size, note


def resolve_llm_timeout(args: argparse.Namespace, provider_config) -> int:
    if args.llm_timeout is not None:
        return max(int(args.llm_timeout), 1)
    return max(int(provider_config.timeout_seconds or 1), 1)


def run_llm_analysis(args: argparse.Namespace, contents: list[dict], logger) -> LLMBatchResult:
    llm_limit = parse_limit(args.llm_limit, "--llm-limit")
    targets = select_llm_review_targets(contents, llm_limit)
    logger.info("LLM target content rows: %d", len(targets))
    if args.llm_dry_run:
        logger.info("LLM dry run: DeepSeek API will not be called")
        return LLMBatchResult(total_count=len(targets), skipped_count=len(targets))

    provider_config = load_provider_config(
        config_path=args.llm_config,
        provider=args.llm_provider,
        api_key_file_override=args.llm_api_key_file,
    )
    if provider_config.provider != "deepseek":
        raise ValueError(f"Unsupported LLM provider for now: {provider_config.provider}")
    batch_size, batch_size_source = resolve_llm_batch_size(args, provider_config)
    timeout_seconds = resolve_llm_timeout(args, provider_config)
    logger.info("LLM batch size: %d | source: %s", batch_size, batch_size_source)
    logger.info("LLM request timeout: %d seconds", timeout_seconds)

    api_key_file = provider_config.api_key_file
    if api_key_file and not Path(api_key_file).expanduser().is_absolute():
        api_key_file = str(PROJECT_DIR / api_key_file)
    model_name = args.llm_model or provider_config.default_model or "DeepSeek-V4-Flash-0731"

    service = LLMCommentAnalysisService(
        deepseek_client=DeepSeekClient(
            api_key_file=api_key_file,
            base_url=provider_config.base_url or None,
            default_model=model_name,
            timeout=timeout_seconds,
        ),
        prompt_builder=PromptBuilder(prompt_version=args.prompt_version),
        validator=LLMResultValidator(),
        retry_delays=parse_retry_delays(args.llm_retry_delays),
    )
    progress = tqdm(total=len(targets), desc="LLM 情绪判断", unit="item")

    def update_progress(batch_result: LLMBatchResult, _comment: dict) -> None:
        progress.update(1)
        progress.set_postfix(
            ok=batch_result.success_count,
            fail=batch_result.failed_count,
            skip=batch_result.skipped_count,
        )

    try:
        return service.analyze_comments(
            comments=targets,
            model_name=model_name,
            prompt_version=args.prompt_version,
            skip_existing=args.llm_skip_existing,
            progress_callback=update_progress,
            batch_size=batch_size,
        )
    finally:
        progress.close()


def run_sentiment_analysis(args: argparse.Namespace, contents: list[dict], logger) -> SentimentPipelineResult:
    sentiment_limit = parse_limit(args.sentiment_limit, "--sentiment-limit")
    detail_limit = parse_limit(args.detail_limit, "--detail-limit")
    targets = select_sentiment_targets(contents, sentiment_limit)
    logger.info("Sentiment target review rows: %d", len(targets))
    if args.dry_run:
        logger.info("Sentiment dry run: local rules only; DeepSeek API will not be called")
        return process_sentiment_for_comments(
            comments=targets,
            client=None,
            model_name="",
            batch_size=args.sentiment_batch_size,
            detail_batch_size=args.detail_batch_size,
            detail_limit=detail_limit,
            dry_run=True,
        )

    provider_config = load_provider_config(
        config_path=args.llm_config,
        provider=args.llm_provider,
        api_key_file_override=args.llm_api_key_file,
    )
    if provider_config.provider != "deepseek":
        raise ValueError(f"Unsupported LLM provider for now: {provider_config.provider}")
    timeout_seconds = max(int(args.llm_timeout or provider_config.timeout_seconds or 45), 1)
    api_key_file = provider_config.api_key_file
    if api_key_file and not Path(api_key_file).expanduser().is_absolute():
        api_key_file = str(PROJECT_DIR / api_key_file)
    model_name = args.llm_model or provider_config.default_model or "DeepSeek-V4-Flash-0731"
    logger.info(
        "Sentiment fast batch=%d detail batch=%d detail limit=%s timeout=%d",
        args.sentiment_batch_size,
        args.detail_batch_size,
        detail_limit if detail_limit is not None else "all",
        timeout_seconds,
    )
    progress = tqdm(total=len(targets), desc="情感快判", unit="item")

    try:
        result = process_sentiment_for_comments(
            comments=targets,
            client=DeepSeekClient(
                api_key_file=api_key_file,
                base_url=provider_config.base_url or None,
                default_model=model_name,
                timeout=timeout_seconds,
            ),
            model_name=model_name,
            batch_size=max(int(args.sentiment_batch_size or 1), 1),
            detail_batch_size=max(int(args.detail_batch_size or 1), 1),
            detail_limit=detail_limit,
            dry_run=False,
        )
        progress.update(len(targets))
        return result
    finally:
        progress.close()


def main() -> int:
    args = parse_args()
    output_arg = Path(args.output).expanduser().resolve()
    output_dir = output_arg.parent if output_arg.suffix.casefold() == ".xlsx" else output_arg
    logger = setup_logger(str(output_dir / "run.log"))
    keywords = load_keywords(args.keywords)
    files = iter_html_files(args.input, args.recursive)
    if args.max_files is not None:
        files = files[: max(args.max_files, 0)]

    run_name = args.run_name.strip()
    if not run_name and files:
        run_name = infer_run_name_from_first_file(files[0])
    output_path = build_timestamped_output_path(output_dir, run_name)

    logger.info("开始处理文件数量: %d", len(files))
    logger.info("本次运行名称: %s", sanitize_run_name(run_name))
    all_reviews: list[dict] = []
    all_qa: list[dict] = []
    all_debug: list[dict] = []
    errors: list[dict] = []
    contents: list[dict] = []

    for file_path in tqdm(files, desc="处理 HTML", unit="file"):
        platform = "unknown"
        try:
            logger.info("当前处理文件: %s", file_path)
            html_text = load_html(file_path)
            platform = detect_platform(html_text, file_path)
            soup = BeautifulSoup(html_text, "lxml")
            meta = extract_product_meta(html_text, soup, file_path, platform)
            debug_target = all_debug if args.debug else None
            qa_pairs = parse_taobao_qa(html_text, soup, meta, debug_target)
            reviews = parse_reviews(html_text, soup, meta)
            raw_content = build_content_all(reviews, qa_pairs)
            analyzed = [
                analyze_ai_related(record, keywords) for record in raw_content
            ]
            contents.extend(analyzed)
            all_reviews.extend(reviews)
            all_qa.extend(qa_pairs)
            logger.info(
                "平台=%s | 商品=%s | 评论=%d | 问大家=%d | 内容=%d | AI候选=%d",
                platform,
                meta.get("product_title", ""),
                len(reviews),
                len(qa_pairs),
                len(analyzed),
                sum(row["ai_candidate"] for row in analyzed),
            )
        except Exception as exc:  # Keep the batch moving after one bad file.
            errors.append(
                {
                    "source_file": file_path,
                    "platform": platform,
                    "error_stage": "process_file",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            logger.exception("处理失败: %s", file_path)

    # Reassign IDs after all files and sort candidates as specified.
    for index, row in enumerate(contents, 1):
        row["content_id"] = index
        row.pop("_specific_ai_source_hit", None)
        row.pop("_generic_ai_source_hit", None)
        row.pop("_research_inferred_hit", None)
        row.pop("_not_pre_purchase_reason", None)
    candidates = [row for row in contents if row.get("ai_candidate")]
    level_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    candidates.sort(
        key=lambda row: (
            level_order.get(str(row.get("evidence_level", "")), 9),
            -int(row.get("match_score", 0)),
            row.get("source_file", ""),
        )
    )
    summaries = build_summaries(contents, candidates)
    sentiment_result = SentimentPipelineResult()
    sentiment_status = "disabled"
    sentiment_message = "Fast sentiment pipeline is enabled by default; run with --no-enable-sentiment to skip it."
    llm_result = LLMBatchResult(total_count=0)
    llm_target_count = len(select_llm_review_targets(contents, parse_limit(args.llm_limit, "--llm-limit")))
    llm_status = "disabled"
    llm_message = "LLM analysis is enabled by default; run with --no-llm-analyze to skip it."
    llm_elapsed_seconds = 0.0
    workbook_write_seconds = 0.0
    if args.sentiment_only:
        logger.warning("sentiment-only is reserved for the database workflow; offline mode still extracts current HTML rows.")
    if args.force_reprocess_sentiment:
        logger.warning("force-reprocess-sentiment is reserved for the database workflow; offline mode always processes current rows.")
    if args.enable_sentiment:
        try:
            sentiment_status = "running"
            sentiment_result = run_sentiment_analysis(args, contents, logger)
            sentiment_status = "success" if sentiment_result.failed_count == 0 else "partial"
            sentiment_message = (
                f"total={sentiment_result.total_count}; rule={sentiment_result.rule_count}; "
                f"llm_fast={sentiment_result.llm_fast_count}; detail={sentiment_result.detail_count}; "
                f"failed={sentiment_result.failed_count}"
            )
            logger.info("Sentiment result: %s", sentiment_message)
        except Exception as exc:
            errors.append(
                {
                    "source_file": "",
                    "platform": "",
                    "error_stage": "sentiment_analysis",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            sentiment_status = "failed_to_start"
            sentiment_message = str(exc)
            logger.exception("Sentiment analysis failed to start")
    if args.llm_backfill:
        logger.warning(
            "LLM backfill requires a database repository and is not supported by this offline Excel workflow."
        )
    if args.llm_analyze:
        try:
            llm_status = "running"
            llm_message = ""
            llm_started_at = time.perf_counter()
            llm_result = run_llm_analysis(args, contents, logger)
            llm_elapsed_seconds = round(time.perf_counter() - llm_started_at, 3)
            llm_status = "success" if llm_result.failed_count == 0 else "partial"
            llm_message = (
                f"success={llm_result.success_count}; failed={llm_result.failed_count}; "
                f"skipped={llm_result.skipped_count}"
            )
            logger.info(
                "LLM totals=%d | success=%d | failed=%d | skipped=%d",
                llm_result.total_count,
                llm_result.success_count,
                llm_result.failed_count,
                llm_result.skipped_count,
            )
            if llm_result.failure_rows:
                error_types = Counter(str(row.get("error_type", "")) for row in llm_result.failure_rows)
                error_messages = Counter(str(row.get("error_message", "")) for row in llm_result.failure_rows)
                logger.warning("LLM failure types: %s", dict(error_types.most_common(5)))
                logger.warning("LLM failure messages: %s", dict(error_messages.most_common(5)))
            if llm_result.request_timing_rows:
                timing_totals = {}
                for field in (
                    "total_seconds",
                    "payload_build_seconds",
                    "http_open_seconds",
                    "response_read_seconds",
                    "json_parse_seconds",
                ):
                    timing_totals[field] = round(
                        sum(
                            float(row.get(field) or 0)
                            for row in llm_result.request_timing_rows
                        ),
                        3,
                    )
                logger.info("LLM request timing totals: %s", timing_totals)
        except Exception as exc:
            errors.append(
                {
                    "source_file": "",
                    "platform": "",
                    "error_stage": "llm_analysis",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            llm_status = "failed_to_start"
            llm_message = str(exc)
            logger.exception("LLM analysis failed to start")
    try:
        summary_provider_config = load_provider_config(
            config_path=args.llm_config,
            provider=args.llm_provider,
            api_key_file_override=args.llm_api_key_file,
        )
        summary_batch_size, summary_batch_source = resolve_llm_batch_size(args, summary_provider_config)
        summary_model = args.llm_model or summary_provider_config.default_model
        summary_target_count = summary_provider_config.target_content_count
        summary_target_seconds = summary_provider_config.target_total_seconds
        summary_timeout_seconds = resolve_llm_timeout(args, summary_provider_config)
    except Exception:
        summary_batch_size = max(int(args.llm_batch_size or 1), 1)
        summary_batch_source = "unavailable: provider config could not be loaded"
        summary_model = args.llm_model or ""
        summary_target_count = LLM_TARGET_CONTENT_COUNT
        summary_target_seconds = LLM_TARGET_SECONDS
        summary_timeout_seconds = max(int(args.llm_timeout or 90), 1)

    llm_run_summary = [
        {
            "enabled": bool(args.llm_analyze),
            "status": llm_status,
            "message": llm_message,
            "provider": args.llm_provider,
            "model": summary_model,
            "prompt_version": args.prompt_version,
            "target_review_count": llm_target_count,
            "total_count": llm_result.total_count,
            "success_count": llm_result.success_count,
            "failed_count": llm_result.failed_count,
            "skipped_count": llm_result.skipped_count,
            "config_path": args.llm_config,
            "api_key_file_override": args.llm_api_key_file or "",
            "dry_run": bool(args.llm_dry_run),
            "batch_size": summary_batch_size,
            "batch_size_source": summary_batch_source,
            "target_content_count": summary_target_count,
            "target_total_seconds": summary_target_seconds,
            "timeout_seconds": summary_timeout_seconds,
            "retry_delays": args.llm_retry_delays,
            "llm_elapsed_seconds": llm_elapsed_seconds,
        }
    ]
    sheets = {
        "ai_candidates": candidates,
        "content_all": contents,
        "qa_pairs_raw": all_qa,
        "reviews_raw": all_reviews,
        **summaries,
        "sentiment_run_summary": [
            {
                "enabled": bool(args.enable_sentiment),
                "status": sentiment_status,
                "message": sentiment_message,
                "target_review_count": sentiment_result.total_count,
                "rule_count": sentiment_result.rule_count,
                "llm_fast_count": sentiment_result.llm_fast_count,
                "detail_count": sentiment_result.detail_count,
                "failed_count": sentiment_result.failed_count,
                "sentiment_limit": args.sentiment_limit,
                "detail_limit": args.detail_limit,
                "sentiment_batch_size": args.sentiment_batch_size,
                "detail_batch_size": args.detail_batch_size,
                "dry_run": bool(args.dry_run),
                "elapsed_seconds": sentiment_result.elapsed_seconds,
            }
        ],
        "sentiment_fast": sentiment_result.fast_rows,
        "sentiment_detail": sentiment_result.detail_rows,
        "sentiment_failures": sentiment_result.failure_rows,
        "sentiment_timings": sentiment_result.timing_rows,
        "sentiment_summary": sentiment_result.summary_rows,
        "llm_run_summary": llm_run_summary,
        "llm_review_analysis": llm_result.analysis_rows,
        "llm_praise_items": llm_result.praise_rows,
        "llm_complaint_items": llm_result.complaint_rows,
        "llm_failures": llm_result.failure_rows,
        "llm_request_timings": llm_result.request_timing_rows,
        "errors": errors,
        "debug_samples": all_debug if args.debug else [],
    }
    workbook_started_at = time.perf_counter()
    write_excel(str(output_path), sheets)
    workbook_write_seconds = round(time.perf_counter() - workbook_started_at, 3)
    logger.info("Workbook write seconds: %.3f", workbook_write_seconds)

    levels = {
        level: sum(row.get("evidence_level") == level for row in candidates)
        for level in ("A", "B", "C")
    }
    logger.info(
        "content_all=%d | AI候选=%d | A=%d B=%d C=%d | 错误文件=%d",
        len(contents),
        len(candidates),
        levels["A"],
        levels["B"],
        levels["C"],
        len(errors),
    )
    logger.info("输出文件路径: %s", output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
