from __future__ import annotations

from io import BytesIO
from html import escape
from pathlib import Path
import hashlib
import pandas as pd
import streamlit as st

from ui.cards import ai_candidate_card, review_card
from ui.charts import (
    evidence_bar,
    funnel_chart,
    keyword_rank_chart,
    monthly_trend_chart,
    product_rank_chart,
    sentiment_category_chart,
    sentiment_distribution_chart,
)
from ui.data_loader import (
    ExcelLoadError,
    apply_project_alias,
    build_capture_quality_warnings,
    build_summary_by_keyword,
    build_summary_by_product,
    build_summary_by_month,
    enrich_with_sentiment,
    get_ai_sentiment,
    get_ai_candidates,
    get_content_all,
    get_high_value_sentiment,
    get_pre_purchase,
    get_sentiment_joined,
    latest_output_file,
    list_output_files,
    load_excel,
    merge_workbooks,
    summarize_sentiment,
    summarize_content,
)
from ui.projects import (
    ProjectSummary,
    infer_run_at,
    load_registry,
    project_alias,
    save_project_alias,
    summarize_project,
)
from ui.export import markdown_cases, timestamp
from ui.feedback import feedback_form, load_feedback
from ui.filters import apply_filters, keyword_type_filter, page_boolean_filter, sidebar_filters
from ui.styles import inject_css, metric_cards
from ui.tables import detail_lookup, download_csv, show_table


st.set_page_config(
    page_title="电商评论 AI 影响力中文复核台",
    page_icon="",
    layout="wide",
)
inject_css()


def main() -> None:
    st.sidebar.title("AI 影响力中文复核台")
    data, info = load_workbook_from_sidebar()
    content = get_content_all(data)
    filters = sidebar_filters(content)
    filtered_content = apply_filters(content, filters)

    page = st.sidebar.radio(
        "页面",
        [
            "数据总览",
            "购前决策评论",
            "AI 候选证据库",
            "全部内容",
            "商品汇总",
            "关键词汇总",
            "月份汇总",
            "情感快判",
            "高价值评论",
            "AI 相关情感",
            "调试与错误",
            "复核记录",
        ],
    )
    st.sidebar.caption(f"当前文件：{info.source_name}")
    if info.missing_core_sheets:
        st.sidebar.warning("缺失 Sheet：" + "、".join(info.missing_core_sheets))

    if page == "数据总览":
        dashboard_page(filtered_content, data)
    elif page == "购前决策评论":
        pre_purchase_page(apply_filters(enrich_with_sentiment(get_pre_purchase(data), data), filters))
    elif page == "AI 候选证据库":
        ai_candidates_page(apply_filters(enrich_with_sentiment(get_ai_candidates(data), data), filters))
    elif page == "全部内容":
        all_content_page(enrich_with_sentiment(filtered_content, data))
    elif page == "商品汇总":
        product_summary_page(data, filtered_content)
    elif page == "关键词汇总":
        keyword_summary_page(data, filtered_content)
    elif page == "月份汇总":
        month_summary_page(data, filtered_content)
    elif page == "情感快判":
        sentiment_page(data, filters)
    elif page == "高价值评论":
        high_value_sentiment_page(data, filters)
    elif page == "AI 相关情感":
        ai_sentiment_page(data, filters)
    elif page == "调试与错误":
        debug_page(data)
    elif page == "复核记录":
        feedback_page()


@st.cache_data(show_spinner=False)
def cached_load_from_path(path: str):
    return load_excel(path)


@st.cache_data(show_spinner=False)
def cached_load_from_paths(projects: tuple[tuple[str, str], ...]):
    return merge_workbooks([apply_project_alias(load_excel(path), alias) for path, alias in projects])


@st.cache_data(show_spinner=False)
def cached_load_from_upload(file_name: str, file_bytes: bytes, alias: str):
    buffer = BytesIO(file_bytes)
    buffer.name = file_name
    return apply_project_alias(load_excel(buffer), alias)


@st.cache_data(show_spinner=False)
def cached_project_summary(path: str, modified_ns: int):
    del modified_ns
    try:
        return summarize_project(path)
    except Exception:  # A damaged historical file should not break the project picker.
        return ProjectSummary(0, 0, infer_run_at(path), 0, 0)


