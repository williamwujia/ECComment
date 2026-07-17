from __future__ import annotations

import re

import pandas as pd


def source_file_name(value: object) -> str:
    """Return only the filename portion of a source path from any OS."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    text = str(value).strip()
    if not text:
        return ""
    return re.split(r"[\\/]+", text)[-1]
