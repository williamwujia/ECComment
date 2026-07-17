from __future__ import annotations

import json


OUTPUT_SCHEMA = {
    "review_id": "string",
    "valid_review": True,
    "overall_sentiment": "positive | negative | mixed | neutral | noise",
    "main_target": "product | service | logistics | installation | brand | mixed | unclear",
    "purchase_decision_evidence": {
        "is_purchase_decision_evidence": True,
        "evidence_level": "S | A | B | C | D",
        "reason": "string",
    },
    "praise_items": [
        {
            "target": "product | service | logistics | installation | brand | mixed | unclear",
            "aspect": "string",
            "praise_family": "conclusion | function | reference | trust",
            "praise_method": "direct_satisfaction | function_confirmation | parameter_perception | scene_success | comparison_win | expectation_exceeded | value_recognition | risk_relief | family_feedback | repurchase_recommendation | service_facilitation",
            "scene": "string_or_unknown",
            "evidence_quote": "string",
            "evidence_strength": "S | A | B | C | D",
            "business_value": "high | medium | low",
            "notes": "string",
        }
    ],
    "complaint_items": [
        {
            "target": "product | service | logistics | installation | brand | mixed | unclear",
            "aspect": "string",
            "complaint_family": "product_fact | scene_fit | value | expectation_trust | fulfillment",
            "complaint_method": "hard_defect | function_underperformance | scene_mismatch | usage_friction | experience_conflict | value_doubt | expectation_gap | trust_damage | service_failure | logistics_packaging",
            "scene": "string_or_unknown",
            "evidence_quote": "string",
            "evidence_strength": "S | A | B | C | D",
            "severity": "high | medium | low",
            "fixability": "content_explainable | product_issue | service_issue | logistics_issue | unclear",
            "notes": "string",
        }
    ],
    "noise_flags": {
        "pure_service": False,
        "pure_logistics": False,
        "template_like": False,
        "customer_service_names": False,
        "too_short": False,
        "irrelevant": False,
    },
    "one_sentence_summary": "string",
}


class PromptBuilder:
    def __init__(self, prompt_version: str = "v1"):
        self.prompt_version = prompt_version

    def build_system_prompt(self) -> str:
        return (
            "你是一个电商评论结构化分析器。你的任务不是写总结，也不是生成营销建议，"
            "而是从单条评论中抽取结构化证据。你必须判断用户是否在夸奖、吐槽，评价对象，"
            "夸法或骂法，以及这条评论是否能作为购前决策证据。重要规则：只输出合法 json；"
            "不要输出 markdown；不要输出解释文字；没有原文证据就不能生成判断；不要把客服好评"
            "误判为产品好评；不要把物流好评误判为产品好评；不要把泛泛满意夸大为强证据；"
            "evidence_quote 必须来自原文，必须逐字复制原文中的连续片段，不能改写、不能概括、"
            "不能调整空格或标点。praise_family 只能是 conclusion、function、reference、trust；"
            "scene_success、comparison_win、function_confirmation 等只能放在 praise_method，绝不能放在 praise_family。"
            "请优先保证 praise_items、complaint_items、noise_flags 和 evidence_quote 准确；"
            "overall_sentiment、main_target、purchase_decision_evidence 会由程序根据明细证据复算。"
        )

    def build_user_prompt(self, comment: dict) -> str:
        review_id = comment.get("content_hash") or comment.get("content_id") or ""
        payload = json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
        return (
            "请分析以下电商评论，并只输出 json。\n"
            f"prompt_version: {self.prompt_version}\n"
            "商品信息：\n"
            f"- review_id: {review_id}\n"
            f"- product_title: {comment.get('product_title', '')}\n"
            f"- sku: {comment.get('sku', '')}\n"
            f"- source: {comment.get('source_file', '')}\n"
            f"- rating: {comment.get('rating', '')}\n"
            f"评论原文：{comment.get('content_text_clean') or comment.get('review_text_clean') or ''}\n"
            "枚举约束必须严格遵守：\n"
            "- praise_family 只能从 [conclusion, function, reference, trust] 中选择。\n"
            "- praise_method 才能使用 scene_success、comparison_win、function_confirmation 等夸法子类。\n"
            "- complaint_family 和 complaint_method 也不能互相混用。\n"
            "- evidence_quote 必须从评论原文中逐字复制一个连续子串。\n"
            "- 请优先抽取可复核的夸点、槽点和噪音；整体情绪和购前证据等级会由程序按明细复算。\n"
            "请严格按照以下 json 字段输出：\n"
            f"{payload}"
        )

    def build_batch_user_prompt(self, comments: list[dict]) -> str:
        items = [
            {
                "review_id": comment.get("content_hash") or comment.get("content_id") or "",
                "product_title": comment.get("product_title", ""),
                "sku": comment.get("sku", ""),
                "source": comment.get("source_file", ""),
                "rating": comment.get("rating", ""),
                "text": comment.get("content_text_clean") or comment.get("review_text_clean") or "",
            }
            for comment in comments
        ]
        payload = json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
        return (
            "Analyze each ecommerce content item independently and output valid JSON only.\n"
            f"prompt_version: {self.prompt_version}\n"
            'Return exactly this shape: {"items": [analysis_object, ...]}.\n'
            "The items array must contain one analysis object for every input item, in the same order.\n"
            "Each analysis_object must use its input review_id and must follow this schema:\n"
            f"{payload}\n"
            "Critical rules:\n"
            "- Do not merge items or compare items with each other.\n"
            "- evidence_quote must be an exact contiguous substring from that item's text.\n"
            "- If an item is too short, irrelevant, or noisy, still return a valid analysis object with "
            "overall_sentiment=noise and empty item arrays.\n"
            "- Prioritize item-level praise_items, complaint_items, noise_flags, and exact evidence_quote. "
            "The program will recompute overall_sentiment, main_target, and purchase_decision_evidence from the validated items.\n"
            "Input items:\n"
            f"{json.dumps(items, ensure_ascii=False, indent=2)}"
        )
