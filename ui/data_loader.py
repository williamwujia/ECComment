from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pandas as pd

try:
    from utils.excel_writer import SHEET_COLUMNS
except ImportError:  # pragma: no cover - keeps the UI importable in isolation.
    SHEET_COLUMNS = {}


CORE_SHEETS = [
    "content_all",
    "ai_candidates",
    "pre_purchase_details",
    "summary_by_product",
    "summary_by_keyword",
    "summary_by_month",
    "errors",
    "debug_samples",
]

SENTIMENT_SHEETS = [
    "sentiment_run_summary",
    "sentiment_fast",
    "sentiment_detail",
    "sentiment_summary",
    "sentiment_failures",
    "sentiment_timings",
]

LEGACY_LLM_SHEETS = [
    "llm_run_summary",
    "llm_review_analysis",
    "llm_praise_items",
    "llm_complaint_items",
    "llm_failures",
    "llm_request_timings",
]

OPTIONAL_SHEETS = ["reviews_raw", "qa_pairs_raw", "jd_review_tags"] + SENTIMENT_SHEETS + LEGACY_LLM_SHEETS
AUXILIARY_OUTPUT_PREFIXES = ("大家问-",)

CORE_FIELDS = [
    "content_id",
    "record_type",
    "source_file",
    "workbook_source",
    "platform",
    "product_title",
    "shop_name",
    "product_url",
    "product_id",
    "content_role",
    "content_text_raw",
    "content_text_clean",
    "parent_text_clean",
    "sku",
    "user_name_masked",
    "user_status",
    "content_order",
    "content_hash",
    "review_time",
    "review_date",
    "pre_purchase_decision",
    "pre_purchase_terms",
    "pre_purchase_reason",
    "ai_candidate",
    "ai_candidate_gate_reason",
    "ai_source_terms",
    "ai_action_terms",
    "purchase_context_terms",
    "decision_context_terms",
    "matched_keywords",
    "matched_sentence",
    "match_score",
    "evidence_level",
    "evidence_reason",
    "excluded_by_rule",
    "exclude_reason",
    "extract_confidence",
]

BOOL_FIELDS = [
    "pre_purchase_decision",
    "ai_candidate",
    "ai_related",
    "excluded_by_rule",
    "ai_source_hit",
    "ai_action_hit",
    "purchase_context_hit",
    "decision_context_hit",
]

NUMERIC_FIELDS = [
    "match_score",
    "extract_confidence",
    "content_order",
    "source_file_count",
    "review_count",
    "qa_question_count",
    "qa_answer_count",
    "content_count",
    "ai_candidate_count",
    "a_level_count",
    "b_level_count",
    "c_level_count",
    "d_level_count",
    "a_b_count",
    "a_b_c_count",
    "pre_purchase_decision_count",
    "explicit_ai_rate",
    "generic_ai_rate",
    "inferred_ai_rate",
    "ai_candidate_rate",
    "hit_count",
    "sentiment_score",
    "sentiment_confidence",
    "value",
    "target_review_count",
    "rule_count",
    "llm_fast_count",
    "detail_count",
    "failed_count",
    "sentiment_limit",
    "detail_limit",
    "sentiment_batch_size",
    "detail_batch_size",
    "elapsed_seconds",
    "batch_size",
    "attempt",
    "total_seconds",
    "response_read_seconds",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "max_tokens",
]


class ExcelLoadError(ValueError):
    """Raised when a workbook cannot be shown safely in the UI."""


@dataclass(frozen=True)
class WorkbookInfo:
    present_sheets: list[str]
    missing_core_sheets: list[str]
    source_name: str


def apply_project_alias(
    loaded: tuple[dict[str, pd.DataFrame], WorkbookInfo],
    alias: str,
) -> tuple[dict[str, pd.DataFrame], WorkbookInfo]:
    data, info = loaded
    display_name = alias.strip() or info.source_name
    renamed: dict[str, pd.DataFrame] = {}
    for sheet_name, frame in data.items():
        if "workbook_source" in frame.columns:
            frame = frame.copy()
            frame["workbook_source"] = display_name
        renamed[sheet_name] = frame
    return renamed, WorkbookInfo(info.present_sheets, info.missing_core_sheets, display_name)