def load_workbook_from_sidebar():
    uploaded = st.sidebar.file_uploader("上传 Excel", type=["xlsx"])
    output_files = list_output_files("output")
    default_file = latest_output_file("output")
    registry = load_registry("output")
    aliases = {str(path): project_alias(path, registry) for path in output_files}
    selected_files: list[str] = []
    if uploaded is not None:
        upload_alias = st.sidebar.text_input(
            "上传项目别名",
            value=Path(uploaded.name).stem,
            help="别名只用于复核台展示，不会修改原始 Excel 文件名。",
        )
    else:
        upload_alias = ""

    if output_files:
        default_path = str(default_file or output_files[0])
        st.sidebar.caption("output 分析项目")
        with st.sidebar.popover("选择项目", width="stretch"):
            st.caption("悬停项目名查看文件摘要，可多选合并分析。")
            for path in output_files:
                path_text = str(path)
                key_hash = hashlib.sha1(path_text.encode("utf-8")).hexdigest()[:12]
                summary = cached_project_summary(path_text, path.stat().st_mtime_ns)
                checked = st.checkbox(
                    aliases[path_text],
                    value=path_text == default_path,
                    key=f"project_selected_{key_hash}",
                    help=summary.tooltip(path.name),
                )
                if checked:
                    selected_files.append(path_text)

        with st.sidebar.expander("编辑项目别名"):
            edit_path = st.selectbox(
                "项目",
                [str(path) for path in output_files],
                format_func=lambda value: aliases[value],
                label_visibility="collapsed",
            )
            edit_alias = st.text_input(
                "新别名",
                value=aliases[edit_path],
                key=f"project_alias_{hashlib.sha1(edit_path.encode('utf-8')).hexdigest()[:12]}",
            )
            if st.button("保存别名", width="stretch"):
                save_project_alias(edit_path, edit_alias, "output")
                st.cache_data.clear()
                st.rerun()

        if selected_files:
            selected_labels = [aliases[path] for path in selected_files]
            st.sidebar.markdown(
                "已选择：" + "、".join(f"<strong>{escape(label)}</strong>" for label in selected_labels),
                unsafe_allow_html=True,
            )
        if len(selected_files) > 1:
            st.sidebar.info(f"已合并 {len(selected_files)} 个分析项目")
    else:
        st.sidebar.info("没有找到 output/*.xlsx")

    try:
        if uploaded is not None:
            return cached_load_from_upload(uploaded.name, uploaded.getvalue(), upload_alias)
        if len(selected_files) == 1:
            return apply_project_alias(cached_load_from_path(selected_files[0]), aliases[selected_files[0]])
        if len(selected_files) > 1:
            projects = tuple((path, aliases[path]) for path in selected_files)
            return cached_load_from_paths(projects)
    except ExcelLoadError as exc:
        st.error(str(exc))
        st.stop()

    st.info("请上传脚本输出的 Excel，或先运行 main.py 生成 output/*.xlsx。")
    st.stop()


