from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from llm import schema
from llm.hash_utils import build_input_hash
from llm.prompt_builder import PromptBuilder
from llm.validator import LLMResultValidator


class LLMValidationError(ValueError):
    def __init__(self, message: str, raw_content: str):
        super().__init__(message)
        self.raw_content = raw_content


@dataclass
class LLMBatchResult:
    total_count: int
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    failed_comment_ids: list[str] = field(default_factory=list)
    analysis_rows: list[dict] = field(default_factory=list)
    praise_rows: list[dict] = field(default_factory=list)
    complaint_rows: list[dict] = field(default_factory=list)
    failure_rows: list[dict] = field(default_factory=list)
    request_timing_rows: list[dict] = field(default_factory=list)


class LLMCommentAnalysisService:
    def __init__(
        self,
        deepseek_client,
        prompt_builder: PromptBuilder,
        validator: LLMResultValidator,
        retry_delays: tuple[int, ...] = (2, 5, 10),
    ):
        self.deepseek_client = deepseek_client
        self.prompt_builder = prompt_builder
        self.validator = validator
        self.retry_delays = retry_delays

    def analyze_comments(
        self,
        comments: list[dict],
        model_name: str,
        prompt_version: str,
        skip_existing: bool = True,
        progress_callback: Callable[[LLMBatchResult, dict], None] | None = None,
        batch_size: int = 1,
    ) -> LLMBatchResult:
        result = LLMBatchResult(total_count=len(comments))
        seen_input_hashes: set[str] = set()
        batch: list[tuple[dict, str]] = []

        def flush_batch() -> None:
            if not batch:
                return
            current = list(batch)
            batch.clear()
            if batch_size <= 1:
                for comment, input_hash in current:
                    self._analyze_single_comment(
                        result,
                        comment,
                        model_name,
                        prompt_version,
                        input_hash,
                        progress_callback,
                    )
                return
            self._analyze_comment_batch(
                result,
                current,
                model_name,
                prompt_version,
                progress_callback,
            )

        for comment in comments:
            comment_id = str(comment.get("content_hash") or comment.get("content_id") or "")
            input_hash = build_input_hash(comment, prompt_version)
            if skip_existing and input_hash in seen_input_hashes:
                result.skipped_count += 1
                if progress_callback:
                    progress_callback(result, comment)
                continue
            seen_input_hashes.add(input_hash)

            original_text = str(comment.get("content_text_clean") or comment.get("review_text_clean") or "")
            if not original_text.strip():
                self._record_failure(
                    result,
                    comment,
                    model_name,
                    prompt_version,
                    input_hash,
                    "ValueError",
                    "empty review text",
                )
                result.failed_comment_ids.append(comment_id)
                if progress_callback:
                    progress_callback(result, comment)
                continue

            batch.append((comment, input_hash))
            if len(batch) >= max(batch_size, 1):
                flush_batch()

        flush_batch()
        return result

    def _analyze_single_comment(
        self,
        result: LLMBatchResult,
        comment: dict,
        model_name: str,
        prompt_version: str,
        input_hash: str,
        progress_callback: Callable[[LLMBatchResult, dict], None] | None = None,
    ) -> None:
        raw_content = None
        comment_id = str(comment.get("content_hash") or comment.get("content_id") or "")
        original_text = str(comment.get("content_text_clean") or comment.get("review_text_clean") or "")
        try:
            parsed, usage, raw_content = self._call_with_retry(
                result,
                comment,
                model_name,
                prompt_version,
                original_text,
            )
            self._append_success_rows(
                result,
                comment,
                model_name,
                prompt_version,
                input_hash,
                parsed,
                usage,
                raw_content,
            )
        except Exception as exc:
            if isinstance(exc, LLMValidationError):
                raw_content = exc.raw_content
            self._record_failure(
                result,
                comment,
                model_name,
                prompt_version,
                input_hash,
                type(exc).__name__,
                str(exc),
                raw_content,
            )
            result.failed_comment_ids.append(comment_id)
        finally:
            if progress_callback:
                progress_callback(result, comment)

    def _analyze_comment_batch(
        self,
        result: LLMBatchResult,
        batch: list[tuple[dict, str]],
        model_name: str,
        prompt_version: str,
        progress_callback: Callable[[LLMBatchResult, dict], None] | None = None,
    ) -> None:
        comments = [comment for comment, _input_hash in batch]
        try:
            parsed_items, usage, raw_content = self._call_batch_with_retry(
                result,
                comments,
                model_name,
                prompt_version,
            )
        except Exception as exc:
            if len(batch) > 1:
                midpoint = len(batch) // 2
                self._analyze_comment_batch(
                    result,
                    batch[:midpoint],
                    model_name,
                    prompt_version,
                    progress_callback,
                )
                self._analyze_comment_batch(
                    result,
                    batch[midpoint:],
                    model_name,
                    prompt_version,
                    progress_callback,
                )
                return
            for comment, input_hash in batch:
                self._record_failure(
                    result,
                    comment,
                    model_name,
                    prompt_version,
                    input_hash,
                    type(exc).__name__,
                    str(exc),
                    getattr(exc, "raw_content", None),
                )
                result.failed_comment_ids.append(str(comment.get("content_hash") or comment.get("content_id") or ""))
                if progress_callback:
                    progress_callback(result, comment)
            return

        for (comment, input_hash), parsed in zip(batch, parsed_items):
            original_text = str(comment.get("content_text_clean") or comment.get("review_text_clean") or "")
            sanitize_llm_result(parsed, original_text)
            validation = self.validator.validate(parsed, original_text)
            if validation.valid:
                derive_sentiment_fields(parsed)
                self._append_success_rows(
                    result,
                    comment,
                    model_name,
                    prompt_version,
                    input_hash,
                    parsed,
                    usage,
                    raw_content,
                )
            else:
                self._analyze_single_comment(
                    result,
                    comment,
                    model_name,
                    prompt_version,
                    input_hash,
                    progress_callback=None,
                )
            if progress_callback:
                progress_callback(result, comment)

    def _call_with_retry(
        self,
        result: LLMBatchResult,
        comment: dict,
        model_name: str,
        prompt_version: str,
        original_text: str,
    ) -> tuple[dict, dict | None, str]:
        system_prompt = self.prompt_builder.build_system_prompt()
        user_prompt = self.prompt_builder.build_user_prompt(comment)
        last_error: Exception | None = None
        attempts = len(self.retry_delays) + 1
        for attempt in range(attempts):
            try:
                parsed, usage, raw_content = self.deepseek_client.chat_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=model_name,
                )
                self._record_request_timing(
                    result,
                    "single",
                    model_name,
                    prompt_version,
                    1,
                    attempt + 1,
                    "api_ok",
                    [comment],
                )
                sanitize_llm_result(parsed, original_text)
                validation = self.validator.validate(parsed, original_text)
                if not validation.valid:
                    raise LLMValidationError(validation.error_message, raw_content)
                derive_sentiment_fields(parsed)
                return parsed, usage, raw_content
            except Exception as exc:
                last_error = exc
                if not isinstance(exc, LLMValidationError):
                    self._record_request_timing(
                        result,
                        "single",
                        model_name,
                        prompt_version,
                        1,
                        attempt + 1,
                        "api_error",
                        [comment],
                        type(exc).__name__,
                        str(exc),
                    )
                if attempt < len(self.retry_delays):
                    time.sleep(self.retry_delays[attempt])
        raise last_error or RuntimeError("DeepSeek call failed")

    def _call_batch_with_retry(
        self,
        result: LLMBatchResult,
        comments: list[dict],
        model_name: str,
        prompt_version: str,
    ) -> tuple[list[dict], dict | None, str]:
        system_prompt = self.prompt_builder.build_system_prompt()
        user_prompt = self.prompt_builder.build_batch_user_prompt(comments)
        last_error: Exception | None = None
        attempts = len(self.retry_delays) + 1
        for attempt in range(attempts):
            try:
                parsed, usage, raw_content = self.deepseek_client.chat_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=model_name,
                    max_tokens=max(4000, 1200 * len(comments)),
                )
                self._record_request_timing(
                    result,
                    "batch",
                    model_name,
                    prompt_version,
                    len(comments),
                    attempt + 1,
                    "api_ok",
                    comments,
                )
                items = parsed.get("items") if isinstance(parsed, dict) else None
                if not isinstance(items, list):
                    raise LLMValidationError("batch result must contain an items array", raw_content)
                if len(items) != len(comments):
                    raise LLMValidationError(
                        f"batch result item count mismatch: expected {len(comments)}, got {len(items)}",
                        raw_content,
                    )
                if not all(isinstance(item, dict) for item in items):
                    raise LLMValidationError("batch result items must be JSON objects", raw_content)
                return items, usage, raw_content
            except Exception as exc:
                last_error = exc
                if not isinstance(exc, LLMValidationError):
                    self._record_request_timing(
                        result,
                        "batch",
                        model_name,
                        prompt_version,
                        len(comments),
                        attempt + 1,
                        "api_error",
                        comments,
                        type(exc).__name__,
                        str(exc),
                    )
                if attempt < len(self.retry_delays):
                    time.sleep(self.retry_delays[attempt])
        raise last_error or RuntimeError("DeepSeek batch call failed")

    def _record_request_timing(
        self,
        result: LLMBatchResult,
        scope: str,
        model_name: str,
        prompt_version: str,
        batch_size: int,
        attempt: int,
        status: str,
        comments: list[dict],
        error_type: str = "",
        error_message: str = "",
    ) -> None:
        timing = dict(getattr(self.deepseek_client, "last_timing", {}) or {})
        result.request_timing_rows.append(
            {
                "request_index": len(result.request_timing_rows) + 1,
                "scope": scope,
                "model_name": model_name,
                "prompt_version": prompt_version,
                "batch_size": batch_size,
                "attempt": attempt,
                "status": status,
                "error_type": error_type,
                "error_message": error_message,
                "total_seconds": timing.get("total_seconds", ""),
                "payload_build_seconds": timing.get("payload_build_seconds", ""),
                "http_open_seconds": timing.get("http_open_seconds", ""),
                "response_read_seconds": timing.get("response_read_seconds", ""),
                "json_parse_seconds": timing.get("json_parse_seconds", ""),
                "request_bytes": timing.get("request_bytes", ""),
                "response_bytes": timing.get("response_bytes", ""),
                "prompt_tokens": timing.get("prompt_tokens", ""),
                "completion_tokens": timing.get("completion_tokens", ""),
                "total_tokens": timing.get("total_tokens", ""),
                "max_tokens": timing.get("max_tokens", ""),
                "timeout_seconds": timing.get("timeout_seconds", ""),
                "finish_reason": timing.get("finish_reason", ""),
                "content_ids": ",".join(str(comment.get("content_id", "")) for comment in comments),
            }
        )

    def _append_success_rows(
        self,
        result: LLMBatchResult,
        comment: dict,
        model_name: str,
        prompt_version: str,
        input_hash: str,
        parsed: dict,
        usage: dict | None,
        raw_content: str,
    ) -> None:
        purchase = parsed.get("purchase_decision_evidence", {})
        noise = parsed.get("noise_flags", {})
        comment_id = str(comment.get("content_hash") or comment.get("content_id") or "")
        base = {
            "content_id": comment.get("content_id", ""),
            "comment_id": comment_id,
            "source_file": comment.get("source_file", ""),
            "platform": comment.get("platform", ""),
            "product_title": comment.get("product_title", ""),
            "product_id": comment.get("product_id", ""),
            "sku": comment.get("sku", ""),
            "comment_text": comment.get("content_text_clean") or comment.get("review_text_clean") or "",
        }
        result.analysis_rows.append(
            {
                **base,
                "overall_sentiment": parsed.get("overall_sentiment", ""),
                "main_target": parsed.get("main_target", ""),
                "purchase_evidence_level": purchase.get("evidence_level", ""),
                "is_purchase_decision_evidence": purchase.get("is_purchase_decision_evidence", ""),
                "purchase_evidence_reason": purchase.get("reason", ""),
                "praise_count": len(parsed.get("praise_items", [])),
                "complaint_count": len(parsed.get("complaint_items", [])),
                "noise_flags": json.dumps(noise, ensure_ascii=False),
                "one_sentence_summary": parsed.get("one_sentence_summary", ""),
                "model_name": model_name,
                "prompt_version": prompt_version,
                "input_hash": input_hash,
                "usage_json": json.dumps(usage or {}, ensure_ascii=False),
                "raw_llm_json": raw_content,
            }
        )
        for index, item in enumerate(parsed.get("praise_items", []), 1):
            result.praise_rows.append({**base, "item_index": index, **item})
        for index, item in enumerate(parsed.get("complaint_items", []), 1):
            result.complaint_rows.append({**base, "item_index": index, **item})
        result.success_count += 1

    def _record_failure(
        self,
        result: LLMBatchResult,
        comment: dict,
        model_name: str,
        prompt_version: str,
        input_hash: str,
        error_type: str,
        error_message: str,
        raw_response: str | None = None,
    ) -> None:
        result.failed_count += 1
        result.failure_rows.append(
            {
                "content_id": comment.get("content_id", ""),
                "comment_id": comment.get("content_hash") or comment.get("content_id") or "",
                "source_file": comment.get("source_file", ""),
                "product_title": comment.get("product_title", ""),
                "comment_text": comment.get("content_text_clean") or comment.get("review_text_clean") or "",
                "model_name": model_name,
                "prompt_version": prompt_version,
                "input_hash": input_hash,
                "error_type": error_type,
                "error_message": error_message,
                "raw_response": raw_response or "",
            }
        )


