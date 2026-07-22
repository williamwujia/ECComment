from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from project.updater import (
    create_named_project,
    create_project,
    update_project_files,
)
from project.workbook import load_sheets
from ui.charts import (
    evidence_bar,
    funnel_chart,
    keyword_rank_chart,
    monthly_trend_chart,
    product_rank_chart,
    sentiment_category_chart,
    sentiment_distribution_chart,
)
from ui.tables import detail_lookup, download_csv, show_table
from ui.styles import inject_css
from ui.tracker_metrics import (
    EVIDENCE_LEVELS,
    SENTIMENT_LABELS,
    build_brand_overview,
    build_month_summary,
    build_product_comparison,
    build_sentiment_metrics,
    sentiment_series,
)


if __name__ == "__main__":
    # Direct `streamlit run tracker_ui.py` remains supported. When app.py is
    # the entry point, it configures every session before importing this module.
    st.set_page_config(page_title="消费者反馈洞察", layout="wide")
    inject_css()

BRAND_PAGES = [
    "品牌总览",
    "评论洞察",
    "购前评论",
    "AI 影响",
    "月份汇总",
    "高价值评论",
    "商品对比",
    "看板说明",
]
MAINTENANCE_PAGES = [
    "数据更新",
    "项目状态",
    "数据质量与日志",
    "待复核队列",
    "扩展分析",
    "维护说明",
]
NEW_PROJECT_OPTION = "__new_project__"
MANUAL_WORKBOOK_OPTION = "__manual_workbook__"
PROJECTS_DIRECTORY = Path("projects")


@st.cache_data(show_spinner=False)
def cached_load_sheets(
    workbook: str,
    modified_ns: int,
) -> dict[str, pd.DataFrame]:
    del modified_ns
    return load_sheets(workbook)


def main() -> None:
    st.sidebar.title("消费者反馈洞察")
    mode = st.sidebar.radio(
        "使用身份",
        ["品牌看板", "维护后台"],
        help="品牌看板用于日常查看；维护后台用于新增项目、上传页面和检查更新质量。",
    )
    maintenance = mode == "维护后台"
    workbook = workbook_picker(maintenance=maintenance)
    if not workbook:
        if maintenance:
            st.info("请在左侧选择项目工作簿，或输入新工作簿路径。")
        else:
            st.info("目前还没有可查看的品牌项目，请联系维护者添加。")
        return

    if workbook == NEW_PROJECT_OPTION:
        st.title("新建项目")
        render_create_project()
        return

    workbook_path = Path(workbook).expanduser()
    if not workbook_path.exists():
        if maintenance:
            st.title("创建持续追踪项目")
            render_create_project(workbook)
        else:
            st.error("该项目的数据文件不存在，请联系维护者。")
        return

    try:
        sheets = cached_load_sheets(
            str(workbook_path.resolve()),
            workbook_path.stat().st_mtime_ns,
        )
    except Exception as exc:
        st.error(f"无法读取持续追踪工作簿：{exc}")
        return

    created_message = st.session_state.pop("project_created_message", "")
    if created_message:
        st.success(created_message)

    project_ids = (
        sheets["project_info"]["project_id"].fillna("").astype(str).tolist()
    )
    project_ids = [value for value in project_ids if value]
    if not project_ids:
        st.error("工作簿中没有有效的 project_id。")
        return
    project_id = st.sidebar.selectbox(
        "查看项目",
        project_ids,
        format_func=lambda value: project_display_name(sheets, value),
    )
    pages = MAINTENANCE_PAGES if maintenance else BRAND_PAGES
    page = st.sidebar.radio("页面", pages)
    if maintenance:
        st.sidebar.caption(f"工作簿：{Path(workbook).name}")
        st.sidebar.caption(f"数据源：{Path(workbook).resolve()}")
    else:
        st.sidebar.caption("只读看板 · 数据更新由维护者负责")

    if page == "品牌总览":
        render_brand_overview(sheets, project_id)
    elif page == "评论洞察":
        render_brand_reviews(sheets, project_id)
    elif page == "购前评论":
        render_brand_pre_purchase(sheets, project_id)
    elif page == "AI 影响":
        render_brand_ai(sheets, project_id)
    elif page == "月份汇总":
        render_brand_months(sheets, project_id)
    elif page == "高价值评论":
        render_brand_high_value(sheets, project_id)
    elif page == "商品对比":
        render_brand_products(sheets, project_id)
    elif page == "看板说明":
        render_brand_guide()
    elif page == "数据更新":
        render_update_form(workbook, sheets, project_id)
    elif page == "项目状态":
        render_project_home(sheets, project_id)
    elif page == "数据质量与日志":
        render_maintenance_quality(sheets, project_id)
    elif page == "待复核队列":
        render_review_queue(sheets, project_id)
    elif page == "扩展分析":
        render_extended_analysis(sheets, project_id)
    else:
        render_usage_guide()


def workbook_picker(*, maintenance: bool) -> str:
    candidates = discover_project_workbooks()
    with st.sidebar:
        if not maintenance:
            if not candidates:
                return ""
            return st.selectbox(
                "品牌项目",
                [str(path) for path in candidates],
                format_func=lambda value: Path(value).stem,
            )
        options = (
            [NEW_PROJECT_OPTION]
            + [str(path) for path in candidates]
            + [MANUAL_WORKBOOK_OPTION]
        )
        preferred = st.session_state.pop(
            "select_workbook_after_create",
            None,
        )
        preferred_option = matching_workbook_option(preferred, options)
        if preferred_option:
            st.session_state["maintenance_project_selector"] = (
                preferred_option
            )
        selector_index = (
            None
            if "maintenance_project_selector" in st.session_state
            else (1 if candidates else 0)
        )
        selected = st.selectbox(
            "维护项目",
            options,
            index=selector_index,
            key="maintenance_project_selector",
            format_func=workbook_option_label,
        )
        if selected is None:
            return ""
        if selected == NEW_PROJECT_OPTION:
            st.caption("创建一个新的持续追踪项目")
            return NEW_PROJECT_OPTION
        default_path = str(
            (PROJECTS_DIRECTORY / "consumer_evidence.xlsx").resolve()
        )
        if selected == MANUAL_WORKBOOK_OPTION:
            return st.text_input("工作簿路径", value=default_path).strip()
        st.caption(str(Path(selected).resolve()))
        return selected


def workbook_option_label(value: str) -> str:
    if value == NEW_PROJECT_OPTION:
        return "＋ 新建项目"
    if value == MANUAL_WORKBOOK_OPTION:
        return "手动输入工作簿"
    return Path(value).stem


def matching_workbook_option(
    preferred: str | None,
    options: list[str],
) -> str | None:
    if not preferred:
        return None
    if preferred in options:
        return preferred
    preferred_path = Path(preferred).expanduser().resolve()
    for option in options:
        if option in {NEW_PROJECT_OPTION, MANUAL_WORKBOOK_OPTION}:
            continue
        if Path(option).expanduser().resolve() == preferred_path:
            return option
    return None