def dashboard_page(content: pd.DataFrame, data: dict[str, pd.DataFrame]) -> None:
    st.title("数据总览")
    st.caption("先看清楚分母：全部内容行包含商品评论和问大家；购前决策、情感快判等指标只以商品评论为分母。")
    summary = summarize_content(content)
    summary.setdefault("total_content", summary.get("total", len(content)))
    if "review_count" not in summary:
        if "content_role" in content.columns:
            summary["review_count"] = int((content["content_role"].astype(str) == "review").sum())
        else:
            summary["review_count"] = summary.get("total_content", 0)
    if "qa_count" not in summary:
        if "content_role" in content.columns:
            roles = content["content_role"].astype(str)
            summary["qa_count"] = int(roles.isin(["question", "answer"]).sum())
        else:
            summary["qa_count"] = 0
    if "ai_rate_total" not in summary:
        review_count = summary.get("review_count", 0)
        summary["ai_rate_total"] = summary.get("ai_candidates", 0) / review_count if review_count else 0
    metric_cards(
        [
            (
                "全部内容行",
                f"{summary['total_content']:,}",
                f"商品评论 {summary['review_count']:,} ｜ 问大家 {summary['qa_count']:,}",
            ),
            ("商品评论数", f"{summary['review_count']:,}", f"平台 {summary['platforms']} ｜ 商品 {summary['products']}"),
            ("购前决策评论数", f"{summary['pre_purchase']:,}", "仅统计 content_role=review 的商品评论"),
            (
                "AI 候选评论 / 购前决策评论",
                f"{summary['ai_rate_pre_purchase']:.1%}",
                f"AI 候选评论 {summary['ai_candidates']:,} ｜ 占商品评论 {summary['ai_rate_total']:.1%}",
            ),
        ]
    )
    left, right = st.columns([1.1, 1])
    with left:
        st.subheader("评论筛选漏斗")
        st.plotly_chart(funnel_chart(summary), width="stretch")
    with right:
        st.subheader("证据等级分布")
        st.plotly_chart(evidence_bar(content), width="stretch")
    st.subheader("商品 AI 候选 Top 10")
    product_summary = build_summary_by_product(content)
    st.plotly_chart(product_rank_chart(product_summary, "ai_candidate_count"), width="stretch")

    sentiment = get_sentiment_joined(data)
    if not sentiment.empty:
        st.subheader("情感快判概览")
        sentiment_summary = summarize_sentiment(data)
        metric_cards(
            [
                ("快判评论数", f"{sentiment_summary['total_count']:,}", f"平均情感分：{sentiment_summary['average_score']:.1f}"),
                ("规则处理数", f"{sentiment_summary['rule_count']:,}", f"占比：{_rate(sentiment_summary['rule_count'], sentiment_summary['total_count'])}"),
                ("LLM 快判数", f"{sentiment_summary['llm_fast_count']:,}", f"占比：{_rate(sentiment_summary['llm_fast_count'], sentiment_summary['total_count'])}"),
                ("详析 / 失败", f"{sentiment_summary['detail_count']:,} / {sentiment_summary['failed_count']:,}", sentiment_summary.get("status", "") or "情感管线"),
            ]
        )
        left, right = st.columns([1, 1])
        with left:
            st.plotly_chart(sentiment_distribution_chart(sentiment), width="stretch")
        with right:
            st.plotly_chart(sentiment_category_chart(sentiment, "complaint_cn", "主要吐槽"), width="stretch")


def pre_purchase_page(frame: pd.DataFrame) -> None:
    st.title("购前决策评论")
    st.caption("用于复核哪些评论真的在解释买前怎么选、值不值、怕不怕踩坑。")
    frame = page_boolean_filter(frame, "ai_candidate", "是否 AI 候选", "pre_ai_filter")
    render_card_list(frame, "pre_purchase")


def ai_candidates_page(frame: pd.DataFrame) -> None:
    st.title("AI 候选证据库")
    st.caption("只展示 A/B/C，不展示 D。C 级默认视为需要人工复核。")
    if not frame.empty and "evidence_level" in frame.columns:
        order = {"A": 0, "B": 1, "C": 2}
        frame = frame.assign(_level_order=frame["evidence_level"].map(order).fillna(9))
        sort_cols = ["_level_order"]
        ascending = [True]
        if "match_score" in frame.columns:
            sort_cols.append("match_score")
            ascending.append(False)
        frame = frame.sort_values(sort_cols, ascending=ascending).drop(columns=["_level_order"])
    left, right = st.columns([1, 1])
    with left:
        download_csv(frame, "下载 AI 候选案例 CSV", "ai_candidates", "ai_csv")
    with right:
        st.download_button(
            "下载报告案例文档",
            data=markdown_cases(frame).encode("utf-8"),
            file_name=f"ai_candidate_cases_{timestamp()}.md",
            mime="text/markdown",
        )
    for idx, (_, row) in enumerate(frame.head(80).iterrows()):
        ai_candidate_card(row, idx)
    if len(frame) > 80:
        st.info(f"已展示前 80 条，当前筛选共有 {len(frame)} 条。可下载 CSV 查看全部。")


def all_content_page(frame: pd.DataFrame) -> None:
    st.title("全部内容")
    st.caption("完整追溯与排查视图，包含商品评论以及问大家问题和回答。")
    frame = page_boolean_filter(frame, "pre_purchase_decision", "购前决策", "all_pre_filter")
    frame = page_boolean_filter(frame, "ai_candidate", "AI 候选", "all_ai_filter")
    columns = [
        "content_id",
        "workbook_source",
        "platform",
        "product_title",
        "record_type",
        "content_text_clean",
        "pre_purchase_decision",
        "ai_candidate",
        "evidence_level",
        "sentiment_label_cn",
        "sentiment_score",
        "praise_cn",
        "complaint_cn",
        "sentiment_confidence",
        "matched_keywords",
        "exclude_reason",
        "source_file",
    ]
    download_csv(frame, "下载当前筛选 CSV", "content_all_filtered", "all_csv")
    show_table(frame, columns=columns, height=560)
    detail_lookup(frame, "all_detail_lookup")


