from __future__ import annotations

import json
from dataclasses import dataclass, field


DETAIL_SYSTEM_PROMPT = """你是电商评论洞察分析器。

请对以下评论做简短详析。

输出必须是 JSONL。
每条评论一行。
不要 Markdown。
不要多余文字。

字段：
i=评论ID
e=证据句，直接摘取评论中最关键的短句
r=判断原因，30字以内
g=GEO内容价值，40字以内

要求：
1. 只分析评论中明确出现的信息，不要脑补。
2. 如果是混合评论，要同时指出优点和问题。
3. 如果是负向评论，要说明它反映了什么顾虑。
4. GEO内容价值应说明这条评论可用于什么内容方向。
5. 每个字段都要简短。
"""

DECISION_KEYWORDS = [
    "买之前",
    "买前",
    "纠结",
    "对比",
    "比较了",
    "看了很多",
    "攻略",
    "推荐",
    "问了客服",
    "咨询",
    "最后选",
    "为什么买",
    "值不值",
]


@dataclass
class DetailSentimentBatchResult:
    rows: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    timings: list[dict] = field(default_factory=list)


class DetailSentimentLLM:
    def __init__(self, client, model_name: str, max_retries: int = 1):
        self.client = client
        self.model_name = model_name
        self.max_retries = max_retries

    def analyze(self, comments: list[dict], fast_rows_by_id: dict[str, dict], batch_size: int = 10) -> DetailSentimentBatchResult:
        result = DetailSentimentBatchResult()
        for index in range(0, len(comments), max(batch_size, 1)):
            batch = comments[index : index + max(batch_size, 1)]
            self._analyze_batch(batch, fast_rows_by_id, result, attempt=1)
        return result

    def _analyze_batch(
        self,
        comments: list[dict],
        fast_rows_by_id: dict[str, dict],
        result: DetailSentimentBatchResult,
        attempt: int,
    ) -> None:
        if not comments:
            return
        try:
            raw, usage = self.client.chat_text(
                system_prompt=DETAIL_SYSTEM_PROMPT,
                user_prompt=build_detail_user_prompt(comments, fast_rows_by_id),
                model=self.model_name,
                max_tokens=max(300, len(comments) * 120),
            )
            rows = parse_detail_jsonl(raw)
            by_id = {str(row["i"]): row for row in rows if validate_detail_row(row)}
            result.rows.extend(
                _enrich_detail_row(
                    comment,
                    by_id[str(_content_id(comment))],
                    fast_rows_by_id.get(str(_content_id(comment)), {}),
                )
                for comment in comments
                if str(_content_id(comment)) in by_id
            )
            self._record_timing(result, comments, attempt, "ok", usage=usage)
            missing = [comment for comment in comments if str(_content_id(comment)) not in by_id]
            if missing and attempt <= self.max_retries:
                self._analyze_batch(missing, fast_rows_by_id, result, attempt=attempt + 1)
            elif missing:
                result.failures.extend(_failure(comment, "MissingResult", "LLM did not return valid detail JSONL", raw) for comment in missing)
        except Exception as exc:
            self._record_timing(result, comments, attempt, "error", type(exc).__name__, str(exc))
            if attempt <= self.max_retries:
                self._analyze_batch(comments, fast_rows_by_id, result, attempt=attempt + 1)
                return
            result.failures.extend(_failure(comment, type(exc).__name__, str(exc), "") for comment in comments)

    def _record_timing(
        self,
        result: DetailSentimentBatchResult,
        comments: list[dict],
        attempt: int,
        status: str,
        error_type: str = "",
        error_message: str = "",
        usage: dict | None = None,
    ) -> None:
        timing = dict(getattr(self.client, "last_timing", {}) or {})
        result.timings.append(
            {
                "scope": "sentiment_detail",
                "batch_size": len(comments),
                "attempt": attempt,
                "status": status,
                "error_type": error_type,
                "error_message": error_message,
                "total_seconds": timing.get("total_seconds", ""),
                "response_read_seconds": timing.get("response_read_seconds", ""),
                "prompt_tokens": (usage or {}).get("prompt_tokens", timing.get("prompt_tokens", "")),
                "completion_tokens": (usage or {}).get("completion_tokens", timing.get("completion_tokens", "")),
                "total_tokens": (usage or {}).get("total_tokens", timing.get("total_tokens", "")),
                "max_tokens": timing.get("max_tokens", ""),
                "finish_reason": timing.get("finish_reason", ""),
                "content_ids": ",".join(str(_content_id(comment)) for comment in comments),
            }
        )


def should_detail_analyze(comment: dict, fast_row: dict) -> bool:
    text = _text(comment)
    if fast_row.get("sentiment_label") in {"N", "M"}:
        return True
    if fast_row.get("sentiment_confidence") == 1:
        return True
    if comment.get("evidence_level") in {"A", "B", "C"}:
        return True
    like_count = comment.get("like_count")
    if isinstance(like_count, int) and like_count >= 5:
        return True
    if len(text) >= 80:
        return True
    return any(keyword in text for keyword in DECISION_KEYWORDS)


def build_detail_user_prompt(comments: list[dict], fast_rows_by_id: dict[str, dict]) -> str:
    lines = []
    for comment in comments:
        fast_row = fast_rows_by_id.get(str(_content_id(comment)), {})
        item = {
            "i": _content_id(comment),
            "t": _text(comment),
            "s": fast_row.get("sentiment_label", ""),
            "sc": fast_row.get("sentiment_score", ""),
            "p": fast_row.get("praise_code", "-"),
            "n": fast_row.get("complaint_code", "-"),
        }
        lines.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines)


def parse_detail_jsonl(raw: str) -> list[dict]:
    rows = []
    for line in str(raw or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            rows.append(json.loads(stripped))
    return rows


def validate_detail_row(row: dict) -> bool:
    return isinstance(row, dict) and all(field in row for field in ("i", "e", "r", "g"))


def _enrich_detail_row(comment: dict, row: dict, fast_row: dict | None = None) -> dict:
    base = dict(fast_row or {})
    base.update(
        {
            "content_id": _content_id(comment),
            "content_hash": comment.get("content_hash", ""),
            "source_file": comment.get("source_file", base.get("source_file", "")),
            "platform": comment.get("platform", base.get("platform", "")),
            "product_title": comment.get("product_title", base.get("product_title", "")),
            "sku": comment.get("sku", base.get("sku", "")),
            "content_text_clean": _text(comment),
        }
    )
    base.update(
        {
            "sentiment_evidence": row.get("e", ""),
            "sentiment_reason": row.get("r", ""),
            "geo_value": row.get("g", ""),
        }
    )
    return base


def _failure(comment: dict, error_type: str, error_message: str, raw_response: str) -> dict:
    return {
        "content_id": _content_id(comment),
        "content_hash": comment.get("content_hash", ""),
        "content_text_clean": _text(comment),
        "error_type": error_type,
        "error_message": error_message,
        "raw_response": raw_response,
    }


def _content_id(comment: dict) -> object:
    return comment.get("content_id") or comment.get("content_hash") or ""


def _text(comment: dict) -> str:
    return str(comment.get("content_text_clean") or "")
