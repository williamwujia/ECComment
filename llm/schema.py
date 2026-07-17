from __future__ import annotations

OVERALL_SENTIMENTS = {"positive", "negative", "mixed", "neutral", "noise"}
TARGETS = {"product", "service", "logistics", "installation", "brand", "mixed", "unclear"}
EVIDENCE_LEVELS = {"S", "A", "B", "C", "D"}
PRAISE_FAMILIES = {"conclusion", "function", "reference", "trust"}
PRAISE_METHODS = {
    "direct_satisfaction",
    "function_confirmation",
    "parameter_perception",
    "scene_success",
    "comparison_win",
    "expectation_exceeded",
    "value_recognition",
    "risk_relief",
    "family_feedback",
    "repurchase_recommendation",
    "service_facilitation",
}
BUSINESS_VALUES = {"high", "medium", "low"}
COMPLAINT_FAMILIES = {
    "product_fact",
    "scene_fit",
    "value",
    "expectation_trust",
    "fulfillment",
}
COMPLAINT_METHODS = {
    "hard_defect",
    "function_underperformance",
    "scene_mismatch",
    "usage_friction",
    "experience_conflict",
    "value_doubt",
    "expectation_gap",
    "trust_damage",
    "service_failure",
    "logistics_packaging",
}
SEVERITIES = {"high", "medium", "low"}
FIXABILITIES = {
    "content_explainable",
    "product_issue",
    "service_issue",
    "logistics_issue",
    "unclear",
}

REQUIRED_TOP_LEVEL_FIELDS = {
    "review_id",
    "valid_review",
    "overall_sentiment",
    "main_target",
    "purchase_decision_evidence",
    "praise_items",
    "complaint_items",
    "noise_flags",
    "one_sentence_summary",
}
REQUIRED_PURCHASE_FIELDS = {
    "is_purchase_decision_evidence",
    "evidence_level",
    "reason",
}
REQUIRED_NOISE_FIELDS = {
    "pure_service",
    "pure_logistics",
    "template_like",
    "customer_service_names",
    "too_short",
    "irrelevant",
}
REQUIRED_PRAISE_FIELDS = {
    "target",
    "aspect",
    "praise_family",
    "praise_method",
    "scene",
    "evidence_quote",
    "evidence_strength",
    "business_value",
    "notes",
}
REQUIRED_COMPLAINT_FIELDS = {
    "target",
    "aspect",
    "complaint_family",
    "complaint_method",
    "scene",
    "evidence_quote",
    "evidence_strength",
    "severity",
    "fixability",
    "notes",
}