def product_summary_page(data: dict[str, pd.DataFrame], filtered_content: pd.DataFrame) -> None:
    st.title("商品汇总")
    summary = build_summary_by_product(filtered_content)
    if "ai_candidate_rate_total" not in summary.columns and "content_count" in summary.columns:
        summary = summary.copy()
        summary["ai_candidate_rate_total"] = summary["ai_candidate_count"] / summary["content_count"].replace(0, pd.NA)
    left, right = st.columns(2)
    with left:
        st.subheader("Top 10：AI 候选数")
        st.plotly_chart(product_rank_chart(summary, "ai_candidate_count"), width="stretch")
    with right:
        st.subheader("Top 10：AI 候选 / 购前决策")
        st.plotly_chart(product_rank_chart(summary, "ai_candidate_rate"), width="stretch")
    download_csv(summary, "下载商品汇总 CSV", "summary_by_product", "product_csv")
    show_table(summary, height=520)


def keyword_summary_page(data: dict[str, pd.DataFrame], filtered_content: pd.DataFrame) -> None:
    st.title("关键词汇总")
    summary = build_summary_by_keyword(filtered_content)
    summary = keyword_type_filter(summary, "keyword_type_filter")
    st.plotly_chart(keyword_rank_chart(summary), width="stretch")
    download_csv(summary, "下载关键词汇总 CSV", "summary_by_keyword", "keyword_csv")
    show_table(summary, height=520)


def month_summary_page(data: dict[str, pd.DataFrame], filtered_content: pd.DataFrame) -> None:
    st.title("月份汇总")
    summary = build_summary_by_month(filtered_content)
    st.caption("按评论日期看趋势，帮助判断 AI 相关提及是否随时间增加。")
    st.plotly_chart(monthly_trend_chart(summary), width="stretch")
    download_csv(summary, "下载月份汇总 CSV", "summary_by_month", "month_csv")
    show_table(summary, height=520)


def sentiment_page(data: dict[str, pd.DataFrame], filters: dict) -> None:
    st.title("情感快判")
    st.caption("数据源优先使用 sentiment_fast；sentiment_detail 只作为少量高价值评论的补充，不代表总体分布。")
    frame = apply_filters(get_sentiment_joined(data), filters)
    frame = sentiment_filter_controls(frame, "sentiment")
    render_sentiment_overview(data, frame)
    st.plotly_chart(sentiment_category_chart(frame, "complaint_cn", "主要吐槽"), width="stretch")
    columns = [
        "content_id",
        "workbook_source",
        "platform",
        "product_title",
        "sku",
        "content_text_clean",
        "sentiment_label_cn",
        "sentiment_score",
        "praise_cn",
        "complaint_cn",
        "sentiment_confidence",
        "sentiment_source",
        "ai_candidate",
        "evidence_level",
    ]
    download_csv(frame, "下载情感快判 CSV", "sentiment_fast_filtered", "sentiment_csv")
    show_table(frame, columns=columns, height=520)
    detail_lookup(frame, "sentiment_detail_lookup")


def high_value_sentiment_page(data: dict[str, pd.DataFrame], filters: dict) -> None:
    st.title("高价值评论")
    st.caption("只展示 sentiment_detail 中出现的评论，通常包含负向、混合、低置信、AI 相关或长评论。")
    frame = apply_filters(get_high_value_sentiment(data), filters)
    frame = sentiment_filter_controls(frame, "high_value")
    columns = [
        "content_id",
        "platform",
        "product_title",
        "content_text_clean",
        "sentiment_label_cn",
        "sentiment_score",
        "sentiment_evidence",
        "sentiment_reason",
        "geo_value",
        "ai_candidate",
        "evidence_level",
    ]
    download_csv(frame, "下载高价值评论 CSV", "sentiment_detail_filtered", "sentiment_detail_csv")
    show_table(frame, columns=columns, height=560)
    detail_lookup(frame, "high_value_detail_lookup")


