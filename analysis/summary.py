from __future__ import annotations

from collections import Counter, defaultdict


def _terms(rows: list[dict], field: str) -> Counter:
    counter: Counter = Counter()
    for row in rows:
        counter.update(term for term in str(row.get(field, "")).split(";") if term)
    return counter


def _top(counter: Counter, limit: int = 5) -> str:
    return ";".join(f"{term}:{count}" for term, count in counter.most_common(limit))


def build_summaries(content_all: list[dict], ai_candidates: list[dict]) -> dict:
    by_product: dict[tuple, list[dict]] = defaultdict(list)
    for row in content_all:
        key = (
            row.get("platform", ""),
            row.get("product_title", ""),
            row.get("shop_name", ""),
            row.get("product_id", ""),
        )
        by_product[key].append(row)

    products = []
    for key, rows in by_product.items():
        hashes = {row.get("content_hash") for row in rows}
        candidates = [row for row in rows if row.get("ai_candidate")]
        pre_purchase_rows = [row for row in rows if row.get("pre_purchase_decision")]
        count = len(hashes)
        denominator = len(pre_purchase_rows) or 0
        a_count = sum(row.get("ai_influence_level") == "A" for row in rows)
        b_count = sum(row.get("ai_influence_level") == "B" for row in rows)
        c_count = sum(row.get("ai_influence_level") == "C" for row in rows)
        d_count = sum(row.get("ai_influence_level") == "D" for row in rows)
        products.append(
            {
                "platform": key[0],
                "product_title": key[1],
                "shop_name": key[2],
                "product_id": key[3],
                "source_file_count": len({row.get("source_file") for row in rows}),
                "review_count": sum(row.get("content_role") == "review" for row in rows),
                "qa_question_count": sum(
                    row.get("content_role") == "question" for row in rows
                ),
                "qa_answer_count": sum(
                    row.get("content_role") == "answer" for row in rows
                ),
                "content_count": count,
                "ai_candidate_count": len(candidates),
                "a_level_count": a_count,
                "b_level_count": b_count,
                "c_level_count": c_count,
                "d_level_count": d_count,
                "a_b_count": a_count + b_count,
                "a_b_c_count": a_count + b_count + c_count,
                "pre_purchase_decision_count": denominator,
                "explicit_ai_rate": a_count / denominator if denominator else 0,
                "generic_ai_rate": b_count / denominator if denominator else 0,
                "inferred_ai_rate": c_count / denominator if denominator else 0,
                "ai_candidate_rate": len(candidates) / denominator if denominator else 0,
                "top_ai_source_terms": _top(_terms(candidates, "ai_source_terms")),
                "top_ai_action_terms": _top(_terms(candidates, "ai_action_terms")),
                "top_examples": " || ".join(
                    row.get("content_text_clean", "")[:100]
                    for row in sorted(
                        candidates,
                        key=lambda item: item.get("match_score", 0),
                        reverse=True,
                    )[:3]
                ),
            }
        )

    keyword_rows = []
    fields = {
        "ai_source": "ai_source_terms",
        "ai_action": "ai_action_terms",
        "purchase_context": "purchase_context_terms",
        "decision_context": "decision_context_terms",
        "research": "research_terms",
        "algorithm": "algorithm_terms",
    }
    for keyword_type, field in fields.items():
        examples: dict[str, list[str]] = defaultdict(list)
        counts = _terms(ai_candidates, field)
        for row in ai_candidates:
            for term in str(row.get(field, "")).split(";"):
                text = row.get("content_text_clean", "")
                if term and text and text not in examples[term]:
                    examples[term].append(text)
        for keyword, hit_count in counts.most_common():
            values = examples[keyword][:3]
            keyword_rows.append(
                {
                    "keyword_type": keyword_type,
                    "keyword": keyword,
                    "hit_count": hit_count,
                    "example_1": values[0] if len(values) > 0 else "",
                    "example_2": values[1] if len(values) > 1 else "",
                    "example_3": values[2] if len(values) > 2 else "",
                }
            )
    pre_purchase_details = [
        row for row in content_all if row.get("pre_purchase_decision")
    ]

    by_month: dict[str, list[dict]] = defaultdict(list)
    for row in content_all:
        if row.get("content_role") != "review":
            continue
        review_date = str(row.get("review_date", "")).strip()
        if len(review_date) >= 7:
            by_month[review_date[:7]].append(row)

    month_rows = []
    for month, rows in sorted(by_month.items()):
        candidates = [row for row in rows if row.get("ai_candidate")]
        pre_purchase_count = sum(bool(row.get("pre_purchase_decision")) for row in rows)
        a_count = sum(row.get("evidence_level") == "A" for row in candidates)
        b_count = sum(row.get("evidence_level") == "B" for row in candidates)
        c_count = sum(row.get("evidence_level") == "C" for row in candidates)
        month_rows.append(
            {
                "review_month": month,
                "review_count": len(rows),
                "pre_purchase_decision_count": pre_purchase_count,
                "ai_candidate_count": len(candidates),
                "a_level_count": a_count,
                "b_level_count": b_count,
                "c_level_count": c_count,
                "ai_candidate_rate": len(candidates) / len(rows) if rows else 0,
                "top_ai_source_terms": _top(_terms(candidates, "ai_source_terms")),
            }
        )
    return {
        "summary_by_product": products,
        "summary_by_keyword": keyword_rows,
        "pre_purchase_details": pre_purchase_details,
        "summary_by_month": month_rows,
    }
