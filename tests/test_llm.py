from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from llm.comment_analysis_service import (
    LLMCommentAnalysisService,
    derive_sentiment_fields,
    repair_evidence_quotes,
    sanitize_llm_result,
)
from llm.hash_utils import build_input_hash
from llm.prompt_builder import PromptBuilder
from llm.provider_config import load_provider_config
from llm.validator import LLMResultValidator
from main import parse_args, parse_limit, parse_retry_delays, select_llm_review_targets


COMMENT = {
    "content_id": 1,
    "content_hash": "abc123",
    "content_role": "review",
    "product_title": "Desk lamp",
    "sku": "white",
    "source_file": "sample.html",
    "content_text_clean": "Soft light for homework, not harsh, but the base takes desk space.",
}


VALID_RESULT = {
    "review_id": "abc123",
    "valid_review": True,
    "overall_sentiment": "mixed",
    "main_target": "product",
    "purchase_decision_evidence": {
        "is_purchase_decision_evidence": True,
        "evidence_level": "S",
        "reason": "Specific use case, product experience, and drawback.",
    },
    "praise_items": [
        {
            "target": "product",
            "aspect": "light_comfort",
            "praise_family": "function",
            "praise_method": "function_confirmation",
            "scene": "homework",
            "evidence_quote": "Soft light for homework, not harsh",
            "evidence_strength": "A",
            "business_value": "high",
            "notes": "",
        }
    ],
    "complaint_items": [
        {
            "target": "product",
            "aspect": "space_occupation",
            "complaint_family": "scene_fit",
            "complaint_method": "usage_friction",
            "scene": "desk_use",
            "evidence_quote": "the base takes desk space",
            "evidence_strength": "A",
            "severity": "low",
            "fixability": "content_explainable",
            "notes": "",
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
    "one_sentence_summary": "The lamp is comfortable for homework, but the base takes space.",
}


class FakeDeepSeekClient:
    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 2000,
    ):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.model = model
        self.max_tokens = max_tokens
        return VALID_RESULT, {"total_tokens": 123}, "{}"


class FakeBatchDeepSeekClient:
    def __init__(self):
        self.call_count = 0

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 2000,
    ):
        self.call_count += 1
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.model = model
        self.max_tokens = max_tokens
        return {"items": [VALID_RESULT, VALID_RESULT]}, {"total_tokens": 456}, '{"items":[]}'


