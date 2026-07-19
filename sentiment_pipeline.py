from __future__ import annotations

import time
from dataclasses import dataclass, field

from sentiment_codes import COMPLAINT_CODES, PRAISE_CODES, SENTIMENT_LABELS
from sentiment_llm_detail import DetailSentimentLLM, should_detail_analyze
from sentiment_llm_fast import FastSentimentLLM
from sentiment_rules import try_rule_sentiment


@dataclass
class SentimentPipelineResult:
    total_count: int = 0
    rule_count: int = 0
    llm_fast_count: int = 0
    detail_count: int = 0
    failed_count: int = 0
    elapsed_seconds: float = 0.0
    fast_rows: list[dict] = field(default_factory=list)
    detail_rows: list[dict] = field(default_factory=list)
    failure_rows: list[dict] = field(default_factory=list)
    timing_rows: list[dict] = field(default_factory=list)
    summary_rows: list[dict] = field(default_factory=list)


def select_sentiment_targets(contents: list[dict], limit: int | None = None) -> list[dict]:
    targets = [
        row
        for row in contents
        if row.get("content_role") in {"review", "followup"}
        and str(row.get("content_text_clean") or "").strip()
    ]
    if limit is not None:
        targets = targets[: max(limit, 0)]
    return targets


def process_sentiment_for_comments(
    comments: list[dict],
    client,
    model_name: str,
    batch_size: int = 50,
    detail_batch_size: int = 10,
    detail_limit: int | None = 50,
    dry_run: bool = False,
) -> SentimentPipelineResult:
    started_at = time.perf_counter()
    result = SentimentPipelineResult(total_count=len(comments))

    rule_rows = []
    llm_needed = []
    for comment in comments:
        rule_result = try_rule_sentiment(comment)
        if rule_result:
            rule_rows.append(_row_from_fast_result(comment, rule_result))
        else:
            llm_needed.append(comment)
    result.rule_count = len(rule_rows)
    result.fast_rows.extend(rule_rows)

    if dry_run:
        result.summary_rows = _build_summary_rows(result)
        result.elapsed_seconds = round(time.perf_counter() - started_at, 3)
        return result

    fast_llm = FastSentimentLLM(client=client, model_name=model_name)
    fast_llm_result = fast_llm.analyze(llm_needed, batch_size=batch_size)
    result.fast_rows.extend(fast_llm_result.rows)
    result.failure_rows.extend(_with_stage(row, "sentiment_fast") for row in fast_llm_result.failures)
    result.timing_rows.extend(fast_llm_result.timings)
    result.llm_fast_count = len(fast_llm_result.rows)

    fast_rows_by_id = {str(row.get("content_id")): row for row in result.fast_rows}
    detail_candidates = [
        comment
        for comment in comments
        if str(comment.get("content_id")) in fast_rows_by_id
        and should_detail_analyze(comment, fast_rows_by_id[str(comment.get("content_id"))])
    ]
    if detail_limit is not None:
        detail_candidates = detail_candidates[: max(detail_limit, 0)]

    detail_llm = DetailSentimentLLM(client=client, model_name=model_name)
    detail_result = detail_llm.analyze(detail_candidates, fast_rows_by_id, batch_size=detail_batch_size)
    result.detail_rows.extend(detail_result.rows)
    result.failure_rows.extend(_with_stage(row, "sentiment_detail") for row in detail_result.failures)
    result.timing_rows.extend(detail_result.timings)
    result.detail_count = len(detail_result.rows)
    result.failed_count = len(result.failure_rows)
    result.summary_rows = _build_summary_rows(result)
    result.elapsed_seconds = round(time.perf_counter() - started_at, 3)
    return result


def _row_from_fast_result(comment: dict, fast: dict) -> dict:
    label = fast["s"]
    praise = fast["p"]
    complaint = fast["n"]
    return {
        "content_id": comment.get("content_id", ""),
        "content_hash": comment.get("content_hash", ""),
        "source_file": comment.get("source_file", ""),
        "platform": comment.get("platform", ""),
        "product_title": comment.get("product_title", ""),
        "sku": comment.get("sku", ""),
        "content_text_clean": comment.get("content_text_clean", ""),
        "sentiment_label": label,
        "sentiment_label_cn": SENTIMENT_LABELS.get(label, ""),
        "sentiment_score": fast["sc"],
        "praise_code": praise,
        "praise_cn": PRAISE_CODES.get(praise, ""),
        "complaint_code": complaint,
        "complaint_cn": COMPLAINT_CODES.get(complaint, ""),
        "sentiment_confidence": fast["c"],
        "sentiment_source": fast.get("source", ""),
    }


def _build_summary_rows(result: SentimentPipelineResult) -> list[dict]:
    rows = [
        {"metric": "total_count", "value": result.total_count},
        {"metric": "rule_count", "value": result.rule_count},
        {"metric": "llm_fast_count", "value": result.llm_fast_count},
        {"metric": "detail_count", "value": result.detail_count},
        {"metric": "failed_count", "value": len(result.failure_rows)},
        {"metric": "elapsed_seconds", "value": result.elapsed_seconds},
    ]
    for label, label_cn in SENTIMENT_LABELS.items():
        rows.append(
            {
                "metric": f"sentiment_{label}",
                "label": label_cn,
                "value": sum(row.get("sentiment_label") == label for row in result.fast_rows),
            }
        )
    return rows


def _with_stage(row: dict, stage: str) -> dict:
    return {**row, "stage": stage}
