from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
import json
import re

import pandas as pd


REGISTRY_NAME = ".analysis_projects.json"
TIMESTAMP_RE = re.compile(r"_(\d{8})_(\d{6})(?:\s*-\s*副本)?$")


@dataclass(frozen=True)
class ProjectSummary:
    shops: int
    products: int
    run_at: str
    reviews: int
    qa_items: int

    def tooltip(self, file_name: str) -> str:
        safe_file_name = file_name.replace("`", r"\`")
        return (
            f"**原文件：**  \n{safe_file_name}\n\n"
            f"- **店铺数量：** {self.shops:,} 家\n"
            f"- **商品数量：** {self.products:,} 个\n"
            f"- **运行日期：** {self.run_at}\n"
            f"- **评论数量：** {self.reviews:,} 条\n"
            f"- **问大家数量：** {self.qa_items:,} 条"
        )


def default_project_alias(path: str | Path, max_title_length: int = 22) -> str:
    file_path = Path(path)
    stem = file_path.stem
    match = TIMESTAMP_RE.search(stem)
    date_label = ""
    if match:
        stem = stem[: match.start()]
        date_label = f"{match.group(1)[4:6]}-{match.group(1)[6:8]} {match.group(2)[:2]}:{match.group(2)[2:4]}"
    title = stem.strip(" _-") or "未命名项目"
    if len(title) > max_title_length:
        title = title[:max_title_length].rstrip() + "…"
    return f"{title} · {date_label}" if date_label else title


def infer_run_at(path: str | Path) -> str:
    file_path = Path(path)
    match = TIMESTAMP_RE.search(file_path.stem)
    if match:
        return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M")
    return datetime.fromtimestamp(file_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def summarize_project(path: str | Path) -> ProjectSummary:
    file_path = Path(path)
    try:
        frame = pd.read_excel(file_path, sheet_name="summary_by_product")
    except (ValueError, KeyError):
        frame = pd.read_excel(file_path, sheet_name="content_all")

    shops = _unique_count(frame, "shop_name")
    products = _unique_count(frame, "product_id")
    if not products:
        products = _unique_count(frame, "product_title")

    if "content_role" in frame.columns:
        roles = frame["content_role"].fillna("").astype(str)
        reviews = int((roles == "review").sum())
        qa_items = int(roles.isin(["question", "answer"]).sum())
    else:
        reviews = _sum_columns(frame, ["review_count"])
        if "qa_question_count" in frame.columns or "qa_answer_count" in frame.columns:
            qa_items = _sum_columns(frame, ["qa_question_count", "qa_answer_count"])
        else:
            qa_items = _sum_columns(frame, ["qa_count"])

    return ProjectSummary(
        shops=shops,
        products=products,
        run_at=infer_run_at(file_path),
        reviews=reviews,
        qa_items=qa_items,
    )


def load_registry(output_dir: str | Path = "output") -> dict:
    path = Path(output_dir) / REGISTRY_NAME
    if not path.exists():
        return {"projects": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError):
        return {"projects": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("projects"), dict):
        return {"projects": {}}
    return payload


def save_project_alias(path: str | Path, alias: str, output_dir: str | Path = "output") -> None:
    file_path = Path(path)
    registry = load_registry(output_dir)
    entry = registry["projects"].setdefault(file_path.name, {})
    entry["alias"] = alias.strip() or default_project_alias(file_path)
    registry_path = Path(output_dir) / REGISTRY_NAME
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def project_alias(path: str | Path, registry: dict) -> str:
    file_path = Path(path)
    entry = registry.get("projects", {}).get(file_path.name, {})
    return str(entry.get("alias") or default_project_alias(file_path))


def summary_to_dict(summary: ProjectSummary) -> dict:
    return asdict(summary)


def _unique_count(frame: pd.DataFrame, column: str) -> int:
    if column not in frame.columns:
        return 0
    values = frame[column].dropna().astype(str).str.strip()
    return int(values[values != ""].nunique())


def _sum_columns(frame: pd.DataFrame, columns: list[str]) -> int:
    total = 0
    for column in columns:
        if column in frame.columns:
            total += int(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())
    return total