def repair_evidence_quotes(result_json: dict, original_text: str) -> None:
    """Restore exact original substrings when the model only changed whitespace."""
    for group in ("praise_items", "complaint_items"):
        items = result_json.get(group, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            quote = str(item.get("evidence_quote", ""))
            if quote and quote not in original_text:
                repaired = _find_whitespace_insensitive_substring(original_text, quote)
                if repaired:
                    item["evidence_quote"] = repaired


def sanitize_llm_result(result_json: dict, original_text: str) -> None:
    """Apply only audit-preserving cleanup before validation."""
    repair_evidence_quotes(result_json, original_text)


def derive_sentiment_fields(result_json: dict) -> None:
    """Derive final review-level labels from validated praise/complaint evidence."""
    praise_items = [item for item in result_json.get("praise_items", []) if isinstance(item, dict)]
    complaint_items = [item for item in result_json.get("complaint_items", []) if isinstance(item, dict)]
    noise_flags = result_json.get("noise_flags", {}) if isinstance(result_json.get("noise_flags"), dict) else {}

    if praise_items and complaint_items:
        result_json["overall_sentiment"] = "mixed"
    elif praise_items:
        result_json["overall_sentiment"] = "positive"
    elif complaint_items:
        result_json["overall_sentiment"] = "negative"
    elif any(bool(value) for value in noise_flags.values()) or result_json.get("valid_review") is False:
        result_json["overall_sentiment"] = "noise"
    else:
        result_json["overall_sentiment"] = "neutral"

    targets = [
        str(item.get("target"))
        for item in [*praise_items, *complaint_items]
        if item.get("target") in schema.TARGETS and item.get("target") != "unclear"
    ]
    unique_targets = sorted(set(targets))
    if not unique_targets:
        if noise_flags.get("pure_service"):
            result_json["main_target"] = "service"
        elif noise_flags.get("pure_logistics"):
            result_json["main_target"] = "logistics"
        else:
            result_json["main_target"] = "unclear"
    elif len(unique_targets) == 1:
        result_json["main_target"] = unique_targets[0]
    else:
        result_json["main_target"] = "mixed"

    result_json["purchase_decision_evidence"] = derive_purchase_decision_evidence(
        praise_items,
        complaint_items,
        noise_flags,
    )


def derive_purchase_decision_evidence(
    praise_items: list[dict],
    complaint_items: list[dict],
    noise_flags: dict,
) -> dict:
    product_evidence = [
        item
        for item in [*praise_items, *complaint_items]
        if item.get("target") in {"product", "installation", "brand", "mixed"}
    ]
    if not product_evidence:
        if noise_flags.get("pure_service") or noise_flags.get("pure_logistics"):
            return {
                "is_purchase_decision_evidence": False,
                "evidence_level": "D",
                "reason": "主要是客服、物流或履约噪音，不构成商品购前决策证据。",
            }
        return {
            "is_purchase_decision_evidence": False,
            "evidence_level": "D",
            "reason": "没有可复核的商品体验、场景、对比或问题证据。",
        }

    level = _strongest_evidence_level(product_evidence)
    if all(
        item.get("praise_method") == "direct_satisfaction"
        or item.get("complaint_method") in {None, ""}
        for item in product_evidence
    ):
        level = _weaker_level(level, "C")
    is_evidence = level in {"S", "A", "B"}
    return {
        "is_purchase_decision_evidence": is_evidence,
        "evidence_level": level,
        "reason": _purchase_reason(level, is_evidence),
    }


def _strongest_evidence_level(items: list[dict]) -> str:
    order = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}
    levels = [str(item.get("evidence_strength")) for item in items]
    valid_levels = [level for level in levels if level in order]
    if not valid_levels:
        return "D"
    return max(valid_levels, key=lambda level: order[level])


def _weaker_level(level: str, cap: str) -> str:
    order = ["D", "C", "B", "A", "S"]
    if level not in order or cap not in order:
        return level
    return order[min(order.index(level), order.index(cap))]


def _purchase_reason(level: str, is_evidence: bool) -> str:
    if is_evidence:
        return f"包含可复核的商品相关体验证据，程序汇总为 {level} 级购前决策证据。"
    if level == "C":
        return "主要是泛泛满意或泛泛不满，缺少具体商品体验、场景或后果。"
    return "缺少可复核的商品相关体验证据。"


def _find_whitespace_insensitive_substring(original_text: str, quote: str) -> str:
    normalized_chars: list[str] = []
    original_indexes: list[int] = []
    for index, char in enumerate(original_text):
        if re.match(r"\s", char):
            continue
        normalized_chars.append(char)
        original_indexes.append(index)

    normalized_original = "".join(normalized_chars)
    normalized_quote = re.sub(r"\s+", "", quote)
    if not normalized_quote:
        return ""
    start = normalized_original.find(normalized_quote)
    if start < 0:
        return ""
    end = start + len(normalized_quote) - 1
    return original_text[original_indexes[start] : original_indexes[end] + 1]
