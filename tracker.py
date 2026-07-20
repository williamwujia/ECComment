from __future__ import annotations

import argparse
import json
import sys

from project.updater import (
    backfill_project_sentiment,
    create_project,
    reanalyze_project,
    update_project_files,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="电商评论持续追踪项目 CLI")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init-project", help="创建项目 Excel 工作簿")
    init.add_argument("--workbook", required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--name", required=True)
    init.add_argument("--objective", default="")

    update = commands.add_parser("update", help="导入一个商品页面快照")
    update.add_argument("--workbook", required=True)
    update.add_argument("--project-id", required=True)
    update.add_argument(
        "--file",
        required=True,
        nargs="+",
        help="一个或多个 SingleFile 页面；商品 ID 自动从各页面提取",
    )
    update.add_argument("--platform")
    update.add_argument("--brand-product-id")
    update.add_argument("--brand")
    update.add_argument("--model-name")
    update.add_argument("--capture-time")
    update.add_argument("--allow-backfill", action="store_true")
    update.add_argument("--dry-run", action="store_true")
    update.add_argument("--keywords")
    update.add_argument(
        "--sentiment",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="对本次新增评论运行本地规则和 LLM 情绪判断，默认开启",
    )
    update.add_argument(
        "--sentiment-provider",
        default="deepseek",
    )
    update.add_argument(
        "--sentiment-config",
        default="config/llm_providers.local.json",
    )
    update.add_argument("--sentiment-model")
    update.add_argument("--sentiment-batch-size", type=int, default=50)
    update.add_argument("--sentiment-detail-limit", type=int, default=50)
    update.add_argument(
        "--sentiment-full-llm",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "全部新增评论进入 LLM 快判，默认开启；"
            "使用 --no-sentiment-full-llm 可改为本地规则优先"
        ),
    )

    reanalyze = commands.add_parser("reanalyze", help="不重新解析 HTML，重算分析结果")
    reanalyze.add_argument("--workbook", required=True)
    reanalyze.add_argument("--project-id", required=True)
    reanalyze.add_argument("--module", default="ai_candidate")
    reanalyze.add_argument("--version", default="ai_rules_v1.4")
    reanalyze.add_argument("--keywords")
    reanalyze.add_argument("--dry-run", action="store_true")

    backfill = commands.add_parser(
        "backfill-sentiment",
        help="对项目中尚未判别的历史评论补做情绪分析",
    )
    backfill.add_argument("--workbook", required=True)
    backfill.add_argument("--project-id", required=True)
    backfill.add_argument("--provider", default="deepseek")
    backfill.add_argument(
        "--config",
        default="config/llm_providers.local.json",
    )
    backfill.add_argument("--model")
    backfill.add_argument("--batch-size", type=int, default=50)
    backfill.add_argument("--detail-limit", type=int, default=50)
    backfill.add_argument("--limit", type=int)
    backfill.add_argument("--dry-run", action="store_true")
    backfill.add_argument(
        "--full-llm",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init-project":
            create_project(args.workbook, args.project_id, args.name, args.objective)
            result = {
                "result": "success",
                "project_id": args.project_id,
                "workbook": args.workbook,
            }
        elif args.command == "update":
            file_results = update_project_files(
                args.workbook,
                args.project_id,
                args.file,
                dry_run=args.dry_run,
                platform=args.platform,
                brand_product_id=args.brand_product_id,
                brand=args.brand,
                model_name=args.model_name,
                capture_time=args.capture_time,
                allow_backfill=args.allow_backfill,
                keywords_path=args.keywords,
                enable_sentiment=args.sentiment,
                sentiment_provider=args.sentiment_provider,
                sentiment_config_path=args.sentiment_config,
                sentiment_model=args.sentiment_model,
                sentiment_batch_size=args.sentiment_batch_size,
                sentiment_detail_limit=args.sentiment_detail_limit,
                sentiment_full_llm=args.sentiment_full_llm,
            )
            result = {
                "result": "failed"
                if any(item.get("result") == "failed" for item in file_results)
                else "warning"
                if any(item.get("result") == "warning" for item in file_results)
                else "success",
                "file_count": len(file_results),
                "success_count": sum(
                    item.get("result") == "success" for item in file_results
                ),
                "warning_count": sum(
                    item.get("result") == "warning" for item in file_results
                ),
                "failed_count": sum(
                    item.get("result") == "failed" for item in file_results
                ),
                "files": file_results,
            }
        elif args.command == "reanalyze":
            result = reanalyze_project(
                args.workbook,
                args.project_id,
                module=args.module,
                version=args.version,
                keywords_path=args.keywords,
                dry_run=args.dry_run,
            )
        else:
            result = backfill_project_sentiment(
                args.workbook,
                args.project_id,
                provider=args.provider,
                config_path=args.config,
                model=args.model,
                batch_size=args.batch_size,
                detail_limit=args.detail_limit,
                limit=args.limit,
                dry_run=args.dry_run,
                full_llm=args.full_llm,
            )
    except Exception as exc:
        print(json.dumps({"result": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if result.get("result") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
