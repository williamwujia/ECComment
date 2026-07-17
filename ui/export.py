from __future__ import annotations

from datetime import datetime

import pandas as pd

from ui.cards import report_case_text


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def markdown_cases(frame: pd.DataFrame) -> str:
    lines = ["# AI 影响候选案例", ""]
    for level in ["A", "B", "C"]:
        subset = frame[frame["evidence_level"] == level] if "evidence_level" in frame.columns else frame.iloc[0:0]
        lines.append(f"## {level} 级案例")
        lines.append("")
        if subset.empty:
            lines.append("- 暂无")
            lines.append("")
            continue
        for _, row in subset.iterrows():
            lines.extend(
                [
                    f"- 商品：{row.get('product_title', '')}",
                    f"- 平台：{row.get('platform', '')}",
                    f"- 原文：{row.get('content_text_clean', '')}",
                    f"- 判断理由：{row.get('evidence_reason') or row.get('ai_level_reason', '')}",
                    f"- 报告描述：{report_case_text(row)}",
                    "",
                ]
            )
    return "\n".join(lines)

