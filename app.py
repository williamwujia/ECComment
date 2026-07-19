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

    from tracker_ui import main as tracker_main

    tracker_main()
    return 0


if __name__ == "__main__":
    status = main()
    if len(sys.argv) > 1 and sys.argv[1] in TRACKER_COMMANDS:
        raise SystemExit(status)
