from __future__ import annotations

import html
from textwrap import dedent

import streamlit as st


LEVEL_CLASS = {"A": "badge-a", "B": "badge-b", "C": "badge-c", "D": "badge-d", "": "badge-empty"}


def inject_css() -> None:
    markup = """
        <style>
        :root {
            color-scheme: light dark;
            --tc-surface: #ffffff;
            --tc-surface-muted: #f8fafc;
            --tc-border: #e2e8f0;
            --tc-text: #0f172a;
            --tc-muted: #64748b;
            --tc-accent: #2563eb;
            --tc-badge-empty-bg: #e5e7eb;
            --tc-badge-empty-text: #475569;
            --tc-badge-green-bg: #dcfce7;
            --tc-badge-green-text: #166534;
            --tc-badge-gray-bg: #f1f5f9;
            --tc-badge-gray-text: #334155;
            --tc-badge-red-bg: #fee2e2;
            --tc-badge-red-text: #991b1b;
        }

        @media (prefers-color-scheme: dark) {
            :root {
                --tc-surface: #161b22;
                --tc-surface-muted: #0f172a;
                --tc-border: #334155;
                --tc-text: #e5e7eb;
                --tc-muted: #a3b2c7;
                --tc-accent: #60a5fa;
                --tc-badge-empty-bg: #334155;
                --tc-badge-empty-text: #e2e8f0;
                --tc-badge-green-bg: #14532d;
                --tc-badge-green-text: #dcfce7;
                --tc-badge-gray-bg: #334155;
                --tc-badge-gray-text: #e2e8f0;
                --tc-badge-red-bg: #7f1d1d;
                --tc-badge-red-text: #fee2e2;
            }
        }

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

        [data-testid="stSidebar"] {background: var(--tc-surface-muted);}
        h1, h2, h3 {letter-spacing: 0;}
        .muted {color:var(--tc-muted); font-size: 13px;}
        .metric-grid {display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:12px; margin: 12px 0 18px;}
        .metric-card {border:1px solid var(--tc-border); border-radius:8px; background:var(--tc-surface); padding:14px 16px;}
        .metric-label {font-size:12px; color:var(--tc-muted); margin-bottom:8px;}
        .metric-value {font-size:26px; color:var(--tc-text); font-weight:700; line-height:1.1;}
        .metric-help {font-size:12px; color:var(--tc-muted); margin-top:6px;}
        .review-card {border:1px solid var(--tc-border); border-radius:8px; padding:16px; margin-bottom:12px; background:var(--tc-surface);}
        .review-card.strong {border-color:var(--tc-accent); box-shadow: inset 3px 0 0 var(--tc-accent);}
        .review-title {font-size:13px; font-weight:700; color:var(--tc-text); margin-bottom:6px;}
        .review-text {font-size:15px; line-height:1.7; color:var(--tc-text); margin: 8px 0;}
        .meta-text {font-size:12px; color:var(--tc-muted); line-height:1.6;}
        .tag-row {display:flex; gap:6px; flex-wrap:wrap; margin: 8px 0;}
        .badge {display:inline-flex; align-items:center; min-height:22px; padding:2px 8px; border-radius:999px; font-size:12px; font-weight:650;}
        .badge-a {background:#1d4ed8; color:white;}
        .badge-b {background:#2563eb; color:white;}
        .badge-c {background:#b45309; color:white;}
        .badge-d {background:#64748b; color:white;}
        .badge-empty {background:var(--tc-badge-empty-bg); color:var(--tc-badge-empty-text);}
        .badge-green {background:var(--tc-badge-green-bg); color:var(--tc-badge-green-text);}
        .badge-gray {background:var(--tc-badge-gray-bg); color:var(--tc-badge-gray-text);}
        .badge-red {background:var(--tc-badge-red-bg); color:var(--tc-badge-red-text);}
        .detail-box {border:1px solid var(--tc-border); border-radius:8px; background:var(--tc-surface); color:var(--tc-text); padding:14px 16px;}
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