def ai_sentiment_page(data: dict[str, pd.DataFrame], filters: dict) -> None:
    st.title("AI 相关情感")
    st.caption("在 AI 候选评论中查看情感分布、夸法/吐槽分布和高价值样本。")
    frame = apply_filters(get_ai_sentiment(data), filters)
    frame = sentiment_filter_controls(frame, "ai_sentiment")
    if frame.empty:
        st.info("当前文件没有可展示的 AI 相关情感记录。")
        return
    summary = summarize_sentiment({"sentiment_fast": frame})
    metric_cards(
        [
            ("AI 情感评论数", f"{len(frame):,}", f"平均情感分：{summary['average_score']:.1f}"),
            ("负向 / 混合", f"{summary['sentiment_N']:,} / {summary['sentiment_M']:,}", "重点复核样本"),
            ("正向", f"{summary['sentiment_P']:,}", "可看主要夸法"),
            ("低置信", f"{int((frame.get('sentiment_confidence', pd.Series(dtype=int)) == 1).sum()):,}", "建议人工复核"),
        ]
    )
    left, right = st.columns(2)
    with left:
        st.plotly_chart(sentiment_distribution_chart(frame), width="stretch")
    with right:
        st.plotly_chart(sentiment_category_chart(frame, "praise_cn", "主要夸法"), width="stretch")
    st.plotly_chart(sentiment_category_chart(frame, "complaint_cn", "主要吐槽"), width="stretch")
    download_csv(frame, "下载 AI 相关情感 CSV", "ai_sentiment_filtered", "ai_sentiment_csv")
    show_table(
        frame,
        columns=[
            "content_id",
            "platform",
            "product_title",
            "content_text_clean",
            "sentiment_label_cn",
            "sentiment_score",
            "praise_cn",
            "complaint_cn",
            "sentiment_confidence",
            "evidence_level",
            "matched_sentence",
            "sentiment_evidence",
            "geo_value",
        ],
        height=520,
    )


def debug_page(data: dict[str, pd.DataFrame]) -> None:
    st.title("调试与错误")
    errors = data.get("errors", pd.DataFrame())
    debug_samples = data.get("debug_samples", pd.DataFrame())
    sentiment_run = data.get("sentiment_run_summary", pd.DataFrame())
    sentiment_failures = data.get("sentiment_failures", pd.DataFrame())
    sentiment_timings = data.get("sentiment_timings", pd.DataFrame())
    tabs = st.tabs(["解析错误", "低置信度样本", "平台质量提示", "情感运行", "情感失败", "情感耗时"])
    with tabs[0]:
        if errors.empty:
            st.success("当前文件没有解析错误记录。")
        else:
            download_csv(errors, "下载解析错误 CSV", "errors", "errors_csv")
            show_table(errors, height=440)
    with tabs[1]:
        if debug_samples.empty:
            st.info("当前文件没有低置信度样本。")
        else:
            download_csv(debug_samples, "下载低置信度样本 CSV", "debug_samples", "debug_csv")
            show_table(debug_samples, height=440)
    with tabs[2]:
        content = get_content_all(data)
        capture_warnings = build_capture_quality_warnings(content)
        if capture_warnings.empty:
            st.success("未发现“评论极少、问大家很多”的明显页面保存不足提示。")
        else:
            st.warning(
                "部分页面仅保存了少量评论预览卡片，但保存了大量问大家内容；"
                "这通常是 SingleFile 保存前没有完整加载评论区。"
            )
            show_table(capture_warnings)
        if {"declared_review_count", "saved_comment_card_count"}.issubset(content.columns):
            risky = content[
                pd.to_numeric(content["declared_review_count"], errors="coerce").fillna(0)
                > pd.to_numeric(content["saved_comment_card_count"], errors="coerce").fillna(0) * 2
            ]
            if not risky.empty:
                st.warning("部分京东页面只保存了当前可见或已渲染评价，不能代表完整评论池。")
                show_table(risky)
    with tabs[3]:
        if sentiment_run.empty:
            st.info("当前文件没有 sentiment_run_summary。")
        else:
            status = str(sentiment_run.iloc[0].get("status", ""))
            if status and status != "success":
                st.warning(f"情感管线状态：{status}")
            show_table(sentiment_run, height=220)
    with tabs[4]:
        if sentiment_failures.empty:
            st.success("当前文件没有情感处理失败记录。")
        else:
            download_csv(sentiment_failures, "下载情感失败 CSV", "sentiment_failures", "sentiment_failures_csv")
            show_table(sentiment_failures, height=440)
    with tabs[5]:
        if sentiment_timings.empty:
            st.info("当前文件没有 sentiment_timings。")
        else:
            download_csv(sentiment_timings, "下载情感耗时 CSV", "sentiment_timings", "sentiment_timings_csv")
            show_table(sentiment_timings, height=440)