def project_display_name(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> str:
    projects = project_frame(sheets.get("project_info", pd.DataFrame()), project_id)
    if projects.empty:
        return project_id
    name = projects.iloc[0].get("project_name")
    return str(name).strip() if name is not None and not pd.isna(name) and str(name).strip() else project_id


def discover_project_workbooks(root: str | Path = "projects") -> list[Path]:
    directory = Path(root)
    if not directory.exists():
        return []
    return sorted(
        (
            path
            for path in directory.rglob("*.xlsx")
            if not path.name.startswith("~$")
            and "backups" not in {part.casefold() for part in path.parts}
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def render_create_project(workbook: str | None = None) -> None:
    managed_path = workbook is None
    if managed_path:
        st.caption("创建后会生成独立项目文件，并自动切换到该项目。")
    else:
        st.info("该工作簿尚不存在，可以在这里创建新项目。")
    with st.form("create_project"):
        project_name = st.text_input(
            "项目名称",
            placeholder="例如：空气净化器消费者反馈",
        )
        objective = st.text_area(
            "项目目标（可选）",
            placeholder="例如：持续追踪重点型号的评论变化与 AI 影响",
        )
        project_id = (
            ""
            if managed_path
            else st.text_input(
                "项目 ID",
                help="用于数据关联，创建后不建议修改。",
            )
        )
        submitted = st.form_submit_button(
            "创建项目",
            type="primary",
            width="stretch",
        )
    if submitted:
        try:
            if managed_path:
                created_path = create_named_project(
                    PROJECTS_DIRECTORY,
                    project_name,
                    objective,
                )
            else:
                create_project(
                    str(workbook),
                    project_id,
                    project_name,
                    objective,
                )
                created_path = Path(str(workbook)).expanduser().resolve()
        except Exception as exc:
            st.error(str(exc))
        else:
            cached_load_sheets.clear()
            st.session_state["select_workbook_after_create"] = str(
                created_path
            )
            st.session_state["project_created_message"] = (
                f"项目“{project_name.strip()}”已创建，可以开始上传页面。"
            )
            st.rerun()


def render_brand_overview(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    content = brand_content(sheets, project_id)
    overview = build_brand_overview(content)
    project = project_frame(sheets["project_info"], project_id).iloc[0]

    st.title(str(project.get("project_name") or project_id))
    objective = project.get("objective")
    if objective is not None and not pd.isna(objective) and str(objective).strip():
        st.caption(str(objective))

    st.subheader("反馈规模")
    scale = st.columns(4)
    scale[0].metric("商品评论", f"{overview['review_count']:,}")
    scale[1].metric("问大家问题", f"{overview['question_count']:,}")
    scale[2].metric("问大家回答", f"{overview['answer_count']:,}")
    scale[3].metric("全部内容", f"{overview['total_content_count']:,}")

    evidence = overview["evidence_counts"]
    funnel_summary = {
        "review_count": overview["review_count"],
        "pre_purchase": overview["pre_purchase_count"],
        "ai_candidates": overview["ai_candidate_count"],
        "a_level": evidence["A"],
    }
    decision = st.columns(3)
    decision[0].metric(
        "购前决策评论",
        f"{overview['pre_purchase_count']:,}",
    )
    decision[1].metric(
        "AI 候选评论",
        f"{overview['ai_candidate_count']:,}",
    )
    decision[2].metric(
        "AI 候选 / 购前决策",
        (
            f"{overview['ai_candidate_count'] / overview['pre_purchase_count']:.1%}"
            if overview["pre_purchase_count"]
            else "0.0%"
        ),
    )

    left, right = st.columns([1.1, 1])
    with left:
        st.subheader("评论筛选漏斗")
        st.plotly_chart(
            funnel_chart(funnel_summary),
            width="stretch",
        )
    with right:
        st.subheader("证据等级分布")
        reviews = content[
            role_series(content).isin(["review", "followup"])
        ]
        st.plotly_chart(
            evidence_bar(reviews),
            width="stretch",
        )

    st.subheader("情感快判概览")
    fast = project_frame(
        sheets.get("sentiment_fast", pd.DataFrame()),
        project_id,
    )
    detail = project_frame(
        sheets.get("sentiment_detail", pd.DataFrame()),
        project_id,
    )
    failures = project_frame(
        sheets.get("sentiment_failures", pd.DataFrame()),
        project_id,
    )
    sentiment_metrics = build_sentiment_metrics(fast, detail, failures)
    sentiment = sentiment_metrics["sentiment_counts"]
    sentiment_cards = st.columns(5)
    for index, (code, label) in enumerate(SENTIMENT_LABELS.items()):
        sentiment_cards[index].metric(label, f"{sentiment[code]:,}")
    sentiment_cards[4].metric(
        "未判别",
        f"{overview['sentiment_unjudged_count']:,}",
    )
    pipeline_cards = st.columns(4)
    pipeline_cards[0].metric(
        "快判评论",
        f"{sentiment_metrics['total_count']:,}",
        f"平均分 {sentiment_metrics['average_score']:.1f}",
    )
    pipeline_cards[1].metric(
        "本地规则",
        f"{sentiment_metrics['rule_count']:,}",
    )
    pipeline_cards[2].metric(
        "LLM 快判",
        f"{sentiment_metrics['llm_fast_count']:,}",
    )
    pipeline_cards[3].metric(
        "详析 / 失败",
        (
            f"{sentiment_metrics['detail_count']:,} / "
            f"{sentiment_metrics['failed_count']:,}"
        ),
    )
    if overview["sentiment_unjudged_count"]:
        st.warning(
            f"仍有 {overview['sentiment_unjudged_count']:,} 条评论未完成情绪判断。"
        )
    sentiment_chart_frame = fast.copy()
    if "sentiment_label" not in sentiment_chart_frame.columns:
        sentiment_chart_frame["sentiment_label"] = sentiment_series(
            sentiment_chart_frame
        )
    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.plotly_chart(
            sentiment_distribution_chart(sentiment_chart_frame),
            width="stretch",
        )
    with chart_right:
        st.plotly_chart(
            sentiment_category_chart(
                sentiment_chart_frame,
                "complaint_cn",
                "主要吐槽",
            ),
            width="stretch",
        )


def render_brand_reviews(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    st.title("评论洞察")
    content = brand_content(sheets, project_id)
    reviews = content[role_series(content).isin(["review", "followup"])].copy()
    if reviews.empty:
        st.info("当前项目还没有商品评论。")
        return
    reviews["_sentiment_code"] = sentiment_series(reviews)
    reviews["_sentiment_name"] = reviews["_sentiment_code"].map(
        SENTIMENT_LABELS
    ).fillna("未判别")
    reviews["_product_name"] = product_name_series(reviews)

    filters = st.columns(3)
    with filters[0]:
        products = st.multiselect(
            "商品",
            sorted(value for value in reviews["_product_name"].unique() if value),
            key="brand_review_products",
        )
    with filters[1]:
        sentiments = st.multiselect(
            "情绪",
            [*SENTIMENT_LABELS.values(), "未判别"],
            key="brand_review_sentiments",
        )
    with filters[2]:
        levels = st.multiselect(
            "AI 证据等级",
            list(EVIDENCE_LEVELS),
            key="brand_review_levels",
        )
    query = st.text_input(
        "搜索评论、追评、关键词或规格",
        key="brand_review_query",
    ).strip()
    filtered = reviews
    if products:
        filtered = filtered[filtered["_product_name"].isin(products)]
    if sentiments:
        filtered = filtered[filtered["_sentiment_name"].isin(sentiments)]
    if levels:
        filtered = filtered[
            filtered.get("evidence_level", pd.Series("", index=filtered.index))
            .fillna("")
            .astype(str)
            .isin(levels)
        ]
    if query:
        mask = pd.Series(False, index=filtered.index)
        for column in (
            "content_text_clean",
            "parent_text_clean",
            "matched_keywords",
            "sku",
        ):
            if column in filtered.columns:
                mask |= filtered[column].fillna("").astype(str).str.contains(
                    query,
                    case=False,
                    regex=False,
                )
        filtered = filtered[mask]

    metrics = st.columns(4)
    metrics[0].metric("当前评论", f"{len(filtered):,}")
    metrics[1].metric(
        "积极",
        f"{int(filtered['_sentiment_code'].eq('P').sum()):,}",
    )
    metrics[2].metric(
        "消极",
        f"{int(filtered['_sentiment_code'].eq('N').sum()):,}",
    )
    metrics[3].metric(
        "AI 相关",
        f"{int(boolean_series(filtered, 'ai_candidate').sum()):,}",
    )
    download_csv(
        brand_review_export(filtered),
        "下载当前结果",
        "brand_reviews",
        "brand_reviews_download",
    )
    if filtered.empty:
        st.info("当前筛选条件下没有评论。")
        return
    table = pd.DataFrame(
        {
            "商品": filtered["_product_name"],
            "评论内容": filtered.get("content_text_clean", ""),
            "情绪": filtered["_sentiment_name"],
            "情绪分数": filtered.get("sentiment_score", ""),
            "表扬点": filtered.get("praise_cn", ""),
            "抱怨点": filtered.get("complaint_cn", ""),
            "AI 等级": filtered.get("evidence_level", ""),
            "AI 命中词": filtered.get("matched_keywords", ""),
            "评论时间": filtered.get("content_time", ""),
            "规格": filtered.get("sku", ""),
        }
    )
    st.dataframe(table.head(2000), width="stretch", height=620, hide_index=True)
    if len(table) > 2000:
        st.caption("页面展示前 2,000 条；下载文件包含当前筛选的全部结果。")


def render_brand_pre_purchase(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    st.title("购前评论")
    st.caption("集中查看消费者在购买前如何比较、选择、判断值不值和规避风险。")
    content = brand_content(sheets, project_id)
    reviews = content[
        role_series(content).isin(["review", "followup"])
        & boolean_series(content, "pre_purchase_decision")
    ].copy()
    if reviews.empty:
        st.info("当前项目没有识别到购前决策评论。")
        return
    reviews["_product_name"] = product_name_series(reviews)
    reviews["_sentiment_name"] = sentiment_series(reviews).map(
        SENTIMENT_LABELS
    ).fillna("未判别")
    controls = st.columns(3)
    with controls[0]:
        products = st.multiselect(
            "商品",
            sorted(value for value in reviews["_product_name"].unique() if value),
            key="brand_pre_products",
        )
    with controls[1]:
        sentiments = st.multiselect(
            "情绪",
            [*SENTIMENT_LABELS.values(), "未判别"],
            key="brand_pre_sentiments",
        )
    with controls[2]:
        ai_only = st.checkbox(
            "只看 AI 候选",
            key="brand_pre_ai_only",
        )
    query = st.text_input(
        "搜索评论、关键词或规格",
        key="brand_pre_query",
    ).strip()
    filtered = reviews
    if products:
        filtered = filtered[filtered["_product_name"].isin(products)]
    if sentiments:
        filtered = filtered[filtered["_sentiment_name"].isin(sentiments)]
    if ai_only:
        filtered = filtered[boolean_series(filtered, "ai_candidate")]
    if query:
        filtered = filter_brand_query(filtered, query)

    cards = st.columns(4)
    cards[0].metric("购前评论", f"{len(filtered):,}")
    cards[1].metric(
        "AI 候选",
        f"{int(boolean_series(filtered, 'ai_candidate').sum()):,}",
    )
    cards[2].metric(
        "积极",
        f"{int(sentiment_series(filtered).eq('P').sum()):,}",
    )
    cards[3].metric(
        "消极或混合",
        f"{int(sentiment_series(filtered).isin(['N', 'M']).sum()):,}",
    )
    download_csv(
        brand_review_export(filtered),
        "下载当前购前评论",
        "pre_purchase_reviews",
        "brand_pre_download",
    )
    table = pd.DataFrame(
        {
            "商品": filtered["_product_name"],
            "评论内容": filtered.get("content_text_clean", ""),
            "情绪": filtered["_sentiment_name"],
            "AI 候选": boolean_series(filtered, "ai_candidate").map(
                {True: "是", False: "否"}
            ),
            "AI 等级": filtered.get("evidence_level", ""),
            "命中词": filtered.get("matched_keywords", ""),
            "表扬点": filtered.get("praise_cn", ""),
            "抱怨点": filtered.get("complaint_cn", ""),
            "评论时间": filtered.get("content_time", ""),
            "规格": filtered.get("sku", ""),
        }
    )
    st.dataframe(table, width="stretch", height=620, hide_index=True)


def render_brand_ai(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    st.title("AI 影响")
    st.caption("A–D 是消费者购前决策中 AI 影响证据的强弱分级。")
    explanations = st.columns(4)
    explanations[0].info("A 级\n\n明确提到具体 AI 工具或回答，并影响购买判断。")
    explanations[1].info("B 级\n\n明确提到 AI、算法或智能助手，但来源不够具体。")
    explanations[2].info("C 级\n\n表现出高强度检索、比较或研究行为，可能受到 AI 影响。")
    explanations[3].info("D 级\n\n普通购前决策评论，作为观察 AI 影响比例的参照。")

    content = brand_content(sheets, project_id)
    reviews = content[role_series(content).isin(["review", "followup"])].copy()
    reviews["_product_name"] = product_name_series(reviews)
    evidence = reviews.get(
        "evidence_level",
        pd.Series("", index=reviews.index),
    ).fillna("").astype(str).str.upper()
    cards = st.columns(4)
    for index, level in enumerate(EVIDENCE_LEVELS):
        cards[index].metric(
            f"{level} 级评论",
            f"{int(evidence.eq(level).sum()):,}",
        )

    month_summary = build_month_summary(content)
    if not month_summary.empty:
        st.subheader("逐月评论、购前决策与 AI 候选")
        st.plotly_chart(
            monthly_trend_chart(month_summary),
            width="stretch",
        )

    controls = st.columns(2)
    with controls[0]:
        selected_levels = st.multiselect(
            "查看等级",
            list(EVIDENCE_LEVELS),
            default=list(EVIDENCE_LEVELS),
            key="brand_ai_levels",
        )
    with controls[1]:
        selected_products = st.multiselect(
            "商品",
            sorted(value for value in reviews["_product_name"].unique() if value),
            key="brand_ai_products",
        )
    filtered = (
        reviews[evidence.isin(selected_levels)].copy()
        if selected_levels
        else reviews.iloc[0:0].copy()
    )
    if selected_products:
        filtered = filtered[
            filtered["_product_name"].isin(selected_products)
        ].copy()
    filtered["_sentiment_name"] = sentiment_series(filtered).map(
        SENTIMENT_LABELS
    ).fillna("未判别")
    download_csv(
        brand_review_export(filtered),
        "下载当前 AI 证据",
        "brand_ai_evidence",
        "brand_ai_download",
    )
    if filtered.empty:
        st.info("当前筛选条件下没有已分级的评论。")
        return
    table = pd.DataFrame(
        {
            "等级": filtered.get("evidence_level", ""),
            "商品": filtered["_product_name"],
            "评论内容": filtered.get("content_text_clean", ""),
            "命中词": filtered.get("matched_keywords", ""),
            "情绪": filtered["_sentiment_name"],
            "评论时间": filtered.get("content_time", ""),
        }
    ).sort_values("等级")
    st.dataframe(table, width="stretch", height=620, hide_index=True)


def render_brand_months(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    st.title("月份汇总")
    st.caption("按评论日期观察全部评论、购前决策评论和 AI 候选评论的变化。")
    summary = build_month_summary(brand_content(sheets, project_id))
    if summary.empty:
        st.info("当前项目没有可用于月份汇总的评论日期。")
        return
    st.plotly_chart(monthly_trend_chart(summary), width="stretch")
    export = summary.copy()
    export["ai_candidate_rate"] = export["ai_candidate_rate"].map(
        lambda value: f"{value:.1%}"
    )
    shown = export.rename(
        columns={
            "review_month": "月份",
            "review_count": "评论数",
            "pre_purchase_decision_count": "购前决策评论",
            "ai_candidate_count": "AI 候选评论",
            "a_level_count": "A 级",
            "b_level_count": "B 级",
            "c_level_count": "C 级",
            "d_level_count": "D 级",
            "ai_candidate_rate": "AI 候选占比",
        }
    )
    download_csv(
        summary,
        "下载月份汇总",
        "monthly_summary",
        "brand_month_download",
    )
    st.dataframe(shown, width="stretch", height=520, hide_index=True)


def render_brand_high_value(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    st.title("高价值评论")
    st.caption(
        "这里展示经过详析的评论，通常包含负向、褒贬混合、AI 相关、"
        "低置信或信息量较高的评论。"
    )
    frame = high_value_content(sheets, project_id)
    if frame.empty:
        st.info("当前项目还没有高价值评论详析结果。")
        return
    frame["_product_name"] = product_name_series(frame)
    frame["_sentiment_name"] = sentiment_series(frame).map(
        SENTIMENT_LABELS
    ).fillna("未判别")
    controls = st.columns(3)
    with controls[0]:
        products = st.multiselect(
            "商品",
            sorted(value for value in frame["_product_name"].unique() if value),
            key="brand_high_products",
        )
    with controls[1]:
        sentiments = st.multiselect(
            "情绪",
            [*SENTIMENT_LABELS.values(), "未判别"],
            key="brand_high_sentiments",
        )
    with controls[2]:
        levels = st.multiselect(
            "AI 证据等级",
            list(EVIDENCE_LEVELS),
            key="brand_high_levels",
        )
    query = st.text_input(
        "搜索评论、证据或分析结论",
        key="brand_high_query",
    ).strip()
    filtered = frame
    if products:
        filtered = filtered[filtered["_product_name"].isin(products)]
    if sentiments:
        filtered = filtered[filtered["_sentiment_name"].isin(sentiments)]
    if levels:
        filtered = filtered[
            filtered.get("evidence_level", pd.Series("", index=filtered.index))
            .fillna("")
            .astype(str)
            .isin(levels)
        ]
    if query:
        filtered = filter_brand_query(
            filtered,
            query,
            extra_columns=[
                "sentiment_evidence",
                "sentiment_reason",
                "geo_value",
            ],
        )
    cards = st.columns(4)
    cards[0].metric("高价值评论", f"{len(filtered):,}")
    cards[1].metric(
        "消极",
        f"{int(sentiment_series(filtered).eq('N').sum()):,}",
    )
    cards[2].metric(
        "褒贬混合",
        f"{int(sentiment_series(filtered).eq('M').sum()):,}",
    )
    cards[3].metric(
        "AI 候选",
        f"{int(boolean_series(filtered, 'ai_candidate').sum()):,}",
    )
    download_csv(
        high_value_export(filtered),
        "下载高价值评论",
        "high_value_reviews",
        "brand_high_download",
    )
    table = pd.DataFrame(
        {
            "商品": filtered["_product_name"],
            "评论内容": filtered.get("content_text_clean", ""),
            "情绪": filtered["_sentiment_name"],
            "关键证据": filtered.get("sentiment_evidence", ""),
            "判断原因": filtered.get("sentiment_reason", ""),
            "内容价值": filtered.get("geo_value", ""),
            "AI 等级": filtered.get("evidence_level", ""),
            "评论时间": filtered.get("content_time", ""),
        }
    )
    st.dataframe(table, width="stretch", height=620, hide_index=True)


def render_brand_products(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    st.title("商品对比")
    summary = build_product_comparison(brand_content(sheets, project_id))
    if summary.empty:
        st.info("当前项目还没有可比较的商品数据。")
        return
    summary["商品"] = summary["product_title"].where(
        summary["product_title"].fillna("").astype(str).str.strip().ne(""),
        summary["item_key"],
    )
    summary["情绪覆盖率"] = summary["sentiment_coverage"].map(
        lambda value: f"{value:.1%}"
    )
    summary["AI 相关率"] = summary["ai_candidate_rate"].map(
        lambda value: f"{value:.1%}"
    )
    chart = px.bar(
        summary,
        x="review_count",
        y="商品",
        orientation="h",
        labels={"review_count": "评论数"},
    )
    chart.update_layout(
        height=max(340, min(720, 90 + len(summary) * 42)),
        yaxis={"categoryorder": "total ascending"},
    )
    st.plotly_chart(chart, width="stretch")
    shown = summary.rename(
        columns={
            "review_count": "评论",
            "question_count": "问大家",
            "positive_count": "积极",
            "negative_count": "消极",
            "mixed_count": "褒贬混合",
            "neutral_count": "中性",
            "ai_candidate_count": "AI 相关",
            "a_level_count": "A 级",
            "b_level_count": "B 级",
            "c_level_count": "C 级",
            "d_level_count": "D 级",
        }
    )
    columns = [
        "商品",
        "评论",
        "问大家",
        "积极",
        "消极",
        "褒贬混合",
        "中性",
        "情绪覆盖率",
        "AI 相关",
        "AI 相关率",
        "A 级",
        "B 级",
        "C 级",
        "D 级",
    ]
    st.dataframe(shown[columns], width="stretch", hide_index=True)


def render_brand_guide() -> None:
    st.title("看板说明")
    st.markdown(
        """
这个入口面向品牌侧查看者，只负责查看和导出，不承担数据更新。

- **品牌总览**：查看评论、问大家、情绪分类和 AI 影响 A–D 分级。
- **评论洞察**：按商品、情绪和 AI 等级筛选评论，查看表扬点与抱怨点。
- **购前评论**：单独查看消费者买前的比较、选择、顾虑和决策证据。
- **AI 影响**：查看逐月三色趋势，并集中查看 A–D 各级证据及对应原文。
- **月份汇总**：按月比较全部评论、购前评论和 AI 候选评论。
- **高价值评论**：查看经过详析的关键证据、判断原因和内容价值。
- **商品对比**：比较不同商品的反馈规模、情绪和 AI 相关情况。

若出现“未判别”，表示这些评论尚未完成情绪分析，不代表中性。页面数据由维护者在“维护后台”更新。
"""
    )


def render_maintenance_quality(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    snapshots = project_frame(sheets["snapshots"], project_id)
    updates = project_frame(sheets["update_log"], project_id)
    queue = project_frame(sheets["review_queue"], project_id)
    fallback_count = int(
        snapshots.get("boundary_status", pd.Series(dtype=str))
        .fillna("")
        .astype(str)
        .eq("fallback")
        .sum()
    )
    warning_count = int(
        updates.get("result", pd.Series(dtype=str))
        .fillna("")
        .astype(str)
        .isin(["warning", "failed"])
        .sum()
    )
    cards = st.columns(4)
    cards[0].metric("页面快照", f"{len(snapshots):,}")
    cards[1].metric("Fallback", f"{fallback_count:,}")
    cards[2].metric("警告或失败", f"{warning_count:,}")
    cards[3].metric("待复核", f"{unresolved_count(queue):,}")
    render_history(sheets, project_id, show_title=False)


def render_project_home(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    project_rows = project_frame(sheets["project_info"], project_id)
    project = project_rows.iloc[0]
    products = project_frame(sheets["products"], project_id)
    content = project_frame(sheets["content_master"], project_id)
    snapshots = project_frame(sheets["snapshots"], project_id)
    queue = project_frame(sheets["review_queue"], project_id)
    analysis = project_frame(sheets["analysis"], project_id)
    sentiment_fast = project_frame(
        sheets.get("sentiment_fast", pd.DataFrame()),
        project_id,
    )
    sentiment_failures = project_frame(
        sheets.get("sentiment_failures", pd.DataFrame()),
        project_id,
    )
    pending = unresolved_count(queue)
    latest = latest_time(snapshots, "capture_time")
    ai_count = 0
    if not analysis.empty and "ai_candidate" in analysis.columns:
        ai_count = int(analysis["ai_candidate"].map(as_bool).sum())

    st.title(str(project.get("project_name") or project_id))
    objective = project.get("objective")
    if objective is not None and not pd.isna(objective) and str(objective).strip():
        st.caption(str(objective))
    first = st.columns(5)
    first[0].metric("商品数", len(products))
    first[1].metric("累计内容", len(content))
    first[2].metric("AI 候选", ai_count)
    first[3].metric("待复核", pending)
    first[4].metric("最近快照", latest or "暂无")

    recent = snapshots.copy()
    if not recent.empty:
        recent["_capture"] = pd.to_datetime(
            recent["capture_time"], errors="coerce"
        )
        recent = recent.sort_values("_capture", ascending=False).drop(
            columns=["_capture"]
        )
    fallback_count = (
        int(
            recent["boundary_status"]
            .fillna("")
            .astype(str)
            .eq("fallback")
            .sum()
        )
        if not recent.empty
        else 0
    )
    warning_count = (
        int(
            project_frame(sheets["update_log"], project_id)["result"]
            .fillna("")
            .astype(str)
            .isin(["warning", "failed"])
            .sum()
        )
        if not project_frame(sheets["update_log"], project_id).empty
        else 0
    )
    quality = st.columns(3)
    quality[0].metric("快照总数", len(snapshots))
    quality[1].metric("Fallback 快照", fallback_count)
    quality[2].metric("警告或失败更新", warning_count)
    sentiment_metrics = st.columns(3)
    sentiment_metrics[0].metric("已判别情绪评论", len(sentiment_fast))
    sentiment_metrics[1].metric(
        "LLM 情绪评论",
        int(
            sentiment_fast.get(
                "sentiment_source",
                pd.Series(dtype=str),
            )
            .fillna("")
            .astype(str)
            .eq("llm_fast")
            .sum()
        ),
    )
    sentiment_metrics[2].metric("情绪失败记录", len(sentiment_failures))

    st.subheader("商品状态")
    if products.empty:
        st.info("项目还没有商品，请进入“批量更新”导入页面。")
    else:
        show_table(
            products,
            columns=[
                "platform_product_id",
                "brand_product_id",
                "brand",
                "model_name",
                "product_title_current",
                "shop_name_current",
                "last_updated_at",
                "identity_confidence",
            ],
            height=320,
        )

    content_view = compatibility_content(sheets, project_id)
    product_summary = sheets.get("summary_by_product", pd.DataFrame())
    if not content_view.empty:
        left, right = st.columns(2)
        with left:
            st.subheader("证据等级")
            st.plotly_chart(
                evidence_bar(content_view),
                width="stretch",
            )
        with right:
            st.subheader("商品 AI 候选")
            st.plotly_chart(
                product_rank_chart(product_summary, "ai_candidate_count"),
                width="stretch",
            )

    if not recent.empty:
        st.subheader("最近快照")
        show_table(
            recent.head(10),
            columns=[
                "capture_time",
                "item_key",
                "source_file",
                "extracted_count",
                "new_count",
                "existing_count",
                "uncertain_count",
                "boundary_status",
                "notes",
            ],
            height=320,
        )


def render_update_form(
    workbook: str,
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    st.title("批量更新")
    st.caption(
        "一次选择一个或多个 SingleFile HTML 或京东评论 CSV。商品 ID 自动识别，"
        "预览会按文件顺序模拟连续更新；LLM 只在确认写入后调用。"
    )
    with st.form("check_update"):
        platform = st.selectbox(
            "平台",
            ["自动识别", "tmall", "taobao", "jd"],
        )
        capture_time = st.text_input("保存时间（可留空自动读取）")
        brand_product_id = st.text_input("型号聚合 ID（可选）")
        enable_sentiment = st.checkbox(
            "启用 LLM 情绪判断",
            value=True,
            help=(
                "正式确认写入后，对本次新增评论执行情绪判断。"
                "预览阶段不会调用模型。"
            ),
        )
        sentiment_strategy = st.selectbox(
            "情绪判断策略",
            [
                "全量 LLM（默认）",
                "本地规则优先（节省调用）",
            ],
            disabled=not enable_sentiment,
            help=(
                "全量 LLM 会把每条新增评论和追评都提交给 DeepSeek 快判；"
                "详析仍只处理符合条件的高价值评论。"
            ),
        )
        sentiment_full_llm = sentiment_strategy.startswith("全量 LLM")
        sentiment_detail_limit = st.number_input(
            "情绪详析上限",
            min_value=0,
            max_value=1000,
            value=50,
            step=10,
            disabled=not enable_sentiment,
        )
        uploaded = st.file_uploader(
            "数据文件（SingleFile HTML 或京东评论 CSV，可多选）",
            type=["html", "htm", "csv"],
            accept_multiple_files=True,
        )
        checked = st.form_submit_button("检查更新")
    if checked:
        if not uploaded:
            st.error("请至少选择一个 HTML 或 CSV 数据文件。")
        else:
            files = [
                {"name": item.name, "bytes": item.getvalue()}
                for item in uploaded
            ]
            try:
                preview = _run_uploaded_updates(
                    workbook,
                    project_id,
                    files,
                    platform=(
                        None if platform == "自动识别" else platform
                    ),
                    capture_time=capture_time or None,
                    brand_product_id=brand_product_id or None,
                    enable_sentiment=enable_sentiment,
                    sentiment_full_llm=sentiment_full_llm,
                    sentiment_detail_limit=int(sentiment_detail_limit),
                    dry_run=True,
                )
            except Exception as exc:
                st.error(str(exc))
            else:
                st.session_state["tracking_preview"] = preview
                st.session_state["tracking_upload"] = {
                    "files": files,
                    "project_id": project_id,
                    "platform": (
                        None if platform == "自动识别" else platform
                    ),
                    "capture_time": capture_time or None,
                    "brand_product_id": brand_product_id or None,
                    "enable_sentiment": enable_sentiment,
                    "sentiment_full_llm": sentiment_full_llm,
                    "sentiment_detail_limit": int(sentiment_detail_limit),
                }

    preview = st.session_state.get("tracking_preview")
    payload = st.session_state.get("tracking_upload")
    if not preview or not payload or payload["project_id"] != project_id:
        return
    st.subheader("更新预览")
    st.dataframe(
        pd.DataFrame(preview_rows(preview)),
        width="stretch",
        hide_index=True,
    )
    for item in preview:
        if item.get("message"):
            st.warning(f"{item.get('source_file')}：{item['message']}")
        if item.get("error"):
            st.error(f"{item.get('source_file')}：{item['error']}")
    if st.button("确认写入", type="primary"):
        results = _run_uploaded_updates(
            workbook,
            payload["project_id"],
            payload["files"],
            platform=payload["platform"],
            capture_time=payload["capture_time"],
            brand_product_id=payload["brand_product_id"],
            enable_sentiment=payload["enable_sentiment"],
            sentiment_full_llm=payload.get("sentiment_full_llm", True),
            sentiment_detail_limit=payload["sentiment_detail_limit"],
            dry_run=False,
        )
        failed = [item for item in results if item.get("result") == "failed"]
        succeeded = [
            item for item in results if item.get("result") != "failed"
        ]
        st.success(
            f"已处理 {len(results)} 个文件，成功或警告 {len(succeeded)} 个，"
            f"新增内容 "
            f"{sum(int(item.get('new_count') or 0) for item in succeeded)} 条；"
            f"情绪判断 "
            f"{sum(int(item.get('sentiment_rule_count') or 0) + int(item.get('sentiment_llm_count') or 0) for item in succeeded)} 条，"
            f"其中 LLM 快判 "
            f"{sum(int(item.get('sentiment_llm_count') or 0) for item in succeeded)} 条。"
        )
        for item in succeeded:
            if item.get("sentiment_status") not in {
                "success",
                "disabled",
                "not_run_duplicate",
            }:
                st.warning(
                    f"{item.get('source_file')}：情绪判断 "
                    f"{item.get('sentiment_status')}，失败 "
                    f"{item.get('sentiment_failed_count', 0)} 条。"
                )
        for item in failed:
            st.error(f"{item.get('source_file')}：{item.get('error')}")
        if not failed:
            st.session_state.pop("tracking_preview", None)
            st.session_state.pop("tracking_upload", None)
            st.rerun()


def render_content_browser(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    st.title("内容浏览")
    content = compatibility_content(sheets, project_id)
    filtered = content_filters(content, "content")
    count_columns = st.columns(4)
    count_columns[0].metric("当前结果", len(filtered))
    count_columns[1].metric(
        "评论",
        int(role_series(filtered).isin(["review", "followup"]).sum()),
    )
    count_columns[2].metric(
        "问答",
        int(role_series(filtered).isin(["question", "answer"]).sum()),
    )
    count_columns[3].metric(
        "AI 候选",
        int(boolean_series(filtered, "ai_candidate").sum()),
    )
    download_csv(
        filtered,
        "下载当前筛选 CSV",
        "tracked_content",
        "tracked_content_download",
    )
    if filtered.empty:
        st.info("当前筛选条件下没有内容。")
        return
    show_table(
        filtered.head(2000),
        columns=[
            "content_id",
            "item_key",
            "platform",
            "platform_product_id",
            "product_title",
            "content_role",
            "content_text_clean",
            "parent_text_clean",
            "user_name_masked",
            "content_time",
            "sku",
            "pre_purchase_decision",
            "ai_candidate",
            "evidence_level",
            "matched_keywords",
            "sentiment_label_cn",
            "sentiment_score",
            "praise_cn",
            "complaint_cn",
            "sentiment_confidence",
            "sentiment_source",
            "identity_confidence",
            "first_seen_at",
            "last_seen_at",
            "source_file_last",
        ],
        height=600,
    )
    if len(filtered) > 2000:
        st.info("表格显示前 2,000 条；下载 CSV 可获得完整结果。")
    detail_lookup(filtered, "tracking_content_detail")


def render_ai_candidates(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    st.title("AI 候选")
    content = compatibility_content(sheets, project_id)
    if "ai_candidate" in content.columns:
        content = content[boolean_series(content, "ai_candidate")]
    filtered = content_filters(content, "ai")
    st.metric("AI 候选内容", len(filtered))
    download_csv(
        filtered,
        "下载 AI 候选 CSV",
        "tracked_ai_candidates",
        "tracked_ai_download",
    )
    if filtered.empty:
        st.info("当前项目还没有 AI 候选内容。")
        return
    order = {"A": 0, "B": 1, "C": 2, "D": 3}
    level_series = (
        filtered["evidence_level"]
        if "evidence_level" in filtered.columns
        else pd.Series("", index=filtered.index)
    )
    if "match_score" not in filtered.columns:
        filtered["match_score"] = 0
    filtered = filtered.assign(
        _level=level_series.map(order).fillna(9)
    ).sort_values(["_level", "match_score"], ascending=[True, False])
    filtered = filtered.drop(columns=["_level"])
    show_table(
        filtered,
        columns=[
            "content_id",
            "item_key",
            "product_title",
            "content_role",
            "content_text_clean",
            "pre_purchase_decision",
            "ai_influence_level",
            "evidence_level",
            "matched_keywords",
            "match_score",
            "sentiment_label_cn",
            "sentiment_score",
            "praise_cn",
            "complaint_cn",
            "first_seen_at",
            "source_file_last",
        ],
        height=620,
    )
    detail_lookup(filtered, "tracking_ai_detail")


def render_product_summary(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    del project_id
    st.title("商品汇总")
    summary = sheets.get("summary_by_product", pd.DataFrame()).copy()
    if summary.empty:
        st.info("当前项目还没有商品汇总数据。")
        return
    st.plotly_chart(
        product_rank_chart(summary, "ai_candidate_count"),
        width="stretch",
    )
    download_csv(
        summary,
        "下载商品汇总 CSV",
        "summary_by_product",
        "tracking_product_download",
    )
    show_table(summary, height=560)


def render_keyword_summary(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    del project_id
    st.title("关键词汇总")
    summary = sheets.get("summary_by_keyword", pd.DataFrame()).copy()
    if summary.empty:
        st.info("当前项目还没有关键词汇总数据。")
        return
    types = sorted(
        value
        for value in summary.get("keyword_type", pd.Series(dtype=str))
        .fillna("")
        .astype(str)
        .unique()
        if value
    )
    selected = st.multiselect("关键词类型", types)
    if selected:
        summary = summary[summary["keyword_type"].isin(selected)]
    st.plotly_chart(keyword_rank_chart(summary), width="stretch")
    download_csv(
        summary,
        "下载关键词汇总 CSV",
        "summary_by_keyword",
        "tracking_keyword_download",
    )
    show_table(summary, height=560)


def render_history(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
    *,
    show_title: bool = True,
) -> None:
    if show_title:
        st.title("快照与更新日志")
    else:
        st.subheader("快照与更新日志")
    snapshots = project_frame(sheets["snapshots"], project_id)
    updates = project_frame(sheets["update_log"], project_id)
    if not snapshots.empty:
        snapshots = snapshots.assign(
            _capture=pd.to_datetime(
                snapshots["capture_time"], errors="coerce"
            )
        ).sort_values("_capture", ascending=False).drop(columns=["_capture"])
    if not updates.empty:
        updates = updates.assign(
            _update=pd.to_datetime(
                updates["update_time"], errors="coerce"
            )
        ).sort_values("_update", ascending=False).drop(columns=["_update"])
    tabs = st.tabs(["页面快照", "更新日志"])
    with tabs[0]:
        if snapshots.empty:
            st.info("暂无快照。")
        else:
            status_options = sorted(
                snapshots["boundary_status"]
                .fillna("")
                .astype(str)
                .unique()
            )
            selected = st.multiselect(
                "边界状态",
                [value for value in status_options if value],
                key="snapshot_status",
            )
            shown = (
                snapshots[
                    snapshots["boundary_status"].fillna("").isin(selected)
                ]
                if selected
                else snapshots
            )
            download_csv(
                shown,
                "下载快照 CSV",
                "snapshots",
                "tracking_snapshot_download",
            )
            show_table(shown, height=580)
    with tabs[1]:
        if updates.empty:
            st.info("暂无更新日志。")
        else:
            download_csv(
                updates,
                "下载更新日志 CSV",
                "update_log",
                "tracking_update_log_download",
            )
            show_table(updates, height=580)


def render_review_queue(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    st.title("待复核队列")
    queue = project_frame(sheets["review_queue"], project_id)
    if queue.empty:
        st.success("当前没有待复核记录。")
        return
    unresolved_only = st.checkbox("只看未解决", value=True)
    if unresolved_only:
        queue = queue[~queue["resolved"].map(as_bool)]
    st.metric("当前待复核记录", len(queue))
    download_csv(
        queue,
        "下载待复核 CSV",
        "review_queue",
        "tracking_queue_download",
    )
    show_table(
        queue,
        columns=[
            "queue_id",
            "item_key",
            "snapshot_id",
            "candidate_text",
            "possible_existing_content_id",
            "match_reason",
            "similarity",
            "recommended_action",
            "resolved",
            "resolved_action",
        ],
        height=620,
    )


def render_extended_analysis(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> None:
    st.title("扩展分析")
    supported = [
        name
        for name in (
            "sentiment_fast",
            "sentiment_detail",
            "sentiment_summary",
            "sentiment_run_summary",
            "sentiment_failures",
            "sentiment_timings",
            "llm_review_analysis",
            "llm_praise_items",
            "llm_complaint_items",
        )
        if name in sheets and not sheets[name].empty
    ]
    if not supported:
        st.info(
            "当前持续追踪工作簿还没有情感或 LLM 扩展分析。"
            "基础内容和 AI 候选请使用左侧对应页面。"
        )
        return
    sheet_name = st.selectbox("分析数据", supported)
    frame = project_frame(sheets[sheet_name], project_id)
    download_csv(
        frame,
        f"下载 {sheet_name} CSV",
        sheet_name,
        "tracking_extended_download",
    )
    show_table(frame, height=640)


def render_usage_guide() -> None:
    st.title("维护说明")
    st.markdown(
        """
这个入口只给项目维护者使用。品牌侧查看者应停留在“品牌看板”，
不需要上传文件或处理数据质量问题。

### 更新数据

1. 进入“数据更新”，选择 SingleFile HTML 或京东评论 CSV；两种文件可以一起上传。
2. 商品 ID 从每个页面自动读取；页面没有商品 ID 时会报错，不会写入。
3. 点击“检查更新”查看新增、重复、待确认和边界状态；预览不会调用 LLM。
4. 点击“确认写入”后才更新工作簿，并默认把每条新增评论和追评提交给 LLM 快判。
5. 已存在评论不会在普通更新中重复调用模型。

### 维护页面

- **项目状态**：查看商品、内容、快照、待复核和情绪覆盖情况。
- **数据质量与日志**：集中查看 fallback、警告、失败、页面快照和更新日志。
- **待复核队列**：处理身份信息不足的疑似重复内容。
- **扩展分析**：检查情绪快判、详析、失败和 LLM 运行摘要。

### 边界状态

- `first_import`：该商品第一次导入。
- `overlap_found`：找到了可靠的连续重叠评论段。
- `fallback`：没有找到可靠连续边界，系统改用内容主表的集合比对保证更新可继续。
- `duplicate_file`：同一个页面文件已经导入过。

如果 LLM 配置或网络异常，原始内容仍会保存，更新会显示 warning；
具体原因在“扩展分析”的 `sentiment_failures` 和
`sentiment_run_summary` 中查看。
"""
    )


def project_frame(frame: pd.DataFrame, project_id: str) -> pd.DataFrame:
    if frame.empty or "project_id" not in frame.columns:
        return frame.copy()
    return frame[
        frame["project_id"].fillna("").astype(str).eq(project_id)
    ].copy()


def brand_content(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> pd.DataFrame:
    content = compatibility_content(sheets, project_id)
    fast = project_frame(
        sheets.get("sentiment_fast", pd.DataFrame()),
        project_id,
    )
    if content.empty or fast.empty or "content_id" not in content.columns:
        return content
    sentiment_columns = [
        column
        for column in (
            "sentiment_label",
            "sentiment_label_cn",
            "sentiment_score",
            "praise_cn",
            "complaint_cn",
            "sentiment_confidence",
            "sentiment_source",
        )
        if column in fast.columns
    ]
    if not sentiment_columns:
        return content
    latest = fast.drop_duplicates("content_id", keep="last").set_index(
        "content_id"
    )
    result = content.copy()
    ids = result["content_id"]
    for column in sentiment_columns:
        values = ids.map(latest[column])
        if column not in result.columns:
            result[column] = values
        else:
            current = result[column]
            missing = current.isna() | current.astype(str).str.strip().eq("")
            result.loc[missing, column] = values[missing]
    return result


def high_value_content(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> pd.DataFrame:
    content = brand_content(sheets, project_id)
    detail = project_frame(
        sheets.get("sentiment_detail", pd.DataFrame()),
        project_id,
    )
    if (
        content.empty
        or detail.empty
        or "content_id" not in content.columns
        or "content_id" not in detail.columns
    ):
        return content.iloc[0:0].copy()
    detail_columns = [
        column
        for column in (
            "content_id",
            "sentiment_evidence",
            "sentiment_reason",
            "geo_value",
        )
        if column in detail.columns
    ]
    latest = detail[detail_columns].drop_duplicates(
        "content_id",
        keep="last",
    )
    return content.merge(
        latest,
        on="content_id",
        how="inner",
    )


def product_name_series(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series("", index=frame.index, dtype=str)
    title = frame.get(
        "product_title",
        frame.get(
            "product_title_current",
            pd.Series("", index=frame.index),
        ),
    ).fillna("").astype(str)
    item = frame.get(
        "item_key",
        pd.Series("", index=frame.index),
    ).fillna("").astype(str)
    return title.where(title.str.strip().ne(""), item)


def brand_review_export(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        column
        for column in (
            "product_title",
            "item_key",
            "content_text_clean",
            "parent_text_clean",
            "content_time",
            "sku",
            "sentiment_label_cn",
            "sentiment_label",
            "sentiment_score",
            "praise_cn",
            "complaint_cn",
            "evidence_level",
            "matched_keywords",
        )
        if column in frame.columns
    ]
    return frame[columns].copy()


def high_value_export(frame: pd.DataFrame) -> pd.DataFrame:
    base = brand_review_export(frame)
    for column in (
        "sentiment_evidence",
        "sentiment_reason",
        "geo_value",
    ):
        if column in frame.columns:
            base[column] = frame[column]
    return base


def filter_brand_query(
    frame: pd.DataFrame,
    query: str,
    *,
    extra_columns: list[str] | None = None,
) -> pd.DataFrame:
    searchable = [
        "content_text_clean",
        "parent_text_clean",
        "matched_keywords",
        "sku",
        *(extra_columns or []),
    ]
    mask = pd.Series(False, index=frame.index)
    for column in searchable:
        if column in frame.columns:
            mask |= frame[column].fillna("").astype(str).str.contains(
                query,
                case=False,
                regex=False,
            )
    return frame[mask]


def compatibility_content(
    sheets: dict[str, pd.DataFrame],
    project_id: str,
) -> pd.DataFrame:
    content = sheets.get("content_all", pd.DataFrame()).copy()
    return project_frame(content, project_id)


def content_filters(frame: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    controls = st.columns(4)
    item_options = options(result, "item_key")
    role_options = options(result, "content_role")
    level_options = options(result, "evidence_level")
    with controls[0]:
        items = st.multiselect(
            "商品",
            item_options,
            key=f"{key_prefix}_items",
        )
    with controls[1]:
        roles = st.multiselect(
            "内容类型",
            role_options,
            key=f"{key_prefix}_roles",
        )
    with controls[2]:
        levels = st.multiselect(
            "证据等级",
            level_options,
            key=f"{key_prefix}_levels",
        )
    with controls[3]:
        ai_only = st.checkbox(
            "只看 AI 候选",
            key=f"{key_prefix}_ai_only",
        )
    query = st.text_input(
        "搜索正文、问答或关键词",
        key=f"{key_prefix}_query",
    ).strip()
    if items:
        result = result[result["item_key"].fillna("").isin(items)]
    if roles:
        result = result[result["content_role"].fillna("").isin(roles)]
    if levels and "evidence_level" in result.columns:
        result = result[result["evidence_level"].fillna("").isin(levels)]
    if ai_only and "ai_candidate" in result.columns:
        result = result[boolean_series(result, "ai_candidate")]
    if query:
        searchable = [
            column
            for column in (
                "content_text_clean",
                "content_text_raw",
                "parent_text_clean",
                "matched_keywords",
                "sku",
            )
            if column in result.columns
        ]
        mask = pd.Series(False, index=result.index)
        for column in searchable:
            mask = mask | result[column].fillna("").astype(str).str.contains(
                query,
                case=False,
                regex=False,
            )
        result = result[mask]
    return result


def options(frame: pd.DataFrame, column: str) -> list[str]:
    if frame.empty or column not in frame.columns:
        return []
    return sorted(
        value
        for value in frame[column].fillna("").astype(str).unique()
        if value
    )


def preview_rows(preview: list[dict]) -> list[dict]:
    return [
        {
            "文件": item.get("source_file"),
            "页面商品 ID": item.get("extracted_product_id", ""),
            "首次导入": item.get("is_first_import", ""),
            "最近快照": item.get("latest_snapshot_id") or "无",
            "提取数": item.get("extracted_count", ""),
            "新增": item.get("new_count", ""),
            "已存在": item.get("existing_count", ""),
            "待确认": item.get("uncertain_count", ""),
            "边界状态": item.get("boundary_status", ""),
            "连续重叠": item.get("overlap_length", ""),
            "情绪目标": item.get("sentiment_target_count", 0),
            "情绪策略": item.get("sentiment_strategy", ""),
            "情绪状态": item.get("sentiment_status", ""),
            "结果": item.get("result", ""),
            "错误": item.get("error", ""),
        }
        for item in preview
    ]


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    return str(value).strip().casefold() in {
        "1",
        "true",
        "yes",
        "y",
    }


def boolean_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].map(as_bool)


def role_series(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "content_role" not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame["content_role"].fillna("").astype(str)


def unresolved_count(queue: pd.DataFrame) -> int:
    if queue.empty or "resolved" not in queue.columns:
        return 0
    return int((~queue["resolved"].map(as_bool)).sum())


def latest_time(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return ""
    value = pd.to_datetime(frame[column], errors="coerce").max()
    if pd.isna(value):
        return ""
    return value.strftime("%Y-%m-%d %H:%M")


def _run_uploaded_updates(
    workbook: str,
    project_id: str,
    files: list[dict],
    **kwargs,
) -> list[dict]:
    with tempfile.TemporaryDirectory() as temp_dir:
        paths = []
        for index, item in enumerate(files):
            folder = Path(temp_dir) / str(index)
            folder.mkdir()
            temp_path = folder / (
                Path(item["name"]).name or "uploaded.html"
            )
            temp_path.write_bytes(item["bytes"])
            paths.append(str(temp_path))
        return update_project_files(
            workbook,
            project_id,
            paths,
            **kwargs,
        )


if __name__ == "__main__":
    main()