class LLMTests(unittest.TestCase):
    def test_provider_config_loads_selected_provider_and_key_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "llm.json"
            path.write_text(
                """
                {
                  "default_provider": "deepseek",
                  "providers": {
                    "deepseek": {
                      "api_key_file": "config/secrets/deepseek_api_key.txt",
                      "base_url": "https://api.deepseek.com",
                      "default_model": "DeepSeek-V4-Flash-Preview",
                      "default_batch_size": 50,
                      "timeout_seconds": 90,
                      "target_content_count": 500,
                      "target_total_seconds": 120,
                      "capacity_note": "calibrated for UX target"
                    }
                  }
                }
                """,
                encoding="utf-8",
            )
            config = load_provider_config(path, "deepseek")
        self.assertEqual(config.provider, "deepseek")
        self.assertEqual(config.api_key_file, "config/secrets/deepseek_api_key.txt")
        self.assertEqual(config.default_model, "DeepSeek-V4-Flash-0731")
        self.assertEqual(config.default_batch_size, 50)
        self.assertEqual(config.timeout_seconds, 90)
        self.assertEqual(config.target_content_count, 500)
        self.assertEqual(config.target_total_seconds, 120)
        self.assertEqual(config.capacity_note, "calibrated for UX target")

    def test_prompt_mentions_json_and_review_text(self):
        builder = PromptBuilder("v1")
        prompt = builder.build_user_prompt(COMMENT)
        self.assertIn("json", prompt.lower())
        self.assertIn(COMMENT["content_text_clean"], prompt)

    def test_input_hash_changes_with_prompt_version(self):
        self.assertNotEqual(build_input_hash(COMMENT, "v1"), build_input_hash(COMMENT, "v2"))

    def test_validator_accepts_valid_result(self):
        validation = LLMResultValidator().validate(VALID_RESULT, COMMENT["content_text_clean"])
        self.assertTrue(validation.valid, validation.error_message)

    def test_validator_rejects_quote_not_in_original_text(self):
        bad = {
            **VALID_RESULT,
            "praise_items": [{**VALID_RESULT["praise_items"][0], "evidence_quote": "rewritten evidence"}],
        }
        validation = LLMResultValidator().validate(bad, COMMENT["content_text_clean"])
        self.assertFalse(validation.valid)
        self.assertIn("substring", validation.error_message)

    def test_repair_evidence_quotes_restores_whitespace_from_original(self):
        result = {
            "praise_items": [],
            "complaint_items": [{"evidence_quote": "appcouldbebetter"}],
        }
        repair_evidence_quotes(result, "The app could be better after setup.")
        self.assertEqual(result["complaint_items"][0]["evidence_quote"], "app could be better")

    def test_sanitize_llm_result_does_not_guess_or_drop_invalid_items(self):
        result = {
            "praise_items": [
                {**VALID_RESULT["praise_items"][0], "praise_family": "value"},
                {**VALID_RESULT["praise_items"][0], "evidence_quote": "rewritten evidence"},
            ],
            "complaint_items": [
                {**VALID_RESULT["complaint_items"][0], "evidence_quote": "rewritten complaint"},
            ],
        }
        sanitize_llm_result(result, COMMENT["content_text_clean"])
        self.assertEqual(result["praise_items"][0]["praise_family"], "value")
        self.assertEqual(len(result["praise_items"]), 2)
        self.assertEqual(len(result["complaint_items"]), 1)

    def test_derive_sentiment_fields_detects_mixed_chinese_review(self):
        result = {
            **VALID_RESULT,
            "overall_sentiment": "positive",
            "main_target": "service",
            "purchase_decision_evidence": {
                "is_purchase_decision_evidence": False,
                "evidence_level": "D",
                "reason": "model supplied value",
            },
            "praise_items": [
                {
                    **VALID_RESULT["praise_items"][0],
                    "evidence_quote": "光线很柔，不刺眼",
                    "evidence_strength": "A",
                }
            ],
            "complaint_items": [
                {
                    **VALID_RESULT["complaint_items"][0],
                    "evidence_quote": "底座有点占地方",
                    "evidence_strength": "A",
                }
            ],
        }
        derive_sentiment_fields(result)
        self.assertEqual(result["overall_sentiment"], "mixed")
        self.assertEqual(result["main_target"], "product")
        self.assertTrue(result["purchase_decision_evidence"]["is_purchase_decision_evidence"])
        self.assertEqual(result["purchase_decision_evidence"]["evidence_level"], "A")

    def test_derive_sentiment_fields_caps_generic_satisfaction_as_weak_evidence(self):
        result = {
            **VALID_RESULT,
            "praise_items": [
                {
                    **VALID_RESULT["praise_items"][0],
                    "target": "product",
                    "aspect": "general_satisfaction",
                    "praise_family": "conclusion",
                    "praise_method": "direct_satisfaction",
                    "evidence_quote": "不错，很满意",
                    "evidence_strength": "A",
                    "business_value": "low",
                }
            ],
            "complaint_items": [],
            "noise_flags": {key: False for key in VALID_RESULT["noise_flags"]},
        }
        derive_sentiment_fields(result)
        self.assertEqual(result["overall_sentiment"], "positive")
        self.assertEqual(result["main_target"], "product")
        self.assertFalse(result["purchase_decision_evidence"]["is_purchase_decision_evidence"])
        self.assertEqual(result["purchase_decision_evidence"]["evidence_level"], "C")

    def test_derive_sentiment_fields_keeps_pure_service_out_of_purchase_evidence(self):
        result = {
            **VALID_RESULT,
            "praise_items": [
                {
                    **VALID_RESULT["praise_items"][0],
                    "target": "service",
                    "aspect": "pre_purchase_consultation",
                    "praise_family": "trust",
                    "praise_method": "service_facilitation",
                    "evidence_quote": "客服都耐心解答",
                    "evidence_strength": "A",
                    "business_value": "medium",
                }
            ],
            "complaint_items": [],
            "noise_flags": {
                **VALID_RESULT["noise_flags"],
                "pure_service": True,
            },
        }
        derive_sentiment_fields(result)
        self.assertEqual(result["overall_sentiment"], "positive")
        self.assertEqual(result["main_target"], "service")
        self.assertFalse(result["purchase_decision_evidence"]["is_purchase_decision_evidence"])
        self.assertEqual(result["purchase_decision_evidence"]["evidence_level"], "D")

    def test_select_llm_review_targets_only_reviews_and_limit(self):
        rows = [
            COMMENT,
            {**COMMENT, "content_id": 2, "content_role": "question"},
            {**COMMENT, "content_id": 3, "content_role": "answer", "content_text_clean": "  "},
        ]
        self.assertEqual(select_llm_review_targets(rows), rows[:2])
        self.assertEqual(select_llm_review_targets(rows, limit=1), [COMMENT])

    def test_llm_analysis_is_enabled_by_default_and_can_be_disabled(self):
        with patch("sys.argv", ["main.py"]):
            args = parse_args()
            self.assertFalse(args.llm_analyze)
            self.assertTrue(args.enable_sentiment)
            self.assertEqual(args.sentiment_limit, "all")
            self.assertEqual(args.detail_limit, 50)
            self.assertIsNone(args.llm_timeout)
            self.assertEqual(args.llm_retry_delays, "1,3")
            self.assertIsNone(args.llm_batch_size)
        with patch("sys.argv", ["main.py", "--llm-analyze", "--no-enable-sentiment"]):
            args = parse_args()
            self.assertTrue(args.llm_analyze)
            self.assertFalse(args.enable_sentiment)

    def test_parse_retry_delays(self):
        self.assertEqual(parse_retry_delays("1, 3,5"), (1, 3, 5))
        self.assertEqual(parse_retry_delays(""), ())
        with self.assertRaises(ValueError):
            parse_retry_delays("-1")

    def test_parse_limit_accepts_all(self):
        self.assertIsNone(parse_limit(None, "--limit"))
        self.assertIsNone(parse_limit("all", "--limit"))
        self.assertEqual(parse_limit("20", "--limit"), 20)
        with self.assertRaises(ValueError):
            parse_limit("-1", "--limit")

    def test_service_builds_analysis_and_item_rows(self):
        service = LLMCommentAnalysisService(
            deepseek_client=FakeDeepSeekClient(),
            prompt_builder=PromptBuilder("v1"),
            validator=LLMResultValidator(),
            retry_delays=(0,),
        )
        result = service.analyze_comments([COMMENT], "DeepSeek-V4-Flash-0731", "v1")
        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(result.analysis_rows[0]["overall_sentiment"], "mixed")
        self.assertEqual(result.praise_rows[0]["praise_method"], "function_confirmation")
        self.assertEqual(result.complaint_rows[0]["complaint_method"], "usage_friction")

    def test_service_batches_comments_into_one_llm_call(self):
        client = FakeBatchDeepSeekClient()
        service = LLMCommentAnalysisService(
            deepseek_client=client,
            prompt_builder=PromptBuilder("v1"),
            validator=LLMResultValidator(),
            retry_delays=(0,),
        )
        result = service.analyze_comments(
            [COMMENT, {**COMMENT, "content_id": 2, "content_hash": "def456"}],
            "DeepSeek-V4-Flash-0731",
            "v1",
            batch_size=2,
        )
        self.assertEqual(client.call_count, 1)
        self.assertIn('"items"', client.user_prompt)
        self.assertGreaterEqual(client.max_tokens, 4000)
        self.assertEqual(result.success_count, 2)
        self.assertEqual(len(result.analysis_rows), 2)


if __name__ == "__main__":
    unittest.main()
