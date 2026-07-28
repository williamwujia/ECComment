from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from sentiment_codes import COMPLAINT_CODES, PRAISE_CODES, SENTIMENT_LABELS


FAST_SYSTEM_PROMPT = """你是电商评论情感分类器。

任务：为每条评论输出极简 JSONL 标签。
每条评论只输出一行 JSON。
不要解释。
不要 Markdown。
不要输出多余文字。
不要使用中文字段名。

字段：
i=评论ID
s=情感，P正向/N负向/M混合/Z中性
sc=情感分数，1-10
p=主要夸法 code
n=主要骂法 code
c=置信度，1低/2中/3高

情感规则：
P=整体正向
N=整体负向
M=正负并存，或整体满意但指出明确问题
Z=只有事实描述，缺少明显情绪

评分规则：
1-3=明显负面
4-5=弱负面或中性偏负
6=中性偏正
7-8=普通正向
9-10=强正向

注意：
1. 淘宝评论天然偏正向，普通满意通常为7-8分。
2. 不要因为出现“不错”“满意”就给9-10分。
3. 只有强烈推荐、明显超预期、复购、主动安利、解决重大顾虑，才给9-10分。
4. 如果评论同时包含优点和问题，判断为M。
5. 如果问题只是轻微使用边界，不要判断为强负面。
6. 只选择一个最主要夸法 code。
7. 只选择一个最主要骂法 code。
8. 没有夸法或骂法时用 "-"。

夸法 code：
F=功能效果
S=使用场景
E=体验舒适
O=外观质感
I=安装使用
V=服务物流
C=对比胜出
P$=性价比接受
B=品牌信任
D=决策安心
-=无

骂法 code：
F=核心功能不满
S=场景不适配
E=体验不适
O=外观做工问题
I=安装使用麻烦
V=服务物流问题
Q=品控故障
P$=价格不值
G=宣传落差
R=后悔退换
-=无

输出格式示例：
{"i":1,"s":"P","sc":8,"p":"S","n":"-","c":3}
{"i":2,"s":"M","sc":7,"p":"E","n":"S","c":3}
"""


@dataclass
class FastSentimentBatchResult:
    rows: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    timings: list[dict] = field(default_factory=list)


class FastSentimentLLM:
    def __init__(self, client, model_name: str, max_retries: int = 1):
        self.client = client
        self.model_name = model_name
        self.max_retries = max_retries

    def analyze(
        self,
        comments: list[dict],
        batch_size: int = 50,
        concurrency: int = 10,
    ) -> FastSentimentBatchResult:
        result = FastSentimentBatchResult()
        size = max(batch_size, 1)
        batches = [
            comments[index : index + size]
            for index in range(0, len(comments), size)
        ]
        if not batches:
            return result

        def analyze_one(batch: list[dict]) -> FastSentimentBatchResult:
            batch_result = FastSentimentBatchResult()
            self._analyze_batch(batch, batch_result, attempt=1)
            return batch_result

        with ThreadPoolExecutor(
            max_workers=min(max(int(concurrency or 1), 1), len(batches)),
            thread_name_prefix="sentiment-fast",
        ) as executor:
            # map preserves input batch order while requests run concurrently.
            for batch_result in executor.map(analyze_one, batches):
                result.rows.extend(batch_result.rows)
                result.failures.extend(batch_result.failures)
                result.timings.extend(batch_result.timings)
        return result

    def _analyze_batch(self, comments: list[dict], result: FastSentimentBatchResult, attempt: int) -> None:
        if not comments:
            return
        try:
            raw, usage = self.client.chat_text(
                system_prompt=FAST_SYSTEM_PROMPT,
                user_prompt=build_fast_user_prompt(comments),
                model=self.model_name,
                max_tokens=max(500, len(comments) * 50),
            )
            parsed = parse_fast_jsonl(raw)
            valid_rows, invalid_rows = validate_fast_rows(parsed)
            expected_ids = {str(_content_id(comment)) for comment in comments}
            by_id = {str(row["i"]): row for row in valid_rows}
            missing_ids = sorted(expected_ids - set(by_id))
            result.rows.extend(_enrich_fast_row(comment, by_id[str(_content_id(comment))], "llm_fast") for comment in comments if str(_content_id(comment)) in by_id)
            self._record_timing(result, comments, attempt, "ok", usage=usage)
            retry_comments = [
                comment
                for comment in comments
                if str(_content_id(comment)) in missing_ids
            ]
            if invalid_rows:
                result.failures.extend(_failure(comment, "ValidationError", "invalid fast JSONL row", raw) for comment in comments if str(_content_id(comment)) not in by_id and str(_content_id(comment)) not in missing_ids)
            if retry_comments and attempt <= self.max_retries:
                self._analyze_batch(retry_comments, result, attempt=attempt + 1)
            elif retry_comments:
                result.failures.extend(_failure(comment, "MissingResult", "LLM did not return a valid row", raw) for comment in retry_comments)
        except Exception as exc:
            self._record_timing(result, comments, attempt, "error", type(exc).__name__, str(exc))
            if attempt <= self.max_retries:
                self._analyze_batch(comments, result, attempt=attempt + 1)
                return
            result.failures.extend(_failure(comment, type(exc).__name__, str(exc), "") for comment in comments)

    def _record_timing(
        self,
        result: FastSentimentBatchResult,
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
                "scope": "sentiment_fast",
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


def build_fast_user_prompt(comments: list[dict]) -> str:
    lines = []
    for comment in comments:
        item = {"i": _content_id(comment), "t": _text(comment)}
        product_title = str(comment.get("product_title") or "")
        if product_title:
            item["pt"] = product_title[:20]
        lines.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines)


def parse_fast_jsonl(raw: str) -> list[dict]:
    rows = []
    for line in extract_jsonl_lines(raw):
        rows.append(json.loads(line))
    return rows


def extract_jsonl_lines(raw: str) -> list[str]:
    lines = []
    for line in str(raw or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            lines.append(stripped)
    return lines


def validate_fast_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    valid = []
    invalid = []
    for row in rows:
        if _validate_fast_row(row):
            valid.append(row)
        else:
            invalid.append(row)
    return valid, invalid


def _validate_fast_row(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    if not all(field in row for field in ("i", "s", "sc", "p", "n", "c")):
        return False
    if row.get("s") not in SENTIMENT_LABELS:
        return False
    if row.get("p") not in PRAISE_CODES or row.get("n") not in COMPLAINT_CODES:
        return False
    if not isinstance(row.get("sc"), int) or not 1 <= row["sc"] <= 10:
        return False
    if row.get("c") not in {1, 2, 3}:
        return False
    return True


def _enrich_fast_row(comment: dict, row: dict, source: str) -> dict:
    enriched = {
        "content_id": _content_id(comment),
        "content_hash": comment.get("content_hash", ""),
        "source_file": comment.get("source_file", ""),
        "platform": comment.get("platform", ""),
        "product_title": comment.get("product_title", ""),
        "sku": comment.get("sku", ""),
        "content_text_clean": _text(comment),
        "sentiment_label": row["s"],
        "sentiment_label_cn": SENTIMENT_LABELS.get(row["s"], ""),
        "sentiment_score": row["sc"],
        "praise_code": row["p"],
        "praise_cn": PRAISE_CODES.get(row["p"], ""),
        "complaint_code": row["n"],
        "complaint_cn": COMPLAINT_CODES.get(row["n"], ""),
        "sentiment_confidence": row["c"],
        "sentiment_source": source,
    }
    return enriched


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
    return str(comment.get("content_text_clean") or comment.get("review_text_clean") or "")
