from __future__ import annotations

import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from analysis.ai_keyword_matcher import load_keywords, safe_match_ai_sources
from analysis.evidence_rules import analyze_ai_related
from analysis.summary import build_summaries
from extractor.html_loader import load_html
from extractor.product_meta import extract_product_meta
from extractor.reviews import parse_reviews
from extractor.taobao_qa import parse_taobao_qa
from main import build_timestamped_output_path, sanitize_run_name
from utils.excel_sanitizer import sanitize_frame_for_excel
from utils.text_cleaner import clean_text
from ui.source_display import source_file_name
from ui.data_loader import (
    ExcelLoadError,
    WorkbookInfo,
    build_capture_quality_warnings,
    build_summary_by_keyword,
    build_summary_by_month,
    build_summary_by_product,
    is_workbench_output_file,
    list_output_files,
    load_excel,
    merge_workbooks,
)


ROOT = Path(__file__).resolve().parents[1]
KEYWORDS = load_keywords(str(ROOT / "config" / "ai_keywords.yaml"))
META = {
    "source_file": "sample.html",
    "platform": "tmall",
    "product_title": "测试商品",
    "shop_name": "测试店铺",
    "product_url": "https://detail.tmall.com/item.htm?id=123456",
    "product_id": "123456",
}


class CoreTests(unittest.TestCase):
    def test_invalid_excel_control_characters_are_removed(self):
        text = "发货很快\x01使用方便\x0b效果不错\n保留换行\t保留制表符"

        self.assertEqual(
            clean_text(text),
            "发货很快使用方便效果不错\n保留换行 保留制表符",
        )

        frame = sanitize_frame_for_excel(pd.DataFrame({"comment": [text]}))
        self.assertNotIn("\x01", frame.loc[0, "comment"])
        self.assertNotIn("\x0b", frame.loc[0, "comment"])

    def test_html_loader_removes_excel_control_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control-char.html"
            path.write_text(
                '<div class="content--hash">发货很快\x01使用方便</div>',
                encoding="utf-8",
            )

            html = load_html(str(path))

            self.assertEqual(html.count("\x01"), 0)
            self.assertIn("发货很快使用方便", html)

    def test_capture_quality_warning_flags_review_preview_with_large_qa_section(self):
        content = pd.DataFrame(
            [
                {
                    "source_file": "preview.html",
                    "product_title": "测试商品",
                    "platform": "tmall",
                    "content_role": role,
                }
                for role in ["review", "review"] + ["question"] * 10 + ["answer"] * 10
            ]
        )

        warnings = build_capture_quality_warnings(content)

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings.iloc[0]["review_count"], 2)
        self.assertEqual(warnings.iloc[0]["qa_question_count"], 10)
        self.assertEqual(warnings.iloc[0]["qa_answer_count"], 10)

    def test_capture_quality_warning_ignores_normal_review_capture(self):
        content = pd.DataFrame(
            [
                {
                    "source_file": "complete.html",
                    "product_title": "测试商品",
                    "platform": "tmall",
                    "content_role": role,
                }
                for role in ["review"] * 3 + ["qa_question"] * 20
            ]
        )

        self.assertTrue(build_capture_quality_warnings(content).empty)

    def test_capture_quality_warning_ignores_tiny_qa_sample(self):
        content = pd.DataFrame(
            [
                {
                    "source_file": "small-sample.html",
                    "product_title": "测试商品",
                    "platform": "tmall",
                    "content_role": role,
                }
                for role in ["review", "review"] + ["question"] * 4 + ["answer"] * 4
            ]
        )

        self.assertTrue(build_capture_quality_warnings(content).empty)

    def test_product_title_prefers_tmall_sku_panel_title(self):
        html = """
        <html>
          <head><title>用户评价 · 1000+ - 天猫</title></head>
          <body>
            <div id="tbpcDetail_SkuPanelBody">
              <div></div>
              <div><div><div><div><span>明基 Aora 大主灯儿童房护眼吸顶灯</span></div></div></div></div>
            </div>
            <h1>商品评价</h1>
          </body>
        </html>
        """
        meta = extract_product_meta(html, BeautifulSoup(html, "lxml"), "sample.html", "tmall")
        self.assertEqual(meta["product_title"], "明基 Aora 大主灯儿童房护眼吸顶灯")
        self.assertEqual(meta["page_title"], "用户评价 · 1000+ - 天猫")

    def test_product_title_reads_first_sku_panel_title_attribute(self):
        html = """
        <html>
          <head><title>商品详情 - 天猫</title></head>
          <body>
            <div id="tbpcDetail_SkuPanelBody">
              <div><div><div><div><span title="TREK崔克PRECALIBER 24英寸8-12岁轻量双手刹8速青少年儿童自行车">按图片搜索</span></div></div></div></div>
            </div>
          </body>
        </html>
        """
        meta = extract_product_meta(html, BeautifulSoup(html, "lxml"), "sample.html", "tmall")
        self.assertEqual(
            meta["product_title"],
            "TREK崔克PRECALIBER 24英寸8-12岁轻量双手刹8速青少年儿童自行车",
        )

    def test_product_title_skips_review_and_service_noise(self):
        html = """
        <html>
          <head><title>霍尼韦尔落地护眼灯学习专用儿童台灯 - 商品详情 - 天猫</title></head>
          <body>
            <h1>商品评价</h1>
            <div class="title">问大家</div>
            <div class="item-title">客服月夏</div>
            <div class="product-title">霍尼韦尔落地护眼灯学习专用儿童台灯</div>
          </body>
        </html>
        """
        meta = extract_product_meta(html, BeautifulSoup(html, "lxml"), "sample.html", "tmall")
        self.assertEqual(meta["product_title"], "霍尼韦尔落地护眼灯学习专用儿童台灯")

    def test_product_title_falls_back_to_cleaned_page_title(self):
        html = """
        <html>
          <head><title>明基 ScreenBar Halo 2 屏幕挂灯 - 商品详情 - 价格 - 天猫</title></head>
          <body><div class="title">买家评价</div></body>
        </html>
        """
        meta = extract_product_meta(html, BeautifulSoup(html, "lxml"), "sample.html", "tmall")
        self.assertEqual(meta["product_title"], "明基 ScreenBar Halo 2 屏幕挂灯")
        self.assertEqual(meta["page_title"], "明基 ScreenBar Halo 2 屏幕挂灯 - 商品详情 - 价格 - 天猫")

    def test_product_title_ignores_image_search_and_uses_filename(self):
        html = """
        <html>
          <head><title>商品详情 - 天猫</title></head>
          <body>
            <div class="title">按图片搜索</div>
            <h1>商品评价</h1>
          </body>
        </html>
        """
        source_file = (
            "TREK崔克DOMANE AL 4碳纤维前叉油压碟刹公路自行车"
            "-tmall.com天猫 (2026-06-22 14：29：41).html"
        )
        meta = extract_product_meta(html, BeautifulSoup(html, "lxml"), source_file, "tmall")
        self.assertEqual(
            meta["product_title"],
            "TREK崔克DOMANE AL 4碳纤维前叉油压碟刹公路自行车",
        )

    def test_product_title_ignores_countdown_title_and_uses_filename(self):
        html = """
        <html>
          <head><title>商品详情 - 天猫</title></head>
          <body>
            <div class="title">距结束</div>
            <div class="Title">距离结束</div>
          </body>
        </html>
        """
        source_file = (
            "月影林之光大路灯全光谱儿童学习专用桌面台灯普瑞红光护眼落地灯"
            "-tmall.com天猫 (2026_6_21 22：28：06).html"
        )
        meta = extract_product_meta(html, BeautifulSoup(html, "lxml"), source_file, "tmall")
        self.assertEqual(
            meta["product_title"],
            "月影林之光大路灯全光谱儿童学习专用桌面台灯普瑞红光护眼落地灯",
        )

    def test_output_path_gets_timestamp(self):
        result = build_timestamped_output_path(
            ROOT / "output",
            "明基 ScreenBar Halo 2 屏幕挂灯",
            datetime(2026, 6, 14, 18, 30, 25),
        )
        self.assertEqual(result.name, "明基 ScreenBar Halo 2 屏幕挂灯_20260614_183025.xlsx")

    def test_output_path_sanitizes_run_name_and_accepts_legacy_xlsx_path(self):
        result = build_timestamped_output_path(
            ROOT / "output" / "ai_related_reviews.xlsx",
            "TREK/崔克:儿童车?",
            datetime(2026, 6, 14, 18, 30, 25),
        )
        self.assertEqual(result.name, "TREK_崔克_儿童车_20260614_183025.xlsx")
        self.assertEqual(sanitize_run_name("  .  "), "未命名运行")

    def test_source_file_name_strips_windows_and_posix_directories(self):
        self.assertEqual(
            source_file_name(
                r"D:\OneDrive\桌面\CodeX\抽取淘宝评论\input_html\明基Aora大主灯.html"
            ),
            "明基Aora大主灯.html",
        )
        self.assertEqual(source_file_name("/app/input_html/lipro.html"), "lipro.html")

    def test_air_is_not_ai(self):
        self.assertEqual(safe_match_ai_sources("air和pro和max推荐哪个呢？", KEYWORDS), [])
        self.assertEqual(safe_match_ai_sources("chair pair rain", KEYWORDS), [])
        result = analyze_ai_related(
            {
                "content_role": "question",
                "content_text_clean": "air和pro和max推荐哪个呢？",
                "parent_text_clean": "",
            },
            KEYWORDS,
        )
        self.assertEqual(result["evidence_level"], "D")
        self.assertFalse(result["ai_related"])
        self.assertFalse(result["ai_candidate"])

    def test_plain_recommend_and_compare_are_not_ai_candidates(self):
        samples = ["客服月夜很负责，买之前和之后，我问的比较细，客服都耐心的解答，非常不错。"]
        for text in samples:
            with self.subTest(text=text):
                result = analyze_ai_related(
                    {
                        "content_role": "review",
                        "content_text_clean": text,
                        "parent_text_clean": "",
                    },
                    KEYWORDS,
                )
                self.assertEqual(result["evidence_level"], "D")
                self.assertFalse(result["ai_candidate"])

    def test_v14_non_pre_purchase_is_not_labeled_d(self):
        cases = [
            (
                "明基昨天下单今天就到了！和之前的灯对比了一下，个人觉得明基的显色度会更高。",
                "post_purchase_comparison",
            ),
            (
                "月容服务好，产品也还行，就是价格比京东贵不好，淘宝百亿补贴和第三方比价的都是骗人的，完全不给赔。",
                "after_purchase_price_dispute",
            ),
            (
                "物流很快，下单后没两天就收到了，师傅上门安装很及时，之前没用过大路灯还需要适应下，感觉色温和之前家里用的灯对比下来还是不太习惯。客服挺有耐心的。",
                "post_purchase_comparison",
            ),
            (
                "收到了，很满意，物流上有点小插曲，客服也帮忙积极解决了。1、接受任何不满意，包邮全额退；2、101天免费试用；3、欢迎且支持跟任何竞品比质量。",
                "merchant_reply_like_text",
            ),
            ("灯收到了，亮度可以调节，比较适合孩子们。", "post_purchase_experience"),
        ]
        for text, reason in cases:
            with self.subTest(text=text):
                result = analyze_ai_related(
                    {
                        "content_role": "review",
                        "content_text_clean": text,
                        "parent_text_clean": "",
                    },
                    KEYWORDS,
                )
                self.assertFalse(result["pre_purchase_decision"])
                self.assertFalse(result["ai_candidate"])
                self.assertEqual(result["ai_influence_level"], "")
                self.assertEqual(result["evidence_level"], "")
                self.assertEqual(result["ai_evidence_type"], "none")
                self.assertEqual(result["exclude_reason"], reason)

    def test_v14_plain_pre_purchase_is_d(self):
        for text in ["推荐购买，光线柔和，孩子喜欢。", "朋友推荐买的，用下来不错。", "活动价格不错，就买了。"]:
            with self.subTest(text=text):
                result = analyze_ai_related(
                    {
                        "content_role": "review",
                        "content_text_clean": text,
                        "parent_text_clean": "",
                    },
                    KEYWORDS,
                )
                self.assertTrue(result["pre_purchase_decision"])
                self.assertFalse(result["ai_candidate"])
                self.assertEqual(result["ai_influence_level"], "D")

    def test_new_ai_candidate_levels_v13(self):
        cases = [
            ("豆包和DeepSeek都给我推荐了这一款，没做攻略就直接下单了。", "A"),
            ("之前在ChatGPT里看到过这个牌子。", "A"),
            ("问了Kimi怎么选护眼灯，最后买了这款。", "A"),
            ("智能助手推荐的，买回来还可以。", "B"),
            ("系统推荐我看的这款，纠结后下单了。", "B"),
            ("AI搜索里看到这款评价不错。", "B"),
            ("为了给孩子买个台灯，小红书做了很多功课，对比了很多品牌，最后选了这款。", "C"),
            ("对比了好久，认真做了科普，连着咨询了好几天终于确定选了这款。", "C"),
            ("趁着双十一活动，对比好多家最终买的这个，感谢客服推荐。", "C"),
            ("选了很久，网上搜索对比了很多品牌型号，最终还是选择了这款。", "C"),
        ]
        for text, level in cases:
            with self.subTest(text=text):
                result = analyze_ai_related(
                    {
                        "content_role": "review",
                        "content_text_clean": text,
                        "parent_text_clean": "",
                    },
                    KEYWORDS,
                )
                self.assertTrue(result["ai_candidate"])
                self.assertEqual(result["ai_influence_level"], level)
        mixed = analyze_ai_related(
            {
                "content_role": "review",
                "content_text_clean": "趁着双十一活动，对比好多家最终买的这个，感谢客服推荐。",
                "parent_text_clean": "",
            },
            KEYWORDS,
        )
        self.assertEqual(mixed["source_type"], "mixed_research_and_customer_service")

    def test_real_ai_context(self):
        self.assertIn("豆包", safe_match_ai_sources("问了豆包推荐这款", KEYWORDS))
        self.assertIn("豆包", safe_match_ai_sources("又问了豆 包推荐这款", KEYWORDS))
        self.assertIn("DeepSeek", safe_match_ai_sources("Deep Seek 推荐", KEYWORDS))
        self.assertTrue(safe_match_ai_sources("让AI帮我选", KEYWORDS))
        result = analyze_ai_related(
            {
                "content_role": "review",
                "content_text_clean": "问了豆包推荐这款，最后买了它。",
                "parent_text_clean": "",
            },
            KEYWORDS,
        )
        self.assertEqual(result["ai_influence_level"], "A")
        self.assertEqual(result["ai_evidence_type"], "explicit")
        real_review = analyze_ai_related(
            {
                "content_role": "review",
                "content_text_clean": (
                    "三年级小朋友已经近视了，希望可以苟住眼轴疯长，和豆包说了需求，"
                    "她推荐我买的。用了2天感觉不错，光线柔和，不刺眼。"
                ),
                "parent_text_clean": "",
            },
            KEYWORDS,
        )
        self.assertTrue(real_review["pre_purchase_decision"])
        self.assertTrue(real_review["ai_candidate"])
        self.assertEqual(real_review["ai_influence_level"], "A")

    def test_decorated_ai_source_names_are_matched(self):
        self.assertIn("豆包", safe_match_ai_sources("问了【豆 包】推荐这款", KEYWORDS))
        self.assertIn("豆包", safe_match_ai_sources("问了豆·包推荐这款", KEYWORDS))
        self.assertIn("DeepSeek", safe_match_ai_sources("Deep-Seek 推荐", KEYWORDS))
        result = analyze_ai_related(
            {
                "content_role": "review",
                "content_text_clean": "买之前问了【豆 包】，它推荐了这款，最后就下单了。",
                "parent_text_clean": "",
            },
            KEYWORDS,
        )
        self.assertTrue(result["ai_candidate"])
        self.assertEqual(result["ai_influence_level"], "A")
        self.assertIn("豆包", result["ai_source_terms"])

    def test_summary_by_month_aggregates_review_dates(self):
        content_all = [
            {
                "content_role": "review",
                "review_date": "2026-06-05",
                "pre_purchase_decision": True,
                "ai_candidate": True,
                "evidence_level": "A",
                "ai_source_terms": "豆包",
                "ai_action_terms": "",
                "content_text_clean": "问了豆包后买的。",
                "content_hash": "1",
                "platform": "tmall",
                "product_title": "测试商品",
                "shop_name": "测试店铺",
                "product_id": "123",
                "source_file": "a.html",
            },
            {
                "content_role": "review",
                "review_date": "2026-06-18",
                "pre_purchase_decision": False,
                "ai_candidate": False,
                "evidence_level": "D",
                "ai_source_terms": "",
                "ai_action_terms": "",
                "content_text_clean": "普通评论。",
                "content_hash": "2",
                "platform": "tmall",
                "product_title": "测试商品",
                "shop_name": "测试店铺",
                "product_id": "123",
                "source_file": "b.html",
            },
        ]
        summary = build_summaries(content_all, [content_all[0]])
        self.assertIn("summary_by_month", summary)
        self.assertEqual(summary["summary_by_month"][0]["review_month"], "2026-06")
        self.assertEqual(summary["summary_by_month"][0]["review_count"], 2)
        self.assertEqual(summary["summary_by_month"][0]["pre_purchase_decision_count"], 1)
        self.assertEqual(summary["summary_by_month"][0]["ai_candidate_count"], 1)

    def test_tmall_qa_card(self):
        html = """
        <div class="qaItem--hash">
          <div class="questionIcon--hash">问</div>
          <span>air和pro推荐哪个？</span>
          <span class="initTag--hash">已购</span>
          <span>根据面积来就行了</span>
          <div class="viewAllBtnWrap--hash">查看全部回答</div>
        </div>
        """
        pairs = parse_taobao_qa(html, BeautifulSoup(html, "lxml"), META)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["question_text_clean"], "air和pro推荐哪个？")
        self.assertEqual(pairs[0]["answer_text_clean"], "根据面积来就行了")

    def test_tmall_review_card(self):
        html = """
        <div class="Comment--hash">
          <div class="userInfo--hash"><span>匿**名</span>
            <div class="meta--hash">2026-06-08已购：Pro款</div>
          </div>
          <div class="contentWrapper--hash">
            <div class="content--hash">问了ChatGPT后买的，灯光不错。</div>
          </div>
        </div>
        """
        reviews = parse_reviews(html, BeautifulSoup(html, "lxml"), META)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["sku"], "Pro款")
        self.assertEqual(reviews[0]["user_name_masked"], "匿**名")

    def test_compressed_singlefile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compressed.html"
            with path.open("wb") as handle:
                handle.write(b"<!doctype html><p>Please wait...</p>")
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr(
                    "index.html", "<html><body>问大家：测试内容</body></html>"
                )
            self.assertIn("测试内容", load_html(str(path)))


    def test_ui_summaries_are_built_from_filtered_content(self):
        content = pd.DataFrame(
            [
                {
                    "platform": "tmall",
                    "product_title": "Lamp A",
                    "shop_name": "Shop",
                    "product_id": "a",
                    "source_file": "a.html",
                    "content_role": "review",
                    "review_date": "2026-05-01",
                    "pre_purchase_decision": True,
                    "ai_candidate": True,
                    "evidence_level": "A",
                    "matched_keywords": "ChatGPT",
                    "content_text_clean": "asked ChatGPT",
                },
                {
                    "platform": "tmall",
                    "product_title": "Lamp B",
                    "shop_name": "Shop",
                    "product_id": "b",
                    "source_file": "b.html",
                    "content_role": "review",
                    "review_date": "2026-06-01",
                    "pre_purchase_decision": True,
                    "ai_candidate": True,
                    "evidence_level": "C",
                    "matched_keywords": "research",
                    "content_text_clean": "did research",
                },
            ]
        )
        filtered = content[content["product_title"] == "Lamp A"]

        product_summary = build_summary_by_product(filtered)
        keyword_summary = build_summary_by_keyword(filtered)
        month_summary = build_summary_by_month(filtered)

        self.assertEqual(product_summary["product_title"].tolist(), ["Lamp A"])
        self.assertEqual(keyword_summary["keyword"].tolist(), ["ChatGPT"])
        self.assertEqual(month_summary["review_month"].tolist(), ["2026-05"])

    def test_merge_workbooks_preserves_workbook_source(self):
        first = {
            "content_all": pd.DataFrame(
                [{"product_title": "Lamp A", "workbook_source": "first.xlsx", "ai_candidate": True}]
            )
        }
        second = {
            "content_all": pd.DataFrame(
                [{"product_title": "Lamp B", "workbook_source": "second.xlsx", "ai_candidate": False}]
            )
        }

        merged, info = merge_workbooks(
            [
                (first, WorkbookInfo(["content_all"], [], "first.xlsx")),
                (second, WorkbookInfo(["content_all"], [], "second.xlsx")),
            ]
        )

        self.assertEqual(info.source_name, "2 files: first.xlsx, second.xlsx")
        self.assertEqual(merged["content_all"]["product_title"].tolist(), ["Lamp A", "Lamp B"])
        self.assertEqual(merged["content_all"]["workbook_source"].tolist(), ["first.xlsx", "second.xlsx"])

    def test_output_file_list_excludes_auxiliary_qa_exports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            main_file = output_dir / "AOC_20260707_104143.xlsx"
            qa_file = output_dir / "大家问-AOC_20260707_104143.xlsx"
            lock_file = output_dir / "~$AOC_20260707_104143.xlsx"
            main_file.touch()
            qa_file.touch()
            lock_file.touch()

            self.assertTrue(is_workbench_output_file(main_file))
            self.assertFalse(is_workbench_output_file(qa_file))
            self.assertFalse(is_workbench_output_file(lock_file))
            self.assertEqual(list_output_files(output_dir), [main_file])

    def test_load_excel_rejects_auxiliary_qa_export_before_reading_file(self):
        with self.assertRaises(ExcelLoadError) as context:
            load_excel("大家问-AOC_20260707_104143.xlsx")

        self.assertIn("问大家专项导出", str(context.exception))
        self.assertIn("AOC_20260707_104143.xlsx", str(context.exception))


if __name__ == "__main__":
    unittest.main()
