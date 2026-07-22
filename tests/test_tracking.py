from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from matching.content_identity import build_identity_keys
from matching.overlap_detector import detect_overlap_boundary
from project.updater import (
    backfill_project_sentiment,
    create_named_project,
    create_project,
    project_filename_stem,
    reanalyze_project,
    register_product,
    update_project_files,
    update_project_item,
)


def _keyed(text: str, item_key: str = "tmall:123", user: str = "u") -> dict:
    row = {
        "content_role": "review",
        "content_text_clean": text,
        "parent_text_clean": "",
        "user_name_masked": user,
        "content_time": "2026-07-01",
        "sku": "default",
    }
    row.update(build_identity_keys(row, item_key))
    return row


def _html(product_id: str, reviews: list[tuple[str, str, str]]) -> str:
    cards = "\n".join(
        f"""
        <div class="review-item">
          <div class="review-content">{text}</div>
          <div class="meta">{review_time}</div>
          <div class="user-name">{user}</div>
        </div>
        """
        for text, review_time, user in reviews
    )
    return f"""
    <html>
      <head>
        <title>测试商品 - 天猫</title>
        <link rel="canonical" href="https://detail.tmall.com/item.htm?id={product_id}">
      </head>
      <body>{cards}</body>
    </html>
    """


class FakeTrackingSentimentClient:
    default_model = "fake-sentiment"

    def __init__(self):
        self.calls = []
        self.last_timing = {"total_seconds": 0.01}

    def chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 2000,
    ):
        self.calls.append((system_prompt, user_prompt, model, max_tokens))
        payloads = [
            json.loads(line)
            for line in user_prompt.splitlines()
            if line.strip()
        ]
        if "e=证据句" in system_prompt:
            return "\n".join(
                json.dumps(
                    {
                        "i": row["i"],
                        "e": "光线柔和但有点反光",
                        "r": "优点与边界并存",
                        "g": "可用于桌面材质适配说明",
                    },
                    ensure_ascii=False,
                )
                for row in payloads
            ), {}
        return "\n".join(
            json.dumps(
                {
                    "i": row["i"],
                    "s": "M",
                    "sc": 7,
                    "p": "E",
                    "n": "S",
                    "c": 3,
                },
                ensure_ascii=False,
            )
            for row in payloads
        ), {}


