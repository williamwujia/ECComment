from __future__ import annotations

import unittest

from sentiment_llm_fast import build_fast_user_prompt, parse_fast_jsonl, validate_fast_rows
from sentiment_pipeline import process_sentiment_for_comments, select_sentiment_targets
from sentiment_rules import try_rule_sentiment


class FakeTextClient:
    def __init__(self):
        self.calls = []
        self.last_timing = {"total_seconds": 0.1, "completion_tokens": 20, "max_tokens": 500}

    def chat_text(self, system_prompt: str, user_prompt: str, model: str | None = None, max_tokens: int = 2000):
        self.calls.append((system_prompt, user_prompt, model, max_tokens))
        if "e=证据句" in system_prompt:
            return '{"i":2,"e":"亮度足；有点反光","r":"满意但有反光边界","g":"可说明桌面材质适配建议"}', {
                "completion_tokens": 30
            }
        return '\n'.join(
            [
                '{"i":2,"s":"M","sc":7,"p":"E","n":"S","c":3}',
                '{"i":3,"s":"N","sc":2,"p":"-","n":"E","c":3}',
            ]
        ), {"completion_tokens": 40}


class SentimentTests(unittest.TestCase):
    def test_rule_sentiment_handles_short_positive(self):
        result = try_rule_sentiment({"content_id": 1, "content_text_clean": "不错，很满意"})
        self.assertIsNotNone(result)
        self.assertEqual(result["s"], "P")
        self.assertEqual(result["source"], "rule")

    def test_rule_sentiment_sends_mixed_marker_to_llm(self):
        self.assertIsNone(try_rule_sentiment({"content_id": 1, "content_text_clean": "不错，但是有点反光"}))

    def test_fast_jsonl_parser_filters_extra_text_and_validates(self):
        rows = parse_fast_jsonl('extra\n{"i":1,"s":"P","sc":8,"p":"S","n":"-","c":3}\n```')
        valid, invalid = validate_fast_rows(rows)
        self.assertEqual(len(valid), 1)
        self.assertEqual(invalid, [])

    def test_fast_prompt_uses_compact_jsonl(self):
        prompt = build_fast_user_prompt([{"content_id": 1, "content_text_clean": "亮度可以"}])
        self.assertEqual(prompt, '{"i":1,"t":"亮度可以"}')

    def test_pipeline_uses_rules_then_llm_and_detail_candidates(self):
        comments = [
            {"content_id": 1, "content_role": "review", "content_text_clean": "很好"},
            {"content_id": 2, "content_role": "review", "content_text_clean": "亮度足，但是有点反光"},
            {"content_id": 3, "content_role": "review", "content_text_clean": "太刺眼了，准备退货"},
        ]
        result = process_sentiment_for_comments(
            comments,
            client=FakeTextClient(),
            model_name="deepseek-v4-flash",
            batch_size=50,
            detail_limit=1,
            use_local_rules=True,
        )
        self.assertEqual(result.total_count, 3)
        self.assertEqual(result.rule_count, 1)
        self.assertEqual(result.llm_fast_count, 2)
        self.assertEqual(result.detail_count, 1)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(result.detail_rows[0]["content_id"], 2)
        self.assertEqual(result.detail_rows[0]["sentiment_label"], "M")
        self.assertEqual(result.detail_rows[0]["sentiment_score"], 7)
        self.assertEqual(result.detail_rows[0]["praise_code"], "E")
        self.assertIn("praise_cn", result.detail_rows[0])
        self.assertEqual(result.detail_rows[0]["complaint_code"], "S")
        self.assertIn("complaint_cn", result.detail_rows[0])
        self.assertIn("sentiment_evidence", result.detail_rows[0])

    def test_select_sentiment_targets_only_reviews_with_text_and_limit(self):
        rows = [
            {"content_id": 1, "content_role": "review", "content_text_clean": "很好"},
            {"content_id": 4, "content_role": "followup", "content_text_clean": "追评也不错"},
            {"content_id": 2, "content_role": "question", "content_text_clean": "哪个好"},
            {"content_id": 3, "content_role": "review", "content_text_clean": " "},
        ]
        self.assertEqual(select_sentiment_targets(rows, limit=2), rows[:2])


if __name__ == "__main__":
    unittest.main()