def feedback_page() -> None:
    st.title("复核记录")
    target = st.session_state.get("feedback_target")
    feedback_form(target)
    frame = load_feedback()
    st.subheader("已保存记录")
    download_csv(frame, "下载复核记录 CSV", "review_feedback", "feedback_csv")
    show_table(frame, height=520)


def render_card_list(frame: pd.DataFrame, prefix: str) -> None:
    download_csv(frame, "下载当前筛选 CSV", f"{prefix}_filtered", f"{prefix}_csv")
    if frame.empty:
        st.info("当前筛选下没有评论。")
        return
    page_size = st.slider("展示条数", 10, 100, 30, step=10, key=f"{prefix}_page_size")
    for idx, (_, row) in enumerate(frame.head(page_size).iterrows()):
        review_card(row, idx, show_feedback=True)
    if len(frame) > page_size:
        st.info(f"已展示前 {page_size} 条，当前筛选共有 {len(frame)} 条。")


def render_sentiment_overview(data: dict[str, pd.DataFrame], frame: pd.DataFrame) -> None:
    summary = summarize_sentiment(data)
    metric_cards(
        [
            ("总处理评论数", f"{summary['total_count']:,}", f"当前筛选：{len(frame):,}"),
            ("平均情感分", f"{summary['average_score']:.1f}", "1-10 分"),
            ("规则 / LLM", f"{summary['rule_count']:,} / {summary['llm_fast_count']:,}", "rule 与 llm_fast"),
            ("详析 / 失败", f"{summary['detail_count']:,} / {summary['failed_count']:,}", summary.get("status", "") or ""),
        ]
    )
    left, right = st.columns(2)
    with left:
        st.plotly_chart(sentiment_distribution_chart(frame), width="stretch")
    with right:
        st.plotly_chart(sentiment_category_chart(frame, "praise_cn", "主要夸法"), width="stretch")


def sentiment_filter_controls(frame: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    col1, col2, col3, col4 = st.columns(4)
    result = frame
    with col1:
        if "sentiment_label_cn" in result.columns:
            labels = sorted(label for label in result["sentiment_label_cn"].fillna("").astype(str).unique() if label)
            selected = st.multiselect("情感分类构成", labels, key=f"{key_prefix}_labels")
            if selected:
                result = result[result["sentiment_label_cn"].isin(selected)]
    with col2:
        if "praise_cn" in result.columns:
            values = sorted(value for value in result["praise_cn"].fillna("").astype(str).unique() if value)
            selected = st.multiselect("主要夸法", values, key=f"{key_prefix}_praise")
            if selected:
                result = result[result["praise_cn"].isin(selected)]
    with col3:
        if "complaint_cn" in result.columns:
            values = sorted(value for value in result["complaint_cn"].fillna("").astype(str).unique() if value)
            selected = st.multiselect("主要吐槽", values, key=f"{key_prefix}_complaint")
            if selected:
                result = result[result["complaint_cn"].isin(selected)]
    with col4:
        if "sentiment_confidence" in result.columns:
            low_only = st.checkbox("只看低置信", key=f"{key_prefix}_low_confidence")
            if low_only:
                result = result[pd.to_numeric(result["sentiment_confidence"], errors="coerce").fillna(0) == 1]
    toggles = st.columns(2)
    with toggles[0]:
        if "ai_candidate" in result.columns:
            ai_only = st.checkbox("只看 AI 候选", key=f"{key_prefix}_ai_only")
            if ai_only:
                result = result[result["ai_candidate"].astype(bool)]
    with toggles[1]:
        if "sentiment_evidence" in result.columns:
            detail_only = st.checkbox("只看有详析", key=f"{key_prefix}_detail_only")
            if detail_only:
                result = result[result["sentiment_evidence"].fillna("").astype(str).str.strip().ne("")]
    return result


def _rate(numerator: object, denominator: object) -> str:
    numerator_value = pd.to_numeric(numerator, errors="coerce")
    denominator_value = pd.to_numeric(denominator, errors="coerce")
    numerator_value = 0.0 if pd.isna(numerator_value) else float(numerator_value)
    denominator_value = 0.0 if pd.isna(denominator_value) else float(denominator_value)
    return f"{numerator_value / denominator_value:.1%}" if denominator_value else "0.0%"


if __name__ == "__main__":
    main()
