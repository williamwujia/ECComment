from pathlib import Path

from ui.projects import (
    ProjectSummary,
    default_project_alias,
    infer_run_at,
    load_registry,
    project_alias,
    save_project_alias,
)
from tracker_ui import matching_workbook_option


def test_default_project_alias_shortens_long_output_name():
    alias = default_project_alias(
        "非常非常长的商品名称用于测试分析项目别名是否足够紧凑_20260709_103714.xlsx",
        max_title_length=10,
    )
    assert alias == "非常非常长的商品名称… · 07-09 10:37"


def test_infer_run_at_from_output_name():
    assert infer_run_at("商品_20260709_103714.xlsx") == "2026-07-09 10:37"


def test_alias_registry_round_trip(tmp_path: Path):
    workbook = tmp_path / "商品_20260709_103714.xlsx"
    save_project_alias(workbook, "七月商品项目", tmp_path)
    registry = load_registry(tmp_path)
    assert project_alias(workbook, registry) == "七月商品项目"


def test_project_tooltip_uses_markdown_line_breaks_and_punctuation():
    tooltip = ProjectSummary(6, 6, "2026-07-07 10:41", 135, 1513).tooltip("AOC.xlsx")
    assert tooltip.splitlines() == [
        "**原文件：**  ",
        "AOC.xlsx",
        "",
        "- **店铺数量：** 6 家",
        "- **商品数量：** 6 个",
        "- **运行日期：** 2026-07-07 10:41",
        "- **评论数量：** 135 条",
        "- **问大家数量：** 1,513 条",
    ]


def test_matching_workbook_option_accepts_absolute_created_path(tmp_path: Path):
    relative = Path("projects") / "新项目.xlsx"
    absolute = (tmp_path / relative).resolve()
    options = ["__new_project__", str(relative), "__manual_workbook__"]

    original = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        assert matching_workbook_option(str(absolute), options) == str(relative)
    finally:
        os.chdir(original)