def expected_columns(sheet_name: str) -> list[str]:
    base = list(SHEET_COLUMNS.get(sheet_name, []))
    if sheet_name in {"content_all", "ai_candidates", "pre_purchase_details"}:
        for column in CORE_FIELDS:
            if column not in base:
                base.append(column)
    return base


def latest_output_file(output_dir: str | Path = "output") -> Path | None:
    directory = Path(output_dir)
    if not directory.exists():
        return None
    files = sorted(
        (item for item in directory.glob("*.xlsx") if is_workbench_output_file(item)),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def list_output_files(output_dir: str | Path = "output") -> list[Path]:
    directory = Path(output_dir)
    if not directory.exists():
        return []
    return sorted(
        (item for item in directory.glob("*.xlsx") if is_workbench_output_file(item)),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def is_workbench_output_file(path: str | Path) -> bool:
    name = Path(path).name
    if not name.lower().endswith(".xlsx") or name.startswith("~$"):
        return False
    return not name.startswith(AUXILIARY_OUTPUT_PREFIXES)


def auxiliary_workbook_message(source_name: str) -> str | None:
    for prefix in AUXILIARY_OUTPUT_PREFIXES:
        if source_name.startswith(prefix):
            primary_name = source_name.removeprefix(prefix)
            return (
                "这个 Excel 是问大家专项导出，不是复核台主工作簿。"
                f"请改选同时间戳的主结果文件：{primary_name}"
            )
    return None


def load_excel(path_or_file: str | Path | BinaryIO) -> tuple[dict[str, pd.DataFrame], WorkbookInfo]:
    source_name = getattr(path_or_file, "name", str(path_or_file))
    source_name = Path(source_name).name
    auxiliary_message = auxiliary_workbook_message(source_name)
    if auxiliary_message:
        raise ExcelLoadError(auxiliary_message)

    try:
        excel = pd.ExcelFile(path_or_file)
    except Exception as exc:  # noqa: BLE001 - translated into a user-friendly UI error.
        raise ExcelLoadError("Excel 文件无法读取，请确认它是脚本输出的 .xlsx 文件。") from exc

    if not excel.sheet_names:
        raise ExcelLoadError("Excel 文件为空，没有可展示的 Sheet。")

    data: dict[str, pd.DataFrame] = {}
    present = list(excel.sheet_names)
    for sheet in all_supported_sheets():
        if sheet in present:
            frame = pd.read_excel(excel, sheet_name=sheet)
            normalized = normalize_frame(frame, sheet)
            normalized["workbook_source"] = source_name
            data[sheet] = normalized
        else:
            data[sheet] = empty_frame(sheet)

    info = WorkbookInfo(
        present_sheets=present,
        missing_core_sheets=[sheet for sheet in CORE_SHEETS if sheet not in present],
        source_name=source_name,
    )
    return data, info


def merge_workbooks(loaded: list[tuple[dict[str, pd.DataFrame], WorkbookInfo]]) -> tuple[dict[str, pd.DataFrame], WorkbookInfo]:
    if not loaded:
        return ({sheet: empty_frame(sheet) for sheet in CORE_SHEETS + OPTIONAL_SHEETS}, WorkbookInfo([], CORE_SHEETS, ""))

    merged: dict[str, pd.DataFrame] = {}
    for sheet in all_supported_sheets():
        frames = [data.get(sheet, empty_frame(sheet)) for data, _info in loaded]
        frames = [frame for frame in frames if frame is not None and not frame.empty]
        merged[sheet] = pd.concat(frames, ignore_index=True, sort=False) if frames else empty_frame(sheet)

    present_sheets = sorted({sheet for _data, info in loaded for sheet in info.present_sheets})
    present_by_sheet = {sheet: any(sheet in info.present_sheets for _data, info in loaded) for sheet in CORE_SHEETS}
    missing_core_sheets = [sheet for sheet, present in present_by_sheet.items() if not present]
    source_names = [info.source_name for _data, info in loaded]
    source_name = source_names[0] if len(source_names) == 1 else f"{len(source_names)} files: " + ", ".join(source_names)
    return merged, WorkbookInfo(present_sheets, missing_core_sheets, source_name)


def empty_frame(sheet_name: str) -> pd.DataFrame:
    return pd.DataFrame(columns=expected_columns(sheet_name))


def all_supported_sheets() -> list[str]:
    return list(dict.fromkeys(CORE_SHEETS + OPTIONAL_SHEETS))


def normalize_frame(frame: pd.DataFrame, sheet_name: str) -> pd.DataFrame:
    frame = frame.copy()
    original_columns = set(frame.columns)
    for column in expected_columns(sheet_name):
        if column not in frame.columns:
            frame[column] = pd.NA

    if (
        sheet_name == "pre_purchase_details"
        and "pre_purchase_decision" in frame.columns
        and "pre_purchase_decision" not in original_columns
    ):
        frame["pre_purchase_decision"] = True

    if "evidence_level" in frame.columns and "ai_influence_level" in frame.columns:
        empty_level = frame["evidence_level"].isna() | (frame["evidence_level"].astype(str).str.strip() == "")
        frame.loc[empty_level, "evidence_level"] = frame.loc[empty_level, "ai_influence_level"]

    for column in BOOL_FIELDS:
        if column in frame.columns:
            frame[column] = frame[column].map(to_bool).fillna(False).astype(bool)

    for column in NUMERIC_FIELDS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)

    if "evidence_level" in frame.columns:
        frame["evidence_level"] = (
            frame["evidence_level"].fillna("").astype(str).str.strip().str.upper()
        )
        frame.loc[~frame["evidence_level"].isin(["A", "B", "C", "D"]), "evidence_level"] = ""

    text_columns = [
        column
        for column in frame.columns
        if column not in BOOL_FIELDS and column not in NUMERIC_FIELDS
    ]
    for column in text_columns:
        frame[column] = frame[column].fillna("").astype(str)

    return frame


def to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y", "是", "对", "已命中", "命中"}


def get_content_all(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return data.get("content_all", empty_frame("content_all"))


def get_pre_purchase(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    details = data.get("pre_purchase_details", empty_frame("pre_purchase_details"))
    if not details.empty:
        return details.copy()
    content = get_content_all(data)
    if "pre_purchase_decision" not in content.columns:
        return empty_frame("pre_purchase_details")
    return content[content["pre_purchase_decision"]].copy()


def get_ai_candidates(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    candidates = data.get("ai_candidates", empty_frame("ai_candidates"))
    if candidates.empty:
        content = get_content_all(data)
        if content.empty:
            return empty_frame("ai_candidates")
        candidates = content[content["ai_candidate"]].copy()
    if "evidence_level" in candidates.columns:
        candidates = candidates[candidates["evidence_level"].isin(["A", "B", "C"])]
    return candidates.copy()


def get_sentiment_fast(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return data.get("sentiment_fast", empty_frame("sentiment_fast")).copy()


def get_sentiment_detail(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return data.get("sentiment_detail", empty_frame("sentiment_detail")).copy()


def get_sentiment_joined(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    fast = get_sentiment_fast(data)
    if fast.empty:
        return fast

    content = get_content_all(data)
    content_cols = [
        column
        for column in [
            "content_id",
            "workbook_source",
            "pre_purchase_decision",
            "ai_candidate",
            "evidence_level",
            "matched_keywords",
            "matched_sentence",
            "evidence_reason",
            "review_date",
            "content_role",
        ]
        if column in content.columns and column not in fast.columns
    ]
    if not content.empty and "content_id" in content.columns and content_cols:
        fast = fast.merge(
            content[["content_id"] + content_cols].drop_duplicates("content_id"),
            on="content_id",
            how="left",
        )

    detail = get_sentiment_detail(data)
    detail_cols = [
        column
        for column in ["content_id", "sentiment_evidence", "sentiment_reason", "geo_value"]
        if column in detail.columns
    ]
    if not detail.empty and "content_id" in detail.columns and len(detail_cols) > 1:
        fast = fast.merge(
            detail[detail_cols].drop_duplicates("content_id"),
            on="content_id",
            how="left",
        )
    return normalize_joined_sentiment(fast)


def get_ai_sentiment(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    joined = get_sentiment_joined(data)
    if joined.empty or "ai_candidate" not in joined.columns:
        return joined.iloc[0:0].copy()
    return joined[joined["ai_candidate"].astype(bool)].copy()


def normalize_joined_sentiment(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for column in ["sentiment_evidence", "sentiment_reason", "geo_value"]:
        if column in frame.columns:
            frame[column] = frame[column].fillna("").astype(str)
    if "ai_candidate" in frame.columns:
        frame["ai_candidate"] = frame["ai_candidate"].fillna(False).map(to_bool).astype(bool)
    if "pre_purchase_decision" in frame.columns:
        frame["pre_purchase_decision"] = frame["pre_purchase_decision"].fillna(False).map(to_bool).astype(bool)
    return frame


def get_high_value_sentiment(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    joined = get_sentiment_joined(data)
    if joined.empty:
        return joined
    detail_cols = [column for column in ["sentiment_evidence", "sentiment_reason", "geo_value"] if column in joined.columns]
    if not detail_cols:
        return joined.iloc[0:0].copy()
    mask = pd.Series(False, index=joined.index)
    for column in detail_cols:
        mask = mask | joined[column].fillna("").astype(str).str.strip().ne("")
    return joined[mask].copy()


def enrich_with_sentiment(frame: pd.DataFrame, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if frame.empty or "content_id" not in frame.columns:
        return frame
    sentiment = get_sentiment_joined(data)
    if sentiment.empty or "content_id" not in sentiment.columns:
        return frame
    sentiment_cols = [
        column
        for column in [
            "content_id",
            "sentiment_label",
            "sentiment_label_cn",
            "sentiment_score",
            "praise_cn",
            "complaint_cn",
            "sentiment_confidence",
            "sentiment_source",
            "sentiment_evidence",
            "sentiment_reason",
            "geo_value",
        ]
        if column in sentiment.columns and (column == "content_id" or column not in frame.columns)
    ]
    if len(sentiment_cols) <= 1:
        return frame
    return frame.merge(sentiment[sentiment_cols].drop_duplicates("content_id"), on="content_id", how="left")


def summarize_sentiment(data: dict[str, pd.DataFrame]) -> dict[str, int | float | str]:
    fast = get_sentiment_fast(data)
    summary = data.get("sentiment_summary", empty_frame("sentiment_summary"))
    run = data.get("sentiment_run_summary", empty_frame("sentiment_run_summary"))

    metric_values: dict[str, int | float | str] = {}
    if not summary.empty and {"metric", "value"}.issubset(summary.columns):
        for _, row in summary.iterrows():
            metric_values[str(row.get("metric", ""))] = row.get("value", 0)

    total = _metric_number(metric_values, "total_count", len(fast))
    rule_count = _metric_number(metric_values, "rule_count", 0)
    llm_fast_count = _metric_number(metric_values, "llm_fast_count", 0)
    detail_count = _metric_number(metric_values, "detail_count", 0)
    failed_count = _metric_number(metric_values, "failed_count", 0)

    if not run.empty:
        first = run.iloc[0]
        rule_count = int(_scalar_number(first.get("rule_count"), rule_count))
        llm_fast_count = int(_scalar_number(first.get("llm_fast_count"), llm_fast_count))
        detail_count = int(_scalar_number(first.get("detail_count"), detail_count))
        failed_count = int(_scalar_number(first.get("failed_count"), failed_count))

    counts = sentiment_label_counts(fast)
    average_score = 0.0
    if "sentiment_score" in fast.columns and not fast.empty:
        average_score = float(pd.to_numeric(fast["sentiment_score"], errors="coerce").mean())
        if pd.isna(average_score):
            average_score = 0.0
    return {
        "total_count": total,
        "rule_count": rule_count,
        "llm_fast_count": llm_fast_count,
        "detail_count": detail_count,
        "failed_count": failed_count,
        "average_score": average_score,
        "sentiment_P": int(_metric_number(metric_values, "sentiment_P", counts.get("P", 0))),
        "sentiment_N": int(_metric_number(metric_values, "sentiment_N", counts.get("N", 0))),
        "sentiment_M": int(_metric_number(metric_values, "sentiment_M", counts.get("M", 0))),
        "sentiment_Z": int(_metric_number(metric_values, "sentiment_Z", counts.get("Z", 0))),
        "status": str(run.iloc[0].get("status", "")) if not run.empty else "",
        "message": str(run.iloc[0].get("message", "")) if not run.empty else "",
    }


def sentiment_label_counts(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty or "sentiment_label" not in frame.columns:
        return {}
    return {str(key): int(value) for key, value in frame["sentiment_label"].value_counts().items()}


def _metric_number(values: dict[str, object], key: str, default: int | float = 0) -> int | float:
    value = values.get(key, default)
    return _scalar_number(value, default)


def _scalar_number(value: object, default: int | float = 0) -> int | float:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return int(numeric) if float(numeric).is_integer() else float(numeric)


def summarize_content(content: pd.DataFrame) -> dict[str, int | float]:
    total_content = len(content)
    if "content_role" in content.columns:
        review_content = content[content["content_role"].astype(str) == "review"]
        question_count = int((content["content_role"].astype(str) == "question").sum())
        answer_count = int((content["content_role"].astype(str) == "answer").sum())
    else:
        review_content = content
        question_count = 0
        answer_count = 0

    review_count = len(review_content)
    pre_purchase = int(review_content.get("pre_purchase_decision", pd.Series(dtype=bool)).sum())
    ai_candidates = int(review_content.get("ai_candidate", pd.Series(dtype=bool)).sum())
    all_ai_candidates = int(content.get("ai_candidate", pd.Series(dtype=bool)).sum())
    a_level = int((review_content.get("evidence_level", pd.Series(dtype=str)) == "A").sum())
    d_level = int((review_content.get("evidence_level", pd.Series(dtype=str)) == "D").sum())
    products = int(content.get("product_title", pd.Series(dtype=str)).replace("", pd.NA).nunique())
    platforms = int(content.get("platform", pd.Series(dtype=str)).replace("", pd.NA).nunique())
    return {
        "total": total_content,
        "total_content": total_content,
        "review_count": review_count,
        "qa_count": question_count + answer_count,
        "qa_question_count": question_count,
        "qa_answer_count": answer_count,
        "pre_purchase": pre_purchase,
        "ai_candidates": ai_candidates,
        "all_ai_candidates": all_ai_candidates,
        "a_level": a_level,
        "d_level": d_level,
        "products": products,
        "platforms": platforms,
        "ai_rate_total": ai_candidates / review_count if review_count else 0,
        "ai_rate_all_content": all_ai_candidates / total_content if total_content else 0,
        "ai_rate_pre_purchase": ai_candidates / pre_purchase if pre_purchase else 0,
    }


def build_summary_by_product(content: pd.DataFrame) -> pd.DataFrame:
    if content.empty:
        return empty_frame("summary_by_product")
    group_cols = ["platform", "product_title", "shop_name", "product_id"]
    frame = content.copy()
    for col in group_cols:
        if col not in frame.columns:
            frame[col] = ""
    rows = []
    for key, group in frame.groupby(group_cols, dropna=False):
        ai_count = int(group["ai_candidate"].sum()) if "ai_candidate" in group else 0
        pre_count = int(group["pre_purchase_decision"].sum()) if "pre_purchase_decision" in group else 0
        total = len(group)
        levels = group.get("evidence_level", pd.Series(dtype=str)).value_counts()
        rows.append(
            {
                "platform": key[0],
                "product_title": key[1],
                "shop_name": key[2],
                "product_id": key[3],
                "source_file_count": group.get("source_file", pd.Series(dtype=str)).nunique(),
                "content_count": total,
                "pre_purchase_decision_count": pre_count,
                "ai_candidate_count": ai_count,
                "ai_candidate_rate_total": ai_count / total if total else 0,
                "ai_candidate_rate": ai_count / pre_count if pre_count else 0,
                "a_level_count": int(levels.get("A", 0)),
                "b_level_count": int(levels.get("B", 0)),
                "c_level_count": int(levels.get("C", 0)),
                "d_level_count": int(levels.get("D", 0)),
            }
        )
    return pd.DataFrame(rows)


def build_summary_by_keyword(content: pd.DataFrame) -> pd.DataFrame:
    if content.empty or "matched_keywords" not in content.columns:
        return empty_frame("summary_by_keyword")
    rows = []
    for _, row in content.iterrows():
        for keyword in split_terms(row.get("matched_keywords", "")):
            rows.append(
                {
                    "keyword_type": "matched_keywords",
                    "keyword": keyword,
                    "ai_candidate": bool(row.get("ai_candidate", False)),
                    "pre_purchase_decision": bool(row.get("pre_purchase_decision", False)),
                    "evidence_level": row.get("evidence_level", ""),
                    "example": row.get("content_text_clean", ""),
                }
            )
    if not rows:
        return empty_frame("summary_by_keyword")
    raw = pd.DataFrame(rows)
    grouped = []
    for keyword, group in raw.groupby("keyword"):
        levels = group["evidence_level"].value_counts()
        grouped.append(
            {
                "keyword_type": "matched_keywords",
                "keyword": keyword,
                "hit_count": len(group),
                "pre_purchase_count": int(group["pre_purchase_decision"].sum()),
                "ai_candidate_count": int(group["ai_candidate"].sum()),
                "evidence_distribution": " / ".join(
                    f"{level}:{int(levels.get(level, 0))}" for level in ["A", "B", "C", "D"]
                ),
                "example_1": group["example"].iloc[0] if len(group) else "",
            }
        )
    return pd.DataFrame(grouped).sort_values("hit_count", ascending=False)


def build_summary_by_month(content: pd.DataFrame) -> pd.DataFrame:
    if content.empty or "review_date" not in content.columns:
        return empty_frame("summary_by_month")
    rows = content.copy()
    if "content_role" in rows.columns:
        rows = rows[rows["content_role"] == "review"]
    rows = rows[rows["review_date"].fillna("").astype(str).str.len() >= 7]
    if rows.empty:
        return empty_frame("summary_by_month")

    rows = rows.assign(review_month=rows["review_date"].astype(str).str[:7])
    grouped = []
    for month, group in rows.groupby("review_month", dropna=False):
        ai_mask = group["ai_candidate"] if "ai_candidate" in group.columns else pd.Series(False, index=group.index)
        ai_group = group[ai_mask.astype(bool)]
        grouped.append(
            {
                "review_month": month,
                "review_count": len(group),
                "pre_purchase_decision_count": int(group["pre_purchase_decision"].sum())
                if "pre_purchase_decision" in group.columns
                else 0,
                "ai_candidate_count": int(ai_group["ai_candidate"].sum()) if "ai_candidate" in ai_group.columns else len(ai_group),
                "a_level_count": int((ai_group.get("evidence_level", pd.Series(dtype=str)) == "A").sum()),
                "b_level_count": int((ai_group.get("evidence_level", pd.Series(dtype=str)) == "B").sum()),
                "c_level_count": int((ai_group.get("evidence_level", pd.Series(dtype=str)) == "C").sum()),
                "ai_candidate_rate": len(ai_group) / len(group) if len(group) else 0,
                "top_ai_source_terms": "",
            }
        )
    return pd.DataFrame(grouped).sort_values("review_month")


def split_terms(value: object) -> list[str]:
    text = str(value or "")
    for sep in [",", "，", "|", "、"]:
        text = text.replace(sep, ";")
    return [term.strip() for term in text.split(";") if term.strip()]
