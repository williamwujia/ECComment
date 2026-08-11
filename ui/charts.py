from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


COLOR_BLUE = "#3b82f6"
COLOR_GRAY = "#94a3b8"
COLOR_ORANGE = "#f59e0b"
COLOR_GREEN = "#22c55e"
COLOR_RED = "#ef4444"


def vertical_axis_title(text: str) -> str:
    return "<br>".join(text)


def with_vertical_y_title(fig: go.Figure, title: str) -> go.Figure:
    margin = fig.layout.margin.to_plotly_json() if fig.layout.margin else {}
    margin["l"] = max(int(margin.get("l") or 0), 86)
    fig.update_layout(margin=margin)
    fig.update_layout(yaxis_title="", yaxis={"title": {"text": ""}})
    fig.update_yaxes(title_text="", title={"text": ""}, automargin=True)
    fig.add_annotation(
        xref="paper",
        yref="paper",
        x=-0.15,
        y=0.5,
        text=vertical_axis_title(title),
        showarrow=False,
        align="center",
        xanchor="center",
        yanchor="middle",
        textangle=0,
        font={"size": 12},
    )
    return fig


def funnel_chart(summary: dict) -> go.Figure:
    fig = go.Figure(
        go.Funnel(
            y=["商品评论", "购前决策评论", "AI 候选评论", "A 级强证据评论"],
            x=[
                summary.get("review_count", summary.get("total", 0)),
                summary.get("pre_purchase", 0),
                summary.get("ai_candidates", 0),
                summary.get("a_level", 0),
            ],
            marker={"color": [COLOR_GRAY, "#64748b", COLOR_BLUE, "#60a5fa"]},
        )
    )
    return with_vertical_y_title(
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10)),
        "商品评论阶段",
    )


def evidence_bar(content: pd.DataFrame) -> go.Figure:
    levels = ["A", "B", "C", "D"]
    counts = content.get("evidence_level", pd.Series(dtype=str)).value_counts()
    frame = pd.DataFrame({"level": levels, "count": [int(counts.get(level, 0)) for level in levels]})
    fig = px.bar(
        frame,
        x="count",
        y="level",
        orientation="h",
        color="level",
        color_discrete_map={"A": "#2563eb", "B": "#60a5fa", "C": COLOR_ORANGE, "D": COLOR_GRAY},
        labels={"count": "数量", "level": ""},
    )
    return with_vertical_y_title(
        fig.update_layout(height=280, showlegend=False, margin=dict(l=10, r=10, t=20, b=10)),
        "证据等级",
    )


def product_rank_chart(product_summary: pd.DataFrame, metric: str = "ai_candidate_count") -> go.Figure:
    if product_summary.empty or metric not in product_summary.columns:
        frame = pd.DataFrame({"product_title": [], metric: []})
    else:
        frame = product_summary.sort_values(metric, ascending=False).head(10).copy()
    fig = px.bar(
        frame,
        x=metric,
        y="product_title",
        orientation="h",
        color_discrete_sequence=[COLOR_BLUE],
        labels={metric: "数量", "product_title": ""},
    )
    return with_vertical_y_title(
        fig.update_layout(height=420, showlegend=False, margin=dict(l=10, r=10, t=20, b=10), yaxis={"categoryorder": "total ascending"}),
        "商品",
    )


def keyword_rank_chart(keyword_summary: pd.DataFrame) -> go.Figure:
    if keyword_summary.empty or "hit_count" not in keyword_summary.columns:
        frame = pd.DataFrame({"keyword": [], "hit_count": []})
    else:
        frame = keyword_summary.sort_values("hit_count", ascending=False).head(20).copy()
    fig = px.bar(
        frame,
        x="hit_count",
        y="keyword",
        orientation="h",
        color_discrete_sequence=[COLOR_BLUE],
        labels={"hit_count": "命中数", "keyword": ""},
    )
    return with_vertical_y_title(
        fig.update_layout(height=620, showlegend=False, margin=dict(l=10, r=10, t=20, b=10), yaxis={"categoryorder": "total ascending"}),
        "关键词",
    )


def monthly_trend_chart(month_summary: pd.DataFrame) -> go.Figure:
    if month_summary.empty or "review_month" not in month_summary.columns:
        frame = pd.DataFrame(
            {
                "review_month": [],
                "review_count": [],
                "pre_purchase_decision_count": [],
                "ai_candidate_count": [],
            }
        )
    else:
        frame = month_summary.sort_values("review_month").copy()
        if "pre_purchase_decision_count" not in frame.columns:
            frame["pre_purchase_decision_count"] = 0
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=frame.get("review_month", []),
            y=frame.get("review_count", []),
            name="评论数",
            marker_color=COLOR_GRAY,
        )
    )
    fig.add_trace(
        go.Bar(
            x=frame.get("review_month", []),
            y=frame.get("pre_purchase_decision_count", []),
            name="购前决策评论",
            marker_color=COLOR_GREEN,
        )
    )
    fig.add_trace(
        go.Bar(
            x=frame.get("review_month", []),
            y=frame.get("ai_candidate_count", []),
            name="AI 候选数",
            marker_color=COLOR_RED,
        )
    )
    fig.update_layout(
        barmode="group",
        height=360,
        margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation="h"),
    )
    return with_vertical_y_title(fig, "评论数")


def sentiment_distribution_chart(frame: pd.DataFrame) -> go.Figure:
    labels = [("P", "正向"), ("N", "负向"), ("M", "混合"), ("Z", "中性")]
    if frame.empty or "sentiment_label" not in frame.columns:
        counts = {}
    else:
        counts = frame["sentiment_label"].fillna("").astype(str).value_counts().to_dict()
    data = pd.DataFrame(
        {
            "sentiment_label": [code for code, _label in labels],
            "情感分类构成": [label for _code, label in labels],
            "count": [int(counts.get(code, 0)) for code, _label in labels],
        }
    )
    fig = px.bar(
        data,
        x="count",
        y="情感分类构成",
        orientation="h",
        color="sentiment_label",
        color_discrete_map={"P": COLOR_GREEN, "N": COLOR_RED, "M": COLOR_ORANGE, "Z": COLOR_GRAY},
        labels={"count": "数量", "sentiment_label": "情感代码", "情感分类构成": ""},
    )
    return with_vertical_y_title(
        fig.update_layout(height=280, showlegend=False, margin=dict(l=10, r=10, t=20, b=10), yaxis={"categoryorder": "total ascending"}),
        "情感分类构成",
    )


def sentiment_category_chart(frame: pd.DataFrame, column: str, title_column: str | None = None) -> go.Figure:
    label_column = title_column or column
    if frame.empty or column not in frame.columns:
        data = pd.DataFrame({label_column: [], "count": []})
    else:
        values = frame[column].fillna("").astype(str)
        values = values[values.str.strip().ne("")]
        data = values.value_counts().head(15).reset_index()
        data.columns = [label_column, "count"]
    fig = px.bar(
        data,
        x="count",
        y=label_column,
        orientation="h",
        color_discrete_sequence=[COLOR_BLUE],
        labels={"count": "数量", label_column: ""},
    )
    return with_vertical_y_title(
        fig.update_layout(height=420, showlegend=False, margin=dict(l=10, r=10, t=20, b=10), yaxis={"categoryorder": "total ascending"}),
        label_column,
    )
