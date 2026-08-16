from __future__ import annotations

import streamlit as st

from ui.styles import inject_css


def main() -> int:
    st.set_page_config(page_title="电商评论图片剥离", layout="wide")
    inject_css()
    from review_assets_ui import main as assets_main

    assets_main()
    return 0


if __name__ == "__main__":
    main()
