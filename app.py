from __future__ import annotations

import sys


TRACKER_COMMANDS = {
    "init-project",
    "update",
    "reanalyze",
    "backfill-sentiment",
}


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in TRACKER_COMMANDS:
        from tracker import main as tracker_main

        return tracker_main(sys.argv[1:])

    # app.py is re-executed for every Streamlit session and rerun, while
    # imported modules are cached process-wide. Page configuration and global
    # CSS must therefore run here instead of only at tracker_ui import time.
    import streamlit as st

    from ui.styles import inject_css

    st.set_page_config(page_title="消费者反馈洞察", layout="wide")
    inject_css()

    from tracker_ui import main as tracker_main

    tracker_main()
    return 0


if __name__ == "__main__":
    status = main()
    if len(sys.argv) > 1 and sys.argv[1] in TRACKER_COMMANDS:
        raise SystemExit(status)
