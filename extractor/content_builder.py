from __future__ import annotations

from utils.dedupe import content_hash, dedupe_records


META_FIELDS = (
    "source_file",
    "platform",
    "product_title",
    "shop_name",
    "product_url",
    "product_id",
)


def build_content_all(reviews: list[dict], qa_pairs: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for review in reviews:
        row = {
            **{field: review.get(field, "") for field in META_FIELDS},
            "record_type": "review",
            "content_role": "review",
            "content_text_raw": review.get("review_text_raw", ""),
            "content_text_clean": review.get("review_text_clean", ""),
            "parent_text_clean": "",
            "review_time": review.get("review_time", ""),
            "review_date": review.get("review_date", ""),
            "sku": review.get("sku", ""),
            "user_name_masked": review.get("user_name_masked", ""),
            "user_status": "",
            "content_order": review.get("review_order", ""),
            "extract_confidence": review.get("extract_confidence", ""),
        }
        row["content_hash"] = content_hash(row)
        rows.append(row)

    for pair in qa_pairs:
        base = {field: pair.get(field, "") for field in META_FIELDS}
        question = {
            **base,
            "record_type": "qa",
            "content_role": "question",
            "content_text_raw": pair.get("question_text_raw", ""),
            "content_text_clean": pair.get("question_text_clean", ""),
            "parent_text_clean": "",
            "review_time": "",
            "review_date": "",
            "sku": "",
            "user_name_masked": "",
            "user_status": "",
            "content_order": pair.get("qa_order", ""),
            "extract_confidence": pair.get("extract_confidence", ""),
        }
        question["content_hash"] = content_hash(question)
        rows.append(question)

        if pair.get("answer_text_clean"):
            answer = {
                **base,
                "record_type": "qa",
                "content_role": "answer",
                "content_text_raw": pair.get("answer_text_raw", ""),
                "content_text_clean": pair.get("answer_text_clean", ""),
                "parent_text_clean": pair.get("question_text_clean", ""),
                "review_time": "",
                "review_date": "",
                "sku": "",
                "user_name_masked": "",
                "user_status": pair.get("answer_user_status", ""),
                "content_order": pair.get("qa_order", ""),
                "extract_confidence": pair.get("extract_confidence", ""),
            }
            answer["content_hash"] = content_hash(answer)
            rows.append(answer)

    rows = dedupe_records(rows)
    for index, row in enumerate(rows, 1):
        row["content_id"] = index
    return rows
