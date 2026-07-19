from __future__ import annotations

import html
from textwrap import dedent

import streamlit as st


LEVEL_CLASS = {"A": "badge-a", "B": "badge-b", "C": "badge-c", "D": "badge-d", "": "badge-empty"}


def inject_css() -> None:
    markup = """
        <style>
        /* Streamlit 1.58 defaults the actual content column to 736px.
           Make the whole main layout fluid, not just its outer shell. */
        [data-testid="stMain"] {
            width: 100%;
            align-items: stretch;
        }

        [data-testid="stMainBlockContainer"],
        .block-container {
            box-sizing: border-box;
            width: 100%;
            min-width: 0;
            max-width: none !important;
            align-self: stretch;
            flex: 1 1 auto;
            margin-left: 0;
            margin-right: 0;
            padding: 2rem clamp(1rem, 2.5vw, 3rem) 2.5rem;
        }

        [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"],
        .block-container > [data-testid="stVerticalBlock"] {
            width: 100%;
            min-width: 0;
            max-width: none !important;
        }

        [data-testid="stSidebar"] {background: #f8fafc;}
        h1, h2, h3 {letter-spacing: 0;}
        .muted {color:#64748b; font-size: 13px;}
        .metric-grid {display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:12px; margin: 12px 0 18px;}
        .metric-card {border:1px solid #e5e7eb; border-radius:8px; background:#fff; padding:14px 16px;}
        .metric-label {font-size:12px; color:#64748b; margin-bottom:8px;}
        .metric-value {font-size:26px; color:#0f172a; font-weight:700; line-height:1.1;}
        .metric-help {font-size:12px; color:#64748b; margin-top:6px;}
        .review-card {border:1px solid #e5e7eb; border-radius:8px; padding:16px; margin-bottom:12px; background:#ffffff;}
        .review-card.strong {border-color:#1e3a8a; box-shadow: inset 3px 0 0 #1e3a8a;}
        .review-title {font-size:13px; font-weight:700; color:#0f172a; margin-bottom:6px;}
        .review-text {font-size:15px; line-height:1.7; color:#111827; margin: 8px 0;}
        .meta-text {font-size:12px; color:#64748b; line-height:1.6;}
        .tag-row {display:flex; gap:6px; flex-wrap:wrap; margin: 8px 0;}
        .badge {display:inline-flex; align-items:center; min-height:22px; padding:2px 8px; border-radius:999px; font-size:12px; font-weight:650;}
        .badge-a {background:#1e3a8a; color:white;}
        .badge-b {background:#2563eb; color:white;}
        .badge-c {background:#f59e0b; color:white;}
        .badge-d {background:#94a3b8; color:white;}
        .badge-empty {background:#e5e7eb; color:#475569;}
        .badge-green {background:#dcfce7; color:#166534;}
        .badge-gray {background:#f1f5f9; color:#334155;}
        .badge-red {background:#fee2e2; color:#991b1b;}
        .detail-box {border:1px solid #e5e7eb; border-radius:8px; background:#fff; padding:14px 16px;}
        @media (max-width: 900px) {.metric-grid {grid-template-columns: repeat(2, minmax(0, 1fr));}}
        @media (max-width: 560px) {.metric-grid {grid-template-columns: 1fr;}}
        </style>
        """
    if hasattr(st, "html"):
        st.html(markup)
    else:
        st.markdown(markup, unsafe_allow_html=True)


def esc(value: object) -> str:
    return html.escape(str(value or ""))


def badge(label: str, kind: str = "gray") -> str:
    css = LEVEL_CLASS.get(kind, f"badge-{kind}")
    return f'<span class="badge {css}">{esc(label)}</span>'


def level_badge(level: object) -> str:
    text = str(level or "").strip().upper()
    return badge(f"证据 {text or '未标注'}", text)


def metric_cards(cards: list[tuple[str, str, str]]) -> None:
    card_html = [
        (
            '<div class="metric-card">'
            f'<div class="metric-label">{esc(label)}</div>'
            f'<div class="metric-value">{esc(value)}</div>'
            f'<div class="metric-help">{esc(help_text)}</div>'
            "</div>"
        )
        for label, value, help_text in cards
    ]
    markup = dedent(f"""
    <div class="metric-grid">{''.join(card_html)}</div>
    """).strip()
    if hasattr(st, "html"):
        st.html(markup)
    else:
        st.markdown(markup, unsafe_allow_html=True)