class TrackingTests(unittest.TestCase):
    def test_create_named_project_uses_safe_readable_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = create_named_project(
                temp_dir,
                " 测试 / 项目? ",
                "追踪评论变化",
                project_id="p1",
            )

            self.assertEqual(workbook.name, "测试 项目.xlsx")
            project_info = pd.read_excel(
                workbook,
                sheet_name="project_info",
                dtype=str,
            )
            self.assertEqual(project_info.iloc[0]["project_id"], "p1")
            self.assertEqual(project_info.iloc[0]["project_name"], "测试 / 项目?")
            self.assertEqual(project_info.iloc[0]["objective"], "追踪评论变化")

    def test_create_named_project_rejects_duplicate_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            create_named_project(
                temp_dir,
                "测试项目",
                project_id="p1",
            )

            with self.assertRaisesRegex(FileExistsError, "已存在同名项目"):
                create_named_project(
                    temp_dir,
                    "测试项目",
                    project_id="p2",
                )

    def test_project_filename_stem_handles_windows_reserved_name(self):
        self.assertEqual(project_filename_stem("CON"), "CON_项目")

    def test_overlap_requires_contiguous_sequence(self):
        old = [_keyed(value) for value in ["A", "B", "C", "D", "E"]]
        new = [_keyed(value) for value in ["X", "Y", "Z", "A", "B", "C"]]

        result = detect_overlap_boundary(old, new)

        self.assertEqual(result["status"], "overlap_found")
        self.assertEqual(result["overlap_length"], 3)
        self.assertEqual(result["new_prefix_end"], 3)

    def test_identity_is_scoped_to_item_key(self):
        left = _keyed("同一条短评", "tmall:111")
        right = _keyed("同一条短评", "tmall:222")

        self.assertNotEqual(left["composite_key"], right["composite_key"])
        self.assertNotEqual(left["text_key"], right["text_key"])

    def test_registers_same_model_as_two_commerce_items(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "project.xlsx"
            create_project(str(workbook), "p1", "测试项目")
            register_product(
                str(workbook),
                "p1",
                "tmall",
                "111",
                brand_product_id="same_model",
            )
            register_product(
                str(workbook),
                "p1",
                "tmall",
                "222",
                brand_product_id="same_model",
            )

            products = pd.read_excel(workbook, sheet_name="products", dtype=str)

            self.assertEqual(set(products["item_key"]), {"tmall:111", "tmall:222"})
            self.assertEqual(set(products["brand_product_id"]), {"same_model"})

    def test_first_import_then_incremental_overlap_and_duplicate_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook = root / "project.xlsx"
            first = root / "first.html"
            second = root / "second.html"
            first.write_text(
                _html(
                    "123",
                    [
                        ("review A", "2026-07-05", "u1"),
                        ("review B", "2026-07-04", "u2"),
                        ("review C", "2026-07-03", "u3"),
                        ("review D", "2026-07-02", "u4"),
                        ("review E", "2026-07-01", "u5"),
                    ],
                ),
                encoding="utf-8",
            )
            second.write_text(
                _html(
                    "123",
                    [
                        ("review X", "2026-07-08", "u8"),
                        ("review Y", "2026-07-07", "u7"),
                        ("review Z", "2026-07-06", "u6"),
                        ("review A", "2026-07-05", "u1"),
                        ("review B", "2026-07-04", "u2"),
                        ("review C", "2026-07-03", "u3"),
                    ],
                ),
                encoding="utf-8",
            )
            create_project(str(workbook), "p1", "测试项目")

            batch_preview = update_project_files(
                str(workbook),
                "p1",
                [str(first), str(second)],
                dry_run=True,
                capture_time="2026-07-08 12:00:00",
            )
            first_result = update_project_item(
                str(workbook),
                "p1",
                None,
                str(first),
                capture_time="2026-07-05 12:00:00",
                enable_sentiment=False,
            )
            second_result = update_project_item(
                str(workbook),
                "p1",
                None,
                str(second),
                capture_time="2026-07-08 12:00:00",
                enable_sentiment=False,
            )
            duplicate_result = update_project_item(
                str(workbook),
                "p1",
                None,
                str(second),
                capture_time="2026-07-08 12:00:00",
                enable_sentiment=False,
            )

            master = pd.read_excel(workbook, sheet_name="content_master")
            update_log = pd.read_excel(workbook, sheet_name="update_log")
            self.assertEqual(batch_preview[0]["boundary_status"], "first_import")
            self.assertEqual(batch_preview[1]["boundary_status"], "overlap_found")
            self.assertEqual(batch_preview[1]["new_count"], 3)
            self.assertEqual(first_result["boundary_status"], "first_import")
            self.assertEqual(first_result["new_count"], 5)
            self.assertEqual(second_result["boundary_status"], "overlap_found")
            self.assertEqual(second_result["overlap_length"], 3)
            self.assertEqual(second_result["new_count"], 3)
            self.assertEqual(len(master), 8)
            self.assertEqual(duplicate_result["new_count"], 0)
            self.assertEqual(duplicate_result["result"], "warning")
            self.assertEqual(len(update_log), 3)

    def test_page_product_id_is_authoritative(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook = root / "project.xlsx"
            page = root / "page.html"
            page.write_text(
                _html("222", [("review A", "2026-07-01", "u1")]),
                encoding="utf-8",
            )
            create_project(str(workbook), "p1", "测试项目")

            result = update_project_item(
                str(workbook),
                "p1",
                "111",
                str(page),
                enable_sentiment=False,
            )

            snapshots = pd.read_excel(workbook, sheet_name="snapshots")
            products = pd.read_excel(workbook, sheet_name="products")
            self.assertEqual(result["item_key"], "tmall:222")
            self.assertFalse(result["product_id_match"])
            self.assertEqual(products.iloc[0]["platform_product_id"], 222)
            self.assertEqual(snapshots.iloc[0]["extracted_product_id"], 222)

    def test_page_without_product_id_is_rejected_without_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook = root / "project.xlsx"
            page = root / "missing-id.html"
            page.write_text(
                "<html><head><title>测试商品 - 天猫</title></head>"
                "<body><div class='review-item'>review A</div></body></html>",
                encoding="utf-8",
            )
            create_project(str(workbook), "p1", "测试项目")

            with self.assertRaisesRegex(ValueError, "未识别到商品 ID"):
                update_project_item(
                    str(workbook),
                    "p1",
                    None,
                    str(page),
                    enable_sentiment=False,
                )

            self.assertTrue(pd.read_excel(workbook, sheet_name="snapshots").empty)
            self.assertTrue(pd.read_excel(workbook, sheet_name="products").empty)

    def test_multiple_files_are_processed_in_one_batch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook = root / "project.xlsx"
            first = root / "first.html"
            second = root / "second.html"
            first.write_text(
                _html("111", [("review A", "2026-07-01", "u1")]),
                encoding="utf-8",
            )
            second.write_text(
                _html("222", [("review B", "2026-07-01", "u2")]),
                encoding="utf-8",
            )
            create_project(str(workbook), "p1", "测试项目")

            results = update_project_files(
                str(workbook),
                "p1",
                [str(first), str(second)],
                enable_sentiment=False,
            )

            products = pd.read_excel(workbook, sheet_name="products", dtype=str)
            self.assertEqual(len(results), 2)
            self.assertEqual({item["item_key"] for item in results}, {"tmall:111", "tmall:222"})
            self.assertEqual(set(products["item_key"]), {"tmall:111", "tmall:222"})

    def test_incremental_update_persists_rule_and_llm_sentiment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook = root / "project.xlsx"
            page = root / "sentiment.html"
            page.write_text(
                _html(
                    "333",
                    [
                        ("不错，很满意", "2026-07-02", "u1"),
                        ("光线柔和，但是有点反光", "2026-07-01", "u2"),
                    ],
                ),
                encoding="utf-8",
            )
            create_project(str(workbook), "p1", "测试项目")
            client = FakeTrackingSentimentClient()

            result = update_project_item(
                str(workbook),
                "p1",
                None,
                str(page),
                enable_sentiment=True,
                sentiment_client=client,
                sentiment_model="fake-sentiment",
            )

            sentiment = pd.read_excel(workbook, sheet_name="sentiment_fast")
            detail = pd.read_excel(workbook, sheet_name="sentiment_detail")
            analysis = pd.read_excel(workbook, sheet_name="analysis")
            update_log = pd.read_excel(workbook, sheet_name="update_log")
            self.assertEqual(result["sentiment_status"], "success")
            self.assertEqual(result["sentiment_rule_count"], 0)
            self.assertEqual(result["sentiment_llm_count"], 2)
            self.assertEqual(result["sentiment_strategy"], "full_llm")
            self.assertEqual(len(sentiment), 2)
            self.assertEqual(len(detail), 2)
            self.assertEqual(set(analysis["sentiment"]), {"M"})
            self.assertEqual(update_log.iloc[0]["sentiment_status"], "success")
            self.assertEqual(
                update_log.iloc[0]["sentiment_strategy"],
                "full_llm",
            )
            self.assertGreaterEqual(len(client.calls), 2)

            reanalyze_project(str(workbook), "p1")
            reanalyzed = pd.read_excel(workbook, sheet_name="analysis")
            self.assertEqual(set(reanalyzed["sentiment"]), {"M"})

    def test_backfill_sentiment_only_processes_missing_reviews(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook = root / "project.xlsx"
            page = root / "historical.html"
            page.write_text(
                _html(
                    "444",
                    [
                        ("不错，很满意", "2026-07-02", "u1"),
                        ("光线柔和，但是有点反光", "2026-07-01", "u2"),
                    ],
                ),
                encoding="utf-8",
            )
            create_project(str(workbook), "p1", "测试项目")
            update_project_item(
                str(workbook),
                "p1",
                None,
                str(page),
                enable_sentiment=False,
            )
            client = FakeTrackingSentimentClient()

            preview = backfill_project_sentiment(
                str(workbook),
                "p1",
                dry_run=True,
            )
            result = backfill_project_sentiment(
                str(workbook),
                "p1",
                client=client,
                model="fake-sentiment",
            )
            repeated = backfill_project_sentiment(
                str(workbook),
                "p1",
                client=client,
                model="fake-sentiment",
            )

            sentiment = pd.read_excel(
                workbook,
                sheet_name="sentiment_fast",
            )
            analysis = pd.read_excel(workbook, sheet_name="analysis")
            self.assertEqual(preview["candidate_count"], 2)
            self.assertEqual(preview["rule_target_count"], 0)
            self.assertEqual(preview["llm_target_count"], 2)
            self.assertEqual(preview["sentiment_strategy"], "full_llm")
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["rule_count"], 0)
            self.assertEqual(result["llm_count"], 2)
            self.assertEqual(len(sentiment), 2)
            self.assertEqual(set(analysis["sentiment"]), {"M"})
            self.assertEqual(repeated["status"], "nothing_to_do")
            self.assertEqual(repeated["candidate_count"], 0)


class ReviewCsvImportTests(unittest.TestCase):
    def test_combined_jd_csv_is_split_and_merged_into_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "project.xlsx"
            csv_path = root / "jd_reviews.csv"
            create_project(str(workbook), "p1", "消费者反馈洞察")
            pd.DataFrame(
                [
                    {
                        "platform": "jd",
                        "product_id": "13745188",
                        "product_url": "https://item.jd.com/13745188.html",
                        "product_title": "百科全书",
                        "user_name_masked": "a***1",
                        "rating": "5",
                        "review_time": "2026-07-20",
                        "sku": "65册",
                        "review_text_raw": "孩子很喜欢。",
                    },
                    {
                        "platform": "jd",
                        "product_id": "100244103673",
                        "product_url": "https://item.jd.com/100244103673.html",
                        "product_title": "另一套图书",
                        "user_name_masked": "b***2",
                        "rating": "5",
                        "review_time": "2026-07-21",
                        "sku": "套装",
                        "review_text_raw": "内容清晰易懂。",
                    },
                ]
            ).to_csv(csv_path, index=False, encoding="utf-8-sig")

            results = update_project_files(
                str(workbook), "p1", [str(csv_path)], enable_sentiment=False
            )

            products = pd.read_excel(workbook, sheet_name="products")
            contents = pd.read_excel(workbook, sheet_name="content_master")
            self.assertEqual(len(results), 2)
            self.assertEqual(set(products["item_key"]), {"jd:13745188", "jd:100244103673"})
            self.assertEqual(set(contents["content_text_clean"]), {"孩子很喜欢。", "内容清晰易懂。"})

    def test_jd_component_heading_is_not_saved_as_product_title(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "project.xlsx"
            csv_path = root / "jd_reviews.csv"
            create_project(str(workbook), "p1", "消费者反馈洞察")
            pd.DataFrame([{
                "platform": "jd",
                "product_id": "13745188",
                "product_url": "https://item.jd.com/13745188.html",
                "product_title": "最小单价计算器",
                "review_text_raw": "内容很好。",
            }]).to_csv(csv_path, index=False, encoding="utf-8-sig")

            update_project_files(
                str(workbook), "p1", [str(csv_path)], enable_sentiment=False
            )

            products = pd.read_excel(workbook, sheet_name="products").fillna("")
            self.assertEqual(products.iloc[0]["product_title_current"], "")


if __name__ == "__main__":
    unittest.main()
